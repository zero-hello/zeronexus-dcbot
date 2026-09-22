"""ZeroNexus AI Provider Adapters."""

from zeronexus.ai_gateway.adapters.base import BaseAIAdapter, AIResult
from zeronexus.ai_gateway.adapters.gemini import GeminiAdapter
from zeronexus.ai_gateway.adapters.deepseek import DeepSeekAdapter
from zeronexus.ai_gateway.adapters.openrouter import OpenRouterAdapter
from zeronexus.ai_gateway.adapters.huggingface import HuggingFaceAdapter
from zeronexus.ai_gateway.adapters.manus import ManusAdapter
from zeronexus.ai_gateway.adapters.cohere import CohereAdapter
from zeronexus.ai_gateway.adapters.mistral import MistralAdapter
from zeronexus.ai_gateway.adapters.groq import GroqAdapter

__all__ = [
    "BaseAIAdapter",
    "AIResult",
    "GeminiAdapter",
    "DeepSeekAdapter",
    "OpenRouterAdapter",
    "HuggingFaceAdapter",
    "ManusAdapter",
    "CohereAdapter",
    "MistralAdapter",
    "GroqAdapter",
]

