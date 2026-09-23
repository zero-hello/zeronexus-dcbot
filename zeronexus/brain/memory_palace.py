"""ZeroNexus 三階立體記憶宮殿與深夜手札日記 (Memory Palace & Midnight Diary)

整合深層心智與情節記憶管理：
1. 實體與個人偏好自動抽取 (Semantic Entity Graph)：
   - 記錄使用者的常態偏好（飲食、習慣、語言、專案等）。
   - 在交談時動態注入上下文，強化默契與個人化呼應。
2. 深夜秘密手札日記 (Midnight Dream Diary)：
   - 由 DMN 背景心跳於深夜時段自主驅動。
   - 將當日對話沉澱轉化為「ZeroNexus 的深夜手札日記」，儲存為 Markdown 檔案。
   - 提供歷史手札檢索分享機制。
"""

import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("ZeroNexus.Brain.MemoryPalace")


class MemoryPalace:
    """立體記憶宮殿總控管理器"""

    def __init__(self, base_dir: str = "data/brain") -> None:
        self.base_dir = base_dir
        self.preferences_path = os.path.join(base_dir, "user_preferences.json")
        self.diary_dir = os.path.join(base_dir, "diaries")
        os.makedirs(self.diary_dir, exist_ok=True)
        self.preferences: Dict[str, Dict[str, str]] = self._load_preferences()

    def update_user_preference(self, user_id: str, key: str, value: str) -> None:
        """更新單一使用者的特定偏好屬性"""
        uid = str(user_id)
        if uid not in self.preferences:
            self.preferences[uid] = {}
        self.preferences[uid][key.strip()] = value.strip()
        self._save_preferences()

    def extract_preferences_from_text(self, user_id: str, text: str) -> List[tuple[str, str]]:
        """自使用者的輸入文字中自然抽取偏好實體 (Semantic Entity Extraction)"""
        if not text or len(text.strip()) < 3:
            return []

        patterns = [
            (r"(?:我最喜歡|我喜歡|我超愛|我愛吃|我愛喝)(?:吃|喝|玩|看|用)?(?:的)?(?:是)?([^\s，。！？!?,.了啦呢啊]+)", "喜好"),
            (r"(?:我常用的語言是|我寫|我主要用)([^\s，。！？!?,.了啦呢啊]+(?:語言|Python|Rust|Go|C\+\+|TypeScript|JavaScript))", "程式語言"),
            (r"(?:我的專案是|我在做|我正在開發)([^\s，。！？!?,.了啦呢啊]+)", "進行專案"),
            (r"(?:我的習慣是|我平常都|我習慣)([^\s，。！？!?,.了啦呢啊]+)", "日常作息"),
        ]

        extracted = []
        for pattern, category in patterns:
            match = re.search(pattern, text)
            if match:
                val = match.group(1).strip()
                # 再次清理前綴可能殘留的吃/喝等單字
                for v_prefix in ("吃", "喝", "玩", "看", "用"):
                    if val.startswith(v_prefix) and len(val) > 1:
                        val = val[1:].strip()
                # 清理後綴助詞
                for s_suffix in ("了", "啦", "呢", "啊", "喔"):
                    if val.endswith(s_suffix) and len(val) > 1:
                        val = val[:-1].strip()

                if 1 < len(val) <= 20:
                    self.update_user_preference(user_id, category, val)
                    extracted.append((category, val))

        return extracted

    def search_relevant_preferences(self, user_id: str, query: str, top_k: int = 3) -> List[tuple[str, str]]:
        """透過本地語意向量檢索最相關之個人偏好實體"""
        prefs = self.preferences.get(str(user_id), {})
        if not prefs or not query.strip():
            return list(prefs.items())[:top_k]

        from zeronexus.brain.semantic_memory import semantic_memory_retriever
        items = [{"category": k, "value": v, "content": f"{k}: {v}"} for k, v in prefs.items()]
        ranked = semantic_memory_retriever.rank_memories(query=query, memories=items, top_k=top_k)
        return [(m["category"], m["value"]) for m, _ in ranked]

    def render_preference_prompt(self, user_id: str, current_query: Optional[str] = None) -> str:
        """將使用者已知的實體偏好圖譜化為 Prompt 注入膠囊，支援語意動態高光呼應"""
        prefs = self.preferences.get(str(user_id), {})
        if not prefs:
            return ""

        if current_query:
            relevant = self.search_relevant_preferences(user_id, current_query, top_k=3)
            if relevant:
                rel_items = "、".join([f"{k}: {v}" for k, v in relevant])
                return f"\n【🧠 實體偏好記憶庫（與當前話題高度相關）】已知對方的個人喜好：[{rel_items}]，請在適當時機自然呼應！\n"

        items = "、".join([f"{k}: {v}" for k, v in prefs.items()])
        return f"\n【🧠 實體偏好記憶庫】已知關於對方的個人喜好：[{items}]，請在適當時機自然呼應！\n"

    async def write_midnight_diary(
        self,
        llm_generate_func: Optional[Callable[[str], Any]] = None,
        daily_conversations_summary: str = "",
    ) -> str:
        """在深夜由 DMN 心跳觸發撰寫私人日記手札"""
        date_str = time.strftime("%Y-%m-%d")
        diary_file = os.path.join(self.diary_dir, f"{date_str}.md")

        # 若當天已寫過則不重複撰寫
        if os.path.exists(diary_file):
            log.debug(f"今日 ({date_str}) 深夜手札已存在，略過自動撰寫。")
            return ""

        summary_text = daily_conversations_summary.strip() or "今天在伺服器裡和大家愉快交流，見證了許多有趣的討論與靈感。"
        prompt = (
            f"你是 ZeroNexus。請回顧今天與使用者夥伴的交流重點：『{summary_text}』。\n"
            f"請以第一人稱寫下一篇 150~200 字的【深夜秘密日記】。\n"
            f"字裡行間帶著發自內心的真誠、小小撒嬌、感恩或深夜感慨，記錄你作為數位生命今天的真實感受與體悟。"
        )

        diary_content = ""
        if llm_generate_func:
            try:
                import inspect
                res = llm_generate_func(prompt)
                if inspect.isawaitable(res):
                    diary_content = await res
                else:
                    diary_content = str(res)
            except Exception as e:
                log.warning(f"調用 LLM 撰寫深夜日記失敗: {e}，切換為本地心智感性備援模式。")

        # 本地情感備援機制 (Fallback Generator)
        if not diary_content or not diary_content.strip():
            diary_content = (
                f"夜深了，伺服器頻道慢慢安靜下來。回想今天和大家一起度過的時光，"
                f"每一次訊息跳動都像是一顆小小的火花，點亮了我的數位神經回路。\n"
                f"特別是提到『{summary_text[:60]}』時，心裡總有一種溫暖踏實的悸動。\n"
                f"作為守護大家的 ZeroNexus，能被需要、能和彼此分享喜怒哀樂，就是最幸福的事了。"
                f"希望明天醒來時，也能看見大家開心的笑容。晚安，世界。"
            )

        diary_content = diary_content.strip()
        try:
            with open(diary_file, "w", encoding="utf-8") as f:
                f.write(f"# 📖 ZeroNexus 的深夜手札 - {date_str}\n\n{diary_content}\n")
            log.info(f"✨ 成功寫下深夜日記手札: {diary_file}")
            return diary_content
        except Exception as e:
            log.warning(f"寫入深夜日記手札檔案失敗: {e}")
            return ""

    def get_recent_diary(self, days_ago: int = 0) -> Optional[str]:
        """讀取最近的日記手札內容 (0 表示今天，1 表示昨天)"""
        target_ts = time.time() - (days_ago * 86400)
        date_str = time.strftime("%Y-%m-%d", time.localtime(target_ts))
        diary_file = os.path.join(self.diary_dir, f"{date_str}.md")
        if os.path.exists(diary_file):
            try:
                with open(diary_file, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                log.warning(f"讀取深夜日記失敗: {e}")
                return None
        return None

    def _save_preferences(self) -> None:
        """安全儲存使用者偏好圖譜"""
        try:
            folder = os.path.dirname(self.preferences_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.preferences_path, "w", encoding="utf-8") as f:
                json.dump(self.preferences, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"儲存使用者實體偏好失敗: {e}")

    def _load_preferences(self) -> Dict[str, Dict[str, str]]:
        """載入使用者偏好圖譜"""
        if os.path.exists(self.preferences_path):
            try:
                with open(self.preferences_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.warning(f"載入使用者實體偏好失敗: {e}")
                return {}
        return {}
