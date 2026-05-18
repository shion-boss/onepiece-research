# -*- coding: utf-8 -*-
"""Plan F Step 2a (= 2026-05-18): 重み NN の evolutionary fine-tune。

base model (= supervised Step 1 完了 db/weight_nn.pt) から start、
gaussian perturbation で N variants 生成 → mirror baseline eval → 上位選抜で次世代。

数世代で 教師 (= dynamic_weights v2) を超える weights を発見させる。

実行例:
  .venv/bin/python scripts/train_weight_nn_evolutionary.py \\
    --base db/weight_nn.pt \\
    --output-dir db/weight_nn_evolved/ \\
    --generations 5 --variants 10 --sigma 0.1 --n-games-per-deck 5
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.weight_nn import WeightNN  # noqa: E402


def _perturb(model: WeightNN, sigma: float, seed: int) -> WeightNN:
    """base model に gaussian noise を加えた variant を返す。"""
    rng = torch.Generator()
    rng.manual_seed(seed)
    new_model = WeightNN()
    new_model.load_state_dict(copy.deepcopy(model.state_dict()))
    with torch.no_grad():
        for p in new_model.parameters():
            noise = torch.randn(p.shape, generator=rng) * sigma * p.std()
            p.add_(noise)
    new_model.eval()
    return new_model


def _eval_variant(variant: WeightNN, work_dir: Path, n_games_per_deck: int = 5,
                  variant_id: int = 0) -> tuple[float, dict]:
    """variant を mirror baseline で eval、 avg winrate を返す。"""
    # 一時保存
    variant_path = work_dir / f"variant_{variant_id}.pt"
    torch.save(variant.state_dict(), variant_path)

    # mirror eval (= ONEPIECE_WEIGHT_NN_PATH で variant を指定)
    output_path = work_dir / f"eval_{variant_id}.json"
    cmd = [
        ".venv/bin/python", "scripts/run_ai_mirror_eval.py",
        "--ai-class", "engine.ai_experimental.WeightNNPlanningAI",
        "--ai-kwargs", "{}",
        "--output", str(output_path),
        "--n-games", str(n_games_per_deck),
        "--label", f"variant_{variant_id}",
        "--force",
    ]
    env = {"ONEPIECE_WEIGHT_NN_PATH": str(variant_path), "PATH": "/usr/bin:/bin"}
    import os
    env.update(os.environ)
    env["ONEPIECE_WEIGHT_NN_PATH"] = str(variant_path)

    try:
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return 0.0, {"error": "timeout"}

    if not output_path.exists():
        return 0.0, {"error": "no_output", "stderr": result.stderr[-500:]}

    try:
        doc = json.loads(output_path.read_text(encoding="utf-8"))
        results = doc.get("results", [])
        if not results:
            return 0.0, {"error": "empty_results"}
        avg = sum(r["improved_winrate"] for r in results) / len(results)
        return avg, {"n_decks": len(results), "results": results}
    except Exception as e:
        return 0.0, {"error": str(e)}


def _weighted_mean_state_dict(state_dicts: list[dict], weights: list[float]) -> dict:
    """state_dict の list を weights で 加重平均。"""
    total_w = sum(weights)
    norm_w = [w / total_w for w in weights]
    out = {}
    for k in state_dicts[0]:
        out[k] = sum(sd[k] * w for sd, w in zip(state_dicts, norm_w))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="db/weight_nn.pt", help="supervised 完了 base model")
    ap.add_argument("--output-dir", default="db/weight_nn_evolved/")
    ap.add_argument("--generations", type=int, default=3, help="進化世代数")
    ap.add_argument("--variants", type=int, default=8, help="各世代の variant 数")
    ap.add_argument("--sigma", type=float, default=0.1, help="perturbation 強度")
    ap.add_argument("--n-games-per-deck", type=int, default=5)
    ap.add_argument("--top-k", type=int, default=3, help="次世代に残す上位数")
    args = ap.parse_args()

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # base load
    base_path = ROOT / args.base
    if not base_path.exists():
        print(f"[ERROR] base {base_path} not found")
        return 1
    base = WeightNN()
    base.load_state_dict(torch.load(base_path, map_location="cpu", weights_only=True))
    base.eval()
    print(f"=== evolutionary fine-tune 開始 ===")
    print(f"  base: {base_path}")
    print(f"  generations: {args.generations}, variants: {args.variants}, sigma: {args.sigma}")
    print(f"  n_games_per_deck: {args.n_games_per_deck} (= 16 × N = {16 * args.n_games_per_deck} 試合 / variant)")

    history = []
    current_best_score = 0.0

    for gen in range(args.generations):
        print(f"\n--- Generation {gen + 1}/{args.generations} ---")
        gen_dir = out_dir / f"gen_{gen + 1}"
        gen_dir.mkdir(parents=True, exist_ok=True)

        # 1. variants 生成
        variants = [_perturb(base, args.sigma, seed=gen * 1000 + i) for i in range(args.variants)]
        # base も含めて評価 (= 退化を防ぐ)
        variants.insert(0, base)

        # 2. 各 variant を eval
        scores = []
        for i, v in enumerate(variants):
            t_start = time.time()
            score, info = _eval_variant(v, gen_dir, args.n_games_per_deck, variant_id=i)
            elapsed = time.time() - t_start
            marker = "★base" if i == 0 else f"v{i}"
            print(f"  {marker}: avg={score*100:.1f}% ({elapsed:.0f}s)")
            scores.append(score)

        # 3. 上位 K 選抜
        ranked = sorted(zip(scores, variants), key=lambda x: -x[0])[:args.top_k]
        top_scores = [s for s, _ in ranked]
        top_variants = [v for _, v in ranked]
        print(f"  上位 {args.top_k}: {[f'{s*100:.1f}%' for s in top_scores]}")

        # 4. 次世代 base = 上位の weighted mean
        if top_scores[0] <= 0.5:
            # 上位が全て baseline 以下 → mutation 強める方向 (= sigma を増やす)
            print(f"  [WARN] best={top_scores[0]*100:.1f}% < 50%、 次世代 sigma を 1.5x に")
            args.sigma *= 1.5

        new_state = _weighted_mean_state_dict(
            [v.state_dict() for v in top_variants],
            top_scores,
        )
        new_base = WeightNN()
        new_base.load_state_dict(new_state)
        new_base.eval()
        new_path = gen_dir / "new_base.pt"
        torch.save(new_base.state_dict(), new_path)
        print(f"  next base saved: {new_path}")

        history.append({
            "generation": gen + 1,
            "all_scores": [float(s) for s in scores],
            "top_scores": [float(s) for s in top_scores],
            "best_score": float(top_scores[0]),
        })

        if top_scores[0] > current_best_score:
            current_best_score = top_scores[0]
            best_path = out_dir / "best.pt"
            torch.save(new_base.state_dict(), best_path)
            print(f"  ✔ new best: {current_best_score*100:.1f}% saved to {best_path}")

        base = new_base

    # history save
    history_path = out_dir / "evolution_history.json"
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== DONE. best score = {current_best_score*100:.1f}% ===")
    print(f"history: {history_path}")
    print(f"best model: {out_dir / 'best.pt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
