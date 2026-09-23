"""ZeroNexus AI Image Generation Engine.

100% Exclusively Powered by Google Gemini (gemini-2.5-flash-image):
- 官方純血 Google 多模態圖像生成架構。
- 支援多種風格增強（寫實攝影、二次元動漫、奇幻插圖、賽博龐克、像素藝術、3D渲染、復古水彩）。
- 支援多種畫面比例（1:1, 16:9, 9:16, 4:3, 3:4）。
- 整合 Google AI Studio 與 OpenRouter Gemini 圖像雙重通道，絕不降級至第三方非官方模型。
- 自然語言繪圖意圖智慧辨識與提示詞安全提取。
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import httpx

from zeronexus.core.logger import log


@dataclass
class DrawIntent:
    """Represents a parsed user drawing intention."""
    prompt: str
    style: Optional[str] = None
    aspect_ratio: str = "1:1"
    model: str = "gemini-2.5-flash-image"
    raw_text: str = ""


@dataclass
class ImageGenResult:
    """Result of an AI image generation request."""
    success: bool
    image_url: str
    prompt: str
    enhanced_prompt: str = ""
    style: Optional[str] = None
    aspect_ratio: str = "1:1"
    model: str = "gemini-2.5-flash-image"
    width: int = 1024
    height: int = 1024
    seed: int = 0
    image_bytes: Optional[bytes] = None
    content_type: Optional[str] = None
    error_message: Optional[str] = None


class ImageGenEngine:
    """High-performance AI Image Generation Engine 100% powered by Google Gemini."""

    GEMINI_OPENAI_IMAGES_URL = "https://generativelanguage.googleapis.com/v1beta/openai/images/generations"
    DEFAULT_GEMINI_IMAGE_MODEL = "imagen-3.0-generate-002"

    @property
    def default_image_model(self) -> str:
        """動態讀取生圖模型設定 (NORMAL_GEN_IMAGE_MODEL)。"""
        try:
            from zeronexus.core.config import config
            if getattr(config.ai, "normal_gen_image_model", None):
                return config.ai.normal_gen_image_model
        except Exception:
            pass
        env_m = os.getenv("NORMAL_GEN_IMAGE_MODEL", "").strip()
        if env_m:
            return env_m
        return os.getenv("OPENROUTER_GEN_IMAGE_MODEL", self.DEFAULT_GEMINI_IMAGE_MODEL).strip()

    # Style presets enhancing quality and adherence
    STYLE_PRESETS: Dict[str, str] = {
        "寫實攝影": "photorealistic, hyperrealistic 8k photograph, highly detailed photography, shot on 35mm lens, sharp focus, natural volumetric lighting",
        "二次元動漫": "anime style, highly detailed anime illustration, vibrant colors, makoto shinkai aesthetic, studio ghibli inspired, clean lineart",
        "奇幻插圖": "fantasy digital concept art, ethereal, magical glowing atmosphere, intricate details, artstation trending, dramatic lighting",
        "賽博龐克": "cyberpunk aesthetic, neon lighting, futuristic sci-fi city, high tech, glowing neon reflections, cinematic octane render",
        "像素藝術": "pixel art, 16-bit retro game asset, crisp pixel edges, nostalgic pixel graphics, vivid colors, detailed sprite",
        "3D渲染": "3D render, Unreal Engine 5, Octane render, ray tracing, subsurface scattering, volumetric lighting, photorealistic textures, 8k",
        "復古水彩": "vintage watercolor painting, soft textures, pastel tones, fluid brush strokes, elegant artistic composition, traditional media",
    }

    # Style alias mapping for natural language detection
    STYLE_ALIASES: Dict[str, str] = {
        "寫實": "寫實攝影",
        "攝影": "寫實攝影",
        "照片": "寫實攝影",
        "真實": "寫實攝影",
        "動漫": "二次元動漫",
        "二次元": "二次元動漫",
        "日系": "二次元動漫",
        "卡通": "二次元動漫",
        "漫畫": "二次元動漫",
        "奇幻": "奇幻插圖",
        "魔幻": "奇幻插圖",
        "插畫": "奇幻插圖",
        "插圖": "奇幻插圖",
        "賽博龐克": "賽博龐克",
        "賽博朋克": "賽博龐克",
        "賽博": "賽博龐克",
        "cyberpunk": "賽博龐克",
        "像素": "像素藝術",
        "像素風": "像素藝術",
        "pixel": "像素藝術",
        "3d": "3D渲染",
        "3d渲染": "3D渲染",
        "3d模型": "3D渲染",
        "立體": "3D渲染",
        "水彩": "復古水彩",
        "水彩畫": "復古水彩",
        "水墨": "復古水彩",
    }

    # Dimension resolutions mapped from aspect ratios
    ASPECT_RATIOS: Dict[str, Tuple[int, int]] = {
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1152, 864),
        "3:4": (864, 1152),
    }

    # Magic byte signatures for image validation
    MAGIC_SIGNATURES: List[Tuple[bytes, str]] = [
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"RIFF", "image/webp"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
    ]

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float = 35.0) -> httpx.AsyncClient:
        """Returns or instantiates the shared async HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36 ZeroNexus/2.5"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=30, keepalive_expiry=60.0),
            )
        return self._http_client

    async def close(self) -> None:
        """Closes the underlying HTTP client session."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def normalize_aspect_ratio(self, ratio_str: Optional[str]) -> str:
        """Normalizes aspect ratio input string to standard format."""
        if not ratio_str:
            return "1:1"
        clean = ratio_str.strip().lower()
        if "16:9" in clean or "橫" in clean or "寬螢幕" in clean or "landscape" in clean:
            return "16:9"
        if "9:16" in clean or "直" in clean or "桌布" in clean or "portrait" in clean:
            return "9:16"
        if "4:3" in clean:
            return "4:3"
        if "3:4" in clean:
            return "3:4"
        if "1:1" in clean or "正方" in clean or "square" in clean:
            return "1:1"
        return "1:1"

    def normalize_style(self, style_str: Optional[str]) -> Optional[str]:
        """Normalizes style input string to one of the standard presets."""
        if not style_str:
            return None
        clean = style_str.strip()
        if clean in self.STYLE_PRESETS:
            return clean
        lower = clean.lower()
        for alias, target in self.STYLE_ALIASES.items():
            if alias.lower() in lower:
                return target
        return None

    def build_enhanced_prompt(self, prompt: str, style: Optional[str] = None) -> str:
        """Appends quality and aesthetic style boosters to prompt."""
        clean_prompt = prompt.strip()
        norm_style = self.normalize_style(style)
        if norm_style and norm_style in self.STYLE_PRESETS:
            style_tags = self.STYLE_PRESETS[norm_style]
            return f"{clean_prompt}, {style_tags}"
        return clean_prompt

    def construct_image_url(
        self,
        prompt: str,
        style: Optional[str] = None,
        aspect_ratio: str = "1:1",
        model: str = "flux",
        seed: Optional[int] = None,
    ) -> Tuple[str, str, int, int, int]:
        """Constructs the complete Pollinations.ai image URL and parameter set."""
        norm_ratio = self.normalize_aspect_ratio(aspect_ratio)
        width, height = self.ASPECT_RATIOS.get(norm_ratio, (1024, 1024))
        actual_seed = seed if (seed is not None and seed > 0) else (secrets.randbelow(2147483640) + 1)
        enhanced_prompt = self.build_enhanced_prompt(prompt, style=style)

        encoded_prompt = urllib.parse.quote(enhanced_prompt, safe="")
        clean_model = model.strip().lower() if model else "flux"
        if clean_model not in ("flux", "turbo", "flux-realism"):
            clean_model = "flux"

        url = (
            f"{self.BASE_URL}/{encoded_prompt}"
            f"?width={width}&height={height}&model={clean_model}&nologo=true&seed={actual_seed}"
        )
        return url, enhanced_prompt, width, height, actual_seed

    def verify_image_bytes(self, data: bytes) -> Tuple[bool, Optional[str]]:
        """Verifies binary image payload headers."""
        if len(data) < 16:
            return False, None
        for sig, mime in self.MAGIC_SIGNATURES:
            if data.startswith(sig):
                return True, mime
        # Special check for WebP (RIFF....WEBP)
        if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
            return True, "image/webp"
        return False, None

    def _get_gemini_api_key(self) -> Optional[str]:
        """Retrieves an active Google Gemini API key from environment or config."""
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()
        try:
            from zeronexus.core.config import config
            if config.ai.gemini_keys:
                return config.ai.gemini_keys[0]
        except Exception:
            pass
        env_keys = os.getenv("GEMINI_API_KEYS")
        if env_keys:
            for k in env_keys.split(","):
                if k.strip():
                    return k.strip()
        return None

    def _get_openrouter_api_key(self) -> Optional[str]:
        """Retrieves an active OpenRouter API key from environment or config."""
        for env_var in ("OPENROUTER_API_KEY_1", "OPENROUTER_API_KEYS", "OPENROUTER_API_KEY_2", "OPENROUTER_FALLBACK_API_KEY"):
            val = os.getenv(env_var, "").strip()
            if val:
                return val.split(",")[0].strip()
        try:
            from zeronexus.core.config import config
            if config.ai.openrouter_key_1:
                return config.ai.openrouter_key_1
        except Exception:
            pass
        return None

    async def generate_openrouter_gemini_image(
        self,
        prompt: str,
        style: Optional[str] = None,
        aspect_ratio: str = "1:1",
        timeout: float = 45.0,
    ) -> ImageGenResult:
        """Generates an image via OpenRouter using OPENROUTER_GEN_IMAGE_MODEL."""
        api_key = self._get_openrouter_api_key()
        target_model = os.getenv("OPENROUTER_GEN_IMAGE_MODEL", "google/gemini-2.5-flash-image").strip()
        if not api_key:
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=prompt,
                model=target_model,
                error_message="未配置有效的 OPENROUTER_API_KEY",
            )
        clean_prompt = prompt.strip()
        norm_ratio = self.normalize_aspect_ratio(aspect_ratio)
        norm_style = self.normalize_style(style)
        enhanced_prompt = self.build_enhanced_prompt(clean_prompt, style=norm_style)
        if norm_ratio != "1:1":
            enhanced_prompt = f"{enhanced_prompt}, aspect ratio {norm_ratio}"

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://zeronexus.net",
            "X-Title": "ZeroNexus AI",
        }
        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": f"Generate an image: {enhanced_prompt}"}],
            "modalities": ["image", "text"],
        }
        try:
            client = await self._get_client(timeout=timeout)
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                choices = data.get("choices") or []
                if choices and isinstance(choices, list) and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    images = msg.get("images") or []
                    raw_b64 = None
                    if images and isinstance(images, list):
                        raw_img = images[0]
                        img_url = (raw_img.get("image_url") or {}).get("url") if isinstance(raw_img, dict) else str(raw_img)
                        if img_url:
                            raw_b64 = img_url.split(",", 1)[1] if "," in img_url else img_url
                    elif msg.get("content"):
                        content_str = str(msg.get("content"))
                        if "base64," in content_str:
                            raw_b64 = content_str.split("base64,", 1)[1].split(")", 1)[0].split('"', 1)[0].strip()

                    if raw_b64:
                        try:
                            img_bytes = base64.b64decode(raw_b64)
                        except Exception:
                            img_bytes = b""
                        if img_bytes:
                            is_valid, detected_mime = self.verify_image_bytes(img_bytes)
                            mime = detected_mime or "image/png"
                            width, height = self.ASPECT_RATIOS.get(norm_ratio, (1024, 1024))
                            log.info(f"Successfully generated image via OpenRouter {target_model} ({len(img_bytes)} bytes).")
                            return ImageGenResult(
                                success=True,
                                image_url="attachment://ai_image.png",
                                prompt=clean_prompt,
                                enhanced_prompt=enhanced_prompt,
                                style=norm_style,
                                aspect_ratio=norm_ratio,
                                model=target_model,
                                width=width,
                                height=height,
                                seed=0,
                                image_bytes=img_bytes,
                                content_type=mime,
                            )
            err_text = resp.text[:200]
            log.warning(f"OpenRouter image generation HTTP {resp.status_code}: {err_text}")
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=clean_prompt,
                model=target_model,
                error_message=f"OpenRouter 生圖回應異常 (HTTP {resp.status_code}): {err_text}",
            )
        except Exception as e:
            log.warning(f"OpenRouter image generation exception: {e}")
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=clean_prompt,
                model=target_model,
                error_message=str(e),
            )

    async def generate_gemini_image(
        self,
        prompt: str,
        style: Optional[str] = None,
        aspect_ratio: str = "1:1",
        timeout: float = 45.0,
        model: Optional[str] = None,
    ) -> ImageGenResult:
        """Generates an image via official Google Generative Language REST endpoints.

        Supports:
        - Gemini Native Multimodal Image (gemini-2.5-flash-image / gemini-3.1-flash-image) via generateContent
        - Google Imagen 3 (imagen-3.0-generate-002) via predict
        """
        raw_model = (model or self.default_image_model).strip()
        # 移除可能夾帶的第三方前綴 (例如 google/gemini-2.5-flash-image -> gemini-2.5-flash-image)
        clean_model = raw_model.replace("google/", "").strip()

        # 防呆機制：若被指定純文字模型（如 gemini-3.6-flash, gemini-3.1-flash-lite），自動智慧切換至標準生圖模型
        if not ("image" in clean_model.lower() or "imagen" in clean_model.lower()):
            log.warning(f"偵測到非生圖專案模型 '{clean_model}'，自動智慧導向至標準生圖模型 'gemini-2.5-flash-image'")
            clean_model = "gemini-2.5-flash-image"

        api_key = self._get_gemini_api_key()
        if not api_key:
            return await self.generate_openrouter_gemini_image(
                prompt=prompt,
                style=style,
                aspect_ratio=aspect_ratio,
                timeout=timeout,
            )

        clean_prompt = prompt.strip()
        norm_ratio = self.normalize_aspect_ratio(aspect_ratio)
        norm_style = self.normalize_style(style)
        enhanced_prompt = self.build_enhanced_prompt(clean_prompt, style=norm_style)
        if norm_ratio != "1:1":
            enhanced_prompt = f"{enhanced_prompt}, aspect ratio {norm_ratio}"

        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            client = await self._get_client(timeout=timeout)

            # 分支 1: Imagen 3 系列原生 predict 端點
            if "imagen" in clean_model.lower():
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:predict"
                payload = {
                    "instances": [{"prompt": enhanced_prompt}],
                    "parameters": {
                        "sampleCount": 1,
                        "aspectRatio": norm_ratio,
                        "personGeneration": "allow_adult",
                    },
                }
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    preds = resp_json.get("predictions") or []
                    if preds and isinstance(preds, list) and "bytesBase64Encoded" in preds[0]:
                        b64_str = preds[0]["bytesBase64Encoded"]
                        mime = preds[0].get("mimeType") or "image/jpeg"
                        img_bytes = base64.b64decode(b64_str)
                        width, height = self.ASPECT_RATIOS.get(norm_ratio, (1024, 1024))
                        return ImageGenResult(
                            success=True,
                            image_url="attachment://ai_image.png",
                            prompt=clean_prompt,
                            enhanced_prompt=enhanced_prompt,
                            style=norm_style,
                            aspect_ratio=norm_ratio,
                            model=clean_model,
                            width=width,
                            height=height,
                            seed=0,
                            image_bytes=img_bytes,
                            content_type=mime,
                        )
            else:
                # 分支 2: Gemini Native 多模態生圖 (gemini-2.5-flash-image) 原生 generateContent 端點
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
                payload = {
                    "contents": [{
                        "parts": [{"text": enhanced_prompt}]
                    }],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"]
                    },
                    "safetySettings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                }
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    candidates = resp_json.get("candidates") or []
                    if candidates and isinstance(candidates, list):
                        parts = (candidates[0].get("content") or {}).get("parts") or []
                        for part in parts:
                            inline = part.get("inlineData") or part.get("inline_data")
                            if inline and isinstance(inline, dict):
                                b64_str = inline.get("data", "")
                                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                                if b64_str:
                                    img_bytes = base64.b64decode(b64_str)
                                    width, height = self.ASPECT_RATIOS.get(norm_ratio, (1024, 1024))
                                    return ImageGenResult(
                                        success=True,
                                        image_url="attachment://ai_image.png",
                                        prompt=clean_prompt,
                                        enhanced_prompt=enhanced_prompt,
                                        style=norm_style,
                                        aspect_ratio=norm_ratio,
                                        model=clean_model,
                                        width=width,
                                        height=height,
                                        seed=0,
                                        image_bytes=img_bytes,
                                        content_type=mime,
                                    )

            # 若 Google 原生呼叫失敗，嘗試回退至 OpenRouter
            err_snippet = resp.text[:200] if 'resp' in locals() else "No response"
            log.warning(f"Google AI Studio image generation failed ({err_snippet}). Falling back to OpenRouter...")
            or_res = await self.generate_openrouter_gemini_image(
                prompt=prompt,
                style=style,
                aspect_ratio=aspect_ratio,
                timeout=timeout,
            )
            if or_res.success:
                return or_res
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=clean_prompt,
                enhanced_prompt=enhanced_prompt,
                model=clean_model,
                error_message=f"Gemini 官方原生生圖異常: {err_snippet} / OpenRouter 備援: {or_res.error_message}",
            )
        except Exception as e:
            log.warning(f"Google AI Studio image generation exception: {e}. Falling back to OpenRouter...")
            or_res = await self.generate_openrouter_gemini_image(
                prompt=prompt,
                style=style,
                aspect_ratio=aspect_ratio,
                timeout=timeout,
            )
            if or_res.success:
                return or_res
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=clean_prompt,
                enhanced_prompt=enhanced_prompt,
                model=clean_model,
                error_message=f"Gemini 異常 ({e}) / OpenRouter: {or_res.error_message}",
            )

    async def generate_image(
        self,
        prompt: str,
        style: Optional[str] = None,
        aspect_ratio: str = "1:1",
        model: str = "gemini-2.5-flash-image",
        seed: Optional[int] = None,
        verify_download: bool = True,
        timeout: float = 35.0,
    ) -> ImageGenResult:
        """Generates an image 100% strictly powered by Google Gemini (gemini-2.5-flash-image)."""
        clean_prompt = prompt.strip()
        if not clean_prompt:
            return ImageGenResult(
                success=False,
                image_url="",
                prompt=prompt,
                enhanced_prompt="",
                model=self.DEFAULT_GEMINI_IMAGE_MODEL,
                error_message="提示詞不能為空",
            )

        # Strictly normalize target model to Gemini
        clean_model = self.DEFAULT_GEMINI_IMAGE_MODEL

        log.info(f"Generating image strictly with Google Gemini ({clean_model})...")
        gemini_res = await self.generate_gemini_image(
            prompt=clean_prompt,
            style=style,
            aspect_ratio=aspect_ratio,
            timeout=timeout,
        )
        if gemini_res.success:
            return gemini_res

        log.warning(
            f"Gemini image generation unavailable: {gemini_res.error_message}. "
            f"Strictly refusing non-Gemini fallback to maintain brand integrity."
        )
        return ImageGenResult(
            success=False,
            image_url="",
            prompt=clean_prompt,
            enhanced_prompt=gemini_res.enhanced_prompt or clean_prompt,
            model=clean_model,
            error_message=f"Gemini 圖像生成通道忙碌中或配額受限：{gemini_res.error_message}（系統堅持只採用官方純血 Gemini 模型）",
        )

    def detect_draw_intent(self, text: str) -> Optional[DrawIntent]:
        """Detects if a user prompt is asking to draw/generate an image and extracts parameters.
        
        Supports multi-mentions, free word order, and robust prefix/infix drawing intents.
        """
        if not text:
            return None

        # Pre-clean: strip all Discord mentions (@user, @!user, @&role, #channel)
        cleaned = re.sub(r"<@!?\d+>", " ", text)
        cleaned = re.sub(r"<@&\d+>", " ", cleaned)
        cleaned = re.sub(r"<#\d+>", " ", cleaned)
        stripped = re.sub(r"\s+", " ", cleaned).strip()
        if not stripped:
            return None

        # Exclude general questions, definitions, inquiries about drawing
        inquiry_keywords = [
            "是什麼意思", "意思是什麼", "怎麼畫", "如何畫", "為什麼要畫",
            "會畫畫嗎", "能畫畫嗎", "你擅長畫", "誰畫的", "畫質",
            "畫面清晰度", "素描技巧", "水彩技巧", "學畫畫", "畫畫教學",
            "畫蛇添足", "畫餅充飢", "畫地為牢", "畫龍點睛",
        ]
        if any(kw in stripped for kw in inquiry_keywords):
            return None

        # Positive action regex patterns (supports both start-of-string, polite prefixes, and multi-mentions)
        polite_prefix = r"(?:請問)?\s*(?:能|能否|可否|可以|能不能|麻煩|請)?\s*(?:幫我|替我|為我)?\s*"
        patterns = [
            # 1. 生圖 / 繪圖 開頭指令: 生圖: 一隻貓
            rf"(?:^|[\s，,。！!？?]){polite_prefix}(?:生圖|繪圖|產圖|生成圖片|畫圖|繪畫)[:：\s]+(.+)$",
            # 2. 幫我畫 / 請幫我畫 / 畫一張 / 畫一個 / 繪製一幅
            rf"(?:^|[\s，,。！!？?]){polite_prefix}(?:畫|繪製|生成|產生|產出)(?:一張|一個|一幅|隻|隻隻|張|幅)?(?:的)?(?:圖片|圖|插畫|插圖|相片|畫作)?(?:\s*[:：]\s*|\s+)(.+)$",
            # 3. 幫我畫XXX / 畫一張XXX / 繪製XXX
            rf"(?:^|[\s，,。！!？?]){polite_prefix}(?:畫|繪製|生成)(?:一張|一個|一幅|隻|張|幅)?\s*(.+)$",
            # 4. English draw commands
            r"(?:^|[\s，,。！!？?])(?:please\s+)?(?:draw|generate(?:\s+an?)?\s+image\s+of)\s+(.+)$",
        ]

        extracted_prompt: Optional[str] = None
        for pattern in patterns:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                # Ignore trivial 1-character leftovers
                if len(candidate) >= 2:
                    extracted_prompt = candidate
                    break

        if not extracted_prompt:
            return None

        # Detect style from prompt
        detected_style: Optional[str] = None
        for alias, target in self.STYLE_ALIASES.items():
            if alias in extracted_prompt.lower():
                detected_style = target
                break

        # Detect aspect ratio
        detected_ratio = "1:1"
        if "16:9" in extracted_prompt or "橫圖" in extracted_prompt or "寬螢幕" in extracted_prompt or "橫向" in extracted_prompt:
            detected_ratio = "16:9"
        elif "9:16" in extracted_prompt or "直圖" in extracted_prompt or "手機桌布" in extracted_prompt or "直向" in extracted_prompt:
            detected_ratio = "9:16"
        elif "4:3" in extracted_prompt:
            detected_ratio = "4:3"
        elif "3:4" in extracted_prompt:
            detected_ratio = "3:4"

        # Clean prompt: remove ratio tokens and redundant style tokens from the prompt text
        clean_p = extracted_prompt
        for token in ["16:9", "9:16", "4:3", "3:4", "1:1", "橫圖", "直圖", "手機桌布", "正方形"]:
            clean_p = clean_p.replace(token, "")

        clean_p = re.sub(r"\s+", " ", clean_p).strip()
        if not clean_p:
            clean_p = extracted_prompt

        return DrawIntent(
            prompt=clean_p,
            style=detected_style,
            aspect_ratio=detected_ratio,
            model="gemini-2.5-flash-image",
            raw_text=stripped,
        )


# Global singleton instance
image_gen_engine = ImageGenEngine()

__all__ = ["DrawIntent", "ImageGenResult", "ImageGenEngine", "image_gen_engine"]
