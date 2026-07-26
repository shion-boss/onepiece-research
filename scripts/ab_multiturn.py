# -*- coding: utf-8 -*-
"""既存 multi-turn 探索 scaffold の強さを per-AI ミラー A/B で測る (= 新規探索コード0)。

A(test) = ExploitBeam に postopp_turns=MT_TURNS + opp_value/self_value/asym を set したもの。
B       = 配備 ExploitBeam (turns=1 = 現配備 baseline)。 両者同 deck ミラー。

= 「N ターン先読み(相手/自分を value 誘導で rollout)は 1-ply beam を超えるか」の直接測定。
  memory: multi-turn は「opp greedy strawman + self greedy が control 過小評価」で null だった。
  opp_value/self_value(後から追加)を載せた「改良版 multi-turn」が baseline を超えるかを検証。

  MT_SLUG=cardrush_1342 MT_TURNS=2 MT_OPP_VALUE=1 MT_SELF_VALUE=1 MT_N=60 MT_WORKERS=8 \
      .venv/bin/python scripts/ab_multiturn.py

⚠ first-player 優位交絡回避: a_idx (= A がどちら側) と fp (= 先攻) を独立に振る。
⚠ multi-turn は遅い (turns=2 + value rollout) → N=60 でも time がかかる。 background 推奨。
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

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ.get("MT_SLUG", "cardrush_1342")
TURNS = int(os.environ.get("MT_TURNS", "2"))
OPP_V = os.environ.get("MT_OPP_VALUE", "1") == "1"
SELF_V = os.environ.get("MT_SELF_VALUE", "1") == "1"
ASYM = os.environ.get("MT_ASYM", "0") == "1"


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _beam(seed, *, multiturn: bool):
    ai = ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": SLUG},
    )
    if multiturn:
        ai._postopp_turns = TURNS
        ai._postopp_opp_value = OPP_V
        ai._postopp_self_value = SELF_V
        ai._asym_multiturn = ASYM
    return ai


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, multiturn=True)
    ais[1 - a_idx] = _beam(seed * 7 + 3, multiturn=False)
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
    n = int(os.environ.get("MT_N", "60"))
    workers = int(os.environ.get("MT_WORKERS", "8"))
    seeds = list(range(2000, 2000 + n))
    t0 = time.time()
    cfg = f"turns={TURNS} opp_value={OPP_V} self_value={SELF_V} asym={ASYM}"
    print(f"[ab_multiturn] {SLUG}  A(multiturn: {cfg}) vs B(deployed turns=1)  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B"); d = len(res) - a - b
    wr = a / max(1, a + b) * 100
    print(f"[ab_multiturn] {SLUG}  A(multiturn) {a} - {b} B(deployed)  "
          f"draw/incomplete {d}  A_wr={wr:.1f}%  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
