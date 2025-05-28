import anyio
import click
from typing import Optional, List
import mcp.types as types
import os
import re
from mcp.server.lowlevel import Server

# 提示词模版
PROMPT_TEMPLATE = """
根据以下信息生成 Flutter 单元测试代码：
1. 文件名：{file_name}
2. 类名：{class_name}
3. 依赖关系：{dependencies}
4. 其他信息：{other_info}

要求：
1. 使用Flutter test单元测试库，mockito库用来进行模拟数据
2. 属性和方法的断言覆盖率达到100%
3. 包括合适的setup和teardown方法
4. 测试所有的public方法、属性
5. 使用group块来组织不同的逻辑，测试之间需要重置模拟对象
6. 明确测试意图
7. 测试用例脚本的名字为`{file_name}_test.dart`,test目录结构与lib原文件一致

测试涵盖的场景：
1. 同步方法：
    - 测试返回值
    - 测试状态改变
    - 使用不同的参数组合进行测试

2. 异步方法：
    - 测试成功完成路径
    - 测试错误/异常路径
    - 验证 async/await 的正确使用
    - 使用 expectLater 和completion matchers

3. 异常测试：
    - 使用 expect(() => ..., throwsA(isA())) 测试预期异常
    - 测试错误恢复机制
    - 测试错误传播
    - 测试超时场景

4. 边界条件：
    - 在适用的情况下使用空值进行测试
    - 使用空集合进行测试
    - 测试最大值/最小值场景
    - 测试特定于业务逻辑的边缘案例

5. 状态管理（使用flutter_bloc）
    - 测试初始化state
    - 方法调用后测试state
    - 测试状态转换，发出emit后的场景测试
    - 验证状态一致性
    - 并发测试，触发多个emit事件

6. 依赖注入和模拟
    - 使用Mockito模拟外部依赖
    - 验证所有依赖关系交互
    - 测试不同的依赖行为（成功、失败、特定响应）
    - 测试依赖关系边缘情况

测试文件应遵循标准 Dart 格式，顶部是导入，然后是模拟设置类，然后是测试用例。
"""

async def extract_file_info(file_content: str) -> dict:
    """从Dart文件内容中提取关键信息"""
    info = {
        'class_name': '',
        'dependencies': [],
        'methods': [],
        'imports': []
    }

    # 提取导入语句
    import_pattern = r'import\s+[\'"]([^\'"]+)[\'"];'
    imports = re.findall(import_pattern, file_content)
    info['imports'] = imports

    # 提取类名
    class_pattern = r'class\s+(\w+)(?:\s+extends|\s+implements|\s+with|\s*{)'
    class_matches = re.findall(class_pattern, file_content)
    if class_matches:
        info['class_name'] = class_matches[0]

    # 排除的关键字列表 - 这些不是方法名
    exclude_keywords = ['if', 'else', 'for', 'while', 'switch', 'case', 'return', 'break', 'continue']

    # 改进的方法提取 - 使用多个正则表达式捕获不同类型的方法
    methods = []

    # 1. 常规方法 (各种返回类型) - 添加了方法体开始的 { 确保匹配到完整方法
    regular_method = r'(?:@\w+\s+)*(?:static\s+)?(?:void|String|int|bool|double|num|Future|List|Map|Set|Stream|\w+)(?:<[^>]+>)?\s+(\w+)\s*\([^)]*\)\s*(?:async\s*)?{'
    methods.extend([m for m in re.findall(regular_method, file_content) if not m.startswith('_')])

    # 2. 构造函数
    if info['class_name']:
        constructor_pattern = r'(?:@\w+\s+)*(?:const\s+)?(?:factory\s+)?(' + re.escape(info['class_name']) + r'(?:\.\w+)?)\s*\([^)]*\)\s*(?::\s*[\w\s(),]+)?\s*{'
        methods.extend(re.findall(constructor_pattern, file_content))

    # 3. Getter/Setter - 也添加了方法体识别
    getter_pattern = r'(?:@\w+\s+)*(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+get\s+(\w+)\s*(?:=>|{)'
    setter_pattern = r'(?:@\w+\s+)*(?:static\s+)?set\s+(\w+)\s*\([^)]*\)\s*{'
    methods.extend([m for m in re.findall(getter_pattern, file_content) if not m.startswith('_')])
    methods.extend([m for m in re.findall(setter_pattern, file_content) if not m.startswith('_')])

    # 4. 操作符重载
    operator_pattern = r'(?:@\w+\s+)*(?:\w+(?:<[^>]+>)?)\s+operator\s+(\S+)\s*\([^)]*\)\s*{'
    operators = re.findall(operator_pattern, file_content)
    if operators:
        methods.extend([f"operator {op}" for op in operators])

    # 过滤掉控制流关键字等非方法名
    methods = [m for m in methods if m not in exclude_keywords]

    # 去除重复
    info['methods'] = list(set(methods))

    # 提取依赖
    dependencies = []
    for imp in imports:
        if 'package:' in imp:
            pkg = imp.split('package:')[1].split('/')[0]
            if pkg not in dependencies:
                dependencies.append(pkg)
    info['dependencies'] = dependencies
    return info


# path: str 要是用绝对路径
async def generate_unit_test(
    path: str,
    content: Optional[str] = None,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """根据文件路径或内容生成单元测试代码

    Args:
        path: 文件路径，如果不提供content则从此路径读取文件内容
        content: 可选，直接提供的文件内容，优先级高于path
    """
    try:
        file_content = content

        # 如果没有提供内容，则尝试从路径读取
        if file_content is None:
            # 转换为绝对路径
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                # 如果文件不存在，尝试从当前工作目录解析路径
                abs_path = os.path.abspath(os.path.join(os.getcwd(), path))
                if not os.path.exists(abs_path):
                    raise FileNotFoundError(f"File not found: {path}")

            # 读取文件内容
            with open(abs_path, 'r') as file:
                file_content = file.read()

        # 提取文件信息
        info = await extract_file_info(file_content)
        file_name = os.path.basename(path)

        # 准备其他信息字符串
        other_info = f"Methods: {', '.join(info['methods'])}\n"
        other_info += f"Imports: {', '.join(info['imports'])}"

        # 拼凑提示词
        prompt = PROMPT_TEMPLATE.format(
            file_name=file_name,
            class_name=info['class_name'],
            dependencies=", ".join(info['dependencies']),
            other_info=other_info,
        )
        # 拼凑出提示词
        return [types.TextContent(type="text", text=prompt)]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error generating unit test: {str(e)}")]


@click.command()
@click.option("--port", default=8010, help="Port to listen on for SSE")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type",
)
def main(port: int, transport: str) -> int:
    app = Server("flutter-unit-test")

    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        if name != "generateUnitTest":
            raise ValueError(f"Unknown tool: {name}")

        path = arguments.get("path", "")
        if not path and "content" not in arguments:
          raise ValueError("Missing required argument 'path' or 'content'")
        content = arguments.get("content", None)
        return await generate_unit_test(path, content=content)

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="generateUnitTest",
                description="根据提示词，生成 Flutter 单元测试代码",
                inputSchema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "代码路径",
                        },
                        "content": {
                            "type": "string",
                            "description": "代码内容，如果提供了此参数，则path参数将被忽略",
                        },
                    },
                },
            )
        ]

    print("Server starting...")
    print(f"Transport mode: {transport}")
    
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )

        import uvicorn

        uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    else:
        from mcp.server.stdio import stdio_server

        async def arun():
            async with stdio_server() as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )

        anyio.run(arun)

    return 0
