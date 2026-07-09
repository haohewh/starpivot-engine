# 🚀 StarPivot Engine (星枢引擎)

> MCP Protocol-Driven AI Agent Tool Infrastructure — 17 MCP Servers / 73 Tools / 100% Code-Layer Routing, Zero Dependency on Model Function Calling

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Protocol-green.svg)](https://modelcontextprotocol.io/)

[中文文档](README.md)

---

## 📖 Overview

StarPivot Engine is the core infrastructure of the AI Agent platform, providing unified tool-calling capabilities for AI Agents.

Traditional approaches let AI models decide which tool to call (Function Calling) — unstable, prone to hallucinations, and vendor-locked. StarPivot takes a different path: **code-layer intent detection → direct routing to MCP Servers → tool execution → result return**. The AI model handles conversation only; tool calls go through an independent channel.

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────┐
│                   User / Agent                       │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                 StarPivotEngine                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Registry │  │ Circuit   │  │ Security Shield  │  │
│  │          │  │ Breaker   │  │  (Blocks SSH/    │  │
│  │          │  │           │  │   Terminal exec)  │  │
│  └──────────┘  └───────────┘  └──────────────────┘  │
│         execute() / batch_execute()                  │
└──────────────────────┬───────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ search   │ │  image   │ │  model   │  ... 17 MCP Servers
   │ _server  │ │ _server  │ │ _server  │
   └──────────┘ └──────────┘ └──────────┘
```

**Three-Layer Protection:**
1. **Security Gateway** — Blocks dangerous operations (SSH/terminal/file writes) at engine entry
2. **Circuit Breaker** — Auto-disconnects after 3 consecutive failures, prevents cascading errors
3. **Retry Mechanism** — Auto-retries once on failure, 8-second timeout

## 📦 MCP Server Inventory

| Server | Tools | Capabilities |
|:-------|:-----:|:------------|
| search | 1 | Bing web search |
| web | 4 | Web reading, crawling, hot news, general search |
| file | 4 | File read/write/list/search |
| db | 1 | SQL read-only queries |
| image | 3 | Image generation, OCR, multimodal recognition |
| audio | 2 | Text-to-speech (TTS), speech recognition (ASR) |
| media | 3 | Video download, transcription, generation |
| doc | 1 | PDF to Word conversion |
| data | 5 | Data cleaning, export, charts, format conversion |
| code | 2 | Python sandbox (os/socket/exec blocked) |
| misc | 5 | Calculator, time, random, translation, utilities |
| model | 6 | DeepSeek / Qwen / Kimi / MiniMax / SiliconFlow / Doubao |
| notification | 2 | Email, SMS |
| finance | 5 | Market data, financial statements, technical indicators |
| marketplace | 6 | Tool publish/search/install/rate/review/leaderboard |
| platform | 11 | WeChat/DingTalk/Alipay/Douyin/Feishu/Jianying/Tencent Meeting/Xiaohongshu/WeCom |
| payment | 8 | WeChat Pay: create/query/notify/refund/billing |

**Total: 17 Servers, 73 tools (JSON-declared)**

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/haohewh/starpivot-engine.git
cd starpivot-engine
pip install -r requirements.txt
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your API keys
# MINIMAX_API_KEY=xxx
# DEEPSEEK_API_KEY=xxx
# FIRECRAWL_API_KEY=xxx
```

### Run in 5 Minutes

```python
import asyncio
from starpivot.registry import ToolRegistry
from starpivot.engine import StarPivotEngine

async def main():
    # 1. Register tools — auto-discover all MCP Servers
    registry = ToolRegistry()
    registry.discover_servers("mcp_servers/")

    # 2. Start engine
    engine = StarPivotEngine(registry)

    # 3. Call a tool — one line
    result = await engine.execute("web_search", {"query": "latest AI news"})
    print(result.output)

    # 4. Parallel batch execution
    results = await engine.batch_execute([
        ("web_search", {"query": "AI Agent 2026"}),
        ("ocr_image",  {"image_path": "screenshot.png"}),
    ])

    await engine.close()

asyncio.run(main())
```

## ✨ Key Features

| Feature | Description |
|:--------|:------------|
| 🔌 **MCP Protocol** | JSON declaration + Python implementation per server, fully decoupled |
| 🛡️ **Security Sandbox** | Python execution blocks os/socket/exec/__import__ and 25+ dangerous modules |
| ⚡ **Circuit Breaker** | Auto-disconnects after 3 consecutive failures, 30s cooldown with half-open retry |
| 🔄 **Parallel Execution** | batch_execute() fires multiple servers simultaneously, non-blocking |
| 📝 **Tool Marketplace** | Community publish/search/install/rate/review — self-growing ecosystem |
| 💾 **No Function Calling** | Code-layer keyword-match routing, no model capability dependency |
| 🌐 **Multi-Platform** | Unified access to WeChat/DingTalk/Alipay/Douyin and 7 more platforms |

## 📁 Project Structure

```
starpivot-engine/
├── starpivot/                  # Engine core
│   ├── engine.py              # Execution hub (breaker/retry/parallel)
│   ├── registry.py            # Tool registry
│   ├── translator.py          # Model format translator
│   ├── scheduler.py           # Cron-like task scheduler
│   ├── security/
│   │   └── shield.py          # Security gateway
│   ├── spark/                 # Spark Judge — quality evaluation
│   │   ├── judge.py           # 9-dimension scoring engine
│   │   └── ...
│   ├── memory/                # Star Memory — 3-tier memory
│   │   ├── memory.py          # Hot/warm/cold memory management
│   │   ├── relations.py       # Relationship graph
│   │   └── ...
│   ├── marketplace/           # Tool marketplace
│   ├── platform/              # Multi-platform integration
│   ├── discovery/             # Auto tool discovery
│   ├── eval/                  # Evaluation benchmarks
│   ├── models/                # Model marketplace
│   └── finance/               # Finance committee
├── mcp_servers/               # MCP Server implementations (17 JSON+Python pairs)
├── agent_loop.py              # Agent loop (search/tool/chat 3-path)
├── db.py                      # Database layer (SQLite)
├── tools.py                   # Built-in toolset
├── requirements.txt
├── .env.example
├── LICENSE
├── README.md                  # 中文文档
└── README_EN.md               # English docs (this file)
```

## 🤝 Contributing

Issues and Pull Requests are welcome.

## 📄 License

MIT License — see [LICENSE](LICENSE)

---

**allen** — Giving every AI Agent reliable hands.
