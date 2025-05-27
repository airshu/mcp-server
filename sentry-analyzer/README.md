# sentry异常分析mcp server


## 使用

```bash
# 创建独立的python虚拟环境
python -m venv .venv && source .venv/bin/activate

# 安装依赖
uv pip install -e .

# 使用stdio协议启动
uv run sentry-analyzer-sse --port 8011 --auth-token sntryu_xxxxxxxxxx --org sentry --project_id 8

# 构建whl文件
python -m build

# 安装到主python环境
/Users/xxx/.pyenv/shims/python3 -m install dist/sentry_analyzer_sse-0.1.0-py3-none-any.whl


# 配置cline_mcp_settings.json
"sentry-analyzer-sse": {
      "autoApprove": [],
      "disabled": false,
      "timeout": 60,
      "command": "sentry-analyzer",
      "args": [
        "--auth-token",
        "sntryu_xxxxxxxxxx",
        "--org",
        "sentry",
        "--project_id",
        "8"
      ],
      "transportType": "stdio"
    },





# 使用SSE协议
uv run sentry-analyzer-sse --transport sse --port 8011

# 指定sentry后台相关参数
uv run sentry-analyzer-sse --transport sse --port 8011 --auth-token sntryu_xxxxxxxxxx --org sentry --project_id 8

# cline_mcp_settings.json配置
"sentry-analyzer-sse": {
  "disabled": false,
  "timeout": 60,
  "url": "http://127.0.0.1:8011/sse",
  "transportType": "sse"
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
