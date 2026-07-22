#!/usr/bin/env python3
"""改善版 value を EBV2 (現配備基準) 相手にミラー対戦させ、 改善量を測る標準ベンチ。

ohtsuki 2026-07-22 決定: **今後の改善計測の基準相手 = EBV2** (= ExploitBeam + agnostic v2)。
board_eval を基準にすると弱くて何でも良く見える (今日の失敗) を繰り返さない為、 **今の実力
(EBV2) を超えたものだけを本物の改善**とする。

方式 = **改善版 vs EBV2 の同一デッキ・ミラー**: 両者が同じデッキを持ち value(頭脳) だけが違う
→ デッキ差ゼロで「手の良さ」だけを純粋比較。 勝率50%超なら改善。

⚠ ミラーは engine の先攻(P0)有利が bias になる ([[feedback_ab_harness_balance_player_index]])
ので、 **両 seat を均等化** (改善版が P0 の games と P1 の games を同数) して公平に測る。

基準 EBV2 = db/value_gbm_ebv2_baseline.pkl (= 2026-07-22 凍結、 agnostic v2 21次元。 今後
agnostic を強化して value_gbm_agnostic.pkl が変わっても、 基準は不変)。

  .venv/bin/python scripts/bench_vs_ebv2.py --cand db/_selfplay/my_new_value.pkl \
      --decks cardrush_1454,tcgportal_calgara,pros02_luffy_gb --n 40
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
_EBV2 = str(ROOT / "db" / "value_gbm_ebv2_baseline.pkl")


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk(slug, gbm, bw, bd):
    """gbm = value pkl パス。 deck_slug は同一 (ミラー) だが value だけ差し替える。"""
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             gbm_path=gbm, beam_width=bw, max_depth=bd)
    return aif


def _run(task):
    """1 デッキのミラー: 改善版(cand) vs EBV2。 両 seat 均等化して先攻 bias を除去。"""
    deck, cand, n, seed, bw, bd = task
    dl = DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO)
    ana = _ana(deck)
    # seat1: cand = P0, ebv2 = P1
    rep1 = run_matchup(
        dl, DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed,
        ai_factory_1=_mk(deck, cand, bw, bd), ai_factory_2=_mk(deck, _EBV2, bw, bd),
        deck1_analysis=ana, deck2_analysis=ana, effects_overlay=_OVERLAY,
    )
    # seat2: ebv2 = P0, cand = P1 (先攻を入れ替え)。 ⚠ seed は seat1 と同一にする
    # (= 同じ初期手札・乱数列で先攻/後攻だけ入替えた対称ゲーム)。 seed をずらすと別ゲーム群
    # になり同一value同士でも 50% に収束しない (= seat 均等化が壊れる、 sanity で検出)。
    rep2 = run_matchup(
        dl, DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed,
        ai_factory_1=_mk(deck, _EBV2, bw, bd), ai_factory_2=_mk(deck, cand, bw, bd),
        deck1_analysis=ana, deck2_analysis=ana, effects_overlay=_OVERLAY,
    )
    cand_wins = rep1.deck1_wins + rep2.deck2_wins
    ebv2_wins = rep1.deck2_wins + rep2.deck1_wins
    draws = rep1.draws + rep2.draws
    return (deck, cand_wins, ebv2_wins, draws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", required=True, help="改善版 value pkl のパス")
    ap.add_argument("--decks", default="cardrush_1454,tcgportal_calgara,cardrush_1385,pros02_luffy_gb")
    ap.add_argument("--n", type=int, default=40, help="seat あたり (両 seat で 2x)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam-width", type=int, default=16)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    cand = a.cand if Path(a.cand).is_absolute() else str(ROOT / a.cand)
    if not Path(cand).exists():
        print(f"!! 改善版 pkl が無い: {cand}"); return
    decks = [s.strip() for s in a.decks.split(",")]
    tasks = [(d, cand, a.n, a.seed, a.beam_width, a.max_depth) for d in decks]
    print(f"vs EBV2 ミラーベンチ: cand={Path(cand).name} | decks={decks} | "
          f"N={a.n}/seat x2 | beam={a.beam_width}/{a.max_depth}", flush=True)
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    print(f"\n=== 改善版 vs EBV2 (同一デッキ・ミラー、 両seat均等) === ({time.time()-t0:.0f}s)")
    print(f"{'deck':24}{'cand%':>8}{'games':>8}")
    tot_c = tot_e = tot_d = 0
    for deck, cw, ew, dr in res:
        tot = cw + ew + dr
        tot_c += cw; tot_e += ew; tot_d += dr
        wr = cw / max(1, tot) * 100
        mark = " ✓改善" if wr > 52 else (" ✗劣化" if wr < 48 else " =互角")
        print(f"{deck:24}{wr:8.1f}{tot:8d}{mark}")
    overall = tot_c / max(1, tot_c + tot_e + tot_d) * 100
    n_total = tot_c + tot_e + tot_d
    print(f"{'OVERALL':24}{overall:8.1f}{n_total:8d}")
    delta = overall - 50.0
    verdict = ("改善 (EBV2 超え、 配備候補)" if overall > 52 else
               "互角 (改善なし、 [[feedback_ab_statistical_power]] N不足かも)" if overall >= 48 else
               "劣化 (EBV2 に負け、 却下)")
    print(f"\n  → cand は EBV2 相手に {overall:.1f}% ({delta:+.1f}pt) = {verdict}")
    print(f"  ※ 配備 gate は N>=60/deck 級で有意確認 (これは screen)")


if __name__ == "__main__":
    main()
