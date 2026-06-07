"""デッキの核コンボを配備 AI がどれだけ実行しているか測定する (= 手の質の定量、 全デッキ汎用の足場)。

現状は calgara のリーダー【アタック時】summon (= 手札から登場) を例に、 配備 AI (ExploitBeam) の
実行頻度を測る。 ⚠ 効果は「アタック宣言時」 に発火し log 上は atk 行の前に出るため、 attack イベント
frame に紐づけず **全 frame の効果ログ総数** を数えるのが正しい (= 窓ベース紐付けは取りこぼす、 教訓)。

usage: .venv/bin/python scripts/measure_combo_execution.py [opp_slug] [n_games]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.harness import run_matchup  # noqa: E402
from engine.smart_opponent_ai import SmartOpponentAI  # noqa: E402

CAL = "tcgportal_calgara"
OPP = sys.argv[1] if len(sys.argv) > 1 else "cardrush_1455"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20
SUMMON_LOG = "手札から登場"  # calgara リーダーの summon 効果ログ

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
da = DeckList.from_json(ROOT / "decks" / f"{CAL}.json", repo)
db = DeckList.from_json(ROOT / "decks" / f"{OPP}.json", repo)


def aif1(rng, deck_analysis=None):
    return SmartOpponentAI(rng=rng, deck_analysis=deck_analysis, deck_slug=CAL)


def aif2(rng, deck_analysis=None):
    return SmartOpponentAI(rng=rng, deck_analysis=deck_analysis, deck_slug=OPP)


kw = dict(n_games=N, seed=5, effects_overlay=overlay, ai_factory_1=aif1, ai_factory_2=aif2,
          keep_logs=False, enforce_rules=False, record_snapshots=True)
for sl, key in ((CAL, "deck1_analysis"), (OPP, "deck2_analysis")):
    ap = ROOT / "decks" / f"{sl}.analysis.json"
    if ap.exists():
        kw[key] = json.loads(ap.read_text(encoding="utf-8"))

rep = run_matchup(da, db, **kw)
summons = 0
leader_atks = 0
for g in rep.games:
    snaps = g.snapshots or []
    if not snaps:
        continue
    lid = snaps[0]["players"][0]["leader"]["instance_id"]
    for s in snaps:
        summons += (s.get("log") or "").count(SUMMON_LOG)
        ev = s.get("event")
        if ev and ev.get("attacker_iid") == lid and ev.get("type") == "attack":
            leader_atks += 1

print(f"=== calgara コンボ実行測定 (vs {OPP}, N={N}, 配備 ExploitBeam) ===")
print(f"リーダー summon 発火 (手札から登場): {summons}  ({summons / N:.2f}/試合)")
print(f"リーダー attack 回数: {leader_atks}  ({leader_atks / N:.2f}/試合)")
print(f"calgara winrate={rep.deck1_winrate:.2f}")
print("→ summon が毎試合 複数回 発火していれば、 配備 AI は核コンボを search+value で実行できている。")
