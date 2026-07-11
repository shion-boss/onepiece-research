# -*- coding: utf-8 -*-
"""相手手札の「特徴」を デッキ採用率 prior + 盤面 から推定 (2026-07-11、 ohtsuki 案 ③)。

厳密カードでなく **決定に効く手札特徴**(速攻/大型カウンター/ブロッカー/除去 を持つか)を予測。
self-play 学習でなく **実レシピ由来の採用率 prior**(db/deck_feature_priors.json)を土台に、
「相手 leader のデッキは特徴F を平均 R 枚積む」→ 盤面/トラッシュで見えた分を引き → hand_size と
未確定枚数で hypergeometric 推定。 = deck データを根拠に、 全 leader へ即汎化(per-deck 学習不要)。

  P(手札に特徴F を1枚以上持つ) ≈ 1 - C(未確定-残F, H) / C(未確定, H)
  残F = max(0, 採用R - 場/墓地で見えたF), 未確定 = 50 - 場/墓地/ライフ等で見えた総数

runtime: HandFeaturePredictor().predict(leader_id, state, opp_idx) -> {feature: P}
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
from typing import Any

_REMOVAL_KW = ("KO", "手札に戻", "デッキの下", "レストに", "コストを-")
FEATURES = ("rush", "counter2000", "blocker", "removal")


def _card_features(card) -> dict:
    """CardDef から特徴フラグを算出 (build_feature_priors._feat と一致)。"""
    txt = getattr(card, "text", "") or ""
    cat = str(getattr(getattr(card, "category", None), "value", "")).upper()
    counter = int(getattr(card, "counter", 0) or 0)
    return {
        "rush": ("速攻" in txt) and cat == "CHARACTER",
        "blocker": ("ブロッカー" in txt),
        "counter2000": counter >= 2000,
        "removal": (cat in ("EVENT", "CHARACTER") and any(k in txt for k in _REMOVAL_KW)),
    }


def _cid(c):
    return getattr(c, "card_id", None) or getattr(getattr(c, "card", None), "card_id", None)


def _card_of(inplay):
    return getattr(inplay, "card", None) or inplay


class HandFeaturePredictor:
    def __init__(self, priors_path: str | None = None):
        p = priors_path or os.path.join(os.getcwd(), "db", "deck_feature_priors.json")
        self.priors = {}
        try:
            self.priors = json.load(open(p, encoding="utf-8"))
        except Exception:
            self.priors = {}
        # 全 leader 平均 (未知 leader の fallback)
        self._avg = {f: 0.0 for f in FEATURES}
        n = 0
        for lid, prof in self.priors.items():
            n += 1
            for f in FEATURES:
                self._avg[f] += prof.get(f, 0.0)
        if n:
            for f in FEATURES:
                self._avg[f] /= n

    def deck_prior(self, leader_id: str) -> dict:
        prof = self.priors.get(leader_id)
        if not prof:
            return dict(self._avg)
        return {f: prof.get(f, self._avg[f]) for f in FEATURES}

    @staticmethod
    def _p_at_least_one(unseen_total: int, remaining_f: float, hand_size: int) -> float:
        """未確定 unseen_total 枚 (= hand+deck) に 特徴F が remaining_f 枚。 hand H 枚に 1枚以上入る確率。"""
        if hand_size <= 0 or unseen_total <= 0 or remaining_f <= 0:
            return 0.0
        rf = min(remaining_f, unseen_total)
        # P(0 枚) = Π (未確定-残F-i)/(未確定-i)  i=0..H-1  (hypergeometric)
        p0 = 1.0
        for i in range(int(hand_size)):
            num = unseen_total - rf - i
            den = unseen_total - i
            if den <= 0:
                break
            p0 *= max(0.0, num) / den
        return 1.0 - p0

    def predict(self, leader_id: str, state: Any, opp_idx: int) -> dict:
        """相手(opp_idx)の手札が各特徴を1枚以上持つ確率。"""
        opp = state.players[opp_idx]
        prior = self.deck_prior(leader_id)
        hand_size = len(getattr(opp, "hand", []))
        # 見えた札 (場・墓地・ライフtaken 等) の特徴別カウント + 総見え枚数
        seen_cards = list(getattr(opp, "characters", [])) + list(getattr(opp, "trash", []))
        seen_total = len(seen_cards) + hand_size  # 手札は枚数のみ既知(中身不明)
        seen_f = {f: 0 for f in FEATURES}
        for c in seen_cards:
            feats = _card_features(_card_of(c))
            for f in FEATURES:
                if feats.get(f):
                    seen_f[f] += 1
        deck_size = 50
        unseen_total = max(hand_size, deck_size - len(seen_cards))  # hand + 残 deck
        out = {}
        for f in FEATURES:
            remaining = max(0.0, prior.get(f, 0.0) - seen_f[f])
            out[f] = self._p_at_least_one(unseen_total, remaining, hand_size)
        return out


_DEFAULT = None


def get_default() -> HandFeaturePredictor:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HandFeaturePredictor()
    return _DEFAULT
