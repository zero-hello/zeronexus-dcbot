#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus 原生神經符號認知網絡 (Symbolic-Neural Cognitive Network).

授權條款：Apache License 2.0
版權所有：Copyright 2026 Zero

架構設計宗旨：
1. 拒絕純文字 Prompt 模擬，以 Python 原生矩陣運算與圖拓撲傳播實作實體認知網絡。
2. 概念節點（Concept Node）與突觸矩陣（Synaptic Matrix）：
   - 赫布學習規則（Hebbian Learning）：Cells that fire together, wire together。
   - 突觸可塑性（Synaptic Plasticity）與長短期增益/衰減（STDP / LTP / LTD）。
3. 活化擴散演算法（Spreading Activation Algorithm）：
   - 在使用者提出問題或工具觀測輸入時，活化信號沿突觸網路傳導，
     自主激活用戶意圖背後的潛在約束、實體關聯、常識邏輯與邊界隱患。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class CognitiveNode:
    """符號認知神經節點。"""
    concept_id: str
    label: str
    domain: str  # e.g., 'hardware', 'code', 'life', 'weather', 'finance', 'logic', 'security'
    activation_energy: float = 0.0
    base_priority: float = 1.0
    decay_rate: float = 0.15
    attributes: Dict[str, Any] = field(default_factory=dict)
    last_fired_at: float = field(default_factory=time.time)

    def stimulate(self, amount: float) -> float:
        """注入刺激能量並重置發射時間。"""
        self.activation_energy = min(1.0, max(0.0, self.activation_energy + amount))
        self.last_fired_at = time.time()
        return self.activation_energy

    def decay(self, elapsed_seconds: float) -> float:
        """依據時間差進行指數能量衰減。"""
        if elapsed_seconds <= 0:
            return self.activation_energy
        decay_factor = math.exp(-self.decay_rate * elapsed_seconds)
        self.activation_energy *= decay_factor
        if self.activation_energy < 0.001:
            self.activation_energy = 0.0
        return self.activation_energy


ConceptNode = CognitiveNode


@dataclass
class SynapticLink:
    """神經突觸連接鏈。"""
    source_id: str
    target_id: str
    weight: float = 0.5  # 突觸權重 [0.0 ~ 1.0]
    relation: str = "associated_with"  # 'causes', 'requires', 'conflicts_with', 'part_of', 'associated_with'
    fire_count: int = 0
    last_potentiated_at: float = field(default_factory=time.time)

    def potentiate(self, learning_rate: float = 0.05) -> float:
        """赫布長時增程 (Long-Term Potentiation, LTP)：強化突觸連結。"""
        self.fire_count += 1
        self.last_potentiated_at = time.time()
        # 漸進飽和更新：w = w + lr * (1 - w)
        self.weight += learning_rate * (1.0 - self.weight)
        return self.weight

    def depress(self, decay_rate: float = 0.02) -> float:
        """長時抑制 (Long-Term Depression, LTD)：弱化未共同激活之突觸。"""
        self.weight = max(0.01, self.weight * (1.0 - decay_rate))
        return self.weight


class CognitiveNetwork:
    """
    原生神經符號認知圖譜網絡 (Symbolic-Neural Cognitive Network)。
    提供概念建模、突觸關聯、活化擴散與思維聯想能力。
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, CognitiveNode] = {}
        self.synapses: Dict[str, Dict[str, SynapticLink]] = {}  # source -> {target: SynapticLink}
        self.reverse_synapses: Dict[str, Set[str]] = {}  # target -> {sources}
        self.activation_threshold: float = 0.25
        self.max_spread_hops: int = 4
        self._bootstrap_knowledge_base()

    @property
    def concepts(self) -> Dict[str, CognitiveNode]:
        """相容別名：獲取所有概念節點字典。"""
        return self.nodes

    @property
    def associations(self) -> List[SynapticLink]:
        """相容別名：獲取所有突觸關聯邊清單。"""
        edges: List[SynapticLink] = []
        for targets in self.synapses.values():
            edges.extend(targets.values())
        return edges

    def register_node(
        self,
        concept_id: str,
        label: str,
        domain: str,
        base_priority: float = 1.0,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> CognitiveNode:
        """註冊或更新認知神經節點。"""
        if concept_id not in self.nodes:
            node = CognitiveNode(
                concept_id=concept_id,
                label=label,
                domain=domain,
                base_priority=base_priority,
                attributes=attributes or {},
            )
            self.nodes[concept_id] = node
            self.synapses[concept_id] = {}
            self.reverse_synapses[concept_id] = set()
        else:
            node = self.nodes[concept_id]
            node.label = label
            node.domain = domain
            node.base_priority = base_priority
            if attributes:
                node.attributes.update(attributes)
        return node

    def connect(
        self,
        source_id: str,
        target_id: str,
        weight: float = 0.5,
        relation: str = "associated_with",
        bidirectional: bool = False,
    ) -> None:
        """建立突觸神經連結。"""
        if source_id not in self.nodes or target_id not in self.nodes:
            return

        link = SynapticLink(
            source_id=source_id,
            target_id=target_id,
            weight=min(1.0, max(0.01, weight)),
            relation=relation,
        )
        self.synapses[source_id][target_id] = link
        self.reverse_synapses[target_id].add(source_id)

        if bidirectional:
            rev_link = SynapticLink(
                source_id=target_id,
                target_id=source_id,
                weight=min(1.0, max(0.01, weight)),
                relation=relation,
            )
            self.synapses[target_id][source_id] = rev_link
            self.reverse_synapses[source_id].add(target_id)

    def spread_activation(
        self,
        initial_stimuli: Dict[str, float],
        hops: int = 3,
        decay: float = 0.65,
    ) -> Dict[str, float]:
        """
        執行活化擴散演算法 (Spreading Activation Algorithm)。
        
        參數：
            initial_stimuli: 初始刺激節點與能量映射 {concept_id: energy}
            hops: 傳導跳數上限
            decay: 每跳能量傳導衰減率
        回傳：
            所有被激活超過門檻的節點與最終能量映射
        """
        # 1. 注入初始刺激
        active_frontier: Dict[str, float] = {}
        for cid, energy in initial_stimuli.items():
            if cid in self.nodes:
                self.nodes[cid].stimulate(energy)
                active_frontier[cid] = energy

        visited: Set[str] = set()
        cumulative_activations: Dict[str, float] = dict(initial_stimuli)

        # 2. 逐層波紋式向外擴散
        for _ in range(min(hops, self.max_spread_hops)):
            if not active_frontier:
                break

            next_frontier: Dict[str, float] = {}
            for src_id, src_energy in active_frontier.items():
                if src_energy < 0.05 or src_id in visited:
                    continue
                visited.add(src_id)

                # 遍歷出射突觸
                out_synapses = self.synapses.get(src_id, {})
                for tgt_id, link in out_synapses.items():
                    if tgt_id == src_id:
                        continue
                    # 傳導能量 = 來源能量 * 突觸權重 * 衰減係數
                    propagated = src_energy * link.weight * decay
                    if propagated >= 0.03:
                        tgt_node = self.nodes.get(tgt_id)
                        if tgt_node:
                            tgt_node.stimulate(propagated)
                            # 強化共同激發突觸（赫布學習）
                            link.potentiate(learning_rate=0.03)
                            # 累積計算
                            cumulative_activations[tgt_id] = cumulative_activations.get(tgt_id, 0.0) + propagated
                            next_frontier[tgt_id] = max(next_frontier.get(tgt_id, 0.0), propagated)

            active_frontier = next_frontier

        # 3. 篩選出大於活化門檻的高關注概念
        focused_concepts = {
            cid: round(val, 4)
            for cid, val in cumulative_activations.items()
            if val >= self.activation_threshold and cid in self.nodes
        }
        return focused_concepts

    def extract_semantic_anchors(self, query_text: str) -> Dict[str, float]:
        """
        從自然語言文字中辨識出初始概念節點並給予基底刺激。
        """
        stimuli: Dict[str, float] = {}
        text_lower = query_text.lower()

        for cid, node in self.nodes.items():
            matched = False
            # 匹配 label
            if node.label.lower() in text_lower:
                matched = True
            # 匹配別名與關鍵字
            keywords = node.attributes.get("keywords", [])
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched = True
                    break

            if matched:
                stimuli[cid] = node.base_priority

        return stimuli

    def reason_cognitive_context(self, user_query: str) -> Dict[str, Any]:
        """
        根據使用者問題執行神經符號推理，產出結構化認知上下文。
        """
        initial_stimuli = self.extract_semantic_anchors(user_query)
        if not initial_stimuli:
            return {
                "active_concepts": [],
                "domain_bias": "general",
                "recommended_constraints": [],
                "cognitive_density": 0.0,
            }

        # 執行活化擴散
        activations = self.spread_activation(initial_stimuli, hops=3)

        # 排序被激活的概念
        sorted_concepts = sorted(activations.items(), key=lambda x: x[1], reverse=True)

        active_details = []
        domain_counts: Dict[str, float] = {}
        constraints = []

        for cid, energy in sorted_concepts:
            node = self.nodes.get(cid)
            if not node:
                continue
            active_details.append({
                "concept": node.label,
                "domain": node.domain,
                "energy": energy,
            })
            domain_counts[node.domain] = domain_counts.get(node.domain, 0.0) + energy
            # 收集約束條件
            if "constraint" in node.attributes:
                constraints.append(node.attributes["constraint"])

        # 主導領域
        dominant_domain = max(domain_counts.items(), key=lambda x: x[1])[0] if domain_counts else "general"
        density = round(sum(activations.values()) / max(1, len(activations)), 3)

        return {
            "active_concepts": active_details[:8],
            "domain_bias": dominant_domain,
            "recommended_constraints": list(set(constraints))[:5],
            "cognitive_density": density,
        }

    def activate_concepts_from_text(self, text: str, boost: float = 1.0) -> Dict[str, float]:
        """從文字中萃取語意錨點並向全網絡擴散活化能量。"""
        anchors = self.extract_semantic_anchors(text)
        if boost != 1.0:
            anchors = {k: v * boost for k, v in anchors.items()}
        return self.spread_activation(anchors, hops=3)

    def get_activated_concepts(self, threshold: float = 0.1) -> List[Tuple[str, float]]:
        """回傳目前活化能量大於門檻之概念清單 [(label, energy), ...]，依活化度降序排列。"""
        active: List[Tuple[str, float]] = []
        for node in self.nodes.values():
            if node.activation_energy >= threshold:
                active.append((node.label, round(node.activation_energy, 4)))
        active.sort(key=lambda x: x[1], reverse=True)
        return active

    def _bootstrap_knowledge_base(self) -> None:
        """初始化內建符號神經網絡基礎骨幹知識。"""
        # 1. 電腦硬體與組裝
        self.register_node("hw_cpu", "處理器 (CPU)", "hardware", 1.2, {"keywords": ["cpu", "處理器", "r5-3600", "i3", "賽揚", "g6900", "14900ks", "amd", "intel"]})
        self.register_node("hw_gpu", "顯示卡 (GPU)", "hardware", 1.2, {"keywords": ["gpu", "顯卡", "顯示卡", "rx6600", "rtx", "4090", "礦卡"]})
        self.register_node("hw_ram", "記憶體 (RAM)", "hardware", 1.1, {"keywords": ["ram", "記憶體", "雙通道", "8g", "16g", "頻率", "超頻"]})
        self.register_node("hw_psu", "電源供應器 (PSU)", "hardware", 1.1, {"keywords": ["電供", "電源", "瓦數", "psu", "跳電", "炸裂"]})
        self.register_node("hw_cooling", "散熱與散熱膏", "hardware", 1.0, {"keywords": ["散熱", "風扇", "水冷", "散熱膏", "矽脂", "過熱", "高溫"]})
        self.register_node("hw_nas", "網路儲存 (NAS)", "hardware", 1.0, {"keywords": ["nas", "軟路由", "私有雲", "硬碟", "raid"]})

        # 硬體突觸鏈
        self.connect("hw_cpu", "hw_gpu", 0.75, "pairs_with", bidirectional=True)
        self.connect("hw_cpu", "hw_ram", 0.85, "requires", bidirectional=True)
        self.connect("hw_cpu", "hw_cooling", 0.90, "requires")
        self.connect("hw_gpu", "hw_psu", 0.85, "requires")
        self.connect("hw_cpu", "hw_nas", 0.65, "associated_with")

        # 2. 軟體工程與架構
        self.register_node("sw_concurrency", "並行與非同步 (Async/Thread)", "code", 1.2, {"keywords": ["async", "非同步", "協程", "執行緒", "死鎖", "lock", "concurrency"], "constraint": "防範非同步協程死鎖與阻塞"})
        self.register_node("sw_db", "資料庫與交易 (Database & Transaction)", "code", 1.2, {"keywords": ["db", "資料庫", "sql", "sqlite", "postgres", "交易", "rollback"], "constraint": "確保資料庫交易異常時完整 Rollback"})
        self.register_node("sw_memory_leak", "記憶體管理與外洩", "code", 1.1, {"keywords": ["記憶體外洩", "memory leak", "oom", "垃圾回收", "未釋放"], "constraint": "檢查快取與全域集合生命週期避免記憶體膨脹"})
        self.register_node("sw_api", "外部 API 與網路請求", "code", 1.1, {"keywords": ["api", "http", "aiohttp", "429", "503", "逾時", "timeout"], "constraint": "所有外部請求必須配置明確逾時與指數退避重試"})

        # 軟體突觸鏈
        self.connect("sw_concurrency", "sw_db", 0.85, "interacts_with", bidirectional=True)
        self.connect("sw_concurrency", "sw_memory_leak", 0.70, "potential_risk")
        self.connect("sw_concurrency", "sw_api", 0.80, "interacts_with")

        # 3. 台灣民生、生活與即時情資
        self.register_node("life_cwa", "中央氣象署觀測與地震", "weather", 1.2, {"keywords": ["天氣", "氣象", "下雨", "降雨", "地震", "芮氏", "震度", "雷達", "cwa"], "constraint": "依據中央氣象署觀測數據如實陳述，不擅自預報猜測"})
        self.register_node("life_fuel", "中油即時油價與預估", "life", 1.1, {"keywords": ["油價", "中油", "95", "92", "98", "柴油", "漲價", "降價"]})
        self.register_node("life_train", "雙鐵時刻表與誤點", "life", 1.1, {"keywords": ["台鐵", "高鐵", "火車", "時刻表", "誤點", "班次"]})
        self.register_node("life_stock", "台美股即時報價", "finance", 1.1, {"keywords": ["股票", "台積電", "2330", "美股", "nvda", "大盤", "漲跌"]})

        # 生活突觸鏈
        self.connect("life_cwa", "life_train", 0.60, "causes_delay")


# 全域單例認知網絡
cognitive_network = CognitiveNetwork()
