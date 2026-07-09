# API Reference (API 参考文档)

## Engine API

### StarPivotEngine

```python
from starpivot import StarPivotEngine, ToolRegistry

registry = ToolRegistry()
registry.discover_servers("mcp_servers/")
engine = StarPivotEngine(registry)
```

#### `async engine.execute(tool_name, args) -> ToolResult`

Execute a single tool. Auto-retries once on failure.

```python
result = await engine.execute("web_search", {"query": "AI news"})
print(result.output)   # tool output text
print(result.success)  # True/False
print(result.error)    # error message if failed
```

#### `async engine.batch_execute(tasks) -> list[ToolResult]`

Execute multiple tools in parallel. Each task is `(tool_name, args)`.

```python
results = await engine.batch_execute([
    ("web_search", {"query": "AI 2026"}),
    ("ocr_image", {"image_path": "screenshot.png"}),
    ("deepseek_chat", {"messages": [{"role":"user","content":"Hello"}]}),
])
```

#### `async engine.close()`

Shutdown all MCP Server connections.

---

## MCP Server: Search

### `agent_reach_search`

Bing web search.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| query | string | ✅ | Search query, max 200 chars |

```python
await engine.execute("agent_reach_search", {"query": "latest AI news"})
```

---

## MCP Server: Web

### `web_search`

General web search via Firecrawl.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| query | string | ✅ | Search query |
| limit | int | ❌ | Max results (default 5, max 20) |

### `agent_reach_web_read`

Extract clean content from web page URLs.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| url | string | ✅ | Target URL |
| char_limit | int | ❌ | Max chars (default 5000) |

### `read_hot_news`

Get trending news/hot topics.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| source | string | ❌ | News source (weibo/baidu/toutiao) |

### `web_crawl`

Crawl a website recursively.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| url | string | ✅ | Start URL |
| max_pages | int | ❌ | Max pages (default 10) |
| depth | int | ❌ | Crawl depth (default 2) |

---

## MCP Server: File

### `file_read`

Read a file from user directory.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| file_path | string | ✅ | Relative path under user_files/ |
| user_id | string | ❌ | User identifier |

### `file_write`

Write content to user directory (sandboxed).

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| file_path | string | ✅ | Path under user_files/{user_id}/outputs/ |
| content | string | ✅ | File content |
| user_id | string | ❌ | User identifier |

### `file_list`

List files in user directory.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| directory | string | ❌ | Subdirectory (default: root) |
| user_id | string | ❌ | User identifier |

### `file_search`

Search files by name pattern.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| pattern | string | ✅ | Glob pattern (e.g., "*.pdf") |
| user_id | string | ❌ | User identifier |

---

## MCP Server: Image

### `generate_image_freeapi`

Generate images from text prompts.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| prompt | string | ✅ | Image description |
| size | string | ❌ | Image size (default: "1024x1024") |
| style | string | ❌ | Style hint |

### `ocr_image`

Extract text from images using OCR.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| image_path | string | ✅ | Path to image file |

### `qwen_omni`

Multimodal image understanding via Qwen.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| image_path | string | ✅ | Path to image file |
| question | string | ❌ | Question about the image |

---

## MCP Server: Audio

### `agent_speak`

Text-to-speech synthesis.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| text | string | ✅ | Text to speak |
| voice | string | ❌ | Voice ID (uses default if empty) |
| speed | float | ❌ | Playback speed (0.5-2.0) |

### `speech_recognition`

Speech-to-text recognition.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| audio_path | string | ✅ | Path to audio file |
| language | string | ❌ | Language code (e.g., "zh", "en") |

---

## MCP Server: Model

All model servers accept standard OpenAI-compatible chat format.

### `deepseek_chat` / `qwen_chat` / `kimi_chat` / `minimax_chat` / `siliconflow_chat` / `doubao_chat`

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| messages | array | ✅ | Chat messages array |
| temperature | float | ❌ | 0.0-2.0 (default: 0.7) |
| max_tokens | int | ❌ | Max output tokens (default: 2048) |
| stream | bool | ❌ | Enable streaming (default: false) |

---

## MCP Server: Doc

### `pdf_to_word`

Convert PDF to editable Word document.

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| pdf_path | string | ✅ | Path to PDF file |

---

## MCP Server: Code

### `run_python`

Execute Python code in sandboxed environment (os/socket/exec blocked).

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| code | string | ✅ | Python code to run |
| timeout | int | ❌ | Max seconds (default 15, max 30) |

### `run_shell`

Execute whitelisted shell commands (read-only: ls, cat, head, wc, etc.).

| Parameter | Type | Required | Description |
|:----------|:-----|:--------|:------------|
| command | string | ✅ | Shell command (whitelist-only) |

---

## Circuit Breaker

Built-in circuit breaker prevents cascading failures:

```python
# Default: 3 consecutive failures → 30s cooldown
engine = StarPivotEngine(registry, breaker_threshold=3, breaker_cooldown=30.0)
```

- Fails 3 times → circuit opens → calls return immediately with error
- After cooldown → half-open → next call tests if recovered
- Success → circuit closes, normal operation resumes

---

## Security Shield

The security gateway blocks dangerous operations at engine entry:
- SSH/terminal execution (blocked entirely)
- File writes outside sandboxed directories
- Network connections to internal IPs
- Python `os/system/subprocess/socket` modules in sandbox
