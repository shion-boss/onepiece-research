# -*- coding: utf-8 -*-
"""ST04 弾 効果 回帰テスト バックフィル (自動生成 wave 167):
ST04-002 / ST04-003 / ST04-004 / ST04-005 / ST04-006 / ST04-008 /
ST04-010 / ST04-014 / ST04-015 / ST04-016 の 10 枚 (紫 百獣海賊団)。

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
    execute_effect,
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


def _counter(overlay, cid):
    return next(e for e in overlay.get(cid).effects if e["when"] == "counter")


# --------------------------------------------------------------------------- #
#  overlay 整合 (= 効果が overlay に登録されているかの sanity guard)
# --------------------------------------------------------------------------- #
def test_all_st04_wave167_cards_have_overlay():
    """10 枚すべてが cards.json に存在し、 overlay bundle を持つ (= 空でない効果)。"""
    repo = _repo()
    overlay = _overlay()
    ids = ["ST04-002", "ST04-003", "ST04-004", "ST04-005", "ST04-006",
           "ST04-008", "ST04-010", "ST04-014", "ST04-015", "ST04-016"]
    for cid in ids:
        card = repo.get(cid)
        assert card is not None, f"{cid} が cards.json に存在しない"
        bundle = overlay.get(cid)
        assert bundle is not None and len(bundle.effects) > 0, \
            f"{cid} の overlay 効果が空"


# --------------------------------------------------------------------------- #
#  ST04-002 うるティ: 【登場時】ドン!!-1: 手札のコスト4以下「ページワン」1枚までを登場
# --------------------------------------------------------------------------- #
def test_st04_002_ulti_on_play_summon_pageone_ai():
    """【登場時】 AI: 手札のコスト4以下ページワン1枚を登場させる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)  # カイドウ&ビッグ・マム leader
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-112")]  # ページワン 紫 cost4
    chars_before = len(me.characters)
    hand_before = len(me.hand)

    src = InPlay.of(repo.get("ST04-002"), sickness=True)
    for prim in _on_play(overlay, "ST04-002")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.characters) == chars_before + 1, \
        "ページワンが場に登場していない"
    assert any(c.card.card_id == "OP01-112" for c in me.characters), \
        "登場したキャラがページワンでない"
    assert len(me.hand) == hand_before - 1, "手札からページワンが1枚出るべき"


def test_st04_002_ulti_on_play_human_pick():
    """【登場時】 人間 + ページワン 複数候補 → play_from_hand_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    # 2 枚のページワン (cost4 以下) を手札に = 候補 > limit(1) で modal
    me.hand = [repo.get("OP01-112"), repo.get("ST04-012")]

    src = InPlay.of(repo.get("ST04-002"), sickness=True)
    execute_effect(_on_play(overlay, "ST04-002")["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 複数候補で play_from_hand modal が立たない"
    assert st.pending_choice.get("kind") == "play_from_hand_pick", \
        f"kind が play_from_hand_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (ページワン2枚) が 2 件でない: {len(cands)}"

    resolve_pending_choice(st, [0])  # 先頭候補を登場
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [0])
        guard += 1
    assert any(c.card.name == "ページワン" for c in me.characters), \
        "人間が選んだページワンが登場していない"


# --------------------------------------------------------------------------- #
#  ST04-003 カイドウ: 【登場時】ドン!!-5: 相手コスト6以下キャラ1枚KO + 自身に速攻
# --------------------------------------------------------------------------- #
def test_st04_003_kaido_on_play_ko_and_rush_ai():
    """【登場時】 AI: 相手コスト6以下キャラ1枚KO + 自身(カイドウ)は速攻を得る。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3
    opp.characters = [victim]
    kaido = InPlay.of(repo.get("ST04-003"), sickness=True)
    me.characters = [kaido]

    for prim in _on_play(overlay, "ST04-003")["do"]:
        execute_effect(prim, st, me, opp, kaido)

    assert victim not in opp.characters, "相手コスト6以下キャラがKOされていない"
    assert "速攻" in kaido.granted_keywords, "カイドウ自身が速攻を得ていない"


def test_st04_003_kaido_on_play_human_ko_pick():
    """【登場時】 人間 + 相手キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ cost1
    opp.characters = [a, b]
    kaido = InPlay.of(repo.get("ST04-003"), sickness=True)
    me.characters = [kaido]

    execute_effect(_on_play(overlay, "ST04-003")["do"][0], st, me, opp, kaido)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
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
    assert b not in opp.characters, "人間が選んだキャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST04-004 キング: 【登場時】ドン!!-1: 相手コスト4以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_st04_004_king_on_play_ko_cost_le_4_ai():
    """【登場時】 AI: 相手コスト4以下キャラをKO。 コスト5以上は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3 (対象)
    safe = InPlay.of(repo.get("ST04-005"), sickness=False)    # クイーン cost5 (対象外)
    opp.characters = [target, safe]

    src = InPlay.of(repo.get("ST04-004"), sickness=True)
    for prim in _on_play(overlay, "ST04-004")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert target not in opp.characters, "相手コスト4以下キャラがKOされていない"
    assert safe in opp.characters, "コスト5のキャラはKO対象外であるべき"


def test_st04_004_king_on_play_human_ko_pick():
    """【登場時】 人間 + コスト4以下 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    src = InPlay.of(repo.get("ST04-004"), sickness=True)
    execute_effect(_on_play(overlay, "ST04-004")["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    a_idx = next(i for i, c in enumerate(cands) if c["iid"] == a.instance_id)
    resolve_pending_choice(st, [a_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [a_idx])
        guard += 1
    assert a not in opp.characters, "人間が選んだキャラがKOされていない"
    assert b in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST04-005 クイーン: 【ブロッカー】【登場時】ドン!!-1: 2枚引き、手札1枚を捨てる
# --------------------------------------------------------------------------- #
def test_st04_005_queen_on_play_draw2_discard1_ai():
    """【登場時】 AI: カード2枚を引き、 手札1枚を捨てる (net +1、 トラッシュ +1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨て候補用に 1 枚
    hand_before = len(me.hand)
    trash_before = len(me.trash)
    deck_before = len(me.deck)

    src = InPlay.of(repo.get("ST04-005"), sickness=True)
    for prim in _on_play(overlay, "ST04-005")["do"]:
        execute_effect(prim, st, me, opp, src)

    # +2 draw -1 discard = net +1
    assert len(me.hand) == hand_before + 1, \
        f"手札 net (+2引き -1捨て) が +1 でない: {len(me.hand)}"
    assert len(me.trash) == trash_before + 1, "捨てた1枚がトラッシュに置かれていない"
    assert len(me.deck) == deck_before - 2, "デッキから2枚引かれていない"


# --------------------------------------------------------------------------- #
#  ST04-006 ササキ: 【登場時】ドン!!-1: カード1枚を引く
# --------------------------------------------------------------------------- #
def test_st04_006_sasaki_on_play_draw1_ai():
    """【登場時】 AI: カード1枚を引く (手札 +1、 デッキ -1)。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)
    deck_before = len(me.deck)

    src = InPlay.of(repo.get("ST04-006"), sickness=True)
    for prim in _on_play(overlay, "ST04-006")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert len(me.hand) == hand_before + 1, "1枚引けていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"


# --------------------------------------------------------------------------- #
#  ST04-008 ジャック: 【登場時】手札1枚捨てられる: ドンデッキからドン1枚アクティブ追加
# --------------------------------------------------------------------------- #
def test_st04_008_jack_on_play_optional_add_don_ai():
    """【登場時】 AI: 手札1枚を捨てて (任意コスト) ドン1枚をアクティブ追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]  # 捨てるコスト用
    hand_before = len(me.hand)
    don_before = me.don_active

    src = InPlay.of(repo.get("ST04-008"), sickness=True)
    for prim in _on_play(overlay, "ST04-008")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert me.don_active == don_before + 1, "ドンがアクティブで1枚追加されていない"
    assert len(me.hand) == hand_before - 1, "任意コストで手札1枚が捨てられるべき"


def test_st04_008_jack_on_play_human_optional_confirm():
    """【登場時】 人間: 任意コスト → optional_cost_confirm modal が立ち、 承諾で発動する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    me.hand = [repo.get("OP01-013")]
    hand_before = len(me.hand)
    don_before = me.don_active

    src = InPlay.of(repo.get("ST04-008"), sickness=True)
    execute_effect(_on_play(overlay, "ST04-008")["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 任意コストで modal が立たない"
    assert st.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {st.pending_choice.get('kind')}"

    resolve_pending_choice(st, [1])  # 承諾 (= コストを払って発動)
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [1])
        guard += 1
    assert me.don_active == don_before + 1, "承諾後 ドンが1枚追加されていない"
    assert len(me.hand) == hand_before - 1, "承諾後 手札1枚が捨てられるべき"


# --------------------------------------------------------------------------- #
#  ST04-010 フーズ・フー: 【登場時】ドン!!-1: 相手コスト3以下キャラ1枚KO
# --------------------------------------------------------------------------- #
def test_st04_010_whos_who_on_play_ko_cost_le_3_ai():
    """【登場時】 AI: 相手コスト3以下キャラをKO。 コスト4以上は対象外。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    target = InPlay.of(repo.get("OP01-025"), sickness=False)  # ゾロ cost3 (対象)
    safe = InPlay.of(repo.get("ST04-004"), sickness=False)    # キング cost6 (対象外)
    opp.characters = [target, safe]

    src = InPlay.of(repo.get("ST04-010"), sickness=True)
    for prim in _on_play(overlay, "ST04-010")["do"]:
        execute_effect(prim, st, me, opp, src)

    assert target not in opp.characters, "相手コスト3以下キャラがKOされていない"
    assert safe in opp.characters, "コスト4以上のキャラはKO対象外であるべき"


def test_st04_010_whos_who_on_play_human_ko_pick():
    """【登場時】 人間 + コスト3以下 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    b = InPlay.of(repo.get("OP01-016"), sickness=False)  # cost1
    opp.characters = [a, b]

    src = InPlay.of(repo.get("ST04-010"), sickness=True)
    execute_effect(_on_play(overlay, "ST04-010")["do"][0], st, me, opp, src)

    assert st.pending_choice is not None, "人間 + 複数候補で KO modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    b_idx = next(i for i, c in enumerate(cands) if c["iid"] == b.instance_id)
    resolve_pending_choice(st, [b_idx])
    guard = 0
    while st.pending_choice is not None and guard < 5:
        resolve_pending_choice(st, [b_idx])
        guard += 1
    assert b not in opp.characters, "人間が選んだキャラがKOされていない"
    assert a in opp.characters, "選ばなかったキャラは残るべき"


# --------------------------------------------------------------------------- #
#  ST04-014 大看板"災害" (EVENT): 【メイン】カード1枚引き + ドン1枚アクティブ追加
# --------------------------------------------------------------------------- #
def test_st04_014_saigai_main_draw_and_add_don_ai():
    """【メイン】 AI: カード1枚を引き、 ドン1枚をアクティブ追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    me.hand = []
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    don_before = me.don_active

    for prim in _main(overlay, "ST04-014")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert len(me.hand) == hand_before + 1, "1枚引けていない"
    assert len(me.deck) == deck_before - 1, "デッキが1枚減っていない"
    assert me.don_active == don_before + 1, "ドンが1枚アクティブ追加されていない"


# --------------------------------------------------------------------------- #
#  ST04-015 無頼男爆弾 (EVENT): 【メイン】相手コスト6以下キャラ1枚KO + ドン1枚追加
# --------------------------------------------------------------------------- #
def test_st04_015_franosuke_bomb_main_ko_and_add_don_ai():
    """【メイン】 AI: 相手コスト6以下キャラ1枚をKOし、 ドン1枚をアクティブ追加する。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    victim = InPlay.of(repo.get("ST04-004"), sickness=False)  # キング cost6 (対象)
    opp.characters = [victim]
    don_before = me.don_active

    for prim in _main(overlay, "ST04-015")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert victim not in opp.characters, "相手コスト6以下キャラがKOされていない"
    assert me.don_active == don_before + 1, "ドンが1枚アクティブ追加されていない"


def test_st04_015_franosuke_bomb_main_human_ko_pick():
    """【メイン】 人間 + 相手キャラ 複数 → KO の target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    a = InPlay.of(repo.get("ST04-004"), sickness=False)  # cost6
    b = InPlay.of(repo.get("OP01-025"), sickness=False)  # cost3
    opp.characters = [a, b]

    # do は [add_don, ko] 順。 ko prim を取り出して modal を確認する。
    ko_prim = next(p for p in _main(overlay, "ST04-015")["do"] if "ko" in p)
    execute_effect(ko_prim, st, me, opp, None)

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


# --------------------------------------------------------------------------- #
#  ST04-016 熱息 (EVENT): 【カウンター】ドン!!-1: 自リーダー/キャラ1枚 +4000
# --------------------------------------------------------------------------- #
def test_st04_016_nessoku_counter_pump_ai():
    """【カウンター】 AI: 自リーダー(既定)にこのバトル中パワー+4000。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay)
    me, opp = st.players[0], st.players[1]
    power_before = me.leader.power

    for prim in _counter(overlay, "ST04-016")["do"]:
        execute_effect(prim, st, me, opp, None)

    assert me.leader.power == power_before + 4000, \
        f"カウンターの +4000 が自リーダーに反映されていない: {me.leader.power}"


def test_st04_016_nessoku_counter_pump_human_pick():
    """【カウンター】 人間 + 自リーダー/キャラ 複数 → target_pick modal が立ち resolve できる。"""
    repo = _repo()
    overlay = _overlay()
    st = _state(repo, "ST04-001", overlay, human_idx=0)
    me, opp = st.players[0], st.players[1]
    friend = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [friend]

    execute_effect(_counter(overlay, "ST04-016")["do"][0], st, me, opp, None)

    assert st.pending_choice is not None, "人間 + 複数候補で target_pick modal が立たない"
    assert st.pending_choice.get("kind") == "target_pick", \
        f"kind が target_pick でない: {st.pending_choice.get('kind')}"
    cands = st.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"候補 (リーダー+キャラ) が 2 件でない: {len(cands)}"

    friend_idx = next(i for i, c in enumerate(cands) if c["iid"] == friend.instance_id)
    friend_before = friend.power
    resolve_pending_choice(st, [friend_idx])
    assert st.pending_choice is None, "解決後も modal が残る"
    assert friend.power == friend_before + 4000, \
        "人間が選んだキャラに +4000 が反映されていない"
