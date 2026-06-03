# -*- coding: utf-8 -*-
"""層3/層6: プランの学習 bonus テーブル (= [[project_superhuman_ai_distillation]] 塊プラン)。

`(axes-cell, plan_multiset_signature)` ごとに self-play の勝敗 (n_total, n_won) を貯め、
**勝率 bonus 主 + 盤面 value 補完** (= Q1 の答え) を 1 つの [0,1] スコアに統合する:

    value = (n_won + k * prior) / (n_total + k),   prior = sigmoid(eval_score / temp)

- 学習データ無し (n=0) → value = prior (= 盤面 value 補完)。
- 学習データ豊富 → value → 実勝率 (= 勝率 bonus 主)。
- shrink k で低 n を prior へ縮約 (= ノイズ耐性、 既存 build_spec の shrink_k と同思想)。

eval_score (= 到達盤面 board_eval) は enumerate 時に AbstractPlan が持つので、 テーブル本体は
(cell, sig) → (n_total, n_won) だけ保持すれば良い (= 軽量)。 prior は推論時に注入する。

axes-cell は engine/axis_compute.compute_axes_from_state の 12 軸を正準タプル化して使う。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from .axis_compute import ENTRY_AXES_KEYS, compute_axes_from_state


# ===========================================================================
# 鍵の正準化
# ===========================================================================

# cell に使う軸。 fine = 12 軸 (= backward-compat の self_condition 除外)。
_CELL_AXES_FINE = tuple(k for k in ENTRY_AXES_KEYS if k != "self_condition")
# coarse = PoC 用 (= 学習サンプル密度を確保。 fine だと (cell,plan) が n≈1 で value≈prior
# = board_eval から動かず学習しない。 production は cascade で fine→coarse 緩和する想定)。
# opp_leader_id を使う (= archetype は live=JP/corpus=EN 正規化でズレ得る; leader_id は card_id で
# compute_axes_from_state / _from_snapshot 双方一致)。
_CELL_AXES_COARSE = ("turn", "opp_leader_id", "self_life_bucket", "opp_life_bucket")


def cell_key_from_state(state: Any, me_idx: int,
                        opp_archetype: str = "midrange",
                        axes_subset: tuple = _CELL_AXES_COARSE) -> tuple:
    """GameState → axes-cell の正準タプル (= hashable, 順序固定)。

    axes_subset で粒度を制御 (= 既定 coarse、 _CELL_AXES_FINE で 12 軸)。
    """
    axes = compute_axes_from_state(state, me_idx, opp_archetype)
    return tuple((k, axes.get(k)) for k in axes_subset)


def multiset_key(signature: tuple) -> frozenset:
    """ordered signature → 順序非依存 multiset key (= turn_plan_enumerator と同一規約)。"""
    from collections import Counter

    return frozenset(Counter(signature).items())


# ===========================================================================
# value 統合 (= 勝率 bonus 主 + 盤面 value 補完)
# ===========================================================================


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def fuse_value(eval_score: float, n_total: int, n_won: int,
               *, temp: float = 2000.0, shrink_k: float = 6.0) -> float:
    """plan の最終スコア [0,1] = (n_won + k*prior) / (n_total + k)。

    prior = sigmoid(eval_score / temp) (= 盤面 value を擬似勝率化)。
    n_total=0 で value=prior、 n_total→∞ で value→実勝率。

    ⚠ board_eval は数万スケールに振れる (= temp 固定の sigmoid は飽和して全 plan が prior≈1)。
    推論時は候補集合内の **相対 prior** (= eval percentile) を使う fuse_value_with_prior を
    使うこと。 これは単体テスト / スカラー用途のみ。
    """
    prior = _sigmoid(eval_score / temp)
    return (n_won + shrink_k * prior) / (n_total + shrink_k)


def fuse_value_with_prior(prior: float, n_total: int, n_won: int,
                          *, shrink_k: float = 6.0) -> float:
    """prior (= 候補集合内の board_eval 相対順位 [0,1]) を直接渡す版。

    value = (n_won + k*prior) / (n_total + k)。 n=0 で value=prior (= board_eval 順)、
    n 大で実勝率へ。 飽和しない (= 候補内 percentile を使うので常に discriminate)。
    """
    return (n_won + shrink_k * prior) / (n_total + shrink_k)


# ===========================================================================
# PlanBonusTable
# ===========================================================================


class PlanBonusTable:
    """(cell, multiset_sig) → {n_total, n_won} の学習テーブル。

    in-memory は hashable key (cell_tuple, mk_frozenset)、 永続化は JSON records。
    """

    def __init__(self, temp: float = 2000.0, shrink_k: float = 6.0):
        self._t: dict[tuple, list[int]] = {}  # (cell, mk) -> [n_total, n_won]
        self.temp = temp
        self.shrink_k = shrink_k

    # --- 学習 ---
    def update(self, cell: tuple, mk: frozenset, won: bool) -> None:
        rec = self._t.get((cell, mk))
        if rec is None:
            rec = [0, 0]
            self._t[(cell, mk)] = rec
        rec[0] += 1
        if won:
            rec[1] += 1

    def get_counts(self, cell: tuple, mk: frozenset) -> tuple[int, int]:
        rec = self._t.get((cell, mk))
        return (rec[0], rec[1]) if rec else (0, 0)

    # --- 推論: plan の value を返す ---
    def value(self, cell: tuple, mk: frozenset, eval_score: float) -> float:
        n_total, n_won = self.get_counts(cell, mk)
        return fuse_value(eval_score, n_total, n_won,
                          temp=self.temp, shrink_k=self.shrink_k)

    def value_with_prior(self, cell: tuple, mk: frozenset, prior: float) -> float:
        """prior (= 候補内 board_eval percentile [0,1]) を使う飽和しない版 (= 推論で使う)。"""
        n_total, n_won = self.get_counts(cell, mk)
        return fuse_value_with_prior(prior, n_total, n_won, shrink_k=self.shrink_k)

    def is_learned(self, cell: tuple, mk: frozenset, min_n: int = 1) -> bool:
        n_total, _ = self.get_counts(cell, mk)
        return n_total >= min_n

    # --- 永続化 ---
    def to_records(self) -> list[dict]:
        out = []
        for (cell, mk), (n_total, n_won) in self._t.items():
            out.append({
                "cell": [[k, v] for (k, v) in cell],
                "sig": [[list(tok), cnt] for (tok, cnt) in sorted(mk)],
                "n": n_total,
                "w": n_won,
            })
        return out

    @classmethod
    def from_records(cls, records: list[dict], temp: float = 2000.0,
                     shrink_k: float = 6.0) -> "PlanBonusTable":
        tbl = cls(temp=temp, shrink_k=shrink_k)
        for r in records:
            cell = tuple((k, v) for (k, v) in r["cell"])
            mk = frozenset((tuple(tok), cnt) for (tok, cnt) in r["sig"])
            tbl._t[(cell, mk)] = [int(r["n"]), int(r["w"])]
        return tbl

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "temp": self.temp, "shrink_k": self.shrink_k,
                "records": self.to_records(),
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "PlanBonusTable":
        path = Path(path)
        if not path.exists():
            return cls()
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_records(
            d.get("records", []), temp=d.get("temp", 2000.0),
            shrink_k=d.get("shrink_k", 6.0),
        )

    def __len__(self) -> int:
        return len(self._t)

    def merge_(self, other: "PlanBonusTable") -> None:
        """別テーブルの (n,w) を加算 (= 並列収集の集約用)。"""
        for key, (n_total, n_won) in other._t.items():
            rec = self._t.get(key)
            if rec is None:
                self._t[key] = [n_total, n_won]
            else:
                rec[0] += n_total
                rec[1] += n_won
