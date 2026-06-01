# -*- coding: utf-8 -*-
"""OP13-079 イム leader 起動メインの choice cost
(= 「特徴《天竜人》を持つキャラ か 手札1枚 を トラッシュ」) の test。

[[project_card_effect_100_plan_kickoff]] 順2 prototype で fidelity gap と判明した
「天竜人キャラ trash 選択肢を略し discard_hand のみ実装」 を 複合 choice cost で是正した分の検証。
discard_hand_or_trash_filtered_chara cost key + payability + AI heuristic + 人間 modal (既存2種 reuse)。
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    resolve_triggers,
)

ROOT = Path(__file__).resolve().parent.parent
TENRYU = "OP13-091"  # 天竜人/五老星 キャラ
NON_TENRYU = "OP01-016"  # ナミ (天竜人ではない)
FILLER = "OP01-013"


def _repo():
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _setup(repo, overlay, hand_ids, chara_ids, human=False):
    p1 = Player(name="P0", leader=InPlay.of(repo.get("OP13-079"), sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.deck = [repo.get(FILLER)] * 10
    p2.deck = [repo.get(FILLER)] * 10
    p1.hand = [repo.get(c) for c in hand_ids]
    p1.characters = [InPlay.of(repo.get(c), sickness=False) for c in chara_ids]
    st = GameState(players=[p1, p2], phase=Phase.MAIN, rng=random.Random(3),
                   effects_overlay=overlay)
    p1.don_active = 5
    if human:
        st.human_player_idx = 0
        st.turn_player_idx = 0
    return st, p1, p2


def _leader_eff(overlay):
    return [e for e in overlay["OP13-079"].effects if e.get("when") == "activate_main"][0]


def _offered(st, p1, overlay):
    return any(ip is p1.leader for ip, _ in list_activate_main_effects(st, p1, overlay))


def test_ai_hand_available_discards_and_draws():
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [FILLER, FILLER], [])
    assert _offered(st, p1, overlay)
    deck0 = len(p1.deck)
    fire_activate_main(st, p1, p2, p1.leader, _leader_eff(overlay))
    resolve_triggers(st)
    assert len(p1.trash) == 1, "手札1枚trash"
    assert len(p1.deck) == deck0 - 1, "1ドロー"
    assert len(p1.hand) == 2, "手札 -1(discard) +1(draw)"


def test_ai_empty_hand_trashes_tenryu_chara_and_draws():
    """旧 bug: 手札空だと discard_hand 払えず発動不可。 是正後はキャラtrashで発動可。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [], [TENRYU])
    assert _offered(st, p1, overlay), "手札空でも天竜人キャラで発動可"
    deck0 = len(p1.deck)
    fire_activate_main(st, p1, p2, p1.leader, _leader_eff(overlay))
    resolve_triggers(st)
    assert len(p1.characters) == 0, "天竜人キャラがtrashされた"
    assert len(p1.deck) == deck0 - 1, "1ドロー"


def test_not_payable_when_no_hand_no_tenryu_chara():
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [], [NON_TENRYU])
    assert not _offered(st, p1, overlay), "手札空 + 天竜人キャラなし → 発動不可"


def test_human_hand_only_uses_unified_cost_pick_modal():
    """人間 + 手札のみ (盤面天竜人キャラ無し) → 統合 activate_main_cost_pick modal で
    手札候補のみ提示 → 選択解決で discard + draw。

    2026-06-01: 旧実装は手札ありだと activate_main_discard_pick (手札専用) modal を出し、
    盤面天竜人キャラがいても選択肢に出さなかった (= 人間選択の自動化 bug)。 統合 modal 化。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [FILLER, FILLER], [], human=True)
    deck0 = len(p1.deck)
    fire_activate_main(st, p1, p2, p1.leader, _leader_eff(overlay))
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "activate_main_cost_pick"
    cands = st.pending_choice["candidates"]
    assert all(c.get("axis") == "hand" for c in cands), "盤面キャラ無しなら手札候補のみ"
    resolve_pending_choice(st, [0])  # candidates index 0 (手札) を捨てる
    resolve_triggers(st)
    assert st.pending_choice is None
    assert len(p1.trash) == 1 and len(p1.deck) == deck0 - 1


def test_human_both_hand_and_chara_offers_both_axes():
    """★bug regression: 人間 + 手札あり + 盤面天竜人キャラあり → 統合 modal が
    両方 (手札 axis + キャラ axis) を提示し、 盤面キャラを trash する選択ができる。

    ohtsuki さん報告: 旧実装は手札があると盤面天竜人キャラの選択肢を出さず、
    公式「天竜人キャラ か 手札1枚」の2択を手札一択に潰していた (= 人間判断の自動化)。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [FILLER, FILLER], [TENRYU], human=True)
    deck0 = len(p1.deck)
    fire_activate_main(st, p1, p2, p1.leader, _leader_eff(overlay))
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "activate_main_cost_pick"
    cands = st.pending_choice["candidates"]
    assert any(c.get("axis") == "chara" for c in cands), "盤面天竜人キャラが選択肢に出る"
    assert any(c.get("axis") == "hand" for c in cands), "手札も選択肢に出る"
    # 盤面キャラ (axis=chara) を選んで trash → 盤面キャラが消え、 手札は減らない
    chara_idx = next(i for i, c in enumerate(cands) if c.get("axis") == "chara")
    hand0 = len(p1.hand)
    resolve_pending_choice(st, [chara_idx])
    resolve_triggers(st)
    assert st.pending_choice is None
    assert len(p1.characters) == 0, "選んだ盤面天竜人キャラが trash された"
    assert len(p1.hand) == hand0 + 1, "手札は減らず draw +1 のみ (= キャラを切ったので)"
    assert len(p1.deck) == deck0 - 1, "1ドロー"


def test_human_empty_hand_path_uses_chara_pick_modal():
    """人間 + 手札空 + 天竜人キャラ → activate_main_cost_pick(trash_filtered_chara) → 解決でtrash+draw。"""
    repo, overlay = _repo(), load_effect_overlay(ROOT / "db" / "card_effects.json")
    st, p1, p2 = _setup(repo, overlay, [], [TENRYU], human=True)
    deck0 = len(p1.deck)
    fire_activate_main(st, p1, p2, p1.leader, _leader_eff(overlay))
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "activate_main_cost_pick"
    assert st.pending_choice["cost_kind"] == "trash_filtered_chara"
    resolve_pending_choice(st, [0])
    resolve_triggers(st)
    assert st.pending_choice is None
    assert len(p1.characters) == 0 and len(p1.deck) == deck0 - 1
