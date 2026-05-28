#!/usr/bin/env python3
"""per-round bonus 学習 diff report (= 2026-05-28、 周回毎 変化量 可視化)。

multi-round bonus 学習 で 各 round の:
- touched ratio (= 学習対象 entries 数 / 総 entries 数 = 学習信号 量)
- bonus delta 分布 (= median / p95 / max of |bonus_new - bonus_old|)
- top movers (= 大きく動いた entries)
- matrix shift (= deck 別 勝率 before → after)
- round-over-round convergence (= 前 round と 比較で 収束方向 か)

を 集計 + stdout + JSON 出力。

# 使い方

```bash
# round N 単独 (= round N の 学習前後 diff)
.venv/bin/python scripts/report_bonus_round_diff.py \
    --round-dir db/bonus_rounds/round_1

# round N vs round N-1 (= 周回間 比較)
.venv/bin/python scripts/report_bonus_round_diff.py \
    --round-dir db/bonus_rounds/round_2 \
    --prev-round db/bonus_rounds/round_1
```

# round dir 構造 (= snapshot 学習前 状態)

```
db/bonus_rounds/round_N/
├── cardrush_*.target_v1.json     (= 学習前 spec copy)
├── tcgportal_*.target_v1.json
├── target_generic.json
├── matrix_before.json            (= 学習前 matrix)
├── matrix_after.json             (= 学習後 matrix、 step F で 生成)
└── report.json                   (= この script の 出力)
```

学習後 spec は decks/*.target_v1.json (= live state)。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_targets(spec_path: Path):
    """spec 1 ファイル の (entry_idx, target_idx, target_dict) を yield。"""
    spec = _load_spec(spec_path)
    for ei, entry in enumerate(spec.get("entries", [])):
        for ti, tgt in enumerate(entry.get("targets", [])):
            yield ei, ti, tgt


def _bonus_diff(round_dir: Path) -> dict:
    """round_dir の 学習前 spec と live spec を比較、 bonus delta を集計。"""
    deck_files = sorted(round_dir.glob("*.target_v1.json"))
    if not deck_files:
        return {"error": f"no spec files in {round_dir}"}
    total = 0
    deltas: list[float] = []
    big_movers: list[dict] = []  # {deck_slug, entry_idx, target_idx, before, after, delta, description}

    for prev_path in deck_files:
        slug = prev_path.name.replace(".target_v1.json", "")
        live_path = REPO_ROOT / "decks" / f"{slug}.target_v1.json"
        if not live_path.exists():
            continue
        prev_spec = _load_spec(prev_path)
        live_spec = _load_spec(live_path)
        # (entry_idx, target_idx) で 1 対 1 mapping (= diversify は append only なので 順序保持)
        for ei, entry_live in enumerate(live_spec.get("entries", [])):
            entry_prev = (prev_spec.get("entries") or [{}])[ei] if ei < len(prev_spec.get("entries", [])) else {}
            targets_prev = entry_prev.get("targets", [])
            for ti, tgt_live in enumerate(entry_live.get("targets", [])):
                total += 1
                if ti >= len(targets_prev):
                    continue  # 新規 entries (= 学習中 に diversify 等)
                tgt_prev = targets_prev[ti]
                b_prev = int(tgt_prev.get("bonus", 0))
                b_live = int(tgt_live.get("bonus", 0))
                d = b_live - b_prev
                if d != 0:
                    deltas.append(d)
                    if abs(d) >= 50:  # big mover threshold
                        big_movers.append({
                            "deck_slug": slug,
                            "entry_idx": ei,
                            "target_idx": ti,
                            "before": b_prev,
                            "after": b_live,
                            "delta": d,
                            "description": (tgt_live.get("description") or "")[:60],
                            "priority": tgt_live.get("priority"),
                        })

    abs_deltas = [abs(d) for d in deltas]
    big_movers.sort(key=lambda x: -abs(x["delta"]))
    return {
        "total_targets": total,
        "touched": len(deltas),
        "touched_ratio": (len(deltas) / total) if total else 0.0,
        "delta_median": statistics.median(abs_deltas) if abs_deltas else 0,
        "delta_p95": (sorted(abs_deltas)[int(len(abs_deltas) * 0.95)] if len(abs_deltas) >= 20 else max(abs_deltas, default=0)),
        "delta_max": max(abs_deltas, default=0),
        "n_positive": sum(1 for d in deltas if d > 0),
        "n_negative": sum(1 for d in deltas if d < 0),
        "top_movers": big_movers[:20],
    }


def _matrix_shift(round_dir: Path) -> dict:
    """matrix_before.json vs matrix_after.json で deck 別 勝率 shift を計算。"""
    before_path = round_dir / "matrix_before.json"
    after_path = round_dir / "matrix_after.json"
    if not before_path.exists() or not after_path.exists():
        return {"error": f"matrix snapshot 不在 (before={before_path.exists()}, after={after_path.exists()})"}
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    # matrix structure: {"decks": [{"slug": ..., "winrates": [...]}, ...]} or row-based
    # 互換のため両 format 対応
    def _deck_avg_winrate(matrix: dict) -> dict[str, float]:
        result = {}
        decks = matrix.get("decks") or matrix.get("rows") or []
        for d in decks:
            slug = d.get("slug") or d.get("deck_slug") or d.get("name")
            wrs = d.get("winrates") or d.get("rates") or d.get("cells") or []
            # cells may be list of dicts or floats
            numeric_wrs = []
            for w in wrs:
                if isinstance(w, dict):
                    v = w.get("winrate") or w.get("rate")
                    if v is not None:
                        numeric_wrs.append(float(v))
                elif isinstance(w, (int, float)):
                    numeric_wrs.append(float(w))
            if slug and numeric_wrs:
                result[slug] = sum(numeric_wrs) / len(numeric_wrs)
        return result

    avg_before = _deck_avg_winrate(before)
    avg_after = _deck_avg_winrate(after)
    shifts = []
    for slug in sorted(set(avg_before) | set(avg_after)):
        b = avg_before.get(slug)
        a = avg_after.get(slug)
        if b is None or a is None:
            continue
        shifts.append({
            "deck_slug": slug,
            "before_winrate": round(b, 3),
            "after_winrate": round(a, 3),
            "shift_pt": round((a - b) * 100, 2),
        })
    shifts.sort(key=lambda x: -x["shift_pt"])
    return {
        "n_decks": len(shifts),
        "avg_shift_pt": round(statistics.mean([s["shift_pt"] for s in shifts]), 2) if shifts else 0,
        "max_improvement_pt": shifts[0]["shift_pt"] if shifts else 0,
        "max_regression_pt": shifts[-1]["shift_pt"] if shifts else 0,
        "per_deck": shifts,
    }


def _round_over_round(curr: dict, prev_report: dict) -> dict:
    """前 round の report と 比較、 収束指標 を 算出。"""
    out: dict = {}
    if prev_report is None:
        return out
    pb = prev_report.get("bonus_diff", {})
    cb = curr.get("bonus_diff", {})
    out["delta_median_change"] = (cb.get("delta_median", 0) - pb.get("delta_median", 0))
    out["touched_ratio_change"] = (cb.get("touched_ratio", 0) - pb.get("touched_ratio", 0))
    pm = {m["deck_slug"]: m["delta"] for m in pb.get("top_movers", [])}
    cm = {m["deck_slug"]: m["delta"] for m in cb.get("top_movers", [])}
    oscillators = []
    for slug in set(pm) & set(cm):
        if pm[slug] * cm[slug] < 0:  # 符号 反転 = oscillation
            oscillators.append({"deck_slug": slug, "prev_delta": pm[slug], "curr_delta": cm[slug]})
    out["oscillators"] = oscillators
    # 収束 判定 (= heuristic)
    out["converging"] = (
        out["delta_median_change"] < 0
        and len(oscillators) < 5
        and abs(out["touched_ratio_change"]) < 0.05
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round-dir", required=True, help="db/bonus_rounds/round_N (= 学習前 snapshot)")
    ap.add_argument("--prev-round", default=None, help="db/bonus_rounds/round_N-1 (= 周回間 比較 用、 optional)")
    args = ap.parse_args()

    round_dir = Path(args.round_dir)
    if not round_dir.is_dir():
        print(f"ERROR: {round_dir} not found", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Bonus Round Report: {round_dir.name} ===\n")

    # 1. bonus delta 分析
    bdiff = _bonus_diff(round_dir)
    print(f"【bonus delta】")
    print(f"  total targets    : {bdiff['total_targets']}")
    print(f"  touched          : {bdiff['touched']} ({bdiff['touched_ratio']*100:.1f}%)")
    print(f"  delta median     : {bdiff['delta_median']:.0f}")
    print(f"  delta p95        : {bdiff['delta_p95']:.0f}")
    print(f"  delta max        : {bdiff['delta_max']:.0f}")
    print(f"  +/-              : +{bdiff['n_positive']} / -{bdiff['n_negative']}")
    if bdiff["top_movers"]:
        print(f"\n  top 10 movers (|delta| >= 50):")
        for m in bdiff["top_movers"][:10]:
            sign = "+" if m["delta"] > 0 else ""
            print(f"    {m['deck_slug']}#{m['entry_idx']}.{m['target_idx']}: "
                  f"{m['before']} → {m['after']} ({sign}{m['delta']}) "
                  f"[{m['description']}]")

    # 2. matrix shift
    print(f"\n【matrix shift】")
    mshift = _matrix_shift(round_dir)
    if "error" in mshift:
        print(f"  {mshift['error']}")
    else:
        print(f"  decks            : {mshift['n_decks']}")
        print(f"  avg shift        : {mshift['avg_shift_pt']:+.1f} pt")
        print(f"  best improvement : {mshift['max_improvement_pt']:+.1f} pt")
        print(f"  worst regression : {mshift['max_regression_pt']:+.1f} pt")
        print(f"\n  per-deck (sorted by shift desc):")
        for s in mshift["per_deck"]:
            mark = "↑" if s["shift_pt"] >= 5 else ("↓" if s["shift_pt"] <= -5 else " ")
            print(f"    {mark} {s['deck_slug']}: {s['before_winrate']*100:.1f}% → {s['after_winrate']*100:.1f}% ({s['shift_pt']:+.1f} pt)")

    # 3. round-over-round
    rover = {}
    if args.prev_round:
        prev_report_path = Path(args.prev_round) / "report.json"
        if prev_report_path.exists():
            prev_report = json.loads(prev_report_path.read_text(encoding="utf-8"))
            curr = {"bonus_diff": bdiff, "matrix_shift": mshift}
            rover = _round_over_round(curr, prev_report)
            print(f"\n【round-over-round (vs {Path(args.prev_round).name})】")
            print(f"  delta median change : {rover['delta_median_change']:+.0f}")
            print(f"  touched ratio change: {rover['touched_ratio_change']*100:+.1f} pt")
            print(f"  oscillators         : {len(rover['oscillators'])}")
            print(f"  converging          : {rover['converging']}")
        else:
            print(f"\n  (prev round report not found: {prev_report_path})")

    # 4. JSON 出力
    report = {
        "round_dir": str(round_dir),
        "bonus_diff": bdiff,
        "matrix_shift": mshift,
        "round_over_round": rover,
    }
    out_path = round_dir / "report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n--> {out_path}")


if __name__ == "__main__":
    main()
