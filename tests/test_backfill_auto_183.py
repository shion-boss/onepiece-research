# -*- coding: utf-8 -*-
"""ST22 / ST23 弾 効果 回帰テスト バックフィル (自動生成 wave 183):
ST22-003 / ST22-005 / ST22-006 / ST22-007 / ST22-011 / ST22-012 /
ST22-016 / ST22-017 / ST23-001 / ST23-002 の 10 枚。

  ST22-003 エドワード・ニューゲート (CHARACTER 青) = 【登場時】デッキ上1枚公開し
     『白ひげ海賊団』なら 2 枚引く (on_play, reveal_top_then filter 白ひげ → draw2)
  ST22-005 光月おでん (CHARACTER 青) = 相手効果で離脱する場合 代わりに手札2枚捨て /
     【起動メイン】【ターン1回】ドン3レスト + 自キャラ1枚手札戻し：このキャラをアクティブに
     (replace_leave trash_self_hand_random2, activate_main return_to_hand+untap)
  ST22-006 ジョズ (CHARACTER 青) = 【登場時】デッキ上1枚公開し『白ひげ海賊団』なら
     2 枚引き手札1枚捨て (on_play, reveal_top_then → draw2 + trash1)
  ST22-007 スクアード (CHARACTER 青) = 【起動メイン】【ターン1回】デッキ上1枚公開し
     『白ひげ海賊団』なら 自リーダーかキャラ1枚にレストドン1枚付与
     (activate_main, reveal_top_then → attach_rested_don self_inplay_choice)
  ST22-011 ホワイティベイ (CHARACTER 青) = 【自ターン中】【登場時】手札の白ひげ2枚公開：
     自白ひげリーダー1枚 +2000 (on_play, optional_cost_then reveal_hand → power_pump self_leader)
  ST22-012 マルコ (CHARACTER 青) = 【ターン1回】相手効果KO時 代わりに手札1枚捨て /
     【アタック時】デッキ上1枚公開し『白ひげ海賊団』なら +1000 (次相手end まで)
     (replace_ko trash1, on_attack reveal_top_then → power_pump self)
  ST22-016 取り消せよ……!!!今の言葉……!!! (EVENT 青) = 【カウンター】デッキ上1枚公開し
     『白ひげ海賊団』なら 自リーダーかキャラ1枚 +4000 / トリガー 1 枚引く
     (counter reveal_top_then → power_pump one_self_team_any, trigger draw)
  ST22-017 火拳 (EVENT 青) = 【メイン】手札の白ひげ2枚公開：1枚引き コスト5以下キャラ1枚デッキ下 /
     トリガー コスト3以下キャラ1枚手札戻し
     (main optional_cost_then reveal_hand → draw + return_to_deck_bottom, trigger return_to_hand)
  ST23-001 ウタ (CHARACTER 赤) = 手札のこのカードは 自パワー10000以上キャラがいれば コスト-4
     (in_hand, if self_chara_power_ge 10000 → in_hand_cost_minus 4)
  ST23-002 シャンクス (CHARACTER 赤) = 【登場時】リーダーが《赤髪海賊団》か「ウタ」なら
     リーダー +2000 (次相手end まで) (on_play, if or[leader_feature/leader_name] → power_pump self_leader)

目的 (= test_backfill_auto_001〜182.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)
from engine.game import _compute_in_hand_cost_minus

ROOT = Path(__file__).resolve().parent.parent

_LEADER_RED = "OP01-001"      # ロロノア・ゾロ (麦わらの一味) — 赤の汎用リーダー
_LEADER_WB = "ST22-001"       # エース＆ニューゲート (白ひげ海賊団) リーダー
_LEADER_SHANKS = "OP09-001"   # シャンクス (四皇/赤髪海賊団) リーダー
_FILLER = "OP01-016"          # ナミ cost1 power2000 麦わらの一味 (白ひげ でない)
_WB_TOP = "ST22-002"          # イゾウ (ワノ国/白ひげ海賊団) = デッキ上/手札公開用
_WB_TOP2 = "ST22-004"         # エルミー (白ひげ海賊団傘下) — 白ひげ海賊団 含む
_MUGI_C = "OP01-013"          # サンジ cost2 power3000 麦わらの一味
_SANJI4 = "ST01-004"          # サンジ cost2 power4000 麦わらの一味
_BIG_C = "PRB02-013"          # ゲッコー・モリア cost6 power7000


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 MAIN / turn_number=3。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果 (dict) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


def _total_attached(player) -> int:
    """リーダー + 全キャラ に付与されているドンの総数。"""
    return player.leader.attached_dons + sum(c.attached_dons for c in player.characters)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave183_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST22-003", "ST22-005", "ST22-006", "ST22-007", "ST22-011",
           "ST22-012", "ST22-016", "ST22-017", "ST23-001", "ST23-002"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST22-003 エドワード・ニューゲート: 【登場時】デッキ上1枚公開し
#            『白ひげ海賊団』を含む特徴なら カード2枚を引く
# --------------------------------------------------------------------------- #
def test_st22_003_on_play_reveal_whitebeard_draws_two():
    """デッキ上が白ひげ海賊団カード → 2 枚引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    # デッキ上を白ひげ (イゾウ) にする
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    newgate = InPlay.of(repo.get("ST22-003"), sickness=False)

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp, newgate)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 2, \
        f"白ひげ公開で 2 枚引くはず: {len(me.hand)}"


def test_st22_003_on_play_no_draw_when_not_whitebeard():
    """デッキ上が白ひげ海賊団でない → 引かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] + [repo.get(_FILLER)] * 10  # ナミ = 白ひげ でない
    newgate = InPlay.of(repo.get("ST22-003"), sickness=False)

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-003", "on_play")["do"]:
        execute_effect(prim, st, me, opp, newgate)
    _drain(st, [0])
    assert len(me.hand) == hand_before, \
        f"白ひげでないのに引いてはいけない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  ST22-005 光月おでん: 相手効果で離脱する場合 代わりに手札2枚捨て /
#            【起動メイン】【ターン1回】ドン3レスト + 自キャラ1枚手札戻し：アクティブに
# --------------------------------------------------------------------------- #
def test_st22_005_replace_leave_discard_two_ai():
    """相手効果でKO(離脱)する場合、 手札2枚捨てで代替 → 場に残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=False)
    me.characters = [oden]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER), repo.get(_MUGI_C)]  # 3 枚

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, oden, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "手札2枚捨てられるのに離脱が置換されていない"
    assert oden in me.characters, "置換成立時 おでんは場に残るべき"
    assert len(me.hand) == hand_before - 2, "置換コストで手札が2枚捨てられるべき"


def test_st22_005_replace_leave_not_triggered_by_own_effect():
    """自分の効果で離脱する場合は【相手の効果】条件に一致せず 置換しない (False)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=False)
    me.characters = [oden]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER), repo.get(_MUGI_C)]

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, oden, overlay, by_opp_effect=False, leave_kind="ko",
    )
    assert replaced is False, "自分の効果 (by_opp_effect=False) では 置換してはいけない"
    assert len(me.hand) == hand_before, "置換不成立時 手札は減らないはず"


def test_st22_005_replace_leave_human_confirm():
    """人間 actor: replace_leave は 任意 → replace_ko_optional modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, human_idx=0, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=False)
    me.characters = [oden]
    me.hand = [repo.get(_FILLER), repo.get(_FILLER)]  # 2 枚

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, oden, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "人間 optional でも modal を立てて halt するべき (True)"
    assert st.pending_choice is not None, "replace_leave の 任意確認 modal が立たない"
    assert st.pending_choice.get("kind") == "replace_ko_optional", \
        f"kind が replace_ko_optional でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= 置換する)
    _drain(st, [1], guard=6)
    assert oden in me.characters, "人間承諾後 おでんは場に残るべき"
    assert len(me.hand) == hand_before - 2, "承諾後 手札が2枚捨てられるべき"


def test_st22_005_activate_main_untap_self_ai():
    """起動メイン: ドン3レスト + 自キャラ1枚を手札に戻す → おでんをアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=True)
    oden.rested = True  # アクティブにする対象 (= レストから起こす)
    other = InPlay.of(repo.get(_MUGI_C), sickness=False)  # 手札に戻される別キャラ
    me.characters = [oden, other]
    me.don_active = 3

    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST22-005"]
    assert len(opts) == 1, f"ST22-005 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert oden.rested is False, "おでんがアクティブになっていない"
    assert other not in me.characters, "別キャラが手札に戻されていない"
    assert len(me.hand) == hand_before + 1, "戻したキャラが手札に加わっていない"
    assert me.don_rested >= 3, "ドン3枚がレストされていない"


def test_st22_005_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    oden = InPlay.of(repo.get("ST22-005"), sickness=False)
    oden.rested = True
    other = InPlay.of(repo.get(_MUGI_C), sickness=False)
    me.characters = [oden, other]
    me.don_active = 6

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST22-005"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])
    _drain(st, [0])
    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST22-005"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST22-006 ジョズ: 【登場時】デッキ上1枚公開し『白ひげ海賊団』なら
#            2 枚引き 手札1枚捨てる
# --------------------------------------------------------------------------- #
def test_st22_006_on_play_reveal_whitebeard_draw2_discard1():
    """白ひげ公開 → 2 枚引き 1 枚捨て = 手札 差引 +1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    me.hand = [repo.get(_FILLER), repo.get(_MUGI_C)]  # 捨てる余地
    jozu = InPlay.of(repo.get("ST22-006"), sickness=False)

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-006", "on_play")["do"]:
        execute_effect(prim, st, me, opp, jozu)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"draw2 - discard1 で 手札は +1 のはず: {len(me.hand)}"


def test_st22_006_on_play_no_effect_when_not_whitebeard():
    """デッキ上が白ひげでない → 引かず 捨てず (手札不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10  # ナミ = 白ひげ でない
    me.hand = [repo.get(_MUGI_C)]
    jozu = InPlay.of(repo.get("ST22-006"), sickness=False)

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-006", "on_play")["do"]:
        execute_effect(prim, st, me, opp, jozu)
    _drain(st, [0])
    assert len(me.hand) == hand_before, \
        f"白ひげでないのに 手札が変化してはいけない: {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  ST22-007 スクアード: 【起動メイン】【ターン1回】デッキ上1枚公開し
#            『白ひげ海賊団』なら 自リーダーかキャラ1枚にレストドン1枚付与
# --------------------------------------------------------------------------- #
def test_st22_007_activate_main_reveal_attach_rested_don_ai():
    """白ひげ公開 → 自リーダーかキャラに レストドン1枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    squard = InPlay.of(repo.get("ST22-007"), sickness=False)
    me.characters = [squard]
    me.don_rested = 2

    attached_before = _total_attached(me)
    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST22-007"]
    assert len(opts) == 1, f"ST22-007 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st, [0])

    assert _total_attached(me) == attached_before + 1, \
        f"レストドン1枚が付与されていない: {_total_attached(me)}"
    assert me.don_rested == rested_before - 1, "レストドンが1枚消費されるべき"


def test_st22_007_activate_main_human_target_pick():
    """人間 + 白ひげ公開 → 付与先 (リーダー+キャラ) target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, human_idx=0, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    squard = InPlay.of(repo.get("ST22-007"), sickness=False)
    me.characters = [squard]
    me.don_rested = 2

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST22-007"]
    assert len(opts) == 1
    fire_activate_main(st, me, opp, *opts[0])
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+スクアード) が 2 件でない: {len(cands)}"
    sq_idx = next(i for i, c in enumerate(cands) if c["iid"] == squard.instance_id)
    resolve_pending_choice(st, [sq_idx])
    _drain(st, [0])
    assert squard.attached_dons == 1, \
        f"人間が選んだキャラにレストドン1枚が付与されていない: {squard.attached_dons}"


# --------------------------------------------------------------------------- #
#  ST22-011 ホワイティベイ: 【自ターン中】【登場時】手札の白ひげ2枚公開：
#            自白ひげリーダー1枚 +2000 (このターン中)
# --------------------------------------------------------------------------- #
def test_st22_011_on_play_reveal_two_whitebeard_pumps_leader_ai():
    """手札に白ひげ2枚 → 自 (白ひげ) リーダー +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)  # 白ひげ リーダー
    me, opp = st.players[0], st.players[1]
    whitey = InPlay.of(repo.get("ST22-011"), sickness=False)
    me.hand = [repo.get(_WB_TOP), repo.get(_WB_TOP2)]  # 白ひげ 2 枚 (公開コスト)

    eff = _eff(overlay, "ST22-011", "on_play")
    # wrapper conditions (自ターン + 白ひげリーダー) が成立していること
    for cond in eff.get("conditions", []):
        assert eval_condition(cond, st, me, whitey) is True, \
            f"前提条件 {cond} が成立していない"

    leader_before = me.leader.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, whitey)
    _drain(st, [0])
    assert me.leader.power == leader_before + 2000, \
        f"白ひげリーダーへ +2000 が乗っていない: {me.leader.power}"


def test_st22_011_on_play_no_pump_without_two_whitebeard():
    """手札の白ひげが1枚だけ → 公開コスト払えず 昇力なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    whitey = InPlay.of(repo.get("ST22-011"), sickness=False)
    me.hand = [repo.get(_WB_TOP), repo.get(_FILLER)]  # 白ひげ 1 枚のみ

    leader_before = me.leader.power
    for prim in _eff(overlay, "ST22-011", "on_play")["do"]:
        execute_effect(prim, st, me, opp, whitey)
    _drain(st, [0])
    assert me.leader.power == leader_before, \
        f"白ひげ1枚では +2000 が乗ってはいけない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  ST22-012 マルコ: 【ターン1回】相手効果KO時 代わりに手札1枚捨て /
#            【アタック時】デッキ上1枚公開し『白ひげ海賊団』なら +1000 (次相手end まで)
# --------------------------------------------------------------------------- #
def test_st22_012_replace_ko_discard_one_ai():
    """相手効果KO時、 手札1枚捨てで代替 → 場に残る (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    marco = InPlay.of(repo.get("ST22-012"), sickness=False)
    me.characters = [marco]
    me.hand = [repo.get(_FILLER), repo.get(_MUGI_C)]

    hand_before = len(me.hand)
    replaced = try_replace_ko(
        st, me, opp, marco, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "手札1枚捨てられるのに KO が置換されていない"
    assert marco in me.characters, "置換成立時 マルコは場に残るべき"
    assert len(me.hand) == hand_before - 1, "置換コストで手札が1枚捨てられるべき"


def test_st22_012_on_attack_reveal_whitebeard_pump_self():
    """【アタック時】白ひげ公開 → 自身 +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    marco = InPlay.of(repo.get("ST22-012"), sickness=False)
    me.characters = [marco]

    power_before = marco.power
    for prim in _eff(overlay, "ST22-012", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, marco)
    _drain(st, [0])
    assert marco.power == power_before + 1000, \
        f"白ひげ公開で 自身 +1000 が乗っていない: {marco.power}"


def test_st22_012_on_attack_no_pump_when_not_whitebeard():
    """デッキ上が白ひげでない → 昇力なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    marco = InPlay.of(repo.get("ST22-012"), sickness=False)
    me.characters = [marco]

    power_before = marco.power
    for prim in _eff(overlay, "ST22-012", "on_attack")["do"]:
        execute_effect(prim, st, me, opp, marco)
    _drain(st, [0])
    assert marco.power == power_before, \
        f"白ひげでないのに 昇力が乗ってはいけない: {marco.power}"


# --------------------------------------------------------------------------- #
#  ST22-016 取り消せよ……!!!今の言葉……!!! (EVENT): 【カウンター】デッキ上1枚公開し
#            『白ひげ海賊団』なら 自リーダーかキャラ1枚 +4000 / トリガー 1 枚引く
# --------------------------------------------------------------------------- #
def test_st22_016_counter_reveal_whitebeard_pump_ai():
    """【カウンター】白ひげ公開 → 自リーダー (唯一の候補) +4000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10

    leader_before = me.leader.power
    for prim in _eff(overlay, "ST22-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert me.leader.power == leader_before + 4000, \
        f"白ひげ公開で 自リーダー +4000 が乗っていない: {me.leader.power}"


def test_st22_016_counter_human_target_pick():
    """人間 + 白ひげ公開 + リーダー+キャラ → +4000 の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, human_idx=0, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_WB_TOP)] + [repo.get(_FILLER)] * 10
    chara = InPlay.of(repo.get(_MUGI_C), sickness=False)
    me.characters = [chara]

    for prim in _eff(overlay, "ST22-016", "counter")["do"]:
        execute_effect(prim, st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    ch_idx = next(i for i, c in enumerate(cands) if c["iid"] == chara.instance_id)
    power_before = chara.power
    resolve_pending_choice(st, [ch_idx])
    _drain(st, [0])
    assert chara.power == power_before + 4000, \
        f"人間が選んだキャラに +4000 が乗っていない: {chara.power}"


def test_st22_016_trigger_draws_one():
    """【トリガー】カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-016", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert len(me.hand) == hand_before + 1, "トリガーで 1 枚引けていない"


# --------------------------------------------------------------------------- #
#  ST22-017 火拳 (EVENT): 【メイン】手札の白ひげ2枚公開：1枚引き コスト5以下キャラ1枚
#            デッキ下 / トリガー コスト3以下キャラ1枚手札戻し
# --------------------------------------------------------------------------- #
def test_st22_017_main_reveal_draw_then_bottom_ai():
    """手札白ひげ2枚 → 1枚引き 相手コスト5以下キャラ1枚をデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WB_TOP), repo.get(_WB_TOP2)]  # 白ひげ 2 枚 (公開コスト)
    victim = InPlay.of(repo.get(_SANJI4), sickness=False)  # cost2 (≤5) = 対象
    opp.characters = [victim]
    opp_deck_before = len(opp.deck)
    hand_before = len(me.hand)

    for prim in _eff(overlay, "ST22-017", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト5以下キャラがデッキ下に戻されていない"
    assert len(opp.deck) == opp_deck_before + 1, "戻したキャラがデッキ下に加わっていない"
    assert len(me.hand) == hand_before + 1, \
        f"1枚引き (+1) が反映されていない: 白ひげ公開は消費なし: {len(me.hand)}"


def test_st22_017_main_no_effect_without_two_whitebeard():
    """手札の白ひげが1枚だけ → 公開コスト払えず 何も起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WB_TOP), repo.get(_FILLER)]  # 白ひげ 1 枚のみ
    victim = InPlay.of(repo.get(_SANJI4), sickness=False)
    opp.characters = [victim]

    hand_before = len(me.hand)
    for prim in _eff(overlay, "ST22-017", "main")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim in opp.characters, "白ひげ1枚では 相手キャラを戻せないはず"
    assert len(me.hand) == hand_before, "白ひげ1枚では 引けないはず"


def test_st22_017_trigger_returns_cost_le_3_to_hand_ai():
    """【トリガー】相手コスト3以下キャラ1枚を持ち主の手札に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_WB, overlay, opp_leader_id=_LEADER_WB)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_MUGI_C), sickness=False)  # cost2 (≤3) = 対象
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    for prim in _eff(overlay, "ST22-017", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)
    _drain(st, [0])
    assert victim not in opp.characters, "相手コスト3以下キャラが手札に戻されていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが相手の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST23-001 ウタ: 手札のこのカードは 自パワー10000以上キャラがいれば コスト-4
# --------------------------------------------------------------------------- #
def test_st23_001_in_hand_cost_minus_with_power10000_chara():
    """自場にパワー10000以上のキャラがいれば 手札のウタは コスト-4。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me = st.players[0]
    big = InPlay.of(repo.get("ST22-003"), sickness=False)  # power 10000
    me.characters = [big]
    assert big.power >= 10000, f"前提: 10000以上キャラの power = {big.power}"
    assert _compute_in_hand_cost_minus(st, me, repo.get("ST23-001")) == 4, \
        "パワー10000以上キャラありで 手札コスト -4 が計算されていない"


def test_st23_001_in_hand_no_reduction_without_power10000():
    """自場にパワー10000以上キャラがいなければ コスト軽減なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get(_SANJI4), sickness=False)]  # power 4000
    assert _compute_in_hand_cost_minus(st, me, repo.get("ST23-001")) == 0, \
        "パワー10000以上キャラが居ないのに コスト軽減が発生してはいけない"


# --------------------------------------------------------------------------- #
#  ST23-002 シャンクス: 【登場時】リーダーが《赤髪海賊団》か「ウタ」なら
#            リーダー +2000 (次相手end まで)
# --------------------------------------------------------------------------- #
def test_st23_002_on_play_pump_leader_when_akagami():
    """リーダーが赤髪海賊団 → リーダー +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_SHANKS, overlay, opp_leader_id=_LEADER_SHANKS)
    me, opp = st.players[0], st.players[1]
    shanks = InPlay.of(repo.get("ST23-002"), sickness=False)

    eff = _eff(overlay, "ST23-002", "on_play")
    assert eval_condition(eff.get("if", {}), st, me, shanks) is True, \
        "赤髪海賊団リーダーで on_play 条件が成立していない"
    leader_before = me.leader.power
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, shanks)
    _drain(st, [0])
    assert me.leader.power == leader_before + 2000, \
        f"赤髪リーダーへ +2000 が乗っていない: {me.leader.power}"


def test_st23_002_on_play_no_pump_when_other_leader():
    """リーダーが赤髪海賊団でもウタでもない → 昇力なし (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_RED, overlay)  # 麦わらの一味 リーダー
    me = st.players[0]
    shanks = InPlay.of(repo.get("ST23-002"), sickness=False)

    eff = _eff(overlay, "ST23-002", "on_play")
    assert eval_condition(eff.get("if", {}), st, me, shanks) is False, \
        "赤髪でもウタでもないのに on_play 条件が成立している"
