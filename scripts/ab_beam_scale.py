# -*- coding: utf-8 -*-
"""ExploitBeam の beam 幅/深さ scaling を per-AI ミラー A/B で測る (= ① 強化 knob)。

A(test) = ExploitBeam(beam_width=BW_A, max_depth=BD_A)。 B = 配備 ExploitBeam(16/10)。
両者とも同 deck・同 agnostic value(deck_slug 解決 → per-deck pkl 無し → agnostic fallback)。
= 「より広く/深い whole-turn 計画は 16/10 を超えるか」の直接測定。 deployment(人間相手=時間潤沢)は
推論 compute を払えるので、 幅 scaling に実 headroom がある(arena では遅いだけ)。

  BS_SLUG=cardrush_1454 BS_BW=24 BS_BD=12 BS_N=40 BS_WORKERS=8 .venv/bin/python scripts/ab_beam_scale.py

⚠ a_idx/fp を独立に振り first-player 交絡を除く。 ⚠ 幅を上げると遅い → N とワーカーに注意。
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

SLUG = os.environ.get("BS_SLUG", "cardrush_1454")
BW_A = int(os.environ.get("BS_BW", "24"))
BD_A = int(os.environ.get("BS_BD", "12"))
BW_B = int(os.environ.get("BS_BW_B", "16"))
BD_B = int(os.environ.get("BS_BD_B", "10"))


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO,
    )


def _beam(seed, bw, bd):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=bw, max_depth=bd,
                         deck_analysis={"deck_slug": SLUG})


def _one(seed):
    a_idx = seed % 2
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _beam(seed * 5 + 1, BW_A, BD_A)
    ais[1 - a_idx] = _beam(seed * 7 + 3, BW_B, BD_B)
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
    n = int(os.environ.get("BS_N", "40"))
    workers = int(os.environ.get("BS_WORKERS", "8"))
    seeds = list(range(4000, 4000 + n))
    t0 = time.time()
    print(f"[ab_beam_scale] {SLUG}  A({BW_A}/{BD_A}) vs B({BW_B}/{BD_B})  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    a = res.count("A"); b = res.count("B"); d = len(res) - a - b
    wr = a / max(1, a + b) * 100
    print(f"[ab_beam_scale] {SLUG}  A({BW_A}/{BD_A}) {a} - {b} B({BW_B}/{BD_B})  "
          f"draw/incomplete {d}  A_wr={wr:.1f}%  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
