# -*- coding: utf-8 -*-
"""OP06 弾 効果 回帰テスト バックフィル (自動生成 wave 068):
OP06-058 / OP06-059 / OP06-062 / OP06-063 / OP06-064 / OP06-065 /
OP06-066 / OP06-067 / OP06-068 / OP06-069 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_066.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 / 択一 を 持つカードは 人間 actor で pending_choice が
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
_LEADER = "OP01-001"        # ロロノア・ゾロ (赤、 汎用リーダー)
_LEADER_GERMA = "OP06-042"  # ヴィンスモーク・レイジュ リーダー (ヴィンスモーク家/ジェルマ66)
_FILLER = "OP01-013"        # サンジ cost2 power3000 (汎用フィラー / cost<=N 対象)
_NAMI = "OP01-016"          # ナミ cost1 power2000 (cost<=N 対象)


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


def _drain(st, pick=0, guard=8):
    """pending_choice を pick で自動解決し切る (= 後続効果を流す)。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, [pick])
        g += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave68_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP06-058", "OP06-059", "OP06-062", "OP06-063", "OP06-064",
           "OP06-065", "OP06-066", "OP06-067", "OP06-068", "OP06-069"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP06-058 重力刀 猛虎 (EVENT 青 cost7):
#    【メイン】コスト6以下のキャラ2枚までを、好きな順番で持ち主のデッキの下に置く。
#    【トリガー】コスト5以下のキャラ1枚をデッキ下。
# --------------------------------------------------------------------------- #
def test_op06_058_main_return_two_to_deck_bottom_ai():
    """メイン: 相手コスト6以下キャラ2枚をデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 6
    b = InPlay.of(repo.get(_NAMI), sickness=False)    # cost1 <= 6
    opp.characters = [a, b]
    deck_before = len(opp.deck)
    src = InPlay.of(repo.get("OP06-058"), sickness=False)

    for prim in _do(overlay, "OP06-058", "main"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(opp.characters) == 0, "相手コスト6以下キャラ2枚がデッキ下に戻っていない"
    assert len(opp.deck) == deck_before + 2, "デッキ下に2枚追加されていない"


def test_op06_058_main_human_target_pick():
    """メイン (人間): 相手キャラ複数候補 → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    opp.characters = [
        InPlay.of(repo.get(_FILLER), sickness=False),
        InPlay.of(repo.get(_NAMI), sickness=False),
        InPlay.of(repo.get(_FILLER), sickness=False),
    ]
    src = InPlay.of(repo.get("OP06-058"), sickness=False)

    execute_effect(_do(overlay, "OP06-058", "main")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"


def test_op06_058_trigger_return_one_to_deck_bottom_ai():
    """トリガー: 相手コスト5以下キャラ1枚をデッキ下へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2 <= 5
    opp.characters = [victim]
    deck_before = len(opp.deck)
    src = InPlay.of(repo.get("OP06-058"), sickness=False)

    for prim in _do(overlay, "OP06-058", "trigger"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim not in opp.characters, "トリガーで相手キャラがデッキ下に戻っていない"
    assert len(opp.deck) == deck_before + 1, "デッキ下に1枚追加されていない"


# --------------------------------------------------------------------------- #
#  OP06-059 ホワイトスネーク (EVENT 青 cost2):
#    【カウンター】自リーダーかキャラ1枚まで +1000 (このターン) + カード1枚ドロー。
#    【トリガー】自デッキ上5枚を並び替え (上 or 下)。
# --------------------------------------------------------------------------- #
def test_op06_059_counter_pump_and_draw_ai():
    """カウンター (AI): 自リーダー +1000 + 1ドロー。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get(_FILLER)] * 10
    power_before = me.leader.power
    hand_before = len(me.hand)

    for prim in _do(overlay, "OP06-059", "counter"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert me.leader.power == power_before + 1000, \
        f"自リーダー +1000 が反映されていない: {me.leader.power} (before {power_before})"
    assert len(me.hand) == hand_before + 1, "カウンターの 1 ドローが起きていない"


def test_op06_059_counter_human_target_pick():
    """カウンター (人間): 自リーダー/キャラ 複数候補 → target_pick modal で選択。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    friend = InPlay.of(repo.get(_FILLER), sickness=False)
    me.characters = [friend]

    execute_effect(_do(overlay, "OP06-059", "counter")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    f_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert friend.power == f_before + 1000, "人間が選んだキャラに +1000 が反映されていない"


def test_op06_059_trigger_scry_ai():
    """トリガー (AI): 自デッキ上5枚並び替えが crash せず自動解決する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    deck_before = len(me.deck)

    for prim in _do(overlay, "OP06-059", "trigger"):
        execute_effect(prim, st, me, opp, me.leader)
    _drain(st)

    assert st.pending_choice is None, "AI 文脈で scry の modal が解決されていない"
    assert len(me.deck) == deck_before, "並び替えのみでデッキ枚数は変わらないはず"


def test_op06_059_trigger_scry_human_modal():
    """トリガー (人間): scry_deck_reorder modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10

    execute_effect(_do(overlay, "OP06-059", "trigger")[0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間で scry modal が立たない"
    assert st.pending_choice.get("kind") == "scry_deck_reorder", \
        f"kind が scry_deck_reorder でない: {st.pending_choice.get('kind')}"
    _drain(st)
    assert st.pending_choice is None, "解決後も modal が残る"


# --------------------------------------------------------------------------- #
#  OP06-062 ヴィンスモーク・ジャッジ (CHARACTER 紫 cost8):
#    【登場時】ドン-1,手札2枚捨て：トラッシュのカード名が異なるパワー4000以下の
#      《ジェルマ66》キャラ4枚までを登場。
#    【起動メイン】【ターン1回】ドン-1：相手のドン1枚までをレスト。
# --------------------------------------------------------------------------- #
def test_op06_062_on_play_revive_germa_ai():
    """登場時 do: トラッシュのカード名が異なる《ジェルマ66》pw4000以下を4枚まで登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    # カード名の異なる ジェルマ66 pw<=4000 を 4 種
    me.trash = [repo.get("OP06-060"), repo.get("OP06-064"),
                repo.get("OP06-066"), repo.get("OP06-068")]
    me.characters = []
    src = InPlay.of(repo.get("OP06-062"), sickness=True)

    for prim in _do(overlay, "OP06-062", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.characters) == 4, \
        f"トラッシュから 4 枚登場していない: {len(me.characters)}"
    names = {c.card.name for c in me.characters}
    assert len(names) == 4, f"登場したキャラ名が重複している: {names}"


def test_op06_062_activate_main_rest_opp_don_ai():
    """起動メイン: ドン-1 → 相手ドン1枚レスト (AI)。【ターン1回】検証も。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    judge = InPlay.of(repo.get("OP06-062"), sickness=False)
    me.characters = [judge]
    me.don_active = 2  # ドン-1 コスト支払い用
    opp.don_active = 2
    opp.don_rested = 0

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-062"]
    assert len(opts) == 1, f"OP06-062 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert opp.don_rested == 1, "相手ドンが1枚レストされていない"
    assert opp.don_active == 1, "相手のアクティブドンが1枚減っていない"

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP06-062"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP06-063 ヴィンスモーク・ソラ (CHARACTER 紫 cost1):
#    【登場時】手札1枚捨て：自場ドンが相手の場ドン以下なら、トラッシュのパワー4000以下の
#      《ヴィンスモーク家》キャラ1枚までを手札に加える。
# --------------------------------------------------------------------------- #
def test_op06_063_on_play_trash_to_hand_when_don_le_ai():
    """登場時 do: don_diff_le 成立時、 トラッシュの《ヴィンスモーク家》pw4000以下を手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    opp.don_active = 2  # 自 <= 相手 → don_diff_le:0 成立
    target = repo.get("OP06-064")  # ヴィンスモーク家 pw3000
    me.trash = [target]
    me.hand = []
    src = InPlay.of(repo.get("OP06-063"), sickness=True)

    for prim in _do(overlay, "OP06-063", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert any(c.card_id == "OP06-064" for c in me.hand), \
        "条件成立時にトラッシュ回収が手札に入っていない"
    assert target not in me.trash, "回収したカードがトラッシュに残っている"


def test_op06_063_on_play_no_effect_when_don_greater():
    """登場時 do: 自場ドンが相手より多い場合、 条件不成立で回収が起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 4
    opp.don_active = 2  # 自 > 相手 → don_diff_le:0 不成立
    me.trash = [repo.get("OP06-064")]
    me.hand = []
    src = InPlay.of(repo.get("OP06-063"), sickness=True)

    for prim in _do(overlay, "OP06-063", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert len(me.hand) == 0, "条件不成立なのにトラッシュ回収が起きている"


# --------------------------------------------------------------------------- #
#  OP06-064 ヴィンスモーク・ニジ (CHARACTER 紫 cost3):
#    【起動メイン】ドン-1,このキャラをトラッシュ：自リーダーが《ジェルマ66》なら、
#      手札かトラッシュのコスト5「ヴィンスモーク・ニジ」1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op06_064_activate_main_play_cost5_niji_ai():
    """起動メイン: 自身をトラッシュ (コスト) → 手札のコスト5ニジ (OP06-065) を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GERMA, overlay)  # ジェルマ66 リーダー
    me, opp = st.players[0], st.players[1]
    niji3 = InPlay.of(repo.get("OP06-064"), sickness=False)
    me.characters = [niji3]
    me.don_active = 2  # ドン-1 コスト用
    me.hand = [repo.get("OP06-065")]  # コスト5 ニジ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-064"]
    assert len(opts) == 1, f"OP06-064 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card.card_id == "OP06-065" for c in me.characters), \
        "コスト5ニジ (OP06-065) が登場していない"
    assert niji3 not in me.characters, "コストとして自身がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP06-065 ヴィンスモーク・ニジ (CHARACTER 紫 cost5):
#    【登場時】自場ドンが相手の場ドン以下の場合、以下から1つ選ぶ。
#      ・相手のコスト2以下のキャラ1枚をKO。
#      ・相手のコスト4以下のキャラ1枚を手札に戻す。
# --------------------------------------------------------------------------- #
def test_op06_065_on_play_choice_ai():
    """登場時 do: choice_effect を AI が自動選択し、 相手キャラを除去する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1 (KO/bounce 両対象)
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-065"), sickness=True)

    for prim in _do(overlay, "OP06-065", "on_play"):
        execute_effect(prim, st, me, opp, src)
    _drain(st)

    assert victim not in opp.characters, \
        "AI が択一効果を選んで相手キャラを除去していない"


def test_op06_065_on_play_choice_human_option_pick():
    """登場時 do: 人間 → option_pick modal が立ち、 KO 側を選ぶと相手キャラが KO される。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get(_NAMI), sickness=False)  # cost1
    opp.characters = [victim]
    src = InPlay.of(repo.get("OP06-065"), sickness=True)

    execute_effect(_do(overlay, "OP06-065", "on_play")[0], st, me, opp, src)
    assert st.pending_choice is not None, "人間で択一 modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"択一の候補が 2 件でない: {len(opts)}"

    _drain(st)  # 先頭 (= KO) を選択して解決
    assert victim not in opp.characters, "人間が選んだ択一で相手キャラが除去されていない"


# --------------------------------------------------------------------------- #
#  OP06-066 ヴィンスモーク・ヨンジ (CHARACTER 紫 cost2):
#    【起動メイン】ドン-1,このキャラをトラッシュ：自リーダーが《ジェルマ66》なら、
#      手札かトラッシュのコスト4「ヴィンスモーク・ヨンジ」1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op06_066_activate_main_play_cost4_yonji_ai():
    """起動メイン: 自身をトラッシュ → 手札のコスト4ヨンジ (OP06-067) を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GERMA, overlay)
    me, opp = st.players[0], st.players[1]
    yonji2 = InPlay.of(repo.get("OP06-066"), sickness=False)
    me.characters = [yonji2]
    me.don_active = 2
    me.hand = [repo.get("OP06-067")]  # コスト4 ヨンジ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-066"]
    assert len(opts) == 1, f"OP06-066 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card.card_id == "OP06-067" for c in me.characters), \
        "コスト4ヨンジ (OP06-067) が登場していない"
    assert yonji2 not in me.characters, "コストとして自身がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP06-067 ヴィンスモーク・ヨンジ (CHARACTER 紫 cost4):
#    自場ドンが相手の場ドン以下の場合、このキャラのパワー+1000。【ブロッカー】
# --------------------------------------------------------------------------- #
def test_op06_067_static_pump_when_don_le():
    """静的: 自場ドン<=相手なら base5000 → 6000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    yonji = InPlay.of(repo.get("OP06-067"), sickness=False)  # base 5000
    me.characters = [yonji]
    me.don_active = 2
    opp.don_active = 2  # 自 <= 相手 → +1000
    evaluate_static_effects(st, overlay)
    assert yonji.power == 6000, f"条件成立で power 6000 のはず: {yonji.power}"


def test_op06_067_static_no_pump_when_don_greater():
    """静的: 自場ドン>相手なら pump されず base5000 のまま。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    yonji = InPlay.of(repo.get("OP06-067"), sickness=False)  # base 5000
    me.characters = [yonji]
    me.don_active = 4
    opp.don_active = 2  # 自 > 相手 → pump なし
    evaluate_static_effects(st, overlay)
    assert yonji.power == 5000, f"条件不成立で power 5000 のはず: {yonji.power}"


# --------------------------------------------------------------------------- #
#  OP06-068 ヴィンスモーク・レイジュ (CHARACTER 紫 cost2):
#    【起動メイン】ドン-1,このキャラをトラッシュ：自リーダーが《ジェルマ66》なら、
#      手札かトラッシュのコスト4「ヴィンスモーク・レイジュ」1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op06_068_activate_main_play_cost4_reiju_ai():
    """起動メイン: 自身をトラッシュ → 手札のコスト4レイジュ (OP06-069) を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER_GERMA, overlay)
    me, opp = st.players[0], st.players[1]
    reiju2 = InPlay.of(repo.get("OP06-068"), sickness=False)
    me.characters = [reiju2]
    me.don_active = 2
    me.hand = [repo.get("OP06-069")]  # コスト4 レイジュ

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP06-068"]
    assert len(opts) == 1, f"OP06-068 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert any(c.card.card_id == "OP06-069" for c in me.characters), \
        "コスト4レイジュ (OP06-069) が登場していない"
    assert reiju2 not in me.characters, "コストとして自身がトラッシュに置かれていない"


# --------------------------------------------------------------------------- #
#  OP06-069 ヴィンスモーク・レイジュ (CHARACTER 紫 cost4):
#    【登場時】自場ドンが相手の場ドン以下でかつ、自分の手札が5枚以下の場合、カード2枚を引く。
# --------------------------------------------------------------------------- #
def test_op06_069_on_play_draw_two_when_conditions_met():
    """登場時: 条件成立時 (自場ドン<=相手 & 手札<=5) にカード2枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 2
    opp.don_active = 2      # 自 <= 相手 → don_diff_le:0 成立
    me.hand = [repo.get(_FILLER)] * 2  # 手札 2 枚 (<= 5)
    me.deck = [repo.get(_FILLER)] * 10
    hand_before = len(me.hand)

    eff = _eff(overlay, "OP06-069", "on_play")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, InPlay.of(repo.get("OP06-069"), sickness=True))
    _drain(st)

    assert len(me.hand) == hand_before + 2, \
        f"登場時の 2 ドローが起きていない: {len(me.hand)} (before {hand_before})"
