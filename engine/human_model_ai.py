# -*- coding: utf-8 -*-
"""HumanModelAI: 人間プレイ log から学んだ「人間の打ち方」を再現する相手モデル (= 2026-06-04)。

⭐ 目的: 今の対戦 AI が弱い核心は「探索が相手を GreedyAI と仮定して読む」こと
(深読みするほど悪化、 と measured 確認済 = [[project_70pct_vs_greedy]])。 本物の人間を
モデル化し、 強い AI の **探索の仮想敵 (set_ai_opp)** に差し替えれば、 AI は人間相手に
過剰展開や咎められる手を避けるようになる (= self-play では作れなかった部分)。

これは その最初の一手。 `db/human_model.json` (= scripts/build_human_model.py で生成) の
粗い人間挙動パラメータで GreedyAI をバイアスする:
  - defense_activity / counter_value_avg: 人間は counter を厚く使う傾向 → 防御を greedy より
    手厚くする (= リーダー被弾を手札カウンターで防ぐ)。

⚠ データ量律速。 sample_size < MIN_SAMPLES の間は **greedy に degrade** (= 8 試合では
≈greedy、 正直)。 公開サーバの試合が増えるほど人間らしくなる (= フライホイール)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .ai import GreedyAI

_MODEL_PATH = Path(__file__).resolve().parent.parent / "db" / "human_model.json"


def _load_model() -> dict:
    try:
        return json.loads(_MODEL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"sample_size": 0}


class HumanModelAI(GreedyAI):
    """人間挙動パラメータで GreedyAI をバイアスした相手モデル。

    現状モデル化している差分は **防御の手厚さ** のみ (= robust に抽出できた信号)。
    攻撃性/マリガン等は log 抽出の精度が上がり次第追加。
    """

    name = "HumanModel"
    # この試合数を下回る間は greedy に degrade (= 統計的に意味が出ない)。
    MIN_SAMPLES = 30
    # defense_activity (= 1 ターンあたり防御アクション数) がこの値以上なら「防御手厚い人間」。
    DEFENSE_ACTIVE_THRESHOLD = 0.30

    def __init__(self, *args, model: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = model if model is not None else _load_model()
        self._sample = int(self._model.get("sample_size", 0) or 0)
        self._defense_activity = float(self._model.get("defense_activity", 0.0) or 0.0)

    def _human_defends_heavily(self) -> bool:
        return (self._sample >= self.MIN_SAMPLES
                and self._defense_activity >= self.DEFENSE_ACTIVE_THRESHOLD)

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        block_iid, counters = super().choose_defense(
            state, attacker, target, is_leader_attack, defender)
        # データ薄 or 防御手薄な人間 → greedy のまま (degrade)。
        if not self._human_defends_heavily():
            return block_iid, counters
        # ブロック済 or キャラ攻撃 (= リーダー被弾でない) は そのまま。
        if block_iid is not None or not is_leader_attack:
            return block_iid, counters
        # 「カウンター厚い人間」 モデル: greedy が通した リーダー被弾を、 手札の
        # 数値カウンターで防ぐ (= 公式: 守り > 攻撃 で無効。 counter は手札を切るだけ)。
        leader_power = int(getattr(defender.leader, "power", 0) or 0)
        atk = int(getattr(attacker, "power", 0) or 0)
        used = set(counters)

        def cval(i: int) -> int:
            if 0 <= i < len(defender.hand):
                return int(getattr(defender.hand[i], "counter", 0) or 0)
            return 0

        cur = leader_power + sum(cval(i) for i in counters)
        if cur > atk:
            return block_iid, counters  # 既に耐える
        cand = sorted(
            (i for i in range(len(defender.hand)) if i not in used and cval(i) > 0),
            key=cval,  # 小さい counter から使う (= 大きいのは温存)
        )
        extra = list(counters)
        for i in cand:
            if cur > atk:
                break
            cur += cval(i)
            extra.append(i)
        return block_iid, tuple(extra)
