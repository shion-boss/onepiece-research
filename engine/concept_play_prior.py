# -*- coding: utf-8 -*-
"""デッキの concept(= 設計上の方針)に沿った card play を beam 選別で加点する concept play-prior。

ohtsuki『archetype 判定が粗い。 各デッキ固有の concept(何をコントロールしてどう勝つか)で打て』
([[project_leader_aware_matchup_ai]])。 配備 GBM value は concept/archetype を使わず board のみ →
concept を効かせるには探索 prior で「concept 整合の手」を beam が捨てないよう誘導する。

原理: `db/deck_concept_profiles.json` の各デッキ concept は prior_card_ids(= concept を前に進める
key card、 役割 = ramp/big_threat 等)を持つ。 それらを play する手を beam 選別スコアで加点。
例: dofla(ramp concept)は ramp(ベビー5/モネ/ピーカ/トレーボル)+ big_threat(10c/8cドフラ)の
play を優先探索 → 「除去 control と誤操縦して durdle」 を是正し ランプ→大型展開を実行させる。

⚠ 設計鉄則(既存 deck_play_prior と同じ、 [[project_combo_aware_ai]]):
  - **beam 選別スコアにのみ加える**(post-opp 再ランクの calibrated value には足さない。 value を
    直接歪めると camp 誘因で自滅)。
  - **asymmetric**: concept 整合を**足すだけ**、 off-concept を**罰しない**(flat-defer は winrate↓)。
  - concept を持つ deck(= profile に prior_card_ids あり)だけ作用、 他は no-op。
  - env `ONEPIECE_CONCEPT_PRIOR_W` で per-AI に bracket(片側 ON で A/B 可)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .game import PlayCharacter, PlayEvent, PlayStage

_ROOT = Path(__file__).resolve().parent.parent
_CACHE: Optional[dict] = None


def _load() -> dict:
    """leader_id → prior_card_ids(set) の map(= deck の concept key cards)。 1 度だけ load。"""
    global _CACHE
    if _CACHE is None:
        m: dict = {}
        try:
            data = json.loads((_ROOT / "db" / "deck_concept_profiles.json").read_text(encoding="utf-8")).get("decks", {})
            for _slug, p in data.items():
                lid = p.get("leader")
                ids = p.get("prior_card_ids") or []
                if lid and ids:
                    m[lid] = set(ids)
        except Exception:
            m = {}
        _CACHE = m
    return _CACHE


def concept_play_bonus(state, action, me_idx: int) -> float:
    """concept 整合の card play なら 1.0(= W でスケール)、 それ以外 0.0。 asymmetric。"""
    if not isinstance(action, (PlayCharacter, PlayEvent, PlayStage)):
        return 0.0
    try:
        me = state.players[me_idx]
        lid = me.leader.card.card_id
    except Exception:
        return 0.0
    prior = _load().get(lid)
    if not prior:
        return 0.0
    try:
        cid = me.hand[action.hand_idx].card_id
    except Exception:
        return 0.0
    return 1.0 if cid in prior else 0.0
