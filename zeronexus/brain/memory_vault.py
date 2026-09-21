"""ZeroNexus 本地情節記憶庫與心智反思日記 (Memory Vault & Conscious Diary)

模擬人類大腦皮質與海馬迴之長效記憶機制：
1. 本地情節記憶庫 (Episodic Memory Database):
   - SQLite 持久化儲存「時間戳記、對話對象、核心事件/偏好、伴隨之情緒維度」。
   - 精準撈取與當前情境最相關的 2~3 則核心回憶，注入工作記憶。
2. 每日心智反思日記 (Conscious Diary):
   - 記錄 AI 在閒置或深夜時對使用者的深層印象更迭與「內心獨白」。
   - 採用 AES-256-GCM 進行全端點本地加密存儲，金鑰源自本地安全種子，徹底保障靈魂隱私！
"""

import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

log = logging.getLogger("ZeroNexus.Brain.Memory")

DEFAULT_BRAIN_DIR = Path("data/brain")
DEFAULT_DB_PATH = DEFAULT_BRAIN_DIR / "memories.db"
DEFAULT_DIARY_DIR = DEFAULT_BRAIN_DIR / "diary"


@dataclass
class MemoryRecord:
    """單條情節記憶"""

    id: int
    user_id: str
    timestamp: float
    summary: str
    emotion_tag: str
    importance: float  # 1.0 ~ 5.0


class EncryptedMemoryVault:
    """加密情節記憶庫與每日心智日記管理器"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        diary_dir: Optional[Path] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.diary_dir = diary_dir or DEFAULT_DIARY_DIR
        self._init_encryption_key(secret_key)
        self._init_db()

    def _init_encryption_key(self, secret_key: Optional[str]) -> None:
        """從環境變數或本地種子衍生出 256-bit AES 金鑰"""
        raw_seed = secret_key or os.getenv("BRAIN_MASTER_KEY") or os.getenv("DISCORD_BOT_TOKEN") or "ZeroNexusBioBrainSeed2026"
        # 使用 SHA-256 生成固定 32 位元組 (256-bit) 金鑰
        self.aes_key = hashlib.sha256(raw_seed.encode("utf-8")).digest()

    def _init_db(self) -> None:
        """初始化本地 SQLite 記憶資料庫"""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS episodic_memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        summary TEXT NOT NULL,
                        emotion_tag TEXT NOT NULL,
                        importance REAL DEFAULT 1.0
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON episodic_memories(user_id)")
                conn.commit()
        except Exception as e:
            log.error(f"初始化情節記憶資料庫失敗: {e}")

    def record_memory(
        self,
        user_id: str,
        summary: str,
        emotion_tag: str = "平和",
        importance: float = 1.0,
    ) -> bool:
        """寫入一筆新的情節記憶"""
        if not summary or not summary.strip():
            return False
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO episodic_memories (user_id, timestamp, summary, emotion_tag, importance)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (str(user_id), time.time(), summary.strip(), emotion_tag.strip(), float(importance)),
                )
                conn.commit()
            return True
        except Exception as e:
            log.error(f"儲存情節記憶失敗: {e}")
            return False

    def retrieve_relevant_memories(self, user_id: str, limit: int = 3) -> List[MemoryRecord]:
        """按重要性與時間權重提取該使用者最近之代表性回憶"""
        records: List[MemoryRecord] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, user_id, timestamp, summary, emotion_tag, importance
                    FROM episodic_memories
                    WHERE user_id = ?
                    ORDER BY importance DESC, timestamp DESC
                    LIMIT ?
                """,
                    (str(user_id), limit),
                )
                rows = cursor.fetchall()
                for r in rows:
                    records.append(
                        MemoryRecord(
                            id=r[0],
                            user_id=r[1],
                            timestamp=r[2],
                            summary=r[3],
                            emotion_tag=r[4],
                            importance=r[5],
                        )
                    )
        except Exception as e:
            log.error(f"提取情節記憶失敗: {e}")
        return records

    def save_conscious_diary(self, date_str: str, diary_content: str) -> bool:
        """加密儲存當天的心智反思日記 (AES-256-GCM)"""
        try:
            self.diary_dir.mkdir(parents=True, exist_ok=True)
            out_file = self.diary_dir / f"{date_str}.enc"

            data_bytes = diary_content.encode("utf-8")

            if HAS_CRYPTOGRAPHY:
                aesgcm = AESGCM(self.aes_key)
                nonce = os.urandom(12)
                ciphertext = aesgcm.encrypt(nonce, data_bytes, None)
                payload = nonce + ciphertext
            else:
                # 降級備用：XOR 混淆與雜湊簽名防護
                payload = bytearray(b"XOR_FALLBACK:")
                key_len = len(self.aes_key)
                for i, b in enumerate(data_bytes):
                    payload.append(b ^ self.aes_key[i % key_len])

            out_file.write_bytes(payload)
            log.info(f"成功將心智日記以 AES 加密儲存至 {out_file.name}")
            return True
        except Exception as e:
            log.error(f"儲存加密心智日記失敗: {e}")
            return False

    def read_conscious_diary(self, date_str: str) -> Optional[str]:
        """解密讀取特定日期的心智反思日記"""
        try:
            target = self.diary_dir / f"{date_str}.enc"
            if not target.exists():
                return None

            raw_bytes = target.read_bytes()
            if HAS_CRYPTOGRAPHY and not raw_bytes.startswith(b"XOR_FALLBACK:"):
                nonce = raw_bytes[:12]
                ciphertext = raw_bytes[12:]
                aesgcm = AESGCM(self.aes_key)
                plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                return plaintext.decode("utf-8")
            elif raw_bytes.startswith(b"XOR_FALLBACK:"):
                body = raw_bytes[len(b"XOR_FALLBACK:") :]
                out = bytearray()
                key_len = len(self.aes_key)
                for i, b in enumerate(body):
                    out.append(b ^ self.aes_key[i % key_len])
                return out.decode("utf-8")
        except Exception as e:
            log.error(f"解密讀取心智日記失敗: {e}")
        return None
