# -*- coding: utf-8 -*-
"""replace_leave 無限ループ + opp_attack stale payload ループ の退行ガード。

2026-06-05 aggressive human bot (= 常に効果発動・modal は全候補 pick) が環境デッキで検出:
- **replace_leave 無限ループ**: 相手 (AI) の置換効果 (OP15-052 レオ「相手効果で自キャラが
  離れる場合、代わりに自キャラ1枚をデッキ下に」) の target_pick が **actor=AI なのに human に
  出て human 視点で解決** され、 自陣 return が by_opp_effect=True 扱いになって レオの replace を
  自己再誘発 → 無限ループ。 修正: 置換 do を holder の owner の actor 文脈で解決 (forced=-1)。
- **opp_attack stale payload**: 払えない opp_attack 効果を graceful skip した後、 session の
  pending_payload を最新 available に同期せず、 client が同じ stale 効果を再指定し続けてループ。

aggressive bot で 検出時の 8 seed を完走させ、 STUCK しないことを保証する。
"""
from __future__ import annotations

import random

import pytest

import scripts.fuzz_human_play as F

F._setup()


def _aggro_pick(pl, rng):
    k = pl.get("kind")
    lim = int(pl.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]
    if k in ("optional_cost_confirm", "replace_ko_optional", "reveal_top_play_confirm",
             "on_attack_optional", "on_opp_attack_optional", "end_of_turn_optional",
             "life_taken_choice", "view_life_top_choose_position", "option_pick"):
        return [1]
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        cs = pl.get("candidates") or pl.get("cards") or []
        o = list(range(len(cs)))
        rng.shuffle(o)
        return o
    cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    return list(range(min(lim, len(cs)))) if cs else []


def _play_aggro(a, b, seed, hf):
    """常に効果発動・常にブロック&カウンター・modal は全候補で解決して完走を試みる。"""
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None
    same = 0
    while not s.state.game_over and steps < 2500:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(pl.get("available_opp_attack_effects") or []))
        if sig == last:
            same += 1
            if same > 80:
                return "STUCK"
        else:
            same = 0
            last = sig
        if pk == "choice":
            s.apply_human_choice(_aggro_pick(pl, rng))
        elif pk == "action":
            acts = s.legal_actions_for_human()
            if not acts:
                break
            ne = [x for x in acts if x.get("kind") != "EndPhase"]
            s.apply_human_action((rng.choice(ne) if ne else acts[0])["idx"])
        elif pk == "defense":
            avail = pl.get("available_opp_attack_effects") or []
            if avail:
                e = avail[0]
                s.apply_human_use_opp_attack_effect(e["source_iid"], e["effect_idx"])
            else:
                blk = pl.get("legal_blocker_iids") or []
                cnt = pl.get("legal_counter_card_idxs") or []
                s.apply_human_defense(blk[0] if blk else None, cnt[:1] if cnt else [])
        else:
            break
    return "OK" if s.state.game_over else "BREAK"


# 検出時に STUCK した (deck_a, deck_b, seed, human_first)。
CASES = [
    ("cardrush_1399", "cardrush_1399", 40000, True),   # replace_leave loop
    ("cardrush_1392", "cardrush_1399", 40001, False),  # replace_leave loop
    ("cardrush_1342", "cardrush_1342", 40009, False),  # opp_attack stale payload
    ("cardrush_1399", "cardrush_1399", 40003, False),  # opp_attack stale payload
    ("cardrush_1399", "cardrush_1439", 40006, False),  # opp_attack stale payload
]


@pytest.mark.parametrize("a,b,seed,hf", CASES)
def test_aggressive_bot_does_not_stuck(a, b, seed, hf):
    """aggressive bot で STUCK (= 無限ループ / stale payload ループ) しない。"""
    assert _play_aggro(a, b, seed, hf) != "STUCK", (
        f"{a} vs {b} seed={seed}: STUCK (= replace_leave 無限ループ / opp_attack stale payload 再発)"
    )
