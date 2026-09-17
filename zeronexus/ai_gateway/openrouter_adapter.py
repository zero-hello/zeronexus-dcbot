"""OpenRouter Adapter Compatibility Module."""

from zeronexus.ai_gateway.adapters.openrouter import (
    OPENROUTER_STRICT_FREE_MODELS,
    OpenRouterAdapter,
    is_openrouter_model_free,
)

__all__ = [
    "OPENROUTER_STRICT_FREE_MODELS",
    "OpenRouterAdapter",
    "is_openrouter_model_free",
]
