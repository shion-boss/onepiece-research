# -*- coding: utf-8 -*-
"""打倒カルガラ / エネル検証: aggro_value (= opp life→hand 資源の過大評価 是正 factor) の sweep。

人間の勝ち筋ログで「序盤の攻撃が eval -3162 と過小評価され AI-エネルが受け身→敗北」 を確認。
challenger 側の _aggro_value を sweep し vs calgara 勝率 + 1試合あたりの AttackLeader 回数
(= 実際に攻めるようになったか) を測る。 calgara は配備固定。

  .venv/bin/python scripts/sweep_aggro_value.py --decks cardrush_1467,cardrush_1454 \
      --avs 1.0,0.5,0.2,0.0 --n 50
"""
import argparse
import sys
import time
import multiprocessing as mp
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _decklist(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", _REPO)


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _run(task):
    challenger, target, av, n, seed = task

    def aif_c(rng, deck_analysis=None):
        ai = ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": challenger})
        ai._aggro_value = av
        return ai

    def aif_t(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": target})

    rep = run_matchup(
        _decklist(challenger), _decklist(target),
        n_games=n, seed=seed, ai_factory_1=aif_c, ai_factory_2=aif_t,
        deck1_analysis=_ana(challenger), deck2_analysis=_ana(target),
        effects_overlay=_OVERLAY, record_snapshots=True,
    )
    # challenger (= P0) の AttackLeader 平均回数
    atk = []
    for g in rep.games:
        aes = getattr(g, "action_evals", None) or []
        atk.append(sum(1 for e in aes if e.get("player_idx") == 0 and e.get("action") == "AttackLeader"))
    avg_atk = sum(atk) / max(1, len(atk))
    return (challenger, av, rep.deck1_wins, rep.deck2_wins, rep.draws, avg_atk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="cardrush_1467")
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--avs", default="1.0,0.5,0.2,0.0")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    decks = [d.strip() for d in a.decks.split(",") if d.strip()]
    avs = [float(x) for x in a.avs.split(",")]
    tasks = [(d, a.target, av, a.n, a.seed) for d in decks for av in avs]
    print(f"aggro_value sweep: {decks} vs {a.target} | N={a.n} seed={a.seed} | avs={avs}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {(c, av): (w, l, d, atk) for c, av, w, l, d, atk in res}
    print(f"=== challenger winrate / 攻撃回数 vs {a.target} (N={a.n}) === ({time.time()-t0:.0f}s)")
    hdr = "".join(f"{('av='+str(av)):>16}" for av in avs)
    print(f"  {'deck':<16}{hdr}")
    for d in decks:
        cells = []
        for av in avs:
            w, l, dd, atk = by.get((d, av), (0, 0, 0, 0))
            cells.append(f"{w}-{l} {w/max(1,w+l+dd)*100:.0f}% a{atk:.1f}")
        print(f"  {d:<16}" + "".join(f"{c:>16}" for c in cells))
    print("  (a = challenger の 1試合あたり AttackLeader 平均回数。 人間の勝ち試合は 10 回)")


if __name__ == "__main__":
    main()
