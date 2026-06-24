# -*- coding: utf-8 -*-
"""打倒1位 campaign: self-play で学習した value を *配備 beam* に差し、 *配備 #1* に勝てるかを
A/B (= 自己対戦の成果が実戦に effくか = deploy gate)。

baseline (= "default" arm = 配備の per-deck GBM を auto-load、 value_defense も config 通り) と、
各 self-play iter の学習 GBM を beam の leaf value に差し替えた時の勝率を比較。 学習 value が
*配備忠実な構成* (= full beam 16/10 + value_defense ON/OFF は deck config 通り) で baseline を
超えれば = self-play 由来の **deployable な打倒 #1 改善**。 超えなければ配備しない (= 回帰を配備しない)。

⚠ 両 seat (deck=deck1 / deck=deck2) を回して平均する (= matrix の seat 非対称/低N noise を均す)。
   出る winrate は「deck の vs-opp 勝率」 = recompute_rank_vs_top.py --override deck=<wr> にそのまま渡せる。

  # 配備 GBM baseline vs 学習 iter5/iter7 を full beam で比較 (両 seat, N=80/seat):
  .venv/bin/python scripts/test_learned_value_deploy.py \
      --deck cardrush_1454 --opp tcgportal_calgara --arms default,iter5,iter7 --n 80
"""
import argparse
import sys
import time
import multiprocessing as mp
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


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _arm_path(arm, prefix):
    """arm 名 → 学習 pkl path。 "default" は None (= 配備 GBM を slug から auto-load)。"""
    if arm == "default":
        return None
    return str(ROOT / "db" / "_selfplay" / f"{prefix}{arm}.pkl")


def _mk_factory(slug, gbm, bw, bd):
    """deck_slug 付きで ExploitBeamAI を作る factory。 gbm=None → 配備 GBM auto-load +
    value_defense は db/deck_ai_config_<slug>.json 通り (= 配備忠実)。 gbm=path → leaf value 差替
    (= deploy したい学習 value)。 beam は bw/bd (= 16/10 配備忠実 or 8/6 高速 screen)。"""
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng,
                             deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             gbm_path=gbm, beam_width=bw, max_depth=bd)
    return aif


def _run(task):
    arm, deck, opp, prefix, n, seed, bw, bd = task
    gbm = _arm_path(arm, prefix)
    # seat 1: deck = deck1 (先攻/後攻は run_matchup 内で交互)
    rep1 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=_mk_factory(deck, gbm, bw, bd), ai_factory_2=_mk_factory(opp, None, bw, bd),
        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OVERLAY,
    )
    # seat 2: deck = deck2
    rep2 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed + 1, ai_factory_1=_mk_factory(opp, None, bw, bd), ai_factory_2=_mk_factory(deck, gbm, bw, bd),
        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck), effects_overlay=_OVERLAY,
    )
    deck_wins = rep1.deck1_wins + rep2.deck2_wins
    opp_wins = rep1.deck2_wins + rep2.deck1_wins
    draws = rep1.draws + rep2.draws
    return (arm, deck_wins, opp_wins, draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454", help="学習させた counter (= deck1)")
    ap.add_argument("--opp", default="tcgportal_calgara", help="標的 #1")
    ap.add_argument("--arms", default="default,iter5,iter7", help="default=配備GBM baseline, iterN=学習pkl")
    ap.add_argument("--pkl-prefix", default=None, help="既定 beamloop_<deck>_ (= selfplay_beam_loop 産)")
    ap.add_argument("--n", type=int, default=80, help="seat あたりの試合数 (両 seat で 2x)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--beam-width", type=int, default=16, help="16=配備忠実/8=高速screen")
    ap.add_argument("--max-depth", type=int, default=10, help="10=配備忠実/6=高速screen")
    a = ap.parse_args()
    prefix = a.pkl_prefix if a.pkl_prefix is not None else f"beamloop_{a.deck}_"
    arms = [x.strip() for x in a.arms.split(",")]
    tasks = [(arm, a.deck, a.opp, prefix, a.n, a.seed, a.beam_width, a.max_depth) for arm in arms]
    print(f"deploy gate: {a.deck}(beam {a.beam_width}/{a.max_depth}, 各 value) vs {a.opp}(配備) | "
          f"N={a.n}/seat x2seats seed={a.seed}")
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {arm: (w, l, d) for arm, w, l, d in res}
    base_w, base_l, base_d = by.get("default", (0, 0, 0))
    base_wr = base_w / max(1, base_w + base_l + base_d) * 100
    print(f"=== {a.deck}(beam+value) vs 配備 {a.opp} 勝率 (両 seat, N={a.n}x2) === ({time.time()-t0:.0f}s)")
    best_arm, best_wr = None, -1
    for arm in arms:
        w, l, d = by.get(arm, (0, 0, 0))
        wr = w / max(1, w + l + d) * 100
        tag = " ← baseline(配備GBM)" if arm == "default" else f"  (Δ={wr-base_wr:+.0f}pt)"
        print(f"  {arm:10} {w}-{l}-{d}  {wr:.0f}%{tag}")
        if arm != "default" and wr > best_wr:
            best_arm, best_wr = arm, wr
    if best_arm is not None:
        verdict = "DEPLOY 可 (baseline 超え)" if best_wr > base_wr + 2 else "配備しない (baseline 超えず = 回帰)"
        print(f"\n  best={best_arm} {best_wr:.0f}% vs baseline {base_wr:.0f}% → {verdict}")
        print(f"  → override 用 winrate = {best_wr/100:.3f} "
              f"(deploy: cp db/_selfplay/{prefix}{best_arm}.pkl db/value_gbm_{a.deck}.pkl)")


if __name__ == "__main__":
    main()
