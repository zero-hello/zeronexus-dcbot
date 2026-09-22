"""ZeroNexus Cohere API 外部服務整合模組。

提供：
1. Cohere Rerank 多語言語意重排序服務（支援官方 SDK 與輕量 HTTP 降級方案）。
2. 超時防護與全域例外攔截，確保在金鑰未配置或連線異常時優雅降級（Graceful Fallback）。
3. 全域單例 `cohere_service`，供海馬迴情節記憶與全域記憶搜尋調用。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
import httpx

from zeronexus.core.logger import log

# 嘗試載入官方 Cohere SDK（選用）
try:
    import cohere
    _COHERE_SDK_AVAILABLE = True
except ImportError:
    cohere = None  # type: ignore
    _COHERE_SDK_AVAILABLE = False


class CohereService:
    """Cohere API 核心服務類別，支援語意重排與模型呼叫。"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key: str = (api_key or os.getenv("COHERE_API_KEY", "")).strip()
        self._client: Optional[Any] = None
        self._timeout: float = 8.0  # 預設 8 秒超時防護

        if self._api_key and _COHERE_SDK_AVAILABLE:
            try:
                # 優先使用 Cohere 官方最新 V2 客戶端，若無則降級為 V1
                if hasattr(cohere, "ClientV2"):
                    self._client = cohere.ClientV2(api_key=self._api_key)
                else:
                    self._client = cohere.Client(api_key=self._api_key)
            except Exception as e:
                log.warning(f"初始化 Cohere SDK 客戶端失敗，將降級為 HTTP 調用模式: {e}")
                self._client = None

    @property
    def is_available(self) -> bool:
        """檢查 Cohere 服務是否具備有效金鑰可供調用。"""
        return bool(self._api_key)

    def _fallback_documents(self, documents: List[str], top_n: int) -> List[Dict[str, Any]]:
        """在重排失敗或未啟用時，回傳維持原始輸入順序的降級列表。"""
        clamped_n = min(len(documents), top_n)
        return [
            {
                "index": i,
                "relevance_score": round(1.0 - (i * 0.05), 4),
                "document": documents[i],
            }
            for i in range(clamped_n)
        ]

    async def rerank_async(
        self,
        query: str,
        documents: List[str],
        top_n: int = 3,
        model: str = "rerank-multilingual-v3.0",
    ) -> List[Dict[str, Any]]:
        """非同步呼叫 Cohere Rerank API 進行多語言語意關聯度重排。

        若金鑰未設定、文本清單為空或發生網路超時錯誤，自動優雅降級回傳原始文件清單。
        """
        if not documents:
            return []

        if not self.is_available:
            return self._fallback_documents(documents, top_n)

        # 若文件數量小於等於 1，直接包裝回傳，無需浪費 API 額度
        if len(documents) <= 1:
            return self._fallback_documents(documents, top_n)

        clamped_top_n = min(len(documents), top_n)

        # 優先嘗試透過官方 SDK 進行重排
        if self._client is not None:
            try:
                loop = asyncio.get_running_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self._client.rerank(
                            model=model,
                            query=query,
                            documents=documents,
                            top_n=clamped_top_n,
                        ),
                    ),
                    timeout=self._timeout,
                )

                ranked_results: List[Dict[str, Any]] = []
                results_attr = getattr(response, "results", None) or []
                for item in results_attr:
                    idx = getattr(item, "index", 0)
                    score = float(getattr(item, "relevance_score", 0.0))
                    ranked_results.append({
                        "index": idx,
                        "relevance_score": score,
                        "document": documents[idx] if idx < len(documents) else "",
                    })
                if ranked_results:
                    return ranked_results
            except Exception as exc:
                log.warning(f"Cohere SDK Rerank 調用失敗 ({exc})，將嘗試 HTTP 降級模式。")

        # 降級或無 SDK 時使用純非同步 HTTP REST 呼叫
        try:
            url = "https://api.cohere.com/v2/rerank"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ZeroNexus-Bot/1.9.0",
            }
            payload = {
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": clamped_top_n,
            }

            async with httpx.AsyncClient(timeout=self._timeout) as http_client:
                res = await http_client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    ranked_results = []
                    for item in data.get("results", []):
                        idx = item.get("index", 0)
                        score = float(item.get("relevance_score", 0.0))
                        ranked_results.append({
                            "index": idx,
                            "relevance_score": score,
                            "document": documents[idx] if idx < len(documents) else "",
                        })
                    return ranked_results
                else:
                    log.warning(f"Cohere HTTP Rerank 伺服器回傳狀態碼 {res.status_code}: {res.text[:120]}")
        except Exception as e:
            log.warning(f"Cohere Rerank API 請求超時或連線異常: {e}，自動啟動優雅降級。")

        # 所有嘗試均失敗時退回原始順序
        return self._fallback_documents(documents, top_n)

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: int = 3,
        model: str = "rerank-multilingual-v3.0",
    ) -> List[Dict[str, Any]]:
        """同步包裝之 Rerank 方法（支援在已存在事件循環或純同步環境中安全調用）。"""
        if not documents:
            return []

        if not self.is_available:
            return self._fallback_documents(documents, top_n)

        try:
            # 檢查當前執行緒是否已有正在執行的 event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 若已有運行中循環，使用 ThreadPoolExecutor 避免阻塞
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.rerank_async(query, documents, top_n=top_n, model=model),
                    )
                    return future.result(timeout=self._timeout + 1.0)
            else:
                return asyncio.run(
                    self.rerank_async(query, documents, top_n=top_n, model=model)
                )
        except Exception as e:
            log.warning(f"Cohere 同步重排包裝執行異常: {e}，退回原始順序。")
            return self._fallback_documents(documents, top_n)


# 全域單例服務實例
cohere_service = CohereService()
