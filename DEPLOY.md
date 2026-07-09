# Deployment Guide (部署指南)

## Requirements

- Python 3.10+
- pip

## Quick Deploy

### 1. Clone & Install

```bash
git clone https://github.com/haohewh/starpivot-engine.git
cd starpivot-engine
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```ini
DEEPSEEK_API_KEY=sk-xxx          # Required for chat/model calls
MINIMAX_API_KEY=xxx              # Required for TTS/ASR
FIRECRAWL_API_KEY=xxx            # Required for web search
DASHSCOPE_API_KEY=xxx            # Optional: image generation
```

### 3. Verify Installation

```bash
python3 -c "
from starpivot.registry import ToolRegistry
registry = ToolRegistry()
count = registry.discover_servers('mcp_servers/')
print(f'{count} MCP Servers loaded')
"
```

Expected output: `17 MCP Servers loaded`

### 4. Run Engine

```python
import asyncio
from starpivot import StarPivotEngine, ToolRegistry

async def main():
    registry = ToolRegistry()
    registry.discover_servers("mcp_servers/")
    engine = StarPivotEngine(registry)

    result = await engine.execute("web_search", {"query": "Hello World"})
    print(result.output)

    await engine.close()

asyncio.run(main())
```

---

## Production Deployment (生产部署)

### Option A: systemd Service (Linux)

Create `/etc/systemd/system/starpivot.service`:

```ini
[Unit]
Description=StarPivot Engine
After=network.target

[Service]
Type=simple
User=starpivot
WorkingDirectory=/opt/starpivot-engine
ExecStart=/opt/starpivot-engine/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable starpivot
sudo systemctl start starpivot
```

### Option B: Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python3", "agent_loop.py"]
```

```bash
docker build -t starpivot-engine .
docker run -d -p 8000:8000 --env-file .env starpivot-engine
```

---

## MCP Server Management

### Add a New MCP Server

1. Create `mcp_servers/my_server.json`:

```json
{
  "name": "my_server",
  "transport": "stdio",
  "command": "python3",
  "args": ["-m", "mcp_servers.my_server"],
  "tools": ["my_tool"],
  "timeout": 15,
  "enabled": true
}
```

2. Create `mcp_servers/my_server.py`:

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

async def main():
    server = Server("my_server")

    @server.list_tools()
    async def list_tools():
        return [Tool(
            name="my_tool",
            description="Description of my tool / 工具描述",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "Parameter 1 / 参数1"}
                },
                "required": ["param1"]
            }
        )]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "my_tool":
            return [TextContent(type="text", text=f"Result: {arguments}")]
        raise ValueError(f"Unknown tool: {name}")

    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

3. Restart engine — new Server auto-discovered.

---

## Directory Structure

```
/opt/starpivot-engine/       ← Recommended production path
├── mcp_servers/             ← MCP Server JSON + Python
├── starpivot/               ← Engine core
│   ├── engine.py
│   ├── registry.py
│   ├── security/
│   └── ...
├── .env                     ← API keys (never commit!)
├── requirements.txt
└── agent_loop.py            ← Entry point
```

## Security Notes

1. **Never commit `.env`** — it's in `.gitignore`
2. **API keys in environment variables only** — no hardcoded keys in code
3. **Code sandbox blocks 25+ dangerous modules** — os, socket, subprocess, exec, etc.
4. **SSH/terminal access permanently blocked** for AI agents
5. **File operations sandboxed** — only within `/opt/starpivot-engine/user_files/{user_id}/`
