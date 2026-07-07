# -*- coding: utf-8 -*-
"""配備 AI の誤りを rollout オラクルで自動検出(2026-07-07、 人間越えループの scale 本体)。

各競り合い局面(配備手 rollout 勝率 0.25-0.75 = decidable)で、 配備手 + 戦略候補手(全攻撃・全効果
発動・主要プレイ)を残りデッキ再シャッフルの paired rollout で評価 → 配備手より明確に良い手(Δ≥thr)
がある局面を「誤り」として記録。 = Claude が手を読まずとも、 rollout 真値で AI の suboptimal 手を自動発掘。
Claude は生成された誤り corpus の**パターン分析→蒸留(fix 化)**に集中する。

  .venv/bin/python scripts/scan_rollout_errors.py --games 20 --rollouts 14 --deck cardrush_1454 --opp tcgportal_calgara
出力: db/_analyst/rollout_errors.jsonl(各誤り: 局面render/配備手/最良手/Δ/種別)
"""
from __future__ import annotations
import argparse, json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone
# claude_pilot_poc の render を再利用
import scripts.claude_pilot_poc as PP

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _reshuffle(state, seed):
    r = random.Random(seed)
    for p in state.players:
        d = list(getattr(p, "deck", [])); r.shuffle(d); p.deck = d


def _rollout(state, action, hero, deck, opp):
    try:
        apply_action(state, action)
    except Exception:
        return 0.5
    steps = 0
    while not state.game_over and state.turn_number < 50 and steps < 400:
        cur = state.turn_player_idx
        dr = _mk(deck, 100 + cur) if cur == hero else _mk(opp, 200 + cur)
        try:
            play_one_action(state, dr, _mk(opp if cur == hero else deck, 300 + cur))
        except Exception:
            break
        steps += 1
    if not state.game_over:
        return 0.5
    w = getattr(state, "winner", -1)
    return 1.0 if w == hero else (0.0 if w == (1 - hero) else 0.5)


def _winrate(st, idx, hero, deck, opp, rollouts, seedb):
    w = 0.0
    for si in range(rollouts):
        b = fast_clone(st); _reshuffle(b, seedb + si)
        w += _rollout(b, legal_actions(b)[idx], hero, deck, opp)
    return w / rollouts


def _candidate_idxs(acts, dep_idx):
    """戦略的に意味ある候補 index(全攻撃・全効果発動・登場・配備手)。 過負荷回避で最大 7。"""
    cand = set()
    if dep_idx is not None:
        cand.add(dep_idx)
    for i, a in enumerate(acts):
        if isinstance(a, (AttackLeader, AttackCharacter, ActivateMain, PlayCharacter)):
            cand.add(i)
    cand = sorted(cand)
    return cand[:7]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1454")
    ap.add_argument("--opp", default="tcgportal_calgara")
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--rollouts", type=int, default=14)
    ap.add_argument("--thr", type=float, default=0.15)
    ap.add_argument("--seed-base", type=int, default=50000)
    ap.add_argument("--out", default="db/_analyst/rollout_errors.jsonl")
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fout = open(out, "a", encoding="utf-8")
    HERO = 0
    n_pos = n_err = 0
    for g in range(a.games):
        st = setup_game(_deck(a.deck), _deck(a.opp), rng=random.Random(a.seed_base + g),
                        first_player=g % 2, effects_overlay=_OVERLAY)
        play_until_main(st)
        ais = [_mk(a.deck, 555 + g), _mk(a.opp, 777 + g)]
        steps = 0
        while not st.game_over and st.turn_number < 50 and steps < 500:
            tp = st.turn_player_idx
            acts = legal_actions(st)
            if tp == HERO and st.turn_number >= 3 and len([x for x in acts if not isinstance(x, EndPhase)]) >= 4 and steps % 2 == 0:
                dep_idx = None
                try:
                    dep = ais[0].choose_action(fast_clone(st))
                    for i, aa in enumerate(acts):
                        if aa == dep: dep_idx = i; break
                except Exception:
                    pass
                if dep_idx is not None:
                    sb = 97 * (n_pos + 1) + a.seed_base
                    wdep = _winrate(fast_clone(st), dep_idx, HERO, a.deck, a.opp, a.rollouts, sb)
                    if 0.25 <= wdep <= 0.75:  # decidable のみ
                        n_pos += 1
                        best_idx, best_w = dep_idx, wdep
                        for ci in _candidate_idxs(acts, dep_idx):
                            if ci == dep_idx:
                                continue
                            wc = _winrate(fast_clone(st), ci, HERO, a.deck, a.opp, a.rollouts, sb)
                            if wc > best_w:
                                best_idx, best_w = ci, wc
                        if best_idx != dep_idx and best_w - wdep >= a.thr:
                            n_err += 1
                            rec = {"game": a.seed_base + g, "turn": st.turn_number,
                                   "deployed_move": PP.render_action(st, acts[dep_idx], 0),
                                   "best_move": PP.render_action(st, acts[best_idx], 0),
                                   "win_deployed": round(wdep, 3), "win_best": round(best_w, 3),
                                   "delta": round(best_w - wdep, 3),
                                   "render": PP.render_position(st, 0)}
                            fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
                            print(f"  [誤り {n_err}] t{st.turn_number} 配備 {wdep:.2f}[{rec['deployed_move']}] "
                                  f"→ 最良 {best_w:.2f}[{rec['best_move']}] Δ{best_w-wdep:+.2f}", flush=True)
            try:
                play_one_action(st, ais[tp], ais[1 - tp])
            except Exception:
                break
            steps += 1
        print(f"  game {g+1}/{a.games} 完了(累計 decidable {n_pos}, 誤り {n_err})", flush=True)
    fout.close()
    print(f"\n[done] decidable 局面 {n_pos}, 誤り検出 {n_err}(誤り率 {100*n_err/max(1,n_pos):.0f}%)-> {out}")


if __name__ == "__main__":
    main()
