# -*- coding: utf-8 -*-
"""counter-event 守備評価 (_counter_event_def) の 非ミラー paired A/B。

HERO_SLUG (= flag を振る側) を OPP_SLUG に対して戦わせ、 HERO の flag を ON にした
ゲームと OFF にしたゲームを **同一 seed / 同一席 / 同一先攻** で走らせて HERO 勝率を比較。
同一 seed + 同一相手 = 完全 paired なので flag が決定を変えた所だけゲームが分岐する。

HERO を 0-counter-event デッキ (= hancock/coby) にすると flag は「相手 (エネル等) の
counter-event 守備をどれだけ見積もるか」だけを変える = 攻撃側 over-commit 抑制の純効果を測れる。

  HERO_SLUG=tcgportal_hancock OPP_SLUG=cardrush_1454 CE_N=120 CE_WORKERS=10 \
      .venv/bin/python scripts/ab_counter_event_def.py

⚠ 先攻/席の交絡を避け、 seed で HERO の席 (P0/P1) と先攻を独立に振る。 N≥100 推奨。
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")

HERO = os.environ["HERO_SLUG"]
OPP = os.environ["OPP_SLUG"]


def _load(slug):
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")),
        _REPO,
    )


def _beam(slug, seed, *, ce_def: bool):
    return ExploitBeamAI(
        rng=random.Random(seed), beam_width=16, max_depth=10,
        deck_analysis={"deck_slug": slug}, counter_event_def=ce_def,
    )


def _play(seed, hero_idx, fp, *, ce_def: bool):
    """1 ゲーム走らせて HERO が勝ったか (True/False/None=draw/incomplete)。"""
    decks = [None, None]
    decks[hero_idx] = _load(HERO)
    decks[1 - hero_idx] = _load(OPP)
    state = setup_game(decks[0], decks[1], rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[hero_idx] = _beam(HERO, seed * 5 + 1, ce_def=ce_def)
    ais[1 - hero_idx] = _beam(OPP, seed * 7 + 3, ce_def=False)  # 相手は常に baseline
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
    hero_idx = seed % 2         # HERO の席
    fp = (seed // 2) % 2        # 先攻 (席と独立)
    on = _play(seed, hero_idx, fp, ce_def=True)
    off = _play(seed, hero_idx, fp, ce_def=False)
    return (on, off)


def main():
    n = int(os.environ.get("CE_N", "120"))
    workers = int(os.environ.get("CE_WORKERS", "10"))
    seeds = list(range(2000, 2000 + n))
    t0 = time.time()
    with mp.Pool(workers) as p:
        res = p.map(_one, seeds)
    on_w = sum(1 for on, off in res if on is True)
    on_l = sum(1 for on, off in res if on is False)
    off_w = sum(1 for on, off in res if off is True)
    off_l = sum(1 for on, off in res if off is False)
    # paired: 同一 seed で ON 勝ち/OFF 負け (flag が勝ちに変えた) と その逆
    flipped_to_win = sum(1 for on, off in res if on is True and off is False)
    flipped_to_loss = sum(1 for on, off in res if on is False and off is True)
    wr_on = on_w / max(1, on_w + on_l) * 100
    wr_off = off_w / max(1, off_w + off_l) * 100
    print(f"HERO={HERO}  OPP={OPP}  N={n}  ({time.time()-t0:.0f}s)")
    print(f"  HERO winrate:  ON(flag)={wr_on:.1f}%  OFF(base)={wr_off:.1f}%  Δ={wr_on-wr_off:+.1f}pt")
    print(f"  paired flips:  ON勝/OFF負={flipped_to_win}  ON負/OFF勝={flipped_to_loss}  "
          f"net={flipped_to_win-flipped_to_loss:+d}")


if __name__ == "__main__":
    main()
