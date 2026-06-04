# -*- coding: utf-8 -*-
"""source 系/特殊コストの強制 (= cost を払わず効果だけ無償発動するバグ class の回帰)。

2026-06-04: ohtsuki 実プレイで OP10-072 (discard_hand_with_filter) のコスト踏み倒しが
発覚 → 予防監査で _can_pay/_pay_counter_cost が未処理だった cost キーを一掃:
  rest_self / trash_self / self_ko / return_self_don_to_deck / trash_to_deck /
  life_to_hand / life_top_or_bottom_to_hand / reveal_hand_with_filter。
これらは on_play 等の「コスト：効果」で コストを払わず効果だけ発動していた (公式 4-10 違反)。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.effects import trigger_on_play

import tests.test_effects as T


def _fresh():
    repo, overlay = T._repo(), T._overlay()
    s = T._make_state(repo, "OP01-001", overlay=overlay)
    s.turn_player_idx = 0
    s.human_player_idx = None
    return s, s.players[0], s.players[1], repo, overlay


def _low_cost_chara(repo):
    return next(c for cid, c in repo._by_id.items()
               if c.category.name == "CHARACTER")


def test_rest_self_paid(repo=None):
    """OP10-112: rest_self を払って (= 自レスト) 効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    opp.life = [_low_cost_chara(repo) for _ in range(5)]
    src = InPlay.of(repo.get("OP10-112"), sickness=True, rested=False)
    me.characters.append(src)
    l0 = len(opp.life)
    trigger_on_play(s, me, opp, src, overlay)
    assert src.rested, "rest_self コストが払われていない (= 自レストせず効果のみ)"
    assert len(opp.life) == l0 - 1, "効果 (相手ライフトラッシュ) が出ていない"


def test_return_don_cost_feasibility():
    """OP06-074: return_self_don_to_deck=1。 ドン0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.don_active = 0
    me.don_rested = 0
    victim = InPlay.of(repo.get("OP04-077"), sickness=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-074"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert victim in opp.characters, "ドン0でコスト払えないのに効果 (KO/無効) が発動した"


def test_return_don_cost_paid():
    """OP06-074: ドンがあれば 1 枚戻して効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    me.don_active = 5
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP06-074"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert me.don_active == 4, "return_self_don_to_deck コストが払われていない"


def test_life_cost_feasibility():
    """OP11-106: life_top_or_bottom_to_hand=1。 ライフ0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.life = []
    me.hand = []
    victim = InPlay.of(repo.get("OP04-077"), sickness=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP11-106"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert victim in opp.characters, "ライフ0でコスト払えないのに効果 (KO) が発動した"


def test_life_cost_paid():
    """OP11-106: ライフがあれば 1 枚手札に加えて効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    me.life = [_low_cost_chara(repo) for _ in range(4)]
    me.hand = []
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP11-106"), sickness=True)
    me.characters.append(src)
    lf0 = len(me.life)
    trigger_on_play(s, me, opp, src, overlay)
    assert len(me.life) == lf0 - 1, "life コストが払われていない"
    assert len(me.hand) == 1, "ライフが手札に加わっていない"


def test_trash_self_paid():
    """OP15-100: trash_self を払って (= 自身トラッシュ) 効果発動。"""
    s, me, opp, repo, overlay = _fresh()
    opp.characters = [InPlay.of(repo.get("OP04-077"), sickness=False)]
    src = InPlay.of(repo.get("OP15-100"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert src not in me.characters, "trash_self コストが払われていない (= 自身が場に残存)"
    assert "OP15-100" in [c.card_id for c in me.trash], "自身がトラッシュに置かれていない"


def test_reveal_hand_cost_feasibility():
    """OP08-040: reveal_hand_with_filter (白ひげ2枚)。 該当0 なら払えず効果不発。"""
    s, me, opp, repo, overlay = _fresh()
    me.hand = []  # 白ひげ海賊団 なし
    victim = InPlay.of(repo.get("OP04-077"), sickness=False, rested=False)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP08-040"), sickness=True)
    me.characters.append(src)
    trigger_on_play(s, me, opp, src, overlay)
    assert not victim.rested, "公開コスト払えないのに効果 (相手レスト) が発動した"


def test_activate_main_trash_to_deck_cost():
    """OP05-082 起動メイン: rest_self + trash_to_deck=2。 trash 不足なら払えず、
    足りれば 2 枚デッキ下へ (= activate_main 経路の trash_to_deck 踏み倒し回帰)。"""
    import json
    from engine.effects import fire_activate_main, _can_pay_activate_cost
    s, me, opp, repo, overlay = _fresh()
    am = [x for x in json.load(open("db/card_effects.json"))["OP05-082"]
          if isinstance(x, dict) and x.get("when") == "activate_main"][0]
    src = InPlay.of(repo.get("OP05-082"), sickness=False, rested=False)
    me.characters.append(src)
    me.trash = [repo.get("OP04-077")]  # 1 枚 < 2
    assert not _can_pay_activate_cost(s, me, src, am["cost"]), "trash<2 なのに払える判定"
    me.trash = [repo.get("OP04-077") for _ in range(6)]
    assert _can_pay_activate_cost(s, me, src, am["cost"])
    tr0, dk0 = len(me.trash), len(me.deck)
    fire_activate_main(s, me, opp, src, am)
    assert src.rested, "rest_self が払われていない"
    assert len(me.trash) == tr0 - 2, "trash_to_deck=2 が払われていない"
    assert len(me.deck) == dk0 + 2, "デッキに 2 枚戻っていない"


def test_opp_attack_rest_self_cost():
    """OP07-024 コアラ 相手アタック時: rest_self コスト。 AI defender は即時支払 (= 自レスト)。

    bug (2026-06-04 修正前): opp_attack の AI 支払いが pay_don/rest_self_don/discard_hand のみ
    inline で、 rest_self/trash_self/discard_hand_with_filter を踏み倒していた。
    """
    from engine.effects import trigger_on_opp_attack
    s, me, opp, repo, overlay = _fresh()
    s.turn_player_idx = 1  # 相手ターン
    koala = InPlay.of(repo.get("OP07-024"), sickness=False, rested=False)
    me.characters.append(koala)
    atk = InPlay.of(repo.get("OP04-077"), sickness=False, rested=False)
    opp.characters.append(atk)
    trigger_on_opp_attack(s, me, opp, atk, overlay)
    assert koala.rested, "opp_attack の rest_self コストが払われていない (= 自レストせず)"


def test_human_opp_attack_rest_self_paid():
    """人間 defender が opp_attack 効果 (OP07-024 rest_self) を発動 → 自レスト (踏み倒さない)。

    bug (2026-06-04 修正前): apply_human_use_opp_attack_effect も pay_don/rest_self_don/
    discard_hand のみ inline 支払で source 系コストを踏み倒していた。
    """
    import json
    from pathlib import Path
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.effects import load_effect_overlay
    from engine.human_session import HumanSession
    from engine.ai import GreedyAI
    root = Path(__file__).resolve().parent.parent
    repo = CardRepository.from_json(root / "db" / "cards.json")
    overlay = load_effect_overlay(root / "db" / "card_effects.json")
    deck_json = json.loads((root / "decks" / "cardrush_1456.json").read_text(encoding="utf-8"))
    da = make_deck_from_dict(deck_json, repo)
    db = make_deck_from_dict(deck_json, repo)
    session = HumanSession(
        deck_a=da, deck_b=db,
        ai_factory=lambda rng, deck_analysis=None: GreedyAI(rng=rng),
        seed=1, effects_overlay=overlay, human_first=True)
    session.advance_until_pause()
    state = session.state
    defender = state.players[session.human_idx]
    koala = InPlay.of(repo.get("OP07-024"), sickness=False, rested=False)
    defender.characters.append(koala)
    bundle = overlay.get("OP07-024")
    idx = next(i for i, e in enumerate(bundle.effects) if e.get("when") == "opp_attack")
    state._available_opp_attack_effects = [{
        "source_iid": koala.instance_id, "card_id": "OP07-024", "effect_idx": idx,
        "when_key": "opp_attack", "pay_don": 0, "rest_self_don": 0, "discard_hand": 0,
        "rest_self": True, "trash_self": False, "discard_hand_with_filter": False,
    }]
    session.pending_kind = "defense"
    session.apply_human_use_opp_attack_effect(koala.instance_id, idx)
    assert koala.rested, "人間 opp_attack の rest_self コストが払われていない"
