# -*- coding: utf-8 -*-
"""探索路線 最後の未検証形 = 「MCTS(賢い探索) + 現 GBM value」 vs 配備 beam(同 value) の A/B。

旧 IS-MCTS は「検証目標未達」で未 merge だったが **旧 value 前提**。 現 matchup-aware v6 GBM を
az_mcts.AZMcts の value_fn に刺し、 **value を固定して search だけを isolate** して beam と比較する。
= AlphaZero recipe(value-leaf MCTS + PUCT)が同 compute 予算で beam の fixed-width 探索を超えるか。

  A(test) = AZMcts(value_fn=現GBM, n_sim=MCTS_NSIM)。 B = 配備 ExploitBeam(_gbm_path 固定で同 value)。
  両者同 deck ミラー、 a_idx/fp を独立に振る。

  MCTS_SLUG=cardrush_1454 MCTS_GBM=db/value_gbm_cardrush_1454_pre_block.pkl \
      MCTS_NSIM=160 MCTS_N=24 MCTS_WORKERS=8 .venv/bin/python scripts/ab_mcts_vs_beam.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action, GreedyAI
from engine.exploit_beam_ai import ExploitBeamAI
from engine.az_mcts import AZMcts
from engine.gbm_value import _load, _model_pwin

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ.get("MCTS_SLUG", "cardrush_1454")
GBM_PATH = os.environ.get("MCTS_GBM", "db/value_gbm_cardrush_1454_pre_block.pkl")
N_SIM = int(os.environ.get("MCTS_NSIM", "160"))
_MODEL = _load(GBM_PATH)   # module-level → fork で worker に継承


def _load_deck():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO,
    )


class MctsGbmAI(GreedyAI):
    """choose_action = AZMcts(value_fn=GBM)。 choose_defense は GreedyAI 継承(beam と同条件)。"""

    def __init__(self, rng, n_sim):
        super().__init__(rng=rng)
        self._n_sim = n_sim

        def vfn(state, to_move):
            if getattr(state, "game_over", False):
                w = getattr(state, "winner", -1)
                return 1.0 if w == to_move else (0.0 if w == (1 - to_move) else 0.5)
            try:
                return _model_pwin(_MODEL, state, to_move)
            except Exception:
                return 0.5

        self._searcher = AZMcts(value_fn=vfn, defender_ai=GreedyAI(rng=rng), prior="boardeval")

    def choose_action(self, state):
        try:
            action, _ = self._searcher.search(state, self._n_sim)
            return action
        except Exception:
            return super().choose_action(state)


def _beam(seed):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": SLUG})
    ai._gbm_path = GBM_PATH   # 同 value を強制 (= search だけ isolate)
    return ai


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    state = setup_game(_load_deck(), _load_deck(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = MctsGbmAI(rng=random.Random(seed * 5 + 1), n_sim=N_SIM)
    ais[1 - a_idx] = _beam(seed * 7 + 3)
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    w = getattr(state, "winner", -1)
    if w == a_idx:
        return "A"
    if w == (1 - a_idx):
        return "B"
    return None


def main():
    n = int(os.environ.get("MCTS_N", "24"))
    workers = int(os.environ.get("MCTS_WORKERS", "8"))
    seeds = list(range(3000, 3000 + n))
    t0 = time.time()
    print(f"[ab_mcts] {SLUG}  A(MCTS n_sim={N_SIM}) vs B(beam 16/10)  value={GBM_PATH}  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B"); d = len(res) - a - b
    wr = a / max(1, a + b) * 100
    print(f"[ab_mcts] {SLUG}  A(MCTS) {a} - {b} B(beam)  draw/incomplete {d}  "
          f"A_wr={wr:.1f}%  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
