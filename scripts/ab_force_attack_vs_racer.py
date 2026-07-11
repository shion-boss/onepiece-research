# -*- coding: utf-8 -*-
"""force-attack (ExploitBeam._offense_force_attack) を「罰する相手」に対して A/B 計測する。

⚠ 既存 scripts/ab_flag.py は **ミラー** (両側 ExploitBeam・同 deck) で計測する。 これは
   2026-06-13 に force-attack を **誤って無効化** した設定と同じ (= 両者消極なら passivity を
   罰せず、 手札を削れない弊害が出ない → force-attack が「効かない」ように見える)。
   [[feedback_ai_too_passive_attack_pressure]] / [[project_engine_search_levers_exhausted]]。

このスクリプトは hero (= ExploitBeam) を **攻撃的な仮想敵** (AggressiveRacerAI / greedy+顔優先、
または AggressiveBeamRacerAI / 強い) に当て、 hero の force-attack ON vs OFF を **同一 seed の
paired 比較** (= 分散低減) で測る。 「殴らないとレースで負ける」を相手が突くので、 force-attack の
価値 (= 相手 counter を強要・手札を削る圧) が測定に載る。

  AB_SLUG=tcgportal_bonney AB_N=60 AB_WORKERS=8 AB_OPP=racer \
      .venv/bin/python scripts/ab_force_attack_vs_racer.py

  AB_OPP: racer(既定, greedy+顔=高速) / beamracer(ExploitBeam+顔=強いが遅い)
"""
import sys, os, random, time
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.ai_experimental import AggressiveRacerAI, AggressiveBeamRacerAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ["AB_SLUG"]
OPP = os.environ.get("AB_OPP", "racer")


def _load():
    import json
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _hero(seed, *, force_attack: bool):
    ai = ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": SLUG},
    )
    ai._offense_force_attack = force_attack
    return ai


def _opp(seed):
    if OPP == "beamracer":
        return AggressiveBeamRacerAI(
            rng=random.Random(seed), beam_width=16, max_depth=10,
            deck_analysis={"deck_slug": SLUG},
        )
    return AggressiveRacerAI(rng=random.Random(seed))


def _play(hero, opp, hero_idx, seed, fp):
    """hero vs opp を 1 戦。 hero が勝てば True、 負け False、 未決着 None。"""
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[hero_idx] = hero
    ais[1 - hero_idx] = opp
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
    if w == hero_idx:
        return True
    if w == (1 - hero_idx):
        return False
    return None


def _one(seed):
    """同一 seed で ON/OFF を paired 実行。 hero 側と先攻は seed で balance。"""
    hero_idx = seed % 2          # hero がどちら側か (P0 優位の交絡除去)
    fp = (seed // 2) % 2         # 先攻 (hero_idx と独立)
    # ON / OFF で相手・初期状態を同一化 (paired) するため seed を固定して両方走らせる
    on = _play(_hero(seed * 5 + 1, force_attack=True), _opp(seed * 3 + 2),
               hero_idx, seed, fp)
    off = _play(_hero(seed * 5 + 1, force_attack=False), _opp(seed * 3 + 2),
                hero_idx, seed, fp)
    return (on, off)


def main():
    n = int(os.environ.get("AB_N", "60"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(2000, 2000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    on_w = sum(1 for on, off in res if on is True)
    on_l = sum(1 for on, off in res if on is False)
    off_w = sum(1 for on, off in res if off is True)
    off_l = sum(1 for on, off in res if off is False)
    on_wr = on_w / max(1, on_w + on_l) * 100
    off_wr = off_w / max(1, off_w + off_l) * 100
    # paired: 同一 seed で ON 勝ち / OFF 負け の差分
    on_only = sum(1 for on, off in res if on is True and off is False)
    off_only = sum(1 for on, off in res if off is True and on is False)
    print(f"{SLUG}  vs {OPP}  (N={n}, paired)")
    print(f"  force-attack ON : {on_w}-{on_l}  wr={on_wr:.0f}%")
    print(f"  force-attack OFF: {off_w}-{off_l}  wr={off_wr:.0f}%")
    print(f"  paired flips: ON-wins-where-OFF-loses={on_only}  OFF-wins-where-ON-loses={off_only}")
    print(f"  Δwr(ON-OFF) = {on_wr - off_wr:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
