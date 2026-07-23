"""カード効果の「大きさ」(= 矢印の長さ) を overlay の DSL から機械導出 — 2026-07-23。

[[project_eiv1_expert_iteration]] の①表現レバー。 card_labels は効果の **向き** (removal /
draw / ramp …) しか持たないため、 「コスト4以下をKO」と「コスト1以下をKO」が同じ removal_ko に
潰れ、 value からは完全に同一に見えていた (= ohtsuki 指摘「角度が同じでも矢印の長さが違う」)。
ここでは同じ向きの中の **長さ** を数値化する。

⭐ timing で分ける: 盤面に **残っている駒** の脅威は on_play(一発、 既に使用済) ではなく
activate_main / on_attack 等の **繰り返し使える** 効果。 盤面特徴には active 側を使う。

出力 (per card_id):
  rm_active_cost / rm_active_pw   : 盤面から繰り返し撃てる除去の射程 (コスト上限 / パワー上限)
  rm_play_cost   / rm_play_pw     : 登場時など一発の除去の射程
  rm_targets                      : 一度に触れる体数
  draw / don / pump / search / recover : その他の効果量 (= 各向きの矢印の長さ)

射程は 条件なし = 上限値 (cost 10 / power 15000) を入れる (= 「何にでも届く」)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
_OVERLAY_PATH = ROOT / "db" / "card_effects.json"

# 条件なし除去の射程 (= 実在カードの上限より上に置いて「何にでも届く」を表す)
UNCOND_COST = 10.0
UNCOND_POWER = 15000.0
# cost_le_dynamic (= 相手ライフ数などで動く) は中庸値で代表させる
DYNAMIC_COST = 5.0

_REMOVAL_PRIMS = ("ko", "ko_multi", "ko_all_others", "return_to_hand", "return_to_hand_multi",
                  "return_to_deck_bottom", "return_to_deck_bottom_multi", "chara_to_opp_life")
# 盤面に残った駒が繰り返し撃てる timing (= on_play/on_ko 等の一発ものは除く)
_ACTIVE_WHEN = ("activate_main", "on_attack", "on_block", "opp_attack_on_leader",
                "opp_attack_on_chara", "on_self_rested", "on_opp_chara_played",
                "on_self_chara_played", "on_turn_end", "on_opp_turn_end")

_COST_RE = re.compile(r"cost_le_(\d+)")
_POWER_RE = re.compile(r"power_le_(\d+)")

_CACHE: Optional[dict] = None


def _reach_from_filter(f: Any) -> tuple:
    """filter (dict) → (cost 射程, power 射程)。 条件が無ければ上限 (= 何にでも届く)。"""
    if not isinstance(f, dict) or not f:
        return UNCOND_COST, UNCOND_POWER
    cost = power = None
    for key in ("cost_le", "current_cost_le", "cost_le_self_plus_opp_life"):
        if key in f:
            try:
                cost = float(f[key])
            except Exception:
                cost = DYNAMIC_COST
    if "cost_le_dynamic" in f:
        cost = DYNAMIC_COST
    for key in ("power_le", "current_power_le", "truly_original_power_le"):
        if key in f:
            try:
                power = float(f[key])
            except Exception:
                pass
    # 片方しか条件が無い場合、 もう片方は制限なし
    if cost is None and power is None:
        # feature/color 等の条件のみ = 数値射程としては無制限だが的は狭い → 中庸に倒す
        return UNCOND_COST * 0.6, UNCOND_POWER * 0.6
    return (cost if cost is not None else UNCOND_COST,
            power if power is not None else UNCOND_POWER)


def _reach_from_target_str(s: str) -> tuple:
    """target 文字列 ("one_opponent_character_cost_le_4cost" 等) → (cost 射程, power 射程)。"""
    m = _COST_RE.search(s)
    cost = float(m.group(1)) if m else None
    m2 = _POWER_RE.search(s)
    power = float(m2.group(1)) if m2 else None
    if cost is None and power is None:
        return UNCOND_COST, UNCOND_POWER
    return (cost if cost is not None else UNCOND_COST,
            power if power is not None else UNCOND_POWER)


def _removal_reach(val: Any) -> tuple:
    """除去プリミティブの引数 → (cost 射程, power 射程, 体数)。"""
    if isinstance(val, str):
        c, p = _reach_from_target_str(val)
        return c, p, 1
    if isinstance(val, list):   # *_multi = target 列
        cs, ps, n = 0.0, 0.0, 0
        for t in val:
            c, p, _ = _removal_reach(t)
            cs, ps, n = max(cs, c), max(ps, p), n + 1
        return cs, ps, max(n, 1)
    if isinstance(val, dict):
        c, p = _reach_from_filter(val.get("filter"))
        n = 1
        for key in ("count", "n", "limit"):
            if isinstance(val.get(key), int):
                n = max(n, int(val[key]))
        tgt = val.get("type") or val.get("target")
        if isinstance(tgt, str) and ("all" in tgt):
            n = max(n, 5)
        return c, p, n
    return UNCOND_COST, UNCOND_POWER, 1


def _walk(node: Any, out: dict, active: bool) -> None:
    """do ツリーを歩いて magnitude を集約 (max 取り)。"""
    if isinstance(node, list):
        for x in node:
            _walk(x, out, active)
        return
    if not isinstance(node, dict):
        return
    for k, v in node.items():
        if k in _REMOVAL_PRIMS:
            c, p, n = _removal_reach(v)
            if k == "ko_all_others":
                c, p, n = UNCOND_COST, UNCOND_POWER, max(n, 5)
            pre = "rm_active" if active else "rm_play"
            out[f"{pre}_cost"] = max(out[f"{pre}_cost"], c)
            out[f"{pre}_pw"] = max(out[f"{pre}_pw"], p)
            out["rm_targets"] = max(out["rm_targets"], float(n))
        elif k == "draw" and isinstance(v, int):
            out["draw"] = max(out["draw"], float(v))
        elif k in ("add_don", "add_rested_don") and isinstance(v, int):
            out["don"] = max(out["don"], float(v))
        elif k == "power_pump" and isinstance(v, dict):
            try:
                out["pump"] = max(out["pump"], abs(float(v.get("amount") or 0)))
            except Exception:
                pass
        elif k in ("search_top_n", "reveal_top_then", "search") and isinstance(v, dict):
            try:
                out["search"] = max(out["search"], float(v.get("depth") or v.get("count") or 0))
            except Exception:
                pass
        elif k in ("put_top_to_life", "hand_to_self_life", "chara_to_self_life"):
            amt = float(v) if isinstance(v, int) else 1.0
            out["recover"] = max(out["recover"], amt)
        # ネストした do / then / cost 配下も辿る
        _walk(v, out, active)


def _blank() -> dict:
    return {"rm_active_cost": 0.0, "rm_active_pw": 0.0, "rm_play_cost": 0.0, "rm_play_pw": 0.0,
            "rm_targets": 0.0, "draw": 0.0, "don": 0.0, "pump": 0.0, "search": 0.0,
            "recover": 0.0}


def build_all(overlay_path: Optional[str] = None) -> dict:
    """overlay 全カード → {card_id: magnitudes}。 効果なしカードは全 0。"""
    path = Path(overlay_path) if overlay_path else _OVERLAY_PATH
    ov = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for cid, blocks in ov.items():
        if cid.startswith("_") or not isinstance(blocks, list):
            continue
        mg = _blank()
        for blk in blocks:
            if not isinstance(blk, dict):
                continue
            when = str(blk.get("when") or "")
            active = when in _ACTIVE_WHEN
            _walk(blk.get("do"), mg, active)
        out[cid] = mg
    return out


def magnitudes_db() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = build_all()
        except Exception:
            _CACHE = {}
    return _CACHE


def for_card(card_id: str) -> dict:
    return magnitudes_db().get(card_id) or _blank()
