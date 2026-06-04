# -*- coding: utf-8 -*-
"""SemanticReferee で実対戦 (AI vs AI) を監視し、 カード保存則違反を全件 sweep。

RuleReferee には無かった「メインデッキ札の保存則」 を実対戦で検査する。 保存則は数学的に
常に真 → 誤検出ゼロ。 違反 = カード複製/消失バグ (= シュガー複製 class) を 実対戦の文脈で
(= offline 単発発火でなく) 局所化して捕まえる。

  .venv/bin/python scripts/run_semantic_referee.py            # 既定 deck pairs を各数戦
  .venv/bin/python scripts/run_semantic_referee.py 30         # 1 pair あたり 30 戦
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.semantic_referee import SemanticReferee  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

# 効果が濃い (= 複製/消失バグを踏みやすい) 代表 deck pairs。
DEFAULT_PAIRS = [
    ("cardrush_1392", "cardrush_1342"),   # イム / 五老星 系 + KO 系
    ("cardrush_1385", "cardrush_1455"),   # play_from_trash / play_from_hand
    ("tcgportal_op13_luffy", "cardrush_1456"),
    ("cardrush_1439", "cardrush_1453"),
]


def _load(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", repo)


def run(pairs, n_games):
    total_games = 0
    all_violations = []
    for a, b in pairs:
        da, db = _load(a), _load(b)
        report = run_matchup(
            da, db, n_games=n_games, seed=12345,
            ai_factory_1=lambda rng, deck_analysis=None: GreedyAI(rng=rng),
            ai_factory_2=lambda rng, deck_analysis=None: GreedyAI(rng=rng),
            effects_overlay=overlay,
            referee_factory=lambda: SemanticReferee(strict=False),
            time_limit_turns=40,
        )
        for g in report.games:
            total_games += 1
            for v in g.rule_violations:
                # 保存則違反のみ抽出 (= SemanticReferee 固有)。 他は RuleReferee と共通。
                if "メインデッキ札" in v:
                    all_violations.append({"pair": f"{a} vs {b}", "viol": v})
        print(f"=== {a} vs {b}: {n_games} 戦 done ===", flush=True)
    return total_games, all_violations


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    total_games, violations = run(DEFAULT_PAIRS, n)
    print(f"\n監視試合数: {total_games}")
    print(f"カード保存則違反 (= 複製/消失): {len(violations)}")
    for v in violations[:20]:
        print(f"  [{v['pair']}] {v['viol']}")
    if not violations:
        print("OK: 全試合で カード保存則 維持 (= 効果が複製/消失させていない)")
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
