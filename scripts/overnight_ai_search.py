# -*- coding: utf-8 -*-
"""朝までの AI 強化 自走 search (= 2026-05-17 ユーザ要件)。

戦略:
1. 候補 case を順番に mirror eval (= 各 16 デッキ × 10 戦)
2. delta > +5pt の case は「promising」 → 50 戦で確定検証
3. delta > +10pt の case は「strong」 → 同系統の variant を candidate queue に追加 (= hill climb)
4. 各 case の結果を db/ai_search_results.json に追記
5. crash 時に再開可能 (= 既に完了した case は skip)
6. 朝にベスト案 + 全結果ランキングをレポート

実行例:
    nohup .venv/bin/python scripts/overnight_ai_search.py \\
        --output-dir db/ai_search/ --hours 8 \\
        > logs/overnight_ai_search.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# 初期候補 case リスト
INITIAL_CASES: list[dict] = [
    # === Phase 1: 設定 sweep ===
    {"label": "beam2_depth3_baseline_check",
     "ai_class": "engine.ai_experimental.DynamicBeamAI",
     "ai_kwargs": {}},  # ← まず動作確認用

    {"label": "PlanningAI_beam3_depth3",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 3, "max_depth": 3}},

    {"label": "PlanningAI_beam4_depth3",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 4, "max_depth": 3}},

    {"label": "PlanningAI_beam2_depth4",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 2, "max_depth": 4}},

    {"label": "PlanningAI_beam3_depth4",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 3, "max_depth": 4}},

    {"label": "PlanningAI_beam4_depth4",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 4, "max_depth": 4}},

    {"label": "PlanningAI_beam2_depth5",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 2, "max_depth": 5}},

    # === Phase 2: 自作 AI strategy ===
    {"label": "LethalRusherAI",
     "ai_class": "engine.ai_experimental.LethalRusherAI",
     "ai_kwargs": {}},

    {"label": "DynamicBeamAI",
     "ai_class": "engine.ai_experimental.DynamicBeamAI",
     "ai_kwargs": {}},

    {"label": "HybridGreedyPlanning",
     "ai_class": "engine.ai_experimental.HybridGreedyPlanning",
     "ai_kwargs": {}},

    {"label": "AdaptiveBeamDepthAI",
     "ai_class": "engine.ai_experimental.AdaptiveBeamDepthAI",
     "ai_kwargs": {}},

    # === Phase 3: weight multiplier 系 (= eval.py 改造未済、 後回し可) ===
    # {"label": "AggressivePlanning_lethal2",
    #  "ai_class": "engine.ai_experimental.AggressivePlanningAI",
    #  "ai_kwargs": {"lethal_mult": 2.0}},

    # === Phase 4: 重い設定 (= 時間余れば) ===
    {"label": "PlanningAI_beam4_depth5",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 4, "max_depth": 5}},

    {"label": "PlanningAI_beam3_depth5",
     "ai_class": "engine.ai_experimental._NoNNPlanningBase",
     "ai_kwargs": {"beam_width": 3, "max_depth": 5}},
]


def _summary_path(out_dir: Path) -> Path:
    return out_dir / "_summary.json"


def _load_summary(out_dir: Path) -> dict:
    p = _summary_path(out_dir)
    if not p.exists():
        return {"cases": [], "best": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"cases": [], "best": None}


def _save_summary(out_dir: Path, doc: dict) -> None:
    p = _summary_path(out_dir)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _run_one_case(case: dict, out_dir: Path, n_games: int = 10, seed: int = 42) -> dict:
    """1 case 実行 → 結果 (= avg winrate + delta) 返す。"""
    label = case["label"]
    out_path = out_dir / f"{label}.json"

    # 既に完了済 (= 16 デッキ全て) なら skip
    if out_path.exists():
        try:
            d = json.loads(out_path.read_text(encoding="utf-8"))
            if d.get("decks_done") == d.get("decks_total") and d.get("n_games_per_deck") == n_games:
                avg = sum(r["improved_winrate"] for r in d["results"]) / len(d["results"])
                return {"label": label, "avg_winrate": avg, "delta_pt": (avg - 0.5) * 100, "skipped": True}
        except Exception:
            pass

    cmd = [
        ".venv/bin/python", "scripts/run_ai_mirror_eval.py",
        "--ai-class", case["ai_class"],
        "--ai-kwargs", json.dumps(case["ai_kwargs"]),
        "--output", str(out_path),
        "--n-games", str(n_games),
        "--seed", str(seed),
        "--label", label,
    ]
    print(f"\n=== START: {label} (n_games={n_games}) ===", flush=True)
    print(f"  cmd: {' '.join(cmd)}", flush=True)
    t0 = time.time()
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=3600)
        out_text = result.stdout + "\n" + result.stderr
        elapsed = time.time() - t0
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print(f"  [TIMEOUT] {label} after {elapsed:.0f}s", flush=True)
        return {"label": label, "avg_winrate": None, "delta_pt": None, "error": "timeout"}

    # 結果読み取り
    if not out_path.exists():
        print(f"  [ERROR] no output for {label}", flush=True)
        return {"label": label, "avg_winrate": None, "delta_pt": None, "error": "no_output"}

    try:
        d = json.loads(out_path.read_text(encoding="utf-8"))
        results = d.get("results", [])
        if not results:
            return {"label": label, "avg_winrate": None, "delta_pt": None, "error": "empty_results"}
        avg = sum(r["improved_winrate"] for r in results) / len(results)
        delta = (avg - 0.5) * 100
        n_wins = sum(1 for r in results if r["improved_winrate"] > 0.55)
        n_losses = sum(1 for r in results if r["improved_winrate"] < 0.45)
        print(f"  [DONE] {label}: avg={avg*100:.1f}% delta={delta:+.1f}pt ({n_wins} W / {n_losses} L) in {elapsed:.0f}s", flush=True)
        return {
            "label": label, "avg_winrate": avg, "delta_pt": delta,
            "wins": n_wins, "losses": n_losses, "elapsed_sec": elapsed,
            "n_games_per_deck": n_games,
        }
    except Exception as e:
        return {"label": label, "avg_winrate": None, "delta_pt": None, "error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="db/ai_search/")
    ap.add_argument("--hours", type=float, default=8.0,
                    help="self-imposed time limit (= 朝起きるまでの hours)")
    ap.add_argument("--n-games-screen", type=int, default=10,
                    help="screen pass n_games per deck (= 小サンプル)")
    ap.add_argument("--n-games-validate", type=int, default=50,
                    help="promising case の確定検証 n_games (= 大サンプル)")
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = _load_summary(out_dir)
    completed_labels = {c["label"] for c in summary.get("cases", []) if c.get("avg_winrate") is not None}
    print(f"=== overnight AI search 開始 ===", flush=True)
    print(f"  output: {out_dir}", flush=True)
    print(f"  budget: {args.hours} hours", flush=True)
    print(f"  完了済 case: {len(completed_labels)}", flush=True)
    print(f"  initial 候補: {len(INITIAL_CASES)}", flush=True)

    t_start = time.time()
    deadline = t_start + args.hours * 3600

    case_queue: list[dict] = list(INITIAL_CASES)
    promising: list[dict] = []  # delta > +5pt の case (= 後で 50 戦確定検証)

    while case_queue:
        if time.time() > deadline:
            print(f"\n=== TIME OUT (= {args.hours}h) ===", flush=True)
            break

        case = case_queue.pop(0)
        if case["label"] in completed_labels:
            print(f"  [SKIP existing] {case['label']}", flush=True)
            continue

        # screen pass (= n_games_screen)
        r = _run_one_case(case, out_dir, n_games=args.n_games_screen, seed=42)
        summary["cases"].append(r)
        _save_summary(out_dir, summary)
        completed_labels.add(r["label"])

        # promising 判定 (= 後で 50 戦)
        if r.get("delta_pt") is not None and r["delta_pt"] > 5.0:
            promising.append(case)
            print(f"  [PROMISING] {case['label']} delta={r['delta_pt']:+.1f}pt → 後で 50 戦検証", flush=True)

        # hill climb (= strong case の variant 自動生成)
        if r.get("delta_pt") is not None and r["delta_pt"] > 10.0:
            # 同系統の variant を queue に追加 (= 設定 sweep のみ対応)
            kw = case["ai_kwargs"]
            if "beam_width" in kw and "max_depth" in kw:
                variants = []
                for db in (-1, +1):
                    for dd in (-1, +1):
                        nb = kw["beam_width"] + db
                        nd = kw["max_depth"] + dd
                        if 1 <= nb <= 5 and 2 <= nd <= 6:
                            new_kw = dict(kw, beam_width=nb, max_depth=nd)
                            v_label = f"hillclimb_b{nb}_d{nd}_from_{case['label']}"
                            if v_label not in completed_labels:
                                variants.append({"label": v_label, "ai_class": case["ai_class"], "ai_kwargs": new_kw})
                if variants:
                    case_queue = variants + case_queue
                    print(f"  [HILL CLIMB] adding {len(variants)} variants", flush=True)

    # promising case の確定検証
    elapsed_so_far = time.time() - t_start
    remaining = deadline - time.time()
    print(f"\n=== screen pass 完了、 elapsed {elapsed_so_far/60:.1f} min、 残 {remaining/60:.0f} min ===", flush=True)
    print(f"=== promising case 確定検証 (= n_games={args.n_games_validate}) ===", flush=True)

    # delta 大きい順に確定検証
    promising.sort(key=lambda c: -next((s["delta_pt"] for s in summary["cases"] if s["label"] == c["label"]), 0))
    for case in promising:
        if time.time() > deadline:
            print(f"  [TIME OUT in validation]", flush=True)
            break
        case_validate = dict(case)
        case_validate["label"] = case["label"] + "_validated50"
        if case_validate["label"] in completed_labels:
            continue
        r = _run_one_case(case_validate, out_dir, n_games=args.n_games_validate, seed=42)
        summary["cases"].append(r)
        _save_summary(out_dir, summary)
        completed_labels.add(r["label"])

    # 最終 best 更新
    completed_with_score = [c for c in summary["cases"] if c.get("avg_winrate") is not None]
    if completed_with_score:
        best = max(completed_with_score, key=lambda c: c["avg_winrate"])
        summary["best"] = best
        _save_summary(out_dir, summary)
        print(f"\n=== 最終 best ===", flush=True)
        print(f"  label: {best['label']}", flush=True)
        print(f"  avg_winrate: {best['avg_winrate']*100:.1f}% (mirror 期待 50%)", flush=True)
        print(f"  delta: {best.get('delta_pt', 0):+.1f}pt", flush=True)

    # ランキング表示
    print(f"\n=== 全結果ランキング (= 完了 {len(completed_with_score)} case) ===", flush=True)
    ranked = sorted(completed_with_score, key=lambda c: -c["avg_winrate"])
    for r in ranked:
        n = r.get("n_games_per_deck", "?")
        print(f"  {r['label']:<50} avg={r['avg_winrate']*100:>5.1f}% delta={r.get('delta_pt',0):>+5.1f}pt (n={n})", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
