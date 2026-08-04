# -*- coding: utf-8 -*-
"""EB02 弾 効果 回帰テスト バックフィル (自動生成 wave 008):
EB02-037 / EB02-039 / EB02-040 / EB02-044 / EB02-045 / EB02-046 /
EB02-047 / EB02-048 / EB02-049 / EB02-050 の 10 枚。

目的 (= test_backfill_auto_001〜007.py と同一方針):
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
    デッキは効果の薄いバニラ気味カード (ST01-004) で埋める (= サーチ/ドローの混入回避)。"""
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


def _do(overlay, cid, when):
    """指定 card_id の overlay から when 一致の最初の効果の (do, effect) を返す。"""
    for e in overlay.get(cid).effects:
        if e.get("when") == when:
            return e["do"], e
    raise AssertionError(f"{cid} に when={when} の効果がない")


def _drain_choices(st, pick=None, guard=8):
    """残った pending_choice を安全に drain (= 後続 modal を順に解決)。"""
    n = 0
    while st.pending_choice is not None and n < guard:
        resolve_pending_choice(st, list(pick) if pick is not None else [])
        n += 1


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_eb02_wave8_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB02-037", "EB02-039", "EB02-040", "EB02-044", "EB02-045",
           "EB02-046", "EB02-047", "EB02-048", "EB02-049", "EB02-050"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB02-037 フランキー: 【登場時】【アタック時】自リーダーが《麦わらの一味》&
#           自ドン<=相手ドン → ドンデッキから1枚 レストで追加
# --------------------------------------------------------------------------- #
def test_eb02_037_franky_on_play_add_rested_don_ai():
    """登場時 (麦わら leader + 自ドン<=相手ドン): ドンデッキから1枚 レストで追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ロロノア・ゾロ (麦わらの一味 leader)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 0
    me.don_remaining_in_deck = 10
    opp.don_active = 2  # 相手ドン >= 自ドン (= don_diff_le 0 成立)

    do, eff = _do(overlay, "EB02-037", "on_play")
    conds = eff.get("conditions", [])
    assert {"leader_feature": "麦わらの一味"} in conds, "overlay の 条件 leader_feature が無い"
    assert {"don_diff_le": 0} in conds, "overlay の 条件 don_diff_le=0 が無い"
    for cond in conds:
        assert eval_condition(cond, st, me) is True, f"条件 {cond} が成立していない"

    rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-037"), sickness=False))
    assert me.don_rested == rested_before + 1, \
        f"レストドンが1枚追加されていない: {me.don_rested} (before {rested_before})"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキから1枚減っていない"


def test_eb02_037_franky_condition_fails_when_don_ahead():
    """自ドンが相手より多い場合 don_diff_le=0 は 不成立 (= 追加しない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 5
    opp.don_active = 0  # 自ドン > 相手ドン
    _, eff = _do(overlay, "EB02-037", "on_play")
    assert eval_condition({"don_diff_le": 0}, st, me) is False, \
        "自ドンが多いのに don_diff_le=0 が成立してはいけない"


def test_eb02_037_franky_condition_fails_wrong_leader():
    """リーダーが《麦わらの一味》でない場合 条件 不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay)  # ガープ (海軍、 麦わらでない)
    me = st.players[0]
    assert eval_condition({"leader_feature": "麦わらの一味"}, st, me) is False, \
        "麦わらでない leader で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB02-039 GERMA 66 (EVENT): 【メイン】ジェルマ66 pow4000以下を1枚捨てる →
#           自ドン<=相手ドンなら 同名 pow5000-7000 を トラッシュから登場
# --------------------------------------------------------------------------- #
def test_eb02_039_germa66_main_reanimate_same_name_ai():
    """メイン: ヴィンスモーク・イチジ(pow4000)を捨て → トラッシュの同名 pow7000 を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP06-021", overlay)  # 紫リーダー (任意)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    opp.don_active = 2  # 自ドン<=相手ドン (= don_diff_le 0 成立)
    ichiji_small = repo.get("OP06-060")   # ヴィンスモーク・イチジ cost4 pow4000 ジェルマ66
    ichiji_big = repo.get("OP06-061")     # ヴィンスモーク・イチジ cost7 pow7000 ジェルマ66
    assert ichiji_small.name == ichiji_big.name, "テスト前提: 同名イチジ"
    me.hand = [ichiji_small]
    me.trash = [ichiji_big]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB02-039", "main")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-039"), sickness=False))
    assert ichiji_small not in me.hand, "コストで pow4000 イチジが手札から捨てられていない"
    assert any(c.card.card_id == "OP06-061" for c in me.characters), \
        "トラッシュの同名 pow5000-7000 キャラが登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


# --------------------------------------------------------------------------- #
#  EB02-040 BRAND NEW WORLD (EVENT): 【メイン】上4枚から コスト4以上1枚まで 手札 /
#           【トリガー】このカードの【メイン】効果を発動
# --------------------------------------------------------------------------- #
def test_eb02_040_bnw_main_search_cost_ge4_ai():
    """メイン: 上4枚から コスト4以上のカードを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB01-049")  # cost5 (= コスト4以上)
    assert big.cost >= 4
    me.deck = [big] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-040", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "上4枚から コスト4以上のカードが手札に加わっていない"


def test_eb02_040_bnw_trigger_fires_main():
    """トリガー: fire_self_effect で【メイン】効果 (上4枚サーチ) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-040", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-040"), sickness=False))
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "トリガー経由で メイン効果 (サーチ) が発動していない"


def test_eb02_040_bnw_main_human_search_modal():
    """人間: 上4枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-040", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "人間が選んだ コスト4以上カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-044 センゴク: 【ブロッカー】【登場時】自トラッシュから コスト4以下の
#           黒《海軍》キャラ1枚まで レスト登場
# --------------------------------------------------------------------------- #
def test_eb02_044_sengoku_on_play_reanimate_navy_ai():
    """登場時: トラッシュの 黒《海軍》cost4以下キャラ (クザン) を レスト登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay)  # ガープ (海軍 leader)
    me, opp = st.players[0], st.players[1]
    kuzan = repo.get("OP11-084")  # クザン cost4 黒 海軍
    assert kuzan.cost <= 4 and "黒" in kuzan.color \
        and any("海軍" in f for f in (kuzan.features or ()))
    me.trash = [kuzan]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB02-044", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-044"), sickness=False))
    played = [c for c in me.characters if c.card.card_id == "OP11-084"]
    assert played, "トラッシュから 黒《海軍》キャラが登場していない"
    assert played[0].rested is True, "公式は「レストで登場」 → rested であるべき"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_eb02_044_sengoku_on_play_human_pick_modal():
    """人間 + トラッシュに候補 複数 → play_from_trash modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.trash = [repo.get("OP11-084"), repo.get("OP11-088")]  # クザン / シュウ (共に黒海軍cost4)

    do, _ = _do(overlay, "EB02-044", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-044"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で modal が立たない"
    assert "play_from_trash" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_trash 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card.card_id in ("OP11-084", "OP11-088") for c in me.characters), \
        "人間が選んだ 黒《海軍》キャラが登場していない"


# --------------------------------------------------------------------------- #
#  EB02-045 トラファルガー・ロー: 【ブロッカー】【登場時】トラッシュ2枚をデッキ下→
#           1つ選ぶ: ・1ドロー ・相手手札5以上なら相手手札1捨て
# --------------------------------------------------------------------------- #
def test_eb02_045_law_on_play_choice_draw_ai():
    """登場時 choice: AI は先頭 valid option (= 1 ドロー) を発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []

    do, _ = _do(overlay, "EB02-045", "on_play")
    hand_before = len(me.hand)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-045"), sickness=False))
    assert len(me.hand) == hand_before + 1, \
        f"AI choice の 1 ドローが反映されていない: {len(me.hand)}"


def test_eb02_045_law_on_play_human_option_modal():
    """人間: choice_effect の option_pick modal が立ち、 1 ドローを選んで解決できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []
    opp.hand = [repo.get("ST01-004")] * 5  # 相手手札5枚 (= option2 も valid)

    do, _ = _do(overlay, "EB02-045", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-045"), sickness=False))
    assert st.pending_choice is not None, "人間で option_pick modal が立たない"
    assert st.pending_choice.get("kind") == "option_pick", \
        f"kind が option_pick でない: {st.pending_choice.get('kind')}"
    opts = st.pending_choice.get("options", [])
    assert len(opts) == 2, f"valid option が 2 件でない: {len(opts)}"
    hand_before = len(me.hand)
    resolve_pending_choice(st, [0])  # 1 ドローを選択
    _drain_choices(st)
    assert len(me.hand) == hand_before + 1, "人間が選んだ 1 ドローが反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-046 ヒルドン: 【登場時】上2枚トラッシュ + 相手キャラ1枚まで このターン コスト-1
# --------------------------------------------------------------------------- #
def test_eb02_046_hildon_on_play_mill_and_cost_minus_ai():
    """登場時: 上2枚をトラッシュ + 相手キャラ1枚を コスト-1 (AI 自動選択)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.trash = []
    victim = repo.get("EB01-049")  # cost5 CHARACTER
    victim_ip = InPlay.of(victim, sickness=False)
    opp.characters = [victim_ip]

    deck_before = len(me.deck)
    cost_before = victim_ip.base_cost
    do, _ = _do(overlay, "EB02-046", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-046"), sickness=False))
    assert len(me.deck) == deck_before - 2, "デッキ上2枚がトラッシュされていない"
    assert len(me.trash) == 2, "トラッシュに2枚置かれていない"
    assert victim_ip.base_cost == cost_before - 1, \
        f"相手キャラの コスト-1 が反映されていない: {victim_ip.base_cost} (before {cost_before})"


def test_eb02_046_hildon_cost_minus_human_pick_modal():
    """人間 + 相手キャラ 複数 → cost_minus の target_pick modal が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("EB01-049"), sickness=False)
    b = InPlay.of(repo.get("OP01-016"), sickness=False)
    opp.characters = [a, b]

    do, _ = _do(overlay, "EB02-046", "on_play")
    # do[1] = cost_minus (do[0] は mill_self_top)
    execute_effect(do[1], st, me, opp,
                   InPlay.of(repo.get("EB02-046"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    b_before = b.base_cost
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st)
    assert b.base_cost == b_before - 1, "人間が選んだ相手キャラに コスト-1 が反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-047 ブルーノ: 【起動メイン】手札1捨て+このキャラをトラッシュ →
#           トラッシュから「ブルーノ」以外の cost5以下『CP』特徴キャラ1枚まで 登場
# --------------------------------------------------------------------------- #
def test_eb02_047_bruno_activate_main_reanimate_cp_ai():
    """起動メイン (手札1捨て + 自トラッシュ コスト): トラッシュの CP cost5以下を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    bruno = InPlay.of(repo.get("EB02-047"), sickness=False)
    me.characters = [bruno]
    me.hand = [repo.get("ST01-004")]  # 捨てるコスト用
    spandine = repo.get("EB01-043")  # スパンダイン CP9 cost3
    assert any("CP" in f for f in (spandine.features or ())) and spandine.cost <= 5
    me.trash = [spandine]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-047"]
    assert len(mine) == 1, f"EB02-047 の起動メインが legal に出ない: {len(mine)}"
    hand_before = len(me.hand)
    fire_activate_main(st, me, opp, *mine[0])

    assert bruno not in me.characters, "コストで ブルーノ 自身がトラッシュに置かれるべき"
    assert len(me.hand) == hand_before - 1, "コストで手札1枚が捨てられるべき"
    assert any(c.card.card_id == "EB01-043" for c in me.characters), \
        "トラッシュから CP cost5以下キャラ (スパンダイン) が登場していない"


def test_eb02_047_bruno_activate_main_needs_hand_to_discard():
    """手札が無いと discard_hand コストが払えず 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("EB02-047"), sickness=False)]
    me.hand = []  # 捨てる手札なし
    me.trash = [repo.get("EB01-043")]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-047"]
    assert len(mine) == 0, "手札が無いのに 起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  EB02-048 ブルック: 【登場時】トラッシュから「ラブーン」1枚まで 手札 /
#           【KO時】手札から cost4以下「ラブーン」1枚まで 登場
# --------------------------------------------------------------------------- #
def test_eb02_048_brook_on_play_recover_laboon_ai():
    """登場時: トラッシュの「ラブーン」を手札に加える (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    laboon = repo.get("EB01-047")  # ラブーン cost2 黒
    assert laboon.name == "ラブーン"
    me.trash = [laboon]
    me.hand = []

    do, _ = _do(overlay, "EB02-048", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-048"), sickness=False))
    assert any(c.card_id == "EB01-047" for c in me.hand), \
        "トラッシュの「ラブーン」が手札に加わっていない"
    assert laboon not in me.trash, "手札に加えた「ラブーン」がトラッシュに残っている"


def test_eb02_048_brook_on_ko_play_laboon_ai():
    """KO時: 手札の cost4以下「ラブーン」を登場 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    laboon = repo.get("EB01-047")  # ラブーン cost2 (<=4)
    me.hand = [laboon]

    chars_before = len(me.characters)
    do, _ = _do(overlay, "EB02-048", "on_ko")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-048"), sickness=False))
    assert any(c.card.card_id == "EB01-047" for c in me.characters), \
        "手札の cost4以下「ラブーン」が登場していない"
    assert len(me.characters) == chars_before + 1, "登場キャラが1体増えていない"


def test_eb02_048_brook_on_ko_human_play_modal():
    """人間 + 手札に「ラブーン」複数 → play_from_hand modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("EB01-047"), repo.get("ST08-012")]  # ラブーン cost2 / cost4

    do, _ = _do(overlay, "EB02-048", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-048"), sickness=False))
    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert "play_from_hand" in st.pending_choice.get("kind", ""), \
        f"kind が play_from_hand 系でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card.card_id in ("EB01-047", "ST08-012") for c in me.characters), \
        "人間が選んだ「ラブーン」が登場していない"


# --------------------------------------------------------------------------- #
#  EB02-049 モンキー・D・ガープ: 【登場時】自リーダーにレストドン2枚まで付与 /
#           【起動メイン】自レスト + リーダーが「ガープ」→ 相手 cost1以下1枚まで KO
# --------------------------------------------------------------------------- #
def test_eb02_049_garp_on_play_attach_rested_don_ai():
    """登場時: 自リーダーにレストドン2枚を付与 (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay)  # ガープ leader
    me, opp = st.players[0], st.players[1]
    me.don_rested = 3

    don_before = me.leader.attached_dons
    rested_before = me.don_rested
    do, _ = _do(overlay, "EB02-049", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-049"), sickness=False))
    assert me.leader.attached_dons == don_before + 2, \
        "自リーダーにレストドン2枚が付与されていない"
    assert me.don_rested == rested_before - 2, "レストドンが2枚消費されるべき"


def test_eb02_049_garp_activate_main_ko_cost1_ai():
    """起動メイン (leader ガープ): 自レスト → 相手 cost1以下キャラを KO (AI)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay)  # ガープ leader → if 条件成立
    me, opp = st.players[0], st.players[1]
    garp = InPlay.of(repo.get("EB02-049"), sickness=False)
    me.characters = [garp]
    victim = InPlay.of(repo.get("EB04-032"), sickness=False)  # クイーン cost1
    assert victim.card.cost <= 1
    opp.characters = [victim]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-049"]
    assert len(mine) == 1, f"EB02-049 の起動メインが legal に出ない: {len(mine)}"
    fire_activate_main(st, me, opp, *mine[0])

    assert victim not in opp.characters, "相手 cost1以下キャラが KO されていない"
    assert garp.rested is True, "起動メインコストで ガープ がレストされるべき"


def test_eb02_049_garp_activate_main_not_legal_wrong_leader():
    """リーダーが「ガープ」でない場合、 起動メインの if 条件で legal に出ない。"""
    # ⚠ 2026-08-05 是正: 公式は 「〜できる：<条件>の場合、<効果>」 のコロン後の条件を
    #   **効果のみ** の gate とする。 任意コストは条件不成立でも支払える。
    #   一次情報 (cardqa_op_02): 「自分のリーダーが「エンポリオ・イワンコフ」ではない場合、
    #   この【起動メイン】効果を発動できますか？」 → 「はい、できます。 その場合、このカードを
    #   レストにしますが、 **その後の効果では何も起きません**」。
    #   → 「条件不成立なら legal に出ない」 は **行動の合法性ごと消す旧バグ** を固定していた。
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)  # ゾロ (ガープでない)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("EB02-049"), sickness=False)]
    opp.characters = [InPlay.of(repo.get("EB04-032"), sickness=False)]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-049"]
    assert len(mine) == 1, (
        "任意コストは条件不成立でも払えるので legal に残るべき (公式: cardqa_op_02)"
    )


def test_eb02_049_garp_activate_main_human_ko_modal():
    """人間 + 相手 cost1以下 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-002", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("EB02-049"), sickness=False)]
    a = InPlay.of(repo.get("EB04-032"), sickness=False)  # cost1
    b = InPlay.of(repo.get("EB04-037"), sickness=False)  # cost1
    opp.characters = [a, b]

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-049"]
    assert len(mine) == 1
    fire_activate_main(st, me, opp, *mine[0])

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    _drain_choices(st, pick=[b_idx])
    assert b not in opp.characters, "人間が選んだキャラが KO されていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  EB02-050 ココロのちず (EVENT): 【メイン】上4枚から コスト4以上1枚まで 手札 /
#           【トリガー】このカードの【メイン】効果を発動 (= EB02-040 と同型)
# --------------------------------------------------------------------------- #
def test_eb02_050_kokoro_main_search_cost_ge4_ai():
    """メイン: 上4枚から コスト4以上のカードを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB01-049")  # cost5
    me.deck = [big] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-050", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "上4枚から コスト4以上のカードが手札に加わっていない"


def test_eb02_050_kokoro_trigger_fires_main():
    """トリガー: fire_self_effect で【メイン】効果 (上4枚サーチ) が発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-050", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-050"), sickness=False))
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "トリガー経由で メイン効果 (サーチ) が発動していない"


def test_eb02_050_kokoro_main_human_search_modal():
    """人間: 上4枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-050", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "人間が選んだ コスト4以上カードが手札に加わっていない"
