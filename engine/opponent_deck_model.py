"""相手デッキ belief モデル (runtime)。

対戦相手の leader (公開情報) と、これまでに見えた相手の札 (seen) から、
相手の 50 枚 main の中身を推定する。db/opponent_deck_priors.json を読み込み、
実大会レシピ集合の bootstrap で以下を提供する:

- belief_for_leader(leader, seen)  : per-card の P(積む) / E[枚数] (seen で事後更新)
- sample_main(leader, rng, seen)   : determinization 用に coherent な 1 デッキをサンプル
- top_cards(leader, n, seen)       : threat 評価用に「積まれやすいカード」上位

seen は「相手のデッキに最低何枚あると分かっているか」= {card_id: min_count}。
相手が場/トラッシュ/手札公開等で見せた札を集計して渡す想定。整合するレシピだけに
絞ることで、marginal より鋭い事後 belief になる。整合レシピが無い時は prior に degrade。

このモジュールは engine 内部状態に依存せず、leader_id (str) と seen (dict) だけで動く。
determinization / value feature / 分析 UI から共通で使える純関数的 API。
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PATH = _REPO_ROOT / "db" / "opponent_deck_priors.json"

# main 1 デッキの合計枚数 (公式構築ルール)
MAIN_DECK_SIZE = 50

Seen = dict[str, int]


def _consistent(main: list[list[Any]], seen: Seen) -> bool:
    """デッキ main が観測 seen と矛盾しないか (見えた枚数以上を積んでいるか)。"""
    if not seen:
        return True
    have: dict[str, int] = {cid: cnt for cid, cnt in main}
    return all(have.get(cid, 0) >= need for cid, need in seen.items())


def _marginals_from(decklists: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """レシピ集合から per-card marginal を再計算する (事後更新用)。"""
    n = len(decklists)
    if n == 0:
        return {}
    present: dict[str, int] = defaultdict(int)
    sum_count: dict[str, int] = defaultdict(int)
    for deck in decklists:
        for cid, cnt in deck["main"]:
            present[cid] += 1
            sum_count[cid] += cnt
    out: dict[str, dict[str, float]] = {}
    for cid, decks_with in present.items():
        out[cid] = {
            "prob": decks_with / n,
            "exp_count": sum_count[cid] / n,
            "mean_present": sum_count[cid] / decks_with,
            "n": decks_with,
        }
    return out


class OpponentDeckModel:
    """leader → 実レシピ集合 + marginal の belief モデル。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._meta: dict[str, Any] = data.get("meta", {})
        self._leaders: dict[str, Any] = data.get("leaders", {})

    # ---- 基本情報 -------------------------------------------------------
    @property
    def leaders(self) -> list[str]:
        return list(self._leaders.keys())

    def has_leader(self, leader_id: str) -> bool:
        return leader_id in self._leaders

    def n_decks(self, leader_id: str) -> int:
        entry = self._leaders.get(leader_id)
        return int(entry["n_decks"]) if entry else 0

    def _decklists(self, leader_id: str, seen: Seen | None) -> list[dict[str, Any]]:
        """leader の候補レシピを返す。seen があれば整合レシピに絞る (無ければ全体)。"""
        entry = self._leaders.get(leader_id)
        if not entry:
            return []
        pool: list[dict[str, Any]] = entry["decklists"]
        if seen:
            consistent = [d for d in pool if _consistent(d["main"], seen)]
            if consistent:
                return consistent
        return pool

    # ---- belief ---------------------------------------------------------
    def belief_for_leader(
        self, leader_id: str, seen: Seen | None = None
    ) -> dict[str, dict[str, float]]:
        """per-card の {prob, exp_count, mean_present, n}。

        seen 無し → 前計算 marginal (prior)。
        seen あり → 整合レシピに絞った事後 marginal (無ければ prior に degrade)。
        未知 leader → 空 dict。
        """
        entry = self._leaders.get(leader_id)
        if not entry:
            return {}
        if not seen:
            return entry["marginals"]
        consistent = [d for d in entry["decklists"] if _consistent(d["main"], seen)]
        if not consistent:
            return entry["marginals"]  # 整合レシピ無し → prior に degrade
        return _marginals_from(consistent)

    def top_cards(
        self, leader_id: str, n: int = 15, seen: Seen | None = None
    ) -> list[tuple[str, dict[str, float]]]:
        """積まれやすい順 (exp_count 降順) の上位 n カード。threat 評価用。"""
        belief = self.belief_for_leader(leader_id, seen)
        ranked = sorted(
            belief.items(), key=lambda kv: kv[1]["exp_count"], reverse=True
        )
        return ranked[:n]

    def prob(self, leader_id: str, card_id: str, seen: Seen | None = None) -> float:
        """特定カードを相手が積んでいる確率。未知は 0.0。"""
        info = self.belief_for_leader(leader_id, seen).get(card_id)
        return float(info["prob"]) if info else 0.0

    # ---- determinization ------------------------------------------------
    def sample_main(
        self,
        leader_id: str,
        rng: random.Random | None = None,
        seen: Seen | None = None,
    ) -> list[tuple[str, int]] | None:
        """coherent な 1 デッキ main をサンプル ((card_id, count) の list)。

        seen と整合する実レシピから一様に 1 つ引く。整合が無ければ leader の全レシピから。
        未知 leader は None。determinization の隠匿情報埋めに使う。
        """
        pool = self._decklists(leader_id, seen)
        if not pool:
            return None
        r = rng or random
        deck = r.choice(pool)
        return [(cid, cnt) for cid, cnt in deck["main"]]


@lru_cache(maxsize=1)
def get_default_model() -> OpponentDeckModel:
    """db/opponent_deck_priors.json を読み込んだ既定モデル (無ければ空)。"""
    if _DEFAULT_PATH.exists():
        data = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
    else:
        data = {"meta": {}, "leaders": {}}
    return OpponentDeckModel(data)


def load_model(path: str | Path | None = None) -> OpponentDeckModel:
    """明示パスから belief モデルを読む (テスト / 実験用)。"""
    p = Path(path) if path else _DEFAULT_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return OpponentDeckModel(data)
