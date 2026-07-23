"""EIV1 の「強さ」指標 = ε=0 の counterbalanced arena (2026-07-23)。

corpus の win率 は ε=0.15 のハンデ込み・sample 重み付きなので「強くなったか」を測れない。
ここでは 探索ノイズ無し (ε=0) で 現 EIV1 value を 凍結した基準 value と直接戦わせる。

⭐ counterbalance: 1 ペア (d1, d2, seed) につき 4 game を回し、
   ①A=d1先攻 ②A=d1後攻 ③A=d2先攻 ④A=d2後攻
   = デッキ有利 と 先攻後攻 の両方を相殺する (残差 = value の差だけ)。

基準 (--refs):
  agnostic        db/value_gbm_agnostic.pkl (= EBV2、 外部固定基準 → 絶対位置)
  snapshot:<iter> db/eiv1/snapshots/value_iter<iter>.pkl (= 過去の自分 → 自己改善曲線)
  snapshot:oldest 現存する最古スナップショット
  <path>          任意の pkl

結果は db/eiv1/arena.jsonl に append (iter 付き) → 「iter に対する強さ曲線」。

  .venv/bin/python scripts/eiv1_arena.py --pairs 100 --workers 12
  .venv/bin/python scripts/eiv1_arena.py --refs agnostic,snapshot:oldest --pairs 50
"""
from __future__ import annotations
import argparse
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# deck/overlay ロードと ref 解決を collect と完全に共有する (= 同じ土俵で測る)
from eiv1_collect import _ana, _dl, _parse_pool, _slug, AGNOSTIC, EIV1_VALUE, _OVERLAY  # noqa: E402
from engine.ai import play_one_action  # noqa: E402
from engine.exploit_beam_ai import ExploitBeamAI  # noqa: E402
from engine.game import play_until_main, setup_game  # noqa: E402

EIV1_DIR = ROOT / "db" / "eiv1"
SNAP_DIR = EIV1_DIR / "snapshots"
ARENA_LOG = EIV1_DIR / "arena.jsonl"
MANIFEST = EIV1_DIR / "manifest.json"

BEAM_W, BEAM_D = 8, 6   # module-global (worker が fork で継承)


def _resolve_ref(ref: str) -> str | None:
    """基準 value の alias を実パスに。 見つからなければ None (= その ref は skip)。"""
    if ref == "agnostic":
        return AGNOSTIC if Path(AGNOSTIC).exists() else None
    if ref.startswith("snapshot:"):
        tag = ref.split(":", 1)[1]
        snaps = sorted(SNAP_DIR.glob("value_iter*.pkl"),
                       key=lambda p: int(p.stem.replace("value_iter", "")))
        if not snaps:
            return None
        if tag == "oldest":
            return str(snaps[0])
        if tag == "latest":
            return str(snaps[-1])
        p = SNAP_DIR / f"value_iter{int(tag)}.pkl"
        return str(p) if p.exists() else None
    p = Path(ref)
    if not p.is_absolute():
        p = ROOT / ref
    return str(p) if p.exists() else None


def _play(task):
    """A が deck_a を、 B が deck_b を操縦して 1 game。 返り値 = (A の勝敗, A が先攻か)。"""
    seed, deck_a, deck_b, a_first, path_a, path_b = task
    try:
        if a_first:
            st = setup_game(_dl(deck_a), _dl(deck_b), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(deck_a),
                            deck2_analysis=_ana(deck_b))
            a_idx = 0
        else:
            st = setup_game(_dl(deck_b), _dl(deck_a), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(deck_b),
                            deck2_analysis=_ana(deck_a))
            a_idx = 1
        play_until_main(st)
    except Exception:
        return None
    ais = [None, None]
    ais[a_idx] = ExploitBeamAI(rng=random.Random(seed * 3 + 1),
                               deck_analysis={**_ana(deck_a), "deck_slug": _slug(deck_a)},
                               gbm_path=path_a, beam_width=BEAM_W, max_depth=BEAM_D)
    ais[1 - a_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                   deck_analysis={**_ana(deck_b), "deck_slug": _slug(deck_b)},
                                   gbm_path=path_b, beam_width=BEAM_W, max_depth=BEAM_D)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    n = 0
    while not st.game_over and st.turn_number < 60 and n < 800:
        cur = st.turn_player_idx
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return None   # 未決着は除外 (勝敗を捏造しない)
    return (1 if getattr(st, "winner", -1) == a_idx else 0), bool(a_first)


def _run_arena(path_a: str, path_b: str, pool: list, pairs: int, seed0: int, workers: int,
               timeout_s: int) -> dict:
    tasks = []
    for i in range(pairs):
        seed = seed0 + i * 7
        r = random.Random(seed * 9176 + 12345)
        d1, d2 = r.choice(pool), r.choice(pool)
        # counterbalance: デッキ側 (d1/d2) × 先攻後攻 の 4 通り
        for deck_a, deck_b in ((d1, d2), (d2, d1)):
            for a_first in (True, False):
                tasks.append((seed, deck_a, deck_b, a_first, path_a, path_b))
    t0 = time.time()
    with mp.Pool(workers) as pl:
        try:
            res = pl.map_async(_play, tasks).get(timeout=timeout_s)
        except mp.TimeoutError:
            pl.terminate()
            print(f"!! arena timeout ({timeout_s}s) → 打ち切り", flush=True)
            res = []
    ok = [r for r in res if r is not None]
    n = len(ok)
    if not n:
        return {"n_games": 0}
    wins = sum(w for w, _ in ok)
    p = wins / n
    se = math.sqrt(max(p * (1 - p), 1e-9) / n)
    first = [w for w, f in ok if f]
    second = [w for w, f in ok if not f]
    return {"n_games": n, "n_dropped": len(res) - n, "win": p, "se": se,
            "win_first": (sum(first) / len(first)) if first else None,
            "win_second": (sum(second) / len(second)) if second else None,
            "secs": round(time.time() - t0, 1)}


def main():
    global BEAM_W, BEAM_D
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=100, help="1 ペア = 4 game (counterbalanced)")
    ap.add_argument("--refs", default="agnostic", help="基準 value (comma-list)")
    ap.add_argument("--arm", default=str(EIV1_VALUE), help="測る側の value (既定 = 現 EIV1)")
    ap.add_argument("--pool", default="@db/eiv1/pool_all.txt")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260723)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    a = ap.parse_args()
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    if not Path(a.arm).exists():
        print(f"!! arm value 無し ({a.arm}) → 先に eiv1_train.py")
        return
    pool = _parse_pool(a.pool)
    it = 0
    if MANIFEST.exists():
        try:
            it = int(json.loads(MANIFEST.read_text(encoding="utf-8")).get("train_iters", 0))
        except Exception:
            pass
    timeout_s = int(os.environ.get("EIV1_ARENA_TIMEOUT", "2400"))
    for ref in [s for s in a.refs.split(",") if s]:
        path_b = _resolve_ref(ref)
        if not path_b:
            print(f"arena skip: 基準 {ref} が見つからない", flush=True)
            continue
        print(f"EIV1 arena: iter{it} value vs {ref} | pairs={a.pairs} (=4x games) "
              f"eps=0 beam={BEAM_W}/{BEAM_D} pool={len(pool)}", flush=True)
        r = _run_arena(a.arm, path_b, pool, a.pairs, a.seed, a.workers, timeout_s)
        if not r.get("n_games"):
            print("  !! 有効ゲーム 0", flush=True)
            continue
        print(f"  EIV1 勝率 = {r['win']:.3f} ± {r['se']:.3f} (N={r['n_games']}, "
              f"先攻 {r['win_first']:.3f} / 後攻 {r['win_second']:.3f}, {r['secs']}s)", flush=True)
        rec = {"iter": it, "ref": ref, "ref_path": path_b, "arm": a.arm,
               "beam": [BEAM_W, BEAM_D], "pairs": a.pairs, **r}
        with open(ARENA_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
