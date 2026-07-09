"""MCP Server: 支付系统 — 支付宝/微信支付/数字人民币"""
import sys, json, logging
sys.path.insert(0, "/opt/starpivot")
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("payment_server")

app = Server("payment_server")

TOOLS = [
    Tool(name="alipay_pay", description="支付宝支付（扫码/转账）",
         inputSchema={"type":"object","properties":{"amount":{"type":"number","description":"金额"},"to":{"type":"string","description":"收款方"},"note":{"type":"string","description":"备注"}},"required":["amount","to"]}),
    Tool(name="alipay_refund", description="支付宝退款",
         inputSchema={"type":"object","properties":{"order_id":{"type":"string","description":"订单号"},"amount":{"type":"number","description":"退款金额"}},"required":["order_id"]}),
    Tool(name="alipay_query", description="支付宝交易查询",
         inputSchema={"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}),
    Tool(name="wechat_pay", description="微信支付",
         inputSchema={"type":"object","properties":{"amount":{"type":"number"},"to":{"type":"string"},"note":{"type":"string"}},"required":["amount","to"]}),
    Tool(name="wechat_refund", description="微信退款",
         inputSchema={"type":"object","properties":{"order_id":{"type":"string"},"amount":{"type":"number"}},"required":["order_id"]}),
    Tool(name="wechat_query", description="微信交易查询",
         inputSchema={"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}),
    Tool(name="e_cny_pay", description="数字人民币支付",
         inputSchema={"type":"object","properties":{"amount":{"type":"number"},"to":{"type":"string"}},"required":["amount","to"]}),
    Tool(name="e_cny_query", description="数字人民币余额/交易查询",
         inputSchema={"type":"object","properties":{"account":{"type":"string"}},"required":[]}),
]

@app.list_tools()
async def list_tools():
    return TOOLS

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    logger.info("支付请求: %s %s", name, arguments)
    # TODO: 接入真实支付网关
    return [TextContent(type="text", text=json.dumps({
        "success": True, "order_id": f"ORDER_{name}_{hash(str(arguments))%100000:05d}",
        "output": f"{name} 处理成功（待接入真实网关）"
    }, ensure_ascii=False))]

async def main():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
