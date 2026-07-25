# -*- coding: utf-8 -*-
"""OP07 弾 効果 回帰テスト バックフィル (自動生成 wave 079):
OP07-076 / OP07-077 / OP07-078 / OP07-079 / OP07-081 / OP07-082 /
OP07-083 / OP07-085 / OP07-086 / OP07-087 の 10 枚
(紫 フォクシー/百獣/BM ギミック 残 + 黒 CP0/スリラーバーク 除去 系)。

目的 (= 永続的 pytest による担保、 test_backfill_auto_078.py と同一方針):
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
    eval_all_conditions,
    eval_condition,
    execute_effect,
    evaluate_static_effects,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

_LEADER = "OP01-001"         # ロロノア・ゾロ (赤、 直接 execute_effect なので色は無関係)
_KAIDO_LEADER = "OP01-061"   # カイドウ (特徴《百獣海賊団》を持つ leader)
_FILLER = "OP01-013"         # サンジ cost2 power3000 (汎用フィラー、 相手キャラ cost<=6)
_OPP_C = "OP01-013"          # サンジ cost2 power3000 (相手キャラ)
_OPP_C2 = "OP06-025"         # ケイミー cost1 (相手キャラ 2 体目)
_FOXY_CHARA = "OP10-075"     # フォクシー cost2 power1000 (name「フォクシー」の CHARACTER)
_HYAKUJU_CHARA = "EB04-032"  # クイーン cost1 (特徴《百獣海賊団》の CHARACTER)
# スリラーバーク海賊団 の CHARACTER 4 枚 (OP07-083 の trash_to_deck コスト用)
_THRILLER = ["OP15-079", "OP15-080", "OP15-084", "EB02-046"]


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _state(repo, leader_id, overlay, human_idx=None, opp_leader_id="OP01-001"):
    """P0 = テスト対象デッキ、 P1 = ダミー。 turn_player=0 / MAIN。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get(opp_leader_id), sickness=False))
    p0.deck = [repo.get(_FILLER)] * 30
    p1.deck = [repo.get(_FILLER)] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _eff(overlay, cid, when):
    """when 一致の効果 dict (do + if を含む) を返す。"""
    matches = [e for e in overlay.get(cid).effects if e.get("when") == when]
    if not matches:
        raise AssertionError(f"{cid} に when={when} の効果がない")
    return matches[0]


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の効果の do (list) を返す。"""
    return _eff(overlay, cid, when)["do"]


def _drain(st, pick=0, guard=15):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave79_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-076", "OP07-077", "OP07-078", "OP07-079", "OP07-081",
           "OP07-082", "OP07-083", "OP07-085", "OP07-086", "OP07-087"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-076 ノロノロビームソード (EVENT 紫 cost2):
#    【カウンター】ドン‼-1：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。
#      その後、相手のキャラ1枚までを、レストにする。
#    【トリガー】ドン‼デッキからドン‼1枚までをアクティブで追加。
# --------------------------------------------------------------------------- #
def test_op07_076_counter_pump_and_rest_ai():
    """カウンター: 自リーダー +2000 (battle) + 相手キャラ1枚を rest (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    victim.rested = False
    opp.characters = [victim]
    leader_before = me.leader.power

    for prim in _do(overlay, "OP07-076", "counter"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.leader.power == leader_before + 2000, \
        f"自リーダーに battle +2000 が反映されていない: {me.leader.power}"
    assert victim.rested is True, "相手キャラが rest されていない"


def test_op07_076_counter_rest_human_pick():
    """カウンター (人間): 相手キャラが2体 → rest の target_pick modal → 選んだ方を rest。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C), sickness=False)
    b = InPlay.of(repo.get(_OPP_C2), sickness=False)
    opp.characters = [a, b]

    do = _do(overlay, "OP07-076", "counter")
    # do[0] = 自リーダー/キャラ +2000 (自陣キャラなし → リーダー一意、 modal なし)
    execute_effect(do[0], st, me, opp, None)
    _drain(st)
    # do[1] = 相手キャラ1枚 rest (2体 → 人間 modal)
    execute_effect(do[1], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.rested is True, "人間が選んだ相手キャラが rest されていない"
    assert a.rested is False, "選ばなかった相手キャラは rest されないべき"


def test_op07_076_trigger_add_active_don_ai():
    """トリガー: ドンデッキからアクティブドン1枚を追加 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    active_before = me.don_active

    for prim in _do(overlay, "OP07-076", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert me.don_active == active_before + 1, "トリガーでアクティブドンが1枚追加されていない"


# --------------------------------------------------------------------------- #
#  OP07-077 "ひとつなぎの大秘宝"を獲りに行くぞ!!! (EVENT 紫 cost1):
#    【メイン】自分のリーダーが特徴《百獣海賊団》か《ビッグ・マム海賊団》を持つ場合、
#      デッキ上5枚を見て、該当特徴カード1枚までを公開し手札に加える。残りをデッキ下へ。
# --------------------------------------------------------------------------- #
def test_op07_077_main_search_hyakuju_to_hand_ai():
    """メイン: デッキ上5枚から《百獣海賊団》カード1枚を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KAIDO_LEADER, overlay)  # カイドウ = 百獣海賊団
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_HYAKUJU_CHARA)] + [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP07-077", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert any(getattr(c, "card_id", None) == _HYAKUJU_CHARA for c in me.hand), \
        "デッキ上5枚から百獣海賊団カードが手札に加わっていない"
    assert len(me.hand) == hand_before + 1, "手札が1枚増えていない"


def test_op07_077_leader_feature_condition():
    """条件: リーダーが《百獣海賊団》/《ビッグ・マム海賊団》で成立、 そうでなければ不成立。"""
    repo = _repo()
    overlay = _overlay()
    cond = _eff(overlay, "OP07-077", "main").get("if")
    assert cond is not None, "OP07-077 に leader_feature 条件がない"
    st_ok = _state(repo, _KAIDO_LEADER, overlay)
    assert eval_condition(cond, st_ok, st_ok.players[0]) is True, \
        "百獣海賊団 leader で条件が成立するべき"
    st_ng = _state(repo, _LEADER, overlay)
    assert eval_condition(cond, st_ng, st_ng.players[0]) is False, \
        "対象特徴でない leader で条件が成立してはいけない"


def test_op07_077_trigger_fires_main_ai():
    """トリガー: 【メイン】効果を発動する (fire_self_effect) → crash せず手札に加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _KAIDO_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_HYAKUJU_CHARA)] + [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)
    # トリガー発火の source は そのイベントカード自身 (= engine が trigger 処理時に設定する)。
    st.current_source_card_id = "OP07-077"

    for prim in _do(overlay, "OP07-077", "trigger"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert len(me.hand) == hand_before + 1, \
        "トリガーの【メイン】再発動で百獣カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP07-078 メガトン九尾ラッシュ (EVENT 紫 cost3):
#    【メイン】自分の場のドン!!が相手の場のドン!!の枚数以下の場合、自分の「フォクシー」
#      1枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op07_078_main_untap_foxy_ai():
    """メイン: レストの「フォクシー」1枚をアクティブにする (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    foxy = InPlay.of(repo.get(_FOXY_CHARA), sickness=False)
    foxy.rested = True
    me.characters = [foxy]

    for prim in _do(overlay, "OP07-078", "main"):
        execute_effect(prim, st, me, opp, None)
    _drain(st)
    assert foxy.rested is False, "「フォクシー」がアクティブになっていない"


def test_op07_078_don_diff_condition():
    """条件: 自ドン<=相手ドン で成立 (don_diff_le 0)、 自ドンが多いと不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me = st.players[0]
    cond = _eff(overlay, "OP07-078", "main").get("if")
    assert cond is not None, "OP07-078 に don_diff 条件がない"
    assert eval_condition(cond, st, me) is True, "自0<=相手0で条件が成立するべき"
    me.don_active = 2
    assert eval_condition(cond, st, me) is False, \
        "自ドンが相手より多いと条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  OP07-079 ロブ・ルッチ (LEADER 黒):
#    【アタック時】自分のデッキの上から2枚をトラッシュに置くことができる：相手のキャラ
#      1枚までを、このターン中、コスト-1。
# --------------------------------------------------------------------------- #
def test_op07_079_leader_attack_mill_then_cost_minus_ai():
    """アタック時: 任意コスト (上2枚トラッシュ) を払い、 相手キャラ1枚を コスト-1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-079", overlay)  # リーダー = ロブ・ルッチ
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-079", "on_attack"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)
    assert len(me.deck) == deck_before - 2, "コストのデッキ上2枚トラッシュが起きていない"
    assert len(me.trash) == trash_before + 2, "トラッシュが2枚増えていない (mill コスト)"
    assert victim.base_cost == cost_before - 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op07_079_leader_attack_human_optional_cost():
    """アタック時 (人間): optional_cost_confirm modal → pay ([1]) で mill + コスト減 解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-079", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-079", "on_attack"):
        execute_effect(prim, st, me, opp, me.leader)
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert len(me.deck) == deck_before - 2, "任意コスト承認後に デッキ上2枚トラッシュが起きていない"
    assert victim.base_cost == cost_before - 1, \
        "任意コスト承認後に 相手キャラの コスト-1 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-081 カリファ (CHARACTER 黒 cost4):
#    【ドン‼×1】【自分のターン中】相手のキャラすべてを、コスト-1。 (静的)
# --------------------------------------------------------------------------- #
def test_op07_081_static_cost_minus_all_opp_ai():
    """静的 (ドン付与1 + 自ターン中): 相手のキャラすべてを コスト-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    califa = InPlay.of(repo.get("OP07-081"), sickness=False)
    califa.attached_dons = 1  # 【ドン‼×1】gate
    me.characters = [califa]
    o1 = InPlay.of(repo.get(_OPP_C), sickness=False)   # cost2
    o2 = InPlay.of(repo.get(_OPP_C2), sickness=False)  # cost1
    opp.characters = [o1, o2]
    c1_before, c2_before = o1.base_cost, o2.base_cost

    evaluate_static_effects(st, overlay)
    assert o1.base_cost == c1_before - 1, \
        f"相手キャラ o1 のコスト-1 が反映されていない: {o1.base_cost} (before {c1_before})"
    assert o2.base_cost == c2_before - 1, \
        f"相手キャラ o2 のコスト-1 が反映されていない: {o2.base_cost} (before {c2_before})"


def test_op07_081_static_off_turn_or_no_don():
    """条件: 相手ターン中 (自ターンでない) は コスト-1 が付かない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    st.turn_player_idx = 1  # 相手ターン → 【自分のターン中】不成立
    me, opp = st.players[0], st.players[1]
    califa = InPlay.of(repo.get("OP07-081"), sickness=False)
    califa.attached_dons = 1
    me.characters = [califa]
    o1 = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [o1]
    c1_before = o1.base_cost

    evaluate_static_effects(st, overlay)
    assert o1.base_cost == c1_before, \
        "相手ターン中はコスト-1が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP07-082 キャプテン・ジョン (CHARACTER 黒 cost2):
#    【登場時】自分のデッキの上から2枚をトラッシュに置き、相手のキャラ1枚までを、
#      このターン中、コスト-1。
# --------------------------------------------------------------------------- #
def test_op07_082_on_play_mill_and_cost_minus_ai():
    """登場時: 上2枚トラッシュ + 相手キャラ1枚を コスト-1 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-082", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-082"), sickness=False))
    _drain(st)
    assert len(me.deck) == deck_before - 2, "デッキ上2枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 2, "トラッシュが2枚増えていない"
    assert victim.base_cost == cost_before - 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op07_082_cost_minus_human_pick():
    """登場時 (人間): 相手キャラが2体 → cost_minus の target_pick modal → 選んだ方に コスト-1。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C), sickness=False)
    b = InPlay.of(repo.get(_OPP_C2), sickness=False)
    opp.characters = [a, b]

    do = _do(overlay, "OP07-082", "on_play")
    # do[0] = mill_self_top (対象なし)、 do[1] = cost_minus (2体 → modal)
    execute_effect(do[1], st, me, opp,
                   InPlay.of(repo.get("OP07-082"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.base_cost == b_before - 1, "人間が選んだ相手キャラに コスト-1 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-083 ゲッコー・モリア (CHARACTER 黒 cost4):
#    【起動メイン】自分のトラッシュの特徴《スリラーバーク海賊団》4枚を好きな順番で
#      デッキ下に置くことができる：このキャラは、このターン中、【バニッシュ】を得て、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op07_083_activate_trash_to_deck_then_vanish_pump_ai():
    """起動メイン: トラッシュのスリラーバーク4枚をデッキ下へ → バニッシュ付与 + パワー+1000 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-083"), sickness=False)
    me.characters = [moria]
    me.trash = [repo.get(cid) for cid in _THRILLER]  # スリラーバーク 4 枚
    me.deck = [repo.get(_FILLER)] * 10
    power_before = moria.power
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-083"]
    assert len(opts) == 1, f"OP07-083 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)
    assert moria.power == power_before + 1000, \
        f"パワー+1000 が反映されていない: {moria.power} (before {power_before})"
    assert "バニッシュ" in moria.granted_keywords, \
        "【バニッシュ】が付与されていない"
    assert len(me.trash) == trash_before - 4, "トラッシュのスリラーバーク4枚が離れていない"
    assert len(me.deck) == deck_before + 4, "デッキ下へ4枚が置かれていない"


def test_op07_083_activate_requires_4_thriller_in_trash():
    """負例: トラッシュのスリラーバークが3枚以下ならコストを払えず、 効果 (バニッシュ/+1000) が乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    moria = InPlay.of(repo.get("OP07-083"), sickness=False)
    me.characters = [moria]
    me.trash = [repo.get(cid) for cid in _THRILLER[:3]]  # 3 枚のみ
    me.deck = [repo.get(_FILLER)] * 10
    power_before = moria.power

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP07-083"]
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st)
    assert moria.power == power_before, \
        "スリラーバーク3枚 (コスト不足) では パワー+1000 が乗ってはいけない"
    assert "バニッシュ" not in moria.granted_keywords, \
        "スリラーバーク3枚 (コスト不足) では 【バニッシュ】が付いてはいけない"


# --------------------------------------------------------------------------- #
#  OP07-085 ステューシー (CHARACTER 黒 cost9):
#    【登場時】自分のキャラ1枚をトラッシュに置くことができる：相手のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op07_085_on_play_sacrifice_then_ko_ai():
    """登場時: 自キャラ1枚をトラッシュ (任意コスト) → 相手キャラ1枚を KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    fodder = InPlay.of(repo.get(_FILLER), sickness=False)  # 犠牲用 自キャラ
    me.characters = [fodder]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-085", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-085"), sickness=False))
    _drain(st)
    assert fodder not in me.characters, "任意コスト (自キャラKO) が支払われていない"
    assert victim not in opp.characters, "相手キャラが KO されていない"


def test_op07_085_on_play_human_optional_cost():
    """登場時 (人間): optional_cost_confirm modal → pay ([1]) で自キャラ犠牲 + 相手KO 解決。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    fodder = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [fodder]
    victim = InPlay.of(repo.get(_OPP_C), sickness=False)
    opp.characters = [victim]

    for prim in _do(overlay, "OP07-085", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-085"), sickness=False))
        if st.pending_choice is not None:
            break
    assert st.pending_choice is not None, "人間 任意コストの modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 任意コストを払う
    _drain(st)
    assert victim not in opp.characters, "任意コスト承認後に 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP07-086 スパンダム (CHARACTER 黒 cost3):
#    【登場時】自分のデッキの上から2枚をトラッシュに置き、相手のキャラ1枚までを、
#      このターン中、コスト-2。
# --------------------------------------------------------------------------- #
def test_op07_086_on_play_mill_and_cost_minus2_ai():
    """登場時: 上2枚トラッシュ + 相手キャラ1枚を コスト-2 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    deck_before = len(me.deck)
    trash_before = len(me.trash)
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [victim]
    cost_before = victim.base_cost

    for prim in _do(overlay, "OP07-086", "on_play"):
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-086"), sickness=False))
    _drain(st)
    assert len(me.deck) == deck_before - 2, "デッキ上2枚がトラッシュされていない"
    assert len(me.trash) == trash_before + 2, "トラッシュが2枚増えていない"
    assert victim.base_cost == max(0, cost_before - 2), \
        f"相手キャラの コスト-2 が反映されていない: {victim.base_cost} (before {cost_before})"


def test_op07_086_cost_minus_human_pick():
    """登場時 (人間): 相手キャラが2体 → cost_minus の target_pick modal → 選んだ方に コスト-2。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_OPP_C), sickness=False)   # cost2
    b = InPlay.of(repo.get("OP09-093"), sickness=False)  # 高コスト相手キャラ (下振れ防止)
    opp.characters = [a, b]

    do = _do(overlay, "OP07-086", "on_play")
    execute_effect(do[1], st, me, opp,
                   InPlay.of(repo.get("OP07-086"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で cost_minus modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b.base_cost == max(0, b_before - 2), \
        "人間が選んだ相手キャラに コスト-2 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-087 バスカビル (CHARACTER 黒 cost3):
#    【自分のターン中】相手のコスト0のキャラがいる場合、このキャラはパワー+3000。 (静的)
# --------------------------------------------------------------------------- #
def test_op07_087_static_pump_body_ai():
    """効果本体: パワー+3000 (static) が このキャラに乗る (do を直接発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    baskerville = InPlay.of(repo.get("OP07-087"), sickness=False)
    me.characters = [baskerville]
    power_before = baskerville.power

    for prim in _do(overlay, "OP07-087", "on_attached_don"):
        execute_effect(prim, st, me, opp, baskerville)
    _drain(st)
    assert baskerville.power == power_before + 3000, \
        f"パワー+3000 が反映されていない: {baskerville.power} (before {power_before})"


def test_op07_087_condition_needs_opp_cost0_chara():
    """条件: 相手にコスト0のキャラがいない場合は成立しない (通常キャラは cost>=1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    opp.characters = [InPlay.of(repo.get(_OPP_C), sickness=False)]  # cost2
    cond = _eff(overlay, "OP07-087", "on_attached_don").get("if")
    assert cond is not None, "OP07-087 に条件がない"
    assert eval_condition(cond, st, me) is False, \
        "相手にコスト0キャラがいない状態で条件が成立してはいけない"
