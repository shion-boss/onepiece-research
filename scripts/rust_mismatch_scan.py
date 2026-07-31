"""Python↔Rust 差分 MISMATCH の広域スキャン + 診断キュー生成 — 2026-07-31。

`rust_parity_check.py` の差分ハーネスを **広域 (多ペア構成 × 多 seed)** に回し、 各 unique な
silent MISMATCH (= Rust が黙って Python と違う状態を作った箇所) を検出し、 **カード / action /
field 差分 / log / 再現 seed** 付きの人間・エージェント可読キュー `db/rust_mismatch_queue.md` を
**再生成** する。 = 自動修正ルーティン (onepiece-rust-parity-fix skill) の入力。

effect_bugfix_escalate.py の Rust 版: 難 case を黙って残さず、 常に最新の MISMATCH 一覧を repo に出す。

  .venv/bin/python scripts/rust_mismatch_scan.py                 # 広域スキャン → queue 再生成
  .venv/bin/python scripts/rust_mismatch_scan.py --seeds 1-40    # seed 範囲指定
  .venv/bin/python scripts/rust_mismatch_scan.py --assert        # MISMATCH>0 で exit 1 (CI 用)
  .venv/bin/python scripts/rust_mismatch_scan.py --commit        # 変更あれば commit も

各 MISMATCH は「Rust を Python に bit 一致させる or 明示 bail に落とす」ことで潰す (correctness=
MISMATCH0 が不変条件)。 fix 手順は skill onepiece-rust-parity-fix を参照。
"""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.rust_parity_check as P  # noqa: E402
from engine.game import (setup_game, play_until_main, apply_action,  # noqa: E402
                         AttackLeader, AttackCharacter, ActivateMain, AttachDonToCharacter)
from engine.ai import GreedyAI  # noqa: E402
from engine.plan_search import fast_clone  # noqa: E402
from engine.state_snapshot import state_digest, full_dump, canonical_state, diff_canonical  # noqa: E402
from engine.core import reset_iid  # noqa: E402

try:
    import optcg_engine as eng  # noqa: E402
except Exception as exc:  # pragma: no cover
    print(f"optcg_engine 未ビルド ({exc}) — maturin develop が必要", file=sys.stderr)
    sys.exit(2)

OUT = ROOT / "db" / "rust_mismatch_queue.md"


def _parse_seeds(spec: str) -> tuple[int, ...]:
    """"1-40" or "1,7,13" → seed tuple。"""
    if "-" in spec and "," not in spec:
        a, b = spec.split("-")
        return tuple(range(int(a), int(b) + 1))
    return tuple(int(x) for x in spec.split(","))


def _card_of(st, mi, act, t: str) -> str:
    """action の主体カード card_id を特定 (診断ラベル用)。"""
    tp = st.players[mi]
    hi = getattr(act, "hand_idx", None)
    if hi is not None and 0 <= hi < len(tp.hand):
        return tp.hand[hi].card_id
    if isinstance(act, ActivateMain):
        k, i = P._kidx(tp, act.source_iid)
        s = tp.leader if k == "leader" else (tp.characters[i] if k == "character" and i is not None and i < len(tp.characters) else None)
        return s.card.card_id if s else "?"
    if isinstance(act, AttachDonToCharacter):
        k, i = P._kidx(tp, act.target_iid)
        s = tp.characters[i] if k == "character" and i is not None and i < len(tp.characters) else None
        return s.card.card_id if s else "?"
    return "?"


def scan(seeds: tuple[int, ...], offsets=(3, 8, 5), max_turns: int = 300) -> dict:
    """広域スイープ。 unique MISMATCH を {key: 診断} で返す。"""
    _, ov = P._load()
    decks = P.DECKS
    pairs = [(decks[i], decks[(i + j) % len(decks)], s)
             for i in range(len(decks)) for j in offsets for s in seeds]
    seen: dict[str, dict] = {}
    for a, b, s in pairs:
        reset_iid()
        st = setup_game(P._dl(a), P._dl(b), rng=random.Random(s),
                        first_player=s % 2, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(s * 3 + 1)), GreedyAI(rng=random.Random(s * 5 + 2))]
        for _ in range(max_turns):
            if st.game_over:
                break
            mi = st.turn_player_idx
            act = ais[mi].choose_action(st)
            if act is None:
                break
            if isinstance(act, (AttackLeader, AttackCharacter)):
                act = P._defended(st, act, ais[1 - mi])
            e = P._enc(st, act)
            if e.get("t") != "?":
                dump = json.dumps(full_dump(st))
                # static-diff は別軸 (evaluate_static のズレは recompute で isolation) → skip
                if eng.recompute_static_digest(dump) == state_digest(st):
                    c = fast_clone(st)
                    # rng を full_dump の _rng_state に揃える (偽 MISMATCH 防止)
                    _sr = getattr(st, "rng", None)
                    if _sr is not None and hasattr(_sr, "getstate"):
                        _r = random.Random()
                        _r.setstate(_sr.getstate())
                        c.rng = _r
                    try:
                        apply_action(c, act)
                        ok = c.pending_choice is None
                    except Exception:
                        ok = False
                    if ok:
                        try:
                            dr = eng.apply_action_digest(dump, json.dumps(e))
                        except Exception:
                            dr = None  # bail は MISMATCH でない (別軸)
                        if dr is not None and dr != state_digest(c):
                            cid = _card_of(st, mi, act, e["t"])
                            key = f"{e['t']}:{cid}"
                            if key not in seen:
                                try:
                                    blob = json.loads(eng.apply_action_blob(dump, json.dumps(e)))
                                    diffs = diff_canonical(canonical_state(c), blob)[:6]
                                except Exception:
                                    diffs = []
                                logs = [ln for ln in c.log[-10:]
                                        if any(x in ln for x in ("効果", "TRIGGER", "登場", "KO",
                                                                 "レスト", "ドロー", "差替", "公開",
                                                                 "付与", "hit", "atk", "cost"))]
                                seen[key] = {
                                    "action": e["t"], "card": cid, "seed": s,
                                    "pair": f"{a} vs {b}",
                                    "diffs": [list(d) for d in diffs],
                                    "log": logs[-6:],
                                }
            if not st.game_over:
                try:
                    apply_action(st, act)
                except Exception:
                    break
    return seen


def render(seen: dict, seeds: tuple[int, ...]) -> str:
    n = len(seen)
    lines = [
        "# Python↔Rust 差分 MISMATCH キュー (自動生成)",
        "",
        "> `scripts/rust_mismatch_scan.py` が広域差分スイープで検出した **silent MISMATCH**",
        "> (= Rust が黙って Python と違う状態を作った箇所) の一覧。 不変条件 = MISMATCH0",
        "> (Rust は「Python と bit 一致」 か 「明示 bail」 の二択のみ)。 空なら「不一致なし」。",
        "> 消化 = skill `onepiece-rust-parity-fix` の diagnose→fix→verify→commit ループ。",
        ">   各 MISMATCH は Rust を Python 挙動に bit 一致 or 明示 bail に落として潰す。",
        "",
        f"**合計: {n} 件** (scan seeds={seeds[0]}-{seeds[-1]}, {len(seeds)} seeds × 全デッキ × 3 ペア構成)",
        "",
    ]
    if n == 0:
        lines.append("不一致なし (この広域サンプルでは Python↔Rust 完全一致)。")
        return "\n".join(lines) + "\n"
    for i, (key, info) in enumerate(sorted(seen.items()), 1):
        lines.append(f"## {i}. `{info['action']}` : `{info['card']}` (seed={info['seed']})")
        lines.append("")
        lines.append(f"- 再現: {info['pair']} / seed={info['seed']}")
        if info["diffs"]:
            lines.append("- field 差分 (path, python, rust):")
            for d in info["diffs"]:
                lines.append(f"    - `{d[0]}`  py=`{d[1]}`  rust=`{d[2]}`")
        if info["log"]:
            lines.append("- 直前 log:")
            for ln in info["log"]:
                lines.append(f"    - {ln}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Python↔Rust 差分 MISMATCH 広域スキャン + キュー生成")
    ap.add_argument("--seeds", default="1-30", help='seed 範囲 "1-30" か "1,7,13" (既定 1-30)')
    ap.add_argument("--assert", dest="do_assert", action="store_true", help="MISMATCH>0 で exit 1 (CI 用)")
    ap.add_argument("--commit", action="store_true", help="queue 変更あれば commit も")
    args = ap.parse_args()

    seeds = _parse_seeds(args.seeds)
    print(f"広域スキャン: {len(seeds)} seeds × 全デッキ × 3 ペア構成 …", file=sys.stderr)
    seen = scan(seeds)
    md = render(seen, seeds)
    prev = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    changed = md != prev
    OUT.write_text(md, encoding="utf-8")
    print(f"MISMATCH {len(seen)} 件 → {OUT} ({'更新' if changed else '不変'})")
    for key, info in sorted(seen.items()):
        print(f"  {key}  (seed={info['seed']})")

    if args.commit and changed:
        subprocess.run(["git", "add", str(OUT)], cwd=ROOT, check=False)
        subprocess.run(["git", "commit", "-q", "-m",
                        f"chore(rust): MISMATCH キュー再生成 ({len(seen)} 件)"], cwd=ROOT, check=False)
        print("committed queue")

    if args.do_assert and seen:
        print(f"\nFAIL: MISMATCH={len(seen)} 件 (Python↔Rust 同期崩れ)")
        sys.exit(1)


if __name__ == "__main__":
    main()
