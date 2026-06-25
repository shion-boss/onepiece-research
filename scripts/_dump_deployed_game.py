"""配備 ExploitBeam の1ゲームを verbose log で dump し、 精読で悪手/バグを探す(複利ループ検出step)。
control が aggro に負ける defense 局面を観察する。"""
import sys, random
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from scripts.deploy_counter import _mk_factory, _ana

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
OV = load_effect_overlay(ROOT / "db" / "card_effects.json")

def dl(s): return DeckList.from_json(ROOT / "decks" / f"{s}.json", REPO)

A, B = sys.argv[1] if len(sys.argv) > 1 else "cardrush_1385", sys.argv[2] if len(sys.argv) > 2 else "tcgportal_bonney"
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
rep = run_matchup(dl(A), dl(B), n_games=1, seed=seed, keep_logs=True,
                  ai_factory_1=_mk_factory(A, None, 16, 10), ai_factory_2=_mk_factory(B, None, 16, 10),
                  deck1_analysis=_ana(A), deck2_analysis=_ana(B), effects_overlay=OV)
g = rep.games[0]
print(f"=== {A}(P0) vs {B}(P1) seed={seed} | winner=P{g.winner} ===")
log = getattr(g, "log", []) or []
for line in log:
    print(line)
