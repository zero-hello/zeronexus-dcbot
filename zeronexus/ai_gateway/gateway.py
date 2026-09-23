"""ZeroNexus AI Gateway with Tri-Level Resilient Fallback.

Fallback Hierarchy:
Gemini (Primary) -> DeepSeek (Secondary) -> OpenRouter (Tertiary)

Features:
- Seamless multi-key pool rotation per provider
- Dynamic model tracking from response headers/payload
- Automatic failover notification tracking
- Diagnostic health status evaluation
"""

from __future__ import annotations

import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from zeronexus.ai_gateway.adapters.base import AIResult
from zeronexus.ai_gateway.adapters.deepseek import DeepSeekAdapter
from zeronexus.ai_gateway.adapters.gemini import GeminiAdapter
from zeronexus.ai_gateway.adapters.huggingface import HuggingFaceAdapter
from zeronexus.ai_gateway.adapters.manus import ManusAdapter
from zeronexus.ai_gateway.adapters.cohere import CohereAdapter
from zeronexus.ai_gateway.adapters.mistral import MistralAdapter
from zeronexus.ai_gateway.adapters.groq import GroqAdapter
from zeronexus.ai_gateway.adapters.openrouter import (
    OPENROUTER_STRICT_FREE_MODELS,
    OpenRouterAdapter,
    is_openrouter_model_free,
)
from zeronexus.ai_gateway.key_pool import KeyState, ProviderKeyPool
from zeronexus.core.config import config
from zeronexus.ai_gateway.model_registry import model_registry, ModelStatus
from zeronexus.core.logger import log
from zeronexus.core.stats import stats
from zeronexus.security.sanitizer import redact_secrets


class AIGateway:
    """Master AI inference coordinator managing providers, key pools, and failovers."""

    def __init__(self) -> None:
        self.adapters = {
            "gemini": GeminiAdapter(),
            "deepseek": DeepSeekAdapter(),
            "openrouter": OpenRouterAdapter(),
            "huggingface": HuggingFaceAdapter(),
            "manus": ManusAdapter(),
            "cohere": CohereAdapter(),
            "mistral": MistralAdapter(),
            "groq": GroqAdapter(),
        }

        hf_keys = getattr(config.ai, "huggingface_keys", None) or ([config.ai.huggingface_token] if config.ai.huggingface_token else [])
        manus_keys = getattr(config.ai, "manus_keys", None) or []
        cohere_keys = getattr(config.ai, "cohere_keys", None) or []
        mistral_keys = getattr(config.ai, "mistral_keys", None) or []
        groq_keys = getattr(config.ai, "groq_keys", None) or []
        self.key_pools = {
            "gemini": ProviderKeyPool("gemini", config.ai.gemini_keys),
            "deepseek": ProviderKeyPool("deepseek", config.ai.deepseek_keys),
            "openrouter": ProviderKeyPool("openrouter", config.ai.openrouter_keys),
            "huggingface": ProviderKeyPool("huggingface", hf_keys),
            "manus": ProviderKeyPool("manus", manus_keys),
            "cohere": ProviderKeyPool("cohere", cohere_keys),
            "mistral": ProviderKeyPool("mistral", mistral_keys),
            "groq": ProviderKeyPool("groq", groq_keys),
        }

    async def generate_response(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        override_model: Optional[str] = None,
        images: Optional[List[Dict[str, Any]]] = None,
        allow_fallback: bool = True,
        disable_safety: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        allow_tools: bool = True,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Any]]] = None,
        max_tool_rounds: int = 3,
        thinking_budget: Optional[int] = None,
        **kwargs: Any,
    ) -> Tuple[AIResult, Optional[str]]:
        """Executes inference through fallback chain: Gemini -> DeepSeek -> OpenRouter.
        When images are provided, reorders to prioritize vision models: Gemini -> OpenRouter -> DeepSeek.

        Returns (AIResult, fallback_notice_str).
        """
        # Clean and normalize override_model (strip whitespace, resolve empty strings)
        clean_override: Optional[str] = None
        if override_model and isinstance(override_model, str) and override_model.strip():
            clean_override = override_model.strip()

        # Determine primary provider based on override_model or images
        primary: Optional[str] = None
        if clean_override:
            meta = model_registry.get(clean_override)
            if meta and getattr(meta, "status", None) == ModelStatus.RETIRED and getattr(meta, "replacement_model_id", None):
                repl_id = meta.replacement_model_id
                repl = model_registry.get(repl_id)
                log.info(f"模型 '{clean_override}' 已退役或不可用，自動平滑升級為 '{repl_id}'")
                if repl:
                    meta = repl
                    clean_override = repl.model_id
                else:
                    clean_override = repl_id

            if meta and meta.provider in self.adapters:
                primary = meta.provider
                clean_override = meta.model_id
            elif clean_override.lower().startswith("huggingface/"):
                primary = "huggingface"
            elif "/" in clean_override:
                primary = "openrouter"
            elif "gemini" in clean_override.lower():
                primary = "gemini"
            elif "deepseek" in clean_override.lower():
                primary = "deepseek"
            elif "manus" in clean_override.lower():
                primary = "manus"
            elif "cohere" in clean_override.lower() or "command-r" in clean_override.lower():
                primary = "cohere"
            elif any(k in clean_override.lower() for k in ("mistral", "codestral", "pixtral")):
                primary = "mistral"
            elif any(k in clean_override.lower() for k in ("groq", "llama-3.3", "llama-3.1", "deepseek-r1-distill")):
                primary = "groq"
            else:
                primary = "openrouter"

            # 智慧自動路由：若目標提供者為 deepseek，但原生 deepseek key pool 無可用金鑰
            # 且 openrouter key pool 具備可用金鑰，自動切換至 openrouter 並標準化模型 ID
            if primary == "deepseek":
                deepseek_pool = self.key_pools.get("deepseek")
                deepseek_active = bool(deepseek_pool and getattr(deepseek_pool, "has_active_keys", False))
                if not deepseek_active:
                    or_pool = self.key_pools.get("openrouter")
                    if or_pool and getattr(or_pool, "has_active_keys", False):
                        primary = "openrouter"
                        low_id = clean_override.lower()
                        if "r1" in low_id or "reasoner" in low_id:
                            clean_override = "deepseek/deepseek-r1"
                        elif "v4-flash-vision" in low_id or "v4.1" in low_id or "v4-flash" in low_id or "v4" in low_id:
                            clean_override = "deepseek/deepseek-v4-flash-vision-exp"
                        elif "chat" in low_id or "v3" in low_id:
                            clean_override = "deepseek/deepseek-chat"
                        elif not clean_override.startswith("deepseek/"):
                            clean_override = f"deepseek/{clean_override}"

            configured_fallbacks = getattr(config.ai, "fallback_providers", None) or [
                "gemini", "groq", "deepseek", "mistral", "openrouter", "cohere", "manus", "huggingface"
            ]
            base_chain = [p for p in configured_fallbacks if p in self.key_pools and self.key_pools[p].has_active_keys]
            if not base_chain:
                base_chain = [p for p in configured_fallbacks if p in self.key_pools]
            if not allow_fallback:
                fallback_chain = [primary]
            else:
                fallback_chain = [primary] + [p for p in base_chain if p != primary]
        elif images:
            configured_fallbacks = getattr(config.ai, "fallback_providers", None) or [
                "gemini", "groq", "deepseek", "mistral", "openrouter", "cohere", "manus", "huggingface"
            ]
            base_chain = [p for p in configured_fallbacks if p in self.key_pools and self.key_pools[p].has_active_keys]
            if not base_chain:
                base_chain = [p for p in configured_fallbacks if p in self.key_pools]
            vision_chain = ["gemini", "openrouter"]
            fallback_chain = [p for p in vision_chain if p in base_chain] + [p for p in base_chain if p not in vision_chain]
        else:
            configured_fallbacks = getattr(config.ai, "fallback_providers", None) or [
                "gemini", "groq", "deepseek", "mistral", "openrouter", "cohere", "manus", "huggingface"
            ]
            fallback_chain = [p for p in configured_fallbacks if p in self.key_pools and self.key_pools[p].has_active_keys]
            if not fallback_chain:
                fallback_chain = [p for p in configured_fallbacks if p in self.key_pools]

        fallback_notice: Optional[str] = None
        attempted_providers: List[str] = []

        for idx, provider_name in enumerate(fallback_chain):
            pool = self.key_pools[provider_name]

            # Assign valid model ID per provider
            if clean_override and provider_name == primary:
                model = clean_override
            elif clean_override and provider_name == "openrouter" and "deepseek" in clean_override.lower():
                low_id = clean_override.lower()
                if "r1" in low_id or "reasoner" in low_id:
                    model = "deepseek/deepseek-r1"
                elif "v4" in low_id:
                    model = "deepseek/deepseek-v4-flash-vision-exp"
                else:
                    model = "deepseek/deepseek-chat"
            else:
                model = self._get_default_model(provider_name, has_images=bool(images))

            # Check if this provider call requires paid quota
            requires_paid = False
            if provider_name == "openrouter":
                requires_paid = not is_openrouter_model_free(model)

            try:
                key_obj = pool.get_available_key(requires_paid=requires_paid)
            except TypeError:
                key_obj = pool.get_available_key()

            # If paid key is unavailable for OpenRouter, fall back to zero-cost fallback key and switch model to free
            if not key_obj and requires_paid and provider_name == "openrouter" and allow_fallback:
                try:
                    # Look specifically for fallback key or free_only key in pool
                    free_key = None
                    for k in pool._keys:
                        if (getattr(k, "free_only", False) or getattr(k, "is_fallback_key", False)) and k.is_available:
                            free_key = k
                            break
                    # If not found, any healthy key in the pool can be used for zero-cost models
                    if not free_key:
                        for k in pool._keys:
                            if k.is_available:
                                free_key = k
                                break
                    if free_key:
                        key_obj = free_key
                        chosen_free = OPENROUTER_STRICT_FREE_MODELS[0]
                        log.warning(
                            f"[AI Gateway Fallback] Paid quota unavailable for '{model}'. "
                            f"Falling back to zero-cost key {free_key.masked} and switching to free model '{chosen_free}'."
                        )
                        model = chosen_free
                        requires_paid = False
                except Exception as ex:
                    log.warning(f"[AI Gateway Fallback] Error resolving free key for OpenRouter: {ex}")

            if not key_obj:
                if requires_paid:
                    attempted_providers.append(f"{provider_name} (無可用付費額度金鑰)")
                else:
                    attempted_providers.append(f"{provider_name} (無可用金鑰/冷卻中)")
                continue

            # Strict free filtering if OpenRouter key is fallback key or free_only
            is_fallback_key = False
            if provider_name == "openrouter":
                fallback_val = getattr(config.ai, "openrouter_fallback_key", "")
                if (fallback_val and key_obj.raw_key == fallback_val) or getattr(key_obj, "free_only", False):
                    is_fallback_key = True
                    if not is_openrouter_model_free(model):
                        chosen_free = OPENROUTER_STRICT_FREE_MODELS[0]
                        log.warning(
                            f"[AIGateway Free Filter] Model '{model}' is a paid model but OpenRouter is on fallback key. "
                            f"Strictly switching to zero-cost free model '{chosen_free}'."
                        )
                        model = chosen_free

            # Prepare provider-specific tool schemas
            provider_tools = None
            if allow_tools:
                if tools is not None:
                    provider_tools = tools
                else:
                    user_prompt = ""
                    for m in reversed(messages):
                        if m.get("role") == "user":
                            user_prompt = str(m.get("content", ""))
                            break

                    from zeronexus.intelligence.dynamic_projector import dynamic_projector
                    from zeronexus.agent.tools import agent_tools

                    projected_set = dynamic_projector.project(user_prompt=user_prompt)
                    tools_list = []
                    for pt in projected_set.tools:
                        t = agent_tools.get_tool(pt.name)
                        if t:
                            if provider_name == "gemini":
                                tools_list.append(t.to_gemini_tool_schema())
                            elif provider_name == "openrouter":
                                tools_list.append(t.to_openai_tool_schema())
                    if tools_list:
                        provider_tools = tools_list

            adapter = self.adapters[provider_name]

            start_ts = time.perf_counter()

            try:
                log.info(f"AI Gateway dispatching to {provider_name} ({model}) via {key_obj.masked}{' [with images]' if images else ''}")
                result = await adapter.generate(
                    system_instruction=system_instruction,
                    messages=messages,
                    model=model,
                    api_key=key_obj.raw_key,
                    max_tokens=config.ai.max_tokens,
                    temperature=config.ai.temperature,
                    timeout=config.ai.request_timeout_seconds,
                    images=images,
                    allow_fallback=allow_fallback,
                    disable_safety=disable_safety,
                    tools=provider_tools,
                    tool_executor=tool_executor,
                    max_tool_rounds=max_tool_rounds,
                    free_only=is_fallback_key,
                    thinking_budget=thinking_budget,
                    **kwargs,
                )

                latency = (time.perf_counter() - start_ts) * 1000
                key_obj.mark_success(latency)
                if result.is_fallback:
                    log.warning(f"AI Gateway request completed via fallback ({result.fallback_reason}). Key {key_obj.masked}.")

                is_fallback = (idx > 0) or result.is_fallback
                stats.record_ai_request(
                    provider=provider_name,
                    latency_ms=latency,
                    success=True,
                    tokens=result.total_tokens,
                    is_fallback=is_fallback,
                )

                def _format_failed_provider(p: str) -> str:
                    for k, v in [("gemini", "Gemini"), ("deepseek", "DeepSeek"), ("openrouter", "OpenRouter"), ("huggingface", "Hugging Face")]:
                        if p.lower().startswith(k):
                            return p.replace(p[:len(k)], v, 1)
                    return p.title()

                is_alias_match = bool(
                    clean_override
                    and result.model_name
                    and (
                        clean_override.lower() == result.model_name.lower()
                        or (clean_override.lower() == "manus" and "manus" in result.model_name.lower())
                    )
                )
                if idx > 0:
                    result.is_fallback = True
                    result.requested_model = clean_override
                    failed_disp = ", ".join([_format_failed_provider(p) for p in attempted_providers])
                    fallback_notice = f"{failed_disp} 暫時不可用，已自動切換"
                    log.warning(f"AI Gateway successfully fell back to {provider_name}. Detailed route: {attempted_providers} -> {provider_name}")
                elif result.is_fallback or (clean_override and result.model_name and not is_alias_match):
                    result.is_fallback = True
                    req_model = clean_override or result.requested_model
                    result.requested_model = req_model
                    orig_disp = model_registry.get_display_name(req_model)
                    fallback_notice = f"{orig_disp} 暫時不可用，已自動切換"
                    log.warning(f"AI Gateway intra-provider model fallback occurred: {clean_override} -> {result.model_name}")

                # Zero Intelligence 身分人稱與真實性清洗
                from zeronexus.intelligence.identity_anchor import identity_anchor
                if result.text:
                    result.text = identity_anchor.sanitize_perspective(result.text)

                return result, fallback_notice

            except Exception as e:
                latency = (time.perf_counter() - start_ts) * 1000
                err_str = str(e)
                log.warning(f"Provider {provider_name} failed with {key_obj.masked}: {redact_secrets(err_str)}")
                is_upstream = "upstream" in err_str.lower() or "temporarily rate-limited" in err_str.lower()
                is_paid_quota = (
                    ("403" in err_str or "402" in err_str or "limit exceeded" in err_str.lower() or "credit" in err_str.lower() or "balance" in err_str.lower())
                    and provider_name == "openrouter"
                )
                if is_paid_quota and hasattr(key_obj, "mark_paid_quota_exhausted"):
                    key_obj.mark_paid_quota_exhausted()

                if is_paid_quota and provider_name == "openrouter" and allow_fallback and not is_openrouter_model_free(model):
                    try:
                        free_key = None
                        for k in pool._keys:
                            if (getattr(k, "free_only", False) or getattr(k, "is_fallback_key", False)) and k.is_available:
                                free_key = k
                                break
                        if not free_key:
                            for k in pool._keys:
                                if k.is_available:
                                    free_key = k
                                    break
                        if free_key:
                            chosen_free = OPENROUTER_STRICT_FREE_MODELS[0]
                            log.warning(
                                f"[AI Gateway In-Place Fallback] OpenRouter paid model '{model}' failed with quota error. "
                                f"In-place falling back to zero-cost key {free_key.masked} with free model '{chosen_free}'."
                            )
                            fb_start = time.perf_counter()
                            fb_result = await adapter.generate(
                                system_instruction=system_instruction,
                                messages=messages,
                                model=chosen_free,
                                api_key=free_key.raw_key,
                                max_tokens=config.ai.max_tokens,
                                temperature=config.ai.temperature,
                                timeout=config.ai.request_timeout_seconds,
                                images=images,
                                allow_fallback=True,
                                disable_safety=disable_safety,
                                tools=provider_tools,
                                tool_executor=tool_executor,
                                max_tool_rounds=max_tool_rounds,
                                free_only=True,
                            )
                            fb_latency = (time.perf_counter() - fb_start) * 1000
                            free_key.mark_success(fb_latency)
                            fb_result.is_fallback = True
                            stats.record_ai_request(
                                provider=provider_name,
                                latency_ms=fb_latency,
                                success=True,
                                tokens=fb_result.total_tokens,
                                is_fallback=True,
                            )
                            failed_disp = ", ".join([_format_failed_provider(p) for p in attempted_providers + [f"OpenRouter ({model})"]])
                            fallback_notice = f"{failed_disp} 額度耗盡，已自動切換至免費模型"
                            return fb_result, fallback_notice
                    except Exception as fb_err:
                        log.warning(f"OpenRouter in-place free fallback also failed: {fb_err}")

                is_quota = ("429" in err_str or "quota" in err_str.lower() or is_paid_quota) and not is_upstream

                if is_quota:
                    key_obj.mark_failure(is_quota=True)
                elif not is_upstream:
                    key_obj.mark_failure(is_quota=False)
                else:
                    log.info(f"Key {key_obj.masked} ({provider_name}) not penalized due to upstream model limitation.")

                stats.record_ai_request(
                    provider=provider_name,
                    latency_ms=latency,
                    success=False,
                    tokens=0,
                )
                attempted_providers.append(provider_name)

        # If all providers in fallback chain failed
        raise RuntimeError(
            f"所有 AI 提供者皆無法回應 ({', '.join(attempted_providers)})。請稍後再試或檢查 API 金鑰與額度。"
        )

    def _get_default_model(self, provider: str, has_images: bool = False) -> str:
        if provider == "gemini":
            return getattr(config.ai, "normal_vision_model", "gemini-3.1-flash-lite") if has_images else getattr(config.ai, "normal_text_model", config.ai.gemini_model)
        if provider == "manus":
            return getattr(config.ai, "manus_model", "manus")
        if provider == "cohere":
            return getattr(config.ai, "cohere_model", "command-r-plus-08-2024")
        if provider == "mistral":
            return getattr(config.ai, "mistral_model", "mistral-large-latest")
        if provider == "groq":
            return getattr(config.ai, "groq_model", "llama-3.3-70b-versatile")
        if provider == "deepseek":
            return config.ai.deepseek_model
        if provider == "openrouter":
            return config.ai.openrouter_model
        if provider == "huggingface":
            return config.ai.huggingface_model
        return getattr(config.ai, "normal_text_model", config.ai.gemini_model)

    async def health_check(self) -> Dict[str, Any]:
        """Summarizes key pool health across all configured providers."""
        provider_summaries: Dict[str, Any] = {}
        all_ok = False

        for name, pool in self.key_pools.items():
            keys_info = pool.get_status_summary()
            has_healthy = any(k["state"] == KeyState.HEALTHY.value for k in keys_info)
            if has_healthy:
                all_ok = True

            provider_summaries[name] = {
                "active": pool.has_active_keys,
                "total_keys": len(keys_info),
                "keys": keys_info,
                "default_model": self._get_default_model(name),
            }

        return {
            "name": "AI 閘道 (AI Gateway)",
            "icon": "🟢" if all_ok else "🟡",
            "providers": provider_summaries,
        }

    async def close(self) -> None:
        """Closes all underlying adapter HTTP client connections."""
        for adapter in self.adapters.values():
            if hasattr(adapter, "close") and callable(adapter.close):
                await adapter.close()


# Singleton AI Gateway instance
ai_gateway = AIGateway()
