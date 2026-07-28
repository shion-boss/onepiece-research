# -*- coding: utf-8 -*-
"""RL ループ: value-policy(新) vs 現best の勝率 gate (2026-07-28)。

新 value-policy が現best(EBV2 or 旧 value-policy)を超えるか。 先攻/side を相殺、 多デッキ pool。
> 50% で昇格。 OMP_NUM_THREADS=1 で thread oversubscription 回避(必須)。

  AR_NEW=db/_selfplay/rl_value0.pkl AR_BEST=ebv2 AR_FEAT=v19 AR_N=160 AR_WORKERS=12 \
      .venv/bin/python scripts/arena_policy.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.value_policy_ai import ValuePolicyAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
NEW = os.environ.get("AR_NEW", "db/_selfplay/rl_value0.pkl")
BEST = os.environ.get("AR_BEST", "ebv2")
FEAT = os.environ.get("AR_FEAT", "v19")
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1456", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_DL = {}
_FEATKW = {"rich": True, FEAT: True} if FEAT else {"rich": True}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _mk(spec, seed, slug):
    if spec == "ebv2":
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})
    return ValuePolicyAI(spec, feat_kwargs=_FEATKW, rng=random.Random(seed), deck_analysis={"deck_slug": slug})


def _one(seed):
    r = random.Random(seed)
    d1, d2 = r.sample(POOL, 2)      # 非ミラー field(汎用性)
    new_p0 = (seed % 2 == 0)       # 新policy の side を相殺
    fp = (seed // 2) % 2
    hslug, oslug = (d1, d2)
    state = setup_game(_dl(hslug), _dl(oslug), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    # setup は先攻を index0 に。 hslug=deck1 は fp==0→idx0 / fp==1→idx1
    h_idx = 0 if fp == 0 else 1
    new_idx = h_idx if new_p0 else (1 - h_idx)
    ais = [None, None]
    ais[new_idx] = _mk(NEW, seed * 5 + 1, hslug if new_idx == h_idx else oslug)
    ais[1 - new_idx] = _mk(BEST, seed * 7 + 3, oslug if new_idx == h_idx else hslug)
    n = 0
    while not state.game_over and state.turn_number < 45 and n < 700:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    return 1 if getattr(state, "winner", -1) == new_idx else 0


def main():
    n = int(os.environ.get("AR_N", "160"))
    W = int(os.environ.get("AR_WORKERS", "12"))
    seeds = list(range(400000, 400000 + n))
    t0 = time.time()
    print(f"[arena_policy] NEW={Path(NEW).name} vs BEST={BEST}  feat={FEAT} N={n}", flush=True)
    with mp.Pool(W) as p:
        res = [x for x in p.map(_one, seeds) if x is not None]
    w = sum(res); tot = len(res)
    wr = w / max(1, tot) * 100
    import math
    se = math.sqrt(max(wr / 100 * (1 - wr / 100), 1e-9) / max(1, tot)) * 100
    print(f"[arena_policy] 新 value-policy 勝率 {wr:.1f}% ± {se:.1f} ({w}/{tot})  "
          f"{'✅昇格' if wr - se > 50 else ('△微妙' if wr > 48 else '✗')}  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
