# -*- coding: utf-8 -*-
"""per-deck AI config tuner (= 2026-06-21、 persist→consume の実体)。

任意デッキ (= ユーザー作成含む) に対し self-play mirror A/B で「このデッキで勝つ lever 設定」
を選び、 db/deck_ai_config_<slug>.json に persist する。 ExploitBeam が __init__ で消費。
= value-defense 等の deck-specific レバーを「A/B 勝ちしたデッキだけ ON」 で配備 (= 回帰ゼロ)。

robust gate: [[project_rollout_gbm_value]] の教訓「single-seed promote は 2nd-seed audit 必須」
に従い 2 seed の平均で判定 (= lucky-seed promote を防ぐ)。 [[feedback_ab_statistical_power]]。

usage:
  # 1 デッキ tune (= value_defense A/B → config 書込):
  PYTHONPATH=. .venv/bin/python scripts/tune_deck.py cardrush_1454 --n-games 60 --workers 12
  # dry-run (測定のみ、 書込まない):
  PYTHONPATH=. .venv/bin/python scripts/tune_deck.py cardrush_1454 --dry-run
  # 複数デッキ:
  PYTHONPATH=. .venv/bin/python scripts/tune_deck.py --decks meta --n-games 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
REPO = Path(__file__).resolve().parent.parent

from scripts.eval_value_defense import run_parallel as vd_ab


def _cfg_path(slug: str) -> Path:
    return REPO / "db" / f"deck_ai_config_{slug}.json"


def _load_cfg(slug: str) -> dict:
    p = _cfg_path(slug)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def tune_value_defense(slug, n_games, workers, seeds, threshold):
    """value_defense ON vs OFF mirror A/B を 2 seed で測り、 平均 >= threshold で ON。"""
    wrs = []
    for sd in seeds:
        print(f"--- value_defense A/B seed={sd} ---", flush=True)
        wrs.append(vd_ab(slug, n_games, sd, workers))
    avg = sum(wrs) / len(wrs)
    return (avg >= threshold), avg, wrs


def tune_one(slug, n_games, workers, seeds, threshold, dry_run,
             deck_spec=None, cfg_path=None):
    """slug (or deck_spec=path) を A/B → config を cfg_path (既定 slug-keyed) に書く。

    deck_spec: A/B に渡す deck (= slug or decks 外の json path、 user deck 用)。
    cfg_path: config 書込先 Path (= 既定 slug-keyed、 user deck は hash-keyed を渡す)。
    """
    deck_spec = deck_spec or slug
    cfg_path = cfg_path or _cfg_path(slug)
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    print(f"\n========== tuning {slug} (seeds={seeds}, N={n_games} each) ==========")
    deploy, avg, wrs = tune_value_defense(deck_spec, n_games, workers, seeds, threshold)
    tag = "ON" if deploy else "OFF"
    print(f"\n>>> {slug}: value_defense per-seed={['%.1f%%' % (w*100) for w in wrs]} "
          f"avg={avg:.1%} → {tag} (thr={threshold:.0%})")
    cfg["value_defense"] = bool(deploy)
    cfg.setdefault("ab", {})["value_defense"] = {
        "avg": round(avg, 3), "seeds": {s: round(w, 3) for s, w in zip(seeds, wrs)},
        "n_each": n_games,
    }
    cfg["tuned_at"] = time.strftime("%Y-%m-%d")
    if dry_run:
        print(f"[dry-run] would write {cfg_path.name}: {json.dumps(cfg, ensure_ascii=False)}")
    else:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[wrote] {cfg_path}")
    return cfg


def _select_decks(spec: str) -> list[str]:
    if spec == "meta":
        return json.loads((REPO / "db" / "meta_decks.json").read_text())["meta_deck_slugs"]
    if spec in ("no-pkl", "all"):
        # user-deck 代表 = per-deck GBM pkl の無い decks/cardrush_*.json (= agnostic/board_eval 経路)。
        out = []
        for p in sorted((REPO / "decks").glob("cardrush_*.json")):
            s = p.stem
            if any(x in s for x in ("analysis", "target_v1", "locked")):
                continue
            if spec == "no-pkl" and (REPO / "db" / f"value_gbm_{s}.pkl").exists():
                continue
            out.append(s)
        return out
    return [s.strip() for s in spec.split(",") if s.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default=None)
    ap.add_argument("--decks", default=None, help="'meta' か カンマ区切り (slug 引数の代替)")
    ap.add_argument("--n-games", type=int, default=60, help="A/B 1 seed あたりの試合数")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seeds", default="100,500", help="2nd-seed audit 用の seed list")
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="2 seed 平均がこれ以上で ON 配備 (= 回帰防止 gate)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-existing", action="store_true",
                    help="既に config がある deck を skip (= batch の checkpoint 再開)")
    ap.add_argument("--deck-json", default=None,
                    help="任意 path の recipe を tune (= user deck、 decks/ 外)。 --hash 必須")
    ap.add_argument("--hash", dest="deck_hash", default=None,
                    help="--deck-json 用: config を deck_ai_config_h<hash>.json に書く (= 内容 keyed)")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    # --- 単一 recipe を hash-keyed で tune (= auto-trigger / user deck 経路) ---
    if args.deck_json:
        from engine.deck_config import hash_config_path, recipe_hash
        h = args.deck_hash
        if not h:
            rec = json.loads(Path(args.deck_json).read_text(encoding="utf-8"))
            h = recipe_hash(rec.get("leader", ""), rec.get("main", []))
        cfg_path = hash_config_path(h)
        if args.skip_existing and cfg_path.exists():
            print(f"[skip] hash {h} は config 済")
            return
        slug = Path(args.deck_json).stem
        tune_one(slug, args.n_games, args.workers, seeds, args.threshold,
                 args.dry_run, deck_spec=args.deck_json, cfg_path=cfg_path)
        return

    if args.decks:
        slugs = _select_decks(args.decks)
    elif args.slug:
        slugs = [args.slug]
    else:
        ap.error("slug か --decks か --deck-json を指定")

    summary = []
    for slug in slugs:
        if args.skip_existing and _cfg_path(slug).exists():
            cfg = _load_cfg(slug)
            print(f"[skip] {slug} は config 済 (value_defense={cfg.get('value_defense')})")
            summary.append((slug, cfg.get("value_defense"),
                            cfg.get("ab", {}).get("value_defense", {}).get("avg", 0.0)))
            continue
        cfg = tune_one(slug, args.n_games, args.workers, seeds, args.threshold, args.dry_run)
        summary.append((slug, cfg.get("value_defense"), cfg["ab"]["value_defense"]["avg"]))
    print("\n========== SUMMARY ==========")
    for slug, vd, avg in summary:
        print(f"  {slug}: value_defense={'ON' if vd else 'off'}  (avg {avg:.1%})")


if __name__ == "__main__":
    main()
