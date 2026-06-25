"""control(受け) vs aggro(bonney) の deployed-faithful 勝率を測る再利用 A/B ハーネス。

全改善案(control-aware value / rollout GBM / search-arch)の共通の物差し。
deploy_counter の _mk_factory/_measure_seat を再利用 = 配備忠実 16/10 両 seat。
現在 deploy されている value(value_gbm_<slug>.pkl)を読むので、 value を差し替えて
再実行すれば before/after が測れる。

usage:
  .venv/bin/python scripts/ab_control_vs_aggro.py --n 24 --beam-width 16 --max-depth 10 \
      --controls cardrush_1385 cardrush_1392 cardrush_1342 --aggro tcgportal_bonney
"""
import argparse, multiprocessing as mp, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.deploy_counter import _measure_seat  # 配備忠実 seat 計測を再利用


def measure_control_vs_aggro(controls, aggro, n, bw, bd, seed=42, workers=12):
    """各 control deck の vs-aggro both-seat 勝率を返す。"""
    tasks = []
    for i, c in enumerate(controls):
        # _measure_seat task = (cond, seat, counter, top, gbm, n, seed, bw, bd)
        # counter=control, top=aggro, gbm=None → 配備 GBM auto-load (両者とも)
        tasks.append((c, "cA", c, aggro, None, n, seed + i, bw, bd))
        tasks.append((c, "tA", c, aggro, None, n, seed + 100 + i, bw, bd))
    with mp.Pool(min(workers, len(tasks))) as p:
        res = p.map(_measure_seat, tasks, chunksize=1)
    # res: (cond=control_slug, seat, cw=control_wins, tw=aggro_wins, draws)
    agg = {}
    for cond, seat, cw, tw, draws in res:
        d = agg.setdefault(cond, {"cw": 0, "tw": 0, "draws": 0, "games": 0})
        d["cw"] += cw; d["tw"] += tw; d["draws"] += draws; d["games"] += (cw + tw + draws)
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controls", nargs="+", default=["cardrush_1385", "cardrush_1392", "cardrush_1342"])
    ap.add_argument("--aggro", default="tcgportal_bonney")
    ap.add_argument("--n", type=int, default=24, help="seat あたり試合数")
    ap.add_argument("--beam-width", type=int, default=16)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    t0 = time.time()
    print(f"=== control vs aggro({a.aggro}) | {a.label} | n={a.n}/seat beam={a.beam_width}/{a.max_depth} ===", flush=True)
    agg = measure_control_vs_aggro(a.controls, a.aggro, a.n, a.beam_width, a.max_depth, a.seed)
    tot_c = tot_g = 0
    for c in a.controls:
        d = agg.get(c, {})
        g = d.get("games", 0); cw = d.get("cw", 0)
        wr = cw / g if g else 0.0
        tot_c += cw; tot_g += g
        print(f"  {c:<22} control勝率 = {wr*100:5.1f}%  ({cw}/{g}, draws={d.get('draws',0)})", flush=True)
    print(f"  ---- control 平均勝率 = {tot_c/tot_g*100:5.1f}%  ({tot_c}/{tot_g}) ----  [{time.time()-t0:.0f}s]", flush=True)


if __name__ == "__main__":
    main()
