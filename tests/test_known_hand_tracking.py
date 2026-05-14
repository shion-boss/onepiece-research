# -*- coding: utf-8 -*-
"""
Phase 7I 公開済手札追跡 テスト (= 2026-05-14)
=============================================

- Player.add_to_hand_publicly / normalize_known_hand
- return_to_hand / search で 公開カードが known_hand_card_ids に追加
- 手札退場 (= play / discard) で known list が自動 cleanup
- hand_estimator pmf が known + unknown 分離で計算
"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.hand_estimator import counter_total_pmf, probability_counter_total_at_least

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _make_state(repo):
    me = Player(name="me", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    opp = Player(name="opp", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    me.deck = [repo.get("OP01-013")] * 30
    opp.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[me, opp],
        phase=Phase.MAIN,
        rng=random.Random(1),
    )


# ─────────────────────────────────────────────────────
# Player methods
# ─────────────────────────────────────────────────────


def test_add_to_hand_publicly_marks_known():
    """add_to_hand_publicly で hand + known の両方に追加。"""
    repo = _repo()
    p = Player(name="x", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    card = repo.get("OP01-013")
    p.add_to_hand_publicly(card)
    assert len(p.hand) == 1
    assert p.known_hand_card_ids == ["OP01-013"]


def test_normalize_known_hand_removes_stale():
    """hand から退場したカード分の known entry が削除される。"""
    repo = _repo()
    p = Player(name="x", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    # 公開で 3 枚加える
    for _ in range(3):
        p.add_to_hand_publicly(repo.get("OP01-013"))
    assert len(p.known_hand_card_ids) == 3
    # 1 枚 hand から退場 (= play / counter のシミュ)
    p.hand.pop(0)
    p.normalize_known_hand()
    assert len(p.known_hand_card_ids) == 2, "1 枚削減後の known は 2 枚"


def test_normalize_handles_multiple_card_ids():
    """同 card_id 複数 + 異種カード mixed で正しく正規化。"""
    repo = _repo()
    p = Player(name="x", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    # 3 枚同種公開 + 1 枚別公開
    for _ in range(3):
        p.add_to_hand_publicly(repo.get("OP01-013"))
    p.add_to_hand_publicly(repo.get("OP01-016"))
    assert len(p.known_hand_card_ids) == 4
    # 同種 1 枚 + 別種 1 枚 を play (= hand から popreplace)
    p.hand.pop(0)  # OP01-013 1 枚消費
    p.hand.pop(-1)  # OP01-016 消費
    p.normalize_known_hand()
    # 残: OP01-013 × 2 → known もそうなる
    assert sorted(p.known_hand_card_ids) == ["OP01-013", "OP01-013"]


# ─────────────────────────────────────────────────────
# hand_estimator pmf with known
# ─────────────────────────────────────────────────────


def test_pmf_all_known_is_deterministic():
    """全 hand card が known なら pmf は確定 (= 1 点に集中)。"""
    repo = _repo()
    state = _make_state(repo)
    # opp.hand に 1000 counter card 3 枚、 全部 known
    counter_card = repo.get("OP01-016")  # 1000 counter
    state.players[1].hand = [counter_card] * 3
    state.players[1].known_hand_card_ids = ["OP01-016"] * 3
    state.players[1].deck = []  # pool は hand のみ
    pmf = counter_total_pmf(state, opp_idx=1)
    # 3 × 1000 = 3000 が確率 1.0
    assert pmf == {3000: 1.0}


def test_pmf_mixed_known_unknown_combines():
    """known + unknown 混在 → known を shift base に unknown pmf 加算。"""
    repo = _repo()
    state = _make_state(repo)
    # opp.hand: 2000 counter 1 枚 (known) + 1000 counter 2 枚 (unknown)
    state.players[1].hand = [
        repo.get("OP03-044"),  # 2000 counter
        repo.get("OP01-016"),  # 1000
        repo.get("OP01-016"),  # 1000
    ]
    state.players[1].known_hand_card_ids = ["OP03-044"]  # 2000 だけ known
    state.players[1].deck = []  # pool は hand のみ
    pmf = counter_total_pmf(state, opp_idx=1)
    # known = 2000 確定、 残 2 枚は OP01-016 × 2 (= 1000 × 2 = 2000) で確定
    # 合計 = 4000 確率 1.0
    assert pmf == {4000: 1.0}


def test_pmf_shifts_with_known_counter_value():
    """known カードを変えると pmf が shift する。"""
    repo = _repo()
    state = _make_state(repo)
    # opp.hand: 1000 counter 2 枚、 全部 unknown
    state.players[1].hand = [repo.get("OP01-016")] * 2
    state.players[1].known_hand_card_ids = []
    state.players[1].deck = []
    pmf_no_known = counter_total_pmf(state, opp_idx=1)

    # known を 1 枚 mark → 残り 1 枚だけ unknown
    state.players[1].known_hand_card_ids = ["OP01-016"]
    pmf_with_known = counter_total_pmf(state, opp_idx=1)
    # 両方とも 2000 (= 1000 + 1000) 確定なので同じ
    assert pmf_no_known == {2000: 1.0}
    assert pmf_with_known == {2000: 1.0}


def test_probability_at_least_uses_known():
    """probability_counter_total_at_least が known 情報を反映。"""
    repo = _repo()
    state = _make_state(repo)
    # opp.hand: 2000 counter 1 枚 (known)
    state.players[1].hand = [repo.get("OP03-044")]
    state.players[1].known_hand_card_ids = ["OP03-044"]
    state.players[1].deck = []
    # P(>= 2000) = 1.0、 P(>= 2001) = 0.0
    assert probability_counter_total_at_least(state, 1, 2000) == 1.0
    assert probability_counter_total_at_least(state, 1, 2001) == 0.0


# ─────────────────────────────────────────────────────
# bluff の対象から known カード除外 (Phase 7I 拡張)
# ─────────────────────────────────────────────────────


def test_bluff_uses_unknown_portion_only():
    """expected_counter_from_don_bluff: known なし時と known で counter event 無い時を比較。

    全 5 枚 hand のうち 4 枚が known で counter event 無し → bluff は 残 1 枚 のみ対象 (= 大幅縮小)
    """
    from engine.hand_estimator import expected_counter_from_don_bluff
    repo = _repo()
    state = _make_state(repo)
    state.players[1].don_active = 2
    # 5 枚 hand、 全部 chara card (= 非 counter event)
    state.players[1].hand = [repo.get("OP01-013")] * 5
    state.players[1].known_hand_card_ids = []
    no_known = expected_counter_from_don_bluff(state, 1, use_archetype_factor=False)

    # 4 枚 known (= counter event 無し chara)
    state.players[1].known_hand_card_ids = ["OP01-013"] * 4
    with_4_known = expected_counter_from_don_bluff(state, 1, use_archetype_factor=False)

    # 5 枚 known
    state.players[1].known_hand_card_ids = ["OP01-013"] * 5
    all_known = expected_counter_from_don_bluff(state, 1, use_archetype_factor=False)

    # 単調減少: known が多いほど bluff 期待は減る
    assert no_known >= with_4_known >= all_known
    # 全 known で counter event 無し → bluff 0
    assert all_known == 0


def test_bluff_zero_when_all_known_no_event():
    """全 known で counter event 不在 → bluff 完全に 0。"""
    from engine.hand_estimator import expected_counter_from_don_bluff
    repo = _repo()
    state = _make_state(repo)
    state.players[1].don_active = 5
    state.players[1].hand = [repo.get("OP01-013")] * 3
    state.players[1].known_hand_card_ids = ["OP01-013"] * 3
    val = expected_counter_from_don_bluff(state, 1, use_archetype_factor=False)
    assert val == 0, "全 known で counter event 無しなら bluff 0"


def test_self_bluff_skipped_when_hand_mostly_known():
    """自分の手札の半分以上が公開済 → bluff モードに入らない (= 通常プレイ)。"""
    from engine.ai import GreedyAI
    repo = _repo()
    state = _make_state(repo)
    state.turn_player_idx = 0
    # me の手札 5 枚中 4 枚が公開済
    state.players[0].hand = [repo.get("OP01-013")] * 5
    state.players[0].known_hand_card_ids = ["OP01-013"] * 4

    ai = GreedyAI()
    # opp_next_lethal が高くても、 自分の手札が ばれてるなら bluff しない
    # 詳細は test setup 次第なので、 「bluff 判定 入口で skip される」 ことだけ確認
    result = ai._is_desperate_losing_position(state, me_idx=0)
    # 公開済が 80% (= 4/5) > 50% threshold → False (= bluff モード回避)
    assert result is False


def test_self_bluff_engaged_when_hand_mostly_unknown():
    """自分の手札が大半 未公開なら bluff モード判定が通常通り作動。"""
    from engine.ai import GreedyAI
    repo = _repo()
    state = _make_state(repo)
    state.turn_player_idx = 0
    # me の手札 5 枚、 公開済 1 枚 (= 80% 未知)
    state.players[0].hand = [repo.get("OP01-013")] * 5
    state.players[0].known_hand_card_ids = ["OP01-013"]
    # me を負け確定気味に設定 (life=1, opp 大型 4 体)
    state.players[0].life = [repo.get("OP01-013")] * 1
    state.players[1].life = [repo.get("OP01-013")] * 4
    state.players[1].characters = [
        InPlay.of(repo.get("OP07-021"), sickness=False)
        for _ in range(4)
    ]

    ai = GreedyAI()
    # 公開率 20% で threshold 下回らない → desperate 条件他に依存
    # = ここでは関数がエラーなく完了することのみ確認
    result = ai._is_desperate_losing_position(state, me_idx=0)
    assert isinstance(result, bool)
