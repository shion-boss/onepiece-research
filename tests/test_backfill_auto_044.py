# -*- coding: utf-8 -*-
"""OP03 (黄) + OP04 (赤 アラバスタ王国) 効果 回帰テスト バックフィル (自動生成 wave 044):
OP03-120 / OP03-121 / OP03-122 / OP03-123 / OP04-002 / OP04-003 /
OP04-004 / OP04-005 / OP04-006 / OP04-009 の 10 枚。

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
    evaluate_static_effects,
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


def _arabasta_char_id(repo, exclude=()):
    """特徴《アラバスタ王国》を持つ CHARACTER (パラレル/レア除外) を1つ返す。"""
    for c in repo._by_id.values():
        if c.category.name == "CHARACTER" \
                and "アラバスタ王国" in (c.features or ()) \
                and "_p" not in c.card_id and "_r" not in c.card_id \
                and c.card_id not in exclude:
            return c.card_id
    raise AssertionError("アラバスタ王国 特徴キャラが見つからない")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave44_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP03-120", "OP03-121", "OP03-122", "OP03-123", "OP04-002",
           "OP04-003", "OP04-004", "OP04-005", "OP04-006", "OP04-009"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP03-120 熱海温泉 (EVENT 黄 cost3):
#    【メイン】相手のライフが4枚以上の場合、 相手のライフの上から1枚までを、 トラッシュに置く。
#    【トリガー】このカードの【メイン】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op03_120_main_mill_when_opp_life_ge4_ai():
    """【メイン】(相手ライフ4+) 相手ライフ上1→トラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 4
    opp_life_before = len(opp.life)
    opp_trash_before = len(opp.trash)

    on_main = _get_eff(overlay, "OP03-120", "main")
    assert on_main.get("if", {}).get("opp_life_ge") == 4, \
        "overlay の 相手ライフ4以上 条件が無い"
    assert eval_condition(on_main["if"], st, me) is True, \
        "テスト前提: 相手ライフ4+ で条件成立していない"
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-120"), sickness=True))

    assert len(opp.life) == opp_life_before - 1, "相手ライフが1枚減っていない"
    assert len(opp.trash) == opp_trash_before + 1, \
        "相手ライフがトラッシュに置かれていない"


def test_op03_120_main_condition_false_opp_life_lt4():
    """相手ライフが3枚以下なら【メイン】条件は不成立 (= 発動しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 3
    on_main = _get_eff(overlay, "OP03-120", "main")
    assert eval_condition(on_main["if"], st, me) is False, \
        "相手ライフ3枚なのに条件が成立している"


def test_op03_120_trigger_fires_main_ai():
    """【トリガー】自身の【メイン】効果を再発火 (相手ライフ4+ → -1、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 4
    opp_life_before = len(opp.life)
    st.current_source_card_id = "OP03-120"

    on_trig = _get_eff(overlay, "OP03-120", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-120"), sickness=True))

    assert len(opp.life) == opp_life_before - 1, \
        "トリガーで【メイン】が再発火し相手ライフが1枚減っていない"


# --------------------------------------------------------------------------- #
#  OP03-121 雷霆 (EVENT 黄 cost2):
#    【メイン】自分のライフの上から1枚をトラッシュに置くことができる：
#      相手のコスト5以下のキャラ1枚までを、 KOする。
#    【トリガー】相手のコスト5以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op03_121_main_optcost_ko_ai():
    """【メイン】(任意) 自ライフ1→トラッシュ → 相手コスト5以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=5)
    opp.characters = [victim]
    life_before = len(me.life)
    trash_before = len(me.trash)

    on_main = _get_eff(overlay, "OP03-121", "main")
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-121"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, "相手コスト5以下キャラが KO されていない"
    assert len(me.life) == life_before - 1, "コストで自ライフが1枚減っていない"
    assert len(me.trash) == trash_before + 1, "自ライフがトラッシュに置かれていない"


def test_op03_121_main_no_life_no_ko():
    """自ライフが無ければ 任意コスト不能 → KO は起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = []
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_main = _get_eff(overlay, "OP03-121", "main")
    for prim in on_main["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-121"), sickness=True))
        _drain(st, [0])

    assert victim in opp.characters, \
        "自ライフが無いのに KO が起きている (コスト未払いで発火してはならない)"


def test_op03_121_trigger_ko_ai():
    """【トリガー】相手コスト5以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    on_trig = _get_eff(overlay, "OP03-121", "trigger")
    for prim in on_trig["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-121"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, "トリガーで相手キャラが KO されていない"


def test_op03_121_main_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 2
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_main = _get_eff(overlay, "OP03-121", "main")
    execute_effect(on_main["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-121"), sickness=True))

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert victim not in opp.characters, "人間承諾後 相手キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP03-122 そげキング (CHARACTER 青 cost7):
#    【登場時】コスト6以下のキャラ1枚までを、 持ち主の手札に戻す。
#      その後、 カード2枚を引き、 自分の手札2枚を捨てる。
# --------------------------------------------------------------------------- #
def test_op03_122_on_play_bounce_draw_discard_ai():
    """【登場時】相手コスト6以下キャラを手札へ戻す + 2ドロー + 手札2捨て (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=6)
    opp.characters = [victim]
    opp_hand_before = len(opp.hand)
    deck_before = len(me.deck)

    on_play = _get_eff(overlay, "OP03-122", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-122"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, "コスト6以下キャラが場から戻されていない"
    assert len(opp.hand) == opp_hand_before + 1, "戻したキャラが持ち主の手札に加わっていない"
    # 2ドロー → デッキ -2、 空手札から 2 引き 2 捨て = 手札 0
    assert len(me.deck) == deck_before - 2, f"2ドローでデッキが-2でない: {len(me.deck)}"
    assert len(me.hand) == 0, f"2ドロー-2捨てで手札が0でない: {len(me.hand)}"


def test_op03_122_on_play_human_target_pick():
    """人間 actor: 手札に戻す対象の target_pick modal が立ち、 解決で bounce。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-122", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-122"), sickness=True))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭候補を戻す
    assert victim not in opp.characters, "人間選択後 対象キャラが場から戻されていない"


# --------------------------------------------------------------------------- #
#  OP03-123 シャーロット・カタクリ (CHARACTER 黄 cost8):
#    【登場時】コスト8以下のキャラ1枚までを、 持ち主のライフの上か下に表向きで加える。
# --------------------------------------------------------------------------- #
def test_op03_123_on_play_chara_to_life_ai():
    """【登場時】相手コスト8以下キャラを 持ち主ライフへ (= 場から除去、 AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)  # ウタ cost4 (<=8)
    opp.characters = [victim]
    opp_life_before = len(opp.life)

    on_play = _get_eff(overlay, "OP03-123", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP03-123"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, "相手コスト8以下キャラが場から除去されていない"
    assert len(opp.life) == opp_life_before + 1, "除去キャラが持ち主ライフに加わっていない"


def test_op03_123_on_play_human_target_pick():
    """人間 actor: ライフに加える対象の target_pick modal が立ち、 解決で除去。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-005"), sickness=False)
    opp.characters = [victim]

    on_play = _get_eff(overlay, "OP03-123", "on_play")
    execute_effect(on_play["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP03-123"), sickness=True))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert victim not in opp.characters, "人間選択後 対象キャラが除去されていない"


# --------------------------------------------------------------------------- #
#  OP04-002 イガラム (CHARACTER 赤 cost2):
#    【起動メイン】このキャラをレストにし、 自分のアクティブのリーダー1枚を、 このターン中、
#      パワー-5000することができる：自分のデッキの上から5枚を見て、 特徴《アラバスタ王国》を
#      持つカード1枚までを公開し、 手札に加える。 その後、 残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_002_activate_main_search_arabasta_ai():
    """【起動メイン】自レスト + リーダー-5000 → デッキ上5から アラバスタ王国 を手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    igaram = InPlay.of(repo.get("OP04-002"), sickness=False)
    me.characters = [igaram]
    arab_id = _arabasta_char_id(repo, exclude=("OP04-002",))
    me.deck = [repo.get(arab_id)] + [repo.get("OP01-013")] * 10  # 先頭に アラバスタ王国
    leader_power_before = me.leader.power

    options = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in options if s.card.card_id == "OP04-002"]
    assert len(mine) == 1, f"OP04-002 の起動メインが legal に出ない: {len(mine)}"
    src, eff = mine[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])

    assert igaram.rested is True, "起動コストでイガラムがレストになっていない"
    assert me.leader.power == leader_power_before - 5000, \
        f"リーダー-5000 が反映されていない: {me.leader.power} (before {leader_power_before})"
    assert any(c.card_id == arab_id for c in me.hand), \
        "デッキ上5枚から アラバスタ王国 カードが手札に加わっていない"


def test_op04_002_activate_main_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    igaram = InPlay.of(repo.get("OP04-002"), sickness=False)
    me.characters = [igaram]
    arab_id = _arabasta_char_id(repo, exclude=("OP04-002",))
    me.deck = [repo.get(arab_id)] + [repo.get("OP01-013")] * 10

    on_act = _get_eff(overlay, "OP04-002", "activate_main")
    execute_effect(on_act["do"][0], st, me, opp, igaram)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card_id == arab_id for c in me.hand), \
        "人間承諾後 アラバスタ王国 カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-003 ウソップ (CHARACTER 赤 cost4):
#    【KO時】相手の元々のパワーが5000以下のキャラ1枚までを、 KOする。
# --------------------------------------------------------------------------- #
def test_op04_003_on_ko_ko_low_power_ai():
    """【KO時】相手の元々パワー5000以下キャラを KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ 元々2000 (<=5000)
    opp.characters = [victim]

    on_ko = _get_eff(overlay, "OP04-003", "on_ko")
    for prim in on_ko["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-003"), sickness=True))
        _drain(st, [0])

    assert victim not in opp.characters, \
        "相手の元々パワー5000以下キャラが KO されていない"


def test_op04_003_on_ko_human_target_pick():
    """人間 actor: KO 対象の target_pick modal が立ち、 解決で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    on_ko = _get_eff(overlay, "OP04-003", "on_ko")
    execute_effect(on_ko["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-003"), sickness=True))

    assert st.pending_choice is not None, "人間 + 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert victim not in opp.characters, "人間選択後 対象キャラが KO されていない"


# --------------------------------------------------------------------------- #
#  OP04-004 カルー (CHARACTER 赤 cost1):
#    【起動メイン】このキャラをレストにできる：自分の特徴《アラバスタ王国》を持つキャラ
#      すべてにレストのドン!!1枚ずつまでを、 付与する。
# --------------------------------------------------------------------------- #
def test_op04_004_activate_main_attach_don_all_arabasta_ai():
    """【起動メイン】自レスト → 自 アラバスタ王国 キャラ全てに レストドン1枚付与 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    karoo = InPlay.of(repo.get("OP04-004"), sickness=False)   # アラバスタ王国
    koza = InPlay.of(repo.get("OP04-006"), sickness=False)    # アラバスタ王国
    me.characters = [karoo, koza]
    me.don_rested = 5
    karoo_don_before = karoo.attached_dons
    koza_don_before = koza.attached_dons

    options = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in options if s.card.card_id == "OP04-004"]
    assert len(mine) == 1, f"OP04-004 の起動メインが legal に出ない: {len(mine)}"
    src, eff = mine[0]
    fire_activate_main(st, me, opp, src, eff)
    _drain(st, [0])

    assert karoo.rested is True, "起動コストでカルーがレストになっていない"
    assert karoo.attached_dons == karoo_don_before + 1, \
        f"カルーに レストドン1枚が付与されていない: {karoo.attached_dons}"
    assert koza.attached_dons == koza_don_before + 1, \
        f"コーザに レストドン1枚が付与されていない: {koza.attached_dons}"


# --------------------------------------------------------------------------- #
#  OP04-005 クンフージュゴン (CHARACTER 赤 cost1):
#    このキャラ以外の自分の「クンフージュゴン」がいる場合、 このキャラは【ブロッカー】を得る。
# --------------------------------------------------------------------------- #
def test_op04_005_static_blocker_when_two_present():
    """自「クンフージュゴン」が2枚以上いる場合、 各々が【ブロッカー】を得る (静的)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    a = InPlay.of(repo.get("OP04-005"), sickness=False)
    b = InPlay.of(repo.get("OP04-005"), sickness=False)
    me.characters = [a, b]

    evaluate_static_effects(st, overlay)

    assert "ブロッカー" in a.static_granted_keywords, \
        "2枚存在時に 1枚目が ブロッカー を得ていない"
    assert "ブロッカー" in b.static_granted_keywords, \
        "2枚存在時に 2枚目が ブロッカー を得ていない"


def test_op04_005_static_no_blocker_when_alone():
    """自「クンフージュゴン」が1枚だけなら【ブロッカー】を得ない (条件不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    a = InPlay.of(repo.get("OP04-005"), sickness=False)
    me.characters = [a]

    evaluate_static_effects(st, overlay)

    assert "ブロッカー" not in a.static_granted_keywords, \
        "1枚だけなのに ブロッカー を得ている (条件不成立のはず)"


# --------------------------------------------------------------------------- #
#  OP04-006 コーザ (CHARACTER 赤 cost3):
#    【アタック時】自分のアクティブのリーダー1枚を、 このターン中、 パワー-5000することが
#      できる：このキャラは、 次の自分のターン開始時まで、 パワー+2000。
# --------------------------------------------------------------------------- #
def test_op04_006_on_attack_optcost_self_pump_ai():
    """【アタック時】(任意) リーダー-5000 → 自身 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-006"), sickness=False)
    me.characters = [attacker]
    leader_power_before = me.leader.power
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP04-006", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)
        _drain(st, [0])

    assert me.leader.power == leader_power_before - 5000, \
        f"コストでリーダー-5000 が反映されていない: {me.leader.power}"
    assert attacker.power == power_before + 2000, \
        f"自身 +2000 が反映されていない: {attacker.power} (before {power_before})"


def test_op04_006_on_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-006"), sickness=False)
    me.characters = [attacker]
    power_before = attacker.power

    on_attack = _get_eff(overlay, "OP04-006", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert attacker.power == power_before + 2000, "人間承諾後 +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP04-009 超カルガモ部隊 (CHARACTER 赤 cost2):
#    【アタック時】自分のアクティブのリーダー1枚を、 このターン中、 パワー-5000することが
#      できる：このターン終了時、 このキャラを持ち主の手札に戻す。
# --------------------------------------------------------------------------- #
def test_op04_009_on_attack_optcost_schedule_return_ai():
    """【アタック時】(任意) リーダー-5000 → このターン終了時に自身を手札へ戻す予約 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-009"), sickness=False)
    me.characters = [attacker]
    leader_power_before = me.leader.power

    on_attack = _get_eff(overlay, "OP04-009", "on_attack")
    for prim in on_attack["do"]:
        execute_effect(prim, st, me, opp, attacker)
        _drain(st, [0])

    assert me.leader.power == leader_power_before - 5000, \
        f"コストでリーダー-5000 が反映されていない: {me.leader.power}"
    scheduled = getattr(me, "scheduled_at_self_turn_end", [])
    assert any("return_self_to_hand" in str(entry) for entry in scheduled), \
        f"ターン終了時の 自身手札戻し が予約されていない: {scheduled}"


def test_op04_009_on_attack_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾で予約。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    attacker = InPlay.of(repo.get("OP04-009"), sickness=False)
    me.characters = [attacker]

    on_attack = _get_eff(overlay, "OP04-009", "on_attack")
    execute_effect(on_attack["do"][0], st, me, opp, attacker)

    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    scheduled = getattr(me, "scheduled_at_self_turn_end", [])
    assert any("return_self_to_hand" in str(entry) for entry in scheduled), \
        f"人間承諾後 自身手札戻しが予約されていない: {scheduled}"
