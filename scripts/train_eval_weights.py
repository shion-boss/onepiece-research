#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 2 / Step 2C: outcome regression で BoardEvalWeights を学習。

入力: db/self_play_snapshots.jsonl (= collect_self_play_data.py の出力)
出力: db/ai_params.suggested.json (= 学習後の重み案、 自動 apply はしない)
      + diff レポート (stdout)

モデル:
  - sklearn.linear_model.Ridge(alpha=1.0): 連続 value (= +1/0/-1) の線形回帰
  - sklearn.linear_model.LogisticRegression: 2 クラス (= win/lose、 draw 除外) でも比較

検証: holdout 80/20、 「予測 score の符号 = 実 outcome の符号」 一致率を測定。
baseline 60% → 目標 75%+。

Usage:
  .venv/bin/python scripts/train_eval_weights.py
  .venv/bin/python scripts/train_eval_weights.py --input /tmp/test.jsonl --eval-only
  .venv/bin/python scripts/train_eval_weights.py --filter-early-mid-only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.eval import BoardEvalWeights  # noqa: E402


# feature_name → BoardEvalWeights field name のマッピング
# (= compute_breakdown のキー名と W_ field の対応)
FEATURE_TO_WEIGHT_FIELD = {
    "life": "W_LIFE",
    "field_count": "W_FIELD_COUNT",
    "field_power": "W_FIELD_POWER",
    "hand": "W_HAND",
    "don": "W_DON",
    "blocker": "W_BLOCKER",
    "attached_don": "W_ATTACHED_DON",
    "active_chara": "W_ACTIVE_CHARA",
    "lethal": "W_LETHAL",
    "next_turn_lethal": "W_OPP_NEXT_LETHAL",
    "deck_finisher": "W_DECK_FINISHER",
    "life_trigger": "W_LIFE_TRIGGER",
    "chara_quality": "W_CHARA_QUALITY",
    "hand_quality": "W_HAND_QUALITY",
    "opp_hand_threat": "W_OPP_HAND_THREAT",
    # Step 2-pre 計画書 10
    "is_first_player": "W_IS_FIRST_PLAYER",
    "stage_count": "W_STAGE_COUNT",
    "stage_value": "W_STAGE_VALUE",
    "trash_count": "W_TRASH_COUNT",
    "trash_archetype_match": "W_TRASH_ARCHETYPE_MATCH",
    "rush_count": "W_RUSH_COUNT",
    "double_attack_count": "W_DOUBLE_ATTACK_COUNT",
    "static_cost_reduction_total": "W_STATIC_COST_REDUCTION_TOTAL",
    "playable_cost_match": "W_PLAYABLE_COST_MATCH",
    "synergy_count": "W_SYNERGY_COUNT",
    # Step 2-pre 即追加 9
    "is_my_turn": "W_IS_MY_TURN",
    "turn_number_normalized": "W_TURN_NUMBER_NORMALIZED",
    "dead_card_in_hand": "W_DEAD_CARD_IN_HAND",
    "active_blocker_count": "W_OPP_ACTIVE_BLOCKER_COUNT",
    "removal_threat_count": "W_REMOVAL_THREAT_COUNT",
    "self_counter_in_hand_total": "W_SELF_COUNTER_IN_HAND_TOTAL",
    "finisher_in_hand_count": "W_FINISHER_IN_HAND_COUNT",
    "keyword_taunt_count": "W_KEYWORD_TAUNT_COUNT",
    "ko_immune_count": "W_KO_IMMUNE_COUNT",
    # state 拡張 5
    "cards_drawn_total": "W_CARDS_DRAWN_TOTAL",
    "cards_played_total": "W_CARDS_PLAYED_TOTAL",
    "dons_used_total": "W_DONS_USED_TOTAL",
    "tempo_lost_total": "W_TEMPO_LOST_TOTAL",
    "known_finisher_count_in_hand": "W_OPP_KNOWN_FINISHER_COUNT",
    # Step 2A 4
    "don_reserve": "W_DON_RESERVE",
    "field_exposure": "W_FIELD_EXPOSURE",
    "hand_log": "W_HAND_LOG",
    "lethal_risk_diff": "W_LETHAL_RISK_DIFF",
    # Iter2 interaction 30
    "int_low_life_low_hand": "W_INT_LOW_LIFE_LOW_HAND",
    "int_low_life_no_blocker": "W_INT_LOW_LIFE_NO_BLOCKER",
    "int_opp_lethal_no_counter": "W_INT_OPP_LETHAL_NO_COUNTER",
    "int_defensive_collapse": "W_INT_DEFENSIVE_COLLAPSE",
    "int_opp_da_pressure": "W_INT_OPP_DA_PRESSURE",
    "int_lethal_setup_ready": "W_INT_LETHAL_SETUP_READY",
    "int_aggressive_window_open": "W_INT_AGGRESSIVE_WINDOW_OPEN",
    "int_burst_threshold": "W_INT_BURST_THRESHOLD",
    "int_removal_window": "W_INT_REMOVAL_WINDOW",
    "int_don_advantage_open": "W_INT_DON_ADVANTAGE_OPEN",
    "int_on_curve": "W_INT_ON_CURVE",
    "int_tempo_lost_critical": "W_INT_TEMPO_LOST_CRITICAL",
    "int_ramp_paying_off": "W_INT_RAMP_PAYING_OFF",
    "int_mana_starved": "W_INT_MANA_STARVED",
    "int_synergy_threshold_3": "W_INT_SYNERGY_THRESHOLD_3",
    "int_trash_archetype_5": "W_INT_TRASH_ARCHETYPE_5",
    "int_stage_with_synergy": "W_INT_STAGE_WITH_SYNERGY",
    "int_ramp_finisher_combo": "W_INT_RAMP_FINISHER_COMBO",
    "int_opp_hidden_threat_high": "W_INT_OPP_HIDDEN_THREAT_HIGH",
    "int_self_hand_quality_high": "W_INT_SELF_HAND_QUALITY_HIGH",
    "int_opp_low_resource": "W_INT_OPP_LOW_RESOURCE",
    "int_early_game_strong": "W_INT_EARLY_GAME_STRONG",
    "int_mid_game_pressure": "W_INT_MID_GAME_PRESSURE",
    "int_late_game_solver": "W_INT_LATE_GAME_SOLVER",
    "int_ko_immune_finisher": "W_INT_KO_IMMUNE_FINISHER",
    "int_blocker_with_taunt": "W_INT_BLOCKER_WITH_TAUNT",
    "int_first_player_early_adv": "W_INT_FIRST_PLAYER_EARLY_ADV",
    "int_second_player_late_swing": "W_INT_SECOND_PLAYER_LATE_SWING",
    "int_exposed_finisher": "W_INT_EXPOSED_FINISHER",
    "int_draw_advantage": "W_INT_DRAW_ADVANTAGE",
}

# json key 名 (= ai_params.json で使う lowercase)
WEIGHT_FIELD_TO_JSON_KEY = {
    field: field.lower() for field in FEATURE_TO_WEIGHT_FIELD.values()
}


def load_snapshots(path: Path, filter_early_mid_only: bool = False) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """JSONL を numpy array にロード。

    Returns: X (N, D), y (N,), feature_names (list of D feature key)
    """
    feature_names: list[str] = list(FEATURE_TO_WEIGHT_FIELD.keys())
    X_rows: list[list[float]] = []
    y_rows: list[float] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            if filter_early_mid_only and snap.get("turn", 0) > 5:
                continue
            features = snap.get("features", {})
            row = [float(features.get(name, 0.0)) for name in feature_names]
            target = snap.get("final_winner", 0)
            X_rows.append(row)
            y_rows.append(float(target))

    X = np.array(X_rows, dtype=np.float64)
    y = np.array(y_rows, dtype=np.float64)
    return X, y, feature_names


def train_ridge(X: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> tuple[Ridge, dict]:
    """Ridge 回帰 + 80/20 holdout で sign 一致率測定。"""
    n = len(X)
    split = int(n * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = Ridge(alpha=alpha)
    model.fit(X_train, y_train)
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    sign_acc_train = float(np.mean(np.sign(y_pred_train) == np.sign(y_train)))
    sign_acc_test = float(np.mean(np.sign(y_pred_test) == np.sign(y_test)))

    return model, {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "sign_acc_train": sign_acc_train,
        "sign_acc_test": sign_acc_test,
        "intercept": float(model.intercept_),
    }


def train_logistic(X: np.ndarray, y: np.ndarray, C: float = 1.0) -> tuple[Optional[LogisticRegression], dict]:
    """LogisticRegression (= win/lose 2クラス分類)。 draw (= y==0) は除外。"""
    mask = y != 0
    X = X[mask]
    y_bin = (y[mask] > 0).astype(int)
    if len(set(y_bin)) < 2:
        return None, {"error": "single class only"}

    n = len(X)
    split = int(n * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y_bin[:split], y_bin[split:]

    model = LogisticRegression(C=C, max_iter=1000)
    model.fit(X_train, y_train)
    acc_train = float(accuracy_score(y_train, model.predict(X_train)))
    acc_test = float(accuracy_score(y_test, model.predict(X_test)))

    return model, {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "acc_train": acc_train,
        "acc_test": acc_test,
        "intercept": float(model.intercept_[0]),
    }


def make_suggested_params(
    feature_names: list[str],
    coefs: np.ndarray,
    scale: float = 1000.0,
) -> dict:
    """Ridge の coef を BoardEvalWeights 形式の dict に変換。

    Ridge の coef は -1〜+1 オーダーなので、 既存重み (= 100〜5000) と桁を合わせるため
    scale 倍して int 化。 W_GAME_OVER は学習対象外で固定。
    """
    suggested: dict = {}
    for name, coef in zip(feature_names, coefs):
        weight_field = FEATURE_TO_WEIGHT_FIELD[name]
        json_key = weight_field.lower()
        suggested[json_key] = int(round(coef * scale))
    return suggested


def diff_against_current(suggested: dict) -> str:
    """現 ai_params.json との diff レポート。"""
    current_path = ROOT / "db" / "ai_params.json"
    if not current_path.exists():
        return "  (ai_params.json not found, skip diff)"
    cur = json.loads(current_path.read_text(encoding="utf-8")).get("params", {})
    lines = []
    for key, new_val in suggested.items():
        old_val = cur.get(key, 0)
        if old_val != new_val:
            lines.append(f"    {key}: {old_val} → {new_val}  (Δ {new_val - old_val:+d})")
    if not lines:
        return "  (no change vs current)"
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input",
        type=Path,
        default=ROOT / "db" / "self_play_snapshots.jsonl",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "db" / "ai_params.suggested.json",
    )
    ap.add_argument("--alpha", type=float, default=1.0, help="Ridge alpha (= L2 強度)")
    ap.add_argument("--scale", type=float, default=1000.0, help="coef → weight 倍率")
    ap.add_argument(
        "--filter-early-mid-only",
        action="store_true",
        help="turn <= 5 の snapshot のみで学習 (= late game 除外)",
    )
    ap.add_argument(
        "--eval-only",
        action="store_true",
        help="精度測定のみ、 suggested.json は出力しない",
    )
    args = ap.parse_args()

    print(f"loading snapshots from {args.input}...")
    X, y, feature_names = load_snapshots(args.input, args.filter_early_mid_only)
    print(f"  N = {len(X)}, D = {X.shape[1] if len(X) else 0}")
    print(f"  outcome distribution: win={int((y > 0).sum())}, "
          f"lose={int((y < 0).sum())}, draw={int((y == 0).sum())}")

    if len(X) < 100:
        print("  insufficient data (< 100), skipping training")
        return

    print(f"\n[Ridge alpha={args.alpha}]")
    ridge, ridge_stats = train_ridge(X, y, alpha=args.alpha)
    print(f"  train sign acc: {ridge_stats['sign_acc_train']:.3f}")
    print(f"  test  sign acc: {ridge_stats['sign_acc_test']:.3f}")
    print(f"  intercept: {ridge_stats['intercept']:.4f}")

    print(f"\n[LogisticRegression]")
    logreg, log_stats = train_logistic(X, y)
    if logreg is not None:
        print(f"  train acc: {log_stats['acc_train']:.3f}")
        print(f"  test  acc: {log_stats['acc_test']:.3f}")
    else:
        print(f"  skipped: {log_stats.get('error')}")

    if args.eval_only:
        print("\n--eval-only mode, no output")
        return

    print(f"\n[suggested params (Ridge × scale={args.scale})]")
    suggested = make_suggested_params(feature_names, ridge.coef_, scale=args.scale)
    print(diff_against_current(suggested))

    out_data = {
        "version": "1",
        "saved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "note": (
            f"trained from {args.input.name} (N={len(X)}), "
            f"Ridge alpha={args.alpha}, scale={args.scale}, "
            f"test_sign_acc={ridge_stats['sign_acc_test']:.3f}"
        ),
        "params": suggested,
        "training_stats": {
            "ridge": ridge_stats,
            "logistic": log_stats,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote: {args.output}")


if __name__ == "__main__":
    main()
