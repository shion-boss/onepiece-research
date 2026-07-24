"""EIV1-ExIt データ収集 = 探索の「改善された初手ランキング」を蒸留教師として記録 — 2026-07-24。

自己対戦 (hero=ExploitBeam[現policy+温度探索+capture] / opp=世代窓) を回し、 各 hero 判断で
探索 (beam) が出した「初手 → best score」を pop_exit_policy() で取り、 同一判断の兄弟初手を
1グループとして記録。 学習側 (eiv1_exit_train) が群内相対 advantage を policy 教師にする。

= Expert Iteration の "探索(熟練者)→蒸留" の収集側。 誰の指摘も要らず、 探索が engine の中で
踏んだ帰結 (速攻リーサル・温存カウンター等) が policy 教師として自動 banking される。

各行 = 1 判断: {"sibs": [[feat116, score], ...], "y": 最終勝敗, "hero", "opp", "turn"}
  feat116 = 状態v20(94) + 行動identity(22)。 y は hero 視点の勝敗 (value floor 用に併記)。

  .venv/bin/python scripts/eiv1_exit_collect.py --games 150 --workers 8 --temperature 0.6
"""
from __future__ import annotations
import os

for _tv in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_tv, "1")
os.environ["ONEPIECE_EXIT_CAPTURE"] = "1"   # 探索に policy capture を有効化 (worker が fork 継承)
import argparse
import json
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from engine.game import setup_game, play_until_main  # noqa: E402
from engine.ai import play_one_action  # noqa: E402
from engine.core import Phase  # noqa: E402
from engine.exploit_beam_ai import ExploitBeamAI  # noqa: E402
from engine import plan_search  # noqa: E402
from engine.exit_policy import featurize  # noqa: E402
# eiv1_collect と deck/overlay/世代窓 opp を共有
from eiv1_collect import (_ana, _dl, _parse_pool, _pick_opp_value, _resolve_opp_mix, _slug,  # noqa: E402
                          AGNOSTIC, EIV1_VALUE, _OVERLAY)

EIV1_DIR = ROOT / "db" / "eiv1"
EXIT_CORPUS = EIV1_DIR / "exit_corpus.jsonl"
BEAM_W, BEAM_D = 8, 6
TEMP = 0.6
EXIT_POLICY_W = 0.0   # collect 時に現 policy で探索を導くか (0=素の探索、 >0=on-policy ExIt)
HEROES: list = []
OPPS: list = []


def _hero_value_path() -> str:
    return str(EIV1_VALUE) if EIV1_VALUE.exists() else AGNOSTIC


def _collect_game(task):
    seed, hero, opp, opp_value = task
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
    ais = [None, None]
    # hero = 現 policy を使う探索 (on-policy ExIt) + 温度探索。 capture は env で ON。
    ais[hero_idx] = ExploitBeamAI(rng=random.Random(seed * 3 + 1),
                                  deck_analysis={**_ana(hero), "deck_slug": _slug(hero)},
                                  gbm_path=_hero_value_path(), beam_width=BEAM_W, max_depth=BEAM_D,
                                  plan_temperature=TEMP, exit_policy_w=EXIT_POLICY_W)
    # opp = 世代窓から抽選した value (cycling 回避)
    if opp_value == AGNOSTIC:
        ais[1 - hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                          deck_analysis={**_ana(opp), "deck_slug": _slug(opp)},
                                          gbm_path=opp_value, beam_width=BEAM_W, max_depth=BEAM_D)
    else:
        ais[1 - hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                          deck_analysis={**_ana(opp), "deck_slug": _slug(opp)},
                                          gbm_path=opp_value, beam_width=BEAM_W, max_depth=BEAM_D,
                                          plan_temperature=TEMP)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])

    decisions: list = []   # [(turn, [(feat116, score), ...])]
    n = 0
    while not st.game_over and st.turn_number < 60 and n < 800:
        cur = st.turn_player_idx
        if cur == hero_idx and st.phase == Phase.MAIN:
            try:
                action = ais[cur].choose_action(st)
                pol = plan_search.pop_exit_policy()   # [(初手 Action, score)]
                sibs = []
                for act, sc in pol:
                    if act is None:
                        continue
                    try:
                        sibs.append((featurize(st, act, hero_idx), float(sc)))
                    except Exception:
                        continue
                if len(sibs) >= 2:   # 兄弟が 2 個以上ある判断のみ (= 選択の余地がある)
                    decisions.append((st.turn_number, sibs))
                # choose_action が返した手をそのまま適用 (二重探索を避ける)
                from engine.game import apply_action
                apply_action(st, action)
                n += 1
                continue
            except Exception:
                pass
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over or not decisions:
        return []
    y = 1 if getattr(st, "winner", -1) == hero_idx else 0
    hs, os_ = _slug(hero), _slug(opp)
    return [(turn, sibs, y, hs, os_) for turn, sibs in decisions]


def main():
    global HEROES, OPPS, BEAM_W, BEAM_D, TEMP, EXIT_POLICY_W
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=150)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--heroes", default="@db/eiv1/pool_all.txt")
    ap.add_argument("--opps", default="@db/eiv1/pool_all.txt")
    ap.add_argument("--opp-mix", default="eiv1:0.2,gen1:0.25,gen2:0.2,gen3:0.15,snapshot:0.2")
    ap.add_argument("--temperature", type=float, default=TEMP)
    ap.add_argument("--exit-policy-w", type=float, default=0.0,
                    help=">0 で現 policy を使って探索を導く (on-policy ExIt)")
    ap.add_argument("--beam-width", type=int, default=BEAM_W)
    ap.add_argument("--max-depth", type=int, default=BEAM_D)
    ap.add_argument("--seed-base", type=int, default=None)
    a = ap.parse_args()
    HEROES = _parse_pool(a.heroes)
    OPPS = _parse_pool(a.opps)
    BEAM_W, BEAM_D, TEMP, EXIT_POLICY_W = a.beam_width, a.max_depth, a.temperature, a.exit_policy_w
    EIV1_DIR.mkdir(parents=True, exist_ok=True)
    base = a.seed_base if a.seed_base is not None else \
        800000 + (EXIT_CORPUS.stat().st_size if EXIT_CORPUS.exists() else 0) % 400000
    mix = _resolve_opp_mix(a.opp_mix)
    tasks = []
    for i in range(a.games):
        seed = base + i
        r = random.Random(seed * 9176 + 12345)
        tasks.append((seed, r.choice(HEROES), r.choice(OPPS), _pick_opp_value(mix, r)))
    print(f"ExIt collect: {a.games} games | temp={TEMP} exit_policy_w={EXIT_POLICY_W} "
          f"| hero pool={len(HEROES)}", flush=True)
    t0 = time.time()
    rows = []
    with mp.Pool(a.workers) as pool:
        for r in pool.imap_unordered(_collect_game, tasks):
            if r:
                rows.extend(r)
    with open(EXIT_CORPUS, "a", encoding="utf-8") as f:
        for turn, sibs, y, hero, opp in rows:
            f.write(json.dumps({"turn": turn, "y": y, "hero": hero, "opp": opp,
                                "sibs": [[fv, sc] for fv, sc in sibs]}) + "\n")
    total = sum(1 for _ in open(EXIT_CORPUS)) if EXIT_CORPUS.exists() else 0
    n_sib = sum(len(s) for _, s, _, _, _ in rows)
    print(f"appended {len(rows)} 判断 ({n_sib} 兄弟手) ({time.time()-t0:.0f}s) "
          f"→ exit_corpus 総計 {total} 判断", flush=True)


if __name__ == "__main__":
    main()
