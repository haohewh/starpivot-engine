"""模型市场 — Model Market。

统一管理 DeepSeek / 通义千问 / 豆包 / Kimi / MiniMax / 硅基流动 接口。

核心设计:
  - 统一 query(model, prompt, system_prompt, tools) 接口
  - 自动负载均衡（多 Key 轮换）
  - 降级策略（失败自动切备用模型）
  - token 和费用统计
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════════


class ModelProvider(str, Enum):
    """支持的模型提供商。"""
    DEEPSEEK = "deepseek"
    QWEN = "qwen"          # 通义千问
    DOUBAO = "doubao"      # 豆包
    KIMI = "kimi"
    MINIMAX = "minimax"
    SILICONFLOW = "siliconflow"


@dataclass
class ModelConfig:
    """单个模型的配置。"""
    name: str                       # 模型名称标识
    provider: ModelProvider          # 提供商
    api_keys: list[str] = field(default_factory=list)   # 多 Key（负载均衡）
    base_url: str = ""              # API 端点
    default_model: str = ""         # 实际模型名（如 deepseek-chat）
    max_tokens: int = 4096
    temperature: float = 0.7
    fallback: str | None = None     # 降级目标模型名


@dataclass
class UsageRecord:
    """单次调用的用量记录。"""
    model: str
    provider: ModelProvider
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0               # 费用（元）
    latency: float = 0.0            # 延迟（秒）
    success: bool = True
    key_index: int = 0              # 使用的 Key 索引
    timestamp: float = 0.0
    error: str = ""


@dataclass
class ModelResponse:
    """模型返回的标准格式。"""
    content: str
    finish_reason: str = "stop"
    usage: UsageRecord | None = None
    raw: dict | None = None


# ════════════════════════════════════════════════════════════════════
# 模型客户端基类
# ════════════════════════════════════════════════════════════════════


class ModelClient:
    """模型客户端基类。子类实现具体 API 调用。"""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self._key_index: int = 0

    def _next_key(self) -> str | None:
        """轮换获取下一个 API Key（负载均衡）。"""
        if not self.config.api_keys:
            return None
        key = self.config.api_keys[self._key_index % len(self.config.api_keys)]
        self._key_index = (self._key_index + 1) % len(self.config.api_keys)
        return key

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """统一查询接口。子类必须重写此方法。

        Args:
            prompt: 用户提示词。
            system_prompt: 系统提示词（可选）。
            tools: 工具定义列表（可选）。
            **kwargs: 额外参数（temperature, max_tokens, top_p 等）。

        Returns:
            ModelResponse: 标准化响应。
        """
        raise NotImplementedError

    def calculate_cost(self, usage: UsageRecord) -> float:
        """根据 token 数计算费用（元）。子类可按供应商重写。"""
        # 默认：输入 0.001 元/1K tokens, 输出 0.002 元/1K tokens
        return (usage.prompt_tokens * 0.001 + usage.completion_tokens * 0.002) / 1000


# ════════════════════════════════════════════════════════════════════
# 具体模型客户端（骨架 — 模拟调用返回）
# ════════════════════════════════════════════════════════════════════


class DeepSeekClient(ModelClient):
    """DeepSeek API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.DEEPSEEK, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        # 骨架：模拟调用
        await asyncio.sleep(0.2)
        latency = time.time() - start
        # 模拟 token 计数
        pt = len(prompt) + len(system_prompt)
        ct = len(prompt) * 2
        usage = UsageRecord(
            model=self.config.name,
            provider=ModelProvider.DEEPSEEK,
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency,
            success=True,
            key_index=self._key_index - 1,
            timestamp=time.time(),
        )
        logger.info("DeepSeek 调用: model=%s tokens=%d cost=%.4f元 latency=%.2fs",
                     self.config.default_model, usage.total_tokens, usage.cost, latency)
        return ModelResponse(
            content=f"[DeepSeek 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop",
            usage=usage,
        )


class QwenClient(ModelClient):
    """通义千问 API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.QWEN, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        await asyncio.sleep(0.3)
        latency = time.time() - start
        pt = len(prompt) + len(system_prompt)
        ct = int(len(prompt) * 1.8)
        usage = UsageRecord(
            model=self.config.name, provider=ModelProvider.QWEN,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency, success=True, key_index=self._key_index - 1, timestamp=time.time(),
        )
        return ModelResponse(
            content=f"[通义千问 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop", usage=usage,
        )


class DoubaoClient(ModelClient):
    """豆包 API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.DOUBAO, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        await asyncio.sleep(0.25)
        latency = time.time() - start
        pt = len(prompt) + len(system_prompt)
        ct = int(len(prompt) * 2.5)
        usage = UsageRecord(
            model=self.config.name, provider=ModelProvider.DOUBAO,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency, success=True, key_index=self._key_index - 1, timestamp=time.time(),
        )
        return ModelResponse(
            content=f"[豆包 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop", usage=usage,
        )


class KimiClient(ModelClient):
    """Kimi API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.KIMI, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        await asyncio.sleep(0.28)
        latency = time.time() - start
        pt = len(prompt) + len(system_prompt)
        ct = int(len(prompt) * 2.2)
        usage = UsageRecord(
            model=self.config.name, provider=ModelProvider.KIMI,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency, success=True, key_index=self._key_index - 1, timestamp=time.time(),
        )
        return ModelResponse(
            content=f"[Kimi 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop", usage=usage,
        )

    async def read_file(self, file_content: str, file_type: str = "auto") -> dict:
        """Kimi 文件读取（模拟）。"""
        return {
            "success": True,
            "content": f"[Kimi 文件读取模拟] 已读取{file_type}文件，共{len(file_content)}字符",
        }


class MiniMaxClient(ModelClient):
    """MiniMax API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.MINIMAX, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        await asyncio.sleep(0.22)
        latency = time.time() - start
        pt = len(prompt) + len(system_prompt)
        ct = int(len(prompt) * 1.5)
        usage = UsageRecord(
            model=self.config.name, provider=ModelProvider.MINIMAX,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency, success=True, key_index=self._key_index - 1, timestamp=time.time(),
        )
        return ModelResponse(
            content=f"[MiniMax 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop", usage=usage,
        )

    async def tts(self, text: str, voice: str = "standard") -> dict:
        """MiniMax 语音合成（模拟）。"""
        return {
            "success": True,
            "audio_url": f"https://mock.minimax.com/tts/{hash(text)}.mp3",
            "text": text[:100],
            "duration_seconds": len(text) * 0.1,
        }


class SiliconFlowClient(ModelClient):
    """硅基流动 API 客户端。"""

    async def query(
        self,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        api_key = self._next_key()
        if not api_key:
            return ModelResponse(content="", finish_reason="error", usage=UsageRecord(
                model=self.config.name, provider=ModelProvider.SILICONFLOW, success=False,
                error="API Key 未配置", timestamp=time.time(),
            ))
        start = time.time()
        await asyncio.sleep(0.35)
        latency = time.time() - start
        pt = len(prompt) + len(system_prompt)
        ct = int(len(prompt) * 2.0)
        usage = UsageRecord(
            model=self.config.name, provider=ModelProvider.SILICONFLOW,
            prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
            cost=self.calculate_cost(UsageRecord(model="", provider=self.config.provider, prompt_tokens=pt, completion_tokens=ct)),
            latency=latency, success=True, key_index=self._key_index - 1, timestamp=time.time(),
        )
        return ModelResponse(
            content=f"[硅基流动 模拟回复] 您的问题是: {prompt[:50]}...",
            finish_reason="stop", usage=usage,
        )


# 模型客户端工厂映射
_CLIENT_MAP: dict[ModelProvider, type[ModelClient]] = {
    ModelProvider.DEEPSEEK: DeepSeekClient,
    ModelProvider.QWEN: QwenClient,
    ModelProvider.DOUBAO: DoubaoClient,
    ModelProvider.KIMI: KimiClient,
    ModelProvider.MINIMAX: MiniMaxClient,
    ModelProvider.SILICONFLOW: SiliconFlowClient,
}


# ════════════════════════════════════════════════════════════════════
# 模型市场核心
# ════════════════════════════════════════════════════════════════════


class ModelMarket:
    """模型市场 — 统一管理和调用多模型。

    用法:
        market = ModelMarket()
        market.register_defaults()

        # 单次调用
        resp = await market.query("deepseek_chat", "你好")
        print(resp.content)

        # 带降级
        resp = await market.query("deepseek_chat", "你好", fallback="qwen_chat")

        # 获取统计
        stats = market.get_stats()
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelClient] = {}
        self._configs: dict[str, ModelConfig] = {}
        self._usage_records: list[UsageRecord] = []
        self._default_fallback_chain: list[str] = [
            "deepseek_chat", "qwen_chat", "kimi_chat", "doubao_chat",
        ]

    # ── 模型注册 ──────────────────────────

    def register(self, name: str, provider: ModelProvider | str,
                 api_keys: list[str] | None = None,
                 default_model: str = "",
                 base_url: str = "",
                 fallback: str | None = None,
                 **kwargs: Any) -> None:
        """注册一个模型。

        Args:
            name: 模型标识名（如 "deepseek_chat"）。
            provider: 提供商枚举或字符串。
            api_keys: API Key 列表（多 Key 负载均衡）。
            default_model: 实际模型名。
            base_url: API 端点。
            fallback: 降级目标模型名。
        """
        if isinstance(provider, str):
            provider = ModelProvider(provider)

        config = ModelConfig(
            name=name,
            provider=provider,
            api_keys=api_keys or [],
            base_url=base_url,
            default_model=default_model or name,
            fallback=fallback,
            **kwargs,
        )
        self._configs[name] = config

        client_class = _CLIENT_MAP.get(provider)
        if client_class is None:
            raise ValueError(f"不支持的模型提供商: {provider}")
        self._models[name] = client_class(config)
        logger.info("模型已注册: %s (%s)", name, provider.value)

    def register_defaults(self) -> None:
        """注册默认的 6 个模型。"""
        self.register("deepseek_chat", ModelProvider.DEEPSEEK,
                      default_model="deepseek-chat",
                      fallback="qwen_chat")
        self.register("deepseek_reason", ModelProvider.DEEPSEEK,
                      default_model="deepseek-reasoner",
                      fallback="kimi_chat")
        self.register("qwen_chat", ModelProvider.QWEN,
                      default_model="qwen-plus",
                      fallback="doubao_chat")
        self.register("doubao_chat", ModelProvider.DOUBAO,
                      default_model="doubao-1.5-pro",
                      fallback="kimi_chat")
        self.register("kimi_chat", ModelProvider.KIMI,
                      default_model="kimi-latest",
                      fallback="qwen_chat")
        self.register("minimax_chat", ModelProvider.MINIMAX,
                      default_model="minimax-abab-7b",
                      fallback="qwen_chat")
        self.register("siliconflow_chat", ModelProvider.SILICONFLOW,
                      default_model="Qwen/Qwen2.5-72B-Instruct",
                      fallback="deepseek_chat")

    def add_api_key(self, model_name: str, key: str) -> bool:
        """为已注册的模型添加 API Key。"""
        config = self._configs.get(model_name)
        if config is None:
            logger.warning("模型 %s 未注册，无法添加 Key", model_name)
            return False
        config.api_keys.append(key)
        logger.info("模型 %s 已添加 API Key (共 %d 个)", model_name, len(config.api_keys))
        return True

    def list_models(self) -> list[dict]:
        """列出所有已注册的模型。"""
        return [
            {
                "name": cfg.name,
                "provider": cfg.provider.value,
                "model": cfg.default_model,
                "keys": len(cfg.api_keys),
                "fallback": cfg.fallback,
            }
            for cfg in self._configs.values()
        ]

    # ── 核心查询 ──────────────────────────

    async def query(
        self,
        model: str,
        prompt: str,
        system_prompt: str = "",
        tools: list[dict] | None = None,
        fallback: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """统一模型查询接口。

        Args:
            model: 模型名称（如 "deepseek_chat"）。
            prompt: 用户提示词。
            system_prompt: 系统提示词。
            tools: 工具定义列表。
            fallback: 降级模型名称（覆盖预设）。
            **kwargs: 额外参数。

        Returns:
            ModelResponse: 标准化响应。
        """
        client = self._models.get(model)
        if client is None:
            return ModelResponse(
                content="",
                finish_reason="error",
                usage=UsageRecord(
                    model=model, provider=ModelProvider.DEEPSEEK,
                    success=False, error=f"未注册模型: {model}，可用: {list(self._models.keys())}",
                    timestamp=time.time(),
                ),
            )

        # 尝试主模型
        try:
            resp = await client.query(prompt, system_prompt, tools, **kwargs)
            if resp.usage:
                self._usage_records.append(resp.usage)
            if resp.finish_reason != "error" and resp.content:
                return resp
            # 主模型失败，尝试降级
            error_msg = resp.usage.error if resp.usage else "未知错误"
            logger.warning("模型 %s 失败: %s", model, error_msg)
        except Exception as e:
            logger.warning("模型 %s 异常: %s", model, e)
            error_msg = str(e)

        # ── 降级逻辑 ──
        fallback_model = fallback or client.config.fallback
        if fallback_model and fallback_model in self._models:
            logger.info("降级: %s -> %s", model, fallback_model)
            fallback_client = self._models[fallback_model]
            try:
                resp = await fallback_client.query(prompt, system_prompt, tools, **kwargs)
                if resp.usage:
                    resp.usage.error = f"降级自 {model}: {error_msg}"
                    self._usage_records.append(resp.usage)
                if resp.finish_reason != "error" and resp.content:
                    return resp
            except Exception as e2:
                logger.error("降级模型 %s 也失败: %s", fallback_model, e2)

        # 自动降级链（进一步尝试）
        for fallback_name in self._default_fallback_chain:
            if fallback_name == model or fallback_name == fallback_model:
                continue
            if fallback_name in self._models:
                logger.info("自动降级: %s -> %s", model, fallback_name)
                fb_client = self._models[fallback_name]
                try:
                    resp = await fb_client.query(prompt, system_prompt, tools, **kwargs)
                    if resp.usage:
                        resp.usage.error = f"降级自 {model}"
                        self._usage_records.append(resp.usage)
                    if resp.finish_reason != "error" and resp.content:
                        return resp
                except Exception:
                    continue

        # 全部失败
        return ModelResponse(
            content="", finish_reason="error",
            usage=UsageRecord(
                model=model, provider=client.config.provider,
                success=False, error=f"模型 {model} 及降级均失败: {error_msg}",
                timestamp=time.time(),
            ),
        )

    # ── 统计 ──────────────────────────────

    def get_stats(self) -> dict:
        """获取调用统计。"""
        total_calls = len(self._usage_records)
        if total_calls == 0:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "avg_latency": 0.0,
                "success_rate": 0.0,
                "by_model": {},
                "by_provider": {},
            }

        total_tokens = sum(r.total_tokens for r in self._usage_records)
        total_cost = sum(r.cost for r in self._usage_records)
        avg_latency = sum(r.latency for r in self._usage_records) / total_calls
        success_count = sum(1 for r in self._usage_records if r.success)

        # 按模型统计
        by_model: dict[str, dict] = {}
        for r in self._usage_records:
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "tokens": 0, "cost": 0.0, "success": 0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["tokens"] += r.total_tokens
            by_model[r.model]["cost"] += r.cost
            if r.success:
                by_model[r.model]["success"] += 1

        # 按提供商统计
        by_provider: dict[str, dict] = {}
        for r in self._usage_records:
            p = r.provider.value if hasattr(r.provider, 'value') else str(r.provider)
            if p not in by_provider:
                by_provider[p] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_provider[p]["calls"] += 1
            by_provider[p]["tokens"] += r.total_tokens
            by_provider[p]["cost"] += r.cost

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "avg_latency": round(avg_latency, 3),
            "success_rate": round(success_count / total_calls, 4) if total_calls else 0.0,
            "by_model": by_model,
            "by_provider": by_provider,
        }

    def get_recent_calls(self, limit: int = 10) -> list[dict]:
        """获取最近的调用记录。"""
        recent = self._usage_records[-limit:] if self._usage_records else []
        return [
            {
                "model": r.model,
                "provider": r.provider.value if hasattr(r.provider, 'value') else str(r.provider),
                "tokens": r.total_tokens,
                "cost": round(r.cost, 4),
                "latency": round(r.latency, 3),
                "success": r.success,
                "error": r.error,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp)),
            }
            for r in recent
        ]
