# -*- coding: utf-8 -*-
"""人間モデル (HumanModelAI) を探索の仮想敵にすると配備 ExploitBeam が強くなるか A/B。

memory [[project_human_opponent_model]] の残タスク: 「探索が相手を GreedyAI と仮定して読む」
のが配備 AI の弱さの核心 → 人間 log から学んだ HumanModelAI (db/human_model.json) を
set_ai_opp で探索の仮想敵に差すと、 AI は「自分の攻撃はカウンターされる / 相手は顔を詰める」
と読むようになる。 これを A/B で検証し、 勝ち越せば ONEPIECE_HUMAN_OPP を配備 default に flip。

  hero-ON  = ExploitBeam + set_ai_opp(HumanModelAI)   (= 相手を人間モデルで読む)
  hero-OFF = ExploitBeam + set_ai_opp(GreedyAI)        (= 現配備 default)

同一 seed / deck / 先後 で paired 比較 (分散低減)。 seat も balance。

  AB_SLUG=cardrush_1342 AB_N=60 AB_WORKERS=8 AB_OPP=human \
      .venv/bin/python scripts/ab_human_opp_model.py

  AB_OPP: human(既定, HumanModelAI=人間proxy) / greedy(bot 回帰ガード) / beam(強bot ガード)
"""
import sys, os, random, time
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action, GreedyAI
from engine.exploit_beam_ai import ExploitBeamAI
from engine.human_model_ai import HumanModelAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

SLUG = os.environ["AB_SLUG"]
OPP = os.environ.get("AB_OPP", "human")


def _load():
    import json
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _hero(seed, *, human_opp: bool):
    da = {"deck_slug": SLUG}
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    # 探索の仮想敵を差し替え (env でなく直接 set → multiprocessing 安全)
    if human_opp:
        ai.set_ai_opp(HumanModelAI(rng=random.Random(seed + 11), deck_analysis=da))
    else:
        ai.set_ai_opp(GreedyAI(rng=random.Random(seed + 11), deck_analysis=da))
    return ai


def _opp(seed):
    da = {"deck_slug": SLUG}
    if OPP == "beam":
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if OPP == "beamracer":
        # 強い + 顔詰め = 強い人間ライク (天井を外す proxy)
        from engine.ai_experimental import AggressiveBeamRacerAI
        return AggressiveBeamRacerAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis=da)
    if OPP == "greedy":
        return GreedyAI(rng=random.Random(seed), deck_analysis=da)
    # human proxy: 人間 log から学んだ挙動 (顔詰め + counter 厚め)
    return HumanModelAI(rng=random.Random(seed), deck_analysis=da)


def _play(hero, opp, hero_idx, seed, fp):
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
    hero_idx = seed % 2
    fp = (seed // 2) % 2
    on = _play(_hero(seed * 5 + 1, human_opp=True), _opp(seed * 3 + 2), hero_idx, seed, fp)
    off = _play(_hero(seed * 5 + 1, human_opp=False), _opp(seed * 3 + 2), hero_idx, seed, fp)
    return (on, off)


def main():
    n = int(os.environ.get("AB_N", "60"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(3000, 3000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    on_w = sum(1 for on, off in res if on is True)
    on_l = sum(1 for on, off in res if on is False)
    off_w = sum(1 for on, off in res if off is True)
    off_l = sum(1 for on, off in res if off is False)
    on_wr = on_w / max(1, on_w + on_l) * 100
    off_wr = off_w / max(1, off_w + off_l) * 100
    on_only = sum(1 for on, off in res if on is True and off is False)
    off_only = sum(1 for on, off in res if off is True and on is False)
    print(f"{SLUG}  hero=ExploitBeam  vs {OPP}  (N={n}, paired)")
    print(f"  human-opp-model ON : {on_w}-{on_l}  wr={on_wr:.0f}%")
    print(f"  human-opp-model OFF: {off_w}-{off_l}  wr={off_wr:.0f}%  (= 現配備)")
    print(f"  paired flips: ON-wins/OFF-loses={on_only}  OFF-wins/ON-loses={off_only}")
    print(f"  Δwr(ON-OFF) = {on_wr - off_wr:+.1f}pt   ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
