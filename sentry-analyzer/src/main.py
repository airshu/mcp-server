import asyncio
from dataclasses import dataclass
from typing import List, Dict
import click
import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError

SENTRY_API_BASE = "https://sentry.domain.com/api/0/"

@dataclass
class SentryIssueData:
    title: str
    issue_id: str
    status: str
    level: str
    first_seen: str
    last_seen: str
    count: int
    stacktrace: str

    def to_text(self) -> str:
        return f"""
Sentry Issue: {self.title}
Issue ID: {self.issue_id}
Status: {self.status}
Level: {self.level}
First Seen: {self.first_seen}
Last Seen: {self.last_seen}
Event Count: {self.count}

{self.stacktrace}
        """

    def to_tool_result(self) -> List[types.TextContent]:
        return [types.TextContent(type="text", text=self.to_text())]

@dataclass
class ProjectListData:
    projects: List[Dict]

    def to_text(self) -> str:
        result = "项目列表:\n\n"
        for idx, project in enumerate(self.projects, 1):
            result += f"{idx}. {project['name']}\n"
            result += f"   项目ID: {project['slug']}\n"
            result += f"   状态: {project['status']}\n"
            result += f"   平台: {', '.join(project.get('platforms', ['未知']))}\n"
            result += f"   团队: {project.get('team', {}).get('name', '未分配')}\n"
            result += f"   最后更新: {project.get('dateCreated', '未知')}\n"
            result += f"   URL: https://sentry.domain.com/organizations/sentry/projects/{project['slug']}/\n\n"
        return result

    def to_tool_result(self) -> List[types.TextContent]:
        return [types.TextContent(type="text", text=self.to_text())]

@dataclass
class TopIssueData:
    issues: List[Dict]

    def to_text(self) -> str:
        result = "Top Issues:\n\n"
        for idx, issue in enumerate(self.issues, 1):
            result += f"{idx}. {issue['title']}\n"
            result += f"   ID: {issue['id']}\n"
            result += f"   URL: {issue['url']}\n"
            result += f"   Status: {issue['status']}\n"
            result += f"   Events: {issue['count']}\n"
            result += f"   First Seen: {issue['firstSeen']}\n"
            result += f"   Last Seen: {issue['lastSeen']}\n\n"
        return result

    def to_tool_result(self) -> List[types.TextContent]:
        return [types.TextContent(type="text", text=self.to_text())]

class SentryError(Exception):
    pass

def extract_issue_id(issue_id_or_url: str) -> str:
    """从URL中提取issue ID"""
    if not issue_id_or_url:
        raise SentryError("Missing issue_id_or_url argument")

    try:
        parts = issue_id_or_url.split("/")
        for i, part in enumerate(parts):
            if part == "issues" and i + 1 < len(parts):
                return parts[i + 1].split("?")[0]
        raise ValueError("Invalid URL format")
    except Exception:
        raise SentryError(f"Could not extract issue ID from URL: {issue_id_or_url}")

def create_stacktrace(latest_event: Dict) -> str:
    """创建格式化的堆栈跟踪信息"""
    stacktraces = []
    for entry in latest_event.get("entries", []):
        if entry.get("type") != "exception":
            continue

        exception_data = entry.get("data", {}).get("values", [])
        for exception in exception_data:
            exception_type = exception.get("type", "Unknown")
            exception_value = exception.get("value", "")
            stacktrace = exception.get("stacktrace", {})

            stacktrace_text = f"Exception: {exception_type}: {exception_value}\n\n"
            if stacktrace:
                stacktrace_text += "Stacktrace:\n"
                for frame in stacktrace.get("frames", []):
                    filename = frame.get("filename", "Unknown")
                    lineno = frame.get("lineNo", "?")
                    function = frame.get("function", "Unknown")
                    context = frame.get("context", [])

                    stacktrace_text += f"{filename}:{lineno} in {function}\n"
                    if context:
                        for ctx_line in context:
                            stacktrace_text += f"    {ctx_line[1]}\n"
                    stacktrace_text += "\n"

            stacktraces.append(stacktrace_text)

    return "\n".join(stacktraces) if stacktraces else "No stacktrace found"

async def handle_sentry_issue(
    http_client: httpx.AsyncClient, auth_token: str, org_slug: str, issue_id_or_url: str
) -> SentryIssueData:
    """处理单个Sentry问题"""
    try:
        issue_id = extract_issue_id(issue_id_or_url)

        # 获取问题详情
        response = await http_client.get(
            f"issues/{issue_id}/",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        if response.status_code == 401:
            raise McpError(types.ErrorData(code=401, message="Error: Unauthorized. Please check your authentication token."))
        response.raise_for_status()
        issue_data = response.json()

        # 获取最新事件
        events_response = await http_client.get(
            f"issues/{issue_id}/events/latest/",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        events_response.raise_for_status()
        event_data = events_response.json()

        stacktrace = create_stacktrace(event_data)

        return SentryIssueData(
            title=issue_data["title"],
            issue_id=issue_id,
            status=issue_data["status"],
            level=issue_data["level"],
            first_seen=issue_data["firstSeen"],
            last_seen=issue_data["lastSeen"],
            count=issue_data["count"],
            stacktrace=stacktrace
        )

    except SentryError as e:
        raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message=str(e)))
    except httpx.HTTPStatusError as e:
        raise McpError(types.ErrorData(code=e.response.status_code, message=f"Error fetching Sentry issue: {str(e)}"))
    except Exception as e:
        raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=f"An error occurred: {str(e)}"))

async def handle_top_issues(
    http_client: httpx.AsyncClient, auth_token: str, org_slug: str, project_id: str, limit: int = 10
) -> TopIssueData:
    """获取最常见的问题"""
    try:
        response = await http_client.get(
            f"projects/{org_slug}/{project_id}/issues/",
            params={
                "query": "is:unresolved",
                "sort": "freq",
                "limit": limit
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        if response.status_code == 401:
            raise McpError(types.ErrorData(code=401, message="Error: Unauthorized. Please check your authentication token."))
        response.raise_for_status()

        # 获取响应数据并打印详细结构
        issues = response.json()
        print("First issue structure:", issues[0] if issues else "No issues found")
        # 处理每个issue并添加完整URL
        processed_issues = []
        for issue in issues:
            issue_dict = dict(issue)  # 保留原始数据
            issue_dict['url'] = f"https://sentry.domain.com/organizations/sentry/issues/{issue['id']}/"  # 添加URL字段
            processed_issues.append(issue_dict)

        return TopIssueData(issues=processed_issues)

    except httpx.HTTPStatusError as e:
        raise McpError(types.ErrorData(code=e.response.status_code, message=f"Error fetching top issues: {str(e)}"))
    except Exception as e:
        raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=f"An error occurred: {str(e)}"))

async def handle_list_projects(http_client: httpx.AsyncClient, auth_token: str, org_slug: str) -> ProjectListData:
    """获取所有项目列表"""
    try:
        response = await http_client.get(
            f"projects/",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        print("Response status code:", response.status_code)
        print("Response headers:", response.headers)
        print("Response content:", response.content)

        if response.status_code == 401:
            raise McpError(types.ErrorData(code=401, message="Error: Unauthorized. Please check your authentication token."))
        response.raise_for_status()

        projects = response.json()
        return ProjectListData(projects=projects)

    except httpx.HTTPStatusError as e:
        raise McpError(types.ErrorData(code=e.response.status_code, message=f"Error fetching projects list: {str(e)}"))
    except Exception as e:
        raise McpError(types.ErrorData(code=types.INTERNAL_ERROR, message=f"An error occurred: {str(e)}"))

def create_server(auth_token: str, org_slug: str) -> Server:
    """创建并配置MCP服务器"""
    app = Server("sentry-analyzer")  # Match the server name in MCP settings
    http_client = httpx.AsyncClient(base_url=SENTRY_API_BASE, timeout=30.0)

    @app.list_tools()
    async def handle_list_tools() -> List[types.Tool]:
        return [
            types.Tool(
                name="get_top_issues",
                description="获取项目中出现频率最高的未解决异常",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "Sentry项目ID"
                        },
                        "limit": {
                            "type": "number",
                            "description": "返回的异常数量（默认10）",
                            "minimum": 1,
                            "maximum": 100
                        }
                    },
                    "required": ["project_id"]
                }
            ),
            types.Tool(
                name="list_projects",
                description="获取所有Sentry项目列表",
                inputSchema={
                    "type": "object",
                    "properties": {},
                }
            ),
            types.Tool(
                name="list_organizations",
                description="获取所有Sentry组织列表",
                inputSchema={
                    "type": "object",
                    "properties": {},
                }
            ),
            types.Tool(
                name="analyze_issue",
                description="分析特定异常并提供详细信息",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "issue_url": {
                            "type": "string",
                            "description": "Sentry异常URL"
                        }
                    },
                    "required": ["issue_url"]
                }
            )
        ]

    @app.call_tool()
    async def handle_call_tool(
        name: str, arguments: Dict | None
    ) -> List[types.TextContent]:
        if name == "get_top_issues":
            if not arguments:
                raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="Missing arguments"))
            project_id = arguments.get("project_id")
            if not project_id:
                raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="Missing project_id argument"))
            limit = int(arguments.get("limit", 10))
            try:
                print(f"Getting top issues for project {project_id}")
                result = await handle_top_issues(http_client, auth_token, org_slug, project_id, limit)
                print("Successfully retrieved top issues")
                return result.to_tool_result()
            except Exception as e:
                print(f"Error in get_top_issues: {str(e)}")
                raise

        elif name == "analyze_issue":
            if not arguments:
                raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="Missing arguments"))
            issue_url = arguments.get("issue_url")
            if not issue_url:
                raise McpError(types.ErrorData(code=types.INVALID_PARAMS, message="Missing issue_url argument"))
            result = await handle_sentry_issue(http_client, auth_token, org_slug, issue_url)
            return result.to_tool_result()

        elif name == "list_projects":
            result = await handle_list_projects(http_client, auth_token, org_slug)
            return result.to_tool_result()

        elif name == "list_organizations":
            # 处理组织列表的逻辑
            response = await http_client.get(
                f"organizations/",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            if response.status_code == 401:
                raise McpError(types.ErrorData(code=401, message="Error: Unauthorized. Please check your authentication token."))
            response.raise_for_status()
            organizations = response.json()
            org_list = [org["slug"] for org in organizations]
            return [types.TextContent(type="text", text="\n".join(org_list))]

        else:
            raise McpError(types.ErrorData(code=types.METHOD_NOT_FOUND, message=f"Unknown tool: {name}"))

    return app

@click.command()
@click.option(
    "--auth-token",
    envvar="SENTRY_AUTH_TOKEN",
    required=True,
    help="Sentry authentication token"
)
@click.option(
    "--org",
    envvar="SENTRY_ORG",
    required=True,
    help="Sentry organization slug"
)
@click.option(
    "--project_id",
    envvar="SENTRY_PROJECT_ID",
    required=False,
    help="Sentry project ID"
)
@click.option(
    "--port",
    envvar="PORT",
    default=8011,
    help="服务器端口号"
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(auth_token: str, org: str, project_id: str | None, port: int, transport: str) -> None:
    """启动MCP服务器"""
    print("Server starting...")
    print(f"Transport mode: {transport}")

    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route, Mount
        import uvicorn

        app = create_server(auth_token, org)
        print("Created server with name:", app.name)

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            print("Handling SSE request...")
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                try:
                    print("Running server...")
                    init_options = app.create_initialization_options()
                    print("Init options:", init_options)
                    await app.run(streams[0], streams[1], init_options)
                except Exception as e:
                    print("Error in handle_sse:", e)
                    import traceback
                    traceback.print_exc()
                    raise

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        print("Starting uvicorn...")
        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                server = create_server(auth_token, org)
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )

        asyncio.run(arun())

