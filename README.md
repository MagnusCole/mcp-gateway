# mcp-gateway

[![PyPI](https://img.shields.io/pypi/v/mcp-unify)](https://pypi.org/project/mcp-unify/)
[![License](https://img.shields.io/github/license/MagnusCole/mcp-gateway)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/mcp-unify)](https://pypi.org/project/mcp-unify/)

Unify multiple MCP servers behind a single endpoint. Lazy loading, auto-cleanup, Python plugins, role-based filtering.

## The Problem

If you use Claude Code or any MCP client with 3+ servers, you get:
- Multiple subprocesses (~50MB each)
- Duplicated config
- No centralized control
- No way to add custom Python tools without a full MCP server

## The Solution

`mcp-gateway` runs **one process** that proxies N MCP servers on-demand:

```
Claude Code / MCP Client
  │
  ▼
mcp-gateway (1 process)
  ├─ [plugin] Python @tool functions     ← in-process, 0 overhead
  ├─ [lazy]   filesystem-server          ← subprocess spawned on first call
  ├─ [lazy]   github-server              ← subprocess spawned on first call
  └─ [lazy]   playwright                 ← subprocess spawned on first call
      ↑
      5 min idle → auto-kill
```

## Install

```bash
pip install mcp-gateway
```

## Quick Start

### 1. Create `gateway.yaml`

```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
    enabled: false

idle_timeout: 300
```

### 2. Run

**stdio** (for Claude Code):
```bash
mcp-gateway stdio --config gateway.yaml
```

**SSE** (for remote clients):
```bash
mcp-gateway serve --config gateway.yaml --port 8765
```

### 3. Add to Claude Code

```json
{
  "mcpServers": {
    "gateway": {
      "command": "mcp-gateway",
      "args": ["stdio", "--config", "/path/to/gateway.yaml"]
    }
  }
}
```

## Python Plugins

Add custom tools with zero boilerplate:

```python
from mcp_gateway import tool

@tool(description="Add two numbers")
def add(a: float, b: float) -> float:
    return a + b
```

Reference in your config:

```yaml
plugins:
  - module: my_tools.calculator
```

Or register programmatically:

```python
from mcp_gateway import MCPGateway

gw = MCPGateway()
gw.register_tool(add)
await gw.serve_stdio()
```

Sync functions run via `asyncio.to_thread()`. Async functions run natively. Schemas are auto-generated from type hints.

## Role-Based Filtering

Control which tools each client sees:

```yaml
roles:
  admin: null        # all tools
  readonly: ["filesystem_*", "gateway_status"]
  developer: ["github_*", "filesystem_*", "gateway_*"]
```

Set the role via environment variable:

```bash
MCP_GATEWAY_ROLE=readonly mcp-gateway stdio
```

Uses glob patterns — `filesystem_*` matches all tools from the filesystem server.

## How It Works

1. **Lazy Loading**: Servers aren't started until a tool is called. Each server gets a `_<name>_connect` placeholder tool. Calling it spawns the subprocess and discovers real tool schemas via `session.list_tools()`.

2. **Auto-Cleanup**: A background task checks every 60s and kills server subprocesses idle for longer than `idle_timeout` (default: 5 min).

3. **Real Schemas**: Tool schemas are discovered from the actual server via the MCP SDK, not hardcoded. You always get accurate `inputSchema`.

4. **Plugin Tools**: Python functions decorated with `@tool` run in the gateway process. Type hints are introspected to generate JSON Schema automatically.

## API

```python
from mcp_gateway import MCPGateway, tool

# From YAML
gw = MCPGateway.from_config("gateway.yaml")

# Programmatic
gw = MCPGateway()
gw.register_tool(my_function, name="my_tool", description="...")

# Serve
await gw.serve_stdio()    # stdio mode
await gw.serve_sse()      # SSE mode on :8765

# Context manager
async with MCPGateway() as gw:
    await gw.serve_stdio()
```

## CLI

```
mcp-gateway serve [--config FILE] [--host HOST] [--port PORT]
mcp-gateway stdio [--config FILE]
mcp-gateway list  [--config FILE]
```

Config discovery: `--config` > `./gateway.yaml` > `./mcp-gateway.yaml`

## Requirements

- Python >= 3.10
- `mcp >= 1.0.0`
- `starlette >= 0.27.0`
- `uvicorn >= 0.23.0`
- `pyyaml >= 6.0`

## License

MIT
