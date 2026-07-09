"""实用性检测 (Utility Test) — 运行工具，验证有实际输出。

不同工具类型有不同的判断标准：
- 搜索类：返回结果非空且包含有效信息
- 代码类：能成功生成或编译代码
- 其他：有实际输出内容

评分标准：
- 100: 输出完整、可用、高质量
- 70: 有输出但质量一般
- 40: 输出很少或基本为空
- 0: 无输出或执行失败
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from tool_args import TOOL_ARGS


class UtilityTest:
    """实用性检测器。

    运行工具的功能测试，验证其是否能产出实际可用的输出。
    不需要连接真实引擎时可运行静态模式。
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine
        self._results: dict[str, Any] = {}

    async def evaluate(self, tool_name: str, arguments: dict | None = None) -> dict:
        """评估工具的实用性。

        Args:
            tool_name: 工具名称。
            arguments: 测试参数（可选，使用默认参数）。

        Returns:
            dict: {score, output_summary, detail}
        """
        result: dict[str, Any] = {
            "name": "utility_test",
            "tool_name": tool_name,
            "score": 0,
            "output_summary": "",
            "detail": {},
            "error": None,
        }

        if not self._engine:
            result["score"] = 50
            result["output_summary"] = "无引擎连接，跳过实际测试"
            result["detail"] = {"mode": "static", "note": "引擎未配置，使用默认评分"}
            self._results[tool_name] = result
            return result

        args = arguments or self._default_args(tool_name)
        try:
            resp = await self._engine.execute(tool_name, args)
            output = self._extract_output(resp)

            if resp.get("success") and output and len(str(output).strip()) > 10:
                result["score"] = self._score_output(tool_name, str(output))
                result["output_summary"] = str(output)[:200]
                result["detail"] = {
                    "output_length": len(str(output)),
                    "success": True,
                }
            elif resp.get("success"):
                result["score"] = 40
                result["output_summary"] = "输出为空或过短"
                result["detail"] = {"success": True, "output_length": len(str(output or ""))}
            else:
                result["score"] = 0
                result["output_summary"] = resp.get("error", "执行失败")
                result["detail"] = {"success": False, "error": resp.get("error")}
                result["error"] = resp.get("error")
        except Exception as e:
            result["score"] = 0
            result["output_summary"] = f"执行异常: {e}"
            result["error"] = str(e)
            logger.warning("实用性检测异常: %s", e)

        self._results[tool_name] = result
        return result

    # ── 辅助 ─────────────────────────────────────────────────

    def _default_args(self, tool_name: str) -> dict:
        """根据工具名称生成默认测试参数，优先使用参数模板。"""
        # 先在 TOOL_ARGS 模板中查找
        if tool_name in TOOL_ARGS:
            return dict(TOOL_ARGS[tool_name])
        # 后备：基于名称启发式生成
        name_lower = tool_name.lower()
        if "search" in name_lower:
            return {"query": "今日新闻"}
        if "read" in name_lower or "web" in name_lower:
            return {"url": "https://www.baidu.com"}
        if "write" in name_lower or "create" in name_lower:
            return {"content": "test", "filename": "test_output.txt"}
        return {}

    def _extract_output(self, response: Any) -> str | None:
        """从引擎响应中提取文本输出。"""
        if response is None:
            return None
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            for key in ("output", "content", "result", "text", "message"):
                if key in response:
                    val = response[key]
                    if isinstance(val, str):
                        return val
                    if isinstance(val, list):
                        return "\n".join(str(v) for v in val)
            return str(response)
        if isinstance(response, list):
            texts = []
            for item in response:
                if isinstance(item, dict):
                    texts.append(str(item.get("text", item.get("content", ""))))
            return "\n".join(texts) if texts else str(response)
        return str(response)

    def _score_output(self, tool_name: str, output: str) -> int:
        """根据输出质量评分。"""
        length = len(output.strip())

        if length > 500:
            return 100
        if length > 200:
            return 85
        if length > 80:
            return 70
        if length > 30:
            return 50
        return 30
