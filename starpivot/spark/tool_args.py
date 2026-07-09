"""工具参数模板 — 为测试提供正确的默认参数。

从 stability_test.py 中提取，供 utility_test / speed_test / integration_test 共用。
"""
from __future__ import annotations

from typing import Any

# ── 工具参数模板 ───────────────────────────────────
# 为每个工具提供正确的默认参数，避免测试因"缺少必需参数"而失败。
# 不在字典中的工具将被跳过（标记为 skip）。
TOOL_ARGS: dict[str, dict[str, Any]] = {
    # ── 搜索 ──
    "agent_reach_search": {"query": "测试新闻"},
    "agent_reach_web_read": {"url": "https://example.com"},
    "web_search": {"query": "测试"},
    "read_hot_news": {"dummy": ""},
    "web_crawl": {"url": "https://example.com"},
    # ── 文件 ──
    "read_file": {"path": "/tmp/test.txt"},
    "read_user_file": {"filepath": "test.txt"},
    "write_file": {"path": "/tmp/test.txt", "content": "test"},
    "list_files": {"path": "."},
    # ── 数据库 ──
    "query_database": {"sql": "SELECT 1"},
    # ── 图片 ──
    "generate_image_freeapi": {"prompt": "测试图片"},
    "ocr_image": {"filepath": "/tmp/test.png"},
    "compose_poster": {"title": "测试"},
    "generate_image": {"description": "测试图片"},
    # ── 音频 ──
    "agent_speak": {"text": "你好"},
    "speech_recognition": {"audio_path": "/tmp/test.wav"},
    # ── 视频 ──
    "download_video": {"url": "https://example.com/video.mp4"},
    "video_to_text": {"video_path": "/tmp/test.mp4"},
    "generate_video": {"prompt": "测试视频"},
    # ── 文档 ──
    "convert_document": {"filepath": "/tmp/test.docx"},
    "pdf_to_word": {"pdf_path": "/tmp/test.pdf"},
    # ── 数据 ──
    "data_clean": {"data": "a,b,c"},
    "export_csv": {"data": [{"a": 1}], "filepath": "/tmp/test.csv"},
    "export_excel": {"data": [{"a": 1}], "filepath": "/tmp/test.xlsx"},
    "chart_generate": {"data": [1, 2, 3], "chart_type": "bar"},
    # ── 代码 ──
    "run_python": {"code": "print('hello')"},
    "run_shell": {"command": "echo hello"},
    # ── 基础 ──
    "calculate": {"expression": "1+1"},
    "echo": {"text": "hello"},
    "skills_execute": {"skill_id": "test"},
    "call_agent": {"target_agent_id": "test", "message": "hello"},
    # ── 模型 ──
    "deepseek_chat": {"prompt": "hello"},
    "qwen_chat": {"prompt": "hello"},
    "kimi_chat": {"prompt": "hello"},
    "minimax_chat": {"prompt": "hello"},
    "siliconflow_chat": {"prompt": "hello"},
    "doubao_chat": {"prompt": "hello"},
    # ── 通知 ──
    "wechat_send_msg": {"msg": "test"},
    "dingtalk_send_msg": {"msg": "test"},
    "xiaohongshu_search": {"keyword": "test"},
    "douyin_upload": {"video_path": "/tmp/test.mp4"},
    "douyin_get_data": {"user_id": "test"},
    "jianying_create": {"title": "test"},
    "jianying_export": {"draft_id": "test"},
    "feishu_send_msg": {"msg": "test"},
    "feishu_get_doc": {"doc_id": "test"},
    "meeting_create": {"title": "test"},
    "meeting_join_url": {"meeting_id": "test"},
    "email_send": {"to": "test@test.com", "subject": "test", "body": "test"},
    "sms_send": {"phone": "13800138000", "message": "test"},
    # ── 支付 ──
    "alipay_pay": {"amount": 1, "to": "test"},
    "alipay_refund": {"order_id": "test"},
    "alipay_query": {"order_id": "test"},
    "wechat_pay": {"amount": 1, "to": "test"},
    "wechat_refund": {"order_id": "test"},
    "wechat_query": {"order_id": "test"},
    "e_cny_pay": {"amount": 1, "to": "test"},
    "e_cny_query": {"account": "test"},
    # ── 财务 ──
    "finance_report": {"type": "损益表"},
    "finance_audit": {"keyword": "test"},
    "finance_budget": {"action": "list"},
    "finance_invoice": {"action": "list"},
    "finance_tax": {"income": 100000},
    # ── 市场 ──
    "tool_publish": {"name": "test", "description": "test"},
    "tool_install": {"name": "test"},
    "tool_search": {"keyword": "test"},
    "tool_rate": {"tool_name": "test", "rating": 5},
    "tool_top": {},
    "tool_review": {"tool_name": "test", "action": "approve"},
}
