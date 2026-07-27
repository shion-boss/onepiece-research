# -*- coding: utf-8 -*-
"""pros02 ドフラ理想線「最速 8/10ドフラ 着地」を scripted force して勝率を測る決定的検定 (2026-07-28)。

leaf bonus では大型展開を強制できなかった(beam が着地 line を枝刈り)ので、 AI をラップして
「8/10ドフラ が打てる(legal=affordable)なら即展開、 それ以外は配備 beam に委ねる」変種 A を作る。
paired 非ミラー: 同一 seed で A(強制)と B(baseline)を各々 field 相手と対戦 → hero 勝率比較。
上がれば AI は早期大型を過小評価(プロ正)/ 変わらねば AI 判断が正(プロ線は engine で過大)。

  CR_HERO=cardrush_1342 CR_N=160 CR_WORKERS=12 .venv/bin/python scripts/ab_force_bigdeploy.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, legal_actions, PlayCharacter
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("CR_HERO", "cardrush_1342")
BIG_CIDS = set((os.environ.get("CR_BIG", "OP14-069,OP10-071")).split(","))  # 10ドフラ, 8ドフラ
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1456", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_calgara", "tcgportal_coby"]
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


class ForceBigDeployBeam(ExploitBeamAI):
    """8/10ドフラ が legal(=affordable)なら即展開、 それ以外は配備 beam。"""
    def choose_action(self, state):
        me = state.players[state.turn_player_idx]
        best = None
        for a in legal_actions(state):
            if isinstance(a, PlayCharacter) and 0 <= getattr(a, "hand_idx", -1) < len(me.hand):
                c = me.hand[a.hand_idx]
                if getattr(c, "card_id", None) in BIG_CIDS:
                    cost = getattr(c, "cost", 0)
                    if best is None or cost > best[1]:
                        best = (a, cost)  # 10ドフラ を 8ドフラ より優先
        if best is not None:
            return best[0]
        return super().choose_action(state)


def _play(seed, opp, force):
    fp = seed % 2
    state = setup_game(_dl(HERO), _dl(opp), rng=random.Random(seed), first_player=fp,
                       effects_overlay=_OVERLAY)
    play_until_main(state)
    hero_idx = 0 if fp == 0 else 1
    opp_idx = 1 - hero_idx
    Cls = ForceBigDeployBeam if force else ExploitBeamAI
    hero_ai = Cls(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                  deck_analysis={"deck_slug": HERO})
    opp_ai = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                           deck_analysis={"deck_slug": opp})
    ais = [None, None]
    ais[hero_idx] = hero_ai
    ais[opp_idx] = opp_ai
    n = 0
    while not state.game_over and state.turn_number < 55 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    return "W" if getattr(state, "winner", -1) == hero_idx else "L"


def _one(seed):
    opp = random.Random(seed).choice(POOL)
    return (_play(seed, opp, True), _play(seed, opp, False))  # (force, baseline)


def main():
    n = int(os.environ.get("CR_N", "160"))
    workers = int(os.environ.get("CR_WORKERS", "12"))
    seeds = list(range(50000, 50000 + n))
    t0 = time.time()
    print(f"[ab_force_bigdeploy] hero={HERO} vs field  強制展開={BIG_CIDS}  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    fw = sum(1 for a, b in res if a == "W"); fl = sum(1 for a, b in res if a == "L")
    bw = sum(1 for a, b in res if b == "W"); bl = sum(1 for a, b in res if b == "L")
    wr_f = fw / max(1, fw + fl) * 100
    wr_b = bw / max(1, bw + bl) * 100
    print(f"[ab_force_bigdeploy] プロ線強制 hero勝率 {wr_f:.1f}% ({fw}-{fl})  |  "
          f"baseline hero勝率 {wr_b:.1f}% ({bw}-{bl})  |  Δ={wr_f-wr_b:+.1f}pt  ({time.time()-t0:.0f}s)",
          flush=True)


if __name__ == "__main__":
    main()
