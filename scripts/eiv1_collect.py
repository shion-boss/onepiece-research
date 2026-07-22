"""EIV1 self-play データ収集 → 永続 append-only corpus (2026-07-23)。

hero = ExploitBeam(EIV1 value or agnostic fallback) + ε探索 (探索ノイズ)、 opp = EBV2(agnostic)。
各 hero MAIN 局面の eiv1_features を記録、 終局 outcome (0/1) でラベル → db/eiv1/corpus.jsonl に APPEND。

= EIV1 の②永続 corpus + ⑤フライホイールの"データ生成"側 (自分側=beam+学習value+探索、 相手=EBV2)。
「回せば貯まる」器。 rollout target(④)は現状 outcome ラベル (拡張点=--rollout-n で後日)。

  .venv/bin/python scripts/eiv1_collect.py --games 40 --workers 12
    [--hero cardrush_1454] [--opps a,b,c] [--epsilon 0.15]
"""
from __future__ import annotations
import argparse
import json
import random
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
from engine.eiv1_features import eiv1_features
from engine.card_embed import per_card_snapshot

_REPO = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
_OVERLAY = load_effect_overlay(str(ROOT / "db" / "card_effects.json"))
EIV1_DIR = ROOT / "db" / "eiv1"
CORPUS = EIV1_DIR / "corpus.jsonl"
AGNOSTIC = str(ROOT / "db" / "value_gbm_agnostic.pkl")
EIV1_VALUE = ROOT / "db" / "eiv1" / "value.pkl"

# module-global (worker が fork で継承)
HERO = "cardrush_1454"
OPPS = ["cardrush_1385", "tcgportal_calgara", "tcgportal_bonney", "cardrush_1399"]
EPSILON = 0.15
BEAM_W, BEAM_D = 8, 6


def _dl(slug: str) -> DeckList:
    return DeckList.from_json(str(ROOT / "decks" / f"{slug}.json"), _REPO)


def _ana(slug: str) -> dict:
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class _ExploreBeam(ExploitBeamAI):
    """ExploitBeam + ε探索 (= 探索ノイズ)。 hero(学習側)用。"""

    def __init__(self, *a, epsilon=0.0, **k):
        super().__init__(*a, **k)
        self._epsilon = epsilon

    def choose_action(self, state):
        rng = self.rng or random
        if self._epsilon > 0 and rng.random() < self._epsilon:
            acts = legal_actions(state)
            if acts:
                return rng.choice(acts)
        return super().choose_action(state)


def _hero_value_path() -> str:
    """EIV1 value があればそれ、 無ければ agnostic に degrade (iter0)。"""
    return str(EIV1_VALUE) if EIV1_VALUE.exists() else AGNOSTIC


def _collect_game(task):
    seed, opp = task
    fp = seed % 2
    hero_first = (seed % 2 == 0)
    if hero_first:
        st = setup_game(_dl(HERO), _dl(opp), rng=random.Random(seed), first_player=0,
                        effects_overlay=_OVERLAY, deck1_analysis=_ana(HERO), deck2_analysis=_ana(opp))
        hero_idx = 0
    else:
        st = setup_game(_dl(opp), _dl(HERO), rng=random.Random(seed), first_player=0,
                        effects_overlay=_OVERLAY, deck1_analysis=_ana(opp), deck2_analysis=_ana(HERO))
        hero_idx = 1
    play_until_main(st)
    ais = [None, None]
    # hero = EIV1 value (or agnostic) + ε探索
    ais[hero_idx] = _ExploreBeam(rng=random.Random(seed * 3 + 1),
                                 deck_analysis={**_ana(HERO), "deck_slug": HERO},
                                 gbm_path=_hero_value_path(), beam_width=BEAM_W, max_depth=BEAM_D,
                                 epsilon=EPSILON)
    # opp = EBV2 (agnostic)
    ais[1 - hero_idx] = ExploitBeamAI(rng=random.Random(seed * 5 + 2),
                                      deck_analysis={**_ana(opp), "deck_slug": opp},
                                      gbm_path=AGNOSTIC, beam_width=BEAM_W, max_depth=BEAM_D)
    for i, x in enumerate(ais):
        if hasattr(x, "set_ai_opp"):
            x.set_ai_opp(ais[1 - i])
    rows, seen = [], set()  # rows = (v15_features, per_card_snapshot) の対
    n = 0
    while not st.game_over and st.turn_number < 60 and n < 800:
        cur = st.turn_player_idx
        if cur == hero_idx and st.phase == Phase.MAIN and st.turn_number not in seen:
            seen.add(st.turn_number)
            try:
                fv = eiv1_features(st, hero_idx)       # v15 集計 (GBM が使う)
                snap = per_card_snapshot(st, hero_idx)  # per-card 生 (identity NN 用、 育てば使う)
                rows.append((fv, snap))
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
    return [(fv, y, opp, snap) for fv, snap in rows]


def main():
    global HERO, OPPS, EPSILON, BEAM_W, BEAM_D
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero", default=HERO)
    ap.add_argument("--opps", default=",".join(OPPS))
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--epsilon", type=float, default=EPSILON)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--seed-base", type=int, default=None)
    ap.add_argument("--beam-width", type=int, default=BEAM_W)
    ap.add_argument("--max-depth", type=int, default=BEAM_D)
    a = ap.parse_args()
    HERO, OPPS, EPSILON = a.hero, a.opps.split(","), a.epsilon
    BEAM_W, BEAM_D = a.beam_width, a.max_depth
    EIV1_DIR.mkdir(parents=True, exist_ok=True)
    # seed-base: 既存 corpus 行数からずらして重複を避ける (毎日足しても別ゲーム)
    base = a.seed_base
    if base is None:
        base = 700000 + (CORPUS.stat().st_size if CORPUS.exists() else 0) % 500000
    tasks = [(base + i, OPPS[i % len(OPPS)]) for i in range(a.games)]
    print(f"EIV1 collect: hero={HERO} vs {OPPS} | games={a.games} eps={EPSILON} "
          f"beam={BEAM_W}/{BEAM_D} | value={'EIV1' if EIV1_VALUE.exists() else 'agnostic(iter0)'}",
          flush=True)
    t0 = time.time()
    with mp.Pool(a.workers) as pool:
        results = pool.map(_collect_game, tasks)
    rows, n_games = [], 0
    for r in results:
        if r:
            n_games += 1
            rows.extend(r)
    with open(CORPUS, "a", encoding="utf-8") as f:
        for fv, y, opp, snap in rows:
            # f = v15 集計特徴 (GBM 学習が使う) / cards = per-card 生 (将来の identity NN 用、 再収集不要に)
            f.write(json.dumps({"f": fv, "y": y, "opp": opp, "cards": snap}) + "\n")
    total = sum(1 for _ in open(CORPUS)) if CORPUS.exists() else 0
    print(f"appended {len(rows)} samples from {n_games}/{a.games} games "
          f"({time.time()-t0:.0f}s) → corpus 総計 {total} samples", flush=True)


if __name__ == "__main__":
    main()
