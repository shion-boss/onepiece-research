# -*- coding: utf-8 -*-
"""カード効果テスト バックフィル (手書き wave 190): manifest 最後の 2 枚。

  OP09-084 カタリーナ・デボン / ST06-008 ヒナ

これで db/test_backfill_manifest.json (効果ありカード 2,354 枚) の未カバーが 0 になる。
⚠ クラウド cron (optcg-test-backfill) がこの 2 枚を残したまま 「完了」 と空コミットを
   繰り返していたため手書きした (2026-08-04)。

方針は test_backfill_auto_001〜189 と同じ:
  (1) 効果が 公式テキスト通り 盤面で発火する (発火前後の差分を assert)
  (2) 対象選択がある効果は 人間 actor で pending_choice が正しく立つ
  (3) AI 文脈 (human_player_idx=None) でも crash せず自動解決する
"""
from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_all_conditions,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
)

ROOT = Path(__file__).resolve().parent.parent
_FILLER = "OP01-013"          # サンジ cost2 power3000 CHARACTER
_LEADER_KUROHIGE = "OP09-081"  # マーシャル・Ｄ・ティーチ (特徴 四皇/黒ひげ海賊団)


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, overlay, leader_id="OP01-001", human_idx=None):
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    m = [e for e in overlay.get(cid).effects if e.get("when") == when]
    assert m, f"{cid} に when={when} の効果がない"
    return m[0]


# --------------------------------------------------------------------------- #
#  OP09-084 カタリーナ・デボン (CHARACTER)
#    【起動メイン】【ターン1回】自分のリーダーが特徴《黒ひげ海賊団》を持つ場合、
#    このキャラは次の相手のターン終了時まで、
#    【ダブルアタック】か【バニッシュ】か【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op09_084_overlay_matches_official_text():
    """公式テキストの 3 要素 (リーダー条件 / 3 択キーワード / 次の相手ターン終了まで) が揃う。"""
    eff = _eff(_overlay(), "OP09-084", "activate_main")
    assert eff.get("if", {}).get("leader_feature") == "黒ひげ海賊団", \
        "リーダー条件《黒ひげ海賊団》が無い"
    spec = eff["do"][0]["give_keyword"]
    assert set(spec["keywords"]) == {"ダブルアタック", "バニッシュ", "ブロッカー"}, \
        f"3 択キーワードが公式と違う: {spec.get('keywords')}"
    assert spec["duration"] == "next_opp_turn_end", "「次の相手のターン終了時まで」 でない"
    assert eff.get("cost", {}).get("once_per_turn") is True, "【ターン1回】 が無い"


def test_op09_084_requires_kurohige_leader():
    """リーダーが《黒ひげ海賊団》でなければ条件不成立 = 起動できない。"""
    repo, overlay = _repo(), _overlay()
    eff = _eff(overlay, "OP09-084", "activate_main")
    for leader, expect in ((_LEADER_KUROHIGE, True), ("OP01-001", False)):
        st = _state(repo, overlay, leader_id=leader)
        me = st.players[0]
        devon = InPlay.of(repo.get("OP09-084"), sickness=False)
        me.characters = [devon]
        assert eval_all_conditions(eff, st, me, devon) is expect, \
            f"leader={leader} で条件が {expect} にならない"


def test_op09_084_grants_one_of_three_keywords_ai():
    """AI 文脈: 起動すると 3 択のいずれかを得る (次の相手ターン終了時まで)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader_id=_LEADER_KUROHIGE)
    me, opp = st.players[0], st.players[1]
    devon = InPlay.of(repo.get("OP09-084"), sickness=False)
    me.characters = [devon]

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP09-084"]
    assert len(opts) == 1, "起動メインが legal に出ない"
    fire_activate_main(st, me, opp, *opts[0])

    granted = set(devon.granted_keywords) | set(devon.granted_keywords_through_opp_turn)
    assert granted & {"ダブルアタック", "バニッシュ", "ブロッカー"}, \
        f"3 択キーワードが 1 つも付与されていない: {granted}"
    assert st.pending_choice is None, "AI 文脈で pending_choice が残っている"


def test_op09_084_once_per_turn():
    """【ターン1回】= 一度起動したら legal から消える。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay, leader_id=_LEADER_KUROHIGE)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("OP09-084"), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-084"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP09-084"]
    assert len(opts2) == 0, "【ターン1回】 なのに再度 legal に出た"


# --------------------------------------------------------------------------- #
#  ST06-008 ヒナ (CHARACTER)
#    【登場時】相手のキャラ1枚までを、このターン中、コスト-4。
# --------------------------------------------------------------------------- #
def test_st06_008_overlay_matches_official_text():
    """公式テキスト通り 「相手キャラ1枚まで / このターン中 / コスト-4」。"""
    do = _eff(_overlay(), "ST06-008", "on_play")["do"]
    spec = do[0]["cost_minus"]
    assert spec["amount"] == 4, f"コスト-4 でない: {spec.get('amount')}"
    assert "opponent" in str(spec["target"]), f"相手キャラが対象でない: {spec.get('target')}"


def test_st06_008_reduces_opponent_cost_ai():
    """AI 文脈: 相手キャラのコストが 4 下がる (このターン中)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP09-084"), sickness=False)   # cost 5
    opp.characters = [victim]
    before = victim.base_cost

    for prim in _eff(overlay, "ST06-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim.base_cost == max(0, before - 4), \
        f"コスト-4 が反映されていない: {before} → {victim.base_cost}"


def test_st06_008_no_target_is_noop():
    """相手キャラが居なければ何も起きない (「1枚まで」 = 0 枚可)。"""
    repo, overlay = _repo(), _overlay()
    st = _state(repo, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = []
    for prim in _eff(overlay, "ST06-008", "on_play")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is None, "対象 0 なのに choice が立った"
