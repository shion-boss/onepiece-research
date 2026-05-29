#!/usr/bin/env python3
"""online self-play spec learning (= 2026-05-30、 task #52)。

GoalDirectedAI 同士 で N game self-play、 各 game 終了 後 に loser/winner spec
micro-update → 次 game で 強化 spec 使用 → AlphaZero 系譜 の online RL。

## 使い方

```bash
# smoke (= 1 deck mirror で 100 game)
.venv/bin/python -u scripts/online_spec_learn.py \\
    --decks cardrush_1342 \\
    --mirror-only --n-games 100 \\
    --alpha 0.05

# 16 deck full matchup (= 16×16×50 game = 12,800 game)
.venv/bin/python -u scripts/online_spec_learn.py \\
    --decks all --n-games 50 --alpha 0.05 \\
    --output-dir db/spec_online/round_1
```

## 流れ

1. 各 deck の spec を load (= 現状 decks/<slug>.target_v1.json) → in-memory deep copy
2. game loop:
   - A vs B 試合 (= 一時 corpus dump で trajectory 取得)
   - winner_spec の 取った action: bonus *= (1+α)
   - loser_spec の 取った action: bonus *= (1-α)
   - in-memory で 直接 更新
3. 全 game 完了 後 spec を 保存
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DECKS = [
    "cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
    "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
    "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
    "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy",
    "tcgportal_op13_luffy",
]


def _load_initial_spec(deck_slug: str) -> dict:
    """decks/<slug>.target_v1.json を deep copy で 取得 (= in-memory 更新 用)。"""
    from engine.target_dsl import load_target_spec, clear_target_spec_cache
    clear_target_spec_cache()  # cache bug 回避
    spec = load_target_spec(deck_slug, version="v1")
    if spec is None:
        return {
            "deck_slug": deck_slug,
            "leader_id": None,
            "archetype": "midrange",
            "entries": [],
            "generated_by": "online_spec_learn.py",
            "notes": "initialized empty for online learning",
        }
    return copy.deepcopy(spec)


def _run_one_game(deck_a_slug: str, deck_b_slug: str,
                   spec_a: dict, spec_b: dict, seed: int):
    """1 game 実行、 (g, trajectory_a, trajectory_b) を 返す。"""
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    from engine.goal_directed_ai import GoalDirectedAI

    repo = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_a_slug}.json", repo)
    deck_b = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_b_slug}.json", repo)

    # ONEPIECE_PURE_LOOKUP=1 で online + pure lookup 統 合 (= 2026-05-30)
    import os
    _pure = os.environ.get("ONEPIECE_PURE_LOOKUP", "0") == "1"
    def factory_a(rng, deck_analysis=None):
        if _pure:
            os.environ["ONEPIECE_PURE_LOOKUP"] = "1"
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                               beam_width=2, max_depth=4,
                               target_spec=spec_a)
    def factory_b(rng, deck_analysis=None):
        if _pure:
            os.environ["ONEPIECE_PURE_LOOKUP"] = "1"
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                               beam_width=2, max_depth=4,
                               target_spec=spec_b)

    with tempfile.TemporaryDirectory() as tmp:
        rep = run_matchup(
            deck_a, deck_b, n_games=1, seed=seed,
            ai_factory_1=factory_a, ai_factory_2=factory_b,
            corpus_dump_dir=Path(tmp),
            enforce_rules=False,
        )
        g = rep.games[0]
        files = list(Path(tmp).glob("game_*.json"))
        if not files:
            return g, [], []
        game_dict = json.loads(files[0].read_text(encoding="utf-8"))

    # side index 決定 (= first_player から)
    fp = game_dict.get("first_player", 0)
    side_a_idx = 0 if fp == 0 else 1
    side_b_idx = 1 - side_a_idx

    from engine.online_update import extract_trajectory_from_corpus_game
    from scripts.build_spec_from_corpus import build_leader_maps
    leader_to_deck, _, _ = build_leader_maps()
    traj_a = extract_trajectory_from_corpus_game(game_dict, side_a_idx, leader_to_deck)
    traj_b = extract_trajectory_from_corpus_game(game_dict, side_b_idx, leader_to_deck)

    return g, traj_a, traj_b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="*", default=["cardrush_1342"])
    ap.add_argument("--n-games", type=int, default=100)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--clamp-min", type=int, default=100)
    ap.add_argument("--clamp-max", type=int, default=5000)
    ap.add_argument("--output-dir", type=Path,
                    default=REPO_ROOT / "db" / "spec_online" / "round_1")
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--mirror-only", action="store_true")
    args = ap.parse_args()

    if args.decks == ["all"]:
        args.decks = DEFAULT_DECKS
    args.output_dir.mkdir(parents=True, exist_ok=True)

    from engine.online_update import update_spec_from_trajectory, save_spec

    print(f"[online] loading specs for {len(args.decks)} decks ...", flush=True)
    specs = {slug: _load_initial_spec(slug) for slug in args.decks}
    n_entries_initial = {slug: len(s.get("entries", []))
                         for slug, s in specs.items()}

    if args.mirror_only:
        pairs = [(d, d) for d in args.decks]
    else:
        pairs = [(a, b) for a in args.decks for b in args.decks]

    t0 = time.time()
    total_games = len(pairs) * args.n_games
    completed = 0
    wins_a_total = 0
    total_actions_updated = 0
    print(f"[online] start: {len(pairs)} pairs × {args.n_games} games = {total_games:,} total",
          flush=True)
    print(f"[online] alpha={args.alpha} clamp=[{args.clamp_min},{args.clamp_max}]", flush=True)

    for pair_idx, (a, b) in enumerate(pairs):
        for game_idx in range(args.n_games):
            seed = args.seed_base + pair_idx * 10000 + game_idx
            # 2026-05-30 fix: first_player 交 互 化 (= 偶 数 game = A 先 攻、 奇 数 = B 先 攻)
            # run_matchup の n_games=1 だと first_player=0 固定 になる ため swap で 解消。
            swap_sides = (game_idx % 2 == 1)
            try:
                if swap_sides:
                    g, traj_b, traj_a = _run_one_game(b, a, specs[b], specs[a], seed)
                    # swap 後 g.winner = 「side A=元 B」 が 勝った か。 A/B 判定 反 転 必要
                    if g.winner == 0:
                        a_won, b_won = False, True
                    elif g.winner == 1:
                        a_won, b_won = True, False
                    else:
                        a_won, b_won = False, False
                else:
                    g, traj_a, traj_b = _run_one_game(a, b, specs[a], specs[b], seed)
                    a_won = (g.winner == 0)
                    b_won = (g.winner == 1)
            except Exception as e:
                print(f"  [{completed+1}/{total_games}] ERROR {a} vs {b} seed={seed}: {e}",
                      flush=True)
                completed += 1
                continue
            if a_won:
                wins_a_total += 1

            # 2026-05-30 fix: winner-only update (= loser ノイズ 除 去)
            # 負 けた 側 は 「ダ メ な 戦 略」 だけ で は な く ライフ trigger / draw 運 の
            # 不 運 も 含 む。 勝った 側 のみ 強化 で 信号 純化。
            if a_won and traj_a:
                stats_a = update_spec_from_trajectory(
                    specs[a], traj_a, won=True, alpha=args.alpha,
                    clamp_min=args.clamp_min, clamp_max=args.clamp_max,
                )
                total_actions_updated += stats_a["n_actions"]
            if b_won and traj_b:
                stats_b = update_spec_from_trajectory(
                    specs[b], traj_b, won=True, alpha=args.alpha,
                    clamp_min=args.clamp_min, clamp_max=args.clamp_max,
                )
                total_actions_updated += stats_b["n_actions"]

            completed += 1
            if completed % 20 == 0 or completed == total_games:
                elapsed = time.time() - t0
                rate = completed / max(1, elapsed) * 60
                eta = (total_games - completed) / max(1, rate) * 60
                print(f"  [{completed:5d}/{total_games}] {a:22s} vs {b:22s} "
                      f"winner={g.winner} A_wins={wins_a_total} "
                      f"updates={total_actions_updated:,} "
                      f"rate={rate:.0f}/min ETA={eta/60:.1f}min",
                      flush=True)

    elapsed = time.time() - t0
    print(flush=True)
    print(f"[online] DONE: {completed:,} games in {elapsed/60:.1f} min", flush=True)
    print(f"[online] A wins: {wins_a_total:,}/{completed:,} = "
          f"{wins_a_total/max(1,completed)*100:.1f}%", flush=True)
    print(f"[online] total actions updated: {total_actions_updated:,}", flush=True)
    print(flush=True)

    print(f"[online] saving specs to {args.output_dir}", flush=True)
    for slug, spec in specs.items():
        out_path = args.output_dir / f"{slug}.target_v1.json"
        save_spec(spec, out_path)
        n_e_now = len(spec.get("entries", []))
        n_e_init = n_entries_initial[slug]
        print(f"  {slug:22s}: {n_e_init:3d} → {n_e_now:3d} entries "
              f"({n_e_now - n_e_init:+d})", flush=True)

    summary_path = args.output_dir / "_summary.json"
    summary = {
        "alpha": args.alpha,
        "n_games_total": completed,
        "elapsed_min": round(elapsed / 60, 2),
        "wins_a": wins_a_total,
        "actions_updated": total_actions_updated,
        "decks": args.decks,
        "pair_count": len(pairs),
        "entries_per_deck": {slug: len(s.get("entries", []))
                             for slug, s in specs.items()},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    try:
        rel = summary_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        rel = summary_path
    print(f"[online] summary: {rel}", flush=True)


if __name__ == "__main__":
    main()
