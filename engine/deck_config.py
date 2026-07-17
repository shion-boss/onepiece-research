# -*- coding: utf-8 -*-
"""per-deck AI config の解決 (= 2026-06-21、 persist→consume の keying 層)。

config は **deck の内容ハッシュ** で keying する (= 同一レシピ = 同一最適 config、 誰の deck でも
共有でき、 user 間の slug 衝突を回避)。 既存の slug-keyed config (= decks/cardrush_* の 53 件) も
後方互換で読む。 解決順: deck_hash → deck_slug → {} (= default、 no-harm)。

tune_deck.py が書き、 ExploitBeam.__init__ → _load_deck_config が読む。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB = _REPO_ROOT / "db"


def recipe_hash(leader: str, main: list) -> str:
    """leader + main (= [{card_id,count},...]) の安定ハッシュ (= 順序非依存、 12 hex)。

    main 要素は dict ({"card_id","count"}) でも (card_id,count) tuple でも可。
    同一構成なら入力順に依らず同じ hash (= sorted で正規化)。
    """
    norm = []
    for e in main:
        if isinstance(e, dict):
            cid = e.get("card_id") or e.get("id") or ""
            cnt = int(e.get("count", 1))
        else:
            cid, cnt = e[0], int(e[1])
        norm.append((str(cid), cnt))
    norm.sort()
    payload = json.dumps({"leader": str(leader or ""), "main": norm},
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def hash_config_path(h: str) -> Path:
    return _DB / f"deck_ai_config_h{h}.json"


def slug_config_path(slug: str) -> Path:
    return _DB / f"deck_ai_config_{slug}.json"


def _read(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_deck_config(deck_slug: Optional[str] = None,
                     deck_hash: Optional[str] = None) -> dict:
    """deck_hash → deck_slug の順で config を解決 (= 無ければ {})。

    hash 優先 = user deck (内容 keyed) を最特異に解決。 slug fallback = 既存 53 件 + meta 用。
    """
    if deck_hash:
        cfg = _read(hash_config_path(deck_hash))
        if cfg:
            return cfg
    if deck_slug:
        return _read(slug_config_path(deck_slug))
    return {}


# ExploitBeam._load_deck_config が実際に読む「AI の挙動を変える」 knob (= それ以外は metadata)。
LEVER_KEYS = frozenset({
    "value_defense", "counter_event_def", "ce_discount", "hand_quality_w",
    "don_efficiency_w", "concept_prior_w", "postopp_turns", "postopp_self_value",
    "postopp_opp_value", "asym_multiturn", "plan_temperature", "play_prior_w",
})


def write_deck_config(cfg: dict, *, deck_hash: Optional[str] = None,
                      deck_slug: Optional[str] = None) -> Optional[Path]:
    """config を hash (優先) or slug の path に書く。 既存があれば merge (= 同 key 上書き)。"""
    if deck_hash:
        p = hash_config_path(deck_hash)
    elif deck_slug:
        p = slug_config_path(deck_slug)
    else:
        return None
    merged = _read(p)
    merged.update(cfg)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    except Exception:
        return None


def default_config_for_deck(leader: str, main: list, repo=None) -> dict:
    """user deck 保存時の初期 config。 危険な lever は入れず (= 既定=no-harm)、 値は tune/human-play
    で埋める前提。 唯一 value_defense だけ、 守備寄りデッキ (= 高 counter 密度 + blocker 多) の粗い
    heuristic で初期値を置く (tune で上書き可)。 それ以外は default のまま (config に書かない)。"""
    cfg: dict = {"source": "default_on_save", "tuned": False, "tune_status": "pending"}
    try:
        if repo is not None and main:
            counters, blockers, n = 0, 0, 0
            for e in main:
                cid = e.get("card_id") if isinstance(e, dict) else (e[0] if e else None)
                cnt = int(e.get("count", 1)) if isinstance(e, dict) else 1
                if not cid:
                    continue
                c = repo.get(cid)
                counters += int(getattr(c, "counter", 0) or 0) * cnt
                blockers += (1 if int(getattr(c, "block_icon", 0) or 0) > 0 else 0) * cnt
                n += cnt
            if n > 0:
                avg_counter = counters / n
                cfg["value_defense"] = bool(avg_counter >= 1300 and blockers >= 6)
    except Exception:
        pass
    return cfg


def propose_config_from_human_play(stats: dict) -> dict:
    """人間がそのデッキを操作した実績 (= human_matches 集計) から config 調整を **提案** する。

    ⚠ 提案のみ (= 自動適用しない)。 human play は「人間がそのデッキをどう戦わせたいか」の signal に
    なるが、 config を変えると AI の挙動が変わるので、 適用前に必ず deploy gate (A/B) で現行超えを
    確認する (= 未検証で ship しない、 [[feedback_ab_statistical_power]])。 ここでは stats から粗い
    提案を返すだけ。 現状 signal は勝敗/ターン数 (= human_matches 列) に限る (細かい「どの効果をいつ」
    は Blob action ログ + Claude 教師の別 track):
      - 長期戦で勝つ (= 高 avg_turns + 高 win_rate) → 守備寄り → value_defense 提案。
      - 短期決着で勝つ → 攻め寄り → value_defense OFF 提案。
    """
    prop: dict = {"source": "human_play_proposal", "applied": False, "n": int(stats.get("n", 0))}
    n = int(stats.get("n", 0))
    if n < 10:  # サンプル不足 = 提案しない
        prop["note"] = "insufficient_samples"
        return prop
    wr = float(stats.get("human_win_rate", 0.0))
    avg_turns = float(stats.get("avg_turns", 0.0))
    if wr >= 0.55 and avg_turns >= 11:
        prop["value_defense"] = True
        prop["reason"] = "human wins long/grindy games → 守備寄り運用"
    elif wr >= 0.55 and avg_turns <= 8:
        prop["value_defense"] = False
        prop["reason"] = "human wins short/aggressive games → 攻め寄り"
    else:
        prop["note"] = "no_clear_style"
    return prop
