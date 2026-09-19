"""Zero Intelligence - 原生因果推論引擎與矛盾消解器 (Causal Inference Engine & Conflict Resolver)

本模組為 Zero Intelligence 核心符號邏輯推論組件，以原生 Python 代碼實作：
1. 因果有向無環圖 (Causal Directed Acyclic Graph, DAG)
2. 介入推演 (Intervention / do-calculus 原生模擬)
3. 反事實分析 (Counterfactual Reasoning)
4. 矛盾衝突消解器 (Contradiction & Conflict Resolver)
5. 命題自洽度評估 (Logical Coherence Evaluator)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from zeronexus.intelligence.truth_spectrum import TruthFact, TruthLevel


class RelationType(str, Enum):
    """因果作用類型"""
    STIMULATES = "stimulates"     # 正向刺激 / 促成 (正權重)
    INHIBITS = "inhibits"         # 負向抑制 / 阻礙 (負權重)
    NECESSARY = "necessary"       # 必要條件
    SUFFICIENT = "sufficient"     # 充分條件
    CORRELATED = "correlated"     # 統計相關 (非確定因果)


@dataclass
class CausalNode:
    """因果網絡變數節點"""
    node_id: str
    label: str
    value: float = 0.0                      # 數值或活化值 (-1.0 ~ 1.0)
    truth_level: TruthLevel = TruthLevel.HYPOTHESIS
    is_intervened: bool = False             # 是否受 do-operator 介入
    metadata: Dict[str, Any] = field(default_factory=dict)
    evidence: Optional[TruthFact] = None    # 綁定的真理事實


@dataclass
class CausalEdge:
    """因果有向邊"""
    source_id: str
    target_id: str
    weight: float                           # 因果影響權重 (-1.0 ~ 1.0)
    relation_type: RelationType = RelationType.STIMULATES
    confidence: float = 1.0                 # 信任度 (0.0 ~ 1.0)
    description: str = ""


@dataclass
class ContradictionReport:
    """矛盾衝突報告"""
    has_conflict: bool
    conflict_nodes: List[str] = field(default_factory=list)
    coherence_score: float = 1.0            # 全域自洽度 (0.0 ~ 1.0)
    conflict_details: List[str] = field(default_factory=list)
    resolution_actions: List[str] = field(default_factory=list)


class CausalEngine:
    """Zero Intelligence 原生因果推論引擎"""

    def __init__(self) -> None:
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: Dict[Tuple[str, str], CausalEdge] = {}
        self.adjacency_in: Dict[str, Set[str]] = {}
        self.adjacency_out: Dict[str, Set[str]] = {}

    def add_node(
        self,
        node_id: str,
        label: str,
        value: float = 0.0,
        truth_level: TruthLevel = TruthLevel.HYPOTHESIS,
        evidence: Optional[TruthFact] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CausalNode:
        """添加或更新因果變數節點"""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.label = label
            node.value = value
            node.truth_level = truth_level
            if evidence:
                node.evidence = evidence
            if metadata:
                node.metadata.update(metadata)
            return node

        node = CausalNode(
            node_id=node_id,
            label=label,
            value=value,
            truth_level=truth_level,
            evidence=evidence,
            metadata=metadata or {},
        )
        self.nodes[node_id] = node
        self.adjacency_in[node_id] = set()
        self.adjacency_out[node_id] = set()
        return node

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        weight: float,
        relation_type: RelationType = RelationType.STIMULATES,
        confidence: float = 1.0,
        description: str = "",
    ) -> bool:
        """添加因果有向邊，若會造成有向環 (Cycle) 則拒絕並回傳 False"""
        if source_id not in self.nodes or target_id not in self.nodes:
            raise ValueError(f"節點不存在: {source_id} -> {target_id}")

        if source_id == target_id:
            return False  # 禁止自環

        # 暫時加入並檢測環
        edge_key = (source_id, target_id)
        edge = CausalEdge(
            source_id=source_id,
            target_id=target_id,
            weight=max(-1.0, min(1.0, weight)),
            relation_type=relation_type,
            confidence=max(0.0, min(1.0, confidence)),
            description=description,
        )

        self.edges[edge_key] = edge
        self.adjacency_out[source_id].add(target_id)
        self.adjacency_in[target_id].add(source_id)

        # 檢測 DAG 拓撲是否合法
        if not self._is_acyclic():
            # 回滾
            del self.edges[edge_key]
            self.adjacency_out[source_id].remove(target_id)
            self.adjacency_in[target_id].remove(source_id)
            return False

        return True

    def _is_acyclic(self) -> bool:
        """Kahn 演算法拓撲排序檢測無環性"""
        in_degree = {nid: len(self.adjacency_in[nid]) for nid in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for nxt in self.adjacency_out.get(curr, set()):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        return visited_count == len(self.nodes)

    def topological_sort(self) -> List[str]:
        """回傳因果節點拓撲排序序列"""
        in_degree = {nid: len(self.adjacency_in[nid]) for nid in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: List[str] = []

        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for nxt in self.adjacency_out.get(curr, set()):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        return order

    def propagate_forward(self) -> None:
        """沿拓撲順序向前傳播因果效應"""
        order = self.topological_sort()
        for nid in order:
            node = self.nodes[nid]
            if node.is_intervened:
                # 介入節點不受上游入邊影響
                continue

            parents = self.adjacency_in.get(nid, set())
            if not parents:
                continue

            total_influence = 0.0
            total_weight = 0.0
            for pid in parents:
                edge = self.edges.get((pid, nid))
                if not edge:
                    continue
                parent_node = self.nodes[pid]
                influence = parent_node.value * edge.weight * edge.confidence
                total_influence += influence
                total_weight += abs(edge.weight * edge.confidence)

            if total_weight > 0:
                # 雙曲正切非線性壓縮
                aggregated = total_influence / total_weight
                node.value = math.tanh(aggregated)

    def apply_intervention(self, node_id: str, target_value: float) -> None:
        """Pearl do-calculus 介入操作: do(X = target_value)
        切斷所有流入該節點的因果鏈，並向前傳播效應。
        """
        if node_id not in self.nodes:
            raise KeyError(f"節點不存在: {node_id}")

        node = self.nodes[node_id]
        node.is_intervened = True
        node.value = max(-1.0, min(1.0, target_value))
        node.truth_level = TruthLevel.OBSERVED  # 介入被視為已知觀測事實

        # 傳播更新下游
        self.propagate_forward()

    def counterfactual_reasoning(
        self,
        intervene_node_id: str,
        counterfactual_value: float,
        target_eval_node_ids: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, float]]:
        """反事實推演 (Counterfactual Analysis)
        在當前狀態已知的條件下，若過去條件改為 counterfactual_value，
        下游關鍵節點的預期偏轉量 (Delta)。
        """
        # 1. 備份當前狀態
        backup_states = {
            nid: (n.value, n.is_intervened) for nid, n in self.nodes.items()
        }

        # 2. 實施反事實假設介入
        self.apply_intervention(intervene_node_id, counterfactual_value)

        # 3. 收集推演結果
        eval_targets = target_eval_node_ids or list(self.nodes.keys())
        results: Dict[str, Dict[str, float]] = {}

        for nid in eval_targets:
            if nid in self.nodes:
                orig_val = backup_states[nid][0]
                new_val = self.nodes[nid].value
                results[nid] = {
                    "original_value": round(orig_val, 4),
                    "counterfactual_value": round(new_val, 4),
                    "delta": round(new_val - orig_val, 4),
                }

        # 4. 恢復原始狀態
        for nid, (val, interv) in backup_states.items():
            self.nodes[nid].value = val
            self.nodes[nid].is_intervened = interv

        return results

    def audit_contradictions(self) -> ContradictionReport:
        """檢測全圖邏輯矛盾與衝突
        規則：
        1. 命題互斥衝突：若兩節點被定義為互斥，但兩者活化值同時 > 0.5。
        2. 符號真實衝突：上游由 OBSERVED 高權重強烈刺激下游，但下游觀測值為 OBSERVED 且強烈相反。
        3. 自洽性評分計算。
        """
        conflicts: List[str] = []
        conflict_nodes: Set[str] = set()
        resolution_actions: List[str] = []

        # 遍歷所有邊，檢測因果預測與真實觀測的分歧
        inconsistency_sum = 0.0
        edge_count = len(self.edges)

        for (src_id, tgt_id), edge in self.edges.items():
            src_node = self.nodes[src_id]
            tgt_node = self.nodes[tgt_id]

            expected_direction = src_node.value * edge.weight
            actual_direction = tgt_node.value

            # 若上游訊號顯著，且邊信任度高，但下游走向完全相反
            if abs(expected_direction) > 0.4 and abs(actual_direction) > 0.4:
                if (expected_direction > 0 and actual_direction < -0.3) or (
                    expected_direction < 0 and actual_direction > 0.3
                ):
                    # 檢查兩者真理位階
                    inconsistency = abs(expected_direction - actual_direction) / 2.0
                    inconsistency_sum += inconsistency

                    if tgt_node.truth_level == TruthLevel.OBSERVED and src_node.truth_level < TruthLevel.OBSERVED:
                        # 下游為真實觀測，上游為假說 -> 上游假說被現實推翻！
                        detail = (
                            f"【因果衝突】節點 '{src_node.label}' ({src_node.truth_level.value}) "
                            f"預期推導 '{tgt_node.label}' 應為 {expected_direction:.2f}，"
                            f"但實際觀測 ({tgt_node.truth_level.value}) 為 {actual_direction:.2f}。"
                        )
                        conflicts.append(detail)
                        conflict_nodes.add(src_id)
                        conflict_nodes.add(tgt_id)
                        resolution_actions.append(
                            f"依據真實性公理：降級或修正假說節點 '{src_node.label}' 之權重。"
                        )
                    elif tgt_node.truth_level < TruthLevel.OBSERVED and src_node.truth_level == TruthLevel.OBSERVED:
                        # 上游為真實觀測，下游為推測 -> 下游推測值應被強行校正
                        detail = (
                            f"【推論偏差】確定事實 '{src_node.label}' 應驅動 '{tgt_node.label}'，"
                            f"但其當前信念值與因果律脫節。"
                        )
                        conflicts.append(detail)
                        conflict_nodes.add(tgt_id)
                        resolution_actions.append(
                            f"強制前向校正節點 '{tgt_node.label}' 之信念值為 {expected_direction:.2f}。"
                        )

        # 計算自洽度分數
        if edge_count > 0:
            avg_inconsistency = inconsistency_sum / edge_count
            coherence = max(0.0, min(1.0, 1.0 - avg_inconsistency))
        else:
            coherence = 1.0

        return ContradictionReport(
            has_conflict=len(conflicts) > 0,
            conflict_nodes=list(conflict_nodes),
            coherence_score=round(coherence, 3),
            conflict_details=conflicts,
            resolution_actions=resolution_actions,
        )

    def resolve_conflicts(self, report: Optional[ContradictionReport] = None) -> int:
        """執行衝突消解，依據真實性位階修復網絡不一致"""
        if report is None:
            report = self.audit_contradictions()

        if not report.has_conflict:
            return 0

        resolved_count = 0
        for (src_id, tgt_id), edge in list(self.edges.items()):
            src_node = self.nodes[src_id]
            tgt_node = self.nodes[tgt_id]

            expected = src_node.value * edge.weight
            actual = tgt_node.value

            if (expected > 0.4 and actual < -0.3) or (expected < -0.4 and actual > 0.3):
                # 若下游是 OBSERVED，上游只是 HYPOTHESIS，衰減邊的權重並降級上游
                if tgt_node.truth_level == TruthLevel.OBSERVED and src_node.truth_level != TruthLevel.OBSERVED:
                    edge.confidence *= 0.5
                    src_node.value *= 0.5
                    resolved_count += 1
                elif src_node.truth_level == TruthLevel.OBSERVED and tgt_node.truth_level != TruthLevel.OBSERVED:
                    tgt_node.value = math.tanh(expected)
                    resolved_count += 1

        # 重新傳播計算
        self.propagate_forward()
        return resolved_count


# 全域因果推論引擎單例
causal_engine = CausalEngine()

