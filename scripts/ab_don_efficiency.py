# -*- coding: utf-8 -*-
"""DON 有効活用 penalty (_don_efficiency_w) の paired A/B + 挙動計測。

HERO を OPP に対して戦わせ、 HERO の don_efficiency_w を ON(=W) / OFF(=0) で 同一 seed/席/先攻
で走らせて、 (1)HERO 勝率 (2)HERO の弱 body(≤2000)登場回数 を比較する。 弱 body 展開が
減り、 勝率が落ちなければ「DON を無駄な 2000 body に使わず集中/温存」 が効いた証拠。

  HERO_SLUG=user_f0cd3241f3b2 OPP_SLUG=cardrush_1392 DE_W=0.08 DE_N=80 DE_WORKERS=10 \
      .venv/bin/python scripts/ab_don_efficiency.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main, PlayCharacter
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

HERO = os.environ["HERO_SLUG"]
OPP = os.environ["OPP_SLUG"]
W = float(os.environ.get("DE_W", "0.08"))
WEAK = 2000


def _resolve(slug):
    # メタは decks/、 ユーザーは _resolve_decklist 経由 (user DB)
    p = REPO_ROOT / "decks" / f"{slug}.json"
    if p.exists():
        return make_deck_from_dict(json.loads(p.read_text(encoding="utf-8")), _REPO)
    from api.main import _resolve_decklist
    return _resolve_decklist(slug, "local")


def _beam(slug, seed, *, de_w):
    return ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": slug}, don_efficiency_w=de_w,
    )


def _play(seed, hero_idx, fp, *, de_w):
    """1 ゲーム走らせて (HERO勝ち?, HEROの弱body登場数) を返す。"""
    decks = [None, None]
    decks[hero_idx] = _resolve(HERO)
    decks[1 - hero_idx] = _resolve(OPP)
    state = setup_game(decks[0], decks[1], rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[hero_idx] = _beam(HERO, seed * 5 + 1, de_w=de_w)
    ais[1 - hero_idx] = _beam(OPP, seed * 7 + 3, de_w=0.0)
    weak_deploys = 0
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            act = play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        if cur == hero_idx and isinstance(act, PlayCharacter):
            card = getattr(act, "card", None)
            if card is not None and int(getattr(card, "power", 0) or 0) <= WEAK:
                weak_deploys += 1
        n += 1
    if not state.game_over:
        return (None, weak_deploys)
    return (getattr(state, "winner", -1) == hero_idx, weak_deploys)


def _one(seed):
    hero_idx = seed % 2
    fp = (seed // 2) % 2
    on_w, on_wd = _play(seed, hero_idx, fp, de_w=W)
    off_w, off_wd = _play(seed, hero_idx, fp, de_w=0.0)
    return (on_w, on_wd, off_w, off_wd)


def main():
    n = int(os.environ.get("DE_N", "80"))
    workers = int(os.environ.get("DE_WORKERS", "10"))
    seeds = list(range(3000, 3000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    on_win = sum(1 for r in res if r[0] is True)
    on_los = sum(1 for r in res if r[0] is False)
    off_win = sum(1 for r in res if r[2] is True)
    off_los = sum(1 for r in res if r[2] is False)
    on_wd = sum(r[1] for r in res) / max(1, len(res))
    off_wd = sum(r[3] for r in res) / max(1, len(res))
    flip_win = sum(1 for r in res if r[0] is True and r[2] is False)
    flip_los = sum(1 for r in res if r[0] is False and r[2] is True)
    print(f"HERO={HERO} OPP={OPP} W={W} N={n} ({time.time()-t0:.0f}s)")
    print(f"  弱body(≤{WEAK})登場/game:  ON={on_wd:.2f}  OFF={off_wd:.2f}  Δ={on_wd-off_wd:+.2f}")
    print(f"  HERO 勝率:  ON={on_win/max(1,on_win+on_los)*100:.1f}%  "
          f"OFF={off_win/max(1,off_win+off_los)*100:.1f}%  "
          f"Δ={on_win/max(1,on_win+on_los)*100-off_win/max(1,off_win+off_los)*100:+.1f}pt")
    print(f"  paired flips: ON勝/OFF負={flip_win}  ON負/OFF勝={flip_los}  net={flip_win-flip_los:+d}")


if __name__ == "__main__":
    main()
