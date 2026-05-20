# -*- coding: utf-8 -*-
"""Plan E (= 2026-05-18): genetic algorithm で AI variant を進化させ最強 AI を発見。

ohtsuki さん示唆 ([[feedback_evolutionary_over_tuning]]) の本格実装:
  - 人間がチューニングするより、 多数バリエーション × 競争 × 進化で「想定外の最強」 を発見

Generation:
  1. base AI から N variants 生成 (= NN weight perturbation + hyperparameter mutation)
  2. mirror tournament で 全 vs 全 (or vs baseline) → 上位 K 選抜
  3. 上位 weighted mean で 次世代 base (= 進化的選択)
  4. 反復 (= 10-30 世代)

実行:
  .venv/bin/python scripts/plan_e_genetic_ai_search.py \\
    --generations 5 --variants 8 \\
    --output-dir db/plan_e/
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.weight_nn import WeightNN  # noqa: E402


def _perturb_weights(state_dict: dict, sigma: float, seed: int) -> dict:
    """state_dict を gaussian noise で perturb。"""
    rng = torch.Generator()
    rng.manual_seed(seed)
    new = {}
    for k, v in state_dict.items():
        if isinstance(v, torch.Tensor) and v.dtype.is_floating_point:
            noise = torch.randn(v.shape, generator=rng) * sigma * v.abs().mean().clamp(min=0.01)
            new[k] = v + noise
        else:
            new[k] = v.clone() if isinstance(v, torch.Tensor) else v
    return new


def _eval_variant(variant_path: Path, n_games: int = 5, label: str = "v") -> float:
    """variant を mirror baseline で評価 (= avg winrate)。"""
    import subprocess
    import os
    out_path = variant_path.parent / f"eval_{label}.json"
    cmd = [
        ".venv/bin/python", "scripts/run_ai_mirror_eval.py",
        "--ai-class", "engine.ai_experimental.WeightNNTwoTurnAI",
        "--ai-kwargs", "{}",
        "--output", str(out_path),
        "--n-games", str(n_games),
        "--label", label,
        "--force",
    ]
    env = dict(os.environ)
    env["ONEPIECE_WEIGHT_NN_PATH"] = str(variant_path)
    env["ONEPIECE_WEIGHT_NN"] = "1"
    try:
        subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=2400)
    except subprocess.TimeoutExpired:
        return 0.0
    if not out_path.exists():
        return 0.0
    try:
        d = json.loads(out_path.read_text(encoding="utf-8"))
        results = d.get("results", [])
        if not results:
            return 0.0
        return sum(r["improved_winrate"] for r in results) / len(results)
    except Exception:
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="db/weight_nn.pt")
    ap.add_argument("--output-dir", default="db/plan_e/")
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--variants", type=int, default=6)
    ap.add_argument("--sigma", type=float, default=0.3)
    ap.add_argument("--n-games-per-deck", type=int, default=3)
    ap.add_argument("--top-k", type=int, default=2)
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    base_path = ROOT / args.base
    print(f"=== Plan E genetic AI search ===")
    print(f"  base: {base_path}")
    print(f"  generations: {args.generations}, variants: {args.variants}, sigma: {args.sigma}")

    current_base_path = base_path
    history = []

    for gen in range(args.generations):
        print(f"\n--- Generation {gen + 1}/{args.generations} ---")
        gen_dir = out_dir / f"gen_{gen + 1}"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # base load
        base_sd = torch.load(current_base_path, map_location="cpu", weights_only=True)

        # variants 生成 (= base + perturb × N、 base 自身も含む)
        variants = [(0, base_sd, "base")]
        for i in range(args.variants):
            sd = _perturb_weights(base_sd, args.sigma, seed=gen * 10000 + i)
            variants.append((i + 1, sd, f"v{i+1}"))

        # 各 variant save + eval
        scores = []
        for idx, sd, label in variants:
            var_path = gen_dir / f"variant_{idx}.pt"
            torch.save(sd, var_path)
            t_start = time.time()
            score = _eval_variant(var_path, args.n_games_per_deck, f"gen{gen+1}_{label}")
            elapsed = time.time() - t_start
            marker = "★" if label == "base" else " "
            print(f"  {marker} {label}: avg={score*100:.1f}% ({elapsed:.0f}s)")
            scores.append((idx, sd, label, score))

        # 上位 K 選抜 + weighted mean で 次世代
        scores.sort(key=lambda x: -x[3])
        top = scores[:args.top_k]
        print(f"  上位 {args.top_k}: {[(t[2], f'{t[3]*100:.1f}%') for t in top]}")

        top_scores = [t[3] for t in top]
        top_sds = [t[1] for t in top]
        if sum(top_scores) > 0:
            norm_w = [s / sum(top_scores) for s in top_scores]
            new_sd = {}
            for k in top_sds[0]:
                if isinstance(top_sds[0][k], torch.Tensor) and top_sds[0][k].dtype.is_floating_point:
                    new_sd[k] = sum(sd[k] * w for sd, w in zip(top_sds, norm_w))
                else:
                    new_sd[k] = top_sds[0][k]
        else:
            new_sd = top_sds[0]

        new_path = gen_dir / "new_base.pt"
        torch.save(new_sd, new_path)
        current_base_path = new_path
        history.append({
            "generation": gen + 1,
            "scores": {t[2]: float(t[3]) for t in scores},
            "top_avg": sum(top_scores) / len(top_scores),
        })

    # final 結果保存
    history_path = out_dir / "evolution_history.json"
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    final_path = out_dir / "best.pt"
    torch.save(torch.load(current_base_path, map_location="cpu", weights_only=True), final_path)
    print(f"\n=== DONE. best model: {final_path} ===")
    print(f"history: {history_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
