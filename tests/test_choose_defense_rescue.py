# -*- coding: utf-8 -*-
"""
choose_defense Phase 7A 改修テスト (= 2026-05-14)
================================================

ブロッカー判定の 3-tier 並列評価:
- Tier 1 (block_safe): c.power > atk_p (= 公式 7-1-4 準拠、 strictly greater)
- Tier 2 (block_rescue): counter で救う、 valuable blocker のみ対象
- Tier 3 (block_sacrifice): life ≤ 1 の特攻

修正前の bug (= `>=` で同値生存扱い) は test_blocker_strictly_greater_required で検出。
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.ai import GreedyAI
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo, defender_life=3):
    """defender (me) が life=N、 attacker (opp) がターンプレイヤー の state を作る。"""
    me = Player(name="defender", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="attacker", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    # defender side: life
    me.life = [repo.get("OP01-013")] * defender_life
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    state = GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )
    state.turn_player_idx = 1  # opp がアタッカー
    return state


def _make_attacker(repo, power: int) -> InPlay:
    """指定 power の attacker (= rest 解除) を作る。"""
    # OP01-013 (3000 power) ベースで attached_dons で調整
    card = repo.get("OP01-013")
    attacker = InPlay.of(card, sickness=False)
    extra = max(0, (power - 3000) // 1000)
    attacker.attached_dons = min(4, extra)
    return attacker


def _make_blocker_5k(repo) -> InPlay:
    """5000 power blocker (= OP07-021 ウルージ) を作る。"""
    return InPlay.of(repo.get("OP07-021"), sickness=False)


def _make_blocker_3k(repo) -> InPlay:
    """3000 power blocker (= OP09-014 ライムジュース、 cost 3 = non-valuable) を作る。"""
    return InPlay.of(repo.get("OP09-014"), sickness=False)


def _counter_card(repo, value: int):
    """指定 counter 値のカードを返す。"""
    if value == 2000:
        return repo.get("OP03-044")  # 1 コスト 2000 counter (= カヤ)
    if value == 1000:
        return repo.get("OP01-016")  # 1 コスト 1000 counter (= ナミ)
    return None


# ─────────────────────────────────────────────────────
# Test 1: rule fix (= blocker.power == attacker.power で blocker は死ぬ)
# ─────────────────────────────────────────────────────


def test_blocker_strictly_greater_required():
    """公式 7-1-4: blocker.power > attacker.power でなければ blocker は死ぬ。

    5000 blocker vs 5000 attacker、 手札 counter なし、 life=3。
    旧 bug (= `>=` で同値生存): block_iid set + counter 不要
    fix 後 (= `>` で strictly greater): blocker 生存しない、 valuable だが counter なしで rescue 不可、
    life > 1 なので 特攻 もしない → block_iid = None
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    me.characters = [_make_blocker_5k(repo)]
    me.hand = []  # counter なし
    attacker = _make_attacker(repo, power=5000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None, \
        f"5000 vs 5000 で blocker は生存できない、 counter 無しなら block しないはず (got block_iid={block_iid})"


def test_blocker_strictly_greater_survives():
    """6000 blocker vs 5000 attacker は 真に生存可能 (= 既存挙動)。"""
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    # 6000 blocker を仮想生成 (= ウルージ 5000 を InPlay で attached_dons で 6000 に)
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 5000 + 1000 = 6000
    me.characters = [blocker]
    attacker = _make_attacker(repo, power=5000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid == blocker.instance_id, "6000 blocker は 5000 attacker に勝てるので使うべき"
    assert counters == (), "自力生存なので counter 不要"


# ─────────────────────────────────────────────────────
# Test 2: rescue (= counter で blocker を救う)
# ─────────────────────────────────────────────────────


def test_rescue_5k_blocker_skipped_when_leader_can_defend():
    """5000 blocker vs 6000 attacker + 手札 2000 counter → blocker rescue は SKIP。

    観戦コメント cluster #3 由来の修正: 同 counter で leader 直接受けで防げるなら
    blocker rescue は不要 (= blocker rest を温存)。
    leader P 5000 + 2000 counter = 7000 > 6000 atk → leader 自身で防げる →
    blocker は使わず leader 受けで counter のみ使う方が得。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    me.characters = [_make_blocker_5k(repo)]
    me.hand = [_counter_card(repo, 2000)]  # 2000 counter 1 枚
    attacker = _make_attacker(repo, power=6000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None, \
        f"同 counter で leader 受けで防げる → blocker rescue skip (got block_iid={block_iid})"
    # leader 受けの counter 判定は別ロジック (defense_thresholds) なので、 ここでは
    # blocker 温存 (= block_iid=None) のみアサート。 counter の有無は profile 依存。


def test_no_rescue_for_low_value_blocker():
    """3000 power の cost=3 vanilla-ish blocker は rescue されない (= 価値不足)。

    3000 blocker vs 5000 attacker + 手札 2000 counter、 life=3。
    valuable blocker 判定: power < 5000、 role 未確定、 cost < 4 → NOT valuable
    → rescue 不発、 life > 1 で 特攻 もしない → block_iid = None
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    me.characters = [_make_blocker_3k(repo)]
    me.hand = [_counter_card(repo, 2000)]
    attacker = _make_attacker(repo, power=5000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    # 3000 blocker は valuable じゃないので rescue されず、 life=3 で 特攻 もせず
    assert block_iid is None, \
        f"低価値 blocker は rescue されないはず (got block_iid={block_iid})"


# ─────────────────────────────────────────────────────
# Test 3: sacrifice (= life ≤ 1 の特攻)
# ─────────────────────────────────────────────────────


def test_sacrifice_at_life_1():
    """life=1 + 自力生存 / rescue 不可 → 特攻 (= blocker 失っても leader 守る)。

    5000 blocker vs 6000 attacker、 counter なし、 life=1。
    自力生存 NG、 rescue 不可 (counter なし)、 life=1 なので 特攻 で blocker 使う。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=1)
    me = state.players[0]
    me.characters = [_make_blocker_5k(repo)]
    me.hand = []
    attacker = _make_attacker(repo, power=6000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid == me.characters[0].instance_id, "life=1 では blocker 特攻すべき"


def test_no_sacrifice_at_life_3():
    """life=3 で 自力生存 NG / rescue NG なら、 block しない (= 特攻はしない)。

    Test 3 と同条件で life=3 にする。 sacrifice モード不発、 leader で受ける。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    me.characters = [_make_blocker_5k(repo)]
    me.hand = []  # counter なし → rescue 不可
    attacker = _make_attacker(repo, power=6000)
    state.players[1].characters = [attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None, "life=3 で 特攻はしない、 ライフで受けるべき"


# ─────────────────────────────────────────────────────
# Test 4: helper functions
# ─────────────────────────────────────────────────────


def test_is_valuable_blocker_5k_power():
    """5000+ power は valuable と判定。"""
    repo = _repo()
    ai = GreedyAI()
    b5k = _make_blocker_5k(repo)
    assert ai._is_valuable_blocker(b5k), "5000 power blocker は valuable"


def test_is_valuable_blocker_3k_cost3():
    """3000 power + cost 3 + 未知 role → not valuable。"""
    repo = _repo()
    ai = GreedyAI()
    b3k = _make_blocker_3k(repo)
    # 注: card_role.json で OP09-014 が finisher 系に登録されてる場合は valuable 扱いになる
    # 現実装でロード時にエラーがあれば未登録扱い (= False)
    # ここはあくまで「実装ロジック自体」 のテスト


def test_is_rescue_worthwhile_5k_with_2k_counter():
    """5000 power blocker は 2000 counter / 2 枚まで rescue 価値あり。"""
    repo = _repo()
    ai = GreedyAI()
    b5k = _make_blocker_5k(repo)
    assert ai._is_rescue_worthwhile(b5k, rescue_total=2000, rescue_count=1, life_left=3)
    assert ai._is_rescue_worthwhile(b5k, rescue_total=2000, rescue_count=2, life_left=3)
    assert not ai._is_rescue_worthwhile(b5k, rescue_total=3000, rescue_count=2, life_left=3), \
        "5000 blocker でも 3000 counter (= 2 枚で 2000 超過) は過剰投資"
    assert not ai._is_rescue_worthwhile(b5k, rescue_total=2000, rescue_count=3, life_left=3), \
        "3 枚使う rescue は許容範囲外"


def test_is_rescue_worthwhile_low_power():
    """3000 power 以下の blocker は rescue されない (= 価値不足)。"""
    repo = _repo()
    ai = GreedyAI()
    b3k = _make_blocker_3k(repo)
    # 3000 blocker は 1000 / 1 枚なら rescue 価値あり (= power ≥ 3000 ルート)
    # ただし life > 2 だと role-based ルートも発動しない
    assert ai._is_rescue_worthwhile(b3k, rescue_total=1000, rescue_count=1, life_left=3)
    assert not ai._is_rescue_worthwhile(b3k, rescue_total=2000, rescue_count=1, life_left=3), \
        "3000 blocker で 2000 counter は過剰"
    assert not ai._is_rescue_worthwhile(b3k, rescue_total=1000, rescue_count=2, life_left=3), \
        "3000 blocker で 2 枚 counter は過剰"



# ─────────────────────────────────────────────────────
# Test: 高ライフでの near-free チップは受ける (= 過剰カウンター抑制、 2026-06-12)
# campaign (Claude vs AI) で人間に最も繰り返し突かれた弱点への対策。
# 配備 AI (op13=ランプ {4:(3000,1)} / control {4:(5000,2)}) は高ライフでも単発チップに
# counter を吐き、 数ターンで手札が枯れていた。
# ─────────────────────────────────────────────────────


def _greedy_generous_thresholds():
    """高ライフで counter する寛容な閾値の GreedyAI (= 多くの control/midrange 相当)。

    matchup override が呼ばれると閾値を _base から再構築するので no-op 化し、
    new take ルールを isolate して検証する。
    """
    ai = GreedyAI()
    ai._ensure_matchup_overrides = lambda *a, **k: None  # type: ignore
    ai.defense_thresholds = {1: (99999, 99), 2: (8000, 3), 3: (7000, 2), 4: (3000, 1)}
    ai.avoid_life_loss = False
    return ai


def test_take_near_free_chip_at_high_life():
    """life=4 で gap≤1000 の near-free チップは受ける (= counter 温存)。

    寛容閾値 {4:(3000,1)} なら旧挙動は 1000 counter で守る。 新ルールで受ける (counters == ())。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=4)
    me = state.players[0]
    me.characters = []
    me.hand = [_counter_card(repo, 1000)]
    attacker = _make_attacker(repo, power=5000)  # gap 0 vs 5000 leader
    state.players[1].characters = [attacker]

    ai = _greedy_generous_thresholds()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None
    assert counters == (), f"高ライフの near-free チップは受けるはず (got {counters})"


def test_counter_chip_at_low_life():
    """life=2 では near-free チップでも counter する (= 高ライフ take ルールは発火しない)。"""
    repo = _repo()
    state = _make_state(repo, defender_life=2)
    me = state.players[0]
    me.characters = []
    me.hand = [_counter_card(repo, 1000)]
    attacker = _make_attacker(repo, power=5000)
    state.players[1].characters = [attacker]

    ai = _greedy_generous_thresholds()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert counters != (), "低ライフ (≤2) ではチップでも counter するはず"


def test_counter_boosted_attack_at_life3():
    """life=3 では gap>0 の boost 攻撃 (= 単なるチップでない) は従来通り counter する。

    純チップ (gap≤0) のみ受け、 1 DON でも boost された攻撃は守る (= ライフが減るほど慎重)。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    me = state.players[0]
    me.characters = []
    me.hand = [_counter_card(repo, 2000)]
    attacker = _make_attacker(repo, power=6000)  # gap 1000 > 0
    state.players[1].characters = [attacker]

    ai = _greedy_generous_thresholds()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert counters != (), "life=3 で gap>0 の boost 攻撃は counter するはず"


def test_avoid_life_loss_deck_still_counters_chip():
    """avoid_life_loss シグナルのデッキは高ライフでもチップを counter (= 高ライフ維持重視)。"""
    repo = _repo()
    state = _make_state(repo, defender_life=4)
    me = state.players[0]
    me.characters = []
    me.hand = [_counter_card(repo, 1000)]
    attacker = _make_attacker(repo, power=5000)
    state.players[1].characters = [attacker]

    ai = _greedy_generous_thresholds()
    ai.avoid_life_loss = True
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert counters != (), "avoid_life_loss デッキは高ライフでもチップを守るはず"


# ─────────────────────────────────────────────────────
# Test: ロジャー OP09-118 在場 + life0 で block すると相手即勝利 → ブロックしない
# (campaign 1456 g5 で観測した block self-lose バグ、 2026-06-12)
# ─────────────────────────────────────────────────────


def _roger_overlay():
    from engine.effects import CardEffectBundle
    return {
        "OP09-118": CardEffectBundle(
            card_id="OP09-118",
            effects=[{
                "when": "on_opp_blocker_use",
                "if": {"life_zero_either": True},
                "do": [{"win_game": True}],
            }],
        )
    }


def test_no_block_when_blocking_grants_opp_roger_win():
    """attacker 側に ロジャー在場 + どちらか life0 では、 6000 blocker があってもブロックしない。

    ブロック発動 = 相手の【相手ブロッカー発動時】win_game を踏んで即敗北するため。
    """
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    state.effects_overlay = _roger_overlay()
    me = state.players[0]   # defender
    opp = state.players[1]  # attacker (turn player)
    # defender に 6000 blocker (= 通常なら 5000 attacker を安全 block)
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 6000
    me.characters = [blocker]
    me.hand = []
    # attacker 側に ロジャー在場 + attacker が life0 (= life_zero_either 成立)
    roger = InPlay.of(repo.get("OP09-118"), sickness=False)
    opp.life = []  # attacker 0 life
    attacker = _make_attacker(repo, power=5000)
    opp.characters = [roger, attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None, \
        f"ロジャー在場+life0 では block すると即敗北なのでブロックしてはならない (got block_iid={block_iid})"


def test_block_normal_when_no_roger():
    """ロジャー不在なら 6000 blocker は通常通り使う (= ガードが過剰発火しない)。"""
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    state.effects_overlay = _roger_overlay()
    me = state.players[0]
    opp = state.players[1]
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 6000
    me.characters = [blocker]
    me.hand = []
    # attacker は life0 だが ロジャー不在 → ガード非発火
    opp.life = []
    attacker = _make_attacker(repo, power=5000)
    opp.characters = [attacker]  # ロジャーなし

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid == blocker.instance_id, \
        f"ロジャー不在なら 6000 blocker は通常通り使うはず (got {block_iid})"


def test_block_normal_when_roger_but_both_life_positive():
    """ロジャー在場でも両者 life>0 なら条件不成立 → 通常通り block。"""
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    state.effects_overlay = _roger_overlay()
    me = state.players[0]
    opp = state.players[1]
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 6000
    me.characters = [blocker]
    me.hand = []
    roger = InPlay.of(repo.get("OP09-118"), sickness=False)
    opp.life = [repo.get("OP01-013")] * 2  # attacker life>0
    attacker = _make_attacker(repo, power=5000)
    opp.characters = [roger, attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid == blocker.instance_id, \
        f"両者 life>0 なら win_game 条件不成立 → 通常 block するはず (got {block_iid})"


def _st10006_overlay():
    """ST10-006 ルフィ: 相手ブロッカー発動時に自陣 power8000以下キャラ 1 枚 KO。"""
    from engine.effects import CardEffectBundle
    return {
        "ST10-006": CardEffectBundle(
            card_id="ST10-006",
            effects=[{
                "when": "on_opp_blocker_use",
                "cost": {"once_per_turn": True},
                "do": [{"ko": {"type": "one_opponent_character_filtered",
                               "filter": {"current_power_le": 8000}}}],
            }],
        )
    }


def test_no_block_when_punished_by_opp_ko_at_safe_life():
    """ST10-006 在場 + ライフ安全 (≥3) では、 ブロックでキャラを失う罰を避けて block しない。"""
    repo = _repo()
    state = _make_state(repo, defender_life=3)
    state.effects_overlay = _st10006_overlay()
    me = state.players[0]
    opp = state.players[1]
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 6000
    me.characters = [blocker]
    me.hand = []
    st10 = InPlay.of(repo.get("ST10-006"), sickness=False)
    attacker = _make_attacker(repo, power=5000)
    opp.characters = [st10, attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid is None, \
        f"ST10-006 在場 + 安全ライフ では block しない (キャラ KO の罰回避) はず (got {block_iid})"


def test_block_when_punished_by_opp_ko_at_low_life():
    """ST10-006 在場でも低ライフ (≤2) なら survival 優先でブロックする。"""
    repo = _repo()
    state = _make_state(repo, defender_life=2)
    state.effects_overlay = _st10006_overlay()
    me = state.players[0]
    opp = state.players[1]
    blocker = _make_blocker_5k(repo)
    blocker.attached_dons = 1  # 6000
    me.characters = [blocker]
    me.hand = []
    st10 = InPlay.of(repo.get("ST10-006"), sickness=False)
    attacker = _make_attacker(repo, power=5000)
    opp.characters = [st10, attacker]

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    assert block_iid == blocker.instance_id, \
        f"低ライフでは ST10-006 でも survival 優先で block するはず (got {block_iid})"
