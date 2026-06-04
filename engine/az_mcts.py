# -*- coding: utf-8 -*-
"""PUCT MCTS (= AlphaZero proper の核、 2026-06-04 自律)。

OPTCG は **multi-action turn**(1ターン=同一playerの複数行動)なので、 各ノードに
`to_move`(その盤面の手番player)を持ち、 leaf value は to_move 視点の P(win)∈[0,1]。
backup は to_move が一致するノードには v、 違えば 1-v を積む(= 2人零和、 P(win for A)=1-P(win for B))。

- 状態はノードに保持(= fast_clone)。 selection は木を降りる、 expansion で 1 child 展開、
  leaf を value_fn で評価、 backup。
- value_fn(state, to_move) -> [0,1]: board_eval(sigmoid) or value NN。 terminal は 1/0。
- prior: 既定 uniform(高速)。 board_eval-softmax も可(focus するが expansion 重い)。

AlphaZero 化の段階: Phase1 = value-leaf MCTS(policy head 無し、 prior uniform)。
Phase2 で policy head(行動slot encoding)を足して PUCT prior を学習値に。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

from .game import EndPhase, legal_actions
from .plan_search import _apply_with_defense, fast_clone


class _Node:
    __slots__ = ("state", "to_move", "actions", "P", "N", "W", "children", "terminal")

    def __init__(self, state: Any, to_move: int):
        self.state = state
        self.to_move = to_move
        self.actions: Optional[list] = None      # lazy: legal_actions
        self.P: Optional[list] = None            # priors aligned with actions
        self.N: Optional[list] = None            # visit count per action
        self.W: Optional[list] = None            # value sum per action (to_move 視点)
        self.children: dict = {}                 # action_idx -> _Node
        self.terminal = bool(getattr(state, "game_over", False))


def _board_eval_value(state: Any, to_move: int, scale: float = 4000.0) -> float:
    """board_eval を to_move 視点の P(win)∈[0,1] に(= sigmoid)。 terminal は 1/0。"""
    if getattr(state, "game_over", False):
        w = getattr(state, "winner", -1)
        return 1.0 if w == to_move else (0.0 if w == (1 - to_move) else 0.5)
    from .eval import compute_score
    s = compute_score(state, to_move)
    x = s / scale
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


class AZMcts:
    def __init__(self, value_fn: Optional[Callable] = None, defender_ai=None,
                 c_puct: float = 1.5, prior: str = "uniform"):
        self.value_fn = value_fn or _board_eval_value
        self.defender_ai = defender_ai
        self.c_puct = c_puct
        self.prior = prior

    def _ensure_defender(self, state):
        if self.defender_ai is None:
            from .ai import GreedyAI
            self.defender_ai = GreedyAI(rng=getattr(state, "rng", None))
        return self.defender_ai

    def _expand(self, node: _Node) -> float:
        """node の legal actions + priors を確定、 leaf value を返す。"""
        if node.terminal:
            return self.value_fn(node.state, node.to_move)
        la = legal_actions(node.state)
        if not la:
            la = [EndPhase()]
        node.actions = la
        n = len(la)
        if self.prior == "uniform":
            node.P = [1.0 / n] * n
        else:
            node.P = [1.0 / n] * n  # Phase2 で policy net に差し替え
        node.N = [0] * n
        node.W = [0.0] * n
        return self.value_fn(node.state, node.to_move)

    def _select(self, node: _Node) -> int:
        total = sum(node.N)
        sq = math.sqrt(total + 1)
        best_i = 0
        best_u = -1e18
        for i in range(len(node.actions)):
            q = (node.W[i] / node.N[i]) if node.N[i] > 0 else 0.5
            u = q + self.c_puct * node.P[i] * sq / (1 + node.N[i])
            if u > best_u:
                best_u = u
                best_i = i
        return best_i

    def search(self, root_state: Any, n_sim: int) -> tuple:
        me = root_state.turn_player_idx
        defender = self._ensure_defender(root_state)
        root = _Node(fast_clone(root_state), me)
        self._expand(root)
        if root.terminal or len(root.actions) == 1:
            return (root.actions[0] if root.actions else EndPhase()), root

        # root prior を board_eval-softmax で focus (= uniform は探索が散る、 root だけ安く)
        if self.prior == "boardeval" and root.actions:
            from .eval import compute_score
            scores = []
            for a in root.actions:
                ch = fast_clone(root.state)
                try:
                    _apply_with_defense(ch, a, defender)
                    scores.append(compute_score(ch, me) / 3000.0)
                except Exception:
                    scores.append(-5.0)
            m = max(scores)
            exps = [math.exp(s - m) for s in scores]
            z = sum(exps) or 1.0
            root.P = [e / z for e in exps]

        for _ in range(n_sim):
            node = root
            path = []  # (node, action_idx)
            # selection
            while True:
                a_idx = self._select(node)
                path.append((node, a_idx))
                child = node.children.get(a_idx)
                if child is None:
                    # expand this edge
                    child_state = fast_clone(node.state)
                    try:
                        _apply_with_defense(child_state, node.actions[a_idx], defender)
                    except Exception:
                        # 不正手 → このedgeを軽くペナルティして打ち切り
                        v = 0.0
                        self._backup(path, v, node.to_move)
                        break
                    child = _Node(child_state, child_state.turn_player_idx)
                    node.children[a_idx] = child
                    v = self._expand(child)  # leaf eval
                    self._backup(path, v, child.to_move)
                    break
                node = child
                if node.terminal:
                    v = self.value_fn(node.state, node.to_move)
                    self._backup(path, v, node.to_move)
                    break
        # 訪問数最大の行動を選ぶ
        best_i = max(range(len(root.actions)), key=lambda i: root.N[i])
        return root.actions[best_i], root

    def _backup(self, path: list, v: float, leaf_to_move: int) -> None:
        for (node, a_idx) in reversed(path):
            vv = v if node.to_move == leaf_to_move else (1.0 - v)
            node.N[a_idx] += 1
            node.W[a_idx] += vv


class AZMctsAI:
    """PUCT MCTS で1手ずつ選ぶ AI (= receding horizon、 robust)。"""

    name = "AZMcts"

    def __init__(self, rng=None, deck_analysis=None, *, n_sim: int = 120,
                 c_puct: float = 1.5, value_fn=None, prior: str = "uniform", **kwargs):
        import random
        self.rng = rng or random.Random()
        self.deck_analysis = deck_analysis
        self._n_sim = n_sim
        from .ai import GreedyAI
        self._defender = GreedyAI(rng=self.rng, deck_analysis=deck_analysis)
        self._mcts = AZMcts(value_fn=value_fn, defender_ai=self._defender,
                            c_puct=c_puct, prior=prior)

    def choose_action(self, state):
        la = legal_actions(state)
        if not la:
            return EndPhase()
        if len(la) == 1:
            return la[0]
        try:
            action, _root = self._mcts.search(state, self._n_sim)
            return action
        except Exception:
            return self._defender.choose_action(state)

    # 防御は greedy 継承的に
    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        return self._defender.choose_defense(state, attacker, target, is_leader_attack, defender)
