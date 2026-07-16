# -*- coding: utf-8 -*-
"""ユーザーデッキの裏分析 (= AI vs AI 相性 + 役割内訳 + キーカード)。

ワーカー (scripts/deck_analysis_worker.py) が呼ぶ純関数。 Vercel サーバーレスでは長時間
計算できないので、 別プロセスで回してレポート dict を返し、 user_store に書き戻す。

方針:
- 相性は「両サイド同じ baseline AI (GoalDirected 既定) で操縦した時の勝率」= デッキ間の
  相対比較 (= pilot 非対称を避けるため analysis を渡さない)。 理論値ではない旨を UI で明示。
- 役割/キーカード/カーブは card_roles.json + カード DB から即算出 (シミュレーション不要)。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
_ROLES_PATH = ROOT / "db" / "card_roles.json"
_META_PATH = ROOT / "db" / "meta_decks.json"
_DECKS_DIR = ROOT / "decks"

_ROLE_LABEL = {
    "finisher": "フィニッシャー",
    "removal": "除去",
    "negation": "無効化",
    "disruption": "妨害",
    "recovery": "回復",
    "ramp": "ランプ(ドン加速)",
    "search": "サーチ",
    "draw": "ドロー",
    "blocker": "ブロッカー",
    "synergy": "シナジー",
}

# レポートに載せる役割の並び順 (= 重要度が伝わる順)。
_ROLE_ORDER = ["finisher", "removal", "negation", "disruption", "search", "draw",
               "ramp", "recovery", "blocker", "synergy"]

_roles_cache: Optional[dict] = None
_meta_cache: Optional[list] = None


def _load_roles() -> dict:
    global _roles_cache
    if _roles_cache is None:
        _roles_cache = json.loads(_ROLES_PATH.read_text(encoding="utf-8"))
    return _roles_cache


def _role_of(card_id: str, roles: dict) -> Optional[dict]:
    """variant (_p1 等) は base に fallback して role 情報を引く。"""
    return roles.get(card_id) or roles.get(card_id.split("_", 1)[0])


def _role_breakdown(main: list, roles: dict) -> dict:
    """役割内訳 + キーカード + テンポ/アーキタイプ推定。"""
    role_count: Counter = Counter()
    speed_count: Counter = Counter()
    key: list[dict] = []
    for e in main:
        cid = str(e.get("card_id"))
        n = int(e.get("count", 1))
        info = _role_of(cid, roles) or {}
        role = info.get("primary_role", "synergy")
        role_count[role] += n
        speed_count[info.get("speed_class", "mid")] += n
        threat = int(info.get("threat_level", 0) or 0)
        # キーカード候補 = finisher か 脅威度が高いカード。
        if role == "finisher" or threat >= 3:
            key.append({
                "card_id": cid,
                "name": info.get("name", cid),
                "role": role,
                "label": _ROLE_LABEL.get(role, role),
                "threat_level": threat,
                "count": n,
            })
    roles_out = [
        {"role": r, "label": _ROLE_LABEL.get(r, r), "count": role_count[r]}
        for r in _ROLE_ORDER
        if role_count.get(r)
    ]
    key.sort(key=lambda k: (-(k["threat_level"]), k["role"] != "finisher"))
    # アーキタイプ推定 (= speed_class 分布の偏り)。 粗い prior。
    early, mid, late = speed_count.get("early", 0), speed_count.get("mid", 0), speed_count.get("late", 0)
    total = max(1, early + mid + late)
    if early / total >= 0.45:
        archetype = "アグロ"
    elif late / total >= 0.35:
        archetype = "コントロール"
    else:
        archetype = "ミッドレンジ"
    return {
        "roles": roles_out,
        "key_cards": key[:8],
        "archetype": archetype,
        "speed_dist": {"early": early, "mid": mid, "late": late},
    }


def _curve_buckets(main: list, repo) -> dict:
    low = mid = high = 0
    for e in main:
        try:
            cost = repo.get(str(e.get("card_id"))).cost
        except KeyError:
            continue
        n = int(e.get("count", 1))
        if cost <= 2:
            low += n
        elif cost <= 4:
            mid += n
        else:
            high += n
    return {"low": low, "mid": mid, "high": high}


def _load_meta_decklists(repo) -> list:
    """16 メタデッキを (slug, name, leader, DeckList) で返す (キャッシュ)。"""
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    from engine.deck import make_deck_from_dict

    slugs = json.loads(_META_PATH.read_text(encoding="utf-8")).get("meta_deck_slugs", [])
    out = []
    for slug in slugs:
        p = _DECKS_DIR / f"{slug}.json"
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            dl = make_deck_from_dict(d, repo)
        except Exception:
            continue
        leader_name = d.get("leader_name") or ""
        if not leader_name:
            try:
                leader_name = repo.get(d.get("leader", "")).name
            except KeyError:
                leader_name = d.get("leader", "")
        out.append({"slug": slug, "name": d.get("name", slug),
                    "leader": d.get("leader", ""), "leader_name": leader_name, "decklist": dl})
    _meta_cache = out
    return out


def compute_deck_report(deck_dict: dict, *, n_games: int = 12, seed: int = 0,
                        progress=None) -> dict:
    """デッキ dict → 分析レポート dict。 役割は即算出、 相性は AI vs AI で計測。

    progress(done, total, label) が渡されれば各マッチアップ後に呼ぶ (= 進捗表示用)。
    """
    from engine.deck import CardRepository, make_deck_from_dict
    from engine.harness import run_matchup

    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    roles = _load_roles()
    main = deck_dict.get("main", [])

    comp = _role_breakdown(main, roles)
    curve = _curve_buckets(main, repo)

    user_dl = make_deck_from_dict(deck_dict, repo)
    metas = _load_meta_decklists(repo)

    matchups: list[dict] = []
    total = len(metas)
    for i, m in enumerate(metas):
        # 自分自身がメタ (= 同 leader) でもミラーとして計測する。
        rep = run_matchup(
            user_dl, m["decklist"], n_games=n_games, seed=seed + i,
            time_limit_turns=40, time_limit_mode="both_lose",
        )
        matchups.append({
            "slug": m["slug"],
            "name": m["name"],
            "leader": m["leader"],
            "leader_name": m["leader_name"],
            "win_rate": round(rep.deck1_winrate, 3),
            "n": rep.deck1_wins + rep.deck2_wins + rep.draws,
        })
        if progress:
            progress(i + 1, total, m["name"])

    played = [x for x in matchups if x["n"]]
    avg = round(sum(x["win_rate"] for x in played) / len(played), 3) if played else 0.0
    ranked = sorted(played, key=lambda x: -x["win_rate"])
    summary = {
        "avg": avg,
        "best": ranked[:3],
        "worst": list(reversed(ranked[-3:])) if len(ranked) >= 3 else [],
    }

    return {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ai_version": "GoalDirected_baseline",
        "n_games_per_matchup": n_games,
        "roles": comp["roles"],
        "key_cards": comp["key_cards"],
        "archetype": comp["archetype"],
        "speed_dist": comp["speed_dist"],
        "curve_buckets": curve,
        "matchups": matchups,
        "matchup_summary": summary,
    }
