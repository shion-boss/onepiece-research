# -*- coding: utf-8 -*-
"""EB04 弾 効果 回帰テスト バックフィル (自動生成 wave 018):
EB04-039 / EB04-040 / EB04-041 / EB04-042 / EB04-043 / EB04-046 /
EB04-047 / EB04-048 / EB04-049 / EB04-050 の 10 枚。

目的 (= test_backfill_auto_001〜017.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 任意コスト を 持つカードは 人間 actor で pending_choice が
      正しい kind + 候補で立ち、 resolve_pending_choice で解決できる (= 人間が選べる)
  (3) 同じ効果を AI 文脈 (human_player_idx=None) で回しても crash せず自動解決する
      (= AI が選べる)
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    eval_condition,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    try_replace_ko,
)

ROOT = Path(__file__).resolve().parent.parent


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
    """指定 card_id の overlay から when 一致の効果の (do, effect) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    if needle is not None:
        for e in matches:
            if any(needle in prim for prim in e["do"]):
                return e["do"], e
        raise AssertionError(f"{cid} when={when} に {needle} を含む効果がない")
    return matches[0]["do"], matches[0]


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
def test_all_wave18_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB04-039", "EB04-040", "EB04-041", "EB04-042", "EB04-043",
           "EB04-046", "EB04-047", "EB04-048", "EB04-049", "EB04-050"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB04-039 ユースタス・キッド (CHARACTER 紫 cost7 power8000 キッド海賊団):
#    【登場時】ドン‼デッキからドン‼1枚までを、アクティブで追加する /
#    【起動メイン】このキャラをトラッシュに置く：手札からコスト5以下の
#                 特徴《キッド海賊団》キャラ1枚までを、登場させる
# --------------------------------------------------------------------------- #
def test_eb04_039_kid_on_play_add_active_don_ai():
    """登場時: ドンデッキからアクティブドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    active_before = me.don_active
    deck_don_before = me.don_remaining_in_deck

    do, _ = _do(overlay, "EB04-039", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-039"), sickness=True))

    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚減っていない"


def test_eb04_039_kid_activate_main_trash_and_summon_ai():
    """起動メイン: 自身をトラッシュ + コスト5以下キッド海賊団を手札から登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kid = InPlay.of(repo.get("EB04-039"), sickness=False)
    me.characters = [kid]
    me.hand = [repo.get("OP05-064")]  # キラー cost1 キッド海賊団
    trash_before = len(me.trash)

    opts = _am(st, me, overlay, "EB04-039")
    assert len(opts) == 1, f"EB04-039 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert kid not in me.characters, "起動コストで自身がトラッシュに置かれていない"
    assert any(c.card_id == "EB04-039" for c in me.trash), \
        "自身がトラッシュに送られていない"
    assert any(c.card.card_id == "OP05-064" for c in me.characters), \
        "手札のキッド海賊団キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB04-040 火龍大炬 (EVENT 紫 cost1):
#    【メイン】ドン‼6レスト：「カイドウ」1枚+3000。その後 相手キャラ1枚レスト /
#    【カウンター】ドン‼-1：自リーダー このバトル中 +4000
# --------------------------------------------------------------------------- #
def test_eb04_040_karyu_main_pump_and_rest_ai():
    """メイン: 自「カイドウ」+3000 + 相手キャラ1枚レスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kaidou = InPlay.of(repo.get("EB04-030"), sickness=False)  # 名前「カイドウ」
    assert kaidou.card.name == "カイドウ", "テスト前提: EB04-030 は カイドウ"
    me.characters = [kaidou]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ
    opp.characters = [victim]
    power_before = kaidou.power

    do, _ = _do(overlay, "EB04-040", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert kaidou.power == power_before + 3000, \
        f"カイドウに +3000 が反映されていない: {kaidou.power}"
    assert victim.rested is True, "相手キャラがレストされていない"


def test_eb04_040_karyu_main_rest_human_pick():
    """人間 + 相手キャラ複数 → レスト対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ power5000
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-040", "main")
    # do[1] = 相手キャラ1枚レスト (one_opponent_character_any)
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で レスト modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b.rested is True, "人間が選んだ相手キャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


def test_eb04_040_karyu_counter_pump_leader_ai():
    """カウンター: 自リーダーを このバトル中 +4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power

    do, _ = _do(overlay, "EB04-040", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  EB04-041 ステルス・ブラック (EVENT 紫 cost3):
#    【メイン】サンジリーダー + 場ドン4+ → 手札/トラッシュから パワー6000以下
#             「サンジ」1枚まで登場 /
#    【トリガー】2ドロー + 手札1捨て
# --------------------------------------------------------------------------- #
def test_eb04_041_stealth_black_main_summon_sanji_ai():
    """メイン: トラッシュから パワー6000以下「サンジ」1枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-026", overlay)  # サンジ leader
    me, opp = st.players[0], st.players[1]
    me.don_active = 4  # 場ドン4+ 条件
    me.trash = [repo.get("OP01-013")]  # サンジ CHARACTER power3000
    chars_before = len(me.characters)

    assert eval_condition({"leader_name": "サンジ"}, st, me) is True, \
        "テスト前提: リーダー名が サンジ でない"
    assert eval_condition({"self_don_ge": 4}, st, me) is True, \
        "テスト前提: 自場ドンが4未満"
    do, _ = _do(overlay, "EB04-041", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card.card_id == "OP01-013" for c in me.characters), \
        "トラッシュのサンジが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


def test_eb04_041_stealth_black_trigger_draw_discard_ai():
    """トリガー: 2ドロー + 手札1捨て (AI)。 手札 net +1、 デッキ -2、 トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-026", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-041", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, f"手札 net (+2-1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"
    assert len(me.trash) == trash_before + 1, "手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  EB04-042 アルファ (CHARACTER 黒 cost1 power2000):
#    【登場時】デッキ上3枚トラッシュ：相手のキャラ1枚 このターン中 コスト-1
# --------------------------------------------------------------------------- #
def test_eb04_042_alpha_on_play_cost_minus_ai():
    """登場時: デッキ上3枚をトラッシュ + 相手キャラ1枚 コスト-1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [victim]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    cost_before = victim.base_cost

    do, _ = _do(overlay, "EB04-042", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-042"), sickness=True))

    assert len(me.deck) == deck_before - 3, "デッキ上3枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 3, "トラッシュが3枚増えていない"
    assert victim.base_cost == cost_before - 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.base_cost}"


# --------------------------------------------------------------------------- #
#  EB04-043 カク (CHARACTER 黒 cost3 power4000):
#    【ターン1回】自元々コスト5以下黒キャラが相手効果でKOされる場合、代わりに
#                トラッシュ3枚をデッキ下に置ける (replace_ko) /
#    【登場時】デッキ上2枚をトラッシュ
# --------------------------------------------------------------------------- #
def test_eb04_043_kaku_on_play_mill_ai():
    """登場時: 自分のデッキ上2枚をトラッシュ (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-043"), sickness=True))

    assert len(me.deck) == deck_before - 2, "デッキ上2枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 2, "トラッシュが2枚増えていない"


def test_eb04_043_kaku_replace_ko_trash_to_deck_ai():
    """replace_ko: 黒コスト5以下キャラが相手効果KOされる代わりに トラッシュ3枚をデッキ下 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    kaku = InPlay.of(repo.get("EB04-043"), sickness=False)
    victim = InPlay.of(repo.get("EB04-042"), sickness=False)  # アルファ 黒 cost1
    me.characters = [kaku, victim]
    me.trash = [repo.get("ST01-004")] * 3  # デッキ下へ回す 3 枚
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    replaced = try_replace_ko(
        st, me, opp, victim, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "黒コスト5以下キャラの KO が置換されていない"
    assert victim in me.characters, "置換成立時 対象キャラは場に残るべき"
    assert len(me.trash) == trash_before - 3, "トラッシュ3枚がデッキに戻っていない"
    assert len(me.deck) == deck_before + 3, "デッキ下に3枚戻っていない"


# --------------------------------------------------------------------------- #
#  EB04-046 ドール (CHARACTER 黒 cost2 power1000 ブロッカー):
#    【相手のターン中】自分の特徴《海軍》を持つキャラすべてを、コスト+2
# --------------------------------------------------------------------------- #
def _opp_turn_state(repo, overlay):
    """P0 のターンでなく P1 (opp) のターン中の state (= EB04-046 静的条件用)。"""
    st = _state(repo, "OP05-041", overlay)  # サカズキ (海軍) leader
    st.turn_player_idx = 1  # 相手 (P1) のターン中
    return st


def test_eb04_046_doll_static_cost_up_during_opp_turn_ai():
    """相手ターン中: 自分の海軍キャラすべてが コスト+2 (静的効果、 AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _opp_turn_state(repo, overlay)
    me = st.players[0]
    doll = InPlay.of(repo.get("EB04-046"), sickness=False)
    navy = InPlay.of(repo.get("OP02-098"), sickness=False)  # コビー 海軍 cost3
    me.characters = [doll, navy]
    assert eval_condition({"opp_turn": True}, st, me) is True, \
        "テスト前提: 相手ターン中でない"

    evaluate_static_effects(st, overlay)

    assert navy.base_cost == navy.card.cost + 2, \
        f"相手ターン中に海軍キャラの コスト+2 が効いていない: {navy.base_cost}"


def test_eb04_046_doll_static_no_effect_on_own_turn():
    """自分のターン中は コスト+2 が効かない (= 【相手のターン中】条件)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)  # 自分 (P0) のターン
    me = st.players[0]
    doll = InPlay.of(repo.get("EB04-046"), sickness=False)
    navy = InPlay.of(repo.get("OP02-098"), sickness=False)  # コビー 海軍 cost3
    me.characters = [doll, navy]

    evaluate_static_effects(st, overlay)

    assert navy.base_cost == navy.card.cost, \
        f"自分ターン中に海軍キャラの コストが変動してはいけない: {navy.base_cost}"


# --------------------------------------------------------------------------- #
#  EB04-047 ヘルメッポ (CHARACTER 黒 cost3 power3000 SWORD):
#    【起動メイン】このキャラをトラッシュ：手札/トラッシュから「ヘルメッポ」以外の
#                 コスト3以下の特徴《SWORD》キャラ1枚まで登場
# --------------------------------------------------------------------------- #
def test_eb04_047_helmeppo_activate_main_summon_sword_ai():
    """起動メイン: 自身をトラッシュ + トラッシュから SWORD キャラを登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    helmeppo = InPlay.of(repo.get("EB04-047"), sickness=False)
    me.characters = [helmeppo]
    me.trash = [repo.get("OP11-004")]  # 孔雀 SWORD cost1

    opts = _am(st, me, overlay, "EB04-047")
    assert len(opts) == 1, f"EB04-047 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert helmeppo not in me.characters, "起動コストで自身がトラッシュされていない"
    assert any(c.card.card_id == "OP11-004" for c in me.characters), \
        "トラッシュの SWORD キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB04-048 ロブ・ルッチ (CHARACTER 黒 cost4 power6000):
#    【登場時】自分のキャラ1枚をトラッシュ：カード1枚を引く
# --------------------------------------------------------------------------- #
def test_eb04_048_lucci_on_play_ko_self_draw_ai():
    """登場時: 自キャラ1枚をトラッシュ + 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    lucci = InPlay.of(repo.get("EB04-048"), sickness=False)  # power6000
    fodder = InPlay.of(repo.get("EB04-042"), sickness=False)  # アルファ power2000
    me.characters = [lucci, fodder]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB04-048", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, lucci)

    # AI は power 低い fodder を犠牲に KO
    assert fodder not in me.characters, "自キャラ (power低) がトラッシュされていない"
    assert len(me.hand) == hand_before + 1, "1枚引かれていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれていない"


# --------------------------------------------------------------------------- #
#  EB04-049 指銃 黄蓮 (EVENT 黒 cost4):
#    【メイン】デッキ上2枚トラッシュ：相手の元々コスト5以下キャラ1枚KO /
#    【トリガー】このカードの【メイン】効果を発動
# --------------------------------------------------------------------------- #
def test_eb04_049_shigan_main_mill_and_ko_ai():
    """メイン: デッキ上2枚トラッシュ + 相手のコスト5以下キャラ1枚KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [victim]
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB04-049", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.deck) == deck_before - 2, "デッキ上2枚がトラッシュされていない"
    assert victim not in opp.characters, "相手のコスト5以下キャラが KO されていない"


def test_eb04_049_shigan_trigger_fires_main_ai():
    """トリガー: 自身の【メイン】効果を発動して 相手キャラをKO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-049", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-049"), sickness=False))

    assert victim not in opp.characters, \
        "トリガー経由の【メイン】発動で 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB04-050 調教してあげる♡ (EVENT 黒 cost1):
#    【メイン】自分の特徴《SWORD》リーダーかキャラ1枚まで このターン中
#             アクティブのキャラにもアタックできる /
#    【カウンター】自リーダー このバトル中 +3000
# --------------------------------------------------------------------------- #
def test_eb04_050_choukyou_main_give_active_attack_ai():
    """メイン: SWORD キャラ1枚に アクティブアタック可 を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sword = InPlay.of(repo.get("EB04-047"), sickness=False)  # ヘルメッポ SWORD
    me.characters = [sword]

    do, _ = _do(overlay, "EB04-050", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert "アクティブアタック可" in sword.granted_keywords, \
        "SWORD キャラに アクティブアタック可 が付与されていない"


def test_eb04_050_choukyou_main_give_active_attack_human_pick():
    """人間 + SWORD キャラ複数 → 付与対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    s1 = InPlay.of(repo.get("EB04-047"), sickness=False)  # ヘルメッポ SWORD
    s2 = InPlay.of(repo.get("OP11-004"), sickness=False)  # 孔雀 SWORD
    me.characters = [s1, s2]

    do, _ = _do(overlay, "EB04-050", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    s2_idx = next(i for i, c in enumerate(cands) if c["iid"] == s2.instance_id)
    resolve_pending_choice(st, [s2_idx])
    _drain(st, pick=[s2_idx])
    assert "アクティブアタック可" in s2.granted_keywords, \
        "人間が選んだ SWORD キャラに付与されていない"


def test_eb04_050_choukyou_counter_pump_leader_ai():
    """カウンター: 自リーダーを このバトル中 +3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power

    do, _ = _do(overlay, "EB04-050", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"
