# -*- coding: utf-8 -*-
"""経験ベース action 枝刈り(2026-07-10、 ohtsuki案「悪い手を経験から刈る」)。

Q(s,a)=P(win|state v6feat, action encode) を db/q_prune_model.pkl から load し、 beam の
候補 legal actions のうち **Q が最良より margin 以上劣る手だけ prune**(選ぶでなく切る)。
min_keep で空/過剰刈りを防ぐ。 env ONEPIECE_QPRUNE_MARGIN>0 で有効化(既定 0=無効=no-harm)。

encode は build_q_prune.encode_action_fields と一致させる(train/inference 同一特徴)。

⚠ **検証結果 = 負(2026-07-10、既定 OFF のまま残置)= [[project_experience_pruning_result]]**。
方策シフト率 0.9%(margin0.04)/2.1%(0.02)、A/B Δ +0.4pt(0.04)/−1.2pt(0.02)= 甘い所無し。
弱margin=配備valueが既に避ける手を刈る=冗長で無効、強margin=粗いaction符号で良手も刈り悪化。
根因: 経験Qは配備beamのvalueの「情報が少ない劣化版」(同v6特徴・粗符号・先読み無)。有効化するな。
"""
from __future__ import annotations
import os
import pickle
from typing import Optional

_MODEL = None
_LOADED = False
_ACTION_TYPES = ["AttackLeader", "AttackCharacter", "PlayCharacter", "PlayEvent",
                 "PlayStage", "ActivateMain", "AttachDonToLeader", "AttachDonToCharacter",
                 "EndPhase"]
_AIDX = {t: i for i, t in enumerate(_ACTION_TYPES)}


def _load():
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    p = "db/q_prune_model.pkl"
    if os.path.exists(p):
        try:
            _MODEL = pickle.load(open(p, "rb"))
        except Exception:
            _MODEL = None
    return _MODEL


def _encode_action_live(action, me):
    """action → 固定長ベクトル(build_q_prune.encode_action_fields と一致)。"""
    at = type(action).__name__
    atk_power = 0; target_is_leader = 0; attached_don = 0
    if at in ("AttackLeader", "AttackCharacter"):
        aid = getattr(action, "attacker_iid", None)
        atk = me.leader if me.leader.instance_id == aid else next(
            (c for c in me.characters if c.instance_id == aid), None)
        if atk is not None:
            atk_power = int(atk.power); attached_don = atk.attached_dons
        target_is_leader = 1 if at == "AttackLeader" else 0
    v = [0.0] * len(_ACTION_TYPES)
    if at in _AIDX:
        v[_AIDX[at]] = 1.0
    v += [atk_power / 10000.0, float(target_is_leader), attached_don / 4.0]
    return v


def q_prune(state, me_idx, actions):
    """Q<max-margin の候補を除いた actions を返す(min_keep 保証)。 model 無/env 無効なら原 actions。"""
    margin = float(os.environ.get("ONEPIECE_QPRUNE_MARGIN", "0") or "0")
    if margin <= 0.0 or len(actions) <= 2:
        return actions
    m = _load()
    if m is None:
        return actions
    min_keep = int(os.environ.get("ONEPIECE_QPRUNE_MINKEEP", "4"))
    try:
        from .gbm_value import features as _feat
        feat = [float(x) for x in _feat(state, me_idx, v6=True)]
        me = state.players[me_idx]
        model = m["model"]
        rows = [feat + _encode_action_live(a, me) for a in actions]
        import numpy as np
        qs = model.predict_proba(np.array(rows, dtype=float))[:, 1]
        best = float(qs.max())
        keep = [a for a, q in zip(actions, qs) if q >= best - margin]
        if len(keep) < min_keep:
            # Q 上位 min_keep を残す
            order = sorted(range(len(actions)), key=lambda i: -qs[i])[:min_keep]
            keep = [actions[i] for i in order]
        return keep if keep else actions
    except Exception:
        return actions
