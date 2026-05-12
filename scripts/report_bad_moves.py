#!/usr/bin/env python3
"""悪手レポート生成

snapshots に埋め込まれた `board_eval` (R62) を読んで、 各ターンプレイヤーの
連続 snapshot 間の board_eval 変化量 (= delta_eval) を計算し、 大きく負の
変化を「悪手候補」 として抽出する。

公式準拠の評価ではなく、 engine 内部 board_eval の差分。 「真の最善手」 ではなく
「自分が出した手で自陣が不利に傾いた瞬間」 を可視化する。

使い方:
    # マッチアップを 1 件再実行して悪手抽出
    .venv/bin/python scripts/report_bad_moves.py \\
        --deck-a decks/cardrush_1342.json --deck-b decks/cardrush_1308.json \\
        --n-games 5 --seed 42 --threshold -3000

    # 既存 replay (= db/match_replays.sqlite) から抽出
    .venv/bin/python scripts/report_bad_moves.py \\
        --from-replays --pair cardrush_1342:cardrush_1308 --threshold -3000

threshold: delta_eval がこれ以下 (= 不利方向) の手を悪手扱い。 既定 -3000。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.replay_recorder import load_replay, list_replays  # noqa: E402


def extract_bad_moves(
    snapshots: list[dict],
    threshold: float = -3000.0,
) -> list[dict]:
    """連続 snapshot 間の delta_eval を計算し、 threshold 以下の手を抽出。

    各 bad move には:
      - turn: ターン番号
      - player_idx: そのターンの actor (= snapshot[i].turn_player_idx)
      - log: snapshot[i+1] のログ行 (= 何が起きたか)
      - eval_before / eval_after: board_eval 値
      - delta: 差分 (negative = 自陣が不利になった)
    """
    bad = []
    prev_eval = None
    prev_player = None
    for i, snap in enumerate(snapshots):
        cur_eval = snap.get("board_eval")
        cur_player = snap.get("turn_player_idx")
        if cur_eval is None:
            continue
        # 同一プレイヤーのターン内での連続評価のみ比較
        # (= ターン切替で player_idx 変わると視点が反転するので delta 不正)
        if prev_eval is not None and prev_player == cur_player:
            delta = cur_eval - prev_eval
            if delta <= threshold:
                bad.append({
                    "turn": snap.get("turn"),
                    "player_idx": cur_player,
                    "log": snap.get("log", ""),
                    "eval_before": prev_eval,
                    "eval_after": cur_eval,
                    "delta": delta,
                })
        prev_eval = cur_eval
        prev_player = cur_player
    return bad


def report_from_matchup(
    deck_a_path: Path,
    deck_b_path: Path,
    n_games: int,
    seed: int,
    threshold: float,
) -> dict:
    """run_matchup を再実行して snapshots を集める。"""
    repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    deck_a = DeckList.from_json(deck_a_path, repo)
    deck_b = DeckList.from_json(deck_b_path, repo)
    rep = run_matchup(
        deck_a, deck_b, n_games=n_games, seed=seed,
        record_snapshots=True, keep_logs=True,
    )
    return _aggregate_games(rep.games, threshold, deck_a_path.stem, deck_b_path.stem)


def report_from_replays(
    pair: str,
    threshold: float,
    limit: int = 50,
) -> dict:
    """既存 replay DB から抽出 (= pair: "deck_a:deck_b")。"""
    deck_a, deck_b = pair.split(":")
    rows = list_replays(deck_a=deck_a, deck_b=deck_b, limit=limit)
    games = []
    for row in rows:
        rep = load_replay(row["id"])
        # rep["snapshots"] が R62 以降の record で board_eval を含む
        games.append({
            "winner_for_deck_a": row["winner_for_deck_a"],
            "snapshots": rep.get("snapshots", []),
        })
    return _aggregate_games(games, threshold, deck_a, deck_b)


def _aggregate_games(games, threshold: float, deck_a: str, deck_b: str) -> dict:
    """game 一覧から悪手を集計。"""
    per_player_bad = defaultdict(list)
    total_actions = 0
    for gi, g in enumerate(games):
        snaps = g.snapshots if hasattr(g, "snapshots") else g.get("snapshots", [])
        if not snaps:
            continue
        total_actions += sum(1 for s in snaps if s.get("board_eval") is not None)
        bad = extract_bad_moves(snaps, threshold=threshold)
        for b in bad:
            b["game_idx"] = gi
            per_player_bad[b["player_idx"]].append(b)
    return {
        "deck_a": deck_a,
        "deck_b": deck_b,
        "n_games": len(games),
        "total_evaluated_actions": total_actions,
        "threshold": threshold,
        "bad_per_player": {
            "0": {
                "count": len(per_player_bad.get(0, [])),
                "avg_delta": _avg([b["delta"] for b in per_player_bad.get(0, [])]),
                "samples": per_player_bad.get(0, [])[:10],
            },
            "1": {
                "count": len(per_player_bad.get(1, [])),
                "avg_delta": _avg([b["delta"] for b in per_player_bad.get(1, [])]),
                "samples": per_player_bad.get(1, [])[:10],
            },
        },
    }


def _avg(xs):
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck-a", type=Path)
    ap.add_argument("--deck-b", type=Path)
    ap.add_argument("--from-replays", action="store_true")
    ap.add_argument("--pair", help='"deck_a_slug:deck_b_slug" (replay 抽出時)')
    ap.add_argument("--n-games", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threshold", type=float, default=-3000.0,
                    help="delta_eval がこれ以下なら悪手 (既定 -3000)")
    ap.add_argument("--out", type=Path, help="JSON 保存先 (省略時 stdout)")
    args = ap.parse_args()

    if args.from_replays:
        if not args.pair:
            ap.error("--from-replays には --pair が必須")
        result = report_from_replays(args.pair, args.threshold)
    else:
        if not args.deck_a or not args.deck_b:
            ap.error("--deck-a / --deck-b が必須")
        result = report_from_matchup(args.deck_a, args.deck_b, args.n_games, args.seed, args.threshold)

    out_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(out_json, encoding="utf-8")
        print(f"Saved: {args.out}")
    else:
        print(out_json)

    # サマリ
    print(f"\n=== サマリ ({result['deck_a']} vs {result['deck_b']}, n={result['n_games']}) ===")
    for pidx in ("0", "1"):
        info = result["bad_per_player"][pidx]
        deck_name = result['deck_a'] if pidx == "0" else result['deck_b']
        print(f"  P{pidx} ({deck_name}): {info['count']} 悪手 (avg delta {info['avg_delta']:.0f})")


if __name__ == "__main__":
    main()
