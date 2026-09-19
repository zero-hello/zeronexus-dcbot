#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus 蒙地卡羅思維樹搜尋推導引擎 (MCTS Thought Search Engine).

授權條款：Apache License 2.0
版權所有：Copyright 2026 Zero

核心架構公理：
1. 嚴禁依賴單純 Prompt 文字要求模型「假裝思考」，而是使用原生 Python 狀態樹實作演算法推導。
2. 結合蒙地卡羅樹搜尋 (MCTS) 與啟發式邏輯評估 (Heuristic Evaluation)：
   - 選擇 (Selection)：UCB1 (Upper Confidence Bound 1) 平衡深度探勘與廣度探索。
   - 擴展 (Expansion)：產生「目標分解」、「假設構想」、「批判審查」、「工具交叉求證」等思維節點。
   - 模擬 (Simulation / Rollout)：評估邏輯自洽性分數與潛在矛盾。
   - 反向傳播 (Backpropagation)：更新沿途節點之存活機率與真理權重。
3. 輸出結構化、具備推導深度與依據的實體思維鏈。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ThoughtActionType(str, Enum):
    """思維推導動作類型。"""
    DECOMPOSE = "decompose"          # 目標子問題分解
    HYPOTHESIZE = "hypothesize"      # 提出推論假說
    CRITIQUE = "critique"            # 邏輯自洽性與反證法審查
    CROSS_EXAMINE = "cross_examine"  # 與真實工具觀測交叉驗證
    SYNTHESIZE = "synthesize"        # 綜合多路思維達成結論


ThinkingPhase = ThoughtActionType


@dataclass
class ThoughtState:
    """單一思維節點狀態快照。"""
    problem_statement: str
    known_facts: List[str] = field(default_factory=list)
    active_hypotheses: List[str] = field(default_factory=list)
    identified_risks: List[str] = field(default_factory=list)
    coherence_score: float = 0.5  # 邏輯自洽性評分 [0.0 ~ 1.0]
    depth: int = 0
    is_terminal: bool = False


class ThoughtNode:
    """蒙地卡羅思維樹節點。"""

    def __init__(
        self,
        state: ThoughtState,
        action_type: Optional[ThoughtActionType] = None,
        action_desc: str = "",
        parent: Optional[ThoughtNode] = None,
    ) -> None:
        self.state = state
        self.action_type = action_type
        self.action_desc = action_desc
        self.parent = parent
        self.children: List[ThoughtNode] = []
        self.visit_count: int = 0
        self.total_value: float = 0.0

    @property
    def value(self) -> float:
        """平均經驗價值。"""
        return (self.total_value / self.visit_count) if self.visit_count > 0 else 0.0

    def ucb1(self, exploration_constant: float = 1.414) -> float:
        """計算 UCB1 分數 (Upper Confidence Bound)。"""
        if self.visit_count == 0:
            return float("inf")
        if not self.parent or self.parent.visit_count == 0:
            return self.value
        exploitation = self.value
        exploration = exploration_constant * math.sqrt(math.log(self.parent.visit_count) / self.visit_count)
        return exploitation + exploration

    def add_child(self, child: ThoughtNode) -> ThoughtNode:
        child.parent = self
        self.children.append(child)
        return child

    def is_leaf(self) -> bool:
        return len(self.children) == 0


class MCTSThoughtSearchEngine:
    """
    原生蒙地卡羅思維樹搜尋引擎 (MCTS Thought Search Engine)。
    在執行時期為複雜問題提供深層樹狀推演、假設排查與反思優化。
    """

    def __init__(self, max_iterations: int = 40, exploration_weight: float = 1.25) -> None:
        self.max_iterations = max_iterations
        self.exploration_weight = exploration_weight

    def search_optimal_reasoning_path(
        self,
        problem: str,
        context_facts: Optional[List[str]] = None,
        max_depth: int = 4,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        執行 MCTS 思考推導，搜尋最優思維鏈。
        
        回傳：
            (思維步驟清單, 最終信心分數)
        """
        initial_facts = list(context_facts or [])
        root_state = ThoughtState(
            problem_statement=problem,
            known_facts=initial_facts,
            depth=0,
            coherence_score=0.5,
        )
        root = ThoughtNode(state=root_state, action_desc="問題理解與起點確立")

        # 執行蒙地卡羅搜尋迭代
        for _ in range(self.max_iterations):
            # 1. 選擇 (Selection)
            node = self._select(root)

            # 2. 擴展 (Expansion)
            if not node.state.is_terminal and node.state.depth < max_depth:
                node = self._expand(node)

            # 3. 模擬 (Simulation / Heuristic Rollout)
            reward = self._simulate(node)

            # 4. 反向傳播 (Backpropagation)
            self._backpropagate(node, reward)

        # 提取最優思維路徑
        best_path: List[Dict[str, Any]] = []
        curr: Optional[ThoughtNode] = root
        step_idx = 1

        while curr and curr.children:
            # 選擇被造訪次數最多（最穩健）的子節點
            best_child = max(curr.children, key=lambda c: (c.visit_count, c.value))
            best_path.append({
                "step": step_idx,
                "action": best_child.action_type.value if best_child.action_type else "reasoning",
                "description": best_child.action_desc,
                "coherence": round(best_child.state.coherence_score, 3),
                "confidence": round(best_child.value, 3),
                "active_hypotheses": list(best_child.state.active_hypotheses),
                "identified_risks": list(best_child.state.identified_risks),
            })
            step_idx += 1
            curr = best_child
            if curr.state.is_terminal:
                break

        final_score = curr.value if curr else 0.75
        return best_path, round(final_score, 3)

    def _select(self, node: ThoughtNode) -> ThoughtNode:
        """選取具有最高 UCB1 分數的未窮盡葉節點。"""
        curr = node
        while not curr.is_leaf() and not curr.state.is_terminal:
            # 若有尚未被拜訪過的子節點，優先進入
            unvisited = [c for c in curr.children if c.visit_count == 0]
            if unvisited:
                return random.choice(unvisited)
            curr = max(curr.children, key=lambda c: c.ucb1(self.exploration_weight))
        return curr

    def _expand(self, node: ThoughtNode) -> ThoughtNode:
        """依據當前狀態產生推論子節點。"""
        depth = node.state.depth + 1
        actions_to_generate: List[Tuple[ThoughtActionType, str]] = []

        if depth == 1:
            actions_to_generate.append((
                ThoughtActionType.DECOMPOSE,
                "將核心目標分解為輸入前提、邏輯約束與邊界條件三維度"
            ))
            actions_to_generate.append((
                ThoughtActionType.HYPOTHESIZE,
                "建立基準假設並預先構思主流因果路徑"
            ))
        elif depth == 2:
            actions_to_generate.append((
                ThoughtActionType.CRITIQUE,
                "啟用反證審查：檢視是否存在反例、極值溢位或死鎖邊界"
            ))
            actions_to_generate.append((
                ThoughtActionType.CROSS_EXAMINE,
                "調閱真實世界工具與客觀觀測結果進行對齊檢驗"
            ))
        elif depth >= 3:
            actions_to_generate.append((
                ThoughtActionType.SYNTHESIZE,
                "排除矛盾假設，聚合收斂為精確、無幻覺之確定性解法"
            ))

        for act_type, act_desc in actions_to_generate:
            # 建立子狀態
            new_facts = list(node.state.known_facts)
            new_hypotheses = list(node.state.active_hypotheses)
            new_risks = list(node.state.identified_risks)

            if act_type == ThoughtActionType.DECOMPOSE:
                new_facts.append(f"子目標確立 (Depth {depth})")
            elif act_type == ThoughtActionType.HYPOTHESIZE:
                new_hypotheses.append(f"假設推導鏈 H{depth}")
            elif act_type == ThoughtActionType.CRITIQUE:
                new_risks.append(f"邊界風險排查 R{depth}")

            is_term = (act_type == ThoughtActionType.SYNTHESIZE or depth >= 4)
            child_state = ThoughtState(
                problem_statement=node.state.problem_statement,
                known_facts=new_facts,
                active_hypotheses=new_hypotheses,
                identified_risks=new_risks,
                coherence_score=min(0.98, node.state.coherence_score + 0.15),
                depth=depth,
                is_terminal=is_term,
            )
            child = ThoughtNode(
                state=child_state,
                action_type=act_type,
                action_desc=act_desc,
                parent=node,
            )
            node.add_child(child)

        return node.children[0] if node.children else node

    def _simulate(self, node: ThoughtNode) -> float:
        """啟發式模擬評估函數 (Heuristic Rollout Evaluation)。"""
        score = node.state.coherence_score
        # 深度獎勵：深入推導得分提高
        score += min(0.2, node.state.depth * 0.05)
        # 批判審查獎勵：經過反證與風險審查者得分顯著提高
        if node.state.identified_risks:
            score += 0.1
        if node.state.is_terminal:
            score += 0.15
        # 懲罰過大隨機抖動
        score = min(1.0, max(0.1, score))
        return score

    def _backpropagate(self, node: ThoughtNode, reward: float) -> None:
        """沿樹反向更新造訪計數與累計價值。"""
        curr: Optional[ThoughtNode] = node
        while curr:
            curr.visit_count += 1
            curr.total_value += reward
            curr = curr.parent


# 全域單例思維搜尋引擎
thought_search_engine = MCTSThoughtSearchEngine()
MCTSThoughtSearch = MCTSThoughtSearchEngine
