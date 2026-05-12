# -*- coding: utf-8 -*-
"""
AI 対戦スキル向上 学習サイクル
==================================

`engine/eval.py` の評価重みと `engine/ai.py` の意思決定閾値を、 敗北データから
自己改善する。

ループ:
  1. baseline: 現 ai_params で 全 N×N matchup を実行 (replay 永続化)
  2. tier_truth (db/tier_truth.json) と比較して予測精度を計算
  3. 敗北 replay → 敗因タグ集計
  4. 上位タグ → params_to_tune で学習対象 AIParams フィールド抽出
  5. grid search: 各候補値で matrix 再計算 → 予測精度 + 勝率分散ペナルティでスコア
  6. 最良が baseline を上回ったら db/ai_params.json に書き込み (--apply のみ)
  7. before/after diff を db/learn_reports/<date>.md に出力

使い方:
    .venv/bin/python scripts/learn_ai_params.py --no-grid             # 診断のみ
    .venv/bin/python scripts/learn_ai_params.py --n-games 10          # short loop
    .venv/bin/python scripts/learn_ai_params.py --target-tag activate_main_overused
    .venv/bin/python scripts/learn_ai_params.py --apply               # 採用して保存
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.ai_params import AIParams, DEFAULT_PATH as AI_PARAMS_PATH   # noqa: E402
from engine.deck import CardRepository, DeckList                         # noqa: E402
from engine.harness import run_matchup                                   # noqa: E402
from engine.loss_classifier import (                                     # noqa: E402
    aggregate_loss_tags,
    classify_loss,
    params_to_tune,
    TAG_TO_PARAMS,
)
from engine.replay_recorder import DB_PATH as REPLAYS_DB_PATH, list_replays  # noqa: E402

TIER_TRUTH_PATH = ROOT / "db" / "tier_truth.json"
REPORTS_DIR = ROOT / "db" / "learn_reports"

# === Grid search 候補値 (各 param ごとに探索する値リスト) ===
# 重み系は [0.7x, 1.0x, 1.3x] の倍率、 閾値系は近傍 4-5 点で探索。
GRID_CANDIDATES_RATIO = [0.7, 1.0, 1.3]
GRID_CANDIDATES_ABSOLUTE: dict[str, list] = {
    "activate_main_min_payoff_global": [0, 300, 600, 1000, 1500],
    "activate_main_don_compensated_strict": [False, True],
    "attack_gap_tolerance_default": [-1000, -500, 0, 500],
    "defense_threshold_life_le_1": [99999, 50000, 99999],
    "defense_threshold_life_eq_2": [6000, 8000, 10000],
    "defense_threshold_life_eq_3": [4000, 6000, 8000],
    "defense_threshold_life_ge_4": [0, 2000, 4000],
}


def _winrate_to_tier(wr: float, thresholds: dict) -> str:
    """勝率から tier (S/A/B/C/D) を判定。"""
    if wr >= thresholds.get("S", 0.85):
        return "S"
    if wr >= thresholds.get("A", 0.75):
        return "A"
    if wr >= thresholds.get("B", 0.50):
        return "B"
    if wr >= thresholds.get("C", 0.25):
        return "C"
    return "D"


def _run_matrix(
    decks: list[tuple[str, str, DeckList]],
    n_games: int,
    seed: int,
    record_replays: bool,
    replays_db_path: Optional[Path] = None,
    verbose: bool = False,
    ai_factory=None,
) -> dict:
    """全 N×N matchup を実行し、 集計勝率と replay パスを返す。

    ai_factory: AI コンストラクタ (省略時は GreedyAI)。 両プレイヤーに適用。
    """
    if ai_factory is None:
        from engine.ai import GreedyAI as _DefaultAI
        ai_factory = _DefaultAI
    pair_winrates: dict[str, list[float]] = {s: [] for s, _, _ in decks}
    t0 = time.time()
    total = len(decks) * (len(decks) - 1)
    done = 0
    for slug_a, name_a, deck_a in decks:
        for slug_b, name_b, deck_b in decks:
            if slug_a == slug_b:
                continue
            done += 1
            rep = run_matchup(
                deck_a, deck_b, n_games=n_games, seed=seed,
                record_replays=record_replays,
                replays_db_path=replays_db_path,
                ai_factory_1=ai_factory,
                ai_factory_2=ai_factory,
            )
            pair_winrates[slug_a].append(rep.deck1_winrate)
            if verbose and done % max(1, total // 10) == 0:
                elapsed = time.time() - t0
                print(f"    matrix progress {done}/{total}  {elapsed:.0f}s")
    avg_winrates = {
        s: (statistics.mean(wr_list) if wr_list else 0.0)
        for s, wr_list in pair_winrates.items()
    }
    return {
        "avg_winrates": avg_winrates,
        "n_games": n_games,
        "seed": seed,
    }


def _prediction_accuracy(matrix: dict, tier_truth: dict) -> float:
    """matrix の勝率 → tier 推定が tier_truth とどれだけ一致するか (0.0-1.0)。"""
    thresholds = tier_truth.get("tier_thresholds", {})
    tiers = tier_truth.get("tiers", {})
    matched = 0
    total = 0
    for slug, info in tiers.items():
        wr = matrix["avg_winrates"].get(slug)
        if wr is None:
            continue
        total += 1
        predicted = _winrate_to_tier(wr, thresholds)
        if predicted == info["tier"]:
            matched += 1
    return matched / max(1, total)


def _winrate_variance_penalty(matrix: dict, tier_truth: dict) -> float:
    """予測勝率と expected_winrate の MSE。 学習で過剰チューニング (= 個別デッキだけ
    強くなって他が崩れる) を防ぐためのペナルティ項。 0.0 以上、 小さいほど良い。
    """
    tiers = tier_truth.get("tiers", {})
    sq_errs = []
    for slug, info in tiers.items():
        wr = matrix["avg_winrates"].get(slug)
        exp = info.get("expected_winrate")
        if wr is None or exp is None:
            continue
        sq_errs.append((wr - exp) ** 2)
    return statistics.mean(sq_errs) if sq_errs else 0.0


def _score(matrix: dict, tier_truth: dict) -> dict:
    acc = _prediction_accuracy(matrix, tier_truth)
    pen = _winrate_variance_penalty(matrix, tier_truth)
    # 合成スコア: 予測精度 - 分散ペナルティ (重み付け)
    return {
        "accuracy": acc,
        "variance_penalty": pen,
        "composite": acc - 0.5 * pen,
    }


def _candidates_for_param(param: str, current_value) -> list:
    """対象 param の grid 候補値を返す。"""
    if param in GRID_CANDIDATES_ABSOLUTE:
        return GRID_CANDIDATES_ABSOLUTE[param]
    # 重み系: 倍率で展開
    if isinstance(current_value, (int, float)) and current_value != 0:
        return [int(round(current_value * r)) for r in GRID_CANDIDATES_RATIO]
    return [current_value]


def _apply_param_values(
    base: AIParams, param_values: dict
) -> AIParams:
    """AIParams に param_values を上書きしたコピーを返す。"""
    valid_fields = {f for f in asdict(base).keys()}
    safe = {k: v for k, v in param_values.items() if k in valid_fields}
    return replace(base, **safe)


def _write_param_overrides(params: AIParams) -> None:
    """grid search 中に AIParams を一時的に反映するため、 json を書き換える。

    本番採用は別途 --apply で行う。 ここは matrix 計算間で AI 側にロードさせるための
    一時的な書き出し (= history は書き換えない)。
    """
    data = {}
    if AI_PARAMS_PATH.exists():
        data = json.loads(AI_PARAMS_PATH.read_text(encoding="utf-8"))
    data["params"] = asdict(params)
    data["note"] = data.get("note", "") + " [grid_search_temp]"
    AI_PARAMS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # eval.py の DEFAULT_WEIGHTS も即時更新
    from engine.eval import reload_default_weights
    reload_default_weights()


def _restore_params(original: AIParams) -> None:
    """grid search 後に元の AIParams に戻す。"""
    _write_param_overrides(original)


def _load_decks() -> list[tuple[str, str, DeckList]]:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    out: list[tuple[str, str, DeckList]] = []
    for p in sorted((ROOT / "decks").glob("cardrush_*.json")):
        if "analysis" in p.name:
            continue
        try:
            d = DeckList.from_json(p, repo)
        except Exception as e:
            print(f"  [WARN] {p.stem}: {e}")
            continue
        out.append((p.stem, d.name, d))
    return out


def _write_report(
    baseline_score: dict,
    baseline_winrates: dict,
    best_score: Optional[dict],
    best_params: Optional[AIParams],
    original_params: AIParams,
    tag_aggregate: dict,
    params_searched: list[str],
    best_winrates: Optional[dict],
    applied: bool,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"learn-{ts}.md"

    lines: list[str] = []
    lines.append(f"# AI Params Learning Report — {ts}")
    lines.append("")
    lines.append("## Baseline")
    lines.append(f"- accuracy: **{baseline_score['accuracy']:.3f}**")
    lines.append(f"- variance penalty: {baseline_score['variance_penalty']:.4f}")
    lines.append(f"- composite: {baseline_score['composite']:.3f}")
    lines.append("")

    lines.append("## Loss Tag Aggregate")
    lines.append(f"- total losses analyzed: {tag_aggregate.get('total_losses', 0)}")
    lines.append("- tag rates:")
    for tag, rate in sorted(tag_aggregate.get("tag_rates", {}).items(), key=lambda x: -x[1]):
        lines.append(f"  - `{tag}`: {rate:.3f}  ({tag_aggregate['tag_counts'][tag]} cases)")
    lines.append("")

    lines.append("## Params Searched")
    for p in params_searched:
        cur = getattr(original_params, p, None)
        lines.append(f"- `{p}` (current: {cur!r})")
    lines.append("")

    if best_score and best_params:
        lines.append("## Best Candidate (grid search)")
        lines.append(f"- accuracy: **{best_score['accuracy']:.3f}**  (Δ {best_score['accuracy'] - baseline_score['accuracy']:+.3f})")
        lines.append(f"- variance penalty: {best_score['variance_penalty']:.4f}")
        lines.append(f"- composite: {best_score['composite']:.3f}  (Δ {best_score['composite'] - baseline_score['composite']:+.3f})")
        lines.append("")
        lines.append("### Param diff")
        for p in params_searched:
            cur = getattr(original_params, p, None)
            new = getattr(best_params, p, None)
            mark = "→" if cur != new else "="
            lines.append(f"- `{p}`: {cur!r} {mark} {new!r}")
        lines.append("")
        if best_winrates:
            lines.append("### Winrate before/after (per deck)")
            lines.append("| deck | baseline | after | Δ |")
            lines.append("|---|---|---|---|")
            for slug in sorted(baseline_winrates.keys()):
                b = baseline_winrates[slug]
                a = best_winrates.get(slug, 0.0)
                lines.append(f"| {slug} | {b:.2%} | {a:.2%} | {a - b:+.2%} |")
            lines.append("")
        lines.append(f"### Applied: {'YES' if applied else 'NO (diagnostic only — re-run with --apply)'}")
    else:
        lines.append("## (No grid search performed — diagnostic mode)")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-games", type=int, default=10, help="各マッチアップ試合数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-grid", action="store_true", help="診断のみ (grid 探索しない)")
    ap.add_argument("--target-tag", type=str, default=None,
                    help="特定タグだけにフォーカス (省略時は上位 3 タグ)")
    ap.add_argument("--apply", action="store_true", help="採用して db/ai_params.json に保存")
    ap.add_argument("--max-grid-combinations", type=int, default=48,
                    help="grid 探索の最大組み合わせ数 (= 計算時間制限)")
    ap.add_argument(
        "--ai",
        choices=["greedy", "eval_greedy", "mcts"],
        default="greedy",
        help="対戦 AI (default: greedy)。 mcts は ISMCTS+PUCT、 計算コスト高め",
    )
    args = ap.parse_args()

    from engine.ai import EvalGreedyAI, GreedyAI, MCTSAI
    _AI_FACTORIES = {
        "greedy": GreedyAI,
        "eval_greedy": EvalGreedyAI,
        "mcts": MCTSAI,
    }
    ai_factory = _AI_FACTORIES[args.ai]
    print(f"AI: {args.ai}")

    # tier_truth ロード
    if not TIER_TRUTH_PATH.exists():
        print(f"ERROR: {TIER_TRUTH_PATH} not found")
        return 1
    tier_truth = json.loads(TIER_TRUTH_PATH.read_text(encoding="utf-8"))

    # デッキ一覧
    decks = _load_decks()
    if len(decks) < 2:
        print("ERROR: 学習にはデッキが 2 つ以上必要")
        return 1
    print(f"対象 {len(decks)} デッキ × {len(decks)} = {len(decks) ** 2} cells, n_games={args.n_games}")

    # 現 AIParams
    original_params = AIParams.load()
    print(f"current ai_params: activate_main_min_payoff_global={original_params.activate_main_min_payoff_global}")

    # ----- ステップ 1: baseline -----
    print("\n=== Baseline ===")
    t0 = time.time()
    baseline_matrix = _run_matrix(
        decks, args.n_games, args.seed, record_replays=True,
        verbose=True, ai_factory=ai_factory,
    )
    print(f"  elapsed {time.time() - t0:.1f}s")
    baseline_score = _score(baseline_matrix, tier_truth)
    print(f"  accuracy: {baseline_score['accuracy']:.3f}")
    print(f"  variance penalty: {baseline_score['variance_penalty']:.4f}")
    print(f"  composite: {baseline_score['composite']:.3f}")

    # ----- ステップ 2: 敗因タグ集計 -----
    print("\n=== Loss Tag Analysis ===")
    replays = list_replays()
    print(f"  {len(replays)} replays found")
    tag_aggregate = aggregate_loss_tags(replays)
    print(f"  total losses: {tag_aggregate.get('total_losses', 0)}")
    for tag, count in sorted(tag_aggregate.get("tag_counts", {}).items(), key=lambda x: -x[1]):
        rate = tag_aggregate["tag_rates"][tag]
        print(f"    {tag}: {count} cases ({rate:.2%})")

    # ----- ステップ 3: 学習対象 params -----
    if args.target_tag:
        params_searched = TAG_TO_PARAMS.get(args.target_tag, [])
        if not params_searched:
            print(f"ERROR: unknown tag '{args.target_tag}'")
            return 1
    else:
        params_searched = params_to_tune(tag_aggregate, top_k=3)
    print(f"\nparams to tune: {params_searched}")

    if args.no_grid or not params_searched:
        print("\n=== Diagnostic only (no grid search) ===")
        report_path = _write_report(
            baseline_score, baseline_matrix["avg_winrates"],
            None, None, original_params,
            tag_aggregate, params_searched, None, applied=False,
        )
        print(f"report: {report_path}")
        return 0

    # ----- ステップ 4: grid search -----
    print(f"\n=== Grid Search ({len(params_searched)} params) ===")
    candidate_lists = []
    for p in params_searched:
        cur = getattr(original_params, p, None)
        cand = _candidates_for_param(p, cur)
        candidate_lists.append([(p, v) for v in cand])
    combinations = list(itertools.product(*candidate_lists))
    if len(combinations) > args.max_grid_combinations:
        print(f"  combinations {len(combinations)} > {args.max_grid_combinations}, truncating")
        combinations = combinations[: args.max_grid_combinations]
    else:
        print(f"  {len(combinations)} combinations")

    best_score = baseline_score
    best_params = original_params
    best_winrates = baseline_matrix["avg_winrates"]
    for i, combo in enumerate(combinations, 1):
        param_dict = dict(combo)
        # baseline 組み合わせはスキップ
        if all(getattr(original_params, k) == v for k, v in param_dict.items()):
            continue
        candidate = _apply_param_values(original_params, param_dict)
        _write_param_overrides(candidate)
        try:
            matrix = _run_matrix(decks, args.n_games, args.seed,
                                 record_replays=False, ai_factory=ai_factory)
            score = _score(matrix, tier_truth)
        finally:
            _restore_params(original_params)
        marker = ""
        if score["composite"] > best_score["composite"]:
            best_score = score
            best_params = candidate
            best_winrates = matrix["avg_winrates"]
            marker = "  *NEW BEST*"
        print(f"  [{i}/{len(combinations)}] {param_dict}  acc={score['accuracy']:.3f}  comp={score['composite']:.3f}{marker}")

    # ----- ステップ 5: 採用 or 提案 -----
    improved = best_score["composite"] > baseline_score["composite"]
    print("\n=== Result ===")
    print(f"  baseline composite: {baseline_score['composite']:.3f}")
    print(f"  best     composite: {best_score['composite']:.3f}")
    print(f"  improvement: {'YES' if improved else 'NO'}")

    applied = False
    if improved and args.apply:
        best_params.save(history_note=f"learned: {','.join(params_searched)}")
        from engine.eval import reload_default_weights
        reload_default_weights()
        applied = True
        print(f"\n  applied to {AI_PARAMS_PATH}")
    elif improved:
        print("\n  (re-run with --apply to commit)")

    report_path = _write_report(
        baseline_score, baseline_matrix["avg_winrates"],
        best_score if improved else None,
        best_params if improved else None,
        original_params,
        tag_aggregate, params_searched,
        best_winrates if improved else None,
        applied=applied,
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
