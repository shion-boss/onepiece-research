# -*- coding: utf-8 -*-
"""
メタデッキ分析 + 自動構築ヒント生成 (2026-05-14)
=================================================

16 active + 88 historical recipes の特徴を抽出し、 勝率との相関から
「強いデッキの共通要素」 を特定する。

入力:
- `decks/cardrush_*.json` + `decks/tcgportal_*.json` (= active 16)
- `decks/_archive/cardrush_raw/cardrush_*.json` (= historical 88)
- `db/matchup_matrix.bug_baseline_v1.json` (= 旧 AI 勝率データ)
- `db/card_role.json` (= 役割タグ)
- `db/cards.json` (= カード DB)

出力:
- `db/meta_deck_analysis.json`: per-deck 特徴 + 統計
- `docs/DECK_CONSTRUCTION_HINTS.md`: 人間レビュー用レポート

実行:
    .venv/bin/python scripts/analyze_meta_decks.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_cards_db() -> dict:
    """cards.json を card_id → card dict にロード。"""
    data = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in data}


def load_card_role_db() -> dict:
    """card_roles.json をロード。"""
    p = ROOT / "db" / "card_roles.json"
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    # 形式: {"cards": {card_id: {primary_role, tags, ...}, ...}} or
    #       {card_id: {primary_role, ...}, ...}
    if isinstance(raw, dict):
        if "cards" in raw and isinstance(raw["cards"], dict):
            return raw["cards"]
        return raw
    return {}


def load_deck_files() -> list[dict]:
    """active + archive の全 deck recipe をロード。"""
    out = []
    for p in sorted((ROOT / "decks").glob("cardrush_*.json")):
        if ".analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["__path"] = str(p.relative_to(ROOT))
            d["__active"] = True
            out.append(d)
        except Exception:
            pass
    for p in sorted((ROOT / "decks").glob("tcgportal_*.json")):
        if ".analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["__path"] = str(p.relative_to(ROOT))
            d["__active"] = True
            out.append(d)
        except Exception:
            pass
    raw_dir = ROOT / "decks" / "_archive" / "cardrush_raw"
    if raw_dir.exists():
        for p in sorted(raw_dir.glob("cardrush_*.json")):
            if ".analysis" in p.name:
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                d["__path"] = str(p.relative_to(ROOT))
                d["__active"] = False
                out.append(d)
            except Exception:
                pass
    return out


def load_winrates() -> dict[str, float]:
    """bug_baseline matrix から deck-level 勝率を計算。"""
    p = ROOT / "db" / "matchup_matrix.bug_baseline_v1.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for row in doc.get("matrix", []):
        slug = row.get("deck_a")
        wrs = [c.get("winrate") for c in row.get("row", []) if c.get("winrate") is not None]
        if wrs:
            out[slug] = sum(wrs) / len(wrs)
    return out


def _to_int(v, default=0):
    if v is None or v == "" or v == "-":
        return default
    try:
        return int(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return default


def extract_features(deck: dict, cards_db: dict, role_db: dict) -> dict:
    """1 deck の特徴を抽出。"""
    main = deck.get("main", [])
    total_cards = sum(c.get("count", 0) for c in main)
    if total_cards == 0:
        return {}

    # cost curve
    cost_curve: dict[int, int] = defaultdict(int)
    # counter
    counter_total = 0
    n_1k = n_2k = n_0c = 0
    # blocker / role
    blocker_count = 0
    role_dist: dict[str, int] = defaultdict(int)
    # feature 集約
    feature_count: Counter = Counter()
    # color
    color_count: Counter = Counter()
    # card uniqueness
    counts_per_card = Counter()
    # 0-cost event
    free_event_count = 0
    # category 分布
    cat_dist: dict[str, int] = defaultdict(int)

    for entry in main:
        cid = entry.get("card_id")
        cnt = entry.get("count", 0)
        if not cid or cnt <= 0:
            continue
        card = cards_db.get(cid)
        if not card:
            continue
        cost = _to_int(card.get("cost"))
        counter = _to_int(card.get("counter"))
        cost_curve[min(cost, 6)] += cnt
        counter_total += counter * cnt
        if counter == 1000:
            n_1k += cnt
        elif counter == 2000:
            n_2k += cnt
        elif counter == 0:
            n_0c += cnt

        text = card.get("text") or ""
        if "ブロッカー" in text and "解除" not in text:
            blocker_count += cnt

        # role
        rinfo = role_db.get(cid)
        if isinstance(rinfo, dict):
            role = rinfo.get("primary_role", "unknown")
            role_dist[role] += cnt
        else:
            role_dist["unknown"] += cnt

        # feature
        features_raw = card.get("features") or ""
        for feat in features_raw.split("/"):
            f = feat.strip()
            if f:
                feature_count[f] += cnt

        # color
        color_raw = card.get("color") or ""
        for col in color_raw.split("/"):
            c = col.strip()
            if c:
                color_count[c] += cnt

        counts_per_card[cnt] += 1

        cat = (card.get("category") or "").upper()
        cat_dist[cat] += cnt

        # 0-cost event
        if cat == "EVENT" and cost == 0:
            free_event_count += cnt

    n_card_types = sum(counts_per_card.values())
    # synergy density: top feature の枚数比率
    if feature_count:
        top_feature, top_feature_count = feature_count.most_common(1)[0]
        synergy_density = top_feature_count / total_cards
    else:
        top_feature, top_feature_count = "", 0
        synergy_density = 0.0

    # color cohesion: dominant color の比率 (= 1.0 = 単色)
    if color_count:
        dom_color_count = color_count.most_common(1)[0][1]
        color_cohesion = dom_color_count / total_cards
    else:
        color_cohesion = 0.0

    avg_cost = sum(c * n for c, n in cost_curve.items()) / total_cards

    return {
        "total_cards": total_cards,
        "cost_curve": dict(cost_curve),
        "avg_cost": round(avg_cost, 2),
        "counter_total": counter_total,
        "n_1k_counter": n_1k,
        "n_2k_counter": n_2k,
        "n_0_counter": n_0c,
        "blocker_count": blocker_count,
        "free_event_count": free_event_count,
        "role_distribution": dict(role_dist),
        "category_distribution": dict(cat_dist),
        "top_feature": top_feature,
        "top_feature_count": top_feature_count,
        "synergy_density": round(synergy_density, 3),
        "color_distribution": dict(color_count),
        "color_cohesion": round(color_cohesion, 3),
        "n_card_types": n_card_types,
        "card_count_distribution": dict(counts_per_card),
    }


def pearson_correlation(x: list[float], y: list[float]) -> float:
    """Pearson 相関係数 (= -1.0〜1.0)。"""
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = mean(x)
    my = mean(y)
    sx = sum((xi - mx) ** 2 for xi in x) ** 0.5
    sy = sum((yi - my) ** 2 for yi in y) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    return cov / (sx * sy)


def analyze_correlations(
    active_features: list[dict],
    winrates: dict[str, float],
) -> dict[str, float]:
    """各 numeric 特徴の勝率との相関を計算。"""
    # active deck のみ (= winrate あり)
    aligned = [
        (f, winrates.get(f["__slug"]))
        for f in active_features
        if f["__slug"] in winrates
    ]
    if len(aligned) < 3:
        return {}

    numeric_keys = [
        "avg_cost", "counter_total", "n_1k_counter", "n_2k_counter",
        "n_0_counter", "blocker_count", "free_event_count",
        "synergy_density", "color_cohesion",
    ]
    corrs: dict[str, float] = {}
    for k in numeric_keys:
        xs = [f[k] for f, _ in aligned]
        ys = [w for _, w in aligned]
        corrs[k] = round(pearson_correlation(xs, ys), 3)
    # role 別密度
    role_keys = set()
    for f, _ in aligned:
        role_keys.update(f.get("role_distribution", {}).keys())
    for role in sorted(role_keys):
        xs = [f.get("role_distribution", {}).get(role, 0) for f, _ in aligned]
        ys = [w for _, w in aligned]
        corrs[f"role_{role}_count"] = round(pearson_correlation(xs, ys), 3)
    return corrs


def find_top_bottom_differences(
    active_features: list[dict],
    winrates: dict[str, float],
    top_n: int = 5,
    bottom_n: int = 5,
) -> dict:
    """上位 N vs 下位 N の特徴差分。"""
    aligned = sorted(
        [(f, winrates.get(f["__slug"], 0.0)) for f in active_features if f["__slug"] in winrates],
        key=lambda x: -x[1],
    )
    top = aligned[:top_n]
    bottom = aligned[-bottom_n:]
    keys = [
        "avg_cost", "counter_total", "n_1k_counter", "n_2k_counter",
        "blocker_count", "free_event_count", "synergy_density",
        "color_cohesion",
    ]
    diff: dict[str, dict] = {}
    for k in keys:
        top_vals = [f[k] for f, _ in top]
        bot_vals = [f[k] for f, _ in bottom]
        diff[k] = {
            "top_avg": round(mean(top_vals), 3) if top_vals else 0,
            "bottom_avg": round(mean(bot_vals), 3) if bot_vals else 0,
            "top_minus_bottom": round(mean(top_vals) - mean(bot_vals), 3) if top_vals and bot_vals else 0,
        }
    return {
        "top_5_slugs": [f["__slug"] for f, _ in top],
        "bottom_5_slugs": [f["__slug"] for f, _ in bottom],
        "feature_differences": diff,
    }


def render_markdown_report(
    features: list[dict],
    correlations: dict[str, float],
    differences: dict,
    winrates: dict[str, float],
) -> str:
    """人間レビュー用 markdown レポートを生成。"""
    lines = []
    lines.append("# メタデッキ分析レポート (= 強デッキ共通要素)\n")
    lines.append("> 2026-05-14 自動生成。 `db/matchup_matrix.bug_baseline_v1.json` (= 旧 AI matrix)")
    lines.append("> を勝率データとして使用。 16 active + 88 historical recipe を分析。\n")

    lines.append("## 1. 勝率順 (= bug_baseline、 active 16)\n")
    lines.append("| 順位 | slug | 勝率 | archetype |")
    lines.append("|---|---|---|---|")
    aligned = sorted(
        [(f, winrates.get(f["__slug"], 0.0)) for f in features if f["__slug"] in winrates],
        key=lambda x: -x[1],
    )
    for i, (f, w) in enumerate(aligned, 1):
        lines.append(f"| {i} | {f['__slug']} | {w*100:.1f}% | {f.get('__name', '?')} |")
    lines.append("")

    lines.append("## 2. 勝率との相関 (= Pearson r)\n")
    lines.append("正の値: 上昇要因、 負の値: 低下要因。 |r| ≥ 0.3 で意味のある関係。\n")
    lines.append("| 特徴 | 相関 | 解釈 |")
    lines.append("|---|---|---|")
    sorted_corrs = sorted(correlations.items(), key=lambda x: -abs(x[1]))
    for key, val in sorted_corrs:
        strength = ""
        if abs(val) >= 0.5:
            strength = "🔥 強い相関"
        elif abs(val) >= 0.3:
            strength = "⚡ 中程度"
        elif abs(val) >= 0.15:
            strength = "弱い相関"
        else:
            strength = "ほぼ無相関"
        sign = "+" if val > 0 else ""
        lines.append(f"| {key} | {sign}{val} | {strength} |")
    lines.append("")

    lines.append("## 3. 上位 5 vs 下位 5 の差分\n")
    lines.append(f"上位: {', '.join(differences['top_5_slugs'])}")
    lines.append(f"下位: {', '.join(differences['bottom_5_slugs'])}\n")
    lines.append("| 特徴 | 上位平均 | 下位平均 | 差 (top - bottom) |")
    lines.append("|---|---|---|---|")
    for key, vals in differences.get("feature_differences", {}).items():
        sign = "+" if vals["top_minus_bottom"] > 0 else ""
        lines.append(f"| {key} | {vals['top_avg']} | {vals['bottom_avg']} | {sign}{vals['top_minus_bottom']} |")
    lines.append("")

    lines.append("## 4. 強デッキの共通要素 (= 推測される構築指針)\n")
    lines.append("上記相関 + 差分から、 強いデッキに共通する要素を推測:\n")
    # 強い正相関の特徴を箇条書き
    pos_strong = [k for k, v in correlations.items() if v >= 0.3]
    neg_strong = [k for k, v in correlations.items() if v <= -0.3]
    if pos_strong:
        lines.append("**+: 多いほど勝率高い (= 増やすべき)**")
        for k in pos_strong:
            lines.append(f"  - {k} (r = {correlations[k]:+.2f})")
    if neg_strong:
        lines.append("")
        lines.append("**-: 多いほど勝率低い (= 抑えるべき)**")
        for k in neg_strong:
            lines.append(f"  - {k} (r = {correlations[k]:+.2f})")
    lines.append("")

    lines.append("## 5. 自動デッキ構築ヒント\n")
    lines.append("`engine/deckbuilder.py` への target 値:\n")
    # 上位 5 の平均値 → target
    top_5 = aligned[:5]
    lines.append("| 特徴 | 上位平均 (= target) | 推奨値範囲 |")
    lines.append("|---|---|---|")
    for k, vals in differences.get("feature_differences", {}).items():
        top_avg = vals["top_avg"]
        std_estimate = abs(vals["top_minus_bottom"]) * 0.3
        low = max(0, top_avg - std_estimate)
        high = top_avg + std_estimate
        lines.append(f"| {k} | {top_avg} | [{low:.1f}, {high:.1f}] |")
    lines.append("")

    lines.append("## 6. 注意事項 (= 解釈の限界)\n")
    lines.append("- サンプル数 16 active deck のみで相関を計算 → 統計的有意性は限定的")
    lines.append("- bug_baseline matrix は 旧 AI 同士の勝率 (= 真の Tier ではない)")
    lines.append("- Phase 7 full matrix 完了後に再分析推奨 (= AI 強化で勝率の意味が変わる)")
    lines.append("- 個別 deck の構築理由 (= テクニカルプレイ前提) は反映されない")
    lines.append("")

    return "\n".join(lines)


def main():
    print("=== メタデッキ分析開始 ===\n")
    cards_db = load_cards_db()
    role_db = load_card_role_db()
    decks = load_deck_files()
    winrates = load_winrates()
    print(f"  cards.json: {len(cards_db)} cards")
    print(f"  card_role.json: {len(role_db)} entries")
    print(f"  decks: {len(decks)} (active={sum(1 for d in decks if d.get('__active'))})")
    print(f"  winrates: {len(winrates)} decks")
    print()

    # 各 deck の特徴抽出
    features = []
    for d in decks:
        feat = extract_features(d, cards_db, role_db)
        if not feat:
            continue
        path = Path(d["__path"])
        feat["__slug"] = path.stem
        feat["__name"] = d.get("name", "?")
        feat["__active"] = d.get("__active", False)
        feat["__source"] = d.get("source", "?")[:80]
        features.append(feat)

    print(f"  特徴抽出完了: {len(features)} deck")

    # active deck のみで相関分析
    active = [f for f in features if f.get("__active")]
    correlations = analyze_correlations(active, winrates)
    print(f"  相関分析: {len(correlations)} 指標 vs 勝率")

    differences = find_top_bottom_differences(active, winrates)

    # 出力
    out_json = {
        "computed_at": "2026-05-14T17:50:00Z",
        "n_features_analyzed": len(features),
        "n_active": len(active),
        "n_with_winrate": sum(1 for f in active if f["__slug"] in winrates),
        "correlations": correlations,
        "differences": differences,
        "per_deck": features,
    }
    out_path = ROOT / "db" / "meta_deck_analysis.json"
    out_path.write_text(json.dumps(out_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_path.relative_to(ROOT)}")

    # markdown report
    md = render_markdown_report(features, correlations, differences, winrates)
    md_path = ROOT / "docs" / "DECK_CONSTRUCTION_HINTS.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"  → {md_path.relative_to(ROOT)}")
    print()
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
