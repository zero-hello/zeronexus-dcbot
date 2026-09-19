"""Base AI Adapter Interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AIResult:
    """Standardized response object from any AI provider adapter."""
    text: str
    model_name: str
    provider: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: Optional[Dict[str, Any]] = None
    is_fallback: bool = False
    fallback_reason: Optional[str] = None
    requested_model: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    thinking_process: Optional[str] = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def actual_model(self) -> str:
        """The actual model that executed and produced this response (Runtime Truth)."""
        return self.model_name

    @property
    def selected_model(self) -> Optional[str]:
        """The model selected for this invocation, prior to any provider failover."""
        return self.requested_model or self.model_name


class BaseAIAdapter(ABC):
    """Abstract base class for high-performance HTTP REST adapters."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    @abstractmethod
    async def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        model: str,
        api_key: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
        images: Optional[List[Dict[str, Any]]] = None,
        allow_fallback: bool = True,
        disable_safety: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Any] = None,
        max_tool_rounds: int = 3,
        free_only: bool = False,
    ) -> AIResult:
        """Sends inference request to the provider API using api_key."""
        pass

    async def close(self) -> None:
        """Closes the underlying persistent HTTP client session."""
        if hasattr(self, "_http_client") and self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
