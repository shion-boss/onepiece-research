# -*- coding: utf-8 -*-
"""ST-32 (緑ゾロ スタートデッキ) 新カード ST32-001〜005 の効果 回帰テスト。

保証する不変条件:
  1. 各カードの効果が **公式テキスト通り** に発火する (盤面変化を assert)。
  2. 対象選択を持つ効果は **人間 actor で pending_choice が正しく立ち、 resolve できる**
     (= 人間が選べる)。
  3. **AI 文脈 (human_player_idx なし) では crash せず 自動解決** される (= AI も選べる)。

ST32-001 錦えもん   : _unimplemented (OR-cost)。 効果本体は skip、 存在 + crash なし のみ確認。
ST32-002 光月おでん : 登場時 draw1 + 相手コスト6以下キャラ1枚まで レスト不能 (次相手END迄)。
ST32-003 ミホーク   : 自ターン中レスト時 draw+discard / 登場時(斬leader) 手札から
                       cost5以下「ペローナ」or斬キャラ 1枚まで登場。
ST32-004 レイリー   : (斬leader) 速攻:キャラ 付与 / 登場時 相手コスト2以下キャラ 2枚まで レスト。
ST32-005 ロロノア・ゾロ: 速攻:キャラ / 登場時(斬leader) 相手コスト2以下キャラ 1枚まで レスト。
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
    trigger_on_play,
    trigger_on_self_rested,
    evaluate_static_effects,
)

ROOT = Path(__file__).resolve().parent.parent

# 属性(斬) を持つ リーダー / 持たない リーダー
ZAN_LEADER = "EB01-001"       # 光月おでん (斬, 赤/緑)
NON_ZAN_LEADER = "EB02-010"   # モンキー・D・ルフィ (打)

# 低コスト 相手キャラ 素材
C_COST1 = "OP01-016"   # ナミ cost1
C_COST2 = "OP01-013"   # サンジ cost2
C_COST2B = "ST21-005"  # ジンベエ cost2
C_COST3 = "OP01-025"   # ロロノア・ゾロ cost3
C_COST4 = "OP11-015"   # モチャ cost4
C_COST7 = "OP02-013"   # エース cost7


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_state(repo, overlay, leader_id=ZAN_LEADER, human_idx=None):
    """P0 = テスト対象カードの owner (turn player)。 human_idx で 人間 acting を設定。"""
    p0 = Player(name="P0", leader=InPlay.of(repo.get(leader_id), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.deck = [repo.get("OP01-013")] * 30
    p1.deck = [repo.get("OP01-013")] * 30
    state = GameState(
        players=[p0, p1],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay,
    )
    state.turn_player_idx = 0
    if human_idx is not None:
        state.human_player_idx = human_idx
    return state


def _play_chara(state, repo, owner_idx, card_id, overlay, fire=True):
    """card を owner の場に登場させ、 on_play を発火 (fire=True)。 登場 InPlay を返す。"""
    owner = state.players[owner_idx]
    opp = state.players[1 - owner_idx]
    ip = InPlay.of(repo.get(card_id), sickness=True)
    owner.characters.append(ip)
    if fire:
        trigger_on_play(state, owner, opp, ip, overlay)
    return ip


# ===========================================================================
# ST32-001 錦えもん: 【登場時】斬leaderかDON1枚レスト(任意OR-cost) → 2ドロー+手札1捨て
# ===========================================================================
def test_st32_001_on_play_or_cost_draw_discard_ai_auto():
    """AI 自動: OR-cost を DON 優先で払い、 カード2枚引き手札1枚捨てる (net +1)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay)  # AI acting (human_idx=None), 斬 leader
    me = state.players[0]
    me.don_active = 3
    me.hand = [repo.get("OP01-013")]  # 捨てる用に1枚
    hand_before = len(me.hand)

    _play_chara(state, repo, 0, "ST32-001", overlay)

    assert state.pending_choice is None, "AI auto は modal を立てない"
    # OR-cost = DON 優先 rest (= リーダーは攻撃用に温存)
    assert me.don_active == 2 and me.don_rested == 1, \
        f"DON!!1枚がレストされていない: active={me.don_active} rested={me.don_rested}"
    assert not me.leader.rested, "DON で払えるので 斬リーダーはレストされない"
    # draw 2 - discard 1 = net +1
    assert len(me.hand) == hand_before + 1, f"draw2+discard1 の net (+1) が合わない: {len(me.hand)}"


def test_st32_001_or_cost_rests_zan_leader_when_no_don():
    """DON が無ければ 斬リーダーをレストして払う (OR-cost の leader 側)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay)  # 斬 leader EB01-001 (アクティブ)
    me = state.players[0]
    me.don_active = 0
    me.hand = [repo.get("OP01-013")]
    assert not me.leader.rested
    _play_chara(state, repo, 0, "ST32-001", overlay)
    assert me.leader.rested, "DON 無しで 斬リーダーがレストされていない"
    assert len(me.hand) == 1 + 1, "leader-cost でも draw2+discard1 の net(+1) が起きる"


def test_st32_001_no_fire_without_payable_cost():
    """DON も無く、 斬でないリーダー → OR-cost 払えず 効果不発 (手札不変)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=NON_ZAN_LEADER)  # 打リーダー
    me = state.players[0]
    me.don_active = 0
    me.hand = [repo.get("OP01-013")]
    hand_before = len(me.hand)
    _play_chara(state, repo, 0, "ST32-001", overlay)
    assert len(me.hand) == hand_before, "払えないコストで効果が発動している"
    assert not me.leader.rested, "非斬リーダーはレストされない"


def test_st32_001_human_optional_cost_confirm_modal():
    """人間 actor: 任意コストの confirm modal が立つ (人間が pay/skip を選べる)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=0)
    me = state.players[0]
    me.don_active = 3
    me.hand = [repo.get("OP01-013")]
    _play_chara(state, repo, 0, "ST32-001", overlay)
    assert state.pending_choice is not None, "人間 + 任意コストで confirm modal が立たない"
    assert state.pending_choice.get("kind") == "optional_cost_confirm", \
        f"kind が optional_cost_confirm でない: {state.pending_choice.get('kind')}"


# ===========================================================================
# ST32-002 光月おでん: draw1 + 相手コスト6以下キャラ1枚まで レスト不能
# ===========================================================================
def test_st32_002_draw_and_cannot_rest_single_target_ai_auto():
    """相手キャラ が 1 枚 (候補=対象上限) の 場合、 AI 文脈 で 自動適用: draw1 + その1枚 レスト不能。
    (人間 acting では 候補 1 枚 でも 「対象を取るか」 を選ばせる modal が立つ = 下の human テスト参照。)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=None)  # AI
    me = state.players[0]
    opp = state.players[1]
    opp.characters = [InPlay.of(repo.get(C_COST4), sickness=False)]  # cost4 (≤6) が唯一
    hand_before = len(me.hand)

    _play_chara(state, repo, 0, "ST32-002", overlay)

    assert state.pending_choice is None, "AI は modal を出さない"
    assert len(me.hand) == hand_before + 1, "登場時 draw 1"
    target = opp.characters[0]
    assert target.cannot_be_rested_buff, "コスト6以下キャラが レスト不能 になる"


def test_st32_002_human_picks_single_candidate():
    """人間 acting: 候補 1 枚 でも 「N 枚まで」 の 決定権 を 人間 に (target_pick が 立つ)。
    唯一の候補を選ぶと レスト不能 が適用され、 draw1 も 実行される。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=0)
    me = state.players[0]
    opp = state.players[1]
    opp.characters = [InPlay.of(repo.get(C_COST4), sickness=False)]
    hand_before = len(me.hand)

    _play_chara(state, repo, 0, "ST32-002", overlay)

    assert state.pending_choice is not None, "人間 acting → 決定権を渡す modal"
    assert state.pending_choice.get("kind") == "target_pick"
    assert len(me.hand) == hand_before + 1, "draw1 は modal 前に 実行済"
    resolve_pending_choice(state, [0])
    assert state.pending_choice is None
    assert opp.characters[0].cannot_be_rested_buff, "選んだ 1 枚が レスト不能"


def test_st32_002_human_picks_cannot_rest_target():
    """相手キャラ が 複数 (候補 > 上限1) + 人間 acting → target_pick が 立ち、 選んだ 1 枚に付与。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=0)
    me = state.players[0]
    opp = state.players[1]
    # コスト6以下 が 2 枚 (cost2, cost4) + 対象外 cost7 が 1 枚
    opp.characters = [
        InPlay.of(repo.get(C_COST2), sickness=False),   # idx0 cost2
        InPlay.of(repo.get(C_COST4), sickness=False),   # idx1 cost4
        InPlay.of(repo.get(C_COST7), sickness=False),   # idx2 cost7 (対象外)
    ]

    _play_chara(state, repo, 0, "ST32-002", overlay)

    assert state.pending_choice is not None, "人間 + 候補 > 1 → modal (人間が選べる)"
    assert state.pending_choice.get("kind") == "target_pick", state.pending_choice.get("kind")
    cands = state.pending_choice.get("candidates", [])
    cand_ids = {c.get("card_id") for c in cands}
    assert cand_ids == {C_COST2, C_COST4}, f"候補は コスト6以下の2枚のみ: {cand_ids}"

    # 人間が cost4 (候補 idx1) を選択
    pick = next(i for i, c in enumerate(cands) if c["card_id"] == C_COST4)
    resolve_pending_choice(state, [pick])
    assert state.pending_choice is None
    chosen = next(c for c in opp.characters if c.card.card_id == C_COST4)
    other = next(c for c in opp.characters if c.card.card_id == C_COST2)
    assert chosen.cannot_be_rested_buff, "選んだ cost4 が レスト不能"
    assert not other.cannot_be_rested_buff, "選ばなかった cost2 は 影響なし"


def test_st32_002_ai_auto_resolves_no_modal():
    """AI 文脈 (human なし): modal を出さず crash せず、 draw1 + レスト不能 が 適用される。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=None)  # AI
    me = state.players[0]
    opp = state.players[1]
    opp.characters = [
        InPlay.of(repo.get(C_COST2), sickness=False),
        InPlay.of(repo.get(C_COST4), sickness=False),
    ]
    hand_before = len(me.hand)

    _play_chara(state, repo, 0, "ST32-002", overlay)

    assert state.pending_choice is None, "AI は modal を出さない"
    assert len(me.hand) == hand_before + 1, "draw 1"
    n_locked = sum(1 for c in opp.characters if c.cannot_be_rested_buff)
    assert n_locked == 1, f"上限1枚だけ レスト不能 (AI 自動): {n_locked}"


# ===========================================================================
# ST32-003 ミホーク: on_self_rested(自ターン) draw+discard / on_play(斬) 手札から登場
# ===========================================================================
def test_st32_003_on_self_rested_draw_discard():
    """自ターン中に ミホークが レストになった時: draw1 + 手札1枚捨て (差引 手札 不変、 デッキ-1)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay)  # 自ターン (turn_player=0)
    me = state.players[0]
    opp = state.players[1]
    me.hand = [repo.get(C_COST1), repo.get(C_COST2)]  # 捨てる 札あり
    hand_before = len(me.hand)
    deck_before = len(me.deck)
    mihawk = InPlay.of(repo.get("ST32-003"), sickness=False)
    me.characters = [mihawk]

    trigger_on_self_rested(state, me, opp, mihawk, overlay)

    assert len(me.hand) == hand_before, "draw1 + discard1 で 手札 枚数 は 不変"
    assert len(me.deck) == deck_before - 1, "draw で デッキ -1"
    assert len(me.trash) == 1, "discard で トラッシュ +1"


def test_st32_003_on_play_summons_zan_from_hand_human_pick():
    """登場時 (斬leader): 手札の cost5以下「ペローナ」/斬キャラ 1枚まで登場。
    候補 > 1 + 人間 → play_from_hand_pick が 立つ (人間が選べる)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=ZAN_LEADER, human_idx=0)
    me = state.players[0]
    # 斬キャラ 2 枚 を 手札に (= 候補 > limit1)
    me.hand = [repo.get("ST32-005"), repo.get("ST32-001")]  # 共に 斬 cost1

    ip = _play_chara(state, repo, 0, "ST32-003", overlay)

    assert state.pending_choice is not None, "人間 + 候補 > 1 → modal"
    assert state.pending_choice.get("kind") == "play_from_hand_pick", state.pending_choice.get("kind")
    cands = state.pending_choice.get("candidates", [])
    assert len(cands) == 2, f"斬キャラ2枚が候補: {cands}"

    # 人間が ST32-005 を登場させる
    pick = next(i for i, c in enumerate(cands) if c["card_id"] == "ST32-005")
    chara_before = len([c for c in me.characters])
    resolve_pending_choice(state, [pick])
    assert state.pending_choice is None
    played_ids = [c.card.card_id for c in me.characters]
    assert "ST32-005" in played_ids, "選んだ 斬キャラ が 登場"
    assert "ST32-005" not in [c.card_id for c in me.hand], "手札 から 抜けている"


def test_st32_003_on_play_requires_zan_leader():
    """斬 でない リーダーでは on_play の登場効果は発火しない (条件 leader_attribute 斬)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=NON_ZAN_LEADER, human_idx=0)
    me = state.players[0]
    me.hand = [repo.get("ST32-005"), repo.get("ST32-001")]
    hand_before = len(me.hand)

    _play_chara(state, repo, 0, "ST32-003", overlay)

    assert state.pending_choice is None, "非斬leader ⇒ 登場効果 不発 ⇒ modal なし"
    # ミホーク 自身のみ増え、 手札の斬キャラは 場に出ない
    assert len(me.hand) == hand_before, "手札 不変 (登場効果 不発)"
    assert "ST32-005" not in [c.card.card_id for c in me.characters]


def test_st32_003_on_play_ai_auto_summons():
    """AI 文脈: 斬leader で 候補 > 1 でも crash せず 自動で 1 枚 登場。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=ZAN_LEADER, human_idx=None)  # AI
    me = state.players[0]
    me.hand = [repo.get("ST32-005"), repo.get("ST32-001")]

    _play_chara(state, repo, 0, "ST32-003", overlay)

    assert state.pending_choice is None, "AI は modal を出さない"
    # ミホーク + 手札から 1 枚 = 場に 2 体、 手札 1 枚 に 減
    played = [c.card.card_id for c in me.characters]
    n_summoned = sum(1 for cid in ("ST32-005", "ST32-001") if cid in played)
    assert n_summoned == 1, f"AI が 1 枚だけ 自動登場: {played}"
    assert len(me.hand) == 1, "手札 は 2→1"


# ===========================================================================
# ST32-004 レイリー: (斬leader)速攻:キャラ 付与 / 登場時 相手コスト2以下2枚レスト
# ===========================================================================
def test_st32_004_rush_chara_granted_with_zan_leader():
    """斬leader + ドン付与 (on_attached_don n=0) で 【速攻:キャラ】を 得る (登場ターンにキャラへアタック可)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=ZAN_LEADER)
    me = state.players[0]
    reilly = InPlay.of(repo.get("ST32-004"), sickness=True)
    me.characters = [reilly]

    evaluate_static_effects(state, overlay)
    assert reilly.is_rush_chara_only_now, "斬leader なら 速攻:キャラ を 得る"
    assert not reilly.is_rush_now, "通常の 速攻 (リーダー攻撃可) では ない"


def test_st32_004_no_rush_without_zan_leader():
    """非斬leader では 速攻:キャラ を 得ない。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=NON_ZAN_LEADER)
    me = state.players[0]
    reilly = InPlay.of(repo.get("ST32-004"), sickness=True)
    me.characters = [reilly]

    evaluate_static_effects(state, overlay)
    assert not reilly.is_rush_chara_only_now, "非斬leader ⇒ 速攻:キャラ なし"


def test_st32_004_on_play_rests_two_low_cost_opp():
    """登場時: 相手コスト2以下キャラ 2枚まで を レスト (AI 自動 = 上位2枚)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, human_idx=None)  # AI 自動
    opp = state.players[1]
    opp.characters = [
        InPlay.of(repo.get(C_COST1), sickness=False),   # cost1
        InPlay.of(repo.get(C_COST2), sickness=False),   # cost2
        InPlay.of(repo.get(C_COST2B), sickness=False),  # cost2
        InPlay.of(repo.get(C_COST3), sickness=False),   # cost3 (対象外)
    ]

    _play_chara(state, repo, 0, "ST32-004", overlay)

    assert state.pending_choice is None, "AI は modal を出さない"
    rested = [c for c in opp.characters if c.rested]
    assert len(rested) == 2, f"コスト2以下を 2 枚 レスト: {[c.card.card_id for c in rested]}"
    assert all(c.card.cost <= 2 for c in rested), "レストされたのは コスト2以下 のみ"
    cost3 = next(c for c in opp.characters if c.card.card_id == C_COST3)
    assert not cost3.rested, "コスト3 は 対象外 (レストされない)"


# ===========================================================================
# ST32-005 ロロノア・ゾロ: 速攻:キャラ / 登場時(斬leader) 相手コスト2以下1枚レスト
# ===========================================================================
def test_st32_005_rush_chara_unconditional():
    """速攻:キャラ は 無条件 (リーダー属性に依らず) 付与される。"""
    repo = _repo()
    overlay = _overlay()
    # 非斬leader でも 付与される (無条件)
    state = _make_state(repo, overlay, leader_id=NON_ZAN_LEADER)
    me = state.players[0]
    zoro = InPlay.of(repo.get("ST32-005"), sickness=True)
    me.characters = [zoro]

    evaluate_static_effects(state, overlay)
    assert zoro.is_rush_chara_only_now, "ST32-005 は 無条件で 速攻:キャラ"


def test_st32_005_on_play_rest_zan_leader_human_pick():
    """登場時 (斬leader): 相手コスト2以下キャラ 1枚まで レスト。
    候補 > 1 + 人間 → target_pick で 選べる。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=ZAN_LEADER, human_idx=0)
    opp = state.players[1]
    opp.characters = [
        InPlay.of(repo.get(C_COST1), sickness=False),   # cost1
        InPlay.of(repo.get(C_COST2), sickness=False),   # cost2
        InPlay.of(repo.get(C_COST3), sickness=False),   # cost3 (対象外)
    ]

    _play_chara(state, repo, 0, "ST32-005", overlay)

    assert state.pending_choice is not None, "人間 + 候補 > 1 → modal"
    assert state.pending_choice.get("kind") == "target_pick", state.pending_choice.get("kind")
    cands = state.pending_choice.get("candidates", [])
    cand_ids = {c["card_id"] for c in cands}
    assert cand_ids == {C_COST1, C_COST2}, f"コスト2以下の2枚のみ候補: {cand_ids}"

    pick = next(i for i, c in enumerate(cands) if c["card_id"] == C_COST2)
    resolve_pending_choice(state, [pick])
    assert state.pending_choice is None
    chosen = next(c for c in opp.characters if c.card.card_id == C_COST2)
    unchosen = next(c for c in opp.characters if c.card.card_id == C_COST1)
    assert chosen.rested, "選んだ cost2 が レスト"
    assert not unchosen.rested, "選ばなかった cost1 は 非レスト"


def test_st32_005_on_play_no_effect_without_zan_leader():
    """非斬leader では 登場時 レスト効果 は 発火しない。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=NON_ZAN_LEADER, human_idx=0)
    opp = state.players[1]
    opp.characters = [InPlay.of(repo.get(C_COST1), sickness=False)]

    _play_chara(state, repo, 0, "ST32-005", overlay)

    assert state.pending_choice is None, "非斬leader ⇒ 登場効果 不発"
    assert not opp.characters[0].rested, "レストされない"


def test_st32_005_on_play_ai_auto_rests():
    """AI 文脈 (斬leader): 候補 > 1 でも crash せず 自動で 1 枚 レスト。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, overlay, leader_id=ZAN_LEADER, human_idx=None)  # AI
    opp = state.players[1]
    opp.characters = [
        InPlay.of(repo.get(C_COST1), sickness=False),
        InPlay.of(repo.get(C_COST2), sickness=False),
    ]

    _play_chara(state, repo, 0, "ST32-005", overlay)

    assert state.pending_choice is None, "AI は modal を出さない"
    rested = [c for c in opp.characters if c.rested]
    assert len(rested) == 1, f"1 枚だけ レスト (AI 自動): {[c.card.card_id for c in rested]}"
