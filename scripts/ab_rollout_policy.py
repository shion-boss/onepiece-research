# -*- coding: utf-8 -*-
"""root-level rollout policy の A/B(2026-07-08、 Claude idea)。

hero の各手番で、 戦略候補手(全攻撃/全効果/登場/配備手)を **残りデッキ再シャッフルの rollout(配備 AI
downstream)で実勝率評価 → 最良手を選ぶ**(= TD-Gammon 式 root rollout = policy improvement 1 step)。
blanket heuristic と違い per-position ground-truth なので compose する想定。 深さ探索(value 近似)と違い
実対局の帰結で選ぶので model 乖離が無い。

condition A = hero が root-rollout policy / condition B = hero が配備 policy。 opp は常に配備。
P0/P1 均等化(run_matchup 相当、 harness bias 修正済)。 同一 seed で A/B 比較。

  AB_N=40 AB_CAND=6 AB_RO=6 AB_WORKERS=8 .venv/bin/python scripts/ab_rollout_policy.py
"""
import sys, os, random, time
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

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
HERO = os.environ.get("AB_HERO", "cardrush_1454")
OPP = os.environ.get("AB_OPP", "tcgportal_calgara")
CAND = int(os.environ.get("AB_CAND", "6"))
RO = int(os.environ.get("AB_RO", "6"))
TURN_CAP = int(os.environ.get("AB_TURN_CAP", "40"))
# ⭐ policy 蒸留モード: AB_POLICY_VALUE=<pkl> で rollout を蒸留 value 予測に差替(高速 policy)。
_POLICY_VALUE = os.environ.get("AB_POLICY_VALUE")
_PV_FEAT = os.environ.get("AB_PV_FEAT", "v14")
_PV_MODEL = None


def _pv_model():
    global _PV_MODEL
    if _PV_MODEL is None:
        import pickle
        _PV_MODEL = pickle.load(open(ROOT / _POLICY_VALUE, "rb"))
    return _PV_MODEL


def _deck(s):
    import json
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{s}.json").read_text(encoding="utf-8")), _REPO)


def _mk(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10, deck_analysis={"deck_slug": slug})


# rollout downstream policy: exploit(=配備同等・重い) / greedy(=高速・配備可能かの検証)。
_RO_DOWN = os.environ.get("AB_RO_DOWNSTREAM", "exploit")


def _mk_ro(slug, seed):
    if _RO_DOWN == "greedy":
        from engine.ai import GreedyAI
        return GreedyAI(rng=random.Random(seed), deck_analysis={"deck_slug": slug})
    if _RO_DOWN == "goal":
        from engine.goal_directed_ai import GoalDirectedAI
        return GoalDirectedAI(rng=random.Random(seed), deck_analysis={"deck_slug": slug})
    if _RO_DOWN == "light":
        from engine.ai import LightDeepPlanningAI
        ai = LightDeepPlanningAI(rng=random.Random(seed), beam_width=4, max_depth=6, adaptive=False)
        from engine.ai import GreedyAI
        ai.set_ai_opp(GreedyAI(rng=random.Random(seed + 1)))
        return ai
    return _mk(slug, seed)


def _reshuffle(state, seed):
    r = random.Random(seed)
    for p in state.players:
        d = list(getattr(p, "deck", [])); r.shuffle(d); p.deck = d


def _rollout(state, action, hero_idx, hero_slug, opp_slug, si):
    try:
        apply_action(state, action)
    except Exception:
        return 0.5
    dr = [None, None]
    dr[hero_idx] = _mk_ro(hero_slug, 900 + si); dr[1 - hero_idx] = _mk_ro(opp_slug, 950 + si)
    steps = 0
    while not state.game_over and state.turn_number < TURN_CAP and steps < 400:
        cur = state.turn_player_idx
        try:
            play_one_action(state, dr[cur], dr[1 - cur])
        except Exception:
            break
        steps += 1
    if not state.game_over:
        return 0.5
    w = getattr(state, "winner", -1)
    return 1.0 if w == hero_idx else (0.0 if w == (1 - hero_idx) else 0.5)


def _candidates(acts, dep_idx):
    cand = set()
    if dep_idx is not None:
        cand.add(dep_idx)
    for i, a in enumerate(acts):
        if isinstance(a, (AttackLeader, AttackCharacter, ActivateMain, PlayCharacter)):
            cand.add(i)
    return sorted(cand)[:CAND]


def _rollout_choice(st, hero_idx, hero_slug, opp_slug, dep_ai, move_seed):
    """hero の手番: 候補手を rollout 評価して最良を返す。 配備手も候補に含む。"""
    acts = legal_actions(st)
    dep_idx = None
    try:
        dep = dep_ai.choose_action(fast_clone(st))
        for i, a in enumerate(acts):
            if a == dep: dep_idx = i; break
    except Exception:
        pass
    cands = _candidates(acts, dep_idx)
    if len(cands) <= 1:
        return dep_idx if dep_idx is not None else (0 if acts else None)
    # ⭐ value モード (AB_POLICY_VALUE): rollout の代わりに蒸留 value で候補を採点(高速)= policy 蒸留。
    if _POLICY_VALUE:
        from engine.gbm_value import features as _pvf
        m = _pv_model()
        best_idx, best_s = dep_idx, -2.0
        feats, cis = [], []
        for ci in cands:
            post = fast_clone(st)
            try:
                apply_action(post, legal_actions(post)[ci])
            except Exception:
                continue
            if getattr(post, "game_over", False):
                w2 = getattr(post, "winner", -1)
                s = 1.5 if w2 == hero_idx else (-1.5 if w2 == (1 - hero_idx) else 0.5)
                if s > best_s:
                    best_s, best_idx = s, ci
            else:
                kw = {"rich": True, _PV_FEAT: True}
                feats.append(_pvf(post, hero_idx, **kw)); cis.append(ci)
        if feats:
            try:
                probs = m.predict_proba(feats)[:, 1]
                for j, ci in enumerate(cis):
                    if float(probs[j]) > best_s:
                        best_s, best_idx = float(probs[j]), ci
            except Exception:
                pass
        return best_idx
    best_idx, best_w = dep_idx, -1.0
    for ci in cands:
        w = 0.0
        for si in range(RO):
            b = fast_clone(st); _reshuffle(b, move_seed * 131 + ci * 17 + si)
            w += _rollout(b, legal_actions(b)[ci], hero_idx, hero_slug, opp_slug, si)
        w /= RO
        if w > best_w:
            best_w, best_idx = w, ci
    return best_idx


def _play(seed, hero_rollout):
    hero_p0 = (seed % 2 == 0)
    if hero_p0:
        st = setup_game(_deck(HERO), _deck(OPP), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(HERO, seed * 3 + 1), _mk(OPP, seed * 5 + 2)]; hero_idx = 0
    else:
        st = setup_game(_deck(OPP), _deck(HERO), rng=random.Random(seed), first_player=0, effects_overlay=_OVERLAY)
        ais = [_mk(OPP, seed * 5 + 2), _mk(HERO, seed * 3 + 1)]; hero_idx = 1
    play_until_main(st)
    n = 0
    while not st.game_over and st.turn_number < TURN_CAP and n < 1500:
        cur = st.turn_player_idx
        if cur == hero_idx and hero_rollout:
            idx = _rollout_choice(st, hero_idx, HERO, OPP, ais[hero_idx], seed * 1000 + n)
            if idx is None:
                break
            try:
                # hero の attack は defense を差し込む必要 → play_one_action 経由でなく apply + defense
                from engine.ai import play_one_action as _po
                # rollout で選んだ index の action を強制適用(defense は opp AI が差す)
                act = legal_actions(st)[idx]
                # play_one_action は AI.choose_action を呼ぶので、 選択済 action を _pending にキャッシュ
                st._pending_ai_action = {"turn_player_idx": st.turn_player_idx, "action": act}
                _po(st, ais[hero_idx], ais[1 - hero_idx])
            except Exception:
                break
        else:
            try:
                play_one_action(st, ais[cur], ais[1 - cur])
            except Exception:
                break
        n += 1
    if not st.game_over:
        return "draw"
    w = getattr(st, "winner", -1)
    return 1 if w == hero_idx else (0 if w == (1 - hero_idx) else "draw")


def _one(seed):
    return (_play(seed, True), _play(seed, False))


def main():
    n = int(os.environ.get("AB_N", "40"))
    workers = int(os.environ.get("AB_WORKERS", "8"))
    seeds = list(range(1000, 1000 + n))
    t0 = time.time()
    print(f"[ab_rollout] {HERO} vs {OPP}  N={n} CAND={CAND} RO={RO} downstream={_RO_DOWN}  開始", flush=True)
    res = []
    with mp.Pool(workers) as p:
        for i, r in enumerate(p.imap_unordered(_one, seeds), 1):
            res.append(r)
            if i % max(1, n // 10) == 0 or i == n:
                aw = sum(1 for x in res if x[0] == 1); bw = sum(1 for x in res if x[1] == 1)
                print(f"  進捗 {i}/{n}  (A={aw} B={bw}, {time.time()-t0:.0f}s)", flush=True)
    a_w = sum(1 for r in res if r[0] == 1); b_w = sum(1 for r in res if r[1] == 1)
    print(f"{HERO} vs {OPP}  root-rollout policy  N={n} CAND={CAND} RO={RO}  ({time.time()-t0:.0f}s)")
    print(f"  A: hero=root-rollout : {a_w}/{n} = {100*a_w/n:.0f}%")
    print(f"  B: hero=配備 policy  : {b_w}/{n} = {100*b_w/n:.0f}%")
    print(f"  Δ = {100*a_w/n - 100*b_w/n:+.0f}pt")


if __name__ == "__main__":
    main()
