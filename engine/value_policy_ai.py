# -*- coding: utf-8 -*-
"""ValuePolicyAI = 蒸留 value で 1-ply 手選択する方策 (2026-07-28、 RL ループの生徒)。

root-rollout が beam を +30pt 超える([[project_rollout_beats_beam]])= value 迂回。 rollout の "選択"
(候補手を打った後の state の rollout-value で argmax)を、 学習 value(rollout-value 予測)で高速近似する方策。
value を使うのは決定点 post-action state のみ = in-distribution。 割引 value(regressor)/ 勝率(classifier)両対応。

⚠ multiprocessing で使う時は OMP_NUM_THREADS=1 を set(sklearn の OpenMP thread oversubscription 回避)。
"""
from __future__ import annotations
import pickle
from typing import Optional

from .ai import GreedyAI
from .game import (legal_actions, apply_action, AttachDonToLeader, AttachDonToCharacter)
from .plan_search import fast_clone
from .gbm_value import features

_MODEL_CACHE: dict = {}


def _load(path: str):
    if path not in _MODEL_CACHE:
        with open(path, "rb") as f:
            _MODEL_CACHE[path] = pickle.load(f)
    return _MODEL_CACHE[path]


class ValuePolicyAI(GreedyAI):
    """全 legal action(DON付与は数個に制限)を post-action state の value で 1-ply 採点、 argmax 選択。

    value_path: 学習済 value pkl (regressor=predict / classifier=predict_proba を自動判別)。
    feat_kwargs: features() に渡す rich 版指定 (例 {"rich": True, "v19": True})。
    don_cap: DON付与候補の上限(速度: 各キャラ分で膨れるのを抑える)。
    """

    def __init__(self, value_path: str, feat_kwargs: Optional[dict] = None,
                 don_cap: int = 3, rng=None, deck_analysis=None, **kw):
        super().__init__(rng=rng, deck_analysis=deck_analysis)
        self._vp_path = value_path
        self._vp_feat = feat_kwargs or {"rich": True, "v14": True}
        self._vp_don_cap = don_cap
        self._vp_is_reg = None  # predict vs predict_proba を初回に判別

    def _score(self, model, feats):
        if self._vp_is_reg is None:
            self._vp_is_reg = not hasattr(model, "predict_proba")
        if self._vp_is_reg:
            return model.predict(feats)
        return model.predict_proba(feats)[:, 1]

    def choose_action(self, state):
        me = state.turn_player_idx
        acts = legal_actions(state)
        if len(acts) <= 1:
            return acts[0] if acts else super().choose_action(state)
        model = _load(self._vp_path)
        non_don, don = [], []
        for i, a in enumerate(acts):
            (don if isinstance(a, (AttachDonToLeader, AttachDonToCharacter)) else non_don).append(i)
        keep = set(non_don) | set(don[: self._vp_don_cap])
        feats, idxs, scores = [], [], {}
        for i in keep:
            post = fast_clone(state)
            try:
                apply_action(post, legal_actions(post)[i])
            except Exception:
                continue
            if getattr(post, "game_over", False):
                w = getattr(post, "winner", -1)
                scores[i] = 2.0 if w == me else (-2.0 if w == (1 - me) else 0.5)
            else:
                feats.append(features(post, me, **self._vp_feat)); idxs.append(i)
        if feats:
            try:
                sc = self._score(model, feats)
                for j, i in enumerate(idxs):
                    scores[i] = float(sc[j])
            except Exception:
                pass
        if not scores:
            return super().choose_action(state)
        return acts[max(scores, key=scores.get)]
