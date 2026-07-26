# -*- coding: utf-8 -*-
"""OP07 / OP08 弾 効果 回帰テスト バックフィル (自動生成 wave 082):
OP07-113 / OP07-114 / OP07-116 / OP07-117 / OP07-118 /
OP08-001 / OP08-002 / OP08-004 / OP08-005 / OP08-006 の 10 枚。

目的 (= 永続的 pytest による担保、 test_backfill_auto_001.py と同一方針):
  (1) 各カードの効果が 公式テキスト通り 盤面で正しく発火する (発火前後の差分を assert)
  (2) 対象選択 を 持つカードは 人間 actor で pending_choice が
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


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_op07_op08_wave082_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["OP07-113", "OP07-114", "OP07-116", "OP07-117", "OP07-118",
           "OP08-001", "OP08-002", "OP08-004", "OP08-005", "OP08-006"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  OP07-113 ロロノア・ゾロ:
#    【トリガー】自リーダーが《エッグヘッド》なら 相手のリーダーかキャラ1枚までをレスト
# --------------------------------------------------------------------------- #
def test_op07_113_zoro_lifecard_trigger_rest_ai():
    """トリガー: エッグヘッド leader → 相手キャラ (or リーダー) 1枚をレストにする (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)  # ベガパンク (エッグヘッド leader)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    assert victim.rested is False
    trig = next(e for e in overlay.get("OP07-113").effects if e["when"] == "trigger")
    assert trig.get("if", {}).get("leader_feature") == "エッグヘッド", \
        "overlay の トリガー条件 leader_feature=エッグヘッド が無い"
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim.rested is True, "相手キャラがレストにされていない"


def test_op07_113_zoro_lifecard_trigger_rest_human_pick():
    """人間 + 相手リーダー/キャラ 複数 → target_pick modal が立ち resolve で 1 枚をレスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    trig = next(e for e in overlay.get("OP07-113").effects if e["when"] == "trigger")
    execute_effect(trig["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    # 相手リーダー + キャラ2体 = 3 候補
    assert len(cands) == 3, f"候補 (リーダー+キャラ2) が 3 件でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.rested is True, "人間が選んだ相手キャラがレストにされていない"
    assert a.rested is False, "選ばなかったキャラがレストされてはいけない"


# --------------------------------------------------------------------------- #
#  OP07-114 世界最大の頭脳を持つ男 (EVENT):
#    【メイン】デッキ上5枚から《エッグヘッド》カード1枚を手札へ、 残りをデッキ下
#    【トリガー】カード1枚を引く
# --------------------------------------------------------------------------- #
def test_op07_114_main_search_egg_to_hand_ai():
    """メイン: デッキ上5枚に エッグヘッドカード を仕込むと手札へ加わる (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)
    me, opp = st.players[0], st.players[1]
    egg = repo.get("OP07-113")  # ゾロ (エッグヘッド)
    assert "エッグヘッド" in (egg.features or ()), "テスト前提: OP07-113 は エッグヘッド"
    me.deck = [egg] + [repo.get("OP01-013")] * 20
    me.hand = []

    main = next(e for e in overlay.get("OP07-114").effects if e["when"] == "main")
    for prim in main["do"]:
        execute_effect(prim, st, me, opp, None)

    assert any(c.card_id == "OP07-113" for c in me.hand), \
        "デッキ上5枚から エッグヘッドカードが手札に加わっていない"


def test_op07_114_main_search_human_pick():
    """人間 + デッキ上5枚に エッグヘッド 複数 → search_top_n modal が立ち resolve で手札へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    egg = repo.get("OP07-113")
    me.deck = [egg, repo.get("OP01-013"), egg] + [repo.get("OP01-013")] * 15
    me.hand = []

    main = next(e for e in overlay.get("OP07-114").effects if e["when"] == "main")
    execute_effect(main["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (ゾロ) を選択
    guard = 0
    while st.pending_choice is not None and guard < 6:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.card_id == "OP07-113" for c in me.hand), \
        "人間が選んだ エッグヘッドカードが手札に加わっていない"


def test_op07_114_trigger_draw_ai():
    """トリガー: カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []

    trig = next(e for e in overlay.get("OP07-114").effects if e["when"] == "trigger")
    before = len(me.hand)
    for prim in trig["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == before + 1, "トリガーで 1 枚 引けていない"


# --------------------------------------------------------------------------- #
#  OP07-116 焔裂き (EVENT):
#    【メイン】/【カウンター】自リーダーかキャラ1枚 +1000。 その後 相手ライフ2以下なら
#    相手のコスト4以下キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_op07_116_counter_pump_and_conditional_rest_ai():
    """カウンター: 自リーダー +1000、 相手ライフ2以下 → 相手コスト4以下キャラ1枚レスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 2  # ライフ 2 → 条件成立
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # コスト1
    opp.characters = [victim]

    counter = next(e for e in overlay.get("OP07-116").effects if e["when"] == "counter")
    power_before = me.leader.power
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, \
        f"カウンターの +1000 が自リーダーに反映されていない: {me.leader.power}"
    assert victim.rested is True, "相手ライフ2以下なのに相手キャラがレストされていない"


def test_op07_116_counter_no_rest_when_life_high_ai():
    """相手ライフ3以上 → +1000 のみ、 レストは発生しない (条件 opp_life_le=2 不成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    opp.life = [repo.get("OP01-013")] * 4  # ライフ 4 → 条件不成立
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    counter = next(e for e in overlay.get("OP07-116").effects if e["when"] == "counter")
    power_before = me.leader.power
    for prim in counter["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 1000, "+1000 が乗っていない"
    assert victim.rested is False, "ライフ3以上で相手キャラがレストされてはいけない"


def test_op07_116_counter_pump_human_pick():
    """人間 + 自リーダー/キャラ 複数 → +1000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    counter = next(e for e in overlay.get("OP07-116").effects if e["when"] == "counter")
    execute_effect(counter["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 1000, \
        "人間が選んだキャラに +1000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP07-117 エッグヘッド (STAGE):
#    【自分のターン終了時】自ライフ3以下なら コスト5以下《エッグヘッド》キャラ1枚をアクティブ
# --------------------------------------------------------------------------- #
def test_op07_117_end_of_turn_untap_egg_chara_ai():
    """ターン終了時: 自ライフ3以下 → レスト中のエッグヘッドキャラをアクティブにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP07-097", overlay)
    me, opp = st.players[0], st.players[1]
    me.life = [repo.get("OP01-013")] * 3  # ライフ3 → 条件成立
    egg = InPlay.of(repo.get("OP07-113"), sickness=False)  # コスト5 エッグヘッド
    egg.rested = True
    me.characters = [egg]

    eot = next(e for e in overlay.get("OP07-117").effects if e["when"] == "end_of_turn")
    assert eot.get("if", {}).get("self_life_le") == 3, \
        "overlay の 条件 self_life_le=3 が無い"
    for prim in eot["do"]:
        execute_effect(prim, st, me, opp, None)

    assert egg.rested is False, "ターン終了時にエッグヘッドキャラがアクティブにされていない"


# --------------------------------------------------------------------------- #
#  OP07-118 サボ:
#    【登場時】手札1枚を捨てられる：相手のコスト5以下キャラ1枚 と コスト3以下キャラ1枚をKO
# --------------------------------------------------------------------------- #
def test_op07_118_sabo_on_play_optional_discard_ko_ai():
    """登場時: 手札1枚を捨てて 相手コスト5以下キャラをKOする (AI 自動、 任意コスト成立)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # コスト2
    opp.characters = [victim]

    hand_before = len(me.hand)
    on_play = next(e for e in overlay.get("OP07-118").effects if e["when"] == "on_play")
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP07-118"), sickness=True))

    assert victim not in opp.characters, "相手コスト5以下キャラがKOされていない"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  OP08-001 トニートニー・チョッパー (LEADER):
#    【起動メイン】【ターン1回】自《動物》/《ドラム王国》キャラ3枚までにレストドン1ずつ付与
# --------------------------------------------------------------------------- #
def test_op08_001_chopper_leader_activate_attach_rested_don_ai():
    """起動メイン: ドラム王国キャラにレストドンを付与する (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3  # レストドン供給源
    c1 = InPlay.of(repo.get("OP08-004"), sickness=False)  # ドラム王国
    c2 = InPlay.of(repo.get("OP08-005"), sickness=False)  # ドラム王国
    me.characters = [c1, c2]

    rested_before = me.don_rested
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-001"]
    assert len(opts) == 1, f"OP08-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert c1.attached_dons >= 1, "ドラム王国キャラ c1 にレストドンが付与されていない"
    assert c2.attached_dons >= 1, "ドラム王国キャラ c2 にレストドンが付与されていない"
    assert me.don_rested < rested_before, "レストドンが消費されるべき"


def test_op08_001_chopper_leader_activate_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3
    me.characters = [InPlay.of(repo.get("OP08-004"), sickness=False)]

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "OP08-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  OP08-002 マルコ (LEADER):
#    【ドン!!×1】【起動メイン】カード1枚引き手札1枚をデッキ上下へ。 その後 相手キャラ1枚 -2000
# --------------------------------------------------------------------------- #
def test_op08_002_marco_leader_activate_draw_and_debuff_ai():
    """起動メイン (ドン1ゲート): 引く→手札戻す→相手キャラ -2000 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1  # ドン!!×1 ゲート成立
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.deck = [repo.get("OP01-013")] * 10
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    hand_before = len(me.hand)
    power_before = victim.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "OP08-002"]
    assert len(opts) == 1, f"OP08-002 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    # 引いて 1 枚戻す → 手札枚数は不変
    assert len(me.hand) == hand_before, \
        f"引く+デッキ戻すで手札枚数が変わってはいけない: {len(me.hand)} (was {hand_before})"
    assert victim.power == power_before - 2000, \
        f"相手キャラの -2000 が反映されていない: {victim.power} (was {power_before})"


def test_op08_002_marco_leader_debuff_human_pick():
    """人間 + 相手キャラ 複数 → -2000 の対象選択 target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP08-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.leader.attached_dons = 1
    me.hand = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.deck = [repo.get("OP01-013")] * 10
    a = InPlay.of(repo.get("OP01-016"), sickness=False)
    b = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [a, b]

    eff = overlay.get("OP08-002").effects[0]
    pump = next(p for p in eff["do"] if "power_pump" in p)
    execute_effect(pump, st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.power
    resolve_pending_choice(st, [b_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert b.power == b_before - 2000, "人間が選んだ相手キャラに -2000 が反映されていない"


# --------------------------------------------------------------------------- #
#  OP08-004 クロマーリモ:
#    【登場時】自分の「チェス」がいる場合、 相手のパワー3000以下キャラ1枚をKO
# --------------------------------------------------------------------------- #
def test_op08_004_kuromarimo_on_play_ko_when_chess_present_ai():
    """登場時: 自「チェス」がいる → 相手パワー3000以下キャラをKO (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    chess = InPlay.of(repo.get("OP08-005"), sickness=False)  # チェス
    me.characters = [chess]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]

    on_play = next(e for e in overlay.get("OP08-004").effects if e["when"] == "on_play")
    assert on_play.get("if", {}).get("self_chara_filtered_count_ge", {}) \
        .get("filter", {}).get("name") == "チェス", "overlay の チェス在場条件が無い"
    for prim in on_play["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("OP08-004"), sickness=True))

    assert victim not in opp.characters, "チェス在場時に相手パワー3000以下キャラがKOされていない"


def test_op08_004_kuromarimo_no_ko_without_chess_ai():
    """自「チェス」がいない → KO 条件不成立で相手キャラは残る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = []  # チェス不在
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [victim]

    on_play = next(e for e in overlay.get("OP08-004").effects if e["when"] == "on_play")
    cond = on_play.get("if", {}).get("self_chara_filtered_count_ge")
    # 条件を engine の gate 経由で検証: チェス不在なら KO を実行しないのが正
    from engine.effects import eval_condition
    assert eval_condition(cond, st, me, None) is False, \
        "チェス不在なのに条件が成立している"


# --------------------------------------------------------------------------- #
#  OP08-005 チェス:
#    【登場時】相手キャラ1枚 -2000。 その後 自「クロマーリモ」不在なら
#    手札から「クロマーリモ」1枚を登場させる
# --------------------------------------------------------------------------- #
def test_op08_005_chess_on_play_debuff_and_play_kuromarimo_ai():
    """登場時: 相手キャラ -2000、 クロマーリモ不在 → 手札から クロマーリモ を登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-016"), sickness=False)  # power 2000
    opp.characters = [victim]
    me.hand = [repo.get("OP08-004")]  # クロマーリモ を手札に
    me.characters = []

    power_before = victim.power
    for eff in overlay.get("OP08-005").effects:
        if eff["when"] != "on_play":
            continue
        for prim in eff["do"]:
            execute_effect(prim, st, me, opp,
                           InPlay.of(repo.get("OP08-005"), sickness=True))

    assert victim.power == power_before - 2000, \
        f"相手キャラの -2000 が反映されていない: {victim.power} (was {power_before})"
    assert any(c.card.card_id == "OP08-004" for c in me.characters), \
        "クロマーリモ不在時に手札から クロマーリモ が登場していない"
    assert all(c.card_id != "OP08-004" for c in me.hand), \
        "登場した クロマーリモ が手札から取り除かれていない"


# --------------------------------------------------------------------------- #
#  OP08-006 チェスマーリモ:
#    【自分のターン中】自トラッシュに「クロマーリモ」と「チェス」がある場合 パワー+2000
# --------------------------------------------------------------------------- #
def test_op08_006_chessmarimo_static_pump_with_trash_on_self_turn():
    """静的: 自ターン中 + トラッシュに クロマーリモ&チェス → base +2000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    marimo_def = repo.get("OP08-006")  # power 6000
    marimo = InPlay.of(marimo_def, sickness=False)
    me.characters = [marimo]
    me.trash = [repo.get("OP08-004"), repo.get("OP08-005")]  # クロマーリモ + チェス

    evaluate_static_effects(st, overlay)
    assert marimo.power == marimo_def.power + 2000, \
        f"トラッシュ条件成立で +2000 が乗っていない: {marimo.power} (base {marimo_def.power})"


def test_op08_006_chessmarimo_static_no_pump_off_turn():
    """相手ターン中は【自分のターン中】条件が不成立 → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    marimo_def = repo.get("OP08-006")
    marimo = InPlay.of(marimo_def, sickness=False)
    me.characters = [marimo]
    me.trash = [repo.get("OP08-004"), repo.get("OP08-005")]
    st.turn_player_idx = 1  # 相手ターン

    evaluate_static_effects(st, overlay)
    assert marimo.power == marimo_def.power, \
        f"相手ターンで pump が乗ってはいけない: {marimo.power} (base {marimo_def.power})"


def test_op08_006_chessmarimo_static_no_pump_without_trash():
    """トラッシュに両方揃っていない → +0。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    marimo_def = repo.get("OP08-006")
    marimo = InPlay.of(marimo_def, sickness=False)
    me.characters = [marimo]
    me.trash = []  # トラッシュ空

    evaluate_static_effects(st, overlay)
    assert marimo.power == marimo_def.power, \
        f"トラッシュ未成立で pump が乗ってはいけない: {marimo.power} (base {marimo_def.power})"
