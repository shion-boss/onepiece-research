# -*- coding: utf-8 -*-
"""EB02 弾 効果 回帰テスト バックフィル (自動生成 wave 007):
EB02-025 / EB02-026 / EB02-027 / EB02-028 / EB02-030 / EB02-031 /
EB02-032 / EB02-033 / EB02-035 / EB02-036 の 10 枚。

目的 (= test_backfill_auto_001〜006.py と同一方針):
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
def test_all_eb02_wave7_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["EB02-025", "EB02-026", "EB02-027", "EB02-028", "EB02-030",
           "EB02-031", "EB02-032", "EB02-033", "EB02-035", "EB02-036"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  EB02-025 ドンキホーテ・ロシナンテ: 【起動メイン】ドン1+自レスト：
#           リーダーが「ロシナンテ」なら 上5枚見て コスト2以下キャラ1枚まで レスト登場
# --------------------------------------------------------------------------- #
def test_eb02_025_rosinante_activate_main_search_play_ai():
    """起動メイン (leader ロシナンテ): ドン1+自レスト コスト → 上5枚から コスト2以下キャラを
    レスト登場する (AI 自動)。 デッキ先頭に該当キャラを仕込む。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-022", overlay)  # ドンキホーテ・ロシナンテ leader
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    rosi = InPlay.of(repo.get("EB02-025"), sickness=False)
    me.characters = [rosi]
    target = repo.get("OP01-016")  # cost1 CHARACTER (= コスト2以下)
    assert target.cost <= 2 and target.category.value == "CHARACTER"
    me.deck = [target] + [repo.get("ST01-004")] * 10

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-025"]
    assert len(mine) == 1, f"EB02-025 の起動メインが legal に出ない: {len(mine)}"
    don_before = me.don_active
    fire_activate_main(st, me, opp, *mine[0])

    assert rosi.rested is True, "起動メインコストで ロシナンテ がレストされるべき"
    assert me.don_active == don_before - 1, "起動メインコストで ドン1枚がレストされるべき"
    played = [c for c in me.characters if c.card.card_id == "OP01-016"]
    assert played, "上5枚から コスト2以下キャラが 登場していない"
    # 公式「レストで登場」を忠実化 (overlay search_top_n に "rested": true を追加済)。
    assert played[0].rested is True, "コスト2以下キャラは レストで登場するべき"


def test_eb02_025_rosinante_activate_main_human_search_modal():
    """人間: 起動メイン発動 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP05-022", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    me.characters = [InPlay.of(repo.get("EB02-025"), sickness=False)]
    me.deck = [repo.get("OP01-016")] + [repo.get("ST01-004")] * 10

    opts = list_activate_main_effects(st, me, overlay)
    mine = [(s, e) for (s, e) in opts if s.card.card_id == "EB02-025"]
    fire_activate_main(st, me, opp, *mine[0])

    assert st.pending_choice is not None, "人間 起動メインで search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭 (該当キャラ) を選択
    _drain_choices(st)
    assert any(c.card.card_id == "OP01-016" for c in me.characters), \
        "人間が選んだキャラが レスト登場していない"


# --------------------------------------------------------------------------- #
#  EB02-026 ネフェルタリ・ビビ: 【登場時】(リーダー多色 &) 手札5枚以下で 2 ドロー
# --------------------------------------------------------------------------- #
def test_eb02_026_vivi_on_play_draw2_ai():
    """登場時: 手札5枚以下 (条件成立) → 2 枚引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST01-004")] * 3
    me.deck = [repo.get("ST01-004")] * 10

    do, eff = _do(overlay, "EB02-026", "on_play")
    assert eff.get("if", {}).get("self_hand_count_le") == 5, \
        "overlay の 条件 self_hand_count_le=5 が無い"
    assert eval_condition(eff["if"], st, me) is True, "手札3枚で 条件が成立していない"

    hand_before = len(me.hand)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-026"), sickness=False))
    assert len(me.hand) == hand_before + 2, \
        f"2 ドローが反映されていない: {len(me.hand)} (before {hand_before})"


def test_eb02_026_vivi_condition_fails_with_6_hand():
    """手札が6枚なら 条件 (self_hand_count_le=5) は 不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.hand = [repo.get("ST01-004")] * 6
    _, eff = _do(overlay, "EB02-026", "on_play")
    assert eval_condition(eff["if"], st, me) is False, \
        "手札6枚で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB02-027 ビスタ: 【登場時】相手のパワー1000以下のキャラ1枚までを デッキ下へ
#  overlay の spec は canonical な {"type","filter": {"current_power_le": 1000}} 形式。
#  return_to_deck_bottom primitive が ko / return_to_hand と同様に v を直接
#  _resolve_target へ渡すよう修正済 (= filter が効く)。 パワー>1000 のキャラは
#  対象化されない (公式は パワー1000以下 限定)。
# --------------------------------------------------------------------------- #
def test_eb02_027_vista_on_play_return_power_le1000_ai():
    """AI: 相手のパワー1000以下のキャラ1枚を デッキ下へ (= 場から消え デッキ末尾に入る)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    low = InPlay.of(repo.get("EB01-015"), sickness=False)  # power 1000 (= 対象)
    assert low.power <= 1000, f"前提: EB01-015 が パワー1000以下 でない ({low.power})"
    opp.characters = [low]
    deck_before = len(opp.deck)

    do, _ = _do(overlay, "EB02-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-027"), sickness=False))

    assert low not in opp.characters, "パワー1000以下のキャラが 場から消えていない"
    assert len(opp.deck) == deck_before + 1, "相手デッキの枚数が1増えていない"
    assert opp.deck[-1] is low.card, "対象カードが 持ち主デッキの末尾 (底) に置かれていない"


def test_eb02_027_vista_on_play_power_over_1000_not_targetable():
    """AI: パワー1000超のキャラは 対象にできない (= 場に残る、 デッキも増えない)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    high = InPlay.of(repo.get("EB01-049"), sickness=False)  # power 5000 (= 対象外)
    assert high.power > 1000, f"前提: EB01-049 が パワー1000超 でない ({high.power})"
    opp.characters = [high]
    deck_before = len(opp.deck)

    do, _ = _do(overlay, "EB02-027", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-027"), sickness=False))

    assert high in opp.characters, "パワー1000超のキャラは デッキ下に置かれてはいけない"
    assert len(opp.deck) == deck_before, "対象0のはずが 相手デッキ枚数が変化している"


def test_eb02_027_vista_on_play_human_modal_filters_candidates():
    """人間: パワー1000以下2枚 + パワー1000超1枚 → target_pick modal の候補は
    パワー1000以下の2枚のみ (filter で高パワーは除外)。 選んだ1枚がデッキ下へ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    lo_a = InPlay.of(repo.get("EB01-015"), sickness=False)  # power 1000
    lo_b = InPlay.of(repo.get("EB04-032"), sickness=False)  # power 1000
    high = InPlay.of(repo.get("EB01-049"), sickness=False)  # power 5000 (= 候補外)
    assert lo_a.power <= 1000 and lo_b.power <= 1000 and high.power > 1000
    opp.characters = [lo_a, high, lo_b]

    do, _ = _do(overlay, "EB02-027", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-027"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    cand_iids = {c["iid"] for c in cands}
    assert cand_iids == {lo_a.instance_id, lo_b.instance_id}, \
        f"候補が パワー1000以下の2枚に絞られていない: {cand_iids}"
    assert high.instance_id not in cand_iids, "パワー1000超が候補に混入している"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == lo_b.instance_id)
    deck_before = len(opp.deck)
    resolve_pending_choice(st, [b_idx])
    assert lo_b not in opp.characters, "人間が選んだキャラが 場から消えていない"
    assert opp.deck[-1] is lo_b.card, "人間が選んだキャラが デッキ底に置かれていない"
    assert lo_a in opp.characters, "選ばなかったキャラはデッキ下に置かれないべき"
    assert high in opp.characters, "パワー1000超は 影響を受けないべき"
    assert len(opp.deck) == deck_before + 1, "デッキ枚数が1だけ増えていない"


# --------------------------------------------------------------------------- #
#  EB02-028 ポートガス・D・エース: 【登場時】(リーダー白ひげ) 上5枚から コスト2キャラ
#           1枚まで 手札 + 手札からコスト2キャラ1枚まで レスト登場
# --------------------------------------------------------------------------- #
def test_eb02_028_ace_on_play_search_and_play_ai():
    """登場時 (leader 白ひげ海賊団): 上5枚から コスト2キャラを手札へ + 手札から
    コスト2キャラをレスト登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay)  # 白ひげ海賊団 leader
    me, opp = st.players[0], st.players[1]
    do, eff = _do(overlay, "EB02-028", "on_play")
    assert "白ひげ海賊団" in eff.get("if", {}).get("leader_features_any", []), \
        "overlay の 条件 leader_features_any=白ひげ海賊団 が無い"
    assert eval_condition(eff["if"], st, me) is True, "白ひげ leader で 条件が成立していない"

    me.deck = [repo.get("OP01-039")] + [repo.get("ST01-004")] * 10  # 上に cost2 キャラ
    me.hand = [repo.get("OP01-039")]  # 登場用 cost2 キャラ
    chars_before = len(me.characters)
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-028"), sickness=False))

    assert len(me.characters) == chars_before + 1, \
        "手札からコスト2キャラが1体 レスト登場していない"
    assert any(c.card.card_id == "OP01-039" for c in me.characters), \
        "登場したキャラが cost2 キャラでない"


def test_eb02_028_ace_on_play_human_search_modal():
    """人間: 上5枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP02-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("OP01-039")] + [repo.get("ST01-004")] * 10
    me.hand = [repo.get("OP01-039")]

    do, _ = _do(overlay, "EB02-028", "on_play")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-028"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "OP01-039" for c in me.hand), \
        "人間が選んだ cost2 キャラが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-030 仲間の夢を笑われた時だ!!!! (EVENT): 【カウンター】自キャラ全体 このターン中
#           バトルKO代替で手札1捨て / 【トリガー】1 ドロー
# --------------------------------------------------------------------------- #
def test_eb02_030_yume_counter_grant_ko_save_ai():
    """カウンター: **発動時に場にいる各キャラ** に「このターン中 バトルKO代替で手札1捨て」
    per-InPlay flag を付与する (発動後登場は対象外 = cardqa_eb_02、 2026-08-05 是正)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    present = InPlay.of(repo.get("ST01-004"), sickness=False)  # 発動時に場にいるキャラ
    me.characters = [present]
    assert present.battle_ko_save_discard_until_turn_end is False

    do, _ = _do(overlay, "EB02-030", "counter")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert present.battle_ko_save_discard_until_turn_end is True, \
        "カウンターで 場にいたキャラに バトルKO代替 flag が付与されていない"

    # 発動 **後** に登場したキャラには付かない (= 救済対象外)
    later = InPlay.of(repo.get("ST01-004"), sickness=False)
    me.characters.append(later)
    assert later.battle_ko_save_discard_until_turn_end is False, \
        "発動後に登場したキャラに flag が付いている (cardqa_eb_02: 対象外)"


def test_eb02_030_yume_trigger_draw1():
    """トリガー: カード1枚を引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []

    do, _ = _do(overlay, "EB02-030", "trigger")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert len(me.hand) == 1, "トリガーの 1 ドローが反映されていない"


# --------------------------------------------------------------------------- #
#  EB02-031 Hope (EVENT): 【メイン】上4枚から コスト4以上のカード1枚まで 手札へ
# --------------------------------------------------------------------------- #
def test_eb02_031_hope_main_search_cost_ge4_ai():
    """メイン: 上4枚から コスト4以上のカードを手札へ (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    big = repo.get("EB01-049")  # cost5 (= コスト4以上)
    assert big.cost >= 4
    me.deck = [big] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-031", "main")
    for prim in do:
        execute_effect(prim, st, me, opp, None)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "上4枚から コスト4以上のカードが手札に加わっていない"


def test_eb02_031_hope_main_human_search_modal():
    """人間: 上4枚公開の search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-049")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-031", "main")
    execute_effect(do[0], st, me, opp, None)
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "EB01-049" for c in me.hand), \
        "人間が選んだ コスト4以上カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  EB02-032 アイスバーグ: 【登場時】場のドン3以上で 上7枚から「ガレーラカンパニー」
#           1枚まで 手札 + 手札から「ガレーラカンパニー」1枚まで 登場
# --------------------------------------------------------------------------- #
def test_eb02_032_iceburg_on_play_search_and_play_stage_ai():
    """登場時 (場のドン3以上): 上7枚から「ガレーラカンパニー」を手札 → ステージ登場 (AI 自動)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 3
    do, eff = _do(overlay, "EB02-032", "on_play")
    assert eff.get("if", {}).get("self_don_ge") == 3, \
        "overlay の 条件 self_don_ge=3 が無い"
    assert eval_condition(eff["if"], st, me) is True, "場のドン3で 条件が成立していない"

    galera = repo.get("OP03-075")  # ガレーラカンパニー STAGE
    assert galera.category.value == "STAGE"
    me.deck = [galera] + [repo.get("ST01-004")] * 10

    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-032"), sickness=False))
    assert any(s.card.card_id == "OP03-075" for s in me.stages), \
        "「ガレーラカンパニー」がステージに登場していない"


def test_eb02_032_iceburg_condition_fails_under_3_don():
    """場のドンが2枚なら 条件 (self_don_ge=3) は 不成立。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me = st.players[0]
    me.don_active = 2
    _, eff = _do(overlay, "EB02-032", "on_play")
    assert eval_condition(eff["if"], st, me) is False, \
        "場のドン2で 条件が成立してはいけない"


# --------------------------------------------------------------------------- #
#  EB02-033 クラバウターマン: 場に「ゴーイング・メリー号」がある場合【ブロッカー】を得る
# --------------------------------------------------------------------------- #
def test_eb02_033_klabautermann_static_blocker_with_merry():
    """静的: 場に「ゴーイング・メリー号」がある場合 ブロッカーを得る (= is_blocker_now True)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    klab = InPlay.of(repo.get("EB02-033"), sickness=False)
    me.characters = [klab]
    me.stages = [InPlay.of(repo.get("EB02-041"), sickness=False)]  # ゴーイング・メリー号
    evaluate_static_effects(st, overlay)
    assert klab.is_blocker_now is True, \
        "「ゴーイング・メリー号」があるのに ブロッカーを得ていない"


def test_eb02_033_klabautermann_no_blocker_without_merry():
    """静的: 「ゴーイング・メリー号」が無ければ ブロッカーを得ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    klab = InPlay.of(repo.get("EB02-033"), sickness=False)
    me.characters = [klab]
    me.stages = []
    evaluate_static_effects(st, overlay)
    assert klab.is_blocker_now is False, \
        "ステージが無いのに ブロッカーを得てはいけない"


# --------------------------------------------------------------------------- #
#  EB02-035 サンジ&プリン: 【登場時】(自ターン, ターン1回) ドン枚数条件で 1 ドロー /
#           【自分のターン中】ドン2以上デッキ戻り時 ドン1追加
# --------------------------------------------------------------------------- #
def test_eb02_035_sanji_purin_on_play_draw1_ai():
    """登場時: (自ターン中) 1 枚引く。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("ST01-004")] * 5
    me.hand = []

    do, _ = _do(overlay, "EB02-035", "on_play")
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-035"), sickness=False))
    assert len(me.hand) == 1, "登場時の 1 ドローが反映されていない"


def test_eb02_035_sanji_purin_don_returned_add_don():
    """自ドン2以上がデッキに戻った時 (ターン1回): ドンデッキから1枚 アクティブ追加。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.don_active = 0
    me.don_rested = 0
    me.don_remaining_in_deck = 10

    do, eff = _do(overlay, "EB02-035", "on_self_don_returned_to_deck")
    assert eff.get("if", {}).get("returned_don_count_ge") == 2, \
        "overlay の 条件 returned_don_count_ge=2 が無い"
    active_before = me.don_active
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-035"), sickness=False))
    assert me.don_active == active_before + 1, \
        f"add_don 1 が反映されていない: {me.don_active} (before {active_before})"
    assert me.don_remaining_in_deck == 9, "ドンデッキから1枚減っていない"


# --------------------------------------------------------------------------- #
#  EB02-036 ニコ・ロビン: 【ブロッカー】【KO時】ドン-1：上3枚から《麦わらの一味》
#           1枚まで 手札
# --------------------------------------------------------------------------- #
def test_eb02_036_robin_on_ko_search_mugiwara_ai():
    """KO時 (ドン-1 コスト): 上3枚から《麦わらの一味》を手札へ (AI 自動、 do 発火)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay)
    me, opp = st.players[0], st.players[1]
    mugi = repo.get("EB01-046")  # 麦わらの一味 CHARACTER
    assert "麦わらの一味" in (mugi.features or "")
    me.deck = [mugi] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, eff = _do(overlay, "EB02-036", "on_ko")
    assert eff.get("cost", {}).get("pay_don") == 1, \
        "overlay の コスト pay_don=1 が無い"
    for prim in do:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("EB02-036"), sickness=False))
    assert any(c.card_id == "EB01-046" for c in me.hand), \
        "上3枚から《麦わらの一味》が手札に加わっていない"


def test_eb02_036_robin_on_ko_human_search_modal():
    """人間: KO時 search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "OP01-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.deck = [repo.get("EB01-046")] + [repo.get("ST01-004")] * 10
    me.hand = []

    do, _ = _do(overlay, "EB02-036", "on_ko")
    execute_effect(do[0], st, me, opp,
                   InPlay.of(repo.get("EB02-036"), sickness=False))
    assert st.pending_choice is not None, "人間で search modal が立たない"
    assert st.pending_choice.get("kind") == "search_top_n", \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])
    _drain_choices(st)
    assert any(c.card_id == "EB01-046" for c in me.hand), \
        "人間が選んだ《麦わらの一味》が手札に加わっていない"
