# -*- coding: utf-8 -*-
"""play-timing policy PRIOR の per-side mirror A/B + 効果活用率 計測。

A (under test) = 配備 ExploitBeam + `_play_prior_w = W` (= overlay 条件由来の play-timing prior)。
B (deployed)   = 配備 ExploitBeam (= W=0、 現挙動)。 両者とも deck の GBM を auto-load。

W は **P(win) 単位** (= 「この手を beam に残すために何 pt の勝率を上乗せするか」)。 plan_search が
GBM scale (×1e6) に変換する。 sweep して keep/revert を measured で判定する ([[project_combo_aware_ai]])。

同時に **効果活用率** を計測 (= 手の質、 docs/HUMAN_LEVEL_AI_PLAN §5 の通過判定):
各 MAIN 決定で「条件付き効果を持つ札を play/activate したか (gated)」 と「その条件が今 live だったか
(live)」 を choice 時 state で数える (= choose_action は clone 探索なので state は未適用)。
prior ON 側の live/gated が OFF 側より上がれば「効果を活かす手を選べている」 証拠。

⚠ first-player 優位の交絡を避け a_idx と fp を独立に振る (ab_flag.py と同様)。 N≥80 推奨。

  PP_SLUG=cardrush_1439 PP_WS=0.02,0.05,0.1 PP_N=100 PP_WORKERS=8 \
      .venv/bin/python scripts/eval_play_prior.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.deck_play_prior import count_conditional

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ.get("PP_SLUG", "cardrush_1439")
WS = [float(x) for x in os.environ.get("PP_WS", "0.02,0.05,0.1").split(",")]


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


class _RecBeam(ExploitBeamAI):
    """choose_action 時に「条件付き play/activate の gated/live」 を累積する計測用 beam。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cg = 0  # gated: 条件付き効果を持つ札を選んだ回数 (= eligible)
        self.cl = 0  # live : そのうち条件が今 満たされていた回数

    def choose_action(self, state):
        action = super().choose_action(state)  # clone 探索 → state は未適用 (= choice 時)
        try:
            g, l = count_conditional(state, action, state.turn_player_idx)
            self.cg += g
            self.cl += l
        except Exception:
            pass
        return action


def _beam(seed, *, w):
    ai = _RecBeam(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": SLUG},
    )
    ai._play_prior_w = float(w)  # 0.0 = 無効 (= 配備挙動)
    return ai


def _one(task):
    seed, w = task
    a_idx = seed % 2          # A (test, prior=w) がどちら側か
    fp = (seed // 2) % 2      # 先攻 (a_idx と独立)
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, w=w)        # A = prior ON
    ais[1 - a_idx] = _beam(seed * 7 + 3, w=0.0)  # B = deployed
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        res = None
    else:
        w_ = getattr(state, "winner", -1)
        res = "A" if w_ == a_idx else ("B" if w_ == (1 - a_idx) else None)
    A, B = ais[a_idx], ais[1 - a_idx]
    return (res, A.cg, A.cl, B.cg, B.cl)


def main():
    n = int(os.environ.get("PP_N", "100"))
    workers = int(os.environ.get("PP_WORKERS", "8"))
    print(f"deck={SLUG}  N={n}/W  Ws={WS}  (A=prior ON  B=deployed)")
    print(f"{'W':>6} | {'A-B':>9} {'draw':>4} {'A_wr%':>6} | "
          f"{'A live/gated':>16} {'B live/gated':>16}")
    print("-" * 78)
    seed0 = int(os.environ.get("PP_SEED0", "1000"))  # 独立検証用に seed 範囲をずらす
    for w in WS:
        seeds = [(s, w) for s in range(seed0, seed0 + n)]
        t0 = time.time()
        with mp.Pool(workers) as p:
            res = p.map(_one, seeds)
        a = sum(1 for r in res if r[0] == "A")
        b = sum(1 for r in res if r[0] == "B")
        d = len(res) - a - b
        wr = a / max(1, a + b) * 100
        acg = sum(r[1] for r in res); acl = sum(r[2] for r in res)
        bcg = sum(r[3] for r in res); bcl = sum(r[4] for r in res)
        a_rate = (acl / acg * 100) if acg else 0.0
        b_rate = (bcl / bcg * 100) if bcg else 0.0
        print(f"{w:>6.3f} | {a:>3}-{b:<3}    {d:>4} {wr:>5.0f}% | "
              f"{acl:>4}/{acg:<4}={a_rate:>3.0f}% {bcl:>4}/{bcg:<4}={b_rate:>3.0f}%  "
              f"({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
