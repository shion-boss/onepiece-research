# -*- coding: utf-8 -*-
"""
AI パラメータ集約
================

`engine/eval.py` の評価重み + `engine/ai.py` の意思決定閾値を 1 dataclass に集約。
`db/ai_params.json` に永続化し、 `scripts/learn_ai_params.py` で学習更新する。

デフォルト値は学習前 (= 現状ハードコード値) と完全一致。 既存テストを破壊しない。

接続:
- `BoardEvalWeights` への変換は `eval_weights()` メソッド
- `GreedyAI.__init__` が起動時に `AIParams.load()` を呼ぶ
- `GreedyAI._pick_activate_main` が `activate_main_*` 系を参照
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from .eval import BoardEvalWeights


DEFAULT_PATH = Path(__file__).resolve().parent.parent / "db" / "ai_params.json"


@dataclass
class AIParams:
    """AI 全体で共有するチューニング可能パラメータ。

    学習対象 (= `scripts/learn_ai_params.py` が grid search で動かす):
      評価重み (W_*) + 意思決定閾値 (activate_main_* / defense_threshold_* /
      attack_gap_tolerance_default)。

    デフォルト値は現状コード (engine/eval.py / engine/ai.py) と一致させてある。
    """

    # === 評価重み (engine/eval.py BoardEvalWeights と同期) ===
    w_life: int = 1500
    w_field_count: int = 1200
    w_field_power: int = 1
    w_hand: int = 250
    w_don: int = 200
    w_blocker: int = 800
    w_attached_don: int = 400
    w_active_chara: int = 600
    w_lethal: int = 5000
    # Phase 1 (R68): 被リーサル / デッキ残 / トリガー期待
    w_opp_next_lethal: int = 4000
    w_deck_finisher: int = 150
    w_life_trigger: int = 200
    # Phase 2 (R69): role 別 個別価値
    w_chara_quality: int = 400
    w_hand_quality: int = 150

    # === 意思決定閾値 (engine/ai.py) ===
    # 起動メイン: ドン相殺型でも eval delta が min_payoff 未満なら発動しない (0 = チェック無効)
    activate_main_min_payoff_global: int = 0
    # 起動メイン: ドン相殺型を「leader 攻撃予定 or DON 再投資先あり」のみ発動 (True で厳格化)
    activate_main_don_compensated_strict: bool = False

    # 防御閾値 (defense_thresholds の base 値 = ミッドレンジ default)。
    # アーキタイプ別 override は engine/ai.py で適用される。
    # 値は (counter_total_max, counter_card_count_max) のうち counter_total_max 側。
    defense_threshold_life_le_1: int = 99999  # 致命: 全力
    defense_threshold_life_eq_2: int = 8000
    defense_threshold_life_eq_3: int = 6000
    defense_threshold_life_ge_4: int = 2000

    # 攻撃: リーダー攻撃の安全マージン (= attacker.power >= leader.power + tolerance)
    # 負の値 = power 不足でも攻撃 (相手 counter を強制消費させる)
    attack_gap_tolerance_default: int = -500

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AIParams":
        """db/ai_params.json から読み込み。 ファイルが無ければ default。"""
        p = path or DEFAULT_PATH
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        params_dict = data.get("params", {})
        valid_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in params_dict.items() if k in valid_names}
        return cls(**filtered)

    def save(self, path: Optional[Path] = None, history_note: str = "") -> None:
        """db/ai_params.json に書き込み。 既存 _history を保持しつつ前バージョンを append。"""
        p = path or DEFAULT_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        prev_history: list = []
        if p.exists():
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
                prev_history = old.get("_history", [])
                if "params" in old:
                    prev_history.append({
                        "params": old["params"],
                        "saved_at": old.get("saved_at"),
                        "note": old.get("note", ""),
                    })
            except Exception:
                pass
        from datetime import datetime
        payload = {
            "version": "1",
            "saved_at": datetime.utcnow().isoformat() + "Z",
            "note": history_note,
            "params": asdict(self),
            "_history": prev_history[-20:],  # 最新 20 版だけ保持
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def eval_weights(self) -> BoardEvalWeights:
        """compute_score 用の BoardEvalWeights を生成。"""
        return BoardEvalWeights(
            W_LIFE=self.w_life,
            W_FIELD_COUNT=self.w_field_count,
            W_FIELD_POWER=self.w_field_power,
            W_HAND=self.w_hand,
            W_DON=self.w_don,
            W_BLOCKER=self.w_blocker,
            W_ATTACHED_DON=self.w_attached_don,
            W_ACTIVE_CHARA=self.w_active_chara,
            W_LETHAL=self.w_lethal,
            W_OPP_NEXT_LETHAL=self.w_opp_next_lethal,
            W_DECK_FINISHER=self.w_deck_finisher,
            W_LIFE_TRIGGER=self.w_life_trigger,
            W_CHARA_QUALITY=self.w_chara_quality,
            W_HAND_QUALITY=self.w_hand_quality,
            # W_GAME_OVER は学習対象外 (固定 1_000_000)
        )

    def defense_threshold_for_life(self, life: int) -> int:
        """ライフ残量に応じた counter 上限値を返す。"""
        if life <= 1:
            return self.defense_threshold_life_le_1
        if life == 2:
            return self.defense_threshold_life_eq_2
        if life == 3:
            return self.defense_threshold_life_eq_3
        return self.defense_threshold_life_ge_4
