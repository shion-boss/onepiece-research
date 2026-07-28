# -*- coding: utf-8 -*-
"""蒸留 policy(rollout-value で 1-ply 手選択)vs EBV2 (2026-07-28、 条件(b) policy 形)。

rollout = 候補手 post-action state を実対局評価し最良選択。 学習 value(AUC0.93)= その rollout 勝率を予測。
→ **その value で候補手を 1-ply 採点(post-action state を value 評価)して argmax = rollout 選択の高速近似**。
value を使うのは決定点 post-action state のみ = 訓練と同分布(value-in-beam が全葉で OOD 失敗したのを回避)。
これが EBV2 を超えれば (b) policy クリア = 成長ループ実在・高速化可能。

  PD_SLUG=cardrush_1385 PD_VALUE=db/_selfplay/value_rollout_v14.pkl PD_N=120 PD_FEAT=v14 PD_WORKERS=12 \
      .venv/bin/python scripts/ab_policy_distilled.py
"""
import sys, os, random, time, json, pickle
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter,
                         AttachDonToLeader, AttachDonToCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone
from engine.gbm_value import features

ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("PD_SLUG", "cardrush_1385")
VALUE = os.environ.get("PD_VALUE", "db/_selfplay/value_rollout_v14.pkl")
FEAT = os.environ.get("PD_FEAT", "v14")
CANDMAX = int(os.environ.get("PD_CANDMAX", "8"))
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        _MODEL = pickle.load(open(ROOT / VALUE, "rb"))
    return _MODEL


def _dl(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text()), _REPO)


def _feat(state, me):
    kw = {"rich": True}
    if FEAT:
        kw[FEAT] = True
    return features(state, me, **kw)


class DistilledPolicyAI(ExploitBeamAI):
    """全 legal action を post-action state の rollout-value(蒸留 value)で 1-ply 採点し argmax 選択。
    = 「rollout = true rollout-value で 1-ply」の predicted-value 版。 EBV2 beam は呼ばない(高速)。"""
    def choose_action(self, state):
        me = state.turn_player_idx
        acts = legal_actions(state)
        if len(acts) <= 1:
            return acts[0] if acts else super().choose_action(state)
        m = _model()
        # 候補限定(速度): 非DON(攻撃/登場/効果/end)全部 + DON付与は数個だけ。 DON付与が各キャラ分で
        # 膨れるのを抑える(value 採点の clone/feat コストを削減)。
        non_don, don = [], []
        for i, a in enumerate(acts):
            if isinstance(a, (AttachDonToLeader, AttachDonToCharacter)):
                don.append(i)
            else:
                non_don.append(i)
        keep = set(non_don) | set(don[:3])
        feats, idxs = [], []
        scores = {}
        for i, a in enumerate(acts):
            if i not in keep:
                continue
            post = fast_clone(state)
            try:
                apply_action(post, a)
            except Exception:
                continue
            if getattr(post, "game_over", False):
                w = getattr(post, "winner", -1)
                scores[i] = 1.5 if w == me else (-1.5 if w == (1 - me) else 0.5)
            else:
                feats.append(_feat(post, me)); idxs.append(i)
        if feats:
            try:
                probs = m.predict_proba(feats)[:, 1]  # batch 予測(1決定=1 call)
                for j, i in enumerate(idxs):
                    scores[i] = float(probs[j])
            except Exception:
                pass
        if not scores:
            return super().choose_action(state)
        return acts[max(scores, key=scores.get)]


def _one(seed):
    a_idx = seed % 2           # A(蒸留policy)がどちら側か
    fp = (seed // 2) % 2
    state = setup_game(_dl(SLUG), _dl(SLUG), rng=random.Random(seed), first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = DistilledPolicyAI(rng=random.Random(seed * 5 + 1), beam_width=16, max_depth=10,
                                   deck_analysis={"deck_slug": SLUG})
    ais[1 - a_idx] = ExploitBeamAI(rng=random.Random(seed * 7 + 3), beam_width=16, max_depth=10,
                                   deck_analysis={"deck_slug": SLUG})
    n = 0
    while not state.game_over and state.turn_number < 45 and n < 800:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return ("incomplete", state.turn_number)
    w = getattr(state, "winner", -1)
    r = "A" if w == a_idx else ("B" if w == (1 - a_idx) else "draw")
    return (r, state.turn_number)


def main():
    n = int(os.environ.get("PD_N", "120"))
    workers = int(os.environ.get("PD_WORKERS", "12"))
    seeds = list(range(200000, 200000 + n))
    t0 = time.time()
    print(f"[ab_policy_distilled] {SLUG} mirror  A(蒸留policy {VALUE}) vs B(EBV2)  N={n} feat={FEAT}", flush=True)
    res = []
    with mp.Pool(workers) as p:
        for i, rr in enumerate(p.imap_unordered(_one, seeds), 1):
            res.append(rr)
            if i % max(1, n // 6) == 0:
                a = sum(1 for x, _ in res if x == "A"); b = sum(1 for x, _ in res if x == "B")
                inc = sum(1 for x, _ in res if x == "incomplete")
                print(f"  進捗 {i}/{n} (A={a} B={b} 未決{inc}, {time.time()-t0:.0f}s)", flush=True)
    a = sum(1 for x, _ in res if x == "A"); b = sum(1 for x, _ in res if x == "B")
    inc = sum(1 for x, _ in res if x == "incomplete")
    turns = [t for _, t in res]
    wr = a / max(1, a + b) * 100
    print(f"[ab_policy_distilled] {SLUG}: 蒸留policy 勝率 {wr:.1f}% ({a}-{b})  "
          f"未決{inc}  avg_turn={sum(turns)/max(1,len(turns)):.1f}  ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
