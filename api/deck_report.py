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


def _mine_strategy(stats: list, key_cards: list) -> list[dict]:
    """試合ログ (GameStats) の集合から「戦い方の型・機能条件」を発掘する (= Phase A 探索)。

    ⚠ これは AI が操縦した試合の傾向 (= 相関、 記述的)。 因果の精密化 (このターンに
    これしないと機能しない) は Phase B の分岐 rollout で行う。
    """
    from statistics import mean

    out: list[dict] = []
    if len(stats) < 8:
        return out

    def avg(xs, attr):
        vals = [getattr(g, attr) for g in xs if getattr(g, attr, None) is not None]
        return mean(vals) if vals else None

    won = [g for g in stats if g.won]
    lost = [g for g in stats if not g.won]
    if len(won) < 3 or len(lost) < 3:
        return out

    # ① 速攻 vs コントロール (= 相手ライフを削り始めたターンの勝敗差)。
    w_hit, l_hit = avg(won, "first_hit_given_turn"), avg(lost, "first_hit_given_turn")
    if w_hit is not None and l_hit is not None:
        if w_hit <= l_hit - 0.7:
            out.append({"kind": "playstyle", "title": "先に攻めて削り切る（速攻寄り）",
                        "detail": f"勝った試合は平均 {w_hit:.1f} ターン目に相手ライフを削り始め、 "
                                  f"負けた試合は {l_hit:.1f} ターン目。 相手より先に詰めにいくほど勝っている。"})
        elif w_hit >= l_hit + 0.7:
            out.append({"kind": "playstyle", "title": "急がず受けて長期戦（コントロール寄り）",
                        "detail": f"勝った試合はライフを削り始めるのが平均 {w_hit:.1f} ターン目と遅い。 "
                                  f"焦って攻めた試合ほど負けており、 盤面を整えてから攻めるべき。"})

    # ② 攻撃を通した手数の勝敗差。
    w_atk, l_atk = avg(won, "attacks_life_hit"), avg(lost, "attacks_life_hit")
    if w_atk is not None and l_atk is not None and w_atk >= l_atk + 1.0:
        out.append({"kind": "tempo", "title": "攻撃を通す手数が勝敗を分ける",
                    "detail": f"勝った試合は相手ライフに平均 {w_atk:.1f} 回攻撃を通し、 負けは {l_atk:.1f} 回。 "
                              f"攻撃の手数が足りないと押し切れない。"})

    # ③ キーカードの機能条件 (= これを出せた/出せないで勝率が変わるか)。
    for kc in key_cards[:5]:
        name = kc.get("name")
        if not name:
            continue
        with_g = [g for g in stats if g.cards_played.get(name, 0) > 0]
        without_g = [g for g in stats if g.cards_played.get(name, 0) == 0]
        if len(with_g) >= 4 and len(without_g) >= 4:
            wr_w = sum(1 for g in with_g if g.won) / len(with_g)
            wr_o = sum(1 for g in without_g if g.won) / len(without_g)
            if wr_w - wr_o >= 0.15:
                out.append({"kind": "key_card", "title": f"{name} の着地が生命線",
                            "detail": f"{name} を出せた試合の勝率 {wr_w * 100:.0f}%、 出せなかった試合は "
                                      f"{wr_o * 100:.0f}%。 これを盤面に出せるかがこのデッキの機能条件。"})

    return out[:6]


def _assemble_report(comp: dict, curve: dict, matchups: list, n_games: int,
                     n_opponents: int, rhash: str, *, partial: bool,
                     insights: Optional[list] = None) -> dict:
    """計算済みの部分/全体から report dict を組む (= 途中経過も同じ形で保存できる)。"""
    played = [x for x in matchups if x.get("n")]
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
        "recipe_hash": rhash,          # この report がどのレシピの計算か (= 再開時の照合)
        "roles": comp["roles"],
        "key_cards": comp["key_cards"],
        "archetype": comp["archetype"],
        "speed_dist": comp["speed_dist"],
        "curve_buckets": curve,
        "matchups": matchups,
        "n_opponents": n_opponents,
        "matchup_summary": summary,
        "insights": insights or [],    # ⭐ 戦い方の型・機能条件 (= 探索で発掘した洞察)
        "partial": partial,            # True = まだ全マッチアップ揃っていない
    }


def compute_deck_report(deck_dict: dict, *, n_games: int = 8, seed: int = 0,
                        recipe_hash: str = "", done_matchups=None,
                        on_progress=None, pause_between: float = 0.0) -> dict:
    """デッキ dict → 分析レポート dict。 役割は即算出、 相性は AI vs AI で 1 マッチずつ計測。

    - done_matchups: 既に計算済みの matchup list (= 途中再開時に渡すと skip する)。
    - on_progress(done, total, label, partial_report): 各マッチアップ後に呼ぶ。 途中経過の
      report を渡すので、 これを保存すれば「1マッチずつ永続 = スリープ/中断に強い」。
    - pause_between: マッチアップ間の休止秒 (= CPU に優しくする / ブラウザで yield する用)。
    """
    import time

    from engine.deck import CardRepository, make_deck_from_dict
    from engine.harness import run_matchup
    from engine.log_analyzer import parse_game_log

    repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
    roles = _load_roles()
    main = deck_dict.get("main", [])

    comp = _role_breakdown(main, roles)
    curve = _curve_buckets(main, repo)

    user_dl = make_deck_from_dict(deck_dict, repo)
    metas = _load_meta_decklists(repo)
    n_opponents = len(metas)
    done_map = {m["slug"]: m for m in (done_matchups or []) if m.get("n")}

    matchups: list[dict] = []
    stats_accum: list = []  # 全試合の GameStats (= 戦略探索の素材、 matchup 計算を再利用)
    for i, m in enumerate(metas):
        if m["slug"] in done_map:
            matchups.append(done_map[m["slug"]])  # 再開: 計算済みは skip
        else:
            # keep_logs=True で試合ログを取り、 戦い方の傾向を発掘する (= 追加試合なし)。
            rep = run_matchup(
                user_dl, m["decklist"], n_games=n_games, seed=seed + i,
                time_limit_turns=40, time_limit_mode="both_lose", keep_logs=True,
            )
            matchups.append({
                "slug": m["slug"],
                "name": m["name"],
                "leader": m["leader"],
                "leader_name": m["leader_name"],
                "win_rate": round(rep.deck1_winrate, 3),
                "n": rep.deck1_wins + rep.deck2_wins + rep.draws,
            })
            # hero (= user デッキ = deck1) の各試合の挙動を抽出。
            # GameResult.first_player = deck1 が先攻(0)/後攻(1) → hero の player index に一致
            #   (first_player=0 → p0=deck1、 first_player=1 → p1=deck1)。
            # GameResult.winner は deck 正規化 (0=deck1 勝ち) なので、 parse 用に player-index
            #   winner へ変換する。
            for gr in rep.games:
                try:
                    hero_idx = gr.first_player
                    if gr.winner == -1:
                        winner_pidx = -1
                    elif gr.winner == 0:            # deck1 (hero) 勝ち
                        winner_pidx = hero_idx
                    else:                           # deck2 勝ち
                        winner_pidx = 1 - hero_idx
                    stats_accum.append(parse_game_log(gr.log, winner_pidx, gr.turns, hero_idx))
                except Exception:
                    continue
            if pause_between:
                time.sleep(pause_between)
        if on_progress:
            insights = _mine_strategy(stats_accum, comp["key_cards"])
            on_progress(i + 1, n_opponents, m["name"],
                        _assemble_report(comp, curve, matchups, n_games, n_opponents,
                                         recipe_hash, partial=(i + 1 < n_opponents), insights=insights))

    insights = _mine_strategy(stats_accum, comp["key_cards"])
    return _assemble_report(comp, curve, matchups, n_games, n_opponents, recipe_hash,
                            partial=False, insights=insights)
