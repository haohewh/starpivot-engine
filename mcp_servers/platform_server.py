"""MCP Server: 平台集成 — 微信/抖音/剪映/钉钉/飞书/小红书/腾讯会议/支付宝/数字人民币"""
import sys, json, logging
sys.path.insert(0, "/opt/starpivot")
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("platform_server")

app = Server("platform_server")

TOOLS = [
    # 已有
    Tool(name="wechat_send_msg", description="Send WeChat message / 发送微信消息", inputSchema={"type":"object","properties":{"msg":{"type":"string"},"to":{"type":"string"}},"required":["msg"]}),
    Tool(name="dingtalk_send_msg", description="Send DingTalk message / 发送钉钉消息", inputSchema={"type":"object","properties":{"msg":{"type":"string"}},"required":["msg"]}),
    Tool(name="xiaohongshu_search", description="Search Xiaohongshu (RED) posts / 搜索小红书笔记", inputSchema={"type":"object","properties":{"keyword":{"type":"string"}},"required":["keyword"]}),
    # 抖音
    Tool(name="douyin_upload", description="Upload video to Douyin (TikTok China) / 上传视频到抖音", inputSchema={"type":"object","properties":{"video_path":{"type":"string"},"title":{"type":"string"},"description":{"type":"string"},"hashtags":{"type":"array","items":{"type":"string"}}},"required":["video_path"]}),
    Tool(name="douyin_get_data", description="Get Douyin video data / 获取抖音视频数据", inputSchema={"type":"object","properties":{"video_id":{"type":"string"}},"required":["video_id"]}),
    # 剪映
    Tool(name="jianying_create", description="Create Jianying (CapCut) draft / 创建剪映草稿", inputSchema={"type":"object","properties":{"title":{"type":"string"},"template_id":{"type":"string"},"materials":{"type":"array","items":{"type":"object"}}},"required":["title"]}),
    Tool(name="jianying_export", description="Export video from Jianying (CapCut) / 从剪映导出视频", inputSchema={"type":"object","properties":{"draft_id":{"type":"string"},"quality":{"type":"string"},"format":{"type":"string"}},"required":["draft_id"]}),
    # 飞书
    Tool(name="feishu_send_msg", description="Send Feishu (Lark) message / 发送飞书消息", inputSchema={"type":"object","properties":{"receive_id":{"type":"string"},"content":{"type":"string"},"msg_type":{"type":"string"}},"required":["receive_id","content"]}),
    Tool(name="feishu_get_doc", description="Get Feishu document content / 获取飞书文档内容", inputSchema={"type":"object","properties":{"document_id":{"type":"string"}},"required":["document_id"]}),
    # 腾讯会议
    Tool(name="meeting_create", description="Create Tencent Meeting / 创建腾讯会议", inputSchema={"type":"object","properties":{"title":{"type":"string"},"duration_minutes":{"type":"integer","default":60}},"required":["title"]}),
    Tool(name="meeting_join_url", description="Get Tencent Meeting join URL / 获取腾讯会议入会链接", inputSchema={"type":"object","properties":{"meeting_id":{"type":"string"},"user_display_name":{"type":"string"}},"required":["meeting_id"]}),
]

# 平台工具名 -> (平台名, 动作名) 映射
_PLATFORM_MAP = {
    # 已有
    "xiaohongshu_search": ("xiaohongshu", "search"),
    # 抖音
    "douyin_upload": ("douyin", "upload_video"),
    "douyin_get_data": ("douyin", "get_video_data"),
    # 剪映
    "jianying_create": ("jianying", "create_draft"),
    "jianying_export": ("jianying", "export_video"),
    # 飞书
    "feishu_send_msg": ("feishu", "send_message"),
    "feishu_get_doc": ("feishu", "get_document"),
    # 腾讯会议
    "meeting_create": ("meeting", "create_meeting"),
    "meeting_join_url": ("meeting", "get_join_url"),
}

@app.list_tools()
async def list_tools():
    return TOOLS

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    from core.starpivot.platform.bus import PlatformBus
    bus = PlatformBus()

    if name == "wechat_send_msg":
        result = await bus.wechat.send_message(arguments.get("to",""), arguments.get("msg",""))
    elif name == "dingtalk_send_msg":
        result = await bus.dingtalk.send_message(arguments.get("to",""), arguments.get("msg",""))
    elif name == "xiaohongshu_search":
        result = bus.call("xiaohongshu", "search", keyword=arguments.get("keyword",""))
    elif name in _PLATFORM_MAP:
        platform, action = _PLATFORM_MAP[name]
        client = getattr(bus, platform, None)
        if client is None:
            result = {"success": False, "error": f"未知平台: {platform}"}
        else:
            method = getattr(client, action, None)
            if method is None:
                result = {"success": False, "error": f"平台 {platform} 不支持操作: {action}"}
            else:
                try:
                    result = await method(**arguments) if hasattr(method, "__await__") else method(**arguments)
                    if not isinstance(result, dict):
                        result = {"success": True, "data": result}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
    else:
        result = {"success": False, "error": f"未知工具: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

async def main():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
