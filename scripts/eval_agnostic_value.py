# -*- coding: utf-8 -*-
"""Phase B: deck非依存 GBM (db/value_gbm_agnostic.pkl) を per-deck pkl の無いデッキの
value に使うと board_eval より上手く回せるか、 per-side mirror A/B で検証。

A (test)    = 配備 ExploitBeam + `_use_agnostic_gbm=True` (= pkl 無し deck で agnostic GBM)。
B (control) = 配備 ExploitBeam (= 現挙動、 pkl 無し deck は board_eval/NN fallback)。

対象 = 学習に出ていない held-out デッキのうち **per-deck pkl が無いもの** (= 真のユーザーデッキ
模擬)。 agnostic GBM は train デッキでのみ学習済 (held-out 未学習) なので汎化の実検証になる。

  AG_N=100 AG_WORKERS=8 .venv/bin/python scripts/eval_agnostic_value.py
"""
import os, sys, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
_DECK_CACHE = {}


def _deck(slug):
    if slug not in _DECK_CACHE:
        _DECK_CACHE[slug] = json.loads(
            (REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    return _DECK_CACHE[slug]


def _load(slug):
    return make_deck_from_dict(_deck(slug), _REPO)


def _beam(seed, slug, *, agnostic):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": slug})
    ai._use_agnostic_gbm = agnostic
    return ai


def _one(task):
    seed, slug = task
    a_idx = seed % 2          # A (test=agnostic) がどちら側か
    fp = (seed // 2) % 2
    state = setup_game(_load(slug), _load(slug), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, slug, agnostic=True)
    ais[1 - a_idx] = _beam(seed * 7 + 3, slug, agnostic=False)
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return (slug, None)
    w = getattr(state, "winner", -1)
    return (slug, "A" if w == a_idx else ("B" if w == (1 - a_idx) else None))


def _held_pklless():
    pool = sorted(p.stem for p in (REPO_ROOT / "decks").glob("cardrush_*.json")
                  if ".analysis" not in p.name and ".target" not in p.name)
    rng = random.Random(42)
    rng.shuffle(pool)
    n_held = max(6, len(pool) // 5)
    return [s for s in pool[:n_held]
            if not (REPO_ROOT / "db" / f"value_gbm_{s}.pkl").exists()]


def main():
    n = int(os.environ.get("AG_N", "100"))
    workers = int(os.environ.get("AG_WORKERS", "8"))
    only = os.environ.get("AG_DECKS")
    held = only.split(",") if only else _held_pklless()
    print(f"held-out pkl-less decks (A=agnostic GBM vs B=board_eval, N={n}/deck): {held}")
    tasks = [(1000 + i, s) for s in held for i in range(n)]
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, tasks, chunksize=8)
    per = defaultdict(lambda: [0, 0, 0])
    for slug, r in res:
        per[slug][0 if r == "A" else 1 if r == "B" else 2] += 1
    tA = tB = 0
    print(f"  {'deck':<18}{'A-B':>10}{'A_wr%':>7}")
    for slug in held:
        a, b, d = per[slug]
        tA += a; tB += b
        print(f"  {slug:<18}{a:>4}-{b:<4}{a/max(1,a+b)*100:>6.0f}%")
    print(f"  {'AGGREGATE':<18}{tA:>4}-{tB:<4}{tA/max(1,tA+tB)*100:>6.0f}%  ({time.time()-t0:.0f}s)")
    print("判定: A_wr > 50% (回帰なし) なら deck非依存 GBM が board_eval を超え、 user deck の value 問題に実弾解")


if __name__ == "__main__":
    main()
