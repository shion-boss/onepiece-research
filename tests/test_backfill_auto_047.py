# -*- coding: utf-8 -*-
"""OP04 (緑 ドンキホーテ海賊団 / 青 東の海・百獣 / 青黒黄 リーダー) 効果 回帰テスト
バックフィル (自動生成 wave 047):
OP04-034 / OP04-035 / OP04-036 / OP04-037 / OP04-038 /
OP04-039 / OP04-040 / OP04-041 / OP04-042 / OP04-043 の 10 枚。

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
    load_effect_overlay,
    resolve_pending_choice,
)

ROOT = Path(__file__).resolve().parent.parent

# ドンキホーテ海賊団 特徴を持つ LEADER (= 緑/紫 ドフラミンゴ OP04-019)。
DOFLA_LEADER = "OP04-019"


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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_wave47_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP04-034", "OP04-035", "OP04-036", "OP04-037", "OP04-038",
           "OP04-039", "OP04-040", "OP04-041", "OP04-042", "OP04-043"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP04-034 ラオG (CHARACTER 緑 cost4):
#    【自分のターン終了時】自分のアクティブのドン!!が3枚以上ある場合、
#      相手のレストのコスト3以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op04_034_end_of_turn_ko_rested_cost_le_3_ai():
    """【自分のターン終了時】アクティブドン3枚以上 → 相手レストcost3以下1枚KO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3  # アクティブドン3枚以上 (条件成立)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=3)
    victim.rested = True  # レスト状態が KO 対象条件
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-034", "end_of_turn")
    assert eval_condition(eff["if"], st, me) is True, \
        "アクティブドン3枚で条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-034"), sickness=False))
        _drain(st, [0])

    assert victim not in opp.characters, "相手のレストcost3以下キャラがKOされていない"
    assert any(c.card_id == "OP01-013" for c in opp.trash), \
        "KOされたキャラがトラッシュに置かれていない"


def test_op04_034_condition_false_when_active_don_lt_3():
    """アクティブドンが3枚未満なら条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.don_active = 2  # 3枚未満

    eff = _get_eff(overlay, "OP04-034", "end_of_turn")
    assert eval_condition(eff["if"], st, me) is False, \
        "アクティブドン2枚なのに条件が成立している"


def test_op04_034_no_ko_when_target_active():
    """相手キャラがアクティブなら KO 対象外 (レスト条件)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)
    victim.rested = False  # アクティブ = 対象外
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-034", "end_of_turn")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-034"), sickness=False))
        _drain(st, [0])

    assert victim in opp.characters, \
        "アクティブの相手キャラがKOされている (レスト制約が効いていない)"


def test_op04_034_human_ko_target_pick():
    """人間 actor: KO 対象の target_pick modal が立ち、 解決でKO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    v1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    v1.rested = True
    v2.rested = True  # 複数候補で modal
    opp.characters = [v1, v2]

    eff = _get_eff(overlay, "OP04-034", "end_of_turn")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-034"), sickness=False))

    assert st.pending_choice is not None, "人間 + KO 対象選択で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    assert len(opp.characters) == 1, "人間選択後 相手のレストキャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP04-035 蜘蛛の巣がき (EVENT 緑 cost2):
#    【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。
#      その後、自分のキャラ1枚までを、アクティブにする。
#    【トリガー】自分のリーダー1枚までを、このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op04_035_counter_pump_battle_4000_ai():
    """【カウンター】自リーダー(or キャラ)1枚 このバトル +4000 (AI 既定=最高パワー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _get_eff(overlay, "OP04-035", "counter", needle="power_pump")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 (このバトル) が自リーダーに反映されていない: {me.leader.power}"


def test_op04_035_counter_untap_chara_ai():
    """【カウンター】その後 自分のキャラ1枚をアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    friend.rested = True  # レスト状態 → アクティブ化対象
    me.characters = [friend]

    eff = _get_eff(overlay, "OP04-035", "counter", needle="untap_chara")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert friend.rested is False, "自分のキャラがアクティブにされていない"


def test_op04_035_trigger_pump_leader_2000_ai():
    """【トリガー】自リーダー1枚 このターン中 +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _get_eff(overlay, "OP04-035", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"トリガーの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op04_035_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +4000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    leader_before = me.leader.power
    friend_before = friend.power
    eff = _get_eff(overlay, "OP04-035", "counter", needle="power_pump")
    execute_effect(eff["do"][0], st, me, opp, None)
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert (me.leader.power == leader_before + 4000
            or friend.power == friend_before + 4000), \
        "人間が選んだ対象に +4000 (このバトル) が反映されていない"


# --------------------------------------------------------------------------- #
#  OP04-036 ドンキホーテファミリー (EVENT 緑 cost1):
#    【カウンター】自分のデッキの上から5枚を見て、特徴《ドンキホーテ海賊団》を持つカード
#      1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
#    【トリガー】このカードの【カウンター】効果を発動する。
# --------------------------------------------------------------------------- #
def test_op04_036_counter_search_donquixote_ai():
    """【カウンター】上5枚から《ドンキホーテ海賊団》1枚を手札に (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    # 上5枚に ドンキホーテ海賊団 (= OP04-034 ラオG) を混ぜる。
    me.deck = [repo.get("OP04-034")] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-036", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-036"), sickness=False))
        _drain(st, [0])
    assert any(c.card_id == "OP04-034" for c in me.hand), \
        "上5枚から《ドンキホーテ海賊団》カードが手札に加わっていない"


def test_op04_036_trigger_fires_counter():
    """【トリガー】fire_self_effect で【カウンター】効果 (サーチ) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP04-034")] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-036", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-036"), sickness=False))
        _drain(st, [0])
    assert any(c.card_id == "OP04-034" for c in me.hand), \
        "トリガー経由で カウンター効果 (サーチ) が発動していない"


def test_op04_036_counter_human_search_modal():
    """人間: 上5枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP04-034")] + [repo.get("OP01-013")] * 10
    me.hand = []

    eff = _get_eff(overlay, "OP04-036", "counter")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-036"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == "OP04-034" for c in me.hand), \
        "人間が選んだ《ドンキホーテ海賊団》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-037 羽撃糸 (EVENT 緑 cost2):
#    【カウンター】自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、
#      自分のリーダーかキャラ1枚までを、このターン中、パワー+2000。
#    【トリガー】相手のレストのコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op04_037_counter_condition_dofla_leader():
    """【カウンター】効果の if = ドンキホーテ海賊団 リーダー。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-037", "counter")
    st_ok = _state(repo, DOFLA_LEADER, overlay)
    assert eval_condition(eff["if"], st_ok, st_ok.players[0]) is True, \
        "ドフラリーダーで条件成立しない"
    st_ng = _state(repo, "OP01-001", overlay)
    assert eval_condition(eff["if"], st_ng, st_ng.players[0]) is False, \
        "非ドフラリーダーで条件が成立している"


def test_op04_037_counter_pump_2000_ai():
    """【カウンター】(ドフラリーダー) 自リーダー1枚 このターン +2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, DOFLA_LEADER, overlay)
    me, opp = st.players[0], st.players[1]

    power_before = me.leader.power
    eff = _get_eff(overlay, "OP04-037", "counter")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"


def test_op04_037_trigger_ko_rested_cost_le_4_ai():
    """【トリガー】相手のレストcost4以下キャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=4)
    victim.rested = True
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-037", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert victim not in opp.characters, "相手のレストcost4以下キャラがKOされていない"


# --------------------------------------------------------------------------- #
#  OP04-038 弱ェ奴は死に方も選べねェ!!! (EVENT 緑 cost5):
#    【メイン】/【カウンター】相手のリーダーかキャラ1枚までを、レストにする。
#      その後、相手のレストのコスト6以下のキャラ1枚までを、KOする。
#    【トリガー】自分のドン!!5枚までを、アクティブにする。
# --------------------------------------------------------------------------- #
def test_op04_038_counter_rest_opp_ai():
    """【カウンター】相手のリーダーかキャラ1枚をレスト (AI 自動、 相手キャラ不在→リーダー)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    assert opp.leader.rested is False

    eff = _get_eff(overlay, "OP04-038", "counter")
    # do[0] = rest one_opponent_inplay_any (相手キャラ不在なら相手リーダー)
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-038"), sickness=False))
    _drain(st, [0])
    assert opp.leader.rested is True, "相手リーダーがレストにされていない"


def test_op04_038_counter_ko_rested_cost_le_6_ai():
    """【カウンター】その後 相手のレストcost6以下キャラ1枚をKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=6)
    victim.rested = True  # 既にレスト → KO 対象
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-038", "counter")
    # do[1] = ko one_opponent_rested_character_cost_le_6cost
    execute_effect(eff["do"][1], st, me, opp,
                   InPlay.of(repo.get("OP04-038"), sickness=False))
    _drain(st, [0])
    assert victim not in opp.characters, "相手のレストcost6以下キャラがKOされていない"
    assert any(c.card_id == "OP01-013" for c in opp.trash), \
        "KOされたキャラがトラッシュに置かれていない"


def test_op04_038_trigger_untap_don_5_ai():
    """【トリガー】自分のドン!!5枚までをアクティブにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 6
    me.don_active = 0

    eff = _get_eff(overlay, "OP04-038", "trigger")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, None)
        _drain(st, [0])
    assert me.don_active == 5, f"レストドン5枚がアクティブになっていない: active={me.don_active}"
    assert me.don_rested == 1, f"レストドンが1枚残っていない: rested={me.don_rested}"


# --------------------------------------------------------------------------- #
#  OP04-039 レベッカ (LEADER 青/黒):
#    【起動メイン】【ターン1回】(ドン!!1レスト)：自分の手札が6枚以下の場合、
#      自分のデッキの上から2枚を見て、特徴《ドレスローザ》を持つカード1枚までを公開し、
#      手札に加える。その後、残りをトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op04_039_activate_main_search_dressrosa_ai():
    """【起動メイン】(手札6枚以下) 上2枚から《ドレスローザ》1枚を手札、 残りトラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-039", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []  # 6枚以下
    me.deck = [repo.get("EB03-048"), repo.get("OP01-013")] + [repo.get("OP01-013")] * 10
    trash_before = len(me.trash)

    eff = _get_eff(overlay, "OP04-039", "activate_main")
    assert eval_condition(eff["if"], st, me, me.leader) is True, \
        "手札6枚以下で条件が成立しない"
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
        _drain(st, [0])
    assert any(c.card_id == "EB03-048" for c in me.hand), \
        "上2枚から《ドレスローザ》カードが手札に加わっていない"
    assert len(me.trash) == trash_before + 1, \
        "残り1枚がトラッシュに置かれていない (rest_remain=trash)"


def test_op04_039_condition_false_when_hand_gt_6():
    """手札が7枚以上なら条件は不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-039", overlay)
    me = st.players[0]
    me.hand = [repo.get("OP01-013")] * 7  # 7枚 (> 6)

    eff = _get_eff(overlay, "OP04-039", "activate_main")
    assert eval_condition(eff["if"], st, me, me.leader) is False, \
        "手札7枚なのに条件が成立している"


def test_op04_039_activate_main_human_search_modal():
    """人間: 上2枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-039", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    me.deck = [repo.get("EB03-048"), repo.get("OP01-013")] + [repo.get("OP01-013")] * 10

    eff = _get_eff(overlay, "OP04-039", "activate_main")
    execute_effect(eff["do"][0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st, [0])
    assert any(c.card_id == "EB03-048" for c in me.hand), \
        "人間が選んだ《ドレスローザ》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-040 クイーン (LEADER 青/黄):
#    【ドン!!×1】【アタック時】自分のライフと手札の合計枚数が4枚以下の場合、カード1枚を引く。
#      自分のコスト8以上のキャラがいる場合、カード1枚を引く代わりに自分のデッキの上から
#      1枚までを、ライフの上に加えることができる。
# --------------------------------------------------------------------------- #
def test_op04_040_on_attack_condition_don_and_life_hand():
    """【アタック時】if = 付与ドン1以上 + ライフ+手札 4枚以下。"""
    repo = _repo()
    overlay = _overlay()
    eff = _get_eff(overlay, "OP04-040", "on_attack")
    st = _state(repo, "OP04-040", overlay)
    me = st.players[0]
    me.leader.attached_dons = 1
    me.life = [repo.get("OP01-013")] * 2
    me.hand = [repo.get("OP01-013")] * 2  # life+hand = 4 (<=4)
    assert eval_condition(eff["if"], st, me, me.leader) is True, \
        "付与ドン1 + ライフ手札4 で条件が成立しない"
    me.hand = [repo.get("OP01-013")] * 4  # life+hand = 6 (>4)
    assert eval_condition(eff["if"], st, me, me.leader) is False, \
        "ライフ手札6枚なのに条件が成立している"


def test_op04_040_on_attack_choice_draw_ai():
    """【アタック時】コスト8以上キャラ不在 → カード1枚を引く (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-040", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = []
    hand_before = len(me.hand)

    eff = _get_eff(overlay, "OP04-040", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp, me.leader)
        _drain(st, [0])
    assert len(me.hand) == hand_before + 1, \
        f"カード1枚を引いていない: hand={len(me.hand)}"


def test_op04_040_on_attack_choice_life_human():
    """人間 + コスト8以上キャラ有り → option_pick modal (引く / ライフ) が立ち、
    ライフ側を選ぶとデッキ上1枚がライフに加わる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP04-040", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.characters = [InPlay.of(repo.get("OP08-079"), sickness=False)]  # カイドウ cost9
    me.hand = []
    life_before = len(me.life)

    eff = _get_eff(overlay, "OP04-040", "on_attack")
    execute_effect(eff["do"][0], st, me, opp, me.leader)
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    # option 1 = デッキ上1枚をライフ
    resolve_pending_choice(st, [1])
    _drain(st, [0])
    assert len(me.life) == life_before + 1, \
        f"デッキ上1枚がライフに加わっていない: life={len(me.life)}"


# --------------------------------------------------------------------------- #
#  OP04-041 アピス (CHARACTER 青 cost1):
#    【登場時】自分の手札2枚を捨てることができる：自分のデッキの上から5枚を見て、
#      特徴《東の海》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな
#      順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op04_041_on_play_optional_cost_search_ai():
    """【登場時】手札2枚捨てて 上5枚から《東の海》1枚を手札 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]  # 捨てる用2枚
    me.deck = [repo.get("EB03-014")] + [repo.get("OP01-016")] * 10  # 東の海 くいな top
    hand_before = len(me.hand)

    on_play = _get_eff(overlay, "OP04-041", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-041"), sickness=False))
        _drain(st, [0])
    # 手札2枚捨て → 東の海1枚加える。 差し引き -2+1 = -1。
    assert any(c.card_id == "EB03-014" for c in me.hand), \
        "上5枚から《東の海》カードが手札に加わっていない"
    assert len(me.hand) == hand_before - 2 + 1, \
        f"手札枚数が想定 (捨2/加1) と違う: hand={len(me.hand)}"


def test_op04_041_on_play_no_fire_when_hand_insufficient():
    """手札が2枚未満なら任意コスト不能 → サーチは起きない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 1枚のみ (< 2)
    me.deck = [repo.get("EB03-014")] + [repo.get("OP01-016")] * 10

    on_play = _get_eff(overlay, "OP04-041", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-041"), sickness=False))
        _drain(st, [0])
    assert not any(c.card_id == "EB03-014" for c in me.hand), \
        "手札不足なのにサーチが発動している (コスト未払いで発火してはならない)"


def test_op04_041_on_play_human_optional_confirm():
    """人間 actor: 任意コスト → optional_cost_confirm modal が立ち、 承諾でサーチ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    apis = InPlay.of(repo.get("OP04-041"), sickness=False)
    me.characters = [apis]
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.deck = [repo.get("EB03-014")] + [repo.get("OP01-016")] * 10

    on_play = _get_eff(overlay, "OP04-041", "on_play")
    execute_effect(on_play["do"][0], st, me, opp, apis)
    assert st.pending_choice is not None, "人間 + 任意コストで確認 modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [1])  # 承諾
    _drain(st, [0])
    assert any(c.card_id == "EB03-014" for c in me.hand), \
        "人間承諾後 《東の海》カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP04-042 いっぽんマツ (CHARACTER 青 cost2):
#    【登場時】自分の属性(斬)を持つキャラ1枚までを、このターン中、パワー+3000。
#      その後、自分のデッキの上から1枚をトラッシュに置く。
# --------------------------------------------------------------------------- #
def test_op04_042_on_play_pump_zan_and_mill_ai():
    """【登場時】自属性(斬)キャラ1枚 このターン +3000 + デッキ上1枚トラッシュ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    zan = InPlay.of(repo.get("EB02-026"), sickness=False)  # ネフェルタリ・ビビ (斬)
    assert zan.card.attribute == "斬"
    me.characters = [zan]
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 10
    power_before = zan.power
    trash_before = len(me.trash)

    on_play = _get_eff(overlay, "OP04-042", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-042"), sickness=False))
        _drain(st, [0])
    assert zan.power == power_before + 3000, \
        f"自属性(斬)キャラに +3000 が反映されていない: {zan.power}"
    assert len(me.trash) == trash_before + 1, \
        "デッキ上1枚がトラッシュに置かれていない"


def test_op04_042_on_play_no_pump_when_no_zan():
    """自属性(斬)キャラがいなければ pump 対象なし (mill のみ発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    non_zan = InPlay.of(repo.get("OP01-013"), sickness=False)  # 打 属性 (斬でない)
    me.characters = [non_zan]
    me.deck = [repo.get("OP01-016")] + [repo.get("OP01-013")] * 10
    power_before = non_zan.power
    trash_before = len(me.trash)

    on_play = _get_eff(overlay, "OP04-042", "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-042"), sickness=False))
        _drain(st, [0])
    assert non_zan.power == power_before, \
        "斬でないキャラに +3000 が付いている (属性フィルタが効いていない)"
    assert len(me.trash) == trash_before + 1, "デッキ上1枚のトラッシュは常に発火する"


# --------------------------------------------------------------------------- #
#  OP04-043 うるティ (CHARACTER 青 cost3):
#    【ドン!!×1】【アタック時】コスト2以下のキャラ1枚までを、持ち主の手札かデッキの下に戻す。
# --------------------------------------------------------------------------- #
def test_op04_043_on_attack_return_cost_le_2_ai():
    """【アタック時】相手のコスト2以下キャラ1枚を 手札/デッキ下 に戻す (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3  # heuristic life_count>=3 → option0 (手札に戻す)
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2 (<=2)
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-043", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-043"), sickness=False))
        _drain(st, [0])
    assert victim not in opp.characters, "相手のコスト2以下キャラが場から戻されていない"
    assert any(c.card_id == "OP01-013" for c in opp.hand), \
        "戻したキャラが持ち主の手札に加わっていない (option0=手札)"


def test_op04_043_on_attack_no_target_cost_gt_2():
    """相手キャラがコスト3以上なら対象外 → 戻されない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3
    victim = InPlay.of(repo.get("OP04-034"), sickness=False)  # cost4 (対象外)
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-043", "on_attack")
    for prim in eff["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP04-043"), sickness=False))
        _drain(st, [0])
    assert victim in opp.characters, \
        "コスト4のキャラが戻されている (コスト2以下制約が効いていない)"


def test_op04_043_on_attack_human_choice_modal():
    """人間 actor: 「手札に戻すか / デッキ下に戻すか」 の option_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # cost2
    opp.characters = [victim]

    eff = _get_eff(overlay, "OP04-043", "on_attack")
    execute_effect(eff["do"][0], st, me, opp,
                   InPlay.of(repo.get("OP04-043"), sickness=False))
    assert st.pending_choice is not None, "人間で 手札/デッキ下 の選択 modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 手札に戻す
    _drain(st, [0])
    assert victim not in opp.characters, "人間選択後 相手キャラが場から戻されていない"
