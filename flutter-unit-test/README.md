
A simple MCP server for running unit tests in Flutter.

## Usage

Start the server using either stdio (default) or SSE transport:

```bash

# 安装
uv pip install -e .

# Using stdio transport (default)
uv run flutter-unit-test

# Using SSE transport on custom port
uv run flutter-unit-test --transport sse --port 8010
```

