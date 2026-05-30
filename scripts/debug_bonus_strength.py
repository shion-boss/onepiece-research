#!/usr/bin/env python3
"""bonus magnitude が AI 行動 を override する 能力 を 測 る test。

NEW spec を base に、 bonus を 1x / 5x / 10x で 試行。
- 全 同 結果 = 「spec 内 容 が base_eval と 同 action 推して る」 (= 構造 限界)
- 結果 違い = 「bonus 強 さ 上げれば argmax flip する」 (= 探索 で 差別 化 可能)
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def run_eval(deck_slug: str, seed: int):
    from engine.deck import CardRepository, DeckList
    from engine.harness import run_matchup
    from engine.goal_directed_ai import GoalDirectedAI
    # cache クリア (= spec file 変更 後 に 正しく 反映 する ため)
    from engine.target_dsl import clear_target_spec_cache
    clear_target_spec_cache()
    repo = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
    deck = DeckList.from_json(REPO_ROOT / "decks" / f"{deck_slug}.json", repo)
    def factory(rng, deck_analysis=None):
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis,
                               beam_width=2, max_depth=4)
    rep = run_matchup(
        deck, deck, n_games=1, seed=seed,
        ai_factory_1=factory, ai_factory_2=factory,
        enable_fire_logging=True, enforce_rules=False,
    )
    g = rep.games[0]
    return g.winner, g.turns, sum(g.fire_counts[0].values()) + sum(g.fire_counts[1].values())


def scale_bonus(spec_path: Path, factor: float, out_path: Path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    for e in spec.get("entries", []):
        for t in e.get("targets", []):
            t["bonus"] = int(t["bonus"] * factor)
    out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    deck = "cardrush_1342"
    seed = 42
    decks_dir = REPO_ROOT / "decks"

    # 旧 spec を backup
    cur_spec_path = decks_dir / f"{deck}.target_v1.json"
    cur_backup = REPO_ROOT / "/tmp/old_spec_for_test.json"
    shutil.copy(cur_spec_path, cur_backup)

    print(f"=== run 1: OLD spec (= 現状) ===", flush=True)
    w_old, t_old, fc_old = run_eval(deck, seed)
    print(f"  winner={w_old} turns={t_old} fires={fc_old}", flush=True)

    # === NEW spec を 生成 して 適用 ===
    import subprocess
    r = subprocess.run([
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        "scripts/build_spec_from_corpus.py",
        "--corpus-dir", "db/game_corpus/round_1_quick",
        "--min-count", "5", "--output-dir", str(decks_dir),
    ], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"build_spec ERROR: {r.stderr}")
        sys.exit(1)
    new_spec_backup = REPO_ROOT / "/tmp/new_spec_for_test.json"
    shutil.copy(cur_spec_path, new_spec_backup)

    print(f"\n=== run 2: NEW 1x bonus ===", flush=True)
    w, t, fc = run_eval(deck, seed)
    print(f"  winner={w} turns={t} fires={fc}", flush=True)

    print(f"\n=== run 3: NEW 5x bonus ===", flush=True)
    scale_bonus(new_spec_backup, 5.0, cur_spec_path)
    w5, t5, fc5 = run_eval(deck, seed)
    print(f"  winner={w5} turns={t5} fires={fc5}", flush=True)

    print(f"\n=== run 4: NEW 10x bonus ===", flush=True)
    scale_bonus(new_spec_backup, 10.0, cur_spec_path)
    w10, t10, fc10 = run_eval(deck, seed)
    print(f"  winner={w10} turns={t10} fires={fc10}", flush=True)

    print(f"\n=== run 5: NEW 50x bonus ===", flush=True)
    scale_bonus(new_spec_backup, 50.0, cur_spec_path)
    w50, t50, fc50 = run_eval(deck, seed)
    print(f"  winner={w50} turns={t50} fires={fc50}", flush=True)

    print(f"\n" + "="*60, flush=True)
    print(f"=== DIAGNOSTIC ===", flush=True)
    print(f"OLD:        winner={w_old:2d} turns={t_old:2d} fires={fc_old:4d}", flush=True)
    print(f"NEW 1x:     winner={w}   turns={t}   fires={fc}", flush=True)
    print(f"NEW 5x:     winner={w5}  turns={t5}  fires={fc5}", flush=True)
    print(f"NEW 10x:    winner={w10} turns={t10} fires={fc10}", flush=True)
    print(f"NEW 50x:    winner={w50} turns={t50} fires={fc50}", flush=True)
    print(flush=True)
    results = [(w, t, fc), (w5, t5, fc5), (w10, t10, fc10), (w50, t50, fc50)]
    if len(set((r[0], r[1]) for r in results)) == 1:
        print("⚠ 全 NEW (1x-50x) で 同じ winner+turns = bonus magnitude 効果 ゼロ", flush=True)
        print("  → spec 内 容 が base_eval と 同じ action を 推して る (= 構造 限界 確定)", flush=True)
        print("  → 探索 で 差別 化 action を corpus に 入れる 必要", flush=True)
    else:
        print(f"✓ bonus magnitude で 行動 変化 確認", flush=True)
        print(f"  → 探索 で 差別 化 entries を 作れば 効く 路線 確定", flush=True)

    # restore OLD
    shutil.copy(cur_backup, cur_spec_path)
    # 残りdeck も backup から restore (= NEW で 上書き した 16 件 全部)
    backups = sorted((REPO_ROOT / "db" / "spec_backups").glob("*"))
    if backups:
        backup_dir = backups[-1]
        for p in backup_dir.glob("*.target_v1.json"):
            shutil.copy(p, decks_dir / p.name)
        print(f"\nrestored 16 OLD specs from {backup_dir.name}", flush=True)


if __name__ == "__main__":
    main()
