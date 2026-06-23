# -*- coding: utf-8 -*-
"""Crocodile(1385) vs calgara の実プレイ精査 (打倒カルガラ campaign)。

配備 ExploitBeam で実際に Crocodile を回し、 (a) ActivateMain (= leader KO-own-char
cost-down) が どれだけ / どんな delta で 発火しているか、 (b) 1 敗北 game の Crocodile
ターン log を 出す。 「beam は null-gain cost-down を 避けるはず」 という理論を 実測で 検証。
"""
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import json
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
CH, TG = "cardrush_1385", "tcgportal_calgara"


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def aif_c(rng, deck_analysis=None):
    return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": CH})


def aif_t(rng, deck_analysis=None):
    return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": TG})


rep = run_matchup(
    DeckList.from_json(ROOT / "decks" / f"{CH}.json", REPO),
    DeckList.from_json(ROOT / "decks" / f"{TG}.json", REPO),
    n_games=6, seed=42, ai_factory_1=aif_c, ai_factory_2=aif_t,
    deck1_analysis=_ana(CH), deck2_analysis=_ana(TG),
    effects_overlay=OVERLAY, record_snapshots=True, keep_logs=True,
)

# Crocodile = player_idx 0 (deck_a). ActivateMain 集計 + delta 分布
print(f"=== {CH} vs {TG}: {rep.deck1_wins}-{rep.deck2_wins}-{rep.draws} ===")
am_deltas = []
act_counts = Counter()
for g in rep.games:
    aes = getattr(g, "action_evals", None) or []
    for e in aes:
        if e.get("player_idx") != 0:
            continue
        act_counts[e.get("action")] += 1
        if e.get("action") == "ActivateMain":
            am_deltas.append((g, e.get("turn"), e.get("delta")))
print("Crocodile action 種別:", dict(act_counts.most_common()))
print(f"Crocodile ActivateMain 発火 {len(am_deltas)} 回 (game別 delta):")
neg = [d for _, _, d in am_deltas if d is not None and d < 0]
print(f"  うち delta<0 (= 自陣不利化) : {len(neg)} 回  例: {sorted(neg)[:8]}")
print(f"  delta>=0 : {sum(1 for _,_,d in am_deltas if d is not None and d>=0)} 回")

# 1 敗北 game の Crocodile ターン log
print("\n=== 1 敗北 game の Crocodile (P0) ターン log ===")
for gi, g in enumerate(rep.games):
    if getattr(g, "winner", -1) == 0:
        continue  # Crocodile が勝った game は skip
    snaps = getattr(g, "snapshots", None) or []
    if not snaps:
        continue
    print(f"--- game#{gi} winner={g.winner} turns={g.turns} ---")
    for s in snaps:
        if s.get("turn_player_idx") != 0:
            continue
        line = s.get("log", "")
        if not line:
            continue
        p0 = s["players"][0]
        p1 = s["players"][1]
        be = s.get("board_eval")
        print(f"  T{s['turn']:>2} L{p0['life_count']}/{p1['life_count']} "
              f"F{len(p0.get('characters', []))}/{len(p1.get('characters', []))} "
              f"be={be if be is None else int(be)}  {line}")
    break
