# -*- coding: utf-8 -*-
"""Canonical state snapshot + digest (2026-07-29、 Rust engine 差分同期の土台)。

Python engine と 将来の Rust engine が「同一 seed/action 列で bit 一致の状態を辿るか」を検証するための
**言語非依存な正準状態表現**。 dataclass introspection で全 field を自動列挙(手書き漏れ防止 = InPlay 71
field でも自動)、 非ゲームプレイ/非決定的 field(rng・log・overlay・hook 等)は除外。

用途:
  1. record_trace(deck_a, deck_b, seed): Python で1ゲーム再生、 各 action 後の canonical 状態 digest を記録
  2. (将来) Rust engine で同じ seed/action を再生 → 同じ digest 列になるか comparator で assert
  3. 乖離時は canonical dict を突合して「どの field / どの primitive で分岐したか」を pinpoint

正準化の規約:
  - CardDef → card_id 文字列 (静的 = card_id で一意)
  - InPlay/Player/GameState → dataclass field を再帰 serialize (card→card_id、 set→sorted、 dict→sorted items)
  - 除外 field = 下記 _EXCLUDE (rng: 言語間で内部状態が違う / log,overlay: 非ゲームプレイ / hook,callable: 非決定的)
  - callable → "<fn:name>" (アドレス非依存)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

# 除外 field 名 (どの dataclass でも). 決定論比較に無関係 or 言語間で一致しない.
_EXCLUDE = {
    "rng",                 # random.Random 内部状態 = 言語間で一致しない (seed 列消費で決定論を担保)
    "log",                 # 人間可読ログ = 非ゲームプレイ
    "effects_overlay",     # 共有静的データ = 両engine同一
    "snapshots",           # ハーネス収集用メタ
    "record_snapshots",    # 同上フラグ
    "event_order_hook",    # callable
    "text",                # CardDef 経由では card_id に畳むので不要 (念のため)
    "instance_id",         # グローバルカウンタ採番 = ゲーム毎/言語間で不一致な単なる一意タグ。
                           #   状態の意味は card_id + flag + zone 位置(list順)で決まる → 除外が正準
    # --- ルール状態でない meta (AI 評価 / UI / デッキ情報 / human 対話) = 差分対象外 ---
    "action_evals",        # AI 行動品質評価履歴
    "audit_violations",    # audit meta
    "record_action_evals", # フラグ
    "deck_slugs",          # デッキ metadata (AI 重み load 用)
    "archetypes",          # 同上
    "deck_flags",          # AI eval interaction 特徴
    "pending_event",       # snapshot 用イベント情報 (UI)
    "human_player_idx",    # human 対戦 config (self-play では None)
    "pending_choice",      # human 選択待ち (self-play では None)
    "forced_human_actor_idx",  # human actor override
    "pending_attack_hits", # human ライフ受け確認 (self-play では None)
}


def _ser(obj: Any) -> Any:
    """任意オブジェクトを JSON 化可能な正準表現へ再帰変換 (決定論的)。"""
    # CardDef: card_id に畳む (静的データ)
    if is_dataclass(obj) and type(obj).__name__ == "CardDef":
        return getattr(obj, "card_id", "?")
    if is_dataclass(obj) and not isinstance(obj, type):
        out = {}
        for f in fields(obj):
            if f.name in _EXCLUDE:
                continue
            out[f.name] = _ser(getattr(obj, f.name))
        return out
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, dict):
        # key を文字列化して sort (順序非依存)
        return {str(k): _ser(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (set, frozenset)):
        return sorted(_ser(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [_ser(x) for x in obj]
    if callable(obj):
        return f"<fn:{getattr(obj, '__name__', '?')}>"
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # 未知オブジェクト: 型名 + 可能なら __dict__ (アドレス非依存を優先)
    if hasattr(obj, "__dict__"):
        return {"__type__": type(obj).__name__,
                **{k: _ser(v) for k, v in sorted(vars(obj).items()) if k not in _EXCLUDE}}
    return f"<{type(obj).__name__}>"


def canonical_state(state: Any) -> dict:
    """GameState → 正準 dict (言語非依存、 決定論的)。"""
    return _ser(state)


def state_digest(state: Any) -> str:
    """GameState → 安定 digest (sha1、 状態が同じなら同じ digest)。"""
    blob = json.dumps(canonical_state(state), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _ser_full(obj: Any) -> Any:
    """Rust 取込用の full dump: canonical と同じだが CardDef を **畳まず全 field の dict** で出す
    (Rust の CardDef struct が deserialize できるように)。 instance_id 除外・set→sorted は同じ。"""
    if is_dataclass(obj) and type(obj).__name__ == "CardDef":
        cat = obj.category.name if isinstance(obj.category, Enum) else obj.category
        return {
            "card_id": obj.card_id, "name": obj.name, "category": cat,
            "color": list(obj.color), "cost": obj.cost, "life": obj.life,
            "power": obj.power, "counter": obj.counter, "attribute": obj.attribute,
            "block_icon": obj.block_icon, "features": list(obj.features),
            "text": obj.text, "trigger": obj.trigger,
        }
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _ser_full(getattr(obj, f.name)) for f in fields(obj) if f.name not in _EXCLUDE}
    if isinstance(obj, Enum):
        return obj.name
    if isinstance(obj, dict):
        return {str(k): _ser_full(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(_ser_full(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [_ser_full(x) for x in obj]
    if callable(obj):
        return f"<fn:{getattr(obj, '__name__', '?')}>"
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if hasattr(obj, "__dict__"):
        return {"__type__": type(obj).__name__,
                **{k: _ser_full(v) for k, v in sorted(vars(obj).items()) if k not in _EXCLUDE}}
    return f"<{type(obj).__name__}>"


def full_dump(state: Any) -> dict:
    """Rust engine が deserialize できる full state dump (card は展開、 instance_id 除外)。"""
    return _ser_full(state)


def diff_canonical(a: dict, b: dict, path: str = "") -> list:
    """2 つの canonical dict の差分箇所を (path, a_val, b_val) で列挙 (乖離 pinpoint 用)。"""
    out = []
    if type(a) is not type(b):
        return [(path or ".", a, b)]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((f"{path}.{k}", "<missing>", b[k]))
            elif k not in b:
                out.append((f"{path}.{k}", a[k], "<missing>"))
            else:
                out.extend(diff_canonical(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((f"{path}[len]", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff_canonical(x, y, f"{path}[{i}]"))
    elif a != b:
        out.append((path or ".", a, b))
    return out
