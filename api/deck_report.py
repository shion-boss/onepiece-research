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
    """試合ログ (GameStats) の集合から「戦い方の型・機能条件」を発掘する (= Phase A/B 探索)。

    全洞察を「ある挙動をした試合 vs しなかった試合の勝率差 (= 効果量)」に統一し、 効果量で
    ランキングして強い相関を上位に出す。 ⚠ AI が操縦した試合の傾向 (相関/タイミング閾値)
    であり、 完全な因果ではない (= 純因果は分岐 rollout が要る)。 先攻/後攻は外生変数なので
    交絡が少ない。
    """
    out: list[dict] = []
    if len(stats) < 12:  # 標本が少なすぎる時は出さない (= ノイズ抑制)
        return out
    won = [g for g in stats if g.won]
    lost = [g for g in stats if not g.won]
    if len(won) < 4 or len(lost) < 4:  # 勝ち/負け双方が要る (= 相関を出すため)
        return out

    N = len(stats)
    MIN_BUCKET = 5  # 各群の最小標本

    def wr(gs):
        return sum(1 for g in gs if g.won) / len(gs) if gs else 0.0

    def add(kind, title, detail, gap):
        out.append({"kind": kind, "title": title, "detail": detail + f"（{N}試合）",
                    "strength": round(min(1.0, abs(gap)), 3)})

    # ① 先攻/後攻 (= 外生変数、 交絡が少なく最も信頼できる)。
    fg = [g for g in stats if getattr(g, "went_first", False)]
    sg = [g for g in stats if not getattr(g, "went_first", False)]
    if len(fg) >= MIN_BUCKET and len(sg) >= MIN_BUCKET:
        wf, ws = wr(fg), wr(sg)
        if abs(wf - ws) >= 0.12:
            if wf > ws:
                add("tempo", "先攻を取れた方が有利",
                    f"先攻時の勝率 {wf * 100:.0f}%、 後攻時 {ws * 100:.0f}%。 先攻できた試合で押し切りやすい。", wf - ws)
            else:
                add("tempo", "後攻から捲る展開が得意",
                    f"後攻時の勝率 {ws * 100:.0f}%、 先攻時 {wf * 100:.0f}%。 受けてから返す試合で勝っている。", ws - wf)

    # ② 速攻 vs コントロール (= 相手ライフを削り始めたターンで割る)。
    early = [g for g in stats if g.first_hit_given_turn is not None and g.first_hit_given_turn <= 4]
    slow = [g for g in stats if g.first_hit_given_turn is None or g.first_hit_given_turn > 4]
    if len(early) >= MIN_BUCKET and len(slow) >= MIN_BUCKET:
        we, wsl = wr(early), wr(slow)
        if abs(we - wsl) >= 0.15:
            if we > wsl:
                add("playstyle", "先に攻めて削り切る（速攻寄り）",
                    f"4ターン目までに相手ライフを削り始めた試合の勝率 {we * 100:.0f}%、 遅れた試合は {wsl * 100:.0f}%。 早く詰めるほど勝つ。", we - wsl)
            else:
                add("playstyle", "急がず受けて長期戦（コントロール寄り）",
                    f"序盤に攻めた試合は勝率 {we * 100:.0f}% と低く、 遅く攻めた試合が {wsl * 100:.0f}%。 盤面を整えてから攻めるべき。", wsl - we)

    # ③ 攻撃の手数 (= 相手ライフに通した攻撃数を中央値で割る)。
    vals = sorted(g.attacks_life_hit for g in stats)
    med = vals[len(vals) // 2]
    hi = [g for g in stats if g.attacks_life_hit > med]
    lo = [g for g in stats if g.attacks_life_hit <= med]
    if len(hi) >= MIN_BUCKET and len(lo) >= MIN_BUCKET and wr(hi) - wr(lo) >= 0.15:
        add("tempo", "攻撃を通す手数が勝敗を分ける",
            f"相手ライフへの攻撃が多かった試合の勝率 {wr(hi) * 100:.0f}%、 少ない試合は {wr(lo) * 100:.0f}%。 手数が足りないと押し切れない。",
            wr(hi) - wr(lo))

    # ④ 除去 (= 相手キャラを KO できたか)。
    ko = [g for g in stats if sum(g.ko_targets.values()) >= 1]
    noko = [g for g in stats if sum(g.ko_targets.values()) == 0]
    if len(ko) >= MIN_BUCKET and len(noko) >= MIN_BUCKET and wr(ko) - wr(noko) >= 0.15:
        add("removal", "相手キャラをKOできると勝つ（除去が鍵）",
            f"相手キャラを除去できた試合の勝率 {wr(ko) * 100:.0f}%、 できない試合は {wr(noko) * 100:.0f}%。 盤面を捌けるかが重要。",
            wr(ko) - wr(noko))

    # ⑤ キーカードのタイミング/機能条件 (= Nターンまでに着地→機能、 or 出せた/出せない)。
    seen_names: set = set()
    for kc in key_cards[:6]:
        name = kc.get("name")
        if not name or name in seen_names:  # 同名の別バリアントは 1 回だけ
            continue
        seen_names.add(name)
        turns = [g.first_play_turn_by_card.get(name) for g in stats]
        if sum(1 for t in turns if t is not None) < MIN_BUCKET:
            continue
        best = None  # (gap, K, wr_by, wr_late)
        for K in (3, 4, 5, 6):
            by_k = [g for g, t in zip(stats, turns) if t is not None and t <= K]
            late = [g for g, t in zip(stats, turns) if t is None or t > K]
            if len(by_k) >= MIN_BUCKET and len(late) >= MIN_BUCKET:
                gap = wr(by_k) - wr(late)
                if best is None or gap > best[0]:
                    best = (gap, K, wr(by_k), wr(late))
        if best and best[0] >= 0.15:
            gap, K, wb, wl = best
            add("key_play", f"{name} は {K} ターン目までに着地させたい",
                f"{K}ターン目までに {name} を出せた試合の勝率 {wb * 100:.0f}%、 遅れた/出せなかった試合は {wl * 100:.0f}%。 着地が遅れると機能しにくい。",
                gap)
            continue
        wg = [g for g in stats if g.cards_played.get(name, 0) > 0]
        wo = [g for g in stats if g.cards_played.get(name, 0) == 0]
        if len(wg) >= MIN_BUCKET and len(wo) >= MIN_BUCKET and wr(wg) - wr(wo) >= 0.15:
            add("key_card", f"{name} の着地が生命線",
                f"{name} を出せた試合の勝率 {wr(wg) * 100:.0f}%、 出せない試合は {wr(wo) * 100:.0f}%。 盤面に出せるかが機能条件。",
                wr(wg) - wr(wo))

    # 効果量の大きい順 (= 強い相関を優先) に上位を採用。
    out.sort(key=lambda x: -x["strength"])
    return out[:5]


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
                    gs = parse_game_log(gr.log, winner_pidx, gr.turns, hero_idx)
                    gs.went_first = (gr.first_player == 0)  # hero(deck1) が先攻だったか
                    stats_accum.append(gs)
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
