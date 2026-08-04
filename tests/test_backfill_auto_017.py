# -*- coding: utf-8 -*-
"""EB04 弾 効果 回帰テスト バックフィル (自動生成 wave 017):
EB04-026 / EB04-027 / EB04-028 / EB04-029 / EB04-030 / EB04-031 /
EB04-033 / EB04-034 / EB04-036 / EB04-038 の 10 枚。

目的 (= test_backfill_auto_001〜016.py と同一方針):
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
def test_all_wave17_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB04-026", "EB04-027", "EB04-028", "EB04-029", "EB04-030",
           "EB04-031", "EB04-033", "EB04-034", "EB04-036", "EB04-038"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB04-026 ブルーグラス (CHARACTER 青 cost4 power6000 エッグヘッド/海軍):
#    【登場時】相手のコスト1以下のキャラ1枚までを、持ち主のデッキの下に置く /
#    【アタック時】カード1枚を引き、自分の手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_eb04_026_bluegrass_on_play_return_deck_bottom_ai():
    """登場時: 相手のコスト1以下キャラ1枚を持ち主のデッキの下に置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)  # サカズキ (海軍)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [victim]
    deck_before = len(opp.deck)

    do, _ = _do(overlay, "EB04-026", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-026"), sickness=True))

    assert victim not in opp.characters, "相手のコスト1以下キャラがデッキ下に置かれていない"
    assert len(opp.deck) == deck_before + 1, "デッキ下に1枚戻っていない"
    assert opp.deck[-1].card_id == "OP01-016", "戻ったカードがデッキの底でない"


def test_eb04_026_bluegrass_on_play_human_pick():
    """人間 + 相手のコスト1以下キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    b = InPlay.of(repo.get("OP15-081"), sickness=False)  # サンジ cost1
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-026", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB04-026"), sickness=True))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだ相手キャラがデッキ下に置かれていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


def test_eb04_026_bluegrass_on_attack_draw_discard_ai():
    """アタック時: カード1枚引き、自分の手札1枚を捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-026", "on_attack")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-026"), sickness=False))

    # 引いて (+1) 捨てる (-1) → 手札枚数 net ±0、 デッキ -1、 トラッシュ +1
    assert len(me.hand) == hand_before, f"手札 net が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれていない"
    assert len(me.trash) == trash_before + 1, "手札1枚が捨てられていない"


# --------------------------------------------------------------------------- #
#  EB04-027 ボア・ハンコック (CHARACTER 青 cost5):
#    【登場時】カード2枚を引き、自分の手札1枚を捨てる /
#    【トリガー】手札からパワー5000以下の【トリガー】持ちキャラ1枚までを登場
# --------------------------------------------------------------------------- #
def test_eb04_027_hancock_on_play_draw2_discard_ai():
    """登場時: カード2枚引き、手札1枚捨てる (AI)。 手札 net +1、 デッキ -2、 トラッシュ +1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    trash_before = len(me.trash)

    do, _ = _do(overlay, "EB04-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-027"), sickness=True))

    assert len(me.hand) == hand_before + 1, f"手札 net (+2-1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"
    assert len(me.trash) == trash_before + 1, "手札1枚が捨てられていない"


def test_eb04_027_hancock_trigger_summon_trigger_char_ai():
    """トリガー: 手札からパワー5000以下の【トリガー】持ちキャラ1枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    trig_char = repo.get("PRB02-012")  # ナミ (トリガー持ち power2000)
    assert (trig_char.trigger or "").startswith("【トリガー】"), \
        "テスト前提: PRB02-012 は【トリガー】持ち"
    me.hand = [trig_char]
    chars_before = len(me.characters)

    do, _ = _do(overlay, "EB04-027", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-027"), sickness=False))

    assert any(c.card.card_id == "PRB02-012" for c in me.characters), \
        "手札のトリガー持ちキャラが登場していない"
    assert len(me.characters) == chars_before + 1, "キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  EB04-028 アイスタイム (EVENT 青 cost5 海軍):
#    【メイン】手札1捨てできる：海軍リーダーなら相手のパワー10000以下キャラ2枚まで
#             次の相手エンド終了時までアタックできない /
#    【トリガー】コスト5以下のキャラ1枚までを持ち主の手札に戻す
# --------------------------------------------------------------------------- #
def test_eb04_028_ice_time_main_cannot_attack_ai():
    """メイン (海軍リーダー): 手札1捨てて相手キャラ2枚までを 次相手ターン中 アタック不可 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)  # サカズキ (海軍)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016"), repo.get("ST01-004")]  # 捨てコスト用
    v1 = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ power5000
    v2 = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ power2000
    opp.characters = [v1, v2]
    hand_before = len(me.hand)

    assert eval_condition({"leader_feature": "海軍"}, st, me) is True, \
        "テスト前提: リーダーが 海軍 でない"
    do, _ = _do(overlay, "EB04-028", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before - 1, "手札1枚が捨てられていない (optional cost)"
    assert v1.cannot_attack_through_opp_turn is True, "相手キャラ1がアタック不可になっていない"
    assert v2.cannot_attack_through_opp_turn is True, "相手キャラ2がアタック不可になっていない"


def test_eb04_028_ice_time_trigger_return_to_hand_ai():
    """トリガー: 相手のコスト5以下キャラ1枚を持ち主の手札に戻す (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-041", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)

    do, _ = _do(overlay, "EB04-028", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手のコスト5以下キャラが手札に戻っていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻ったカードが相手の手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB04-029 女の…涙の落ちる音がした (EVENT 青 cost1):
#    【メイン】サンジリーダー: デッキ上3枚見てサンジ/イベント1枚公開手札追加、残りトラッシュ /
#    【カウンター】手札1捨てできる：自分の「サンジ」1枚まで このバトル中 パワー+4000
# --------------------------------------------------------------------------- #
def test_eb04_029_onnano_main_search_ai():
    """メイン (サンジリーダー): デッキ上3枚から サンジorイベント を手札に (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-026", overlay)  # サンジ leader
    me, opp = st.players[0], st.players[1]
    sanji_char = repo.get("OP01-013")  # サンジ CHARACTER
    assert sanji_char.name == "サンジ", "テスト前提: OP01-013 は サンジ"
    me.deck = [sanji_char] + [repo.get("OP01-016")] * 20  # 上に サンジ を仕込む
    me.hand = []

    assert eval_condition({"leader_name": "サンジ"}, st, me) is True, \
        "テスト前提: リーダー名が サンジ でない"
    do, _ = _do(overlay, "EB04-029", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == "OP01-013" for c in me.hand), \
        "デッキ上3枚から サンジ が手札に加わっていない"


def test_eb04_029_onnano_counter_pump_sanji_ai():
    """カウンター: 自分の「サンジ」1枚を このバトル中 +4000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-026", overlay)
    me, opp = st.players[0], st.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ power3000
    me.characters = [sanji]
    power_before = sanji.power

    do, _ = _do(overlay, "EB04-029", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert sanji.power == power_before + 4000, \
        f"カウンターの +4000 が サンジ に反映されていない: {sanji.power}"


def test_eb04_029_onnano_counter_pump_human_pick():
    """人間 + 「サンジ」 複数 → +4000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-026", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    s1 = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ
    s2 = InPlay.of(repo.get("OP15-047"), sickness=False)  # サンジ (別)
    me.characters = [s1, s2]

    do, _ = _do(overlay, "EB04-029", "counter")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    s2_idx = next(i for i, c in enumerate(cands) if c["iid"] == s2.instance_id)
    s2_before = s2.power
    resolve_pending_choice(st, [s2_idx])
    _drain(st, pick=[s2_idx])
    assert s2.power == s2_before + 4000, "人間が選んだ サンジ に +4000 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB04-030 カイドウ (CHARACTER 紫 cost7 power9000 四皇/百獣海賊団):
#    KOされる場合、代わりに自ドン1枚をドンデッキに戻せる (replace_ko) /
#    【登場時】ドン-2：百獣海賊団リーダーなら 速攻を得て 相手コスト7以下キャラ1枚レスト
# --------------------------------------------------------------------------- #
def test_eb04_030_kaidou_on_play_rest_and_rush_ai():
    """登場時: 相手のコスト7以下キャラ1枚をレスト + 自身が速攻を得る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)  # カイドウ (百獣海賊団) leader
    me, opp = st.players[0], st.players[1]
    kaidou = InPlay.of(repo.get("EB04-030"), sickness=True)  # power9000
    me.characters = [kaidou]
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-030", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, kaidou)

    assert victim.rested is True, "相手のコスト7以下キャラがレストされていない"
    assert "速攻" in kaidou.granted_keywords, "カイドウが速攻を得ていない"


def test_eb04_030_kaidou_replace_ko_return_don_ai():
    """replace_ko: KOされる代わりに自ドン1枚をドンデッキに戻し 場に残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)
    me, opp = st.players[0], st.players[1]
    kaidou = InPlay.of(repo.get("EB04-030"), sickness=False)
    me.characters = [kaidou]
    me.don_active = 2
    deck_don_before = me.don_remaining_in_deck

    replaced = try_replace_ko(
        st, me, opp, kaidou, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自ドンを戻せるのに KO が置換されていない"
    assert kaidou in me.characters, "置換成立時 カイドウは場に残るべき"
    assert me.don_remaining_in_deck == deck_don_before + 1, \
        "自ドン1枚がドンデッキに戻っていない"


# --------------------------------------------------------------------------- #
#  EB04-031 キング (CHARACTER 紫 cost6 power7000 ルナーリア族/百獣海賊団):
#    KOされる場合、代わりに自ドン1枚をドンデッキに戻せる (replace_ko) /
#    【起動メイン】【ターン1回】百獣海賊団リーダーで他のキングがいない場合、
#                 ドンデッキからアクティブ1枚 + レスト1枚を追加
# --------------------------------------------------------------------------- #
def test_eb04_031_king_activate_main_add_don_ai():
    """起動メイン: ドンデッキからアクティブ1 + レスト1 を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)  # カイドウ (百獣海賊団)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("EB04-031"), sickness=False)
    me.characters = [king]
    active_before = me.don_active
    rested_before = me.don_rested

    opts = _am(st, me, overlay, "EB04-031")
    assert len(opts) == 1, f"EB04-031 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"
    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"


def test_eb04_031_king_activate_main_blocked_by_other_king():
    """他の「キング」がいる場合、起動メイン条件が不成立 → legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("EB04-031"), sickness=False)
    other_king = InPlay.of(repo.get("EB04-031"), sickness=False)  # 他のキング
    me.characters = [king, other_king]

    opts = _am(st, me, overlay, "EB04-031")
    assert len(opts) == 0, "他のキングがいるのに起動メインが legal に出てはいけない"


def test_eb04_031_king_replace_ko_return_don_ai():
    """replace_ko: KOされる代わりに自ドン1枚を戻し 場に残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-061", overlay)
    me, opp = st.players[0], st.players[1]
    king = InPlay.of(repo.get("EB04-031"), sickness=False)
    me.characters = [king]
    me.don_active = 1
    deck_don_before = me.don_remaining_in_deck

    replaced = try_replace_ko(
        st, me, opp, king, overlay, by_opp_effect=True, leave_kind="ko",
    )
    assert replaced is True, "自ドンを戻せるのに KO が置換されていない"
    assert king in me.characters, "置換成立時 キングは場に残るべき"
    assert me.don_remaining_in_deck == deck_don_before + 1, \
        "自ドン1枚がドンデッキに戻っていない"


# --------------------------------------------------------------------------- #
#  EB04-033 グロッキーモンスターズ (CHARACTER 紫 cost5 巨人族/魚人族/フォクシー海賊団):
#    【登場時】ドン-1：フォクシー海賊団キャラ3枚以上なら 相手の元々パワー6000以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_eb04_033_groggy_on_play_ko_ai():
    """登場時: 相手の元々パワー6000以下キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-059", overlay)  # フォクシー leader
    me, opp = st.players[0], st.players[1]
    # フォクシー海賊団キャラ 3 枚 (グロッキー + ポルチェ + フォクシー)
    groggy = InPlay.of(repo.get("EB04-033"), sickness=False)
    me.characters = [groggy,
                     InPlay.of(repo.get("EB04-037"), sickness=False),  # ポルチェ
                     InPlay.of(repo.get("OP10-075"), sickness=False)]  # フォクシー
    assert eval_condition(
        {"self_chara_feature_count_ge": {"feature": "フォクシー海賊団", "count": 3}},
        st, me,
    ) is True, "テスト前提: フォクシー海賊団キャラ3枚の条件が成立していない"
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ 元々power2000
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-033", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, groggy)

    assert victim not in opp.characters, "相手の元々パワー6000以下キャラが KO されていない"


def test_eb04_033_groggy_on_play_high_power_safe():
    """相手の元々パワーが6000超なら 対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-059", overlay)
    me, opp = st.players[0], st.players[1]
    groggy = InPlay.of(repo.get("EB04-033"), sickness=False)
    me.characters = [groggy]
    victim = InPlay.of(repo.get("EB04-030"), sickness=False)  # カイドウ 元々power9000
    opp.characters = [victim]

    do, _ = _do(overlay, "EB04-033", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp, groggy)
    assert victim in opp.characters, "元々パワー6000超のキャラが KO されてはいけない"


def test_eb04_033_groggy_on_play_ko_human_pick():
    """人間 + 相手の元々パワー6000以下キャラ 複数 → KO 対象の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-059", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    groggy = InPlay.of(repo.get("EB04-033"), sickness=False)
    me.characters = [groggy]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)  # power2000
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # power3000
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB04-033", "on_play")
    execute_effect(do[0], st, me, opp, groggy)
    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB04-034 シャーロット・プリン (CHARACTER 紫 cost2 power1000 ビッグ・マム海賊団):
#    【ブロッカー】【相手のアタック時】【ターン1回】手札1捨てできる：
#      トラッシュにイベント4枚以上なら 自リーダーかキャラ1枚 このバトル中 +2000
# --------------------------------------------------------------------------- #
def test_eb04_034_pudding_opp_attack_pump_ai():
    """相手アタック時: 自リーダーかキャラ1枚を +2000 (AI = 高パワー = リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    prin = InPlay.of(repo.get("EB04-034"), sickness=False)  # power1000
    me.characters = [prin]
    # ⚠ 2026-08-05: 公式は 「自分の手札1枚を捨てることができる：**自分のトラッシュにイベントが
    #   4枚以上ある場合**、…+2000」。 コロン後の条件は効果のみを gate するので overlay では
    #   `conditional` の中にある。 以前は top-level `if` で、 テストが `do` を直接実行して
    #   **条件を一切満たさずに効果だけ検証** していた (= 条件が壊れても緑になる)。
    me.trash = [repo.get("EB04-008")] * 4          # イベント 4 枚 = 条件成立
    power_before = me.leader.power  # リーダー power5000 > プリン power1000 → AI はリーダーを選ぶ

    do, _ = _do(overlay, "EB04-034", "opp_attack")
    for prim in do:
        execute_effect(prim, st, me, opp, prin)

    assert me.leader.power == power_before + 2000, \
        f"相手アタック時の +2000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  EB04-036 フォクシー (CHARACTER 紫 cost8 power9000 フォクシー海賊団):
#    【登場時】ドン-1：フォクシー海賊団リーダーなら 2ドロー1捨て + 相手コスト9以下1枚レスト /
#    【起動メイン】【ターン1回】ドンデッキからレスト1枚を追加
# --------------------------------------------------------------------------- #
def test_eb04_036_foxy_on_play_draw_discard_rest_ai():
    """登場時: 2枚引き1枚捨て + 相手のコスト9以下キャラ1枚レスト (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-059", overlay)  # フォクシー leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-016")]
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("ST01-013"), sickness=False)  # ゾロ cost3
    opp.characters = [victim]
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    do, _ = _do(overlay, "EB04-036", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-036"), sickness=False))

    assert len(me.hand) == hand_before + 1, f"手札 net (+2-1) が合わない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"
    assert victim.rested is True, "相手のコスト9以下キャラがレストされていない"


def test_eb04_036_foxy_activate_main_add_rested_don_ai():
    """起動メイン: ドンデッキからレストドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-059", overlay)
    me, opp = st.players[0], st.players[1]
    foxy = InPlay.of(repo.get("EB04-036"), sickness=False)
    me.characters = [foxy]
    rested_before = me.don_rested

    opts = _am(st, me, overlay, "EB04-036")
    assert len(opts) == 1, f"EB04-036 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_rested == rested_before + 1, "起動メインでレストドンが1枚追加されていない"


# --------------------------------------------------------------------------- #
#  EB04-038 ロシナンテ＆ロー (CHARACTER 紫 cost6 power8000 海軍/ドンキホーテ海賊団):
#    【ブロッカー】【登場時】自ドンが相手ドン以下なら 1ドロー + ドンデッキからアクティブ1枚追加
# --------------------------------------------------------------------------- #
def test_eb04_038_rosinante_law_on_play_draw_add_don_ai():
    """登場時: 1ドロー + ドンデッキからアクティブドン1枚追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5
    me.don_active = 0
    opp.don_active = 3  # 自ドン(0) ≦ 相手ドン(3) → 条件成立
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    active_before = me.don_active

    assert eval_condition({"don_diff_le": 0}, st, me) is True, \
        "テスト前提: 自ドン ≦ 相手ドン の条件が成立していない"
    do, _ = _do(overlay, "EB04-038", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB04-038"), sickness=False))

    assert len(me.hand) == hand_before + 1, "1枚引かれていない"
    assert len(me.deck) == deck_before - 1, "デッキから1枚引かれていない"
    assert me.don_active == active_before + 1, "アクティブドンが1枚追加されていない"
