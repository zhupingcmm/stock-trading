"""LLM 数据源适配。

关键催化剂采集（脚本 7）需要 Qwen Max 联网搜索能力。本模块封装
DashScope 兼容模式 API，对上层屏蔽 HTTP / SDK 细节。
"""
from __future__ import annotations

from typing import Any

try:
    from openai import OpenAI
except ImportError as exc:  # pragma: no cover - openai 缺失时给出友好错误
    OpenAI = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


class QwenClient:
    """基于 DashScope 兼容模式 API 的 LLM 客户端。

    - ``api_key=None`` 时优先从 ``config.settings.QWEN_API_KEY`` 读；
      若仍为空，尝试从环境变量 ``DASHSCOPE_API_KEY`` 读（与参考脚本兼容）。
    - 模型与 ``base_url`` 默认取 ``config.settings.CATALYST_MODEL`` / ``CATALYST_BASE_URL``，
      便于后续切换到其他兼容模型（DeepSeek、月之暗面等）。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        if OpenAI is None:  # pragma: no cover
            raise ImportError(
                "openai SDK 未安装，请先 ``pip install openai``。"
                f"原始错误：{_IMPORT_ERROR}"
            )

        # 延迟导入以避免硬依赖：催化剂脚本以外的用户不需要这个 client
        from config.settings import (
            CATALYST_BASE_URL,
            CATALYST_MODEL,
            QWEN_API_KEY,
        )

        import os

        self._api_key = api_key or QWEN_API_KEY or os.environ.get("DASHSCOPE_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Qwen API key 未配置，请在 .env 中填写 DASHSCOPE_API_KEY，"
                "或显式传入 api_key 参数。"
            )

        self._base_url = base_url or CATALYST_BASE_URL
        self._model = model or CATALYST_MODEL
        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    @property
    def model(self) -> str:
        return self._model

    def search(self, prompt: str, enable_search: bool = True) -> str:
        """调用 Qwen 完成单轮问答，返回字符串。

        ``enable_search=True`` 时附加联网搜索开关（DashScope 特有），
        适用于「search_catalysts」类需要外部信息的场景。
        """
        extra: dict[str, Any] = {}
        if enable_search:
            extra = {"enable_search": True, "search_options": {"forced_search": True}}

        completion = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            extra_body=extra,
        )
        return completion.choices[0].message.content.strip()