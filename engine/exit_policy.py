"""EIV1-ExIt policy = 探索の「改善された初手ランキング」を蒸留した apprentice — 2026-07-24。

複利ループの核。 探索 (beam+engine+PIMC) は現モデルの 1-ply より良い初手を選ぶ = 改善オペレータ。
その「初手→探索score」を群内相対 advantage にして policy model が学習 → beam の prior に配線 →
次の探索が良い出発点から始まり複利で強くなる (Expert Iteration)。 誰の指摘も要らず、 探索が
engine の中で踏んだ帰結 (速攻リーサル等) が自動で banking される。

- featurize(state, action, me_idx) : (状態94 + 行動 identity) の特徴。 card-aware で汎化。
- policy_prior_bonus(state, action, me_idx) : 配備 beam が各初手に足す prior (= 蒸留の消費側)。
  学習済み model (db/eiv1/exit_policy.pkl) の予測 = その初手の相対優位。 model 無ければ 0 (no-op)。

⚠ value は較正 (絶対勝率)、 policy は弁別 (兄弟初手の相対順位) と役割分離 (研究の共通処方箋)。
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "db" / "eiv1" / "exit_policy.pkl"

# 行動タイプの one-hot 順 (未知は other)
_ATYPES = ("PlayCharacter", "PlayEvent", "PlayStage", "AttackLeader", "AttackCharacter",
           "ActivateMain", "AttachDonToCharacter", "EndPhase", "other")

_MODEL: Any = None
_MODEL_MTIME: float = -1.0


def _inplay(p, iid):
    if p.leader.instance_id == iid:
        return p.leader
    for c in p.characters:
        if c.instance_id == iid:
            return c
    return None


def _card_feats(card) -> list:
    """カード identity の特徴 (cost/power/counter + ラベル/大きさ)。 card_labels/magnitudes 由来。"""
    if card is None:
        return [0.0] * 9
    cid = getattr(card, "card_id", None)
    from . import card_labels as CL
    from . import card_magnitudes as CM
    try:
        labels = set(CL.labels_for_card(cid) or ())
    except Exception:
        labels = set()
    m = CM.for_card(cid) if cid else {}
    return [
        float(getattr(card, "cost", 0) or 0),
        float(getattr(card, "power", 0) or 0) / 1000.0,
        float(getattr(card, "counter", 0) or 0) / 1000.0,
        1.0 if labels & {"removal", "removal_ko", "removal_bounce"} else 0.0,
        1.0 if labels & {"draw", "search", "ramp_don", "recursion"} else 0.0,
        1.0 if "blocker" in labels else 0.0,
        max(float(m.get("rm_play_cost", 0.0)), float(m.get("rm_active_cost", 0.0))),
        float(m.get("draw", 0.0)) + float(m.get("don", 0.0)),
        1.0 if getattr(card, "is_blocker", False) else 0.0,
    ]


def action_feats(state: Any, action: Any, me_idx: int) -> list:
    """行動の identity 特徴 = タイプ one-hot(9) + 主体カード(9) + 対象(4) = 22。"""
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    aname = type(action).__name__
    oh = [1.0 if aname == t else 0.0 for t in _ATYPES[:-1]]
    if aname not in _ATYPES:
        oh = _ATYPES  # unreachable placeholder
    oh = [1.0 if aname == t else 0.0 for t in _ATYPES]
    # 主体カード
    card = None
    if aname in ("PlayCharacter", "PlayEvent", "PlayStage"):
        hi = getattr(action, "hand_idx", None)
        if hi is not None and 0 <= hi < len(me.hand):
            card = me.hand[hi].card if hasattr(me.hand[hi], "card") else me.hand[hi]
    elif aname in ("AttackLeader", "AttackCharacter"):
        ip = _inplay(me, getattr(action, "attacker_iid", -1))
        card = ip.card if ip else None
    elif aname in ("ActivateMain",):
        ip = _inplay(me, getattr(action, "source_iid", -1))
        card = ip.card if ip else None
    elif aname == "AttachDonToCharacter":
        ip = _inplay(me, getattr(action, "target_iid", -1))
        card = ip.card if ip else None
    cf = _card_feats(card)
    # 攻撃対象 (相手キャラ攻撃時): 対象の power/cost/脅威 + leader 攻撃か
    tgt = [0.0, 0.0, 0.0, 0.0]
    if aname == "AttackLeader":
        tgt = [0.0, 0.0, 0.0, 1.0]  # 4列目 = leader 攻撃フラグ
    elif aname == "AttackCharacter":
        tp = _inplay(opp, getattr(action, "target_iid", -1))
        if tp:
            from .opp_threat import _char_threat
            tgt = [float(tp.power) / 1000.0, float(getattr(tp.card, "cost", 0) or 0),
                   float(_char_threat(getattr(tp.card, "card_id", "") or "")), 0.0]
    return oh + cf + tgt


def featurize(state: Any, action: Any, me_idx: int) -> list:
    """(状態 v20 94 + 行動 22) = 116 の policy 入力。"""
    from . import gbm_value as G
    try:
        sf = G.features(state, me_idx, v20=True)
    except Exception:
        sf = [0.0] * 94
    return list(sf) + action_feats(state, action, me_idx)


def _load_model() -> Any:
    global _MODEL, _MODEL_MTIME
    try:
        mt = POLICY_PATH.stat().st_mtime
    except OSError:
        _MODEL = None
        return None
    if _MODEL is None or mt != _MODEL_MTIME:
        try:
            with open(POLICY_PATH, "rb") as f:
                _MODEL = pickle.load(f)
            _MODEL_MTIME = mt
        except Exception:
            _MODEL = None
    return _MODEL


def policy_prior_bonus(state: Any, action: Any, me_idx: int) -> float:
    """配備 beam が初手 action に足す prior (= 蒸留 policy の相対優位予測)。 model 無ければ 0。

    出力は「群内相対 advantage」 (= (score-mean)/std を学習) なので概ね [-2, 2] 程度。
    beam 側で ONEPIECE_EXIT_POLICY_W を掛けて score に加算する。"""
    m = _load_model()
    if m is None:
        return 0.0
    try:
        import numpy as np
        x = np.asarray([featurize(state, action, me_idx)], dtype=np.float32)
        return float(m.predict(x)[0])
    except Exception:
        return 0.0


def enabled() -> bool:
    return POLICY_PATH.exists() and os.environ.get("ONEPIECE_EXIT_POLICY_W", "0") not in ("0", "")
