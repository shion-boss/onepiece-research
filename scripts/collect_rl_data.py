# -*- coding: utf-8 -*-
"""RL ループ: rollout 教師データ収集 (2026-07-28、 proper 版)。

現best AI が self-play → hero 決定点で候補手を faithful rollout(downstream=現best)評価 →
(rich 特徴 v19 of post-action state, 割引 rollout-value γ^手数, group)を教師行に。
DAgger: RL_CB=<value pkl> で現best を value-policy にすれば「生徒自身の分布」で収集(OOD 縮小)。

  RL_CB=ebv2 RL_GAMMA=0.98 RL_FEAT=v19 RL_N=200 RL_CAND=5 RL_RO=3 RL_WORKERS=12 RL_OUT=db/_selfplay/rl_iter0.jsonl \
      .venv/bin/python scripts/collect_rl_data.py
出力: 1 rollout = 1 行 ({f:[rich], y:割引value, g:group})。
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")  # sklearn thread oversubscription 回避
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.value_policy_ai import ValuePolicyAI
from engine.plan_search import fast_clone
from engine.gbm_value import features

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
OUT = ROOT / (os.environ.get("RL_OUT") or "db/_selfplay/rl_iter0.jsonl")
CB = os.environ.get("RL_CB", "ebv2")           # 現best: "ebv2" or value pkl path
GAMMA = float(os.environ.get("RL_GAMMA", "0.98"))
FEAT = os.environ.get("RL_FEAT", "v19")
CAND = int(os.environ.get("RL_CAND", "5"))
RO = int(os.environ.get("RL_RO", "3"))
SAMPLE_EVERY = int(os.environ.get("RL_SAMPLE_EVERY", "2"))
TURN_CAP = int(os.environ.get("RL_TURN_CAP", "45"))
SEED0 = int(os.environ.get("RL_SEED0", "300000"))
POOL = ["cardrush_1385", "cardrush_1392", "cardrush_1399", "cardrush_1439", "cardrush_1453",
        "cardrush_1454", "cardrush_1456", "tcgportal_bonney", "tcgportal_hancock",
        "tcgportal_op11_luffy", "tcgportal_op13_luffy"]
_DL = {}
_FEATKW = {"rich": True, FEAT: True} if FEAT else {"rich": True}


def _dl(slug):
    if slug not in _DL:
        _DL[slug] = make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)
    return _DL[slug]


def _mk(seed, slug):
    """現best AI(driver + rollout downstream)。"""
    if CB == "ebv2":
        return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})
    return ValuePolicyAI(CB, feat_kwargs=_FEATKW, rng=random.Random(seed), deck_analysis={"deck_slug": slug})


def _rollout_labels(st, action_i, me_idx, hslug, oslug, base_seed):
    """action を打った後、 現best 同士で対局 → (勝敗, 手数) から割引 value γ^手数 を RO 個。"""
    labels = []
    for si in range(RO):
        b = fast_clone(st)
        r = random.Random(base_seed + si * 17)
        for p in b.players:
            d = list(getattr(p, "deck", [])); r.shuffle(d); p.deck = d
        try:
            apply_action(b, legal_actions(b)[action_i])
        except Exception:
            continue
        t_start = b.turn_number
        dr = [None, None]
        dr[me_idx] = _mk(900 + si, hslug); dr[1 - me_idx] = _mk(950 + si, oslug)
        steps = 0
        while not b.game_over and b.turn_number < TURN_CAP and steps < 400:
            cur = b.turn_player_idx
            try:
                play_one_action(b, dr[cur], dr[1 - cur])
            except Exception:
                break
            steps += 1
        if b.game_over:
            w = getattr(b, "winner", -1)
            turns = max(0, b.turn_number - t_start)
            if w == me_idx:
                labels.append(GAMMA ** turns)      # 勝ち: 早いほど高い
            elif w == (1 - me_idx):
                labels.append(0.0)                  # 負け
    return labels


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
    ais[h_idx] = _mk(seed * 5 + 1, hslug); ais[1 - h_idx] = _mk(seed * 7 + 3, oslug)
    rows = []
    n, hero_moves = 0, 0
    while not state.game_over and state.turn_number < 50 and n < 800:
        cur = state.turn_player_idx
        if cur == h_idx and state.phase.name == "MAIN":
            acts = legal_actions(state)
            cands = _cands(acts)
            if len(cands) >= 2 and hero_moves % SAMPLE_EVERY == 0:
                for ci in cands:
                    post = fast_clone(state)
                    try:
                        apply_action(post, legal_actions(post)[ci])
                    except Exception:
                        continue
                    if getattr(post, "game_over", False):
                        continue  # 確定局面は value 不要
                    f = [round(x, 5) for x in features(post, h_idx, **_FEATKW)]
                    labels = _rollout_labels(state, ci, h_idx, hslug, oslug, seed * 131 + ci * 17)
                    gid = f"{seed}_{hero_moves}_{ci}"
                    for y in labels:
                        rows.append({"f": f, "y": round(y, 5), "g": gid})
            hero_moves += 1
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    return rows


def main():
    N = int(os.environ.get("RL_N", "200"))
    W = int(os.environ.get("RL_WORKERS", "12"))
    seeds = list(range(SEED0, SEED0 + N))
    t0 = time.time()
    print(f"[collect_rl] CB={CB} γ={GAMMA} feat={FEAT} N={N} CAND={CAND} RO={RO} → {OUT.name}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(OUT, "w", encoding="utf-8") as fout, mp.Pool(W) as p:
        for i, rows in enumerate(p.imap_unordered(_one, seeds), 1):
            for r in rows:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(rows)
            if i % max(1, N // 20) == 0 or i == N:
                print(f"  {i}/{N} games, {total} samples, {time.time()-t0:.0f}s", flush=True)
    print(f"[collect_rl] DONE {total} samples ({time.time()-t0:.0f}s) → {OUT}", flush=True)


if __name__ == "__main__":
    main()
