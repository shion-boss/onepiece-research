# -*- coding: utf-8 -*-
"""OP14 弾 効果 回帰テスト バックフィル (自動生成 wave 133):
OP14-017 / OP14-018 / OP14-021 / OP14-024 / OP14-025 / OP14-026 /
OP14-028 / OP14-029 / OP14-032 / OP14-034 の 10 枚。

目的 (= test_backfill_auto_001〜132.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001",
           turn_player=0):
    """P0 = テスト対象デッキ、 P1 = ダミー。 既定 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = turn_player
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _entries(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果 entry を全件返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の do を返す。"""
    return _entries(overlay, cid, when)[0]["do"]


# 定番 helper カード
_FILLER = "ST01-004"        # サンジ (cost2 pow4000 CHARACTER、 トリガー無し)
_NAMI = "OP01-016"          # ナミ (cost2 pow2000、 truly_original 2000 = KO対象/debuf対象)
_TONG_KAYA = "EB03-023"     # カヤ (cost2 CHARACTER、 特徴《東の海》 = OP14-025 の登場対象)
_MUGI_SANJI = "EB01-014"    # サンジ (cost4 pow5000 緑、 特徴《麦わらの一味》 = OP14-034 静的対象)
_BASE8000 = "EB04-038"      # ロシナンテ＆ロー (cost6 pow8000 = 元々パワー8000以上の判定用)
_KURO_LEADER = "OP03-021"   # クロ (LEADER 緑、 特徴《東の海/クロネコ海賊団》)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave133_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP14-017", "OP14-018", "OP14-021", "OP14-024", "OP14-025",
           "OP14-026", "OP14-028", "OP14-029", "OP14-032", "OP14-034"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP14-017 シャンブルズ (EVENT 赤 cost3):
#    【メイン】相手の元々のパワー9000以下のキャラ2枚を選ぶ。 選んだキャラそれぞれの
#    元々のパワーを、 このターン中、 入れ替える。 (swap_opp_power)
# --------------------------------------------------------------------------- #
def test_op14_017_shambles_swap_opp_power_ai():
    """【メイン】相手キャラ2枚の元々パワーを入れ替える (AI = 最弱↔最強)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    weak = InPlay.of(repo.get(_NAMI), sickness=False)     # 元々 2000
    strong = InPlay.of(repo.get(_FILLER), sickness=False)  # 元々 4000
    opp.characters = [weak, strong]

    for prim in _do(overlay, "OP14-017", "main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-017"), sickness=False))

    # 最弱 (2000) ↔ 最強 (4000) の元々パワーが入れ替わる
    assert weak.turn_base_power_override == 4000, \
        f"最弱キャラの元々パワーが 4000 に入れ替わっていない: {weak.turn_base_power_override}"
    assert strong.turn_base_power_override == 2000, \
        f"最強キャラの元々パワーが 2000 に入れ替わっていない: {strong.turn_base_power_override}"


def test_op14_017_shambles_swap_human_pick():
    """人間 + 相手キャラ2枚以上 → target_pick modal (limit 2) が立ち resolve で入れ替え。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # 2000
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # 4000
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP14-017", "main")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-017"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("limit") == 2, "入れ替えは 2 枚選択のはず"
    resolve_pending_choice(st, [0, 1])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert a.turn_base_power_override == 4000 and b.turn_base_power_override == 2000, \
        f"人間が選んだ2枚の元々パワーが入れ替わっていない: {a.turn_base_power_override}/{b.turn_base_power_override}"


def test_op14_017_shambles_needs_two_targets():
    """負例: 相手キャラが1枚以下なら swap は不発 (2枚未満)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    lone = InPlay.of(repo.get(_NAMI), sickness=False)
    opp.characters = [lone]

    for prim in _do(overlay, "OP14-017", "main"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-017"), sickness=False))

    assert lone.turn_base_power_override is None, \
        "2枚未満なのに元々パワーが入れ替わっている"


# --------------------------------------------------------------------------- #
#  OP14-018 反撃に出るぞ (EVENT 赤 cost1):
#    【カウンター】パワー8000以上のキャラがいる場合、 自分のリーダーかキャラ1枚までを、
#    このバトル中、 パワー+4000。
# --------------------------------------------------------------------------- #
def test_op14_018_counter_pump_ai():
    """【カウンター】自リーダーを このバトル中 パワー+4000 (do 本体を発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # leader OP01-001 = 5000
    me, opp = st.players[0], st.players[1]

    counter = _entries(overlay, "OP14-018", "counter")[0]
    ld_before = me.leader.power
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-018"), sickness=False))

    assert me.leader.power == ld_before + 4000, \
        f"カウンターで自リーダー +4000 が反映されていない: {me.leader.power} (before {ld_before})"


def test_op14_018_counter_condition_power8000():
    """発動条件: 元々パワー8000以上のキャラがいる場合のみ True。"""
    repo = _repo()
    overlay = _overlay()
    counter = _entries(overlay, "OP14-018", "counter")[0]
    cond = counter["if"]

    # 元々パワー 8000 のキャラを場に置くと条件成立
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.characters = [InPlay.of(repo.get(_BASE8000), sickness=False)]
    assert eval_condition(cond, st, me) is True, \
        "元々パワー8000のキャラがいるのに条件が成立していない"

    # 盤面が空なら不成立
    st2 = _state(repo, "OP01-001", overlay)
    assert eval_condition(cond, st2, st2.players[0]) is False, \
        "パワー8000以上のキャラ不在で条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP14-021 イッショウ (CHARACTER 緑 cost6):
#    【自分のターン中】このキャラがレストになった時、 自分のライフの上から1枚を手札に
#    加えてもよい。 そうした場合、 相手のレストの、 キャラかステージ1枚までは、 次の
#    相手のリフレッシュフェイズでアクティブにならない。
# --------------------------------------------------------------------------- #
def test_op14_021_issho_on_self_rested_keep_rested_ai():
    """【自分のターン中】レスト時 → 相手のレストキャラを 次リフレッシュで非アクティブ化 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)
    victim.rested = True
    victim.attached_dons = 1  # keep_opp_rested_chara_with_don_ge (don_ge=1) の対象化
    opp.characters = [victim]

    for prim in _do(overlay, "OP14-021", "on_self_rested"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-021"), sickness=False))

    assert victim.stay_rested_next_refresh is True, \
        "相手のレストキャラが次リフレッシュで非アクティブになっていない"


def test_op14_021_issho_entry_structure():
    """overlay 構造: on_self_rested + 自分のターン中 + 任意 (life_to_hand) コスト。"""
    overlay = _overlay()
    entry = _entries(overlay, "OP14-021", "on_self_rested")[0]
    assert entry.get("if", {}).get("self_turn") is True, \
        "自分のターン中 (self_turn) 条件が無い"
    assert entry.get("optional") is True, "「加えてもよい」 の optional マークが無い"
    assert entry.get("cost", {}).get("life_to_hand") == 1, \
        "ライフ上から1枚を手札に加える cost (life_to_hand=1) が無い"


# --------------------------------------------------------------------------- #
#  OP14-024 錦えもん (CHARACTER 緑 cost4):
#    【登場時】自分のドン‼3枚までを、 アクティブにする。 その後、 自分は、 このターン中、
#    キャラカードを登場できない。 【KO時】相手のカード1枚までを、 レストにする。
# --------------------------------------------------------------------------- #
def test_op14_024_kinemon_on_play_untap_don_and_block_ai():
    """【登場時】レストドン3枚をアクティブ化 + このターン中キャラ登場不可 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 5
    me.don_active = 0

    for prim in _do(overlay, "OP14-024", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-024"), sickness=True))

    assert me.don_active == 3, f"レストドン3枚がアクティブになっていない: {me.don_active}"
    assert me.don_rested == 2, f"レストドンが2枚残っていない: {me.don_rested}"
    assert getattr(me, "block_chara_play_until_turn_end", False) is True, \
        "このターン中キャラ登場不可のフラグが立っていない"


def test_op14_024_kinemon_on_ko_rest_opp_ai():
    """【KO時】相手のカード1枚をレストにする (AI = 相手キャラ優先)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # active
    opp.characters = [victim]

    for prim in _do(overlay, "OP14-024", "on_ko"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-024"), sickness=False))

    assert victim.rested is True, "KO時に相手キャラがレストになっていない"


# --------------------------------------------------------------------------- #
#  OP14-025 クロ (CHARACTER 緑 cost7):
#    【登場時】自分のリーダーが「クロ」の場合、 自分の手札からコスト6以下の特徴《東の海》を
#    持つキャラカード1枚までを、 登場させる。
# --------------------------------------------------------------------------- #
def test_op14_025_kuro_on_play_summon_ai():
    """【登場時】リーダー「クロ」 → 手札のコスト6以下《東の海》キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KURO_LEADER, overlay)  # リーダー = クロ
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_TONG_KAYA)]  # カヤ (東の海 cost2)

    entry = _entries(overlay, "OP14-025", "on_play")[0]
    assert eval_condition(entry["if"], st, me) is True, \
        "前提: リーダー「クロ」で登場時条件が成立していない"

    chars_before = len(me.characters)
    for prim in entry["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-025"), sickness=True))

    assert len(me.characters) == chars_before + 1, \
        "手札の《東の海》キャラが登場していない"
    assert any(c.card.card_id == _TONG_KAYA for c in me.characters), \
        "登場したキャラがカヤ (東の海) でない"
    assert len(me.hand) == 0, "登場に使った手札が消費されていない"


def test_op14_025_kuro_condition_off_when_leader_not_kuro():
    """負例: リーダーが「クロ」でなければ登場時条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # リーダー ≠ クロ
    entry = _entries(overlay, "OP14-025", "on_play")[0]
    assert eval_condition(entry["if"], st, st.players[0]) is False, \
        "リーダーが「クロ」でないのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP14-026 光月おでん (CHARACTER 緑 cost4):
#    【相手のターン中】このキャラがレストの場合、 このキャラのパワー+2000。 (静的)
# --------------------------------------------------------------------------- #
def test_op14_026_oden_static_pump_when_opp_turn_rested():
    """静的: 相手のターン中 + 自身レスト → パワー+2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)  # 相手 (P1) のターン
    me = st.players[0]
    oden = InPlay.of(repo.get("OP14-026"), sickness=False)
    oden.rested = True
    me.characters = [oden]

    evaluate_static_effects(st, overlay)
    assert oden.power == oden.card.power + 2000, \
        f"相手ターン+レストで +2000 が反映されていない: {oden.power} (base {oden.card.power})"


def test_op14_026_oden_static_no_pump_when_active():
    """負例: 相手のターン中でも自身がアクティブなら +2000 は乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, turn_player=1)
    me = st.players[0]
    oden = InPlay.of(repo.get("OP14-026"), sickness=False)
    oden.rested = False
    me.characters = [oden]

    evaluate_static_effects(st, overlay)
    assert oden.power == oden.card.power, \
        f"アクティブなのに +2000 が乗っている: {oden.power} (base {oden.card.power})"


# --------------------------------------------------------------------------- #
#  OP14-028 ジョニー (CHARACTER 緑 cost2):
#    【自分のターン中】このキャラがレストになった時、 相手のレストのコスト2以下のキャラ
#    1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op14_028_johnny_on_self_rested_ko_ai():
    """【自分のターン中】レスト時 → 相手レストのコスト2以下キャラをKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost2
    victim.rested = True
    opp.characters = [victim]

    for prim in _do(overlay, "OP14-028", "on_self_rested"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-028"), sickness=False))

    assert victim not in opp.characters, \
        "相手レストのコスト2以下キャラがKOされていない"


def test_op14_028_johnny_ko_human_pick():
    """人間 + 相手レストcost2以下キャラ複数 → target_pick modal が立ち resolve で 1 体 KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False); a.rested = True
    b = InPlay.of(repo.get(_NAMI), sickness=False); b.rested = True
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP14-028", "on_self_rested")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-028"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert len(opp.characters) == 1, "KO で相手キャラが1体に減っていない"


# --------------------------------------------------------------------------- #
#  OP14-029 たしぎ (CHARACTER 緑 cost5):
#    【相手のターン中】このキャラが相手の効果で場を離れる場合、 代わりに自分のカード1枚を
#    レストにできる。 【起動メイン】【ターン1回】自分のカード2枚をレストにできる：このキャラは、
#    次の相手のエンドフェイズ終了時まで、 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op14_029_tashigi_activate_main_pump_ai():
    """【起動メイン】自分のカード2枚をレスト → 自身 +2000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    tashigi = InPlay.of(repo.get("OP14-029"), sickness=False)  # power 6000
    c1 = InPlay.of(repo.get(_FILLER), sickness=False)
    c2 = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [tashigi, c1, c2]

    power_before = tashigi.power
    for prim in _do(overlay, "OP14-029", "activate_main"):
        execute_effect(prim, st, me, opp, tashigi)

    assert tashigi.power == power_before + 2000, \
        f"起動メインで自身 +2000 が反映されていない: {tashigi.power} (before {power_before})"
    rested_count = sum(1 for c in me.characters if c.rested)
    assert rested_count >= 2, \
        f"コストで自分のカード2枚がレストになっていない (rested={rested_count})"


def test_op14_029_tashigi_replace_leave_structure():
    """replace_leave (相手のターン中 相手効果離脱を 自カード1レストで代替) の overlay 構造。"""
    overlay = _overlay()
    rep = _entries(overlay, "OP14-029", "replace_leave")[0]
    cond = rep.get("if", {})
    assert cond.get("target") == "self", "replace_leave の対象が self でない"
    assert cond.get("opp_turn") is True, "replace_leave の opp_turn 条件が無い"
    assert cond.get("by_opp_effect") is True, "replace_leave の by_opp_effect 条件が無い"
    assert any("rest_self_cards" in d for d in rep.get("do", [])), \
        "代替の rest_self_cards が do に無い"


# --------------------------------------------------------------------------- #
#  OP14-032 ヒューマンドリル (CHARACTER 緑 cost3):
#    【自分のターン中】このキャラがレストになった時、 相手のコスト4以下のキャラ1枚までを、
#    レストにする。
# --------------------------------------------------------------------------- #
def test_op14_032_humandrill_on_self_rested_rest_ai():
    """【自分のターン中】レスト時 → 相手のコスト4以下キャラをレスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2, active
    opp.characters = [victim]

    for prim in _do(overlay, "OP14-032", "on_self_rested"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP14-032"), sickness=False))

    assert victim.rested is True, "相手のコスト4以下キャラがレストになっていない"


def test_op14_032_humandrill_rest_human_pick():
    """人間 + 相手コスト4以下キャラ複数 → target_pick modal が立ち resolve で 1 体レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_NAMI), sickness=False)    # cost2
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP14-032", "on_self_rested")[0], st, me, opp,
                   InPlay.of(repo.get("OP14-032"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.rested is True, "人間が選んだ相手キャラがレストになっていない"
    assert a.rested is False, "選ばなかった相手キャラはレストにならないべき"


# --------------------------------------------------------------------------- #
#  OP14-034 モンキー・Ｄ・ルフィ (CHARACTER 緑 cost3):
#    【自分のターン中】自分の元々のコスト4以上の緑の特徴《麦わらの一味》を持つキャラすべてを、
#    パワー+1000。 (静的)
#    【ターン1回】自分の特徴《麦わらの一味》を持つキャラが相手の効果でKOされる場合、
#    代わりに自分のキャラ1枚をレストにできる。 (replace_ko)
# --------------------------------------------------------------------------- #
def test_op14_034_luffy_static_pump_mugiwara_ai():
    """静的: 自分のターン中 → 緑・元々コスト4以上・《麦わらの一味》キャラ全てに +1000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 自分のターン (turn_player=0)
    me = st.players[0]
    luffy = InPlay.of(repo.get("OP14-034"), sickness=False)
    mugi = InPlay.of(repo.get(_MUGI_SANJI), sickness=False)  # 麦わら 緑 cost4 power5000
    me.characters = [luffy, mugi]

    evaluate_static_effects(st, overlay)
    assert mugi.power == mugi.card.power + 1000, \
        f"麦わら 緑 cost4以上キャラに +1000 が乗っていない: {mugi.power} (base {mugi.card.power})"


def test_op14_034_luffy_replace_ko_mugiwara():
    """replace_ko: 《麦わらの一味》キャラが相手効果でKO → 代わりに自分のキャラ1枚をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    luffy = InPlay.of(repo.get("OP14-034"), sickness=False)  # 置換元 (in play)
    mugi = InPlay.of(repo.get(_MUGI_SANJI), sickness=False)  # KO 被害 (麦わら)
    sac = InPlay.of(repo.get(_FILLER), sickness=False)       # レスト供出候補
    me.characters = [luffy, mugi, sac]

    replaced = try_replace_ko(st, me, opp, mugi, overlay, by_opp_effect=True,
                              leave_kind="ko")
    assert replaced is True, "麦わらキャラの相手効果KOが置換されていない"
    assert mugi in me.characters, "置換成立時 KO被害キャラは場に残るべき"
    assert any(c.rested for c in me.characters), \
        "置換コストとして自分のキャラ1枚がレストになっていない"
