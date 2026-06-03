#!/usr/bin/env python3
"""層6 warm-start: 既存 corpus から plan bonus テーブルを構築 (= [[project_superhuman_ai_distillation]])。

self-play を 0 から回す代わりに、 **既に打たれた数万 game** を (game, turn, actor) で
ターン単位にグループ化し、 各ターンの **multiset plan signature** と勝敗を集計して
PlanBonusTable を per-deck で作る。 「対戦から bonus 最適化」 を corpus 規模で安く実現。

⚠ teacher 天井則: corpus = その corpus を生成した AI (= 今回は壊れた pure_lookup ≒ GreedyAI)
の打ち筋。 ここから学んだ bonus の天井 ≒ その AI。 超えるには beam 教師 or self-play iteration。
まずは「lookup+commit が教師に追随できるか」 を検証する warm-start。

token / cell 規約は engine/turn_plan_enumerator.abstract_token と
engine/plan_library.cell_key_from_state に厳密一致させる (= 推論時に lookup が当たるため)。

使い方:
  .venv/bin/python -u scripts/build_plan_library_from_corpus.py \
      --corpus-dir db/game_corpus/refresh_phaseA_fixed_20260603 \
      --out-dir db/plan_tables --workers 12
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.axis_compute import compute_axes_from_snapshot
from engine.plan_library import _CELL_AXES_COARSE, PlanBonusTable
from scripts.build_spec_from_corpus import (
    build_leader_maps,
    resolve_card_id,
    _resolve_side_idx,
)


# ===========================================================================
# token 抽出 (= 推論側 abstract_token と一致させる)
# ===========================================================================


def _activate_card_id(sb_player: dict, source_iid) -> str | None:
    for c in sb_player.get("field", []) or []:
        if isinstance(c, dict) and c.get("instance_id") == source_iid:
            return c.get("card_id")
    return None


def _token(action_dict: dict, sb_player: dict) -> tuple | None:
    kind = action_dict.get("kind")
    if kind in ("PlayCharacter", "PlayEvent", "PlayStage"):
        return ("play", resolve_card_id(action_dict, sb_player))
    if kind == "AttachDonToLeader":
        return ("attach_don", "leader", int(action_dict.get("n", 1)))
    if kind == "AttachDonToCharacter":
        return ("attach_don", "chara", int(action_dict.get("n", 1)))
    if kind == "ActivateMain":
        # snapshot field に instance_id が無く source 解決不可 → live (abstract_token) と
        # 揃えて bare marker にする。
        return ("activate",)
    if kind == "AttackLeader":
        return ("attack", "leader_face")
    if kind == "AttackCharacter":
        return ("attack", "enemy_chara")
    return None  # EndPhase 等


def _cell_from_snapshot(sb: dict, actor_idx: int) -> tuple:
    """compute_axes_from_snapshot → _CELL_AXES_COARSE subset の正準タプル
    (= plan_library.cell_key_from_state と同形)。"""
    axes = compute_axes_from_snapshot(sb, actor_idx, 1 - actor_idx, "midrange")
    return tuple((k, axes.get(k)) for k in _CELL_AXES_COARSE)


def extract_turn_plans(game: dict, leader_to_deck: dict) -> list[tuple]:
    """1 game → [(deck_slug, cell, multiset_key, won), ...] (= ターン単位)。"""
    winner_for_a = (game.get("result") or {}).get("winner_for_deck_a", -1)
    if winner_for_a == -1:
        return []
    side_a_idx, side_b_idx = _resolve_side_idx(game)

    # (turn, actor) ごとに token 列 + turn-start snapshot を集約
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for a in game.get("actions", []):
        actor = a.get("active_player")
        if actor not in (0, 1):
            continue
        turn = a.get("turn_number", -1)
        key = (turn, actor)
        sb = a.get("state_before") or {}
        players = sb.get("players")
        if not players or len(players) != 2:
            continue
        if key not in groups:
            groups[key] = {"sb": sb, "tokens": []}
            order.append(key)
        tok = _token(a.get("action", {}), players[actor])
        if tok is not None:
            groups[key]["tokens"].append(tok)

    out = []
    for key in order:
        turn, actor = key
        g = groups[key]
        if not g["tokens"]:
            continue  # 何もしなかったターン (= EndPhase のみ) は plan にしない
        sb = g["sb"]
        actor_p = sb["players"][actor]
        actor_leader = (actor_p.get("leader") or {}).get("card_id")
        deck_slug = leader_to_deck.get(actor_leader)
        if not deck_slug:
            continue  # 管理外 deck
        cell = _cell_from_snapshot(sb, actor)
        mk = frozenset(Counter(g["tokens"]).items())
        actor_won = (actor == side_a_idx and winner_for_a == 0) or \
                    (actor == side_b_idx and winner_for_a == 1)
        out.append((deck_slug, cell, mk, actor_won))
    return out


# ===========================================================================
# 並列 scan (= build_spec と同型 map-reduce)
# ===========================================================================

_WORKER_L2D: dict | None = None


def _scan_init(leader_to_deck: dict) -> None:
    global _WORKER_L2D
    _WORKER_L2D = leader_to_deck


def _scan_chunk(files: list) -> dict:
    """worker: file chunk → {(deck, cell, mk): [n_total, n_won]}。"""
    stats: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for fp in files:
        try:
            game = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception:
            continue
        for (deck_slug, cell, mk, won) in extract_turn_plans(game, _WORKER_L2D):
            rec = stats[(deck_slug, cell, mk)]
            rec[0] += 1
            if won:
                rec[1] += 1
    return dict(stats)


def scan_corpus(corpus_dir: Path, workers: int, chunk_size: int = 300) -> dict:
    leader_to_deck, _deck_to_arch, _ = build_leader_maps()
    files = [str(p) for p in sorted(corpus_dir.rglob("game_*.json"))]
    merged: dict[tuple, list] = defaultdict(lambda: [0, 0])
    if not files:
        return {}
    chunks = [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]
    print(f"[plan_lib] {len(files):,} games / {len(chunks):,} chunks / {workers} workers",
          flush=True)
    done = 0
    if workers <= 1:
        _scan_init(leader_to_deck)
        for ch in chunks:
            for k, v in _scan_chunk(ch).items():
                merged[k][0] += v[0]
                merged[k][1] += v[1]
            done += 1
            if done % 20 == 0 or done == len(chunks):
                print(f"  [scan] {done}/{len(chunks)} keys={len(merged):,}", flush=True)
    else:
        with mp.Pool(workers, initializer=_scan_init, initargs=(leader_to_deck,),
                     maxtasksperchild=50) as pool:
            for st in pool.imap_unordered(_scan_chunk, chunks, chunksize=1):
                for k, v in st.items():
                    merged[k][0] += v[0]
                    merged[k][1] += v[1]
                done += 1
                if done % 20 == 0 or done == len(chunks):
                    print(f"  [scan] {done}/{len(chunks)} keys={len(merged):,}", flush=True)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "db" / "plan_tables")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--temp", type=float, default=2000.0)
    ap.add_argument("--shrink-k", type=float, default=6.0)
    ap.add_argument("--min-n", type=int, default=1,
                    help="この n 未満の (cell,plan) は出力しない (= ノイズ抑制)")
    args = ap.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    merged = scan_corpus(args.corpus_dir, args.workers)
    print(f"[plan_lib] total (deck,cell,plan) keys: {len(merged):,}", flush=True)

    # per-deck に分割 → PlanBonusTable
    by_deck: dict[str, PlanBonusTable] = {}
    n_kept = 0
    for (deck_slug, cell, mk), (n_total, n_won) in merged.items():
        if n_total < args.min_n:
            continue
        tbl = by_deck.get(deck_slug)
        if tbl is None:
            tbl = PlanBonusTable(temp=args.temp, shrink_k=args.shrink_k)
            by_deck[deck_slug] = tbl
        tbl._t[(cell, mk)] = [n_total, n_won]
        n_kept += 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[plan_lib] kept {n_kept:,} entries across {len(by_deck)} decks "
          f"(min_n={args.min_n})", flush=True)
    for slug, tbl in sorted(by_deck.items()):
        out = args.out_dir / f"{slug}.plan_v1.json"
        tbl.save(out)
        # n 分布
        ns = sorted((rec[0] for rec in tbl._t.values()), reverse=True)
        n_ge10 = sum(1 for x in ns if x >= 10)
        n_ge50 = sum(1 for x in ns if x >= 50)
        print(f"  {slug:28s}: {len(tbl):6d} plans  (n>=10: {n_ge10:5d}, n>=50: {n_ge50:4d}, "
              f"max_n={ns[0] if ns else 0})", flush=True)
    print(f"[plan_lib] wrote per-deck tables → {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
