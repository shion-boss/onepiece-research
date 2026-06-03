"""pure_lookup 直接 A/B: GoalDirected(NEW spec) vs GoalDirected(OLD spec)。

ohtsuki 指摘 (2026-06-03): GoalDirectedAI を実践 (= spec=policy) で測るなら beam ではなく
pure_lookup (= spec argmax、 訓練と同モード) で eval すべき。 corpus も pure_lookup で収集済。
両側 pure_lookup の直接 mirror なので winrate >50% = NEW policy が OLD より強い (= 直接の答え)。
beam 不使用なので高速 (~beam の 30-50x)。
"""
from __future__ import annotations
import os
os.environ["ONEPIECE_PURE_LOOKUP"] = "1"   # ← 両 AI を spec argmax モードに (beam bypass)
import sys, json, time, random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.harness import run_matchup
from engine.goal_directed_ai import GoalDirectedAI

_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
NEW_DIR = REPO_ROOT / "decks"
OLD_DIR = REPO_ROOT / "db" / "spec_backups" / "pre_explore_20260603"

DECKS = ["cardrush_1342", "cardrush_1456", "tcgportal_op11_luffy", "cardrush_1392"]
N = int(os.environ.get("AB_N", "40"))
SEED = 42


def load_spec(d: Path, slug: str) -> dict:
    return json.loads((d / f"{slug}.target_v1.json").read_text(encoding="utf-8"))


def make_ai(spec: dict):
    def f(rng, deck_analysis=None):
        return GoalDirectedAI(rng=rng, deck_analysis=deck_analysis, target_spec=spec)
    return f


print("=== pure_lookup 直接 A/B: GoalDirected(NEW) vs GoalDirected(OLD)、 両側 spec-argmax ===")
print(f"PURE_LOOKUP={os.environ['ONEPIECE_PURE_LOOKUP']}  N={N}/deck  seed={SEED}", flush=True)
print(f"NEW=decks/  OLD=db/spec_backups/pre_explore_20260603/\n", flush=True)

overall = []
for slug in DECKS:
    deck = make_deck_from_dict(json.loads((NEW_DIR / f"{slug}.json").read_text(encoding="utf-8")), _REPO)
    ai_new = make_ai(load_spec(NEW_DIR, slug))
    ai_old = make_ai(load_spec(OLD_DIR, slug))
    rng_master = random.Random(SEED)
    new_w = old_w = draw = 0
    done = 0
    t0 = time.time()
    npairs = (N + 1) // 2
    for _ in range(npairs):
        sub = rng_master.randrange(2**31)
        pn = min(2, N - done)
        rep = run_matchup(deck, deck, n_games=pn, seed=sub,
                          ai_factory_1=ai_new, ai_factory_2=ai_old, time_limit_turns=40)
        for r in rep.games:
            if r.winner == 0:
                new_w += 1
            elif r.winner == 1:
                old_w += 1
            else:
                draw += 1
        done += pn
        if done % 10 == 0 or done == N:
            el = time.time() - t0
            wr = new_w / max(1, new_w + old_w)
            print(f"    {slug} {done}/{N}: NEW {new_w}W-{old_w}L D{draw} wr={wr:.3f} {el/done:.1f}s/g", flush=True)
    wr = new_w / max(1, new_w + old_w)
    dt = time.time() - t0
    print(f"  >>> {slug:24s}: NEW {new_w}W - OLD {old_w}L (D{draw})  NEW winrate={wr:.3f} ({(wr-0.5)*100:+.1f}pt)  [{dt:.0f}s]\n", flush=True)
    overall.append((slug, wr, new_w, old_w, draw))

print("=" * 64)
avg = sum(w for _, w, _, _, _ in overall) / max(1, len(overall))
for slug, wr, nw, ow, d in overall:
    print(f"  {slug:24s} NEW wr={wr:.3f} ({(wr-0.5)*100:+.1f}pt)  [{nw}-{ow}-{d}]")
print(f"  {'OVERALL NEW vs OLD':24s} wr={avg:.3f} ({(avg-0.5)*100:+.1f}pt)")
print("  (>50% = NEW(explore) policy が OLD(1201b74) より強い、 ~50% = 互角)")
