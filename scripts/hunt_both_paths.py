# -*- coding: utf-8 -*-
"""人間経路 + AI経路 を 環境デッキ で 大量に走らせ、 crash/engine error/保存則違反 を 全件 sweep。

両経路とも in-game 例外を握り潰し「engine error」 で winner 確定するため (= advance_until_pause /
harness の except)、 **game_over の log を engine error 走査** しないと crash を見逃す
([[feedback_verify_game_completion_reason]] の human/AI 両版)。 加えて 保存則 (SemanticReferee /
fuzz INV1)、 stuck/NO_ACT を検査する。

  python scripts/hunt_both_paths.py [N] [both|ai|human]
    N    = 1 ペアあたりの試合数 (既定 16)
    mode = both (既定) / ai / human
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.semantic_referee import SemanticReferee  # noqa: E402
import fuzz_human_play as F  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

DECKS = [
    "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
    "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
    "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
    "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy",
    "tcgportal_op13_luffy",
]


def _load(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", repo)


def _analysis(slug):
    import json
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.load(open(p)) if p.exists() else None


def _pairs():
    """self-play 全16 + cross-play (各デッキ vs 次2デッキ) の round-robin。"""
    ps = [(d, d) for d in DECKS]
    for i, d in enumerate(DECKS):
        for j in (1, 2):
            ps.append((d, DECKS[(i + j) % len(DECKS)]))
    return ps


def _gf(rng, deck_analysis=None):
    return GreedyAI(rng=rng)


def hunt_ai(pairs, n, bugs, seed_base=4242, ai_mode="greedy"):
    total = 0
    if ai_mode == "default":
        from engine.harness import _default_ai_factory
        fac = _default_ai_factory
    else:
        fac = _gf
    for a, b in pairs:
        rep = run_matchup(
            _load(a), _load(b), n_games=n, seed=seed_base,
            ai_factory_1=fac, ai_factory_2=fac, effects_overlay=overlay,
            deck1_analysis=_analysis(a), deck2_analysis=_analysis(b),
            referee_factory=lambda: SemanticReferee(strict=False),
            keep_logs=True, time_limit_turns=40,
        )
        for i, g in enumerate(rep.games):
            total += 1
            ee = next((ln for ln in g.log if "engine error" in ln), None)
            if ee:
                bugs.append(("AI", f"{a} vs {b}", i, "ENGINE_ERROR",
                             ee.split("engine error:")[-1].strip()[:90]))
            for v in g.rule_violations:
                if "メインデッキ札" in v:
                    bugs.append(("AI", f"{a} vs {b}", i, "CONSERVATION", v[:90]))
        print(f"[AI] {a} vs {b} x{n} done | cum {total} bugs {len(bugs)}", flush=True)
    return total


def hunt_human(pairs, n, bugs, seed_base=5000):
    F._setup()
    total = 0
    for a, b in pairs:
        for s in range(n):
            gseed = seed_base + s
            try:
                st, steps, info = F.play_one(a, b, gseed, s % 2 == 0,
                                             random.Random(gseed), set())
            except Exception as e:  # noqa: BLE001
                bugs.append(("HUMAN", f"{a} vs {b}", gseed, "PY_EXC",
                             f"{type(e).__name__}: {str(e)[:80]}"))
                total += 1
                continue
            total += 1
            if st != "OK":
                bugs.append(("HUMAN", f"{a} vs {b}", gseed, st, str(info)[:90]))
        print(f"[HUMAN] {a} vs {b} x{n} done | cum {total} bugs {len(bugs)}", flush=True)
    return total


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    n = nums[0] if nums else 16
    seed_base = nums[1] if len(nums) > 1 else None  # 指定で別局面を探索
    mode = next((a for a in sys.argv[1:] if a in ("both", "ai", "human")), "both")
    ai_mode = "default" if "default" in sys.argv[1:] else "greedy"
    pairs = _pairs()
    bugs: list = []
    tot_ai = tot_h = 0
    if mode in ("both", "ai"):
        tot_ai = hunt_ai(pairs, n, bugs,
                         seed_base=(seed_base or 4242), ai_mode=ai_mode)
    if mode in ("both", "human"):
        tot_h = hunt_human(pairs, n, bugs, seed_base=(seed_base or 5000))
    print(f"\n=== 両経路 hunt 完了: AI {tot_ai} 試合 + 人間 {tot_h} 試合 ===")
    print(f"検出バグ: {len(bugs)}")
    from collections import Counter
    by = Counter((b[0], b[3]) for b in bugs)
    for k, c in by.most_common():
        print(f"  {k}: {c}")
    for path, pair, seed, kind, info in bugs[:40]:
        print(f"  ★[{path}/{kind}] {pair} #{seed}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
