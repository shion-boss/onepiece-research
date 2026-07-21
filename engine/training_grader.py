"""操縦コースの『あなたの手』採点器。

/training は「プロの理想手を見せるだけ」では教材にならない (= ohtsuki のフィードバック
『俺の手でもよくね?ってなるだけ・なぜ悪いか/どのくらい悪いか分からない』)。 このモジュールは
人間が実際に打ったターンを、 配備 value (= AI の勝率判断) と機械的事実で採点する:

  - **どのくらい悪いか** = 汎化 value の P(win): あなたの手番終了盤面 vs AI 最善ターン終了盤面 の差 (pt)。
    de-risk 実測: 同一局面で「何もしない 0.346 / AI 最善 0.463」= 約12pt の幅で手を区別できる。
  - **なぜ悪いか** = 機械的事実の差分 (相手ライフを削った量 / DON 使い残し / 盤面追加 / 相手キャラ除去)。
    value が見落としうる微妙な点 (= [[project_block_value_architecture]] の教訓) は事実で補う。

value は 1-ply の近似 (= 断定でなく「約○%」表示)。 事実は反論不能。 両方 + プロの定石理由で教える。
"""
from __future__ import annotations

import os
from typing import Any, Optional

_AGNOSTIC_PATH = "db/value_gbm_agnostic.pkl"
_model_cache: dict = {}


def _load_value(path: str = _AGNOSTIC_PATH):
    if path not in _model_cache:
        from .gbm_value import _load
        _model_cache[path] = _load(path)
    return _model_cache[path]


def value_pwin(state: Any, me_idx: int, path: str = _AGNOSTIC_PATH) -> Optional[float]:
    """state を me_idx 視点で評価した P(win) (= 汎化 GBM)。 失敗時 None。"""
    try:
        from .gbm_value import _model_pwin
        return float(_model_pwin(_load_value(path), state, me_idx))
    except Exception:
        return None


def _ip_power(c: Any) -> int:
    for attr in ("power", "current_power"):
        v = getattr(c, attr, None)
        if isinstance(v, (int, float)):
            return int(v)
    card = getattr(c, "card", None)
    return int(getattr(card, "power", 0) or 0)


def turn_facts(start: Any, end: Any, me_idx: int) -> dict:
    """start→end (= あなたの手番の前後) で観測できる機械的事実。 全て反論不能な数値。"""
    ms, me = start.players[me_idx], end.players[me_idx]
    os_, oe = start.players[1 - me_idx], end.players[1 - me_idx]
    return {
        "opp_life_dealt": max(0, len(os_.life) - len(oe.life)),   # 相手ライフを削った枚数
        "opp_chars_kod": max(0, len(os_.characters) - len(oe.characters)),  # 相手キャラ除去(概算)
        "my_chars_added": max(0, len(me.characters) - len(ms.characters)),  # 展開したキャラ数
        "my_board_power": sum(_ip_power(c) for c in me.characters),  # 自盤面総パワー
        "don_unused": int(getattr(me, "don_active", 0)),          # 使い残した DON (アクティブ)
        "my_hand": len(me.hand),
    }


# value 差の閾値 (= de-risk の実測幅 ~0.12 を基準に 3 段階)。
_GOOD = 0.03
_SLIGHT = 0.08


def verdict_for_gap(gap: float) -> dict:
    """gap = p_best - p_user (>0 = あなたの手が最善より劣る)。"""
    if gap <= _GOOD:
        return {"tier": "good", "label": "ほぼ最善", "tone": "green",
                "note": "あなたの手は最善手とほぼ互角です。 このまま自信を持ってOK。"}
    if gap <= _SLIGHT:
        return {"tier": "slight", "label": "やや損", "tone": "amber",
                "note": "悪い手ではありませんが、 最善手より少し損しています。"}
    return {"tier": "bad", "label": "明確に損", "tone": "red",
            "note": "最善手と比べて明確に損な手です。 下の違いを確認してください。"}


def _fact_diffs(user_facts: dict, best_facts: dict) -> list[str]:
    """あなた vs 最善 の事実差を『なぜ』の人間可読テキストに。 差がある項目のみ。"""
    out = []
    u, b = user_facts, best_facts
    if b["opp_life_dealt"] > u["opp_life_dealt"]:
        out.append(f"相手ライフを削った枚数: あなた {u['opp_life_dealt']} / 最善 {b['opp_life_dealt']} "
                   f"(= {b['opp_life_dealt'] - u['opp_life_dealt']} 枚多く攻めている)")
    if u["don_unused"] > b["don_unused"]:
        out.append(f"使い残した DON: あなた {u['don_unused']} 枚 / 最善 {b['don_unused']} 枚 "
                   f"(= DON を使い切れていない)")
    if b["my_chars_added"] > u["my_chars_added"]:
        out.append(f"展開したキャラ: あなた {u['my_chars_added']} 体 / 最善 {b['my_chars_added']} 体 "
                   f"(= 盤面作りが遅れている)")
    if b["opp_chars_kod"] > u["opp_chars_kod"]:
        out.append(f"除去した相手キャラ: あなた {u['opp_chars_kod']} / 最善 {b['opp_chars_kod']}")
    if b["my_board_power"] > u["my_board_power"] + 1000:
        out.append(f"自盤面の総パワー: あなた {u['my_board_power']} / 最善 {b['my_board_power']}")
    return out


def grade_turn(start_state: Any, user_end: Any, best_end: Any, me_idx: int,
               value_path: str = _AGNOSTIC_PATH) -> dict:
    """あなたの手番 (user_end) を AI 最善 (best_end) と比較採点。

    Returns: {p_user, p_best, gap_pt, verdict{...}, user_facts, best_facts, reasons[]}。
    value 取得失敗時は p_* を None にし、 事実ベースの採点のみ返す (= graceful degrade)。
    """
    p_user = value_pwin(user_end, me_idx, value_path)
    p_best = value_pwin(best_end, me_idx, value_path)
    user_facts = turn_facts(start_state, user_end, me_idx)
    best_facts = turn_facts(start_state, best_end, me_idx)
    reasons = _fact_diffs(user_facts, best_facts)

    result = {
        "p_user": None if p_user is None else round(p_user, 3),
        "p_best": None if p_best is None else round(p_best, 3),
        "gap_pt": None,
        "verdict": None,
        "user_facts": user_facts,
        "best_facts": best_facts,
        "reasons": reasons,
    }
    if p_user is not None and p_best is not None:
        gap = p_best - p_user
        result["gap_pt"] = round(gap * 100, 1)
        # value が「ほぼ最善」でも事実で明確に損なら格下げしない (= value の見落とし対策)。
        v = verdict_for_gap(gap)
        if v["tier"] == "good" and len(reasons) >= 2:
            v = {"tier": "slight", "label": "やや損", "tone": "amber",
                 "note": "勝率差は僅かですが、 下の点で最善手に劣ります。"}
        result["verdict"] = v
    return result
