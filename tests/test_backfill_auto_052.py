# -*- coding: utf-8 -*-
"""OP04 弾 効果 回帰テスト バックフィル (自動生成 wave 052):
OP04-095 / OP04-096 / OP04-097 / OP04-098 / OP04-099 / OP04-100 /
OP04-101 / OP04-102 / OP04-103 / OP04-104 の 10 枚 (黒 ドレスローザ / 黄 ワノ国 系)。

目的 (= test_backfill_auto_001〜051.py と同一方針):
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
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# よく使うテスト用カード (テキストの前提固定)
_LEADER_REBECCA = "OP04-039"   # レベッカ (青/黒、 特徴 ドレスローザ)
_LEADER_ODEN = "OP01-031"      # 光月おでん (赤、 特徴 ワノ国)
_DRESSROSA_CHAR = "PRB02-014"  # サボ ドレスローザ/革命軍 cost6
_WANO_CHAR = "PRB02-008"       # マルコ ワノ国/元白ひげ海賊団 cost4
_ANIMAL_C3 = "EB02-003"        # トニートニー・チョッパー 動物 cost3
_ANIMAL_C3B = "EB01-006"       # トニートニー・チョッパー 動物 cost3 (別 iid 用)
_WANO_C2 = "PRB02-016"         # お玉 ワノ国 cost2 (OP04-101 ko 対象)
_WANO_C2B = "EB03-012"         # お玉 ワノ国 cost2 (別カード)
_OPP_COST4 = "PRB02-001"       # コビー cost4


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get("ST01-004")] * 30
    p1.deck = [repo.get("ST01-004")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _do(overlay, cid, when, needle=None):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"]
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"]


def _am(st, me, overlay, cid):
    """指定 card_id の legal な起動メイン (src, eff) を返す (無ければ空 list)。"""
    return [(src, eff) for (src, eff) in list_activate_main_effects(st, me, overlay)
            if src.card.card_id == cid]


def _drain(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave52_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-095", "OP04-096", "OP04-097", "OP04-098", "OP04-099",
           "OP04-100", "OP04-101", "OP04-102", "OP04-103", "OP04-104"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-095 バ～～～～リアッ!! (EVENT 黒 cost1):
#    【カウンター】自リーダー/キャラ1枚 +2000。 その後 トラッシュ15枚以上なら さらに +2000。
#    【トリガー】カード2枚を引き、 自分の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op04_095_counter_pump_no_trash_ai():
    """【カウンター】トラッシュ15枚未満: 自リーダーに +2000 のみ (AI 自動、 リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _do(overlay, "OP04-095", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op04_095_counter_pump_trash15_ai():
    """【カウンター】トラッシュ15枚以上: +2000 のあと 条件成立で さらに +2000 = 合計 +4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST01-004")] * 15

    power_before = me.leader.power
    for prim in _do(overlay, "OP04-095", "counter"):
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"トラッシュ15枚以上で 合計 +4000 になっていない: {me.leader.power} (before {power_before})"


def test_op04_095_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("ST01-004"), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP04-095", "counter")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 2000, \
        "人間が選んだキャラに +2000 が反映されていない"


def test_op04_095_trigger_draw_discard_ai():
    """【トリガー】カード2枚を引き、 手札1枚を捨てる → 手札 正味 +1 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 2
    me.deck = [repo.get("ST01-004")] * 10

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-095", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, \
        f"draw 2 - discard 1 = 正味 +1 になっていない: {hand_before} -> {len(me.hand)}"


# --------------------------------------------------------------------------- #
#  OP04-096 コリーダコロシアム (STAGE 黒 cost1):
#    自リーダーが特徴《ドレスローザ》を持つ場合、 自分の《ドレスローザ》キャラは
#    登場したターンにキャラへアタックできる (= 速攻 付与、 常在効果)。
# --------------------------------------------------------------------------- #
def test_op04_096_static_grants_rush_to_dressrosa():
    """常在: ドレスローザ leader 下で 自《ドレスローザ》キャラは 速攻 を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_REBECCA, overlay)  # レベッカ ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    chara = InPlay.of(repo.get(_DRESSROSA_CHAR), sickness=True)  # サボ ドレスローザ
    me.characters = [chara]
    me.stages = [InPlay.of(repo.get("OP04-096"), sickness=False)]

    evaluate_static_effects(st, overlay)
    granted = chara.granted_keywords | chara.static_granted_keywords
    assert "速攻" in granted, \
        f"ドレスローザ leader 下で 速攻 が付与されていない: {granted}"


def test_op04_096_static_no_grant_off_leader():
    """自リーダーが《ドレスローザ》でなければ 条件不成立 → 速攻 は付与されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # 非 ドレスローザ leader
    me, opp = st.players[0], st.players[1]
    chara = InPlay.of(repo.get(_DRESSROSA_CHAR), sickness=True)
    me.characters = [chara]
    me.stages = [InPlay.of(repo.get("OP04-096"), sickness=False)]

    evaluate_static_effects(st, overlay)
    granted = chara.granted_keywords | chara.static_granted_keywords
    assert "速攻" not in granted, \
        f"非 ドレスローザ leader で 速攻 が付いてはいけない: {granted}"


# --------------------------------------------------------------------------- #
#  OP04-097 お玉 (CHARACTER 黄 cost1):
#    【登場時】相手のコスト3以下の《動物》か《SMILE》キャラ1枚までを、 相手ライフ上に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op04_097_otama_on_play_chara_to_opp_life_ai():
    """登場時: 相手の《動物》コスト3以下キャラを 相手ライフ上へ移動 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)  # 動物 cost3
    opp.characters = [victim]
    life_before = len(opp.life)

    for prim in _do(overlay, "OP04-097", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-097"), sickness=True))

    assert victim not in opp.characters, "対象キャラが場から除かれていない"
    assert len(opp.life) == life_before + 1, "相手ライフが1枚増えていない"
    assert opp.life[0].card_id == _ANIMAL_C3, \
        "移動したキャラが相手ライフ上に表向きで加わっていない"


def test_op04_097_otama_on_play_human_pick():
    """人間 + 相手《動物》キャラ複数 → chara_to_opp_life の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_ANIMAL_C3), sickness=False)
    b = InPlay.of(repo.get(_ANIMAL_C3B), sickness=False)
    opp.characters = [a, b]

    execute_effect(_do(overlay, "OP04-097", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-097"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "chara_to_opp_life", \
        "primitive_kind が chara_to_opp_life でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだキャラが相手ライフへ移動していない"


# --------------------------------------------------------------------------- #
#  OP04-098 おトコ (CHARACTER 黄 cost2):
#    【登場時】手札から《ワノ国》2枚を捨てられる：自ライフ1枚以下なら デッキ上1枚をライフ上へ。
# --------------------------------------------------------------------------- #
def test_op04_098_otoko_on_play_opt_cost_put_top_to_life_ai():
    """登場時: 手札の《ワノ国》2枚を捨て (任意コスト) → 自ライフ1以下で デッキ上1枚をライフへ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WANO_CHAR), repo.get("EB01-016")]  # 《ワノ国》2枚
    me.life = [repo.get("ST01-004")]  # ライフ1 (= 条件成立)
    me.deck = [repo.get("ST01-004")] * 10

    life_before = len(me.life)
    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-098", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-098"), sickness=True))

    assert len(me.hand) == hand_before - 2, "任意コストで《ワノ国》2枚が捨てられていない"
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフ上に加わっていない"


def test_op04_098_otoko_on_play_human_optional_confirm():
    """人間: 任意コスト確認 modal が立ち、 承諾すると コスト支払い → ライフ+1 に進む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_WANO_CHAR), repo.get("EB01-016")]
    me.life = [repo.get("ST01-004")]
    me.deck = [repo.get("ST01-004")] * 10

    life_before = len(me.life)
    execute_effect(_do(overlay, "OP04-098", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-098"), sickness=True))

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    assert len(me.life) == life_before + 1, "承諾後 デッキ上1枚がライフに加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-099 おリン (CHARACTER 黄 cost7):
#    【トリガー】自ライフ1枚以下なら このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_099_orin_trigger_play_self_ai():
    """トリガー (自ライフ1以下): このカードを場に登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")]  # ライフ1
    me.trash = [repo.get("OP04-099")]  # トリガー元は トラッシュに置かれている
    st.current_source_card_id = "OP04-099"

    for prim in _do(overlay, "OP04-099", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-099" for c in me.characters), \
        "自ライフ1以下で おリン が登場していない"


# --------------------------------------------------------------------------- #
#  OP04-100 カポネ・ベッジ (CHARACTER 黄 cost3):
#    【トリガー】相手のリーダーかキャラ1枚までは、 このターン中、 アタックできない。
# --------------------------------------------------------------------------- #
def test_op04_100_bege_trigger_set_cannot_attack_ai():
    """トリガー: 相手キャラ1枚を このターン中 アタック不可にする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_COST4), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP04-100", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert victim.cannot_attack_until_turn_end is True, \
        "相手キャラに アタック不可 が付与されていない"


def test_op04_100_bege_trigger_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → set_cannot_attack の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_COST4), sickness=False)
    opp.characters = [victim]

    execute_effect(_do(overlay, "OP04-100", "trigger")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "set_cannot_attack", \
        "primitive_kind が set_cannot_attack でない"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    v_idx = next(i for i, c in enumerate(cands) if c["iid"] == victim.instance_id)
    resolve_pending_choice(st, [v_idx])
    _drain(st)
    assert victim.cannot_attack_until_turn_end is True, \
        "人間が選んだ相手キャラに アタック不可 が付与されていない"


# --------------------------------------------------------------------------- #
#  OP04-101 カルメル (CHARACTER 黄 cost2):
#    【自分のターン中】【登場時】カード1枚を引く。
#    【トリガー】このカードを登場させる。 その後 相手のコスト2以下1枚までを KO。
# --------------------------------------------------------------------------- #
def test_op04_101_carmel_on_play_draw_ai():
    """登場時 (自ターン中): カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # turn_player=0 = 自ターン
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 10

    for prim in _do(overlay, "OP04-101", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-101"), sickness=True))

    assert len(me.hand) == 1, "登場時の 1 ドローが起きていない"


def test_op04_101_carmel_trigger_play_self_and_ko_ai():
    """トリガー: このカードを登場 → 相手コスト2以下1枚を KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-101")]
    st.current_source_card_id = "OP04-101"
    victim = InPlay.of(repo.get(_WANO_C2), sickness=False)  # cost2
    opp.characters = [victim]

    for prim in _do(overlay, "OP04-101", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-101" for c in me.characters), \
        "トリガーで カルメル が登場していない"
    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"


def test_op04_101_carmel_trigger_ko_human_pick():
    """人間 + 相手コスト2以下 複数 → 登場後 ko の target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-101")]
    st.current_source_card_id = "OP04-101"
    a = InPlay.of(repo.get(_WANO_C2), sickness=False)
    b = InPlay.of(repo.get(_WANO_C2B), sickness=False)
    opp.characters = [a, b]

    for prim in _do(overlay, "OP04-101", "trigger"):
        execute_effect(prim, st, me, opp, None)
        if st.pending_choice is not None:
            break

    assert st.pending_choice is not None, "人間 + 複数候補で ko modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "ko", "primitive_kind が ko でない"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st)
    assert a not in opp.characters, "人間が選んだ相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP04-102 錦えもん (CHARACTER 黄 cost6):
#    【起動メイン】【ターン1回】①(ドン!!1レスト)， 自ライフ上下1枚を手札に加えられる：
#      このキャラをアクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_102_kinemon_activate_main_untap_ai():
    """起動メイン: ドン1レスト + ライフ1枚を手札 (任意コスト) → 自身をアクティブに (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kinemon = InPlay.of(repo.get("OP04-102"), sickness=False)
    kinemon.rested = True  # アタック後の想定
    me.characters = [kinemon]
    me.don_active = 2
    me.life = [repo.get("ST01-004")] * 3
    me.hand = []

    hand_before = len(me.hand)
    opts = _am(st, me, overlay, "OP04-102")
    assert len(opts) == 1, f"OP04-102 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert kinemon.rested is False, "起動メインで自身がアクティブになっていない"
    assert len(me.hand) == hand_before + 1, "コストの ライフ→手札 が反映されていない"


def test_op04_102_kinemon_activate_main_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kinemon = InPlay.of(repo.get("OP04-102"), sickness=False)
    kinemon.rested = True
    me.characters = [kinemon]
    me.don_active = 4
    me.life = [repo.get("ST01-004")] * 3
    me.hand = []

    opts1 = _am(st, me, overlay, "OP04-102")
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = _am(st, me, overlay, "OP04-102")
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP04-103 光月日和 (CHARACTER 黄 cost2):
#    【登場時】自分の《ワノ国》リーダーかキャラ1枚までを、 このターン中 パワー+1000。
#    【トリガー】このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_103_hiyori_on_play_pump_wano_ai():
    """登場時: 自《ワノ国》リーダー/キャラ1枚を このターン中 +1000 (AI 自動、 ワノ国 leader)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODEN, overlay)  # 光月おでん ワノ国 leader
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    for prim in _do(overlay, "OP04-103", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-103"), sickness=True))

    assert me.leader.power == power_before + 1000, \
        f"《ワノ国》リーダーの +1000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op04_103_hiyori_on_play_human_pick():
    """人間 + 自《ワノ国》リーダー/キャラ 複数 → power_pump の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_ODEN, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get(_WANO_CHAR), sickness=False)  # ワノ国 キャラ
    me.characters = [friend]

    execute_effect(_do(overlay, "OP04-103", "on_play")[0], st, me, opp,
                   InPlay.of(repo.get("OP04-103"), sickness=True))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    assert st.pending_choice.get("primitive_kind") == "power_pump", \
        "primitive_kind が power_pump でない"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"
    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == friend_before + 1000, \
        "人間が選んだ《ワノ国》キャラに +1000 が反映されていない"


def test_op04_103_hiyori_trigger_play_self_ai():
    """トリガー: このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP04-103")]
    st.current_source_card_id = "OP04-103"

    for prim in _do(overlay, "OP04-103", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-103" for c in me.characters), \
        "トリガーで 光月日和 が登場していない"


# --------------------------------------------------------------------------- #
#  OP04-104 サンジ (CHARACTER 黄 cost4):
#    【ブロッカー】(常在) / 【トリガー】手札1枚を捨てられる：このカードを登場させる。
# --------------------------------------------------------------------------- #
def test_op04_104_sanji_trigger_opt_cost_play_self_ai():
    """トリガー: 手札1枚を捨て (任意コスト) → このカードを登場させる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    me.trash = [repo.get("OP04-104")]
    st.current_source_card_id = "OP04-104"

    hand_before = len(me.hand)
    for prim in _do(overlay, "OP04-104", "trigger"):
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP04-104" for c in me.characters), \
        "トリガーで サンジ が登場していない"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられていない"


def test_op04_104_sanji_trigger_human_optional_confirm():
    """人間: 任意コスト確認 modal が立ち、 承諾すると 手札1枚を捨てて 登場する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")]
    me.trash = [repo.get("OP04-104")]
    st.current_source_card_id = "OP04-104"

    execute_effect(_do(overlay, "OP04-104", "trigger")[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間で任意コスト確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, [0])
    assert any(c.card.card_id == "OP04-104" for c in me.characters), \
        "承諾後 サンジ が登場していない"
