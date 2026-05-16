# -*- coding: utf-8 -*-
"""リーダー脅威プロファイル抽出 (= 関数 3、 Phase 8 / Step 1 / 2026-05-16)。

相手リーダーの効果オーバーレイから「効果が活きるシナジー範囲」 と「脅威 feature」 を
抽出して、 AI が「相手リーダーの効果が活きにくい戦い方」 を選べるようにする。

例:
- 緑ミホーク (OP14-020): cost+1 でブースト → primary_threat_cost_range = (1, 4)、
  avoidance_strategy = "out_of_cost_range"
- 紫エネル (OP15-058): 起動メインで DON 回収 → starve_low_cost_don

# 公開 API
- `ThreatProfile` dataclass
- `extract_leader_threat_profile(leader_card, overlay) -> ThreatProfile`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .core import CardDef


@dataclass
class ThreatProfile:
    """相手リーダーの脅威プロファイル。"""

    leader_id: str
    # シナジー発動コスト範囲 (= 例: (1, 4) で cost 1-4 を狙う leader、 (0, 99) で範囲なし)
    primary_threat_cost_range: tuple[int, int] = (0, 99)
    # 脅威 feature (= 例: 「麦わらの一味」 「ドンキホーテ海賊団」)
    threat_features: list[str] = field(default_factory=list)
    # 戦術ラベル
    # - "default": 特別な対処不要
    # - "out_of_cost_range": cost 範囲外のキャラ展開を優先
    # - "starve_low_cost_don": DON 残量を低く保ち起動メインを潰す
    # - "avoid_features": 脅威 feature を持つキャラの起用を避ける
    avoidance_strategy: str = "default"
    # 起動メインの最小コスト (= DON 消費)、 これ以下に opp DON を留める戦術用
    activate_main_min_don: Optional[int] = None


def _iter_primitives(effect: dict):
    """effect の primitive 集合を yield (= "do" + optional ネスト)。"""
    do_list = effect.get("do", [])
    if isinstance(do_list, list):
        for p in do_list:
            if isinstance(p, dict):
                yield p
    # optional_cost_then 等の ネストもあり得るが、 ここでは 1 layer のみ
    for key in ("then", "else", "do_alt"):
        nested = effect.get(key)
        if isinstance(nested, list):
            for p in nested:
                if isinstance(p, dict):
                    yield p


def extract_leader_threat_profile(
    leader_card: CardDef,
    overlay: Optional[dict] = None,
) -> ThreatProfile:
    """リーダー効果から脅威プロファイルを自動抽出。

    overlay (= db/card_effects.json) の primitive を解析し、
    - amount_per / filtered_by_feature → 脅威 feature を集約
    - filtered_by_cost_le → 脅威 cost 範囲を抽出
    - activate_main の cost → starve 戦術判定
    """
    profile = ThreatProfile(leader_id=leader_card.card_id)

    if overlay is None:
        # overlay 未指定なら lazy ロード
        try:
            import json
            from pathlib import Path
            overlay_path = Path(__file__).resolve().parent.parent / "db" / "card_effects.json"
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
        except Exception:
            overlay = {}

    leader_effects = overlay.get(leader_card.card_id, [])
    if not isinstance(leader_effects, list):
        return profile

    threat_features: set[str] = set()
    cost_min: int = 99
    cost_max: int = -1
    activate_main_costs: list[int] = []

    for effect in leader_effects:
        if not isinstance(effect, dict):
            continue
        when = effect.get("when", "")
        cost_spec = effect.get("cost", {})
        if isinstance(cost_spec, dict) and "don" in cost_spec:
            try:
                d = int(cost_spec.get("don", 0))
                if when == "activate_main" and d > 0:
                    activate_main_costs.append(d)
            except Exception:
                pass

        for prim in _iter_primitives(effect):
            # 特徴 X を持つキャラへの pump / give_keyword 等
            if "filtered_by_feature" in prim:
                feats = prim["filtered_by_feature"]
                if isinstance(feats, list):
                    threat_features.update(feats)
                elif isinstance(feats, str):
                    threat_features.add(feats)
            # コスト N 以下のキャラへの buff
            if "filtered_by_cost_le" in prim:
                try:
                    c = int(prim["filtered_by_cost_le"])
                    cost_max = max(cost_max, c)
                    cost_min = min(cost_min, 1)
                except Exception:
                    pass
            # コスト range
            if "filtered_by_cost_ge" in prim:
                try:
                    c = int(prim["filtered_by_cost_ge"])
                    cost_min = min(cost_min, c)
                except Exception:
                    pass

    if threat_features:
        profile.threat_features = sorted(threat_features)
    if cost_max > 0:
        profile.primary_threat_cost_range = (max(cost_min, 1), cost_max)
        profile.avoidance_strategy = "out_of_cost_range"

    if activate_main_costs:
        min_cost = min(activate_main_costs)
        profile.activate_main_min_don = min_cost
        # 0 < min_cost <= 3 なら starve 戦術が有効
        if 0 < min_cost <= 3 and profile.avoidance_strategy == "default":
            profile.avoidance_strategy = "starve_low_cost_don"

    return profile
