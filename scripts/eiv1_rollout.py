"""EIV1 rollout-target 最小パイプライン — 2026-07-24。

「最終勝敗ラベル」は弱い教師 (試合の結果を全局面に貼るだけ = ノイズ大、 兄弟手の優劣を教えない)。
rollout target = 各局面から実際に打ち進めた勝率 = その局面の本当の価値。 これで「言わずに
戦術を学ぶ」 (= 速攻リーサルの危険度なども rollout の中で自然に発生し数字になる) を狙う。

段取り (subcommand):
  collect : 自己対戦 (hero=EIV1 value beam / opp=EBV2) → 各 hero-MAIN 局面で fork → 相手手札を
            belief で determinize → greedy で K 回 playout → 勝率 yr。 最終勝敗 y も併記して
            db/eiv1/rollout_corpus.jsonl に APPEND。
  train   : 同一局面・同一 feature(v20 94dim) で
              value_rollout = yr (rollout 勝率) を学習した regressor
              value_outcome = y  (最終勝敗) を学習した data-matched baseline
            を作る。
  arena   : value_rollout vs value_outcome を ε=0 arena で直接対決。
            rollout > outcome なら「rollout target が兄弟手の優劣を学べた」= 機構が効く。

⚠ rollout policy は既定 greedy (安価)。 memory: greedy-rollout は beam 学習 value に非整合で
負けうる → policy 整合が鍵。 まず機構の proof を取り、 効けば policy を beam-lite に上げる。

  .venv/bin/python scripts/eiv1_rollout.py collect --games 200 --rollouts 6 --workers 6
  .venv/bin/python scripts/eiv1_rollout.py train
  .venv/bin/python scripts/eiv1_rollout.py arena --pairs 40 --workers 6
"""
from __future__ import annotations
import os

for _tv in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_tv, "1")
import argparse
import json
import math
import pickle
import random
import subprocess
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from engine.ai import GreedyAI, play_one_action  # noqa: E402
from engine.core import Phase  # noqa: E402
from engine.exploit_beam_ai import ExploitBeamAI  # noqa: E402
from engine.game import advance_phase, legal_actions, play_until_main, setup_game  # noqa: E402
from engine.eiv1_features import eiv1_features  # noqa: E402
from engine.game_corpus import snapshot_state  # noqa: E402
from engine.plan_search import fast_clone  # noqa: E402
# eiv1_collect と同じ deck/overlay ロードを共有
from eiv1_collect import _ana, _dl, _parse_pool, _slug, AGNOSTIC, EIV1_VALUE, _OVERLAY  # noqa: E402

EIV1_DIR = ROOT / "db" / "eiv1"
RC = EIV1_DIR / "rollout_corpus.jsonl"
V_ROLLOUT = EIV1_DIR / "value_rollout.pkl"
V_OUTCOME = EIV1_DIR / "value_outcome.pkl"

ROLLOUTS = 6
BEAM_W, BEAM_D = 8, 6
RO_TURN_CAP = 40


def _determinize_opp(st, hero_idx: int, rng: random.Random) -> None:
    """相手の隠匿手札を belief で貼り替える (= 配備 AI は相手手札を知らないので公平)。
    見えている札 (known_hand) は固定、 残りをデッキと混ぜて再配布 → デッキもシャッフル。"""
    opp = st.players[1 - hero_idx]
    hand = list(getattr(opp, "hand", []) or [])
    deck = list(getattr(opp, "deck", []) or [])
    known = set(getattr(opp, "known_hand_card_ids", []) or [])
    fixed, pool = [], []
    for c in hand:
        (fixed if c.card_id in known else pool).append(c)
    pool.extend(deck)
    rng.shuffle(pool)
    need = len(hand) - len(fixed)
    opp.hand = fixed + pool[:need]
    opp.deck = pool[need:]
    rng.shuffle(opp.deck)


def _rollout_winrate(base_state, hero_idx: int, n: int, seed: int) -> float:
    """base_state から greedy 同士で最後まで n 回 playout → hero の勝率。
    各 playout で相手手札を determinize (公平) + デッキを再シャッフル (引き順は未知)。"""
    start_turn = base_state.turn_number
    wins = 0.0
    for i in range(n):
        r = random.Random(seed * 1009 + i)
        st = fast_clone(base_state)
        st.rng = random.Random(seed * 7919 + i)
        _determinize_opp(st, hero_idx, r)
        # 自分のデッキも引き順は未知 → シャッフル (手札は既知なので固定)
        r.shuffle(st.players[hero_idx].deck)
        ais = {0: GreedyAI(rng=random.Random(seed * 3 + i)),
               1: GreedyAI(rng=random.Random(seed * 5 + i + 1))}
        guard = 0
        while not st.game_over and guard < 800 and st.turn_number <= start_turn + RO_TURN_CAP:
            guard += 1
            cur = st.turn_player_idx
            if st.phase == Phase.MAIN:
                try:
                    play_one_action(st, ais[cur], ais[1 - cur])
                except Exception:
                    break
            else:
                advance_phase(st)
        if st.game_over:
            w = getattr(st, "winner", -1)
            wins += 1.0 if w == hero_idx else (0.5 if w == -1 else 0.0)
        else:
            wins += 0.5
    return wins / max(1, n)


def _collect_game(task):
    seed, hero, opp, k = task
    hero_first = (seed % 2 == 0)
    try:
        if hero_first:
            st = setup_game(_dl(hero), _dl(opp), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(hero),
                            deck2_analysis=_ana(opp))
            hero_idx = 0
        else:
            st = setup_game(_dl(opp), _dl(hero), rng=random.Random(seed), first_player=0,
                            effects_overlay=_OVERLAY, deck1_analysis=_ana(opp),
                            deck2_analysis=_ana(hero))
            hero_idx = 1
    except Exception:
        return []
    play_until_main(st)
    vp = str(EIV1_VALUE) if EIV1_VALUE.exists() else AGNOSTIC
    ais = [None, None]
    ais[hero_idx] = ExploitBeamAI(rng=random.Random(seed * 3 + 1),
                                  deck_analysis={**_ana(hero), "deck_slug": _slug(hero)},
                                  gbm_path=vp, beam_width=BEAM_W, max_depth=BEAM_D)
    ais[1 - hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                      deck_analysis={**_ana(opp), "deck_slug": _slug(opp)},
                                      gbm_path=AGNOSTIC, beam_width=BEAM_W, max_depth=BEAM_D)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    rows, seen, n = [], set(), 0
    while not st.game_over and st.turn_number < 60 and n < 800:
        cur = st.turn_player_idx
        if cur == hero_idx and st.phase == Phase.MAIN and st.turn_number not in seen:
            seen.add(st.turn_number)
            try:
                fv = eiv1_features(st, hero_idx)
                snap = snapshot_state(st)
                snap["hero_idx"] = hero_idx
                # ⭐ rollout ラベル = この局面から greedy で k 回 playout した hero 勝率
                yr = _rollout_winrate(st, hero_idx, k, seed * 100 + st.turn_number)
                rows.append((fv, snap, yr))
            except Exception:
                pass
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return []
    y = 1 if getattr(st, "winner", -1) == hero_idx else 0
    hs, os_ = _slug(hero), _slug(opp)
    return [(fv, y, yr, hs, os_, snap) for fv, snap, yr in rows]


def cmd_collect(a):
    heroes = _parse_pool(a.heroes)
    opps = _parse_pool(a.opps)
    base = 500000 + (RC.stat().st_size if RC.exists() else 0) % 400000
    tasks = []
    for i in range(a.games):
        seed = base + i
        r = random.Random(seed * 9176 + 12345)
        tasks.append((seed, r.choice(heroes), r.choice(opps), a.rollouts))
    print(f"rollout collect: {a.games} games × {a.rollouts} rollouts/局面 "
          f"| hero pool={len(heroes)} opp pool={len(opps)}", flush=True)
    t0 = time.time()
    results = []
    with mp.Pool(a.workers) as pool:
        for r in pool.imap_unordered(_collect_game, tasks):
            if r:
                results.append(r)
    rows = [row for r in results for row in r]
    with open(RC, "a", encoding="utf-8") as f:
        for fv, y, yr, hero, opp, snap in rows:
            f.write(json.dumps({"f": fv, "y": y, "yr": yr, "hero": hero, "opp": opp,
                                "state": snap}) + "\n")
    total = sum(1 for _ in open(RC)) if RC.exists() else 0
    ys = [row[1] for r in results for row in r]
    yrs = [row[2] for r in results for row in r]
    print(f"appended {len(rows)} 局面 from {len(results)} games ({time.time()-t0:.0f}s) "
          f"| 平均 y(最終勝敗)={sum(ys)/max(len(ys),1):.3f} yr(rollout)={sum(yrs)/max(len(yrs),1):.3f} "
          f"→ corpus 総計 {total}", flush=True)


def cmd_train(a):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from engine.eiv1_features import eiv1_train_vector
    X, y, yr = [], [], []
    for line in open(RC, encoding="utf-8"):
        try:
            d = json.loads(line)
            X.append(eiv1_train_vector(d))
            y.append(float(d["y"]))
            yr.append(float(d["yr"]))
        except Exception:
            continue
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    yr = np.array(yr, dtype=np.float32)
    print(f"train: n={len(y):,} dim={X.shape[1]} | y 平均={y.mean():.3f} yr 平均={yr.mean():.3f} "
          f"| corr(y,yr)={np.corrcoef(y, yr)[0,1]:.3f}", flush=True)
    cap = dict(random_state=0, max_iter=600, max_leaf_nodes=63, learning_rate=0.05,
               l2_regularization=1.0)
    for tag, target, path in (("rollout", yr, V_ROLLOUT), ("outcome", y, V_OUTCOME)):
        m = HistGradientBoostingRegressor(**cap)
        m.fit(X, target)
        with open(path, "wb") as f:
            pickle.dump(m, f)
        # 空 spec を対で保存 (推論経路が spec を探すため)
        from engine.feature_spec import save_spec, spec_path_for_model
        save_spec(spec_path_for_model(path), [], {"target": tag})
        print(f"  value_{tag} 保存 (target={tag})", flush=True)


def cmd_arena(a):
    print("arena: value_rollout vs value_outcome (ε=0、 data-matched)", flush=True)
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "scripts" / "eiv1_arena.py"),
         "--arm", str(V_ROLLOUT), "--refs", str(V_OUTCOME), "--pairs", str(a.pairs),
         "--workers", str(a.workers)], capture_output=True, text=True)
    print(r.stdout.strip(), flush=True)
    if r.returncode != 0:
        print(r.stderr[-500:], flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--games", type=int, default=200)
    c.add_argument("--rollouts", type=int, default=ROLLOUTS)
    c.add_argument("--workers", type=int, default=6)
    c.add_argument("--heroes", default="@db/eiv1/pool_all.txt")
    c.add_argument("--opps", default="@db/eiv1/pool_all.txt")
    sub.add_parser("train")
    ar = sub.add_parser("arena")
    ar.add_argument("--pairs", type=int, default=40)
    ar.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    {"collect": cmd_collect, "train": cmd_train, "arena": cmd_arena}[a.cmd](a)


if __name__ == "__main__":
    main()
