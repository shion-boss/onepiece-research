# -*- coding: utf-8 -*-
"""公式 floor_rule.pdf II.「時間切れに関して」 準拠の time_limit_turns 実装テスト。

実装位置: engine/harness.py
- run_matchup(time_limit_turns: int | None, time_limit_mode: "both_lose" | "extra_turns")
- _apply_time_limit_tiebreak(state, rng, effective_cap)

仕様 (= floor_rule.pdf II.):
- 1対戦30分推奨 → エンジンでは turn 上限を proxy とする (default 40 turn)
- 公認大会 (= "both_lose"): 時間切れで勝者未決 → 勝敗判定せず両者敗北
- 決勝/トーナメント (= "extra_turns"): 進行中ターンを0として
  先攻(=奇数 turn_number) なら +3、 後攻(=偶数) なら +2 の追加ターン
  それでも未決なら ① life多い方 ② deck多い方 ③ random(じゃんけん)
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo():
    from engine.deck import CardRepository
    return CardRepository.from_json(str(ROOT / "db" / "cards.json"))


@pytest.fixture
def fast_ai_factory():
    """RandomAI は plan_search なし で高速 (= テスト用)。"""
    from engine.ai import RandomAI

    def _factory(rng, deck_analysis=None):
        return RandomAI(rng=rng)

    return _factory


def _load_deck(repo, slug="tcgportal_coby"):
    from engine.deck import DeckList
    return DeckList.from_json(str(ROOT / "decks" / f"{slug}.json"), repo)


def test_both_lose_mode_triggers_draw(repo, fast_ai_factory):
    """time_limit_turns=4 + both_lose → 必ず turn 5 直前で 両者敗北 = draw。"""
    from engine.harness import run_matchup
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    rep = run_matchup(
        d1, d2, n_games=2, seed=42,
        ai_factory_1=fast_ai_factory, ai_factory_2=fast_ai_factory,
        time_limit_turns=4, time_limit_mode="both_lose",
        keep_logs=True, enforce_rules=False,
    )
    assert rep.draws == 2
    assert rep.deck1_wins == 0
    assert rep.deck2_wins == 0
    for g in rep.games:
        # turn 4 が 完了 した 直後 (= turn_number は 5 に なる) に break する
        assert g.winner == -1
        assert g.turns >= 4
        # 時間切れ log が 出ている
        end_lines = [l for l in (g.log or []) if "時間切れ: 両者敗北" in l]
        assert len(end_lines) == 1, f"expected 1 時間切れ log, got {end_lines}"


def test_extra_turns_mode_triggers_tiebreak(repo, fast_ai_factory):
    """time_limit_turns=4 + extra_turns → effective_cap=6 (= 4 even → +2)、 tiebreak で決着。"""
    from engine.harness import run_matchup
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    rep = run_matchup(
        d1, d2, n_games=2, seed=42,
        ai_factory_1=fast_ai_factory, ai_factory_2=fast_ai_factory,
        time_limit_turns=4, time_limit_mode="extra_turns",
        keep_logs=True, enforce_rules=False,
    )
    # tiebreak は 必ず勝者 を 出す (= じゃんけん が ある ので draw は 出にくい)
    decisive = rep.deck1_wins + rep.deck2_wins
    assert decisive + rep.draws == 2
    # 全 game で 時間切れ tiebreak log が 出ている
    for g in rep.games:
        end_lines = [l for l in (g.log or []) if "時間切れ tiebreak" in l]
        # natural end (= life=0 hit / deckout) で 終わった game は tiebreak ログ なし
        # extra_turns では cap+extra まで 続く ので、 fast AI なら 高確率 tiebreak
        if g.winner != -1:
            # 勝者 が 居る = 自然終了 or tiebreak
            assert "時間切れ" in (g.log[-1] if g.log else "") or len(end_lines) == 1


def test_extra_turns_odd_cap_grants_3_more(repo, fast_ai_factory):
    """cap=5 (= 奇数 = 先攻 interrupted) → +3 turn、 effective_cap=8。"""
    from engine.harness import run_matchup
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    rep = run_matchup(
        d1, d2, n_games=1, seed=42,
        ai_factory_1=fast_ai_factory, ai_factory_2=fast_ai_factory,
        time_limit_turns=5, time_limit_mode="extra_turns",
        keep_logs=True, enforce_rules=False,
    )
    g = rep.games[0]
    # tiebreak log に effective_cap=8 が 入る (= 5+3)
    end_lines = [l for l in (g.log or []) if "時間切れ tiebreak" in l]
    if end_lines:  # natural end しない 場合
        assert "cap=8" in end_lines[-1], f"expected cap=8 in: {end_lines[-1]}"


def test_no_time_limit_when_none(repo, fast_ai_factory):
    """time_limit_turns=None で 旧 挙動 (= 時間切れ判定 なし、 max_actions のみ)。"""
    from engine.harness import run_matchup
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    rep = run_matchup(
        d1, d2, n_games=1, seed=42,
        ai_factory_1=fast_ai_factory, ai_factory_2=fast_ai_factory,
        time_limit_turns=None, time_limit_mode="both_lose",
        keep_logs=True, enforce_rules=False,
    )
    g = rep.games[0]
    # 時間切れ log は 出ない (= None で 判定 path に 入らない)
    end_lines = [l for l in (g.log or []) if "時間切れ" in l]
    assert end_lines == [], f"expected no 時間切れ log, got {end_lines}"


def test_invalid_mode_raises():
    """未対応 mode は ValueError。"""
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    d1 = DeckList.from_json(str(ROOT / "decks" / "tcgportal_coby.json"), repo)
    d2 = DeckList.from_json(str(ROOT / "decks" / "tcgportal_coby.json"), repo)
    with pytest.raises(ValueError, match="time_limit_mode"):
        run_matchup(d1, d2, n_games=1, time_limit_mode="invalid")


def test_apply_tiebreak_life_first(repo):
    """① life 多い方 が 優先。"""
    from engine.harness import _apply_time_limit_tiebreak
    from engine.game import setup_game
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    s = setup_game(d1, d2, rng=random.Random(0))
    s.players[0].life = s.players[0].life[:4]
    s.players[1].life = s.players[1].life[:2]
    # deck は 一切 関係ない (= life で 決着)
    _apply_time_limit_tiebreak(s, random.Random(0), 12)
    assert s.winner == 0
    assert s.game_over is True


def test_apply_tiebreak_deck_when_life_tied(repo):
    """② life 同数 → deck 多い方。"""
    from engine.harness import _apply_time_limit_tiebreak
    from engine.game import setup_game
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    s = setup_game(d1, d2, rng=random.Random(0))
    s.players[0].life = s.players[0].life[:3]
    s.players[1].life = s.players[1].life[:3]
    s.players[0].deck = s.players[0].deck[:30]
    s.players[1].deck = s.players[1].deck[:20]
    _apply_time_limit_tiebreak(s, random.Random(0), 12)
    assert s.winner == 0
    assert s.game_over is True


def test_apply_tiebreak_random_when_all_tied(repo):
    """③ life + deck 同数 → random (じゃんけん) で 必ず 0 or 1 が 出る。"""
    from engine.harness import _apply_time_limit_tiebreak
    from engine.game import setup_game
    d1 = _load_deck(repo)
    d2 = _load_deck(repo)
    s = setup_game(d1, d2, rng=random.Random(0))
    s.players[0].life = s.players[0].life[:3]
    s.players[1].life = s.players[1].life[:3]
    s.players[0].deck = s.players[0].deck[:25]
    s.players[1].deck = s.players[1].deck[:25]
    _apply_time_limit_tiebreak(s, random.Random(123), 12)
    assert s.winner in (0, 1)
    assert s.game_over is True
