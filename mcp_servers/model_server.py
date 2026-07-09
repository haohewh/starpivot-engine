"""MCP Server: 模型市场 — DeepSeek/通义/豆包/Kimi/MiniMax/硅基流动"""
import sys, json, logging
sys.path.insert(0, "/opt/starpivot")
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("model_server")

app = Server("model_server")

TOOLS = [
    Tool(name="deepseek_chat", description="调用 DeepSeek 对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
    Tool(name="qwen_chat", description="调用通义千问对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
    Tool(name="kimi_chat", description="调用 Kimi 对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
    Tool(name="minimax_chat", description="调用 MiniMax 对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
    Tool(name="siliconflow_chat", description="调用硅基流动（SiliconFlow）对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
    Tool(name="doubao_chat", description="调用豆包（Doubao）对话", inputSchema={"type":"object","properties":{"prompt":{"type":"string"}},"required":["prompt"]}),
]

@app.list_tools()
async def list_tools():
    return TOOLS

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    from core.starpivot.models.market import ModelMarket
    market = ModelMarket()
    model_map = {"deepseek_chat":"deepseek","qwen_chat":"qwen","kimi_chat":"kimi","minimax_chat":"minimax","siliconflow_chat":"siliconflow","doubao_chat":"doubao"}
    model = model_map.get(name, "deepseek")
    result = market.query(model, arguments.get("prompt",""))
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

async def main():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
