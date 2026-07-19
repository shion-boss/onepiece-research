# -*- coding: utf-8 -*-
"""EB03 弾 効果 回帰テスト バックフィル (自動生成 wave 013):
EB03-038 / EB03-043 / EB03-044 / EB03-045 / EB03-046 / EB03-047 /
EB03-049 / EB03-050 / EB03-051 / EB03-052 の 10 枚。

目的 (= test_backfill_auto_001〜012.py と同一方針):
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
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める。"""
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
def test_all_eb03_wave13_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB03-038", "EB03-043", "EB03-044", "EB03-045", "EB03-046",
           "EB03-047", "EB03-049", "EB03-050", "EB03-051", "EB03-052"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB03-038 ごち♡ (EVENT 紫):
#    【メイン】自ドン1レスト:自ドン ≤ 相手ドン かつ 自キャラが『ジェルマ』特徴のみ →
#      ドンデッキからレストドン2枚まで追加 /
#    【カウンター】自リーダー このバトル +3000
# --------------------------------------------------------------------------- #
def test_eb03_038_main_add_rested_don_ai():
    """メイン do: ドンデッキからレストドン2枚を追加する (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP12-062", overlay)  # ジェルマ王国 leader (対象外だが do 直発火)
    me, opp = st.players[0], st.players[1]
    me.don_remaining_in_deck = 10
    me.don_rested = 0

    rested_before = me.don_rested
    do, _ = _do(overlay, "EB03-038", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.don_rested == rested_before + 2, \
        f"メインでレストドン2枚が追加されていない: {me.don_rested}"


def test_eb03_038_main_condition_jerma_only_and_don_diff():
    """メインの if: 自ドン ≤ 相手ドン かつ 自キャラが『ジェルマ』特徴のみ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP12-062", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 1
    opp.don_active = 3  # 相手ドンの方が多い → don_diff_le=0 成立
    me.characters = [InPlay.of(repo.get("OP10-063"), sickness=False)]  # ジェルマ王国

    assert eval_condition({"don_diff_le": 0}, st, me) is True, \
        "自ドン ≤ 相手ドン で don_diff_le=0 が成立していない"
    assert eval_condition(
        {"self_chara_only_feature_contains": "ジェルマ"}, st, me) is True, \
        "自キャラが『ジェルマ』特徴のみで条件が成立していない"
    # 非ジェルマキャラを混ぜると『ジェルマのみ』は崩れる
    me.characters.append(InPlay.of(repo.get("ST01-004"), sickness=False))  # 麦わらの一味
    assert eval_condition(
        {"self_chara_only_feature_contains": "ジェルマ"}, st, me) is False, \
        "非ジェルマキャラが居るのに『ジェルマのみ』が成立してはいけない"


def test_eb03_038_counter_pump_leader_ai():
    """カウンター: 自リーダー このバトル +3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP12-062", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB03-038", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  EB03-043 ステューシー (CHARACTER 黒 cost7):
#    【ブロッカー】【登場時】自トラッシュの『CP』特徴カード2枚をデッキ下に置ける:
#      相手のコスト4以下のキャラ1枚までを KO
# --------------------------------------------------------------------------- #
def test_eb03_043_stussy_on_play_ko_with_cp_cost_ai():
    """登場時: トラッシュの『CP』2枚をデッキ下 (コスト) → 相手コスト4以下1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB01-044"), repo.get("EB01-043")]  # CP9 ×2
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    opp.characters = [victim]

    trash_before = len(me.trash)
    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-043"), sickness=False))
    assert victim not in opp.characters, "相手コスト4以下キャラが KO されていない"
    assert len(me.trash) == trash_before - 2, "コストで CP カード2枚がトラッシュから離れるべき"
    assert len(me.deck) == deck_before + 2, "デッキ下に CP カード2枚が置かれるべき"


def test_eb03_043_stussy_on_play_no_cp_in_trash():
    """トラッシュに『CP』が2枚未満なら任意コスト不能 → 不発 (KO されない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB01-044")]  # CP 1 枚のみ (< 2)
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-043", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-043"), sickness=False))
    assert victim in opp.characters, "CP カードが足りないのに KO されてはいけない (不発)"


def test_eb03_043_stussy_on_play_human_optional_confirm():
    """人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で KO まで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("EB01-044"), repo.get("EB01-043")]  # CP ×2
    me.deck = [repo.get("ST01-004")] * 5
    victim = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-043", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-043"), sickness=False))
    assert st.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾 (= コストを払う)
    _drain(st, pick=[0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  EB03-044 ブラックマリア (CHARACTER 黒 cost3):
#    リーダー多色なら【ブロッカー】/【登場時】デッキ上5枚から「鬼ヶ島」1枚まで手札 →
#      その後 手札の「鬼ヶ島」1枚までを登場
# --------------------------------------------------------------------------- #
def test_eb03_044_blackmaria_on_play_search_and_play_oni_ai():
    """登場時: デッキ上5枚から「鬼ヶ島」を回収 → ステージとして登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-021", overlay)  # ペローナ (緑/黒 多色)
    me, opp = st.players[0], st.players[1]
    oni = repo.get("ST04-017")  # 鬼ヶ島 (STAGE)
    me.deck = [oni] + [repo.get("ST01-004")] * 20
    me.hand = []
    me.stages = []

    do, _ = _do(overlay, "EB03-044", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-044"), sickness=False))
    on_field = any(s.card.card_id == "ST04-017" for s in me.stages)
    in_hand = any(c.card_id == "ST04-017" for c in me.hand)
    assert on_field or in_hand, "デッキ上5枚の「鬼ヶ島」が手札/ステージに移っていない"
    assert me.deck[0].card_id != "ST04-017" or len(me.deck) == 0, \
        "「鬼ヶ島」がデッキ上に残っている"


def test_eb03_044_blackmaria_leader_color_multi_condition():
    """ブロッカー付与の gate: リーダーが多色 (leader_color_multi)。"""
    repo = _repo()
    overlay = _overlay()
    st_multi = _state(repo, "OP06-021", overlay)   # 緑/黒 多色
    me_multi = st_multi.players[0]
    assert eval_condition({"leader_color_multi": True}, st_multi, me_multi) is True, \
        "多色リーダーで leader_color_multi が成立していない"
    st_mono = _state(repo, "OP01-001", overlay)    # 赤 単色
    me_mono = st_mono.players[0]
    assert eval_condition({"leader_color_multi": True}, st_mono, me_mono) is False, \
        "単色リーダーで leader_color_multi が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB03-045 ペローナ (CHARACTER 黒 cost4):
#    【ブロッカー】【登場時】自リーダー/キャラにレストドン1付与 →
#      トラッシュ10枚以上なら トラッシュのコスト2以下《スリラーバーク海賊団》1枚まで レスト登場
# --------------------------------------------------------------------------- #
def test_eb03_045_perona_on_play_attach_rested_don_ai():
    """登場時: 自リーダーにレストドン1枚を付与 (AI = リーダー既定)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 2

    don_before = me.leader.attached_dons
    do, _ = _do(overlay, "EB03-045", "on_play", needle="attach_rested_don")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-045"), sickness=False))
    assert me.leader.attached_dons == don_before + 1, \
        "登場時に自リーダーへレストドンが付与されていない"


def test_eb03_045_perona_on_play_play_thriller_from_trash_ai():
    """登場時 (トラッシュ10+): トラッシュのコスト2以下《スリラーバーク海賊団》をレスト登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    thriller = repo.get("OP14-082")  # ブヒチャック スリラー cost2
    me.trash = [thriller] + [repo.get("ST01-004")] * 11  # トラッシュ 12 枚 (≥10)

    assert eval_condition({"self_trash_count_ge": 10}, st, me) is True, \
        "トラッシュ12枚で self_trash_count_ge=10 が成立していない"
    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB03-045", "on_play", needle="play_from_trash")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-045"), sickness=False))
    assert len(me.characters) == chars_before + 1, \
        "トラッシュから《スリラーバーク海賊団》キャラが登場していない"
    assert any(c.card.card_id == "OP14-082" for c in me.characters), \
        "登場したのが想定の スリラー キャラでない"


def test_eb03_045_perona_trash_lt_10():
    """トラッシュが10枚未満なら self_trash_count_ge=10 は不成立 (trash 登場しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    me.trash = [repo.get("ST01-004")] * 5  # 5 枚 (< 10)
    assert eval_condition({"self_trash_count_ge": 10}, st, me) is False, \
        "トラッシュ5枚で self_trash_count_ge=10 が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB03-046 ミス・ダブルフィンガー(ザラ) (CHARACTER 黒 cost4):
#    【登場時】コスト0か8以上のキャラがいる場合 1ドロー /
#    【KO時】デッキ上2枚をトラッシュ
# --------------------------------------------------------------------------- #
def test_eb03_046_double_finger_on_play_draw_ai():
    """登場時 do: 1ドロー (AI)。 コスト8以上キャラを場に置いて条件も満たす。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("EB04-051"), sickness=False)]  # cost8
    me.hand = []
    me.deck = [repo.get("ST01-004")] * 5

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-046", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-046"), sickness=False))
    assert len(me.hand) == hand_before + 1, "登場時の1ドローが起きていない"


def test_eb03_046_double_finger_on_play_condition():
    """登場時 gate: コスト0か8以上のキャラがいる (exists_chara_cost_0_or_ge_8)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    assert eval_condition({"exists_chara_cost_0_or_ge_8": True}, st, me) is False, \
        "コスト0/8以上キャラ不在で条件が成立してはいけない"
    me.characters = [InPlay.of(repo.get("EB04-051"), sickness=False)]  # cost8
    assert eval_condition({"exists_chara_cost_0_or_ge_8": True}, st, me) is True, \
        "コスト8キャラが居るのに条件が成立していない"


def test_eb03_046_double_finger_on_ko_mill_ai():
    """KO時: デッキ上2枚をトラッシュに置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.trash = []

    deck_before = len(me.deck)
    trash_before = len(me.trash)
    do, _ = _do(overlay, "EB03-046", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-046"), sickness=False))
    assert len(me.deck) == deck_before - 2, "KO時にデッキ上2枚が離れていない"
    assert len(me.trash) == trash_before + 2, "デッキ上2枚がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  EB03-047 ミス・バレンタイン(ミキータ) (CHARACTER 黒 cost2):
#    【登場時】デッキ上3枚をトラッシュ /【KO時】1ドロー
# --------------------------------------------------------------------------- #
def test_eb03_047_valentine_on_play_mill_ai():
    """登場時: デッキ上3枚をトラッシュに置く (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.trash = []

    deck_before = len(me.deck)
    do, _ = _do(overlay, "EB03-047", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-047"), sickness=False))
    assert len(me.deck) == deck_before - 3, "登場時にデッキ上3枚が離れていない"
    assert len(me.trash) == 3, "デッキ上3枚がトラッシュに置かれていない"


def test_eb03_047_valentine_on_ko_draw_ai():
    """KO時: 1ドロー (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []

    hand_before = len(me.hand)
    do, _ = _do(overlay, "EB03-047", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-047"), sickness=False))
    assert len(me.hand) == hand_before + 1, "KO時の1ドローが起きていない"


# --------------------------------------------------------------------------- #
#  EB03-049 やっぱりお前らかこの大騒ぎ (EVENT 黒 cost1):
#    【メイン】ドン7レスト:ペローナリーダー時、手札/トラッシュから
#      《スリラーバーク海賊団》コスト6以下キャラ 2枚まで登場 /
#    【カウンター】自リーダー このバトル +3000
# --------------------------------------------------------------------------- #
def test_eb03_049_main_play_thriller_ai():
    """メイン (ペローナリーダー): 手札から《スリラーバーク海賊団》コスト6以下2枚を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-021", overlay)  # ペローナ leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("PRB02-013"), repo.get("EB02-046")]  # モリア cost6 / ヒルドン cost3

    assert eval_condition({"leader_name": "ペローナ"}, st, me) is True, \
        "ペローナリーダーで leader_name 条件が成立していない"
    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB03-049", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.characters) == chars_before + 2, \
        "手札から《スリラーバーク海賊団》キャラ2枚が登場していない"


def test_eb03_049_main_negative_leader():
    """リーダーが「ペローナ」でない場合、 メイン登場条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ
    me, _opp = st.players[0], st.players[1]
    assert eval_condition({"leader_name": "ペローナ"}, st, me) is False, \
        "非ペローナリーダーで leader_name 条件が成立してはいけない"


def test_eb03_049_counter_pump_leader_ai():
    """カウンター: 自リーダー このバトル +3000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-021", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    do, _ = _do(overlay, "EB03-049", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert me.leader.power == power_before + 3000, \
        f"カウンターの +3000 が自リーダーに反映されていない: {me.leader.power}"


# --------------------------------------------------------------------------- #
#  EB03-050 コニス (CHARACTER 黄 cost2):
#    【登場時】自分の特徴《空島》キャラ1枚までは このターン中【ダブルアタック】を得る
# --------------------------------------------------------------------------- #
def test_eb03_050_conis_on_play_grant_double_attack_ai():
    """登場時: 自《空島》キャラ1枚に【ダブルアタック】を付与 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    sky = InPlay.of(repo.get("EB01-054"), sickness=False)  # ガン・フォール 空島
    me.characters = [sky]

    do, _ = _do(overlay, "EB03-050", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-050"), sickness=False))
    assert "ダブルアタック" in sky.granted_keywords, \
        "《空島》キャラに【ダブルアタック】が付与されていない"


def test_eb03_050_conis_on_play_human_pick():
    """人間 + 《空島》キャラ複数 → target_pick modal が立ち resolve で1枚に付与。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB01-054"), sickness=False)  # 空島
    b = InPlay.of(repo.get("EB01-054"), sickness=False)  # 空島
    me.characters = [a, b]

    do, _ = _do(overlay, "EB03-050", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB03-050"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert "ダブルアタック" in b.granted_keywords, \
        "人間が選んだ《空島》キャラに【ダブルアタック】が付与されていない"
    assert "ダブルアタック" not in a.granted_keywords, \
        "選ばなかったキャラに付与されてはいけない"


# --------------------------------------------------------------------------- #
#  EB03-051 シャーロット・スムージー (CHARACTER 黄 cost3):
#    【登場時】自分の表向きのライフがある場合、相手のコスト2以下キャラ1枚まで KO →
#      その後 自分のライフすべてを裏向きにする
# --------------------------------------------------------------------------- #
def test_eb03_051_smoothie_on_play_ko_and_life_face_down_ai():
    """登場時 (表向きライフ有): 相手コスト2以下1枚を KO → 自ライフ全裏向き (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.face_up_life_count = 2  # 表向き 2 枚 (= 条件成立)
    victim = InPlay.of(repo.get("EB01-017"), sickness=False)  # cost2
    opp.characters = [victim]

    do, _ = _do(overlay, "EB03-051", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-051"), sickness=False))
    assert victim not in opp.characters, "相手コスト2以下キャラが KO されていない"
    assert me.face_up_life_count == 0, "自ライフが裏向きになっていない"


def test_eb03_051_smoothie_has_face_up_life_condition():
    """gate: 自分の表向きのライフがある (has_face_up_life)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, _opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.face_up_life_count = 0
    assert eval_condition({"has_face_up_life": True}, st, me) is False, \
        "表向きライフ0で has_face_up_life が成立してはいけない"
    me.face_up_life_count = 1
    assert eval_condition({"has_face_up_life": True}, st, me) is True, \
        "表向きライフ1で has_face_up_life が成立していない"


def test_eb03_051_smoothie_on_play_cost3_survives():
    """コスト3のキャラは【コスト2以下】対象外 → KO されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("ST01-004")] * 2
    me.face_up_life_count = 2
    big = InPlay.of(repo.get("EB02-029"), sickness=False)  # cost3
    opp.characters = [big]

    do, _ = _do(overlay, "EB03-051", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB03-051"), sickness=False))
    assert big in opp.characters, "コスト3キャラが KO されてはいけない (対象外)"


# --------------------------------------------------------------------------- #
#  EB03-052 しらほし (CHARACTER 黄 cost3):
#    【起動メイン】このキャラをトラッシュ:しらほしリーダー時、デッキ上1枚をライフの上へ →
#      その後 自《海王類》キャラすべて このターン中 +1000
# --------------------------------------------------------------------------- #
def test_eb03_052_shirahoshi_activate_main_ai():
    """起動メイン: 自身をトラッシュ (コスト) → デッキ上1枚をライフ + 自《海王類》全体 +1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP11-022", overlay)  # しらほし leader
    me, opp = st.players[0], st.players[1]
    shirahoshi = InPlay.of(repo.get("EB03-052"), sickness=False)
    kaiou = InPlay.of(repo.get("OP11-027"), sickness=False)  # ギョロ目 海王類 P6000
    me.characters = [shirahoshi, kaiou]
    me.deck = [repo.get("ST01-004")] * 5
    me.life = []

    life_before = len(me.life)
    deck_before = len(me.deck)
    kaiou_before = kaiou.power
    opts = _am(st, me, overlay, "EB03-052")
    assert len(opts) == 1, f"EB03-052 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert shirahoshi not in me.characters, "コストで しらほし がトラッシュに置かれるべき"
    assert len(me.life) == life_before + 1, "デッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "ライフに加えた分デッキが1枚減るべき"
    assert kaiou.power == kaiou_before + 1000, \
        f"自《海王類》キャラの +1000 が反映されていない: {kaiou.power}"


def test_eb03_052_shirahoshi_activate_main_wrong_leader():
    """リーダーが「しらほし」でなければ leader_name 条件不成立 → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (しらほしでない)
    me, _opp = st.players[0], st.players[1]
    shirahoshi = InPlay.of(repo.get("EB03-052"), sickness=False)
    me.characters = [shirahoshi]
    me.deck = [repo.get("ST01-004")] * 5

    assert eval_condition({"leader_name": "しらほし"}, st, me) is False, \
        "非しらほしリーダーで leader_name 条件が成立してはいけない"
    opts = _am(st, me, overlay, "EB03-052")
    assert len(opts) == 0, "しらほしリーダー以外で起動メインが legal に出てはいけない"
