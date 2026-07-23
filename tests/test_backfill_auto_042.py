# -*- coding: utf-8 -*-
"""OP03 弾 (黒 CP + 黄 ビッグ・マム海賊団) 効果 回帰テスト バックフィル (自動生成 wave 042):
OP03-094 / OP03-095 / OP03-096 / OP03-097 / OP03-098 / OP03-100 /
OP03-102 / OP03-104 / OP03-105 / OP03-108 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
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
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    st = GameState(players=[p0, p1], phase=Phase.MAIN, rng=random.Random(1),
                   effects_overlay=overlay)
    st.turn_player_idx = 0
    st.turn_number = 3  # 1 ターン目制限を回避
    st.human_player_idx = human_idx
    if human_idx is not None:
        st.forced_human_actor_idx = human_idx
    return st


def _get_eff(overlay, cid, when, needle=None):
    for e in overlay.get(cid).effects:
        if e["when"] == when and (needle is None or needle in str(e["do"])):
            return e
    raise KeyError(cid, when, needle)


def _drain(st, sel=None, guard=8):
    """pending_choice を sel (既定 [0]) で解決し続ける (人間チェーン用)。"""
    if sel is None:
        sel = [0]
    g = 0
    while st.pending_choice is not None and g < guard:
        resolve_pending_choice(st, sel)
        g += 1


def _ids(chars):
    return [c.card.card_id for c in chars]


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op03_wave42_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-094", "OP03-095", "OP03-096", "OP03-097", "OP03-098",
           "OP03-100", "OP03-102", "OP03-104", "OP03-105", "OP03-108"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-094 空気開扉 (EVENT 黒 cost4):
#    【メイン】自リーダーが『CP』特徴 → デッキ上5枚を見て コスト5以下の『CP』
#      キャラ1枚までを登場、 残りをトラッシュ。
#    【トリガー】自トラッシュからコスト3以下の黒キャラ1枚までを登場。
# --------------------------------------------------------------------------- #
def test_op03_094_main_search_cp_play_ai():
    """【メイン】(リーダー CP) デッキ上5枚から CP キャラを登場、 残り4枚をトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)  # ロブ・ルッチ (CP9) リーダー
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP03-088")] + [repo.get("OP01-013")] * 10  # 先頭に CP キャラ
    trash_before = len(me.trash)

    on_main = _get_eff(overlay, "OP03-094", "main")
    assert on_main.get("if", {}).get("leader_feature_contains") == "CP", \
        "overlay の リーダー特徴 CP 条件が無い"
    assert eval_condition(on_main["if"], st, me) is True, \
        "テスト前提: リーダーが CP で条件成立していない"
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-094"), sickness=True))

    assert any(c.card.card_id == "OP03-088" for c in me.characters), \
        "デッキ上5枚から CP キャラが登場していない"
    # 上5枚のうち 1枚登場 / 残り4枚トラッシュ
    assert len(me.trash) == trash_before + 4, \
        f"登場しなかった残り4枚がトラッシュに置かれていない: {len(me.trash)}"


def test_op03_094_main_condition_false_non_cp_leader():
    """リーダーが『CP』特徴を持たない場合、【メイン】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (CP でない)
    me = st.players[0]
    on_main = _get_eff(overlay, "OP03-094", "main")
    assert eval_condition(on_main["if"], st, me) is False, \
        "リーダーが CP でないのに条件が成立している"


def test_op03_094_main_human_search_modal():
    """人間 actor: デッキ上5枚を公開して選ばせる search_top_n modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP03-088")] + [repo.get("OP01-013")] * 10

    on_main = _get_eff(overlay, "OP03-094", "main")
    execute_effect(on_main["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-094"), sickness=True))

    assert st.pending_choice is not None, "人間 + CP候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    _drain(st, [0])  # 解決できること (crash しない)


def test_op03_094_trigger_play_from_trash_ai():
    """【トリガー】自トラッシュからコスト3以下の黒キャラを登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-088")]  # フクロウ 黒 cost3 (<=3)
    chars_before = len(me.characters)

    on_trig = _get_eff(overlay, "OP03-094", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-094"), sickness=True))

    assert len(me.characters) == chars_before + 1, "トラッシュから黒キャラが登場していない"
    assert any(c.card.card_id == "OP03-088" for c in me.characters), \
        "登場したキャラが想定 (OP03-088) でない"


# --------------------------------------------------------------------------- #
#  OP03-095 石鹼羊 (EVENT 黒 cost1):
#    【メイン】相手のキャラ2枚までを、 このターン中、 コスト-2。
#    【トリガー】相手は自身の手札1枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op03_095_main_cost_minus_ai():
    """【メイン】相手キャラ2枚までを コスト-2 (AI 自動、 2体に -2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4
    b = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ cost2
    opp.characters = [a, b]

    on_main = _get_eff(overlay, "OP03-095", "main")
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp, None)

    assert a.base_cost == a.card.cost - 2, f"a のコストが -2 されていない: {a.base_cost}"
    assert b.base_cost == b.card.cost - 2, f"b のコストが -2 されていない: {b.base_cost}"


def test_op03_095_main_human_target_pick():
    """人間 + 相手キャラ 3体 → target_pick modal (2枚まで) が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-005"), sickness=False)   # ウタ cost4
    b = InPlay.of(repo.get("OP01-013"), sickness=False)   # サンジ cost2
    c = InPlay.of(repo.get("OP01-016"), sickness=False)   # cost1
    opp.characters = [a, b, c]

    on_main = _get_eff(overlay, "OP03-095", "main")
    execute_effect(on_main["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 3候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 3, f"候補が3体でない: {len(cands)}"
    a_idx = next(i for i, x in enumerate(cands) if x["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    _drain(st, [a_idx])
    assert a.base_cost == a.card.cost - 2, "人間が選んだ相手キャラのコストが -2 されていない"


def test_op03_095_trigger_trash_opp_hand_ai():
    """【トリガー】相手は手札1枚を捨てる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.hand = [repo.get("OP01-013"), repo.get("OP01-016")]
    hand_before = len(opp.hand)

    on_trig = _get_eff(overlay, "OP03-095", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(opp.hand) == hand_before - 1, \
        f"相手の手札が1枚捨てられていない: {len(opp.hand)}"


# --------------------------------------------------------------------------- #
#  OP03-096 嵐脚 周断 (EVENT 黒 cost2):
#    【メイン】相手のコスト0キャラか、 相手のコスト3以下のステージ1枚までを、 KOする。
#    【トリガー】カード2枚を引く。
# --------------------------------------------------------------------------- #
def _cheap_stage_id(repo):
    for c in repo._by_id.values():
        if c.category.name == "STAGE" and c.cost <= 3 \
                and "_p" not in c.card_id and "_r" not in c.card_id:
            return c.card_id
    raise AssertionError("コスト3以下のステージが見つからない")


def test_op03_096_main_choice_ko_stage_ai():
    """【メイン】choice: 相手コスト3以下ステージを KO (AI 自動、 cost0キャラ不在→ステージ枝)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get(_cheap_stage_id(repo)), sickness=False)
    opp.stages = [stage]

    on_main = _get_eff(overlay, "OP03-096", "main")
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])

    assert stage not in opp.stages, "相手コスト3以下ステージが KO されていない"


def test_op03_096_main_human_option_pick():
    """人間 actor: KO 対象の 2 枝を選ぶ option_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get(_cheap_stage_id(repo)), sickness=False)
    opp.stages = [stage]

    on_main = _get_eff(overlay, "OP03-096", "main")
    execute_effect(on_main["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + choice で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    options = st.pending_choice.get("options", [])
    assert len(options) == 2, f"選択肢が2枝でない: {len(options)}"
    resolve_pending_choice(st, [1])  # ステージ KO 枝
    _drain(st, [0])
    assert stage not in opp.stages, "人間が選んだステージ KO 枝が実行されていない"


def test_op03_096_trigger_draw2_ai():
    """【トリガー】カード2枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    on_trig = _get_eff(overlay, "OP03-096", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 2, f"2ドローで手札が+2でない: {len(me.hand)}"
    assert len(me.deck) == deck_before - 2, f"2ドローでデッキが-2でない: {len(me.deck)}"


# --------------------------------------------------------------------------- #
#  OP03-097 六王銃 (EVENT 黒):
#    【カウンター】自分の手札1枚を捨てることができる：自リーダーかキャラ1枚までを、
#      このバトル中、 パワー+3000。
#    【トリガー】カード1枚を引く。 その後、 相手のコスト1以下のキャラ1枚までを、 KO。
# --------------------------------------------------------------------------- #
def test_op03_097_counter_optional_pump_ai():
    """【カウンター】手札1捨て → 自リーダーを このバトル中 パワー+3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト
    me.characters = []  # target = 自リーダー のみ (self_inplay = リーダー+キャラ)
    power_before = me.leader.power

    on_counter = _get_eff(overlay, "OP03-097", "counter")
    for prim in on_counter["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert len(me.hand) == 0, "コストで手札1枚が捨てられていない"
    assert me.leader.power == power_before + 3000, \
        f"自リーダーに +3000 が反映されていない: {me.leader.power} (before {power_before})"


def test_op03_097_counter_no_hand_no_pump():
    """手札が無ければ 任意コスト不能 → パワー+3000 は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.characters = []
    power_before = me.leader.power

    on_counter = _get_eff(overlay, "OP03-097", "counter")
    for prim in on_counter["do"]:
        execute_effect(prim, st, me, opp, me.leader)

    assert me.leader.power == power_before, "手札が無いのに +3000 が起きている"


def test_op03_097_counter_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    me.characters = []
    power_before = me.leader.power

    on_counter = _get_eff(overlay, "OP03-097", "counter")
    execute_effect(on_counter["do"][0], st, me, opp, me.leader)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert me.leader.power == power_before + 3000, "人間承諾後 +3000 が反映されていない"


def test_op03_097_trigger_draw_and_ko_ai():
    """【トリガー】1ドロー + 相手コスト1以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    hand_before = len(me.hand)
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1 (<=1)
    opp.characters = [victim]

    on_trig = _get_eff(overlay, "OP03-097", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, f"1ドローが反映されていない: {len(me.hand)}"
    assert victim not in opp.characters, "相手コスト1以下キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-098 エニエス・ロビー (STAGE 黒 cost2):
#    【起動メイン】このステージをレストにできる：自リーダーが『CP』特徴の場合、
#      相手のキャラ1枚までを、 このターン中、 コスト-2。
# --------------------------------------------------------------------------- #
def test_op03_098_activate_main_cost_minus_ai():
    """【起動メイン】(リーダー CP) ステージをレスト → 相手キャラ1体 コスト-2 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP03-076", overlay)  # CP9 リーダー
    me, opp = st.players[0], st.players[1]
    stage = InPlay.of(repo.get("OP03-098"), sickness=False)
    me.stages = [stage]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4
    opp.characters = [victim]
    cost_before = victim.base_cost

    options = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in options if s.card.card_id == "OP03-098"]
    assert len(mine) == 1, f"OP03-098 の起動メインが legal に出ない: {len(mine)}"
    src, eff = mine[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])

    assert stage.rested is True, "起動コストでステージがレストになっていない"
    assert victim.base_cost == cost_before - 2, \
        f"相手キャラのコストが -2 されていない: {victim.base_cost} (before {cost_before})"


def test_op03_098_trigger_play_self_stage():
    """【トリガー】このステージを登場させる (= 現状 engine は STAGE 未対応)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP03-098")]
    st.current_source_card_id = "OP03-098"
    on_trig = _get_eff(overlay, "OP03-098", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-098"), sickness=True))
    assert any(s.card.card_id == "OP03-098" for s in me.stages), \
        "トリガーでステージが登場していない"


# --------------------------------------------------------------------------- #
#  OP03-100 キングバーム (CHARACTER 黄 cost3):
#    【トリガー】自ライフ1枚をトラッシュ (任意コスト) → このカードを登場。
# --------------------------------------------------------------------------- #
def test_op03_100_trigger_mill_life_play_ai():
    """【トリガー】自ライフ1トラッシュ → 自身を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    me.hand = [repo.get("OP03-100")]  # play_self 探索元 (hand)
    st.current_source_card_id = "OP03-100"
    life_before = len(me.life)
    trash_before = len(me.trash)

    on_trig = _get_eff(overlay, "OP03-100", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-100"), sickness=True))

    assert any(c.card.card_id == "OP03-100" for c in me.characters), \
        "トリガーで自身が登場していない"
    assert len(me.life) == life_before - 1, "自ライフが1枚トラッシュされていない"
    assert len(me.trash) == trash_before + 1, "トラッシュにライフ1枚が置かれていない"


def test_op03_100_trigger_no_life_no_play():
    """自ライフが無ければ 任意コスト不能 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    me.hand = [repo.get("OP03-100")]
    st.current_source_card_id = "OP03-100"

    on_trig = _get_eff(overlay, "OP03-100", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-100"), sickness=True))

    assert not any(c.card.card_id == "OP03-100" for c in me.characters), \
        "ライフが無いのに登場している"


def test_op03_100_trigger_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    me.hand = [repo.get("OP03-100")]
    st.current_source_card_id = "OP03-100"

    on_trig = _get_eff(overlay, "OP03-100", "trigger")
    execute_effect(on_trig["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-100"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card.card_id == "OP03-100" for c in me.characters), \
        "人間承諾後 自身が登場していない"


# --------------------------------------------------------------------------- #
#  OP03-102 サンジ (CHARACTER 黄 cost2):
#    【ドン!!×2】【アタック時】自ライフ上下1枚を手札に加える (任意コスト) →
#      自デッキ上1枚までを ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op03_102_on_attack_life_manip_ai():
    """【アタック時】(ドン2) 自ライフ1→手札 + デッキ上1→ライフ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    attacker = InPlay.of(repo.get("OP03-102"), sickness=False)
    attacker.attached_dons = 2
    me.characters = [attacker]
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    life_before = len(me.life)

    on_attack = _get_eff(overlay, "OP03-102", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 2, \
        "overlay の ドンゲート self_attached_don_ge=2 が無い"
    assert eval_condition(on_attack["if"], st, me) is True, \
        "テスト前提: ドン2で条件成立していない"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert len(me.hand) == hand_before + 1, "自ライフ1枚が手札に加わっていない"
    assert len(me.deck) == deck_before - 1, "デッキ上1枚がライフへ動いていない"
    # ライフ: -1 (手札へ) +1 (デッキから) = 差引 0
    assert len(me.life) == life_before, \
        f"ライフ枚数 (手札へ1 / デッキから1) の差引 0 が合わない: {len(me.life)}"


def test_op03_102_on_attack_don_gate_below_two():
    """ドン付与が2未満なら【アタック時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    attacker = InPlay.of(repo.get("OP03-102"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    on_attack = _get_eff(overlay, "OP03-102", "on_attack")
    assert eval_condition(on_attack["if"], st, me) is False, \
        "ドン1枚なのにドン2ゲートが成立している"


def test_op03_102_on_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    attacker = InPlay.of(repo.get("OP03-102"), sickness=False)
    attacker.attached_dons = 2
    me.characters = [attacker]

    on_attack = _get_eff(overlay, "OP03-102", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    _drain(st, [1])  # 承諾チェーンを解決 (crash しない)


# --------------------------------------------------------------------------- #
#  OP03-104 シャーリー (CHARACTER 黄 cost3):
#    【ブロッカー】【登場時】自分か相手のライフ上1枚までを見て、 ライフ上か下に置く。
# --------------------------------------------------------------------------- #
def test_op03_104_on_play_scry_ai():
    """【登場時】自/相手ライフを覗いて上下に置く scry (AI 自動、 crash せず枚数不変)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    opp.life = [repo.get("OP01-013")] * 3
    my_life_before = len(me.life)
    opp_life_before = len(opp.life)

    on_play = _get_eff(overlay, "OP03-104", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-104"), sickness=True))

    # scry は覗いて上下に戻すだけ → ライフ総枚数は不変
    assert len(me.life) == my_life_before, "scry で自ライフ枚数が変わっている"
    assert len(opp.life) == opp_life_before, "scry で相手ライフ枚数が変わっている"


def test_op03_104_intrinsic_blocker():
    """シャーリーは【ブロッカー】を印刷で持つ (is_blocker_now)。"""
    repo = _repo()
    shirley = InPlay.of(repo.get("OP03-104"), sickness=False)
    assert shirley.is_blocker_now is True, \
        "印刷ブロッカーが is_blocker_now に反映されていない"


# --------------------------------------------------------------------------- #
#  OP03-105 シャーロット・オーブン (CHARACTER 黄 cost3):
#    【ドン!!×1】【アタック時】手札から【トリガー】持ちカード1枚を捨てられる：
#      このキャラは、 このバトル中、 パワー+3000。
# --------------------------------------------------------------------------- #
def _trigger_card_id(repo):
    for c in repo._by_id.values():
        if getattr(c, "trigger", None) and "_p" not in c.card_id \
                and "_r" not in c.card_id:
            return c.card_id
    raise AssertionError("トリガー持ちカードが見つからない")


def test_op03_105_on_attack_pump_ai():
    """【アタック時】(ドン1) トリガー持ち手札1捨て → 自身 +3000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    trig_id = _trigger_card_id(repo)
    me.hand = [repo.get(trig_id)]
    attacker = InPlay.of(repo.get("OP03-105"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP03-105", "on_attack")
    assert on_attack.get("if", {}).get("self_attached_don_ge") == 1, \
        "overlay の ドンゲート self_attached_don_ge=1 が無い"
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)

    assert len(me.hand) == 0, "トリガー持ち手札1枚がコストで捨てられていない"
    assert attacker.power == power_before + 3000, \
        f"自身 +3000 が反映されていない: {attacker.power} (before {power_before})"


def test_op03_105_on_attack_don_gate_below_one():
    """ドン付与が無ければ【アタック時】条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    on_attack = _get_eff(overlay, "OP03-105", "on_attack")
    assert eval_condition(on_attack["if"], st, me) is False, \
        "ドン0枚なのにドン1ゲートが成立している"


def test_op03_105_on_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で +3000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    trig_id = _trigger_card_id(repo)
    me.hand = [repo.get(trig_id)]
    attacker = InPlay.of(repo.get("OP03-105"), sickness=False)
    attacker.attached_dons = 1
    me.characters = [attacker]
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP03-105", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert attacker.power == power_before + 3000, "人間承諾後 +3000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP03-108 シャーロット・クラッカー (CHARACTER 黄 cost4):
#    【トリガー】手札1枚を捨てられる：このカードを登場。
#    【ドン!!×1】自ライフが相手より少ない場合、【ダブルアタック】を得て パワー+1000。
# --------------------------------------------------------------------------- #
def test_op03_108_trigger_play_self_ai():
    """【トリガー】手札1捨て → 自身を登場 (AI 自動、 探索元はトラッシュ)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-108")]  # play_self 探索元 (trash 優先)
    me.hand = [repo.get("OP01-013")]   # 捨てるコスト (別カード)
    st.current_source_card_id = "OP03-108"

    on_trig = _get_eff(overlay, "OP03-108", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-108"), sickness=True))

    assert any(c.card.card_id == "OP03-108" for c in me.characters), \
        "トリガーで自身が登場していない"
    assert len(me.hand) == 0, "コストで手札1枚が捨てられていない"


def test_op03_108_trigger_no_hand_no_play():
    """手札が無ければ 任意コスト不能 → 登場しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP03-108")]
    me.hand = []
    st.current_source_card_id = "OP03-108"

    on_trig = _get_eff(overlay, "OP03-108", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-108"), sickness=True))

    assert not any(c.card.card_id == "OP03-108" for c in me.characters), \
        "手札が無いのに登場している"


def test_op03_108_on_attached_don_double_attack_ai():
    """【ドン!!×1】自ライフ<相手 → 【ダブルアタック】付与 + パワー+1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 1
    opp.life = [repo.get("OP01-013")] * 3
    chara = InPlay.of(repo.get("OP03-108"), sickness=False)
    chara.attached_dons = 1
    me.characters = [chara]
    power_before = chara.power

    on_don = _get_eff(overlay, "OP03-108", "on_attached_don")
    assert eval_condition(on_don["if"], st, me) is True, \
        "テスト前提: 自ライフ<相手 で条件成立していない"
    for prim in on_don["do"]:
        execute_effect(prim, st, me, opp, chara)

    assert "ダブルアタック" in getattr(chara, "granted_keywords", set()), \
        "【ダブルアタック】が付与されていない"
    assert chara.power == power_before + 1000, \
        f"パワー+1000 が反映されていない: {chara.power} (before {power_before})"


def test_op03_108_on_attached_don_condition_gate():
    """自ライフが相手以上なら【ドン!!×1】効果の条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    opp.life = [repo.get("OP01-013")] * 1
    on_don = _get_eff(overlay, "OP03-108", "on_attached_don")
    assert eval_condition(on_don["if"], st, me) is False, \
        "自ライフ>=相手なのに条件が成立している"
