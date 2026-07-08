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

⚠ データ量律速。 sample_size < MIN_SAMPLES の間は **greedy に degrade**。 ただしモデル化する
パラメータは 防御頻度・counter値・顔詰め比率 の **粗い比率/平均** で少数でも安定する上、
発火閾値(防御 0.30 / 顔 0.60)自体が高め = 一貫した傾向でないと跨げないので、 MIN_SAMPLES=10
でも「人間が実際に指した手」から意味ある signal を拾える (2026-07-08 ohtsuki 指摘)。 API の
収集バッチ(batch_size=10)と揃える。 公開サーバの試合が増えるほど精度向上 (= フライホイール)。
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

    モデル化している差分:
      - **防御の手厚さ** (defense_activity): greedy が通すリーダー被弾を手札 counter で防ぐ。
      - **攻撃志向** (aggression): 顔詰め型の人間は greedy がキャラ trade を選ぶ場面でも
        リーダー攻撃を選ぶ → AttackCharacter を AttackLeader に redirect (= 2026-06-05、
        build_human_model の攻撃抽出 fix で aggression が robust に取れるようになり追加)。
    マリガン傾向は今後 mulligan_keep_rate を反映予定。
    """

    name = "HumanModel"
    # この試合数を下回る間は greedy に degrade。 粗い比率/平均パラメータ + 高めの発火閾値なので
    # 10 試合でも「人間が実際に指した手」から意味ある signal を拾える (2026-07-08、 batch_size=10 と整合)。
    MIN_SAMPLES = 10
    # defense_activity (= 1 ターンあたり防御アクション数) がこの値以上なら「防御手厚い人間」。
    DEFENSE_ACTIVE_THRESHOLD = 0.30
    # aggression (= 顔狙い攻撃比率) がこの値以上なら「顔詰め型」 → キャラ攻撃を顔へ寄せる。
    AGGRO_THRESHOLD = 0.60

    def __init__(self, *args, model: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = model if model is not None else _load_model()
        self._sample = int(self._model.get("sample_size", 0) or 0)
        self._defense_activity = float(self._model.get("defense_activity", 0.0) or 0.0)
        self._aggression = float(self._model.get("aggression", 0.0) or 0.0)

    def _human_defends_heavily(self) -> bool:
        return (self._sample >= self.MIN_SAMPLES
                and self._defense_activity >= self.DEFENSE_ACTIVE_THRESHOLD)

    def _human_rushes_face(self) -> bool:
        return (self._sample >= self.MIN_SAMPLES
                and self._aggression >= self.AGGRO_THRESHOLD)

    def choose_action(self, state):
        action = super().choose_action(state)
        # 顔詰め型の人間モデル: greedy が キャラ攻撃 (trade) を選んだ場面で リーダー攻撃が
        # legal なら 顔へ寄せる (= aggression を相手モデルの offense に反映)。 データ薄 or
        # 攻撃志向が低ければ greedy のまま (degrade)。
        if not self._human_rushes_face():
            return action
        from .game import legal_actions, AttackLeader, AttackCharacter
        if isinstance(action, AttackCharacter):
            # 同じ攻撃者でリーダーを殴れるなら そちらへ (= 攻撃者を保ったまま顔へ寄せる)。
            # 無ければ 任意のリーダー攻撃。
            las = legal_actions(state)
            same = next((a for a in las if isinstance(a, AttackLeader)
                         and a.attacker_iid == action.attacker_iid), None)
            face = same or next((a for a in las if isinstance(a, AttackLeader)), None)
            if face is not None:
                return face
        return action

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
