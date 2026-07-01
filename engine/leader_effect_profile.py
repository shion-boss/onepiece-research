"""自分のリーダー効果の「型 + 使い方 prior」(runtime)。

相手デッキ belief モデル (engine/opponent_deck_model.py) の対称 = 自分理解 (A 軸)。
db/leader_effect_profiles.json を読み、リーダーの効果 type / いつ使うか判断が要るか /
使い方 prior を返す。 value の feature / 探索 prior / Claude 教師の context に使う。

⚠ この prior は「型」と「粗い使い方」まで。 精密な timing は多ターン探索 + Claude 教師が
埋める (= build_leader_effect_profiles.py の note 参照)。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PATH = _REPO_ROOT / "db" / "leader_effect_profiles.json"

# usage_pattern → 使い方 prior の一文 (Claude 教師 context / doc / UI 用)
USAGE_HINTS: dict[str, str] = {
    "engine_use_often": "毎ターン回して雪だるま式に有利を広げるエンジン。序盤から積極的に使う",
    "hold_for_threat": "除去/妨害レバー。相手の鍵となる脅威まで温存し、最も刺さる対象に使う",
    "enabler_this_turn": "そのターンの大きい動きを可能にする。本命プレイとセットで切る",
    "aggression_when_attacking": "アタック時の打点上乗せ。ダメージに変換できる時に使う",
    "tempo_aggression": "テンポ攻勢。盤面を押し込むために使う",
    "attack_trigger": "アタックに紐づく効果。攻撃の組み立ての中で発火する",
    "reactive_defense": "相手ターンの防御レバー。守りたい局面のために温存する",
    "defensive_setup": "守りの布石。被害を抑えるために使う",
    "automatic_trigger": "条件で自動発火。使うタイミングの判断は不要",
    "passive_static": "常在効果。判断不要",
    "active_other": "起動効果。局面に応じて判断する",
}


class LeaderEffectProfileModel:
    """leader_id → 効果 type / 使い方 prior。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._meta: dict[str, Any] = data.get("meta", {})
        self._leaders: dict[str, Any] = data.get("leaders", {})

    @property
    def leaders(self) -> list[str]:
        return list(self._leaders.keys())

    def has_leader(self, leader_id: str) -> bool:
        return leader_id in self._leaders

    def profile(self, leader_id: str) -> dict[str, Any] | None:
        """leader の全プロファイル (effects 明細つき)。未知は None。"""
        return self._leaders.get(leader_id)

    def primary_role(self, leader_id: str) -> str | None:
        entry = self._leaders.get(leader_id)
        return entry["primary_role"] if entry else None

    def primary_usage(self, leader_id: str) -> str | None:
        """代表効果の使い方 pattern (engine_use_often / hold_for_threat 等)。"""
        entry = self._leaders.get(leader_id)
        return entry["primary_usage"] if entry else None

    def when_decision(self, leader_id: str) -> bool:
        """プレイヤーが『いつ使うか』を選ぶ効果 (activate_main) を持つか。"""
        entry = self._leaders.get(leader_id)
        return bool(entry["when_decision"]) if entry else False

    def usage_hint(self, leader_id: str) -> str:
        """代表効果の使い方 prior を一文で。未知/未分類は空文字。"""
        usage = self.primary_usage(leader_id)
        return USAGE_HINTS.get(usage or "", "")

    def active_effects(self, leader_id: str) -> list[dict[str, Any]]:
        """『いつ使うか』判断が要る (timing==active) 効果だけを返す。"""
        entry = self._leaders.get(leader_id)
        if not entry:
            return []
        return [e for e in entry["effects"] if e.get("timing") == "active"]


@lru_cache(maxsize=1)
def get_default_model() -> LeaderEffectProfileModel:
    """db/leader_effect_profiles.json を読んだ既定モデル (無ければ空)。"""
    if _DEFAULT_PATH.exists():
        data = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
    else:
        data = {"meta": {}, "leaders": {}}
    return LeaderEffectProfileModel(data)


def load_model(path: str | Path | None = None) -> LeaderEffectProfileModel:
    p = Path(path) if path else _DEFAULT_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    return LeaderEffectProfileModel(data)
