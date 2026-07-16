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
import re
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

    roles = _load_roles()
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
        # 相手のアーキタイプ (= 相手別プランのグループキー)。
        arch = _role_breakdown(d.get("main", []), roles)["archetype"]
        out.append({"slug": slug, "name": d.get("name", slug), "leader": d.get("leader", ""),
                    "leader_name": leader_name, "archetype": arch, "decklist": dl})
    _meta_cache = out
    return out


def _deck_profile(stats: list) -> dict:
    """勝敗に依らず「このデッキが実際どう回るか」を記述するプロファイル (= 常に出せる情報)。

    偏ったデッキ (勝率が極端で相関が出ない) でも、 平均何ターンで決着し・いつ攻め始め・
    どれだけ除去し… という挙動サマリは必ず出せる。"""
    if len(stats) < 6:
        return {}

    def m(fn):
        vals = [fn(g) for g in stats]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "avg_turns": m(lambda g: g.turns),                          # 平均決着ターン
        "first_attack_turn": m(lambda g: g.first_hit_given_turn),   # 攻め始めるターン
        "attacks_per_game": m(lambda g: g.attacks_total),           # 1試合の攻撃回数
        "attacks_landed": m(lambda g: g.attacks_life_hit),          # 相手ライフに通した数
        "ko_dealt": m(lambda g: sum(g.ko_targets.values())),        # 除去した相手キャラ数
        "ko_lost": m(lambda g: sum(g.ko_lost.values())),            # 失った自キャラ数
        "opp_attacks": m(lambda g: g.opp_attacks_total),            # 受けた攻撃回数
        "blocker_uses": m(lambda g: g.blocker_uses),                # ブロッカー使用回数
        "counter_uses": m(lambda g: g.defense_counter_uses),        # カウンター使用回数
    }


def _top_cards(stats: list, main_entries: list, repo, top_n: int = 6) -> list[dict]:
    """よく盤面に出る (= 主戦力) カードを使用率つきで返す (= 記述的、 常に出せる)。"""
    from collections import Counter

    n = len(stats)
    if n < 6:
        return []
    games_with = Counter()
    for g in stats:
        for name in g.cards_played:
            games_with[name] += 1
    # 名前 → main の代表 card_id (画像/表示用)。
    name_to_id: dict[str, str] = {}
    for e in main_entries:
        try:
            c = repo.get(str(e.get("card_id")))
        except KeyError:
            continue
        name_to_id.setdefault(c.name, c.card_id)
    out = []
    for name, gcount in games_with.most_common():
        rate = gcount / n
        if name in name_to_id and rate >= 0.3:  # 3割以上の試合で出る主戦力のみ
            out.append({"card_id": name_to_id[name], "name": name, "play_rate": round(rate, 2)})
        if len(out) >= top_n:
            break
    return out


def _combo_candidates(deck_dict: dict, repo) -> list[dict]:
    """combo_finder が挙げるこのデッキの synergy 候補 (= 2枚以上の組み合わせ) を返す。
    静的なので 1 回だけ計算し、 勝率検証は _validate_combos で行う。"""
    from engine.combo_finder import deck_combo_summary

    deck_cards = []
    for e in deck_dict.get("main", []):
        try:
            deck_cards.append(repo.get(str(e.get("card_id"))))
        except KeyError:
            continue
    leader = None
    try:
        leader = repo.get(deck_dict.get("leader", ""))
    except KeyError:
        pass
    cands: list[dict] = []
    seen: set = set()
    try:
        for ce in deck_combo_summary(deck_cards, leader, top_n=20):
            names: list[str] = []
            for cid in ce.card_ids:
                try:
                    nm = repo.get(cid).name
                    if nm not in names:
                        names.append(nm)
                except KeyError:
                    continue
            if len(names) < 2:  # 2枚以上の組み合わせのみ (= コンボ)
                continue
            key = tuple(sorted(names))
            if key in seen:
                continue
            seen.add(key)
            cands.append({"names": names, "label": getattr(ce, "label", "") or "コンボ"})
    except Exception:
        pass
    return cands


def _validate_combos(stats: list, candidates: list) -> list[dict]:
    """combo 候補を実戦の勝率で検証。 「全部揃った試合」vs「一部だけ/引けなかった試合」の
    勝率差 (= 交絡制御) が大きいものを「勝ちに繋がるコンボ」として返す。"""
    if len(stats) < 12 or not candidates:
        return []

    def wr(gs):
        return sum(1 for g in gs if g.won) / len(gs) if gs else 0.0

    out = []
    for c in candidates:
        names = c["names"]
        both = [g for g in stats if all(g.cards_played.get(n, 0) > 0 for n in names)]
        some = [g for g in stats
                if any(g.cards_played.get(n, 0) > 0 for n in names)
                and not all(g.cards_played.get(n, 0) > 0 for n in names)]
        rest = [g for g in stats if not any(g.cards_played.get(n, 0) > 0 for n in names)]
        if len(both) < 6:
            continue
        # 対照群 = 「一部だけ出た試合」優先 (= ただ札を出した事による交絡を除く)、 無ければ「引けなかった試合」。
        base = some if len(some) >= 6 else (rest if len(rest) >= 6 else None)
        if base is None:
            continue
        gap = wr(both) - wr(base)
        if gap >= 0.12:
            out.append({"cards": names, "label": c["label"], "win_rate": round(wr(both), 3),
                        "base_win_rate": round(wr(base), 3), "n": len(both),
                        "strength": round(gap, 3)})
    out.sort(key=lambda x: -x["strength"])
    return out[:4]


def _structural_guides(comp: dict, curve: dict, main_entries: list, repo) -> list[dict]:
    """序盤の動き方 (#3) と 防御の考え方 (#7) を、 デッキ構造 (archetype/curve/ブロッカー数/
    カウンター総量) から prescriptive に出す。 相関は交絡が強い (劣勢だと守る 等) ので、
    構造ベースで「このタイプのデッキはこう動く/守る」を常に出す方が honest で実用的。"""
    n_blockers = next((r["count"] for r in comp.get("roles", []) if r["role"] == "blocker"), 0)
    counter_total = 0
    for e in main_entries:
        try:
            counter_total += int(getattr(repo.get(str(e.get("card_id"))), "counter", 0) or 0) * int(e.get("count", 1))
        except KeyError:
            continue
    arch = comp.get("archetype", "ミッドレンジ")
    low = curve.get("low", 0)

    # #3 序盤の動き方 (= archetype + 低コスト枚数)。
    if arch == "アグロ":
        seq = (f"序盤から低コスト札（1-2コスト {low}枚）で毎ターン展開し、 盤面を作って一気に攻め切る。 "
               f"手が止まると失速するので、 常に動き続ける。")
    elif arch == "コントロール":
        seq = ("序盤は無理に展開せず、 除去・受け札を構えて相手の攻めをいなす。 リソースを溜めて中盤以降に "
               "主導権を握り、 大型やフィニッシャーで詰める。")
    else:
        seq = (f"序盤は低コスト札（{low}枚）で堅実に展開しつつ、 中盤の主戦力に繋ぐ。 攻めと受けの "
               "バランスを見て、 有利なら押し、 不利なら受けに回る。")

    # #7 防御の考え方 (= archetype 主体。 カウンター総量は全デッキ高く判別に使えないので、
    #    ブロッカー枚数を色付けに、 守り/攻めの方針は archetype で決める)。
    if arch == "コントロール":
        dfn = (f"守りが軸。 ブロッカー {n_blockers}枚とカウンター（総量 {counter_total}）で相手の攻めを捌き、 "
               f"リソース差で勝つ。 序盤はカウンターを温存し、 削られる場面で使って延命する。")
    elif arch == "アグロ":
        dfn = (f"攻めが軸で守りは最小限。 ブロッカー {n_blockers}枚は詰めを遅らせる保険程度で、 基本は先手を"
               f"取って押し切る。 カウンターは無理受けせず、 リーサル回避の一手に絞る。")
    else:
        dfn = (f"攻守バランス型。 ブロッカー {n_blockers}枚で受けつつ、 有利なら攻めに転じる。 カウンター"
               f"（総量 {counter_total}）は要所で使い、 序盤から浪費しない。")

    return [
        {"kind": "sequencing", "title": "序盤の動き方", "detail": seq},
        {"kind": "defense", "title": "防御の考え方", "detail": dfn},
    ]


def _mulligan_guide(stats: list, main_entries: list, repo) -> list[dict]:
    """初手 (マリガン後の開始手札) にあると勝率が上がるカード = キープすべき札 (#1)。

    開始手札は「引いた札」= ほぼ外生 (プレイの選択が入らない) ので、 「出したか」より交絡が
    少なくマリガン指針として素直。 初手にあると勝率が高い札を上位に。"""
    if len(stats) < 16:
        return []

    def wr(gs):
        return sum(1 for g in gs if g.won) / len(gs) if gs else 0.0

    names: list[str] = []
    seen: set = set()
    for e in main_entries:
        try:
            nm = repo.get(str(e.get("card_id"))).name
        except KeyError:
            continue
        if nm not in seen:
            seen.add(nm)
            names.append(nm)

    out = []
    for nm in names:
        with_g = [g for g in stats if nm in getattr(g, "opening_hand", set())]
        without_g = [g for g in stats if nm not in getattr(g, "opening_hand", set())]
        if len(with_g) >= 6 and len(without_g) >= 6:
            gap = wr(with_g) - wr(without_g)
            if gap >= 0.08:
                out.append({"name": nm, "win_rate_with": round(wr(with_g), 3),
                            "win_rate_without": round(wr(without_g), 3), "n": len(with_g),
                            "strength": round(gap, 3)})
    out.sort(key=lambda x: -x["strength"])
    return out[:5]


def _matchup_plans(stats: list) -> list[dict]:
    """相手のアーキタイプ別に「どう戦えば勝つか」を集計する (= #8 相手別プラン)。

    各相手タイプ (アグロ/ミッドレンジ/コントロール) で、 勝率 + 勝ち試合の攻め方 (速攻か
    受けか) を出す。 AI がこのデッキで相手に合わせて立ち回るのに要る情報 = 攻略記事の核。"""
    from collections import defaultdict
    from statistics import mean

    by_arch: dict = defaultdict(list)
    for g in stats:
        arch = getattr(g, "opp_archetype", None)
        if arch:
            by_arch[arch].append(g)

    order = {"アグロ": 0, "ミッドレンジ": 1, "コントロール": 2}
    plans = []
    for arch, games in by_arch.items():
        if len(games) < 10:  # そのタイプの相手が少ない時は出さない
            continue
        won = [g for g in games if g.won]
        lost = [g for g in games if not g.won]
        wr = len(won) / len(games)
        detail = ""
        # 勝ち/負けが両方十分あれば「攻め始めるターン」で勝ち方を導く。
        if len(won) >= 4 and len(lost) >= 4:
            def _fh(xs):
                v = [g.first_hit_given_turn for g in xs if g.first_hit_given_turn is not None]
                return mean(v) if v else None
            wh, lh = _fh(won), _fh(lost)
            if wh is not None and lh is not None:
                if wh <= lh - 0.7:
                    detail = f"勝った試合は平均 {wh:.1f} ターン目から攻めており、 先に詰めるほど勝つ（速攻寄りで対応）。"
                elif wh >= lh + 0.7:
                    detail = f"勝った試合は攻め始めが平均 {wh:.1f} ターンと遅く、 受けて捌いてから攻めるべき（コントロール寄りで対応）。"
        if not detail:
            fh = [g.first_hit_given_turn for g in games if g.first_hit_given_turn is not None]
            avg_fh = mean(fh) if fh else None
            detail = (f"平均 {avg_fh:.1f} ターン目から攻める展開。" if avg_fh else "") + "明確な勝ちパターンはまだ出ていない。"
        plans.append({"archetype": arch, "win_rate": round(wr, 3), "n": len(games), "detail": detail})

    plans.sort(key=lambda p: order.get(p["archetype"], 9))
    return plans


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
                    "先攻できた試合で押し切りやすい。 先攻を取れたら攻めを緩めない。", wf - ws)
            else:
                add("tempo", "後攻から捲る展開が得意",
                    "受けてから返す試合で勝っている。 後攻でも慌てず捌く。", ws - wf)

    # ② 速攻 vs コントロール (= 相手ライフを削り始めたターンで割る)。
    early = [g for g in stats if g.first_hit_given_turn is not None and g.first_hit_given_turn <= 4]
    slow = [g for g in stats if g.first_hit_given_turn is None or g.first_hit_given_turn > 4]
    if len(early) >= MIN_BUCKET and len(slow) >= MIN_BUCKET:
        we, wsl = wr(early), wr(slow)
        if abs(we - wsl) >= 0.12:
            if we > wsl:
                add("playstyle", "先に攻めて削り切る（速攻寄り）",
                    "4ターン目までに相手ライフを削り始めると勝ちやすい。 早く詰めにいく。", we - wsl)
            else:
                add("playstyle", "急がず受けて長期戦（コントロール寄り）",
                    "序盤の無理攻めより、 盤面を整えてから攻めた方が勝てる。", wsl - we)

    # ③ 攻撃の手数 (= 相手ライフに通した攻撃数を中央値で割る)。
    vals = sorted(g.attacks_life_hit for g in stats)
    med = vals[len(vals) // 2]
    hi = [g for g in stats if g.attacks_life_hit > med]
    lo = [g for g in stats if g.attacks_life_hit <= med]
    if len(hi) >= MIN_BUCKET and len(lo) >= MIN_BUCKET and wr(hi) - wr(lo) >= 0.12:
        add("tempo", "攻撃を通す手数が勝敗を分ける",
            "相手ライフへ攻撃を通す手数が多いほど勝ちやすい。 手数が足りないと押し切れない。",
            wr(hi) - wr(lo))

    # ④ 除去 (= 相手キャラを KO できたか)。
    ko = [g for g in stats if sum(g.ko_targets.values()) >= 1]
    noko = [g for g in stats if sum(g.ko_targets.values()) == 0]
    if len(ko) >= MIN_BUCKET and len(noko) >= MIN_BUCKET and wr(ko) - wr(noko) >= 0.12:
        add("removal", "相手キャラをKOできると勝つ（除去が鍵）",
            "相手キャラを除去できた試合で勝ちやすい。 盤面を捌けるかが重要。",
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
        if best and best[0] >= 0.12:
            gap, K, wb, wl = best
            add("key_play", f"{name} は {K} ターン目までに着地させたい",
                f"{K}ターン目までに {name} を着地させると機能しやすい。 遅れると活かせない。",
                gap)
            continue
        wg = [g for g in stats if g.cards_played.get(name, 0) > 0]
        wo = [g for g in stats if g.cards_played.get(name, 0) == 0]
        if len(wg) >= MIN_BUCKET and len(wo) >= MIN_BUCKET and wr(wg) - wr(wo) >= 0.12:
            add("key_card", f"{name} の着地が生命線",
                f"{name} を盤面に出せるかが機能条件。 出せない試合は苦しい。",
                wr(wg) - wr(wo))

    # 効果量の大きい順 (= 強い相関を優先) に上位を採用。
    out.sort(key=lambda x: -x["strength"])
    return out[:7]


def _assemble_report(comp: dict, curve: dict, matchups: list, n_games: int,
                     n_opponents: int, rhash: str, *, partial: bool,
                     insights: Optional[list] = None, profile: Optional[dict] = None,
                     top_cards: Optional[list] = None, matchup_plans: Optional[list] = None,
                     win_combos: Optional[list] = None, mulligan: Optional[list] = None,
                     guides: Optional[list] = None, challenges: Optional[list] = None) -> dict:
    """計算済みの部分/全体から report dict を組む (= 途中経過も同じ形で保存できる)。"""
    # ミラーは対称で ~50% なので メタ相性の平均/ベスト/ワースト からは除く (= 表には出す)。
    played = [x for x in matchups if x.get("n") and x.get("slug") != "__mirror__"]
    avg = round(sum(x["win_rate"] for x in played) / len(played), 3) if played else 0.0
    ranked = sorted(played, key=lambda x: -x["win_rate"])
    summary = {
        "avg": avg,
        "best": ranked[:3],
        "worst": list(reversed(ranked[-3:])) if len(ranked) >= 3 else [],
    }
    return {
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ai_version": "ExploitBeam_deployed",
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
        "profile": profile or {},      # 回り方サマリ (= 勝敗に依らず常に出る記述統計)
        "top_cards": top_cards or [],  # よく盤面に出る主戦力カード (使用率つき)
        "matchup_plans": matchup_plans or [],  # ⭐ 相手タイプ別の立ち回り (#8)
        "win_combos": win_combos or [],        # ⭐ 勝ちに繋がるコンボ (#5)
        "mulligan": mulligan or [],            # ⭐ 初手キープすべき札 (#1)
        "guides": guides or [],                # ⭐ 序盤の動き方(#3) + 防御の考え方(#7) prescriptive
        "challenges": challenges or [],        # ⭐ 惜しい負けを同じ引きで攻略「どう指せば勝てたか」
        "partial": partial,            # True = まだ全マッチアップ揃っていない
    }


def deployed_ai_factory(rng, deck_analysis=None):
    """配備 = 現最強AI (= 人間が実際に戦う ExploitBeam) と同一 factory。
    分析の base も challenge の相手も これで揃える (= GoalDirected baseline は使わない)。"""
    from engine.exploit_beam_ai import ExploitBeamAI
    return ExploitBeamAI(rng=rng, deck_analysis=deck_analysis)


def _win_line_summary(gs, gr) -> str:
    """勝ち筋の型 (速攻/除去/手数) + 決着ターンを短く要約 (= 分岐点の後の流れ)。"""
    t = gr.turns
    fh = getattr(gs, "first_hit_given_turn", None)
    atk = getattr(gs, "attacks_life_hit", 0) or 0
    ko = sum(gs.ko_targets.values()) if getattr(gs, "ko_targets", None) else 0
    if fh is not None and fh <= 4 and atk >= 2:
        core = f"{fh}ターン目から攻めて相手ライフへ {atk} 回通す"
    elif ko >= 2:
        core = f"相手キャラを {ko} 体除去して盤面を捌く"
    elif atk >= 2:
        core = f"相手ライフへ {atk} 回攻撃を通す"
    else:
        core = "盤面を作って詰める"
    return f"以降は {core}流れで {t}ターンに決着。"


_HERO_DECISION_RE = re.compile(r"T(\d+) (P[01]):\s*(play: |event: |起動メイン: |atk: )(.*)")


def _hero_decisions(log, hero_seat: int) -> list:
    """log から hero (= P{seat}) の意思決定 (play/event/起動/攻撃) を (turn, kind, 要約) で抽出。"""
    seat = f"P{hero_seat}"
    out: list = []
    for line in log or []:
        m = _HERO_DECISION_RE.match(line)
        if not m or m.group(2) != seat:
            continue
        turn, verb, rest = int(m.group(1)), m.group(3), m.group(4)
        if verb == "play: ":
            out.append((turn, "play", f"{rest.split(' (cost')[0].strip()}をプレイ"))
        elif verb == "event: ":
            out.append((turn, "event", f"{rest.split(' (cost')[0].strip()}を使用"))
        elif verb == "起動メイン: ":
            out.append((turn, "act", f"{rest.strip()}の効果を起動"))
        elif verb == "atk: ":
            atkr = rest.split("(P=")[0].strip()
            tgt = rest.split("-> ")[-1].split("(P=")[0].strip() if "-> " in rest else "?"
            out.append((turn, "atk", f"{atkr}で{tgt}を攻撃"))
    return out


def _pivotal_move(loss_log, win_log, hero_seat: int, win_gs, win_gr) -> str:
    """負け筋と勝ち筋 (= 同じ引き) の hero 意思決定を先頭から比べ、 最初に食い違ったターン
    (= 分岐点) を「どう指せば勝てたか」として言語化する (= 集約でなく具体的な一手)。"""
    ld = _hero_decisions(loss_log, hero_seat)
    wd = _hero_decisions(win_log, hero_seat)
    tail = _win_line_summary(win_gs, win_gr)
    piv = None
    for i in range(min(len(ld), len(wd))):
        if ld[i][1:] != wd[i][1:]:      # kind+要約 が最初に違う点 = 分岐
            piv = (ld[i], wd[i])
            break
    if piv is None and len(wd) > len(ld):
        piv = (None, wd[len(ld)])       # 負け筋には無い一手を勝ち筋が指した
    if piv is None:
        return f"同じ引きでも、 指し回しを変えれば勝てる。 {tail}"
    loss_d, win_d = piv
    wt = win_d[0]
    if loss_d is None:
        return f"分岐は{wt}ターン目。 手を止めず「{win_d[2]}」と動くと勝てる。 {tail}"
    return f"分岐は{wt}ターン目。 「{loss_d[2]}」ではなく「{win_d[2]}」と指すと勝てる。 {tail}"


def _challenge_losses(user_dl, lost_games: list, n_games: int, repo, k: int = 5) -> list:
    """惜しい負け (= 現最強AI が詰め切れず負けた試合) を、 同じ引き (seed) のまま 探索を
    変えた強AI 群で指し直し、 勝てる筋があるかを探る (= 反実仮想「どう指せば勝てたか」)。

    - base (= 分析本体) も 相手も 現最強 ExploitBeam。 負け = 強AI でも落とした本物の負け。
    - challenge = 同じ引きを、 探索を変えた ExploitBeam 4 通り (広く読む / 深く読む / 別筋を
      サンプル) で指し直す。 どれかが勝てば「その引きに勝ち筋あり」。 = ユーザーの「同じ seed で
      5 戦」。 相手は base のまま (= 引き固定、 自分の指し手だけ変える)。
    - how_to_win = 負け筋と勝ち筋の意思決定を diff し、 分岐点の具体的な一手を出す。
    """
    if not lost_games:
        return []
    from engine.harness import run_matchup
    from engine.exploit_beam_ai import ExploitBeamAI
    from engine.log_analyzer import parse_game_log

    def _mk(**kw):
        return lambda rng, deck_analysis=None: ExploitBeamAI(rng=rng, deck_analysis=deck_analysis, **kw)

    base_factory = _mk()  # 配備既定 (= 負けを喫した本体)
    # 同じ引きで別の勝ち筋を探す探索バリエーション (= 広く/深く/別筋)。
    variants = [
        _mk(beam_width=28),                              # 広く読む
        _mk(postopp_turns=2),                            # 深く読む (相手2ターン先)
        _mk(postopp_turns=2, postopp_self_value=True),   # 自分の未来ターンも value 誘導
        _mk(beam_width=24, plan_temperature=0.8),        # 別の筋をサンプル
    ]

    picks = sorted(lost_games, key=lambda x: x["opp_life"])[:k]
    out: list = []
    for lg in picks:
        opp = lg["opp"]
        hero_seat = lg.get("first_player", 0)
        loss_log = lg.get("loss_log") or []
        won_gr = None
        for vf in variants:
            try:
                r2 = run_matchup(
                    user_dl, opp["decklist"], n_games=n_games, seed=lg["seed"],
                    only_game_index=lg["gi"], ai_factory_1=vf, ai_factory_2=base_factory,
                    time_limit_turns=40, time_limit_mode="both_lose", keep_logs=True,
                )
                g2 = r2.games[lg["gi"]]
            except Exception:
                continue
            if g2.winner == 0:   # deck1 (= 自分) 勝ち
                won_gr = g2
                break
        entry = {
            "opponent": opp["name"],
            "opp_leader": opp.get("leader_name") or opp["name"],
            "opp_archetype": opp.get("archetype", ""),
            "loss_margin": int(lg["opp_life"]),  # 負けた時の相手ライフ残り (= 小さいほど惜しい)
            "winnable": won_gr is not None,
        }
        if won_gr is not None:
            try:
                win_gs = parse_game_log(won_gr.log, hero_seat, won_gr.turns, hero_seat)
                entry["how_to_win"] = _pivotal_move(loss_log, won_gr.log, hero_seat, win_gs, won_gr)
            except Exception:
                entry["how_to_win"] = "同じ引きでも、 指し回しを変えれば勝てる。"
        out.append(entry)
    return out


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
    combo_cands = _combo_candidates(deck_dict, repo)  # 静的なので 1 回だけ
    guides = _structural_guides(comp, curve, main, repo)  # 構造ベース (#3/#7)、 1 回だけ

    user_dl = make_deck_from_dict(deck_dict, repo)
    # ミラー (= 自分 vs 自分) も疑似相手として調査対象に。 先攻/後攻の有利や自デッキの
    # 自然な回り方が分かり、 行動データ (戦略洞察/コンボ/マリガン) も増える。
    mirror_opp = {
        "slug": "__mirror__", "name": "ミラー（自分自身）", "leader": deck_dict.get("leader", ""),
        "leader_name": "", "archetype": comp["archetype"],
        "decklist": make_deck_from_dict(deck_dict, repo),
    }
    metas = list(_load_meta_decklists(repo)) + [mirror_opp]
    n_opponents = len(metas)
    done_map = {m["slug"]: m for m in (done_matchups or []) if m.get("n")}

    matchups: list[dict] = []
    stats_accum: list = []  # 全試合の GameStats (= 戦略探索の素材、 matchup 計算を再利用)
    lost_games: list = []   # 負けた試合の再現情報 (= 後で ExploitBeam で「どう指せば勝てたか」攻略)
    for i, m in enumerate(metas):
        if m["slug"] in done_map:
            matchups.append(done_map[m["slug"]])  # 再開: 計算済みは skip
        else:
            # keep_logs=True で試合ログを取り、 戦い方の傾向を発掘する (= 追加試合なし)。
            # 両サイド 現最強 ExploitBeam (= 人間が実際に戦う配備AIと同一)。 GoalDirected baseline
            # では「弱い操縦」の傾向になり、 負け=操縦ミスと本物の負けが区別できないため。
            rep = run_matchup(
                user_dl, m["decklist"], n_games=n_games, seed=seed + i,
                ai_factory_1=deployed_ai_factory, ai_factory_2=deployed_ai_factory,
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
            for gi, gr in enumerate(rep.games):
                try:
                    hero_idx = gr.first_player
                    if gr.winner == -1:
                        winner_pidx = -1
                    elif gr.winner == 0:            # deck1 (hero) 勝ち
                        winner_pidx = hero_idx
                    else:                           # deck2 勝ち
                        winner_pidx = 1 - hero_idx
                    # 負け試合 (= deck2 勝ち) を再現情報付きで記録 (ミラーは除く)。
                    # opp_life = 負けた時の相手ライフ残り (= 小さいほど「詰め切れず惜しい」)。
                    if gr.winner == 1 and m["slug"] != "__mirror__":
                        opp_life = gr.p1_life_left if hero_idx == 0 else gr.p0_life_left
                        # loss_log = 現最強AIがこの引きでどう負けたか (= 分岐点 diff の対照)。
                        lost_games.append({"opp": m, "seed": seed + i, "gi": gi,
                                           "opp_life": opp_life, "first_player": gr.first_player,
                                           "loss_log": list(gr.log or [])})
                    gs = parse_game_log(gr.log, winner_pidx, gr.turns, hero_idx)
                    gs.went_first = (gr.first_player == 0)  # hero(deck1) が先攻だったか
                    gs.opp_archetype = m.get("archetype")   # 相手別プランのグループキー
                    # 開始手札 (= hero の card_id → name の set)。 マリガン分析用。
                    try:
                        oh = gr.opening_hands[hero_idx] if gr.opening_hands else []
                        gs.opening_hand = {repo.get(cid).name for cid in oh if cid}
                    except Exception:
                        gs.opening_hand = set()
                    stats_accum.append(gs)
                except Exception:
                    continue
            if pause_between:
                time.sleep(pause_between)
        if on_progress:
            insights = _mine_strategy(stats_accum, comp["key_cards"])
            profile = _deck_profile(stats_accum)
            top = _top_cards(stats_accum, main, repo)
            plans = _matchup_plans(stats_accum)
            combos = _validate_combos(stats_accum, combo_cands)
            mull = _mulligan_guide(stats_accum, main, repo)
            on_progress(i + 1, n_opponents, m["name"],
                        _assemble_report(comp, curve, matchups, n_games, n_opponents,
                                         recipe_hash, partial=(i + 1 < n_opponents),
                                         insights=insights, profile=profile, top_cards=top,
                                         matchup_plans=plans, win_combos=combos, mulligan=mull,
                                         guides=guides))

    insights = _mine_strategy(stats_accum, comp["key_cards"])
    profile = _deck_profile(stats_accum)
    top = _top_cards(stats_accum, main, repo)
    plans = _matchup_plans(stats_accum)
    combos = _validate_combos(stats_accum, combo_cands)
    mull = _mulligan_guide(stats_accum, main, repo)
    # 惜しい負けの攻略 (= 同じ引きを強い探索AIで指し直して勝てるか)。 最後に数件だけ実行。
    try:
        challenges = _challenge_losses(user_dl, lost_games, n_games, repo, k=5)
    except Exception:
        challenges = []
    return _assemble_report(comp, curve, matchups, n_games, n_opponents, recipe_hash,
                            partial=False, insights=insights, profile=profile, top_cards=top,
                            matchup_plans=plans, win_combos=combos, mulligan=mull, guides=guides,
                            challenges=challenges)
