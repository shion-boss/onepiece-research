"""matchup context 層 — A軸(自分理解) + B軸(相手理解) prior を統合。

2 つの prior を単体 artifact から state に対して評価し、 探索の相手モデル / Claude 教師の
context / 分析 UI が共通で食える構造化サマリにする。

- B軸: 相手 leader (公開) + 見えた札 (seen) から belief 事後で「相手が握る脅威」を予測
  (engine/opponent_deck_model.py)
- A軸: 自分の leader 効果の型・使い方 prior (engine/leader_effect_profile.py)

human/Claude 可読テキストも出す (= Claude 教師が「相手はこれを握る、 自分のリーダーはこう使う」
を見て良手を demonstrate する為の context)。 純関数的で engine 内部状態を壊さない (read-only)。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .leader_effect_profile import get_default_model as _leader_profile_model
from .opponent_deck_model import get_default_model as _opp_deck_model

_REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _card_index() -> dict[str, dict[str, Any]]:
    """card_id → {name, category, cost, power, counter} の軽量 lookup (1 度だけロード)。"""
    try:
        cards = json.loads((_REPO_ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(cards, dict):
        cards = cards.get("cards", [])
    idx: dict[str, dict[str, Any]] = {}
    for c in cards:
        cid = c.get("card_id")
        if cid:
            idx[cid] = {
                "name": c.get("name", ""),
                "category": c.get("category", ""),
                "cost": c.get("cost"),
                "power": c.get("power"),
                "counter": c.get("counter"),
            }
    return idx


def _leader_id(player: Any) -> str | None:
    try:
        return player.leader.card.card_id
    except Exception:
        return None


def collect_seen_opponent_cards(state: Any, opp_idx: int) -> dict[str, int]:
    """相手のデッキに最低何枚あると分かっているか (= belief 事後の seen)。

    公開ゾーン (場キャラ / ステージ / トラッシュ) + 既知手札 を集計。 これらは
    「相手が確かに 50 枚に積んでいる」 と確定した札 = 事後で整合レシピを絞る材料。
    """
    counts: dict[str, int] = {}
    try:
        opp = state.players[opp_idx]
    except Exception:
        return counts

    def _add(cid: str | None) -> None:
        if cid:
            counts[cid] = counts.get(cid, 0) + 1

    for ip in getattr(opp, "characters", []) or []:
        _add(getattr(getattr(ip, "card", None), "card_id", None))
    for ip in getattr(opp, "stages", []) or []:
        _add(getattr(getattr(ip, "card", None), "card_id", None))
    for c in getattr(opp, "trash", []) or []:
        _add(getattr(c, "card_id", None))
    for cid in getattr(opp, "known_hand_card_ids", []) or []:
        _add(cid)
    return counts


def opponent_threat_summary(state: Any, me_idx: int, top_n: int = 8) -> dict[str, Any]:
    """相手 leader + seen から「相手が握る/積む脅威」を belief 事後で予測して返す。"""
    opp_idx = 1 - me_idx
    try:
        opp = state.players[opp_idx]
    except Exception:
        return {"known": False}
    lid = _leader_id(opp)
    model = _opp_deck_model()
    if not lid or not model.has_leader(lid):
        return {"known": False, "leader_id": lid}

    seen = collect_seen_opponent_cards(state, opp_idx)
    idx = _card_index()
    top = model.top_cards(lid, n=top_n, seen=seen)
    threats = []
    for cid, info in top:
        meta = idx.get(cid, {})
        threats.append({
            "card_id": cid,
            "name": meta.get("name", ""),
            "category": meta.get("category", ""),
            "cost": meta.get("cost"),
            "prob": round(float(info["prob"]), 3),
            "exp_count": round(float(info["exp_count"]), 2),
        })
    return {
        "known": True,
        "leader_id": lid,
        "leader_name": idx.get(lid, {}).get("name", ""),
        "n_decks": model.n_decks(lid),          # belief の confidence 目安
        "n_seen": len(seen),
        "posterior_sharpened": bool(seen),      # seen で事後更新が効いたか
        "top_threats": threats,
    }


def own_leader_plan(state: Any, me_idx: int) -> dict[str, Any]:
    """自分の leader 効果の型・使い方 prior を返す。"""
    try:
        me = state.players[me_idx]
    except Exception:
        return {"known": False}
    lid = _leader_id(me)
    model = _leader_profile_model()
    if not lid or not model.has_leader(lid):
        return {"known": False, "leader_id": lid}
    return {
        "known": True,
        "leader_id": lid,
        "leader_name": model.profile(lid).get("leader_name", ""),
        "primary_role": model.primary_role(lid),
        "primary_usage": model.primary_usage(lid),
        "usage_hint": model.usage_hint(lid),
        "when_decision": model.when_decision(lid),   # 「いつ使うか」判断が要る効果か
        "active_effects": [
            {"text": e.get("text", ""), "usage_pattern": e.get("usage_pattern"),
             "gating": e.get("gating", {})}
            for e in model.active_effects(lid)
        ],
    }


def describe_matchup_context(state: Any, me_idx: int) -> dict[str, Any]:
    """A軸(自分) + B軸(相手) を統合した matchup context (探索/Claude/UI 共通入力)。"""
    return {
        "own": own_leader_plan(state, me_idx),
        "opponent": opponent_threat_summary(state, me_idx),
    }


def format_context_text(ctx: dict[str, Any]) -> str:
    """context を Claude 教師 / ログ用の可読テキストに整形する。"""
    lines: list[str] = []
    own = ctx.get("own", {})
    if own.get("known"):
        lines.append(f"[自分] {own.get('leader_name')} — リーダー効果: {own.get('primary_usage')}")
        if own.get("usage_hint"):
            lines.append(f"  使い方: {own['usage_hint']}")
        if own.get("when_decision"):
            for e in own.get("active_effects", []):
                if e.get("text"):
                    lines.append(f"  起動: {e['text']}")
    opp = ctx.get("opponent", {})
    if opp.get("known"):
        conf = f"n={opp.get('n_decks')}" + (
            f", 観測{opp.get('n_seen')}枚で予想を絞込" if opp.get("posterior_sharpened") else ""
        )
        lines.append(f"[相手] {opp.get('leader_name')} が握る/積む脅威 ({conf}):")
        for t in opp.get("top_threats", []):
            p = int(round(t["prob"] * 100))
            lines.append(f"  {t['name'] or t['card_id']} ({t['category']}, {p}% × {t['exp_count']}枚)")
    else:
        lines.append("[相手] 未知 leader — belief 予測なし")
    return "\n".join(lines)
