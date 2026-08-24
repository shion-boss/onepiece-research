# -*- coding: utf-8 -*-
"""選択列挙 ON で **Rust に移植した primitive** の Python↔Rust パリティ (primitive 単位)。

⚠ 対戦ハーネス (`rust_choice_parity`) は 16 メタデッキしか回さないので、
  そこに入っていないカードの primitive は **一度も踏まれない**。 移植したのに壊れていても
  緑のままになるため、 primitive を直接撃って両エンジンを突き合わせる。

⚠ 列挙 ON の比較は **両側とも選択を解決しきってから**。 Rust 側は
  `apply_raw_effect_choice_policy` (= `apply_action_choice_policy` と同じ決定的方針)。
  片側だけ解決すると 「ライフ 1 枚をデッキへ」 のように **解決で盤面が動く** primitive が
  偽 MISMATCH になる (2026-08-24 に実際に踏んだ)。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DECK = ["OP01-013", "OP01-016", "OP01-025", "OP02-013", "OP03-013",
        "OP05-013", "OP06-013", "OP07-013"]

# 移植した primitive と、 その代表 spec (overlay の実 spec に合わせる)
CASES = [
    ("scry_deck_reorder d3", {"scry_deck_reorder": {"depth": 3}}),
    ("scry_deck_reorder d5", {"scry_deck_reorder": {"depth": 5}}),
    ("scry_all_life_reorder self", {"scry_all_life_reorder": True}),
    ("scry_all_life_reorder opp", {"scry_all_life_reorder": {"owner": "opp"}}),
    ("scry_all_life_one_to_deck top", {"scry_all_life_one_to_deck": True}),
    ("scry_all_life_one_to_deck bottom", {"scry_all_life_one_to_deck": {"to": "bottom"}}),
    ("scry_life d1 self_or_opp", {"scry_life": {"depth": 1, "owner": "self_or_opp"}}),
    ("scry_life d3 self", {"scry_life": {"depth": 3, "owner": "self"}}),
    ("view_life either d1", {"view_life_top_choose_position": {"depth": 1, "owner": "either"}}),
    ("view_life self d2", {"view_life_top_choose_position": {"depth": 2, "owner": "self"}}),
    ("view_life opp d1", {"view_life_top_choose_position": {"depth": 1, "owner": "opp"}}),
    ("self_hand_to_size 1", {"self_hand_to_size": 1}),
    ("draw_per_chara_then_discard", {"draw_per_self_chara_then_discard": {}}),
    ("play_from_hand_choice l1", {"play_from_hand_choice": {"filter": {}, "limit": 1}}),
    ("play_from_hand_choice l2", {"play_from_hand_choice": {"filter": {}, "limit": 2}}),
    ("reveal_hand_play_split",
     {"reveal_hand_play_split": {"filter": {}, "reveal_limit": 2, "extra_rested_cost_le": 4}}),
    # ⚠ 移植ではなく **既存バグの回帰ガード**: 手札から登場させる候補のソート比較子が
    #   コスト昇順 (= 一番弱い札) になっていた。 該当 2 primitive はメタ 16 デッキに
    #   入っていないので、 対戦ハーネスでも掃引でも一度も踏まれない。
    ("play_from_hand_named_with_dynamic_cost",
     {"play_from_hand_named_with_dynamic_cost":
      {"name_filter": {}, "cost_ge": 0, "cost_le_source": "fixed", "cost_le": 99}}),
]


def _mk(repo, ov, enum: bool):
    from engine.core import GameState, InPlay, Phase, Player
    from engine.game import _recompute_static

    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-002"), sickness=False))
    for p in (p0, p1):
        p.deck = [repo.get(i) for i in DECK] * 3
        p.life = [repo.get(i) for i in DECK[:4]]
        p.life_face_up = [False] * 4
        p.hand = [repo.get(i) for i in DECK[:3]]
    # draw_per_self_chara_then_discard が 「自キャラ 1 枚につき 1 ドロー」 なので 2 体置く
    for _ in range(2):
        p0.characters.append(InPlay.of(repo.get("OP01-016"), sickness=False))
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(11),
                   effects_overlay=ov)
    st.turn_player_idx = 0
    st.choice_enumeration = enum
    # ⚠ Python は ResolveChoice を apply_action で解決するので _recompute_static が走る。
    #   Rust 側の入口では走らないので **先に揃える** (揃えないと owner_idx だけで偽 MISMATCH)。
    _recompute_static(st)
    return st


@pytest.mark.parametrize("label,spec", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("enum", [False, True], ids=["off", "on"])
def test_ported_choice_prim_parity(label, spec, enum):
    import optcg_engine as eng

    from engine.deck import CardRepository
    from engine.effects import execute_effect, load_effect_overlay
    from engine.game import apply_action, legal_actions
    from engine.state_snapshot import full_dump, state_digest

    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    ov = load_effect_overlay(ROOT / "db" / "card_effects.json")

    st_py = _mk(repo, ov, enum)
    st_rs = _mk(repo, ov, enum)
    dump = json.dumps(full_dump(st_rs))
    if enum:
        rust = eng.apply_raw_effect_choice_policy(dump, json.dumps(spec), 0, 0)
    else:
        rust = eng.apply_raw_effect_digest(dump, json.dumps(spec), 0)

    execute_effect(spec, st_py, st_py.players[0], st_py.players[1], st_py.players[0].leader)
    guard = 0
    while st_py.pending_choice is not None and guard < 20:
        guard += 1
        acts = legal_actions(st_py)
        if not acts:
            st_py.pending_choice = None
            break
        apply_action(st_py, acts[0])  # 列挙器の先頭 = Rust の policy_k=0 と同じ

    assert state_digest(st_py) == rust, (
        f"{label} (enum={enum}) で Python↔Rust が乖離"
    )


def test_choice_unported_list_is_empty():
    """未移植 primitive は **0 件**。 増えたら学習分布が歪むので気付けるようにする。"""
    import optcg_engine as eng

    unported = set(json.loads(eng.choice_unported_prims()))
    assert unported == set(), (
        f"2026-08-24 に未移植 0 件へ到達した。 増えているなら移植漏れ: {sorted(unported)}"
    )
