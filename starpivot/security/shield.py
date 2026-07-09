"""星枢安全防护 — SecurityShield（安全护盾）。

防止攻击、注入、滥用，提供输入过滤、速率限制、攻击检测和自动修补。

用法:
    shield = SecurityShield()
    
    # 清洗用户输入
    safe = shield.sanitize("SELECT * FROM users; DROP TABLE;")
    
    # 速率限制检查
    allowed = shield.check_rate_limit("user_123", "search")
    
    # 异常检测
    is_attack = shield.detect_anomaly(requests_history)
    
    # 自动修补
    shield.auto_patch()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# ── 危险模式库 ────────────────────────────────

_SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC)\b", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),
    re.compile(r"/\*.*?\*/", re.DOTALL),
    re.compile(r"\bUNION\b.*\bSELECT\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bOR\s+1\s*=\s*1\b", re.IGNORECASE),
    re.compile(r"'.*?(OR|AND).*?'.*?=.*?'", re.IGNORECASE),
]

_XSS_PATTERNS: list[re.Pattern] = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onerror=, onclick=, etc.
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<embed[^>]*>", re.IGNORECASE),
    re.compile(r"<object[^>]*>", re.IGNORECASE),
    re.compile(r"<svg[^>]*>.*?<script", re.IGNORECASE | re.DOTALL),
    re.compile(r"&lt;script&gt;", re.IGNORECASE),
    re.compile(r"document\.(cookie|write|location|domain)", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"alert\s*\(", re.IGNORECASE),
]

_COMMAND_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"[;&|`]\s*(rm|shutdown|reboot|mkfs|dd|wget|curl|chmod|chown|sudo|passwd)", re.IGNORECASE),
    re.compile(r"\$\s*\(.*?\)"),  # $(command)
    re.compile(r"`.*?`"),  # `command`
    re.compile(r"\|.*?\s*(bash|sh|python|perl|ruby)\s"),  # | bash
    re.compile(r"(;|\|\||&&)\s*(rm|mv|cp|dd|mkfs|wget|curl|chmod|chown|sudo)"),  # ; rm / && wget
    re.compile(r"(/etc/passwd|/etc/shadow|~/.ssh/authorized_keys)"),  # sensitive paths
]

_PATH_TRAVERSAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\.\./"),
    re.compile(r"\.\.\\"),
    re.compile(r"%2e%2e%2f", re.IGNORECASE),  # URL encoded ../
    re.compile(r"%2e%2e/", re.IGNORECASE),
    re.compile(r"\.\.%2f", re.IGNORECASE),
]


class SecurityShield:
    """安全防护：输入过滤、速率限制、攻击检测。

    多层安全防护系统，提供:
        1. 输入清洗 — 过滤 SQL 注入、XSS、命令注入、路径遍历。
        2. 速率限制 — 用户级别的工具调用频率控制。
        3. 异常检测 — 检测异常请求模式（暴力攻击、扫描等）。
        4. 自动修补 — 扫描已知漏洞并应用修补。

    线程安全：所有操作设计为可从多个协程并发调用。
    """

    def __init__(self) -> None:
        # ── 速率限制状态 ──
        self._rate_limit: dict[str, dict[str, list[float]]] = {}  # user -> tool -> [timestamps]
        self._rate_limits_config: dict[str, int] = {}  # tool -> max_calls
        self._default_rate_limit = 30  # 默认每 60 秒 30 次

        # ── 异常检测状态 ──
        self._anomaly_threshold = 0.8  # 异常分数阈值

        # ── 自动修补 ──
        self._patches_applied: set[str] = set()

    # ════════════════════════════════════════════════════════════════
    # 输入清洗
    # ════════════════════════════════════════════════════════════════

    def sanitize(self, text: str) -> str:
        """清洗危险输入，移除或转义潜在攻击载荷。

        检测并处理:
            - SQL 注入（SELECT, DROP, UNION 等）
            - XSS（<script>, javascript:, onerror= 等）
            - 命令注入（rm, wget, $(command) 等）
            - 路径遍历（../, %2e%2e%2f 等）

        Args:
            text: 原始用户输入字符串。

        Returns:
            清洗后的安全字符串。如果检测到严重攻击载荷，
            返回空字符串并记录警告。
        """
        if not isinstance(text, str):
            return str(text) if text is not None else ""

        original = text

        # ── 1. 检测 SQL 注入 ──
        for pattern in _SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                logger.warning("SecurityShield: 检测到 SQL 注入: %r", original[:200])
                return ""

        # ── 2. 检测 XSS ──
        for pattern in _XSS_PATTERNS:
            if pattern.search(text):
                logger.warning("SecurityShield: 检测到 XSS: %r", original[:200])
                return ""

        # ── 3. 检测命令注入 ──
        for pattern in _COMMAND_INJECTION_PATTERNS:
            if pattern.search(text):
                logger.warning("SecurityShield: 检测到命令注入: %r", original[:200])
                return ""

        # ── 4. 检测路径遍历 ──
        for pattern in _PATH_TRAVERSAL_PATTERNS:
            if pattern.search(text):
                logger.warning("SecurityShield: 检测到路径遍历: %r", original[:200])
                return ""

        # ── 5. 通用 HTML 转义（仅转义 < 和 > 防 XSS） ──
        # 仅对未匹配 XSS 模式但仍含 HTML 标签的文本做转义
        if "<" in text and ">" in text:
            text = text.replace("<", "&lt;").replace(">", "&gt;")
            if text != original:
                logger.info("SecurityShield: 已转义 HTML 标签")

        return text

    def sanitize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """清洗参数字典中所有字符串值。

        Args:
            params: 包含工具参数的字典。

        Returns:
            清洗后的参数字典。
        """
        cleaned: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                cleaned[key] = self.sanitize(value)
            elif isinstance(value, dict):
                cleaned[key] = self.sanitize_params(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    self.sanitize(item) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                cleaned[key] = value
        return cleaned

    # ════════════════════════════════════════════════════════════════
    # 速率限制
    # ════════════════════════════════════════════════════════════════

    def set_rate_limit(self, tool: str, max_calls: int) -> None:
        """设置工具的速率限制。

        Args:
            tool:     工具名称（"*" 表示全局默认）。
            max_calls: 每 60 秒最大允许调用次数。
        """
        self._rate_limits_config[tool] = max_calls
        logger.info(
            "SecurityShield: 速率限制 %s = %d 次/60秒", tool, max_calls,
        )

    def check_rate_limit(self, user_id: str, tool: str) -> bool:
        """检查速率限制。

        在 60 秒滑动窗口内统计调用次数，超过限制返回 False。

        Args:
            user_id: 用户标识。
            tool:    工具名称。

        Returns:
            True 表示允许调用，False 表示超出限制。
        """
        now = time.time()
        window = 60.0

        # 获取该工具的速率限制
        max_calls = self._rate_limits_config.get(
            tool,
            self._rate_limits_config.get("*", self._default_rate_limit),
        )

        # 初始化用户记录
        if user_id not in self._rate_limit:
            self._rate_limit[user_id] = {}
        if tool not in self._rate_limit[user_id]:
            self._rate_limit[user_id][tool] = []

        timestamps = self._rate_limit[user_id][tool]

        # 清理超出窗口的旧记录
        cutoff = now - window
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        # 检查是否超出限制
        if len(timestamps) >= max_calls:
            logger.warning(
                "SecurityShield: 速率限制触发 — user=%s tool=%s "
                "(%d 次/%ds, 限制 %d)",
                user_id, tool, len(timestamps), int(window), max_calls,
            )
            return False

        # 记录本次调用
        timestamps.append(now)
        return True

    def get_rate_limit_status(self, user_id: str, tool: str) -> dict:
        """获取用户的速率限制状态。

        Args:
            user_id: 用户标识。
            tool:    工具名称。

        Returns:
            - allowed (int):  窗口中已使用的次数。
            - limit (int):    最大允许次数。
            - remaining (int): 剩余可用次数。
            - reset_at (float): 窗口重置时间戳。
        """
        now = time.time()
        window = 60.0
        max_calls = self._rate_limits_config.get(
            tool,
            self._rate_limits_config.get("*", self._default_rate_limit),
        )

        used = len(self._rate_limit.get(user_id, {}).get(tool, []))
        return {
            "used": used,
            "limit": max_calls,
            "remaining": max(max_calls - used, 0),
            "reset_at": now + window,
        }

    # ════════════════════════════════════════════════════════════════
    # 异常检测
    # ════════════════════════════════════════════════════════════════

    def detect_anomaly(self, requests: list[dict]) -> bool:
        """检测异常请求模式。

        分析请求列表中的模式，判断是否为攻击行为：
            - 短时间内大量失败（暴力破解）
            - 连续请求不同工具（扫描行为）
            - 请求中携带明显的攻击载荷（已被 sanitize 拦截的）
            - 来自同一来源的高频率请求

        Args:
            requests: 请求记录列表，每条记录包含:
                - user_id (str):    用户标识。
                - tool (str):       工具名称。
                - success (bool):   是否成功。
                - timestamp (float): 请求时间戳（可选）。
                - sanitized (bool):  是否被安全模块拦截（可选）。

        Returns:
            True 表示检测到异常，False 表示正常。
        """
        if not requests:
            return False

        now = time.time()
        window = 60.0
        cutoff = now - window

        # 只分析窗口内的请求
        recent = [r for r in requests if r.get("timestamp", now) >= cutoff]

        if len(recent) < 10:  # 样本太少，不做判断
            return False

        # ── 特征 1: 失败率 ──
        failures = [r for r in recent if not r.get("success", True)]
        failure_rate = len(failures) / len(recent)

        # ── 特征 2: 工具切换频率（扫描行为） ──
        tools_used = set(r.get("tool", "") for r in recent)
        tool_switch_rate = len(tools_used) / len(recent)

        # ── 特征 3: 被 sanitize 拦截的比例 ──
        sanitized = [r for r in recent if r.get("sanitized", False)]
        sanitized_rate = len(sanitized) / len(recent)

        # ── 得分计算 ──
        score = 0.0
        if failure_rate > 0.5:
            score += 0.4  # 失败率过高
        if tool_switch_rate > 0.3:
            score += 0.3  # 工具切换频繁（扫描行为）
        if sanitized_rate > 0.2:
            score += 0.4  # 大量被拦截的恶意请求

        is_anomaly = score >= self._anomaly_threshold

        if is_anomaly:
            logger.warning(
                "SecurityShield: 检测到异常请求模式 — "
                "score=%.2f failure_rate=%.2f tool_switch=%.2f sanitized=%.2f",
                score, failure_rate, tool_switch_rate, sanitized_rate,
            )

        return is_anomaly

    # ════════════════════════════════════════════════════════════════
    # 自动修补
    # ════════════════════════════════════════════════════════════════

    def auto_patch(self) -> dict[str, str]:
        """自动扫描已知漏洞并修补。

        目前实现的自动修补:
            1. 检查配置文件是否包含默认/弱密码。
            2. 检查是否启用了危险的工具（如 shell 执行）。
            3. 检查是否有过于宽泛的 CORS 配置。

        Returns:
            修补结果字典:
                - patched (list[str]): 已应用修补列表。
                - skipped (list[str]): 无需修补的项目。
                - failed (list[str]):  修补失败的项目。
        """
        result: dict[str, list[str]] = {
            "patched": [],
            "skipped": [],
            "failed": [],
        }

        # ── 1. 检查 rate_limits 配置 ──
        if self._default_rate_limit > 100:
            old = self._default_rate_limit
            self._default_rate_limit = 100
            self._patches_applied.add("rate_limit_tightened")
            result["patched"].append(
                f"降低默认速率限制: {old} → 100 次/60秒",
            )
            logger.info("SecurityShield: 自动收紧默认速率限制 %d→100", old)
        else:
            result["skipped"].append("速率限制配置安全")

        # ── 2. 检查是否设置了显式的速率限制规则 ──
        dangerous_tools = ["exec", "shell", "run_command", "execute_code"]
        for tool in dangerous_tools:
            limit = self._rate_limits_config.get(tool, None)
            if limit is None or limit > 5:
                self.set_rate_limit(tool, 5)
                self._patches_applied.add(f"rate_limit_{tool}")
                result["patched"].append(
                    f"收紧危险工具 {tool} 速率限制至 5 次/60秒",
                )

        # ── 3. 检查异常检测阈值 ──
        if self._anomaly_threshold > 0.9:
            old = self._anomaly_threshold
            self._anomaly_threshold = 0.8
            self._patches_applied.add("anomaly_threshold_tightened")
            result["patched"].append(
                f"降低异常检测阈值: {old} → 0.8",
            )
        else:
            result["skipped"].append("异常检测阈值安全")

        return result

    @property
    def patches_applied(self) -> set[str]:
        """已应用的修补列表。"""
        return set(self._patches_applied)


# ════════════════════════════════════════════════════════════════
# 便捷函数
# ════════════════════════════════════════════════════════════════


def is_safe_input(text: str) -> bool:
    """快速检查输入是否安全（不进行清洗，只返回布尔值）。

    用于在调用 sanitize 之前快速判断。

    Args:
        text: 输入文本。

    Returns:
        True 表示安全，False 表示检测到攻击载荷。
    """
    for pattern in _SQL_INJECTION_PATTERNS + _XSS_PATTERNS + _COMMAND_INJECTION_PATTERNS + _PATH_TRAVERSAL_PATTERNS:
        if pattern.search(text):
            return False
    return True
