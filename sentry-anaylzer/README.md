# sentry异常分析mcp server


## 使用

```json

"sentry-analyzer": {
  "autoApprove": [],
  "disabled": false,
  "timeout": 60,
  "command": "python3",
  "args": [
    "/Users/name/xxx/MCP/sentry-analyzer/src/main.py",
    "--auth-token",
    "", // Sentry API token
    "--org",
    "sentry", // Sentry组织名称
    "--project_id",
    "8" // Sentry项目ID
  ],
  "transportType": "stdio"
},

```

## Tools

### list_projects

获取所有Sentry项目列表

### list_organizations

获取所有Sentry组织列表

### get_top_issues

获取项目中出现频率最高的未解决异常

### analyze_issue

分析特定异常并提供详细信息，输入异常详情url即可
