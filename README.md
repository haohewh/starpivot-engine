# 🚀 星枢引擎 (StarPivot Engine)

> MCP 协议驱动的 AI Agent 工具调用基础设施 — 18 个 MCP Server / 92 个工具 / 100% 代码层路由，零依赖模型 Function Calling

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Protocol-green.svg)](https://modelcontextprotocol.io/)

---

## 📖 简介

**星枢引擎**是 AI Agent 平台的核心基础设施，为 AI Agent 提供统一的工具调用能力。

传统方案让 AI 模型自己决定调用哪个工具（Function Calling）——不稳定、幻觉多、厂商绑定。星枢引擎换了一条路：**代码层检测用户意图 → 直接路由到对应 MCP Server → 执行工具 → 返回结果**。AI 模型只负责聊天，工具调用走独立通道。

## 🏗️ 架构

```
┌──────────────────────────────────────────────────────┐
│                     用户 / Agent                      │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                 StarPivotEngine                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Registry │  │ Circuit   │  │ Security Shield  │  │
│  │(工具注册) │  │ Breaker   │  │  (安全网关)       │  │
│  │          │  │ (熔断器)   │  │  封锁SSH/终端     │  │
│  └──────────┘  └───────────┘  └──────────────────┘  │
│         execute() / batch_execute()                  │
└──────────────────────┬───────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ search   │ │  image   │ │  model   │  ... 17 个 MCP Server
   │ _server  │ │ _server  │ │ _server  │
   └──────────┘ └──────────┘ └──────────┘
```

**三层防护：**
1. **安全闸门** — 引擎入口拦截 SSH/终端/文件写等危险操作
2. **熔断器** — 连续 3 次失败自动断开，防止雪崩
3. **重试机制** — 失败自动重试 1 次，8 秒超时

## 📦 MCP Server 清单

| Server | 工具数 | 能力 |
|:-------|:------:|:-----|
| search | 1 | Bing 搜索 |
| web | 4 | 网页读取、爬虫、热点新闻、通用搜索 |
| file | 4 | 文件读/写/列出/搜索 |
| db | 1 | SQL 只读查询 |
| image | 3 | 图片生成、OCR 识别、多模态识图 |
| audio | 2 | 语音合成(TTS)、语音识别(ASR) |
| media | 3 | 视频下载、转文字、生成 |
| doc | 1 | PDF 转 Word |
| data | 5 | 数据清洗、导出、图表生成、格式转换 |
| code | 2 | Python 安全沙箱（禁 os/socket/exec） |
| misc | 5 | 计算器、时间、随机数、翻译、通用工具 |
| model | 6 | DeepSeek / 通义千问 / Kimi / MiniMax / 硅基流动 / 豆包 |
| notification | 2 | 邮件发送、短信发送 |
| finance | 5 | 行情查询、财务数据、技术指标 |
| marketplace | 6 | 工具发布/搜索/安装/评分/审核/排行榜 |
| platform | 11 | 微信/钉钉/支付宝/抖音/飞书/剪映/腾讯会议/小红书/企微 |
| payment | 8 | 微信支付创建/查询/通知/退款/账单 |

**总计：17 个 Server，73 个工具（JSON 声明）**

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/haohewh/starpivot-engine.git
cd starpivot-engine
pip install -r requirements.txt
```

### 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入你的 API Key
# MINIMAX_API_KEY=xxx
# DEEPSEEK_API_KEY=xxx
# FIRECRAWL_API_KEY=xxx
```

### 5 分钟跑起来

```python
import asyncio
from starpivot.registry import ToolRegistry
from starpivot.engine import StarPivotEngine

async def main():
    # 1. 注册工具 — 自动发现所有 MCP Server
    registry = ToolRegistry()
    registry.discover_servers("mcp_servers/")

    # 2. 启动引擎
    engine = StarPivotEngine(registry)

    # 3. 调用工具 — 一行代码
    result = await engine.execute("web_search", {"query": "今日新闻"})
    print(result.output)

    # 4. 并行批量调用
    results = await engine.batch_execute([
        ("web_search", {"query": "AI Agent 2026"}),
        ("ocr_image",  {"image_path": "screenshot.png"}),
    ])

    await engine.close()

asyncio.run(main())
```

## ✨ 核心特性

| 特性 | 说明 |
|:-----|:-----|
| 🔌 **MCP 协议标准** | 每个 Server JSON 声明 + Python 实现，完全解耦 |
| 🛡️ **安全沙箱** | Python 执行禁 os/socket/exec/__import__ 等 25+ 危险模块 |
| ⚡ **熔断器** | 连续 3 次失败自动断开，30 秒冷却后半开重试 |
| 🔄 **并行执行** | batch_execute() 一次触发多个 Server，互不阻塞 |
| 📝 **工具市场** | 社区发布/搜索/安装/评分/审核，生态自生长 |
| 💾 **无需 Function Calling** | 代码层关键词匹配路由，不依赖模型能力 |
| 🌐 **多平台集成** | 微信/钉钉/支付/飞书/抖音等 11 个平台统一接入 |

## 📁 项目结构

```
starpivot-engine/
├── starpivot/                  # 引擎核心
│   ├── engine.py              # 执行中枢（熔断/重试/并行）
│   ├── registry.py            # 工具注册中心
│   ├── translator.py          # 模型格式翻译器
│   ├── scheduler.py           # 定时任务调度器
│   ├── security/
│   │   └── shield.py          # 安全网关
│   ├── spark/                 # 星火鉴 — 质量评估
│   │   ├── judge.py           # 九维评分引擎
│   │   └── ...
│   ├── memory/                # 星忆 — 三级记忆
│   │   ├── memory.py          # 热/温/冷记忆管理
│   │   ├── relations.py       # 关系图谱
│   │   └── ...
│   ├── marketplace/           # 工具市场
│   ├── platform/              # 多平台集成
│   ├── discovery/             # 工具自动发现
│   ├── eval/                  # 评测基准
│   ├── models/                # 模型市场
│   └── finance/               # 财务委员会
├── mcp_servers/               # MCP Server 实现 (17 对 JSON+Python)
├── agent_loop.py              # Agent 循环（搜索/工具/对话三路径）
├── db.py                      # 数据库层 (SQLite)
├── tools.py                   # 内置工具集
├── LICENSE
└── README.md
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

**allen** — 让每个 AI Agent 拥有可靠的双手。
