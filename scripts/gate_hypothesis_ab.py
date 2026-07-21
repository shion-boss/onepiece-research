#!/usr/bin/env python3
"""archetype gate の前提『meta aggro deck は agnostic value で board_eval に回帰する』を直接検証。

背景 (2026-07-21): pros02 aggro デッキ (zoro/luffy_r/sabo/luffy_gb) は agnostic value で
board_eval に +3〜10pt 改善した = ExploitBeam の `_agnostic_gate_recovery=12` gate の前提
(『aggro は agnostic で回帰』、 [[project_deck_agnostic_value_selfplay]] Phase B、 旧 evidence)
の反例。 gate 緩和で全 pkl-less aggro デッキ (=ユーザーデッキ) を底上げできる可能性があるが、
gate はグローバル (全ユーザーデッキに影響) なので旧 evidence を meta deck で再現確認してから触る。

このスクリプトは各 deck の per-deck pkl を bypass し (deck_slug を渡さない = fallback 経路)、
2 arm を両 seat×多opp で比較:
  - board_eval: _use_agnostic_gbm=False (= 純 board_eval leaf、 gate ON の aggro 挙動と等価)
  - agnostic  : _use_agnostic_gbm=True + ONEPIECE_AGNOSTIC_GATE=0 (= agnostic 強制)

agnostic > board_eval が meta aggro でも成り立てば gate は過剰保守 (= 緩和候補)。
board_eval >= agnostic なら旧 evidence は今も真 (= gate 維持、 pros02 は特殊)。

  .venv/bin/python scripts/gate_hypothesis_ab.py --decks cardrush_1454,cardrush_1385 \
      --opps tcgportal_calgara,cardrush_1342 --n 24
"""
import argparse
import os
import sys
import time
import multiprocessing as mp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk_factory(arm, bw, bd):
    """arm='board' → board_eval fallback / arm='agn' → agnostic 強制。
    deck_slug を渡さない = per-deck pkl を解決させず fallback 経路に落とす (公平比較)。"""
    use_agn = (arm == "agn")

    def wrapped(rng, deck_analysis=None):
        # ⚠ deck_slug を空にしても _resolve_gbm_path は state.deck_slugs から per-deck pkl を
        # 拾ってしまう (run_matchup が state に slug を入れる)。 pkl を確実に bypass する為、
        # 存在しない slug を注入して per-deck 解決を外し、 fallback(board/agnostic)経路に落とす。
        da = {**(deck_analysis or {}), "deck_slug": "__pkl_bypass__"}
        ai = ExploitBeamAI(rng=rng, deck_analysis=da, beam_width=bw, max_depth=bd)
        ai._use_agnostic_gbm = use_agn
        return ai
    return wrapped


def _mk_opp_factory(slug, bw, bd):
    """相手は配備忠実 (per-deck pkl auto-load)。"""
    def aif(rng, deck_analysis=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             beam_width=bw, max_depth=bd)
    return aif


def _run(task):
    arm, deck, opp, n, seed, bw, bd = task
    # agnostic 強制のため gate 無効化 env をこの worker に set。
    if arm == "agn":
        os.environ["ONEPIECE_AGNOSTIC_GATE"] = "0"
    else:
        os.environ.pop("ONEPIECE_AGNOSTIC_GATE", None)
    rep1 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        n_games=n, seed=seed, ai_factory_1=_mk_factory(arm, bw, bd),
        ai_factory_2=_mk_opp_factory(opp, bw, bd),
        deck1_analysis=_ana(deck), deck2_analysis=_ana(opp), effects_overlay=_OVERLAY,
    )
    rep2 = run_matchup(
        DeckList.from_json(ROOT / "decks" / f"{opp}.json", _REPO),
        DeckList.from_json(ROOT / "decks" / f"{deck}.json", _REPO),
        n_games=n, seed=seed + 1, ai_factory_1=_mk_opp_factory(opp, bw, bd),
        ai_factory_2=_mk_factory(arm, bw, bd),
        deck1_analysis=_ana(opp), deck2_analysis=_ana(deck), effects_overlay=_OVERLAY,
    )
    dw = rep1.deck1_wins + rep2.deck2_wins
    ow = rep1.deck2_wins + rep2.deck1_wins
    dr = rep1.draws + rep2.draws
    return (arm, deck, opp, dw, ow, dr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", default="cardrush_1454,cardrush_1385,cardrush_1342")
    ap.add_argument("--opps", default="tcgportal_calgara,tcgportal_bonney")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--beam-width", type=int, default=8)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    decks = [s.strip() for s in a.decks.split(",")]
    opps = [s.strip() for s in a.opps.split(",")]
    tasks = [(arm, deck, opp, a.n, a.seed, a.beam_width, a.max_depth)
             for deck in decks for opp in opps for arm in ("board", "agn")]
    print(f"gate 前提検証: board_eval vs agnostic (pkl bypass) | decks={decks} opps={opps} "
          f"N={a.n}/seat x2 tasks={len(tasks)}", flush=True)
    t0 = time.time()
    with mp.Pool(min(a.workers, len(tasks))) as p:
        res = p.map(_run, tasks, chunksize=1)
    by = {}
    for arm, deck, opp, dw, ow, dr in res:
        by.setdefault((deck, arm), [0, 0, 0])
        by[(deck, arm)][0] += dw; by[(deck, arm)][1] += ow; by[(deck, arm)][2] += dr
    print(f"\n=== gate 前提: meta aggro で agnostic は回帰するか === ({time.time()-t0:.0f}s)")
    print(f"{'deck':22}{'board%':>9}{'agn%':>9}{'Δ(agn-board)':>14}")
    tot = {"board": [0, 0, 0], "agn": [0, 0, 0]}
    for deck in decks:
        wrs = {}
        for arm in ("board", "agn"):
            dw, ow, dr = by[(deck, arm)]
            wrs[arm] = dw / max(1, dw + ow + dr) * 100
            for i in range(3):
                tot[arm][i] += by[(deck, arm)][i]
        d = wrs["agn"] - wrs["board"]
        print(f"{deck:22}{wrs['board']:9.1f}{wrs['agn']:9.1f}{d:+14.1f}")
    ov = {arm: tot[arm][0] / max(1, sum(tot[arm])) * 100 for arm in ("board", "agn")}
    delta = ov["agn"] - ov["board"]
    print(f"{'OVERALL':22}{ov['board']:9.1f}{ov['agn']:9.1f}{delta:+14.1f}")
    print()
    if delta > 2:
        print(f"  → agnostic > board_eval で +{delta:.1f}pt = 旧evidence の反例。 gate 緩和候補 "
              f"(meta aggro でも agnostic 有効)")
    elif delta < -2:
        print(f"  → board_eval > agnostic で {delta:.1f}pt = 旧evidence 今も真。 gate 維持 "
              f"(pros02 は特殊ケース)")
    else:
        print(f"  → Δ={delta:+.1f}pt = ほぼ互角。 agnostic は no-harm (gate 緩和は低リスクだが gain 小)")


if __name__ == "__main__":
    main()
