# -*- coding: utf-8 -*-
import sys, os, random, time
os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, os.getcwd())
import json
from pathlib import Path
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.value_policy_ai import ValuePolicyAI
ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
VAL = os.environ.get("VP", "db/_selfplay/rl_value0.pkl")
FK = {"rich": True, "v19": True}
_dl = lambda s: make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text()), _REPO)
st = setup_game(_dl("cardrush_1385"), _dl("cardrush_1385"), rng=random.Random(3), first_player=0, effects_overlay=_OV)
play_until_main(st)
A = ValuePolicyAI(VAL, feat_kwargs=FK, rng=random.Random(11), deck_analysis={"deck_slug": "cardrush_1385"})
B = ExploitBeamAI(rng=random.Random(13), beam_width=16, max_depth=10, deck_analysis={"deck_slug": "cardrush_1385"})
ais = [A, B]  # P0=value-policy
n, last, t0 = 0, -1, time.time()
while not st.game_over and st.turn_number < 60 and n < 2000:
    if st.turn_number != last:
        last = st.turn_number
        p0, p1 = st.players[0], st.players[1]
        print(f"T{st.turn_number} 手番P{st.turn_player_idx} | P0(vp)ライフ{len(p0.life)}/盤{len(p0.characters)}/手{len(p0.hand)}/DON{p0.don_active}"
              f" P1(EBV2)ライフ{len(p1.life)}/盤{len(p1.characters)} | {time.time()-t0:.0f}s", flush=True)
    play_one_action(st, ais[st.turn_player_idx], ais[1 - st.turn_player_idx]); n += 1
print(f"=== game_over={st.game_over} turn={st.turn_number} winner={getattr(st,'winner',-1)}(0=vp) actions={n} ===")
