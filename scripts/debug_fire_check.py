#!/usr/bin/env python3
"""NEW spec が eval 中 に fire してる か debug (= 2026-05-29、 argmax 不変 問題 切り 分け)。

旧/新 spec で 同 seed で 1 game 走らせ、 fire counts を 比較。

- 0 fire = entry 軸 mismatch (= 修正 必要)
- 多 数 fire + 同 game 結果 = argmax 不変 確定 (= 軸 拡張 + 探索 必要)
"""
from __future__ import annotations

import json
import random
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def run_eval(deck_slug: str, seed: int) -> tuple[int, dict, dict]:
    """1 game 走らせ、 (winner, fire_counts_p0, fire_counts_p1) を 返す。"""
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    from engine.goal_directed_ai import GoalDirectedAI

    repo = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
    deck = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_slug}.json", repo)

    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                               beam_width=2, max_depth=4)

    rep = run_matchup(
        deck, deck,
        n_games=1,
        seed=seed,
        ai_factory_1=factory,
        ai_factory_2=factory,
        enable_fire_logging=True,
        enforce_rules=False,
    )
    g = rep.games[0]
    return g.winner, g.fire_counts[0], g.fire_counts[1]


def main():
    deck = "cardrush_1342"
    seed = 42

    backup_root = REPO_ROOT / "db" / "spec_backups"
    # 最 新 backup を 探す (= pipeline 直 後 の OLD spec 保存)
    backups = sorted(backup_root.glob("*"))
    if not backups:
        print("ERROR: no backup found")
        sys.exit(1)
    backup_dir = backups[-1]  # 最新 (= pipeline 直 後 = OLD spec)
    print(f"backup dir: {backup_dir.name}", flush=True)
    print(f"  → これ は OLD spec (= round 1-6 学習 後) の backup")

    # 現状 (= pipeline 後 OLD 復元 済)
    decks_dir = REPO_ROOT / "decks"
    cur_spec_path = decks_dir / f"{deck}.target_v1.json"
    cur_spec = json.loads(cur_spec_path.read_text(encoding="utf-8"))
    print(f"current spec ({deck}): {len(cur_spec.get('entries', []))} entries", flush=True)

    # === Run 1: 現状 (= OLD) で eval ===
    print()
    print("=== Run 1: OLD spec eval ===", flush=True)
    winner_old, fc_old_0, fc_old_1 = run_eval(deck, seed)
    n_fire_old = sum(fc_old_0.values()) + sum(fc_old_1.values())
    print(f"  winner = {winner_old}", flush=True)
    print(f"  fire counts P0: {len(fc_old_0)} unique entries, {sum(fc_old_0.values())} total fires", flush=True)
    print(f"  fire counts P1: {len(fc_old_1)} unique entries, {sum(fc_old_1.values())} total fires", flush=True)
    if fc_old_0:
        top_old = sorted(fc_old_0.items(), key=lambda x: -x[1])[:5]
        print(f"  top OLD fires P0: {top_old}", flush=True)

    # === NEW spec を 生成 して 適用 ===
    print()
    print("=== build NEW spec from corpus (= round_1_quick) ===", flush=True)
    import subprocess
    r = subprocess.run([
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        "scripts/build_spec_from_corpus.py",
        "--corpus-dir", "db/game_corpus/round_1_quick",
        "--min-count", "5",
        "--output-dir", str(decks_dir),
    ], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"  build_spec ERROR: {r.stderr}", flush=True)
        sys.exit(1)
    print("  build_spec OK", flush=True)

    new_spec = json.loads(cur_spec_path.read_text(encoding="utf-8"))
    print(f"  new spec ({deck}): {len(new_spec.get('entries', []))} entries", flush=True)

    # === Run 2: NEW で eval (= 同 seed) ===
    print()
    print("=== Run 2: NEW spec eval (same seed=42) ===", flush=True)
    winner_new, fc_new_0, fc_new_1 = run_eval(deck, seed)
    n_fire_new = sum(fc_new_0.values()) + sum(fc_new_1.values())
    print(f"  winner = {winner_new}", flush=True)
    print(f"  fire counts P0: {len(fc_new_0)} unique entries, {sum(fc_new_0.values())} total fires", flush=True)
    print(f"  fire counts P1: {len(fc_new_1)} unique entries, {sum(fc_new_1.values())} total fires", flush=True)
    if fc_new_0:
        top_new = sorted(fc_new_0.items(), key=lambda x: -x[1])[:5]
        print(f"  top NEW fires P0: {top_new}", flush=True)

    # === 比較 ===
    print()
    print("=" * 60, flush=True)
    print("=== DIAGNOSTICS ===", flush=True)
    print(f"OLD: winner={winner_old}, total fires P0+P1 = {n_fire_old}", flush=True)
    print(f"NEW: winner={winner_new}, total fires P0+P1 = {n_fire_new}", flush=True)
    print(flush=True)
    if n_fire_new == 0:
        print("⚠ NEW spec entries: **0 fire** = 軸 mismatch あり、 修正 必要", flush=True)
    elif winner_old == winner_new and n_fire_new > 0:
        print(f"⚠ NEW spec: {n_fire_new} fires が 起き てる が 結果 同じ", flush=True)
        print(f"  → argmax 不変 trap 確定: bonus 値 違い が 行動 変えて ない", flush=True)
        print(f"  → 軸 拡張 + 探索 で 解決 する べき", flush=True)
    else:
        print(f"✓ NEW spec: {n_fire_new} fires + 結果 違い (winner OLD={winner_old}, NEW={winner_new})", flush=True)
        print(f"  → 行動 変化 確認、 学習 効果 あり", flush=True)

    # === restore OLD spec ===
    print()
    print("=== restore OLD spec ===", flush=True)
    for p in backup_dir.glob("*.target_v1.json"):
        shutil.copy(p, decks_dir / p.name)
    print(f"  restored {len(list(backup_dir.glob('*.target_v1.json')))} files", flush=True)


if __name__ == "__main__":
    main()
