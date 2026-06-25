"""WS-A isolation: board_eval-only (両者 GBM 無効 = gbm_path="") で control vs bonney を
ONEPIECE_CONTROL_AWARE off/on で測り、 field_power soft-cap が piloting を改善するか切り分け。
GBM を使わないので「eval の効果」だけを見る(配備GBM 経路とは別の純粋テスト)。"""
import os, sys, multiprocessing as mp
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ONEPIECE_NN_DISABLE"] = "1"  # NN off → 線形 board_eval を強制

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
import json
def ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text()) if p.exists() else {}
def dl(s): return DeckList.from_json(ROOT / "decks" / f"{s}.json", REPO)

BW, BD, N = 16, 10, 20

def factory(slug):
    def aif(rng, deck_analysis=None):
        # gbm_path="" → _resolve_gbm_path が "" を返し env 未設定 = board_eval 強制
        return ExploitBeamAI(rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug},
                             gbm_path="", beam_width=BW, max_depth=BD)
    return aif

def measure(control, aggro):
    import random
    cw = g = 0
    for seat in ("cA", "tA"):
        if seat == "cA":
            rep = run_matchup(dl(control), dl(aggro), n_games=N, seed=42,
                              ai_factory_1=factory(control), ai_factory_2=factory(aggro),
                              deck1_analysis=ana(control), deck2_analysis=ana(aggro), effects_overlay=OV)
            cw += rep.deck1_wins
        else:
            rep = run_matchup(dl(aggro), dl(control), n_games=N, seed=142,
                              ai_factory_1=factory(aggro), ai_factory_2=factory(control),
                              deck1_analysis=ana(aggro), deck2_analysis=ana(control), effects_overlay=OV)
            cw += rep.deck2_wins
        g += N
    return cw, g

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", nargs="+", default=["cardrush_1385", "cardrush_1392", "cardrush_1342"],
                    help="勝率を測る側(=「control」スロット)。aggro no-harm 用に aggro deck を入れてもよい")
    ap.add_argument("--vs", default="tcgportal_bonney", help="対戦相手")
    _a = ap.parse_args()
    controls = _a.decks
    aggro = _a.vs
    for cond in ("OFF", "ON"):
        if cond == "ON":
            os.environ["ONEPIECE_CONTROL_AWARE"] = "1"
        else:
            os.environ.pop("ONEPIECE_CONTROL_AWARE", None)
        print(f"\n===== board_eval-only | CONTROL_AWARE={cond} | n={N}/seat beam={BW}/{BD} =====", flush=True)
        tc = tg = 0
        for c in controls:
            cw, g = measure(c, aggro)
            tc += cw; tg += g
            print(f"  {c:<22} control勝率 = {cw/g*100:5.1f}%  ({cw}/{g})", flush=True)
        print(f"  ---- 平均 = {tc/tg*100:5.1f}%  ({tc}/{tg}) ----", flush=True)
