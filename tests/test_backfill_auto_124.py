# -*- coding: utf-8 -*-
"""OP12 弾 (黄 超新星 / 空島シャンドラ / ハートの海賊団 系) 効果 回帰テスト
バックフィル (自動生成 wave 124):
OP12-101 / OP12-102 / OP12-104 / OP12-105 / OP12-107 /
OP12-108 / OP12-109 / OP12-113 / OP12-115 / OP12-116 の 10 枚。

目的 (= test_backfill_auto_001〜123.py と同一方針):
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
    resolve_triggers,
    evaluate_static_effects,
    execute_effect,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    resolve_pending_choice,
    trigger_counter_event,
    trigger_on_ko,
    trigger_on_play,
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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, entry) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _drain(st, guard=14):
    """pending_choice を種別ごとに適切に選び続けて解決しきる。"""
    g = 0
    while st.pending_choice is not None and g < guard:
        kind = st.pending_choice.get("kind", "")
        if kind in ("optional_cost_confirm", "reveal_top_play_confirm",
                    "replace_ko_optional"):
            resolve_pending_choice(st, [1])
        else:
            cands = (st.pending_choice.get("candidates")
                     or st.pending_choice.get("cards")
                     or st.pending_choice.get("options") or [])
            resolve_pending_choice(st, [0] if len(cands) > 0 else [])
        g += 1


# 定番 leader / helper カード
_NEUTRAL = "OP12-081"       # コアラ (黒/黄、 features ドレスローザ/革命軍 = 超新星でない)
_SS_LEADER = "OP07-019"     # ジュエリー・ボニー (超新星/ボニー海賊団)
_LAW_LEADER = "OP01-002"    # トラファルガー・ロー (leader、 name = トラファルガー・ロー)
_VICTIM = "OP01-016"        # ナミ (麦わらの一味 cost1 pow2000 CHARACTER)
_FILLER = "OP01-013"        # サンジ (麦わらの一味 cost2 pow3000 CHARACTER)
_BIG6 = "OP12-087"          # ニコ・ロビン (cost6 pow7000 CHARACTER)
_LAW_C1 = "OP09-069"        # トラファルガー・ロー (CHARACTER cost1 pow2000)
_SS_C4 = "PRB02-006"        # ロロノア・ゾロ (cost4 超新星/麦わらの一味 CHARACTER)
_KAIOU = "OP11-027"         # ギョロ目 (cost4 pow6000 CHARACTER, features 海王類)
_SHANDIA = "OP15-101"       # カルガラ (cost3 CHARACTER, features 空島/シャンドラの戦士)
_COST4 = "OP11-027"         # ギョロ目 (cost4) = KO 対象 (<=4)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op12_wave124_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP12-101", "OP12-102", "OP12-104", "OP12-105", "OP12-107",
           "OP12-108", "OP12-109", "OP12-113", "OP12-115", "OP12-116"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP12-101 ジュエリー・ボニー (CHARACTER 黄 cost3 pow1000):
#    【起動メイン】このキャラをレストにできる：自分の特徴《超新星》を持つリーダーは、
#      次の相手のターン終了時まで、パワー+1000。
# --------------------------------------------------------------------------- #
def test_op12_101_activate_main_pump_ss_leader_ai():
    """起動メイン: 自身をレスト (コスト) → 超新星 leader が +1000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SS_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    boni = InPlay.of(repo.get("OP12-101"), sickness=False)
    me.characters = [boni]

    power_before = me.leader.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-101"]
    assert len(opts) == 1, \
        f"OP12-101 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])
    _drain(st)

    assert me.leader.power == power_before + 1000, \
        f"超新星 leader への +1000 が反映されていない: {me.leader.power}"
    assert boni.rested is True, "起動メインコストで ボニー がレストされるべき"


def test_op12_101_activate_main_not_legal_when_not_ss_leader():
    """負例: 非超新星 leader なら 起動メインの do 条件不成立で pump が乗らない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    boni = InPlay.of(repo.get("OP12-101"), sickness=False)
    me.characters = [boni]

    power_before = me.leader.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP12-101"]
    # 起動メイン自体は legal に出うるが、 do の if(leader_feature=超新星) が不成立
    if opts:
        fire_activate_main(st, me, opp, *opts[0])
        _drain(st)
    assert me.leader.power == power_before, \
        "非超新星 leader で pump が乗ってはいけない"


# --------------------------------------------------------------------------- #
#  OP12-102 しらほし (CHARACTER 黄 cost2 pow-):
#    【相手のターン中】自分の他の元々コスト2の「しらほし」がいない場合、
#      自分の特徴《海王類》を持つキャラすべてのパワー+2000。 (静的)
#    replace_leave: 自元々cost6以下が相手効果で離れる → 代わりに自ライフ上1枚を表向き。
# --------------------------------------------------------------------------- #
def test_op12_102_static_kaiou_pump_on_opp_turn():
    """静的: 相手ターン中 + 他 cost2しらほし不在 → 自 海王類 キャラ +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    shirahoshi = InPlay.of(repo.get("OP12-102"), sickness=False)
    gyoro = InPlay.of(repo.get(_KAIOU), sickness=False)  # 海王類 pow6000
    me.characters = [shirahoshi, gyoro]

    gyoro_base = repo.get(_KAIOU).power
    evaluate_static_effects(st, overlay)

    assert gyoro.power == gyoro_base + 2000, \
        f"相手ターン中に 海王類 キャラ +2000 が反映されていない: {gyoro.power}"


def test_op12_102_static_no_pump_on_self_turn():
    """負例: 自分のターン中は【相手のターン中】条件不成立 → 海王類 pump なし。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    shirahoshi = InPlay.of(repo.get("OP12-102"), sickness=False)
    gyoro = InPlay.of(repo.get(_KAIOU), sickness=False)
    me.characters = [shirahoshi, gyoro]

    gyoro_base = repo.get(_KAIOU).power
    evaluate_static_effects(st, overlay)

    assert gyoro.power == gyoro_base, \
        f"自分のターン中に 海王類 pump が乗ってはいけない: {gyoro.power}"


def test_op12_102_replace_leave_flip_life():
    """replace_leave の do (flip_life_face_up_effect 1) を発火 → 自ライフ上1枚が表向き。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3
    me.face_up_life_count = 0

    do, _ = _do(overlay, "OP12-102", "replace_leave")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert me.face_up_life_count == 1, \
        f"replace_leave で自ライフ上1枚が表向きになっていない: {me.face_up_life_count}"


# --------------------------------------------------------------------------- #
#  OP12-104 戦桃丸 (CHARACTER 黄 cost4 pow5000):
#    【トリガー】相手のコスト4以下のキャラ1枚までを、KOする。
# --------------------------------------------------------------------------- #
def test_op12_104_trigger_ko_cost_le_4_ai():
    """【トリガー】 相手コスト4以下キャラを KO、 cost6 は対象外で残る (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_COST4), sickness=False)  # cost4 (<=4)
    big = InPlay.of(repo.get(_BIG6), sickness=False)      # cost6 (対象外)
    opp.characters = [small, big]

    do, _ = _do(overlay, "OP12-104", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert small not in opp.characters, "コスト4以下の相手キャラが KO されていない"
    assert big in opp.characters, "コスト6の相手キャラは KO 対象外で残るべき"


def test_op12_104_trigger_ko_human_pick():
    """人間 + コスト4以下の相手キャラ複数 → target_pick modal が立ち resolve で KO。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get(_COST4), sickness=False)   # cost4
    b = InPlay.of(repo.get(_FILLER), sickness=False)  # cost2
    opp.characters = [a, b]

    do, _ = _do(overlay, "OP12-104", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain(st)
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  OP12-105 トラファルガー・ラミ (CHARACTER 黄 cost1 pow-):
#    【自分のターン中】【登場時】自分の「トラファルガー・ロー」1枚までを、
#      このターン中、パワー+2000。
# --------------------------------------------------------------------------- #
def test_op12_105_on_play_pump_law_ai():
    """【登場時】 自ターン中 → 自「トラファルガー・ロー」に +2000 (AI 単一候補で自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    lami = InPlay.of(repo.get("OP12-105"), sickness=True)
    law = InPlay.of(repo.get(_LAW_C1), sickness=False)  # ロー pow2000
    me.characters = [law, lami]

    law_before = law.power
    trigger_on_play(st, me, opp, lami, overlay)
    _drain(st)

    assert law.power == law_before + 2000, \
        f"登場時 ロー への +2000 が反映されていない: {law.power} (before {law_before})"


def test_op12_105_on_play_pump_human_pick():
    """人間 + ロー 複数 (leader=ロー + キャラ ロー) → target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _LAW_LEADER, overlay, human_idx=0)  # leader = ロー
    me, opp = st.players[0], st.players[1]
    lami = InPlay.of(repo.get("OP12-105"), sickness=True)
    law = InPlay.of(repo.get(_LAW_C1), sickness=False)
    me.characters = [law, lami]

    trigger_on_play(st, me, opp, lami, overlay)

    assert st.pending_choice is not None, "人間 + ロー 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ロー leader + ロー キャラ) が 2 件でない: {len(cands)}"
    law_idx = next(i for i, c in enumerate(cands) if c["iid"] == law.instance_id)
    law_before = law.power
    resolve_pending_choice(st, [law_idx])
    _drain(st)
    assert law.power == law_before + 2000, \
        "人間が選んだ ロー キャラに +2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP12-107 ドンキホーテ・ドフラミンゴ (CHARACTER 黄 cost8 pow8000):
#    静的: 自ライフ2枚以下 → このキャラは【速攻】を得る。
#    【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフの上に加える。
# --------------------------------------------------------------------------- #
def test_op12_107_static_rush_when_life_le_2():
    """静的: 自ライフ2枚以下 → 【速攻】を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP12-107"), sickness=False)
    me.characters = [dofla]
    me.life = [repo.get(_FILLER)] * 2  # 2枚以下 = 条件成立

    evaluate_static_effects(st, overlay)
    assert dofla.is_rush_now is True, "自ライフ2枚以下で【速攻】を得ていない"


def test_op12_107_static_no_rush_when_life_high():
    """負例: 自ライフ4枚 → 【速攻】を得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    dofla = InPlay.of(repo.get("OP12-107"), sickness=False)
    me.characters = [dofla]
    me.life = [repo.get(_FILLER)] * 4  # 4枚 = 条件不成立

    evaluate_static_effects(st, overlay)
    assert dofla.is_rush_now is False, "ライフ4枚で【速攻】を得てはいけない"


def test_op12_107_on_ko_put_top_to_life_on_opp_turn():
    """【相手のターン中】【KO時】 デッキ上1枚をライフの上に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 1  # 相手ターン (= opp_turn 条件成立)
    me.deck = [repo.get(_FILLER)] * 10
    me.life = [repo.get(_FILLER)] * 2

    deck_before = len(me.deck)
    life_before = len(me.life)
    trigger_on_ko(st, me, opp, repo.get("OP12-107"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert len(me.life) == life_before + 1, "KO時にデッキ上1枚がライフに加わっていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減るべき"


def test_op12_107_on_ko_no_effect_on_self_turn():
    """負例: 自分のターン中は【相手のターン中】条件不成立 → ライフに加わらない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    st.turn_player_idx = 0  # 自分のターン → opp_turn False
    me.deck = [repo.get(_FILLER)] * 10
    me.life = [repo.get(_FILLER)] * 2

    life_before = len(me.life)
    trigger_on_ko(st, me, opp, repo.get("OP12-107"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert len(me.life) == life_before, "自ターンで KO時効果が発火してはいけない"


# --------------------------------------------------------------------------- #
#  OP12-108 ドンキホーテ・ロシナンテ (CHARACTER 黄 cost1 pow2000):
#    【登場時】自分のデッキの上から5枚を見て、「トラファルガー・ロー」1枚までを
#      公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。
# --------------------------------------------------------------------------- #
def test_op12_108_on_play_search_law_ai():
    """【登場時】 デッキ上5枚から ロー を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    rosi = InPlay.of(repo.get("OP12-108"), sickness=True)
    me.characters = [rosi]
    me.deck = [repo.get(_LAW_C1)] + [repo.get(_FILLER)] * 10
    me.hand = []

    trigger_on_play(st, me, opp, rosi, overlay)
    _drain(st)

    assert any(c.card_id == _LAW_C1 for c in me.hand), \
        f"デッキ上5枚から ロー が手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op12_108_on_play_search_human_modal():
    """人間 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    rosi = InPlay.of(repo.get("OP12-108"), sickness=True)
    me.characters = [rosi]
    me.deck = [repo.get(_LAW_C1), repo.get(_FILLER), repo.get(_LAW_C1)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    trigger_on_play(st, me, opp, rosi, overlay)

    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _LAW_C1 for c in me.hand), \
        "人間が選んだ ロー が手札に加わっていない"


# --------------------------------------------------------------------------- #
#  OP12-109 パシフィスタ (CHARACTER 黄 cost4 pow5000):
#    【トリガー】相手のコスト1以下のキャラ1枚までをKOし、このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_op12_109_trigger_ko_cost_le_1_and_keep_ai():
    """【トリガー】 相手コスト1以下キャラを KO + 自身を手札に (keep フラグ) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1 (<=1)
    big = InPlay.of(repo.get(_FILLER), sickness=False)    # cost2 (対象外)
    opp.characters = [small, big]

    do, _ = _do(overlay, "OP12-109", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert small not in opp.characters, "コスト1以下の相手キャラが KO されていない"
    assert big in opp.characters, "コスト2の相手キャラは KO 対象外で残るべき"
    assert st.last_trigger_kept_in_hand is True, \
        "to_hand_self_trigger でこのカードを手札に加えるフラグが立っていない"


# --------------------------------------------------------------------------- #
#  OP12-113 ロロノア・ゾロ (CHARACTER 黄 cost5 pow6000):
#    【KO時】自リーダーが超新星なら、 自手札からコスト4以下の超新星キャラ1枚までを
#      レストで登場させる。
#    【トリガー】相手のコスト1以下のキャラ1枚までをKOし、このカードを手札に加える。
# --------------------------------------------------------------------------- #
def test_op12_113_on_ko_play_from_hand_ss_ai():
    """【KO時】 超新星 leader → 手札からコスト4以下超新星キャラをレスト登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _SS_LEADER, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_SS_C4)]  # 超新星 cost4
    me.characters = []

    trigger_on_ko(st, me, opp, repo.get("OP12-113"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    played = [c for c in me.characters if c.card.card_id == _SS_C4]
    assert len(played) == 1, \
        f"手札から超新星キャラが登場していない: {[c.card_id for c in me.characters]}"
    assert played[0].rested is True, "レストで登場するべき"


def test_op12_113_on_ko_no_play_when_not_ss_leader():
    """負例: 非超新星 leader なら【KO時】の登場が発火しない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get(_SS_C4)]
    me.characters = []

    trigger_on_ko(st, me, opp, repo.get("OP12-113"), overlay)
    resolve_triggers(st)  # KO グループは enqueue のみ = 実経路と同じくここでドレイン
    _drain(st)

    assert not any(c.card.card_id == _SS_C4 for c in me.characters), \
        "非超新星 leader で登場が発火してはいけない"


def test_op12_113_trigger_ko_cost_le_1_and_keep_ai():
    """【トリガー】 相手コスト1以下キャラを KO + 自身を手札に (keep フラグ) (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    small = InPlay.of(repo.get(_VICTIM), sickness=False)  # cost1
    big = InPlay.of(repo.get(_FILLER), sickness=False)    # cost2
    opp.characters = [small, big]

    do, _ = _do(overlay, "OP12-113", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert small not in opp.characters, "コスト1以下の相手キャラが KO されていない"
    assert big in opp.characters, "コスト2の相手キャラは残るべき"
    assert st.last_trigger_kept_in_hand is True, \
        "to_hand_self_trigger のフラグが立っていない"


# --------------------------------------------------------------------------- #
#  OP12-115 愛してるぜ!! (EVENT 黄 cost1):
#    【カウンター】自リーダーかキャラ1枚まで +2000。 その後、自ライフ2枚以下なら
#      自トラッシュから「トラファルガー・ロー」1枚までを手札に加える。
# --------------------------------------------------------------------------- #
def test_op12_115_counter_pump_and_search_ai():
    """【カウンター】 自リーダー +2000 (既定) + 自ライフ2以下でトラッシュから ロー を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 2  # 2枚以下 = search 条件成立
    me.trash = [repo.get(_LAW_C1)]     # トラッシュに ロー
    me.hand = []

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP12-115"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 2000, \
        f"カウンターの +2000 が自リーダーに反映されていない: {me.leader.power}"
    assert any(c.card_id == _LAW_C1 for c in me.hand), \
        "自ライフ2以下でトラッシュから ロー が手札に加わっていない"


def test_op12_115_counter_no_search_when_life_high():
    """負例: 自ライフ3枚 → search 条件不成立で ロー は手札に加わらない (pump は乗る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get(_FILLER)] * 3  # 3枚 = search 条件不成立
    me.trash = [repo.get(_LAW_C1)]
    me.hand = []

    power_before = me.leader.power
    trigger_counter_event(st, me, opp, repo.get("OP12-115"), overlay)
    _drain(st)

    assert me.leader.power == power_before + 2000, "カウンターの pump は乗るべき"
    assert not any(c.card_id == _LAW_C1 for c in me.hand), \
        "ライフ3枚で search が発火してはいけない"


# --------------------------------------------------------------------------- #
#  OP12-116 鐘を鳴らして君を待つ!!!! (EVENT 黄 cost3):
#    【メイン】自デッキ上5枚を見て、特徴《シャンドラの戦士》キャラか
#      「モンブラン・ノーランド」合計2枚までを公開手札。 残りをデッキ下。
#    【トリガー】カード1枚を引く。
# --------------------------------------------------------------------------- #
def test_op12_116_main_search_shandia_ai():
    """【メイン】 デッキ上5枚から シャンドラの戦士 キャラ2枚を手札 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDIA), repo.get(_FILLER), repo.get(_SHANDIA)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    do, _ = _do(overlay, "OP12-116", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    shandia_in_hand = [c for c in me.hand if c.card_id == _SHANDIA]
    assert len(shandia_in_hand) == 2, \
        f"シャンドラの戦士 キャラが2枚手札に加わっていない: {[c.card_id for c in me.hand]}"


def test_op12_116_main_search_human_modal():
    """人間 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_SHANDIA), repo.get(_FILLER), repo.get(_SHANDIA)] \
        + [repo.get(_FILLER)] * 10
    me.hand = []

    do, _ = _do(overlay, "OP12-116", "main")
    execute_effect(do[0], st, me, opp, None)

    assert st.pending_choice is not None, "人間で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain(st)
    assert any(c.card_id == _SHANDIA for c in me.hand), \
        "人間が選んだ シャンドラの戦士 キャラが手札に加わっていない"


def test_op12_116_trigger_draw():
    """【トリガー】 カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, _NEUTRAL, overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get(_FILLER)] * 10
    me.hand = []

    deck_before = len(me.deck)
    do, _ = _do(overlay, "OP12-116", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    _drain(st)

    assert len(me.hand) == 1, "トリガーで 1 ドローされていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減るべき"
