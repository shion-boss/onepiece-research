"""rollout policy variant の arena 結果を db/eiv1/rollout_policy_results.json に merge — 2026-07-25。
dashboard panel⑬ が この file を読んで各 policy を表示する。
  使い方: record_rollout_result.py <tag> <label> <arena_win> <arena_n> <corpus_n>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "db" / "eiv1" / "rollout_policy_results.json"


def main() -> None:
    tag, label, win, an, cn = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    data = {}
    if RES.exists():
        try:
            data = json.loads(RES.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    rec = data.get(tag) or {}
    rec["label"] = label
    rec["arena_vs_outcome"] = round(win, 4)
    rec["arena_n"] = an
    trend = rec.get("trend") or []
    trend.append([cn, round(win, 4)])
    rec["trend"] = trend
    data[tag] = rec
    RES.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"recorded {tag}: win={win:.4f} N={an} corpus={cn}")


if __name__ == "__main__":
    main()
