# -*- coding: utf-8 -*-
"""matchup-aware (on-policy v6) 品質改善を全 meta deck へ自律連続配備するドライバ。

各 deck を end-to-end で処理 (checkpoint/resume 付き):
  1. on-policy v6 loop (selfplay_beam_loop.py, ONEPIECE_GBM_V6=1, deck vs diverse5)
  2. SLOPE から best iter を選び cmp_<deck>_v6onp.pkl に
  3. single high-N gate (matchup_value_deploy_ab.py, default vs v6onp, trained5+heldout)
  4. 判定: overall Δ>=THRESH かつ positive 比率>=0.7 → 配備 (backup→cp→git commit)
  5. rollout_log.json に記録 (resume 用)。 既処理 deck は skip。

recipe は bonney/hancock/dofla で確立済 ([[project_leader_aware_matchup_ai]])。 ここは横展開の自動化。

  .venv/bin/python scripts/rollout_deck_pipeline.py --decks cardrush_1385,cardrush_1392,... \
      --iters 12 --games 80 --gate-n 80
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = ROOT / "db" / "_selfplay"
LOGJSON = SELF / "rollout_log.json"
PY = str(ROOT / ".venv" / "bin" / "python")

# 多様な opp プール (aggro/control/ramp/midrange)。 subject は除外。 先頭5=訓練、 残り=held-out。
POOL = ["tcgportal_calgara", "cardrush_1385", "cardrush_1454", "cardrush_1456",
        "cardrush_1453", "cardrush_1392", "cardrush_1399", "tcgportal_bonney"]


def _slug_to_gbm(slug):
    return ROOT / "db" / f"value_gbm_{slug}.pkl"


def load_log():
    if LOGJSON.exists():
        return json.loads(LOGJSON.read_text())
    return {}


def save_log(d):
    LOGJSON.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def run_loop(deck, train_opps, iters, games, log):
    env = dict(os.environ); env["ONEPIECE_GBM_V6"] = "1"
    logf = SELF / f"rollout_loop_{deck}.log"
    cmd = [PY, str(ROOT / "scripts" / "selfplay_beam_loop.py"),
           "--deck", deck, "--opp", ",".join(train_opps),
           "--iters", str(iters), "--games", str(games), "--eval", "40",
           "--epsilon", "0.30", "--eps-end", "0.05",
           "--beam-width", "8", "--max-depth", "6", "--workers", "12"]
    with open(logf, "w") as f:
        subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
    txt = logf.read_text()
    m = re.search(r"=== SLOPE: \[(.*?)\] ===", txt)
    if not m:
        raise RuntimeError("no SLOPE in loop log")
    slope = [float(x.strip().strip("'%")) for x in m.group(1).split(",")]
    # best iter: argmax SLOPE among iters>=5 (= enough data, avoid early under-trained)
    cand = [(i, s) for i, s in enumerate(slope) if i >= 5]
    best_iter = max(cand, key=lambda z: z[1])[0] if cand else int(max(range(len(slope)), key=lambda i: slope[i]))
    src = SELF / f"beamloop_{deck}_iter{best_iter}.pkl"
    dst = SELF / f"cmp_{deck}_v6onp.pkl"
    shutil.copy(src, dst)
    return slope, best_iter


def run_gate(deck, gate_opps, n, seed):
    logf = SELF / f"rollout_gate_{deck}.log"
    cmd = [PY, str(ROOT / "scripts" / "matchup_value_deploy_ab.py"),
           "--deck", deck, "--opps", ",".join(gate_opps),
           "--prefix", f"cmp_{deck}_", "--arms", "default,v6onp",
           "--n", str(n), "--seed", str(seed),
           "--beam-width", "16", "--max-depth", "10", "--workers", "12"]
    with open(logf, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
    txt = logf.read_text()
    # parse table rows: "<opp>  default%  v6onp%" and OVERALL
    rows = {}
    overall = None
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                d_, v_ = float(parts[-2]), float(parts[-1])
            except ValueError:
                continue
            key = parts[0]
            if key == "OVERALL":
                overall = (d_, v_)
            elif key in gate_opps:
                rows[key] = (d_, v_)
    if overall is None:
        raise RuntimeError("no OVERALL in gate log")
    return rows, overall


def deploy(deck):
    gbm = _slug_to_gbm(deck)
    shutil.copy(gbm, SELF / f"{deck}_PREv6_backup.pkl")
    shutil.copy(SELF / f"cmp_{deck}_v6onp.pkl", gbm)
    subprocess.run(["git", "-C", str(ROOT), "add", str(gbm.relative_to(ROOT))], check=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-q", "-m",
                    f"deploy(ai): {deck} v6 matchup-conditioned value (auto-rollout)\n\n"
                    f"on-policy v6 (matchup eval + interaction + scale) が single high-N gate で "
                    f"配備 baseline を上回ったため自律配備。 recipe は bonney/hancock/dofla で確立済 "
                    f"([[project_leader_aware_matchup_ai]])。 38-dim、 gbm_score 自動判別。\n\n"
                    f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", required=True, help="comma list of subject deck slugs")
    ap.add_argument("--iters", type=int, default=12)
    ap.add_argument("--games", type=int, default=80)
    ap.add_argument("--gate-n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--threshold", type=float, default=4.0, help="overall Δpt 配備閾値")
    ap.add_argument("--pos-frac", type=float, default=0.7, help="positive opp 比率 閾値")
    a = ap.parse_args()
    decks = [s.strip() for s in a.decks.split(",") if s.strip()]
    log = load_log()
    print(f"[rollout] {len(decks)} decks | done so far: {sum(1 for d in log.values() if d.get('status') in ('DEPLOYED','SKIPPED'))}", flush=True)
    for deck in decks:
        if deck in log and log[deck].get("status") in ("DEPLOYED", "SKIPPED"):
            print(f"[skip] {deck} already {log[deck]['status']}", flush=True)
            continue
        opps = [x for x in POOL if x != deck]
        train_opps, gate_opps = opps[:5], opps
        t0 = time.time()
        print(f"\n[deck] {deck} | train={train_opps} | gate={len(gate_opps)} opps", flush=True)
        rec = {"deck": deck, "train_opps": train_opps, "started": int(t0)}
        try:
            slope, best_iter = run_loop(deck, train_opps, a.iters, a.games, log)
            rec["slope"] = slope; rec["best_iter"] = best_iter
            print(f"  loop done: best_iter={best_iter} SLOPE_best={max(slope):.0f}% ({time.time()-t0:.0f}s)", flush=True)
            rows, overall = run_gate(deck, gate_opps, a.gate_n, a.seed)
            d_ov, v_ov = overall
            delta = v_ov - d_ov
            pos = sum(1 for o, (dd, vv) in rows.items() if vv >= dd)
            frac = pos / max(1, len(rows))
            rec.update({"overall_default": d_ov, "overall_v6": v_ov, "delta": delta,
                        "pos": pos, "n_opp": len(rows), "per_opp": rows})
            ok = delta >= a.threshold and frac >= a.pos_frac
            print(f"  gate: default={d_ov:.1f} v6={v_ov:.1f} Δ={delta:+.1f} pos={pos}/{len(rows)} → {'DEPLOY' if ok else 'SKIP'} ({time.time()-t0:.0f}s)", flush=True)
            if ok:
                deploy(deck)
                rec["status"] = "DEPLOYED"
            else:
                rec["status"] = "SKIPPED"
        except Exception as e:
            rec["status"] = "ERROR"; rec["error"] = str(e)
            print(f"  ERROR: {e}", flush=True)
        rec["secs"] = int(time.time() - t0)
        log[deck] = rec
        save_log(log)
    n_dep = sum(1 for d in log.values() if d.get("status") == "DEPLOYED")
    print(f"\n[rollout done] DEPLOYED={n_dep} | SKIPPED={sum(1 for d in log.values() if d.get('status')=='SKIPPED')} | ERROR={sum(1 for d in log.values() if d.get('status')=='ERROR')}", flush=True)


if __name__ == "__main__":
    main()
