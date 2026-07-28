# -*- coding: utf-8 -*-
"""rollout-value 教師データ収集 (2026-07-28、 条件(b) 蒸留)。

root-rollout が beam を超える([[project_rollout_beats_beam]])= value(win/loss ラベル + 21dim)が
bottleneck。 → value を「実 outcome ラベル(rollout-value)+ rich 特徴」で学習し直せば天井を破れるか。
各局面で候補手を打った後の state の rich 特徴 + その rollout-value(RO 回の実対局勝率)を教師行として出力。

  RV_N=200 RV_CAND=5 RV_RO=4 RV_WORKERS=12 RV_FEAT=v14 .venv/bin/python scripts/collect_rollout_value_data.py
出力: db/_selfplay/rollout_value_corpus.jsonl ({f:[rich], y:rollout_value, deck})
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone
from engine.gbm_value import features

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
OUT = ROOT / (os.environ.get("RV_OUT") or "db/_selfplay/rollout_value_corpus.jsonl")
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1456", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
CAND = int(os.environ.get("RV_CAND", "5"))
RO = int(os.environ.get("RV_RO", "4"))
TURN_CAP = int(os.environ.get("RV_TURN_CAP", "40"))
FEAT = os.environ.get("RV_FEAT", "v14")  # rich 特徴版
SAMPLE_EVERY = int(os.environ.get("RV_SAMPLE_EVERY", "2"))  # hero 手番の何回に1回サンプル
_DL = {}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _feat(state, me_idx):
    kw = {"rich": True}
    if FEAT:
        kw[FEAT] = True
    return [round(x, 5) for x in features(state, me_idx, **kw)]


def _mk(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


def _reshuffle(state, seed):
    r = random.Random(seed)
    for p in state.players:
        d = list(getattr(p, "deck", [])); r.shuffle(d); p.deck = d


def _rollout_outcomes(st, action, me_idx, hslug, oslug, base_seed):
    """action を打った後、 both 配備beam で TURN_CAP まで対局 → me の勝敗リスト(RO 個、 各 1/0、 draw除外)。"""
    outs = []
    for si in range(RO):
        b = fast_clone(st); _reshuffle(b, base_seed + si * 17)
        try:
            apply_action(b, legal_actions(b)[action])
        except Exception:
            continue
        dr = [None, None]
        dr[me_idx] = _mk(hslug, 900 + si); dr[1 - me_idx] = _mk(oslug, 950 + si)
        steps = 0
        while not b.game_over and b.turn_number < TURN_CAP and steps < 400:
            cur = b.turn_player_idx
            try:
                play_one_action(b, dr[cur], dr[1 - cur])
            except Exception:
                break
            steps += 1
        if b.game_over:
            ww = getattr(b, "winner", -1)
            if ww == me_idx:
                outs.append(1)
            elif ww == (1 - me_idx):
                outs.append(0)
    return outs


def _cands(acts):
    c = [i for i, a in enumerate(acts)
         if isinstance(a, (AttackLeader, AttackCharacter, ActivateMain, PlayCharacter))]
    return c[:CAND]


def _one(seed):
    rng = random.Random(seed)
    hslug, oslug = rng.sample(POOL, 2)
    fp = seed % 2
    state = setup_game(_dl(hslug), _dl(oslug), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    h_idx = 0 if fp == 0 else 1
    ais = [None, None]
    ais[h_idx] = _mk(hslug, seed * 5 + 1); ais[1 - h_idx] = _mk(oslug, seed * 7 + 3)
    rows = []
    n, hero_moves = 0, 0
    while not state.game_over and state.turn_number < 50 and n < 800:
        cur = state.turn_player_idx
        if cur == h_idx and state.phase.name == "MAIN":
            acts = legal_actions(state)
            cands = _cands(acts)
            if len(cands) >= 2 and hero_moves % SAMPLE_EVERY == 0:
                for ci in cands:
                    # 手を打った後の state の rich 特徴 + rollout 帰結(1 rollout = 1 binary label)
                    post = fast_clone(state)
                    try:
                        apply_action(post, legal_actions(post)[ci])
                    except Exception:
                        continue
                    f = _feat(post, h_idx)
                    outs = _rollout_outcomes(state, ci, h_idx, hslug, oslug, seed * 131 + ci * 17)
                    gid = f"{seed}_{hero_moves}_{ci}"  # 同一 (局面,手) の rollout は同 group(leak 防止)
                    for o in outs:
                        rows.append({"f": f, "y": o, "deck": hslug, "g": gid})
            hero_moves += 1
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return rows


def main():
    N = int(os.environ.get("RV_N", "200"))
    W = int(os.environ.get("RV_WORKERS", "12"))
    seeds = list(range(100000, 100000 + N))
    t0 = time.time()
    print(f"[collect_rollout_value] N={N} games, CAND={CAND} RO={RO} feat={FEAT}, workers={W}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(OUT, "w", encoding="utf-8") as fout, mp.Pool(W) as p:
        for i, rows in enumerate(p.imap_unordered(_one, seeds), 1):
            for r in rows:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(rows)
            if i % max(1, N // 20) == 0 or i == N:
                print(f"  {i}/{N} games, {total} samples, {time.time()-t0:.0f}s", flush=True)
    print(f"[collect_rollout_value] DONE {total} samples ({time.time()-t0:.0f}s) → {OUT}", flush=True)


if __name__ == "__main__":
    main()
