# -*- coding: utf-8 -*-
"""ST05 弾 効果 回帰テスト バックフィル (自動生成 wave 168):
ST05-001 / ST05-002 / ST05-004 / ST05-005 / ST05-006 / ST05-008 /
ST05-009 / ST05-010 / ST05-014 / ST05-016 の 10 枚 (紫 FILM)。

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


def _on_play(overlay, cid):
    return next(e for e in overlay.get(cid).effects if e["when"] == "on_play")


def _main(overlay, cid):
    return next(e for e in overlay.get(cid).effects if e["when"] == "main")


def _activate(overlay, cid):
    return next(e for e in overlay.get(cid).effects if e["when"] == "activate_main")


def _when(overlay, cid, when):
    return next(e for e in overlay.get(cid).effects if e["when"] == when)


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_st05_wave168_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST05-001", "ST05-002", "ST05-004", "ST05-005", "ST05-006",
           "ST05-008", "ST05-009", "ST05-010", "ST05-014", "ST05-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST05-001 シャンクス (LEADER): 【起動メイン】【ターン1回】ドン!!-3:
#                                自分の特徴《FILM》キャラすべてを このターン中 +2000
# --------------------------------------------------------------------------- #
def test_st05_001_shanks_activate_pump_all_film_ai():
    """起動メイン (ドン-3): 自分の FILM キャラすべてが +2000。 AI 自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    ain = InPlay.of(repo.get("ST05-002"), sickness=False)     # FILM power5000
    karina = InPlay.of(repo.get("ST05-005"), sickness=False)  # FILM power3000
    me.characters = [ain, karina]
    me.don_active = 3  # ドン-3 コスト用

    ain_before, karina_before = ain.power, karina.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST05-001"]
    assert len(opts) == 1, \
        f"ST05-001 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert ain.power == ain_before + 2000, \
        f"FILM キャラ (アイン) に +2000 が乗っていない: {ain.power}"
    assert karina.power == karina_before + 2000, \
        f"FILM キャラ (カリーナ) に +2000 が乗っていない: {karina.power}"
    assert me.don_active == 0, "ドン-3 のコストが払われていない"


def test_st05_001_shanks_activate_once_per_turn():
    """起動メインは【ターン1回】。 一度発動したら legal から消える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.characters = [InPlay.of(repo.get("ST05-002"), sickness=False)]
    me.don_active = 6

    opts1 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST05-001"]
    assert len(opts1) == 1
    fire_activate_main(st, me, opp, *opts1[0])

    opts2 = [o for o in list_activate_main_effects(st, me, overlay)
             if o[0].card.card_id == "ST05-001"]
    assert len(opts2) == 0, "【ターン1回】の起動メインが再び legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST05-002 アイン: 【登場時】ドン!!デッキからドン!!1枚までをレストで追加
# --------------------------------------------------------------------------- #
def test_st05_002_ain_on_play_add_rested_don_ai():
    """【登場時】 AI: ドンデッキからレストドン1枚を追加 (レストドン +1、 ドンデッキ -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    rested_before = me.don_rested
    deck_don_before = me.don_remaining_in_deck

    src = InPlay.of(repo.get("ST05-002"), sickness=True)
    for prim in _on_play(overlay, "ST05-002")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert me.don_rested == rested_before + 1, "レストドンが1枚追加されていない"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  ST05-004 ウタ: 【ブロッカー】【ブロック時】ドン!!-1: 相手コスト5以下キャラ1枚をレスト
# --------------------------------------------------------------------------- #
def test_st05_004_uta_on_block_rest_cost_le_5_ai():
    """【ブロック時】 AI: 相手コスト5以下キャラ1枚をレストにする。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3 (対象)
    target.rested = False
    opp.characters = [target]

    for prim in _when(overlay, "ST05-004", "on_block")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST05-004"), sickness=False))

    assert target.rested is True, "相手コスト5以下キャラがレストされていない"


def test_st05_004_uta_on_block_human_rest_pick():
    """【ブロック時】 人間 + 相手コスト5以下キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    a.rested = False
    b.rested = False
    opp.characters = [a, b]

    execute_effect(_when(overlay, "ST05-004", "on_block")["do"][0],
                   st, me, opp, InPlay.of(repo.get("ST05-004"), sickness=False))

    assert st.pending_choice is not None, "人間 + 複数候補で rest modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b.rested is True, "人間が選んだキャラがレストされていない"
    assert a.rested is False, "選ばなかったキャラはレストされないべき"


# --------------------------------------------------------------------------- #
#  ST05-005 カリーナ: 【起動メイン】【ターン1回】自レスト + 手札FILM1捨て:
#                     相手場ドン > 自場ドン なら ドン!!デッキからドン!!2枚をレスト追加
# --------------------------------------------------------------------------- #
def test_st05_005_karina_activate_add_rested_don_ai():
    """起動メイン: (相手ドン>自ドン 成立時) レストドン2枚追加。 自レスト + FILM1捨てコスト。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    karina = InPlay.of(repo.get("ST05-005"), sickness=False)
    me.characters = [karina]
    me.hand = [repo.get("ST05-006")]  # FILM カード = 捨てコスト用
    me.don_active = 0                 # 自場ドン 0
    opp.don_active = 4                # 相手場ドン 4 > 自 0 → don_diff_le:-1 成立

    rested_before = me.don_rested
    hand_before = len(me.hand)
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST05-005"]
    assert len(opts) == 1, \
        f"ST05-005 の起動メインが legal に出ない (条件成立時): {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert me.don_rested == rested_before + 2, "レストドンが2枚追加されていない"
    assert karina.rested is True, "コストで自身がレストされるべき"
    assert len(me.hand) == hand_before - 1, "FILM カード1枚が捨てられるべき"


def test_st05_005_karina_activate_not_legal_when_don_not_behind():
    """相手場ドン ≤ 自場ドン なら don_diff_le:-1 不成立 → 起動メインが legal に出ない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    karina = InPlay.of(repo.get("ST05-005"), sickness=False)
    me.characters = [karina]
    me.hand = [repo.get("ST05-006")]  # FILM (コストは払えるが条件不成立)
    me.don_active = 4                 # 自場ドン 4
    opp.don_active = 0                # 相手場ドン 0 (= 自分の方が多い)

    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST05-005"]
    assert len(opts) == 0, \
        "相手ドンが多くないのに起動メインが legal に出てはいけない"


# --------------------------------------------------------------------------- #
#  ST05-006 ギルド・テゾーロ: 【アタック時】ドン!!-2: カード2枚を引く
# --------------------------------------------------------------------------- #
def test_st05_006_gild_tesoro_attack_draw2_ai():
    """【アタック時】 AI: カード2枚を引く (手札 +2、 デッキ -2)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    for prim in _when(overlay, "ST05-006", "on_attack")["do"]:
        execute_effect(prim, st, me, opp,
                       InPlay.of(repo.get("ST05-006"), sickness=False))

    assert len(me.hand) == hand_before + 2, "アタック時に2枚引けていない"
    assert len(me.deck) == deck_before - 2, "デッキが2枚減っていない"


# --------------------------------------------------------------------------- #
#  ST05-008 シキ: 自分の場にドン!!が8枚以上ある場合、 バトルでKOされない (静的)
# --------------------------------------------------------------------------- #
def test_st05_008_shiki_battle_ko_immune_when_8_don():
    """静的: 自場ドン8枚以上 → battle_ko_immune_static が立つ。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    shiki = InPlay.of(repo.get("ST05-008"), sickness=False)
    me.characters = [shiki]
    me.don_active = 8  # 自場ドン 8 (= 条件成立)

    evaluate_static_effects(st, overlay)
    assert shiki.battle_ko_immune_static is True, \
        "ドン8枚でバトルKO耐性 (battle_ko_immune_static) が立っていない"


def test_st05_008_shiki_no_immune_when_under_8_don():
    """静的: 自場ドン7枚以下 → 条件不成立で KO 耐性は立たない。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    shiki = InPlay.of(repo.get("ST05-008"), sickness=False)
    me.characters = [shiki]
    me.don_active = 7  # 自場ドン 7 (= 条件不成立)

    evaluate_static_effects(st, overlay)
    assert shiki.battle_ko_immune_static is False, \
        "ドン7枚 (8未満) で KO 耐性が立ってはいけない"


# --------------------------------------------------------------------------- #
#  ST05-009 スカーレット: 【トリガー】このカードを登場させる (play_self)
# --------------------------------------------------------------------------- #
def test_st05_009_scarlet_trigger_play_self_ai():
    """【トリガー】 AI: 手札 (ライフ由来) の このカードを場に登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("ST05-009")]  # トリガー由来のカード
    st.current_source_card_id = "ST05-009"
    chars_before = len(me.characters)

    for prim in _when(overlay, "ST05-009", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.characters) == chars_before + 1, \
        "トリガーで スカーレットが場に登場していない"
    assert any(c.card.card_id == "ST05-009" for c in me.characters), \
        "登場したキャラが スカーレットでない"


# --------------------------------------------------------------------------- #
#  ST05-010 ゼット: 属性(打)キャラとのバトル時 +3000 (静的) /
#                   【起動メイン】【ターン1回】ドン!!-1: 自身 +2000
# --------------------------------------------------------------------------- #
def test_st05_010_z_static_battle_pump_vs_uchi():
    """静的: 属性(打)キャラとバトルする時 +3000 (battle_pump_vs_attribute)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    z = InPlay.of(repo.get("ST05-010"), sickness=False)
    me.characters = [z]

    evaluate_static_effects(st, overlay)
    assert z.battle_pump_vs_attribute.get("打") == 3000, \
        f"属性(打)へのバトル +3000 が設定されていない: {z.battle_pump_vs_attribute}"


def test_st05_010_z_activate_self_pump_ai():
    """起動メイン (ドン-1): 自身に このターン中 +2000。 AI 自動発動。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    z = InPlay.of(repo.get("ST05-010"), sickness=False)
    me.characters = [z]
    me.don_active = 1

    power_before = z.power
    opts = [o for o in list_activate_main_effects(st, me, overlay)
            if o[0].card.card_id == "ST05-010"]
    assert len(opts) == 1, \
        f"ST05-010 の起動メインが legal に出ない: {len(opts)}"
    fire_activate_main(st, me, opp, *opts[0])

    assert z.power == power_before + 2000, \
        f"起動メインの自己 +2000 が反映されていない: {z.power}"
    assert me.don_active == 0, "ドン-1 のコストが払われていない"


# --------------------------------------------------------------------------- #
#  ST05-014 ブエナ・フェスタ: 【登場時】デッキ上5枚を見て「ブエナ・フェスタ」以外の
#            特徴《FILM》1枚までを公開手札 → 残りを好きな順でデッキ下
# --------------------------------------------------------------------------- #
def test_st05_014_buena_festa_on_play_search_film_ai():
    """【登場時】 AI: デッキ上5枚から FILM カード1枚を手札に加える。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    film_card = repo.get("ST05-006")  # FILM
    assert "FILM" in (film_card.features or ""), "テスト前提: ST05-006 は FILM"
    me.deck = [film_card] + [repo.get("OP01-013")] * 20  # 上5枚に FILM を仕込む
    me.hand = []

    src = InPlay.of(repo.get("ST05-014"), sickness=True)
    for prim in _on_play(overlay, "ST05-014")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert any(c.card_id == "ST05-006" for c in me.hand), \
        "デッキ上5枚から FILM カードが手札に加わっていない"


def test_st05_014_buena_festa_on_play_human_search_pick():
    """【登場時】 人間 + デッキ上5枚に FILM 候補 → search_top_n modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    film_a = repo.get("ST05-006")  # FILM
    film_b = repo.get("ST05-002")  # FILM
    me.deck = [film_a, repo.get("OP01-013"), film_b] + [repo.get("OP01-013")] * 15
    me.hand = []

    src = InPlay.of(repo.get("ST05-014"), sickness=True)
    execute_effect(_on_play(overlay, "ST05-014")["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 候補で search_top_n modal が立たない"
    assert "search_top_n" in st.pending_choice.get("kind", ""), \
        f"kind が search_top_n でない: {st.pending_choice.get('kind')}"
    resolve_pending_choice(st, [0])  # 先頭候補 (FILM) を選択
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [])
        guard += 1
    assert any(c.features and "FILM" in c.features for c in me.hand), \
        "人間が選んだ FILM カードが手札に加わっていない"


# --------------------------------------------------------------------------- #
#  ST05-016 獅子威し御所地巻き (EVENT): 【メイン】ドン!!-2: 相手コスト5以下キャラ1枚KO /
#            【トリガー】ドン!!デッキからドン!!1枚までをアクティブ追加
# --------------------------------------------------------------------------- #
def test_st05_016_shishioD_main_ko_cost_le_5_ai():
    """【メイン】 AI: 相手コスト5以下キャラをKO。 コスト6以上は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("ST05-006"), sickness=False)  # cost5 (対象)
    safe = InPlay.of(repo.get("ST05-010"), sickness=False)    # ゼット cost7 (対象外)
    opp.characters = [target, safe]

    for prim in _main(overlay, "ST05-016")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert target not in opp.characters, "相手コスト5以下キャラがKOされていない"
    assert safe in opp.characters, "コスト6以上のキャラはKO対象外であるべき"


def test_st05_016_shishioD_main_human_ko_pick():
    """【メイン】 人間 + 相手コスト5以下キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST05-006"), sickness=False)  # cost5
    b = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    opp.characters = [a, b]

    execute_effect(_main(overlay, "ST05-016")["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補が2体でない: {len(cands)}"

    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [a_idx])
        guard += 1
    assert a not in opp.characters, "人間が選んだキャラがKOされていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


def test_st05_016_shishioD_trigger_add_don_ai():
    """【トリガー】 AI: ドンデッキからドン1枚をアクティブ追加 (ドンアクティブ +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST05-001", overlay)
    me, opp = st.players[0], st.players[1]
    don_before = me.don_active
    deck_don_before = me.don_remaining_in_deck

    for prim in _when(overlay, "ST05-016", "trigger")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.don_active == don_before + 1, "トリガーでドンがアクティブ追加されていない"
    assert me.don_remaining_in_deck == deck_don_before - 1, \
        "ドンデッキが1枚減っていない"
