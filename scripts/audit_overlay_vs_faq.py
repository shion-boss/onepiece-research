# -*- coding: utf-8 -*-
"""
overlay vs FAQ 突合監査スクリプト
================================

目的:
    `db/card_effects.json` の効果オーバーレイを、 公式 FAQ (`db/faq/cardqa_*.json`)
    と突合し、 解釈の不一致候補を洗い出す。

    現在のオーバーレイは 15 メタリーダー以外は自動生成されているため、 公式 Q&A の
    解釈と微妙にズレている可能性がある。 このスクリプトは「Q&A で言及されているのに
    overlay に対応する仕組みが無い」 ようなカードを surface することで、 手動レビューの
    優先度付けを支援する。

使い方:
    .venv/bin/python scripts/audit_overlay_vs_faq.py
    # → db/overlay_audit.md (Markdown レポート)
    # → db/overlay_audit.json (JSON データ、 後続加工用)

ロジック:
    1. cardqa_*.json から全 Q&A を集約
    2. Q+A テキストから card_id (OP/ST/EB/PRB/P-NNN) を正規表現抽出
    3. 各 card_id について overlay を引き、 効果 + 公式テキスト + 関連 Q&A を並べる
    4. 不審ヒューリスティック:
       - 公式テキストに 「【起動メイン】」 と書かれてるのに overlay に when=activate_main が無い
       - 公式テキストに 「【ターン1回】」 が含まれるのに overlay の cost に once_per_turn が無い
       - 公式テキストに 「自分のターン中」 「相手のターン中」 が含まれるのに overlay の if に対応条件が無い
       - Q&A が 「いいえ、できません」 と否定しているがその否定対象が overlay に書かれている可能性
       - Q&A 数 ≥ 3 件のカード = 公式が説明したかった = 注目度高い
    5. 不審度スコア順にソートして出力

注意: これは候補 surface ツールであって、 全件レビューを置換するものではない。
      ヒューリスティックは false positive 多め設計 (見逃しを避ける)。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDQA_DIR = ROOT / "db" / "faq"
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
OUTPUT_MD = ROOT / "db" / "overlay_audit.md"
OUTPUT_JSON = ROOT / "db" / "overlay_audit.json"

# card_id 正規表現: OPxx-yyy / STxx-yyy / EBxx-yyy / PRBxx-yyy / P-yyy
CARD_ID_RE = re.compile(r"\b(OP|ST|EB|PRB)(\d{1,2})-(\d{3})\b|\bP-(\d{3})\b")


def extract_card_ids(text: str) -> set[str]:
    out: set[str] = set()
    for m in CARD_ID_RE.finditer(text):
        if m.group(4):  # P-NNN
            out.add(f"P-{m.group(4)}")
        else:
            prefix, num1, num2 = m.group(1), m.group(2), m.group(3)
            out.add(f"{prefix}{num1.zfill(2)}-{num2}")
    return out


def load_all_qa() -> dict[str, list[dict]]:
    """各 cardqa_*.json を読み、 card_id → Q&A 群 を返す。"""
    qa_by_card: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(CARDQA_DIR.glob("cardqa_*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        series = data.get("series_slug") or f.stem
        for item in data.get("items", []):
            q = item.get("q", "")
            a = item.get("a", "")
            ids = extract_card_ids(q + " " + a)
            for cid in ids:
                qa_by_card[cid].append({"q": q, "a": a, "source": series})
    return qa_by_card


def load_cards() -> dict[str, dict]:
    with open(CARDS_JSON, encoding="utf-8") as fh:
        cards = json.load(fh)
    return {c["card_id"]: c for c in cards}


def load_overlay() -> dict[str, list[dict]]:
    with open(OVERLAY_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def overlay_when_set(effects: list[dict]) -> set[str]:
    return {e.get("when") for e in effects if isinstance(e, dict) and e.get("when")}


def overlay_has_once_per_turn(effects: list[dict]) -> bool:
    """cost.once_per_turn (= activate_main / on_attack の所有コスト) もしくは
    top-level once_per_turn (= 任意 when の trigger ガード) のどちらかが指定されているか判定。"""
    for e in effects:
        if not isinstance(e, dict):
            continue
        cost = e.get("cost") or {}
        if cost.get("once_per_turn"):
            return True
        # top-level (= cost 不要の trigger ガード、 engine の _check_and_set_once_per_turn 経由)
        if e.get("once_per_turn"):
            return True
    return False


# R2 拡張で engine 側に追加された新規 cost / trigger / primitive。
# audit が「未知のキー」 と勘違いしないように知識として記録。
# (audit が能動的にチェックする訳ではなく、 ドキュメンテーション目的。)
R2_KNOWN_COST_KEYS = {
    # filter 付き discard (= 「特徴X を持つカード N 枚を捨てる」)
    "discard_hand_with_filter",
    # name 一致キャラ/ステージを rest (= 「自分の『X』1 枚をレストにできる」)
    "rest_self_target_name",
    "rest_self_target",  # alias
}
R2_KNOWN_WHEN_VALUES = {
    # KO された側 (自陣) の場効果発火 (OP10-042 ウソップ等)
    "on_self_chara_ko",
    # 相手が EVENT/COUNTER/【トリガー】 を発動した時 (OP11-102 ケイミー等)
    "opp_event_or_trigger_fired",
}
R2_KNOWN_PRIMITIVE_KEYS = {
    # 名前フィルタ付き taunt (OP01-051 ユースタス・キッド系)
    "cannot_attack_target_except",
    # filter 付き base_cost 静的変更 (OP10-042 ウソップ系)
    "set_base_cost_filtered_static",
}
R2_KNOWN_OPTIONAL_COST_PRIMITIVES = {
    # optional_cost_then.cost で扱える追加 primitive (R2)
    "return_self_don_to_deck",
    "power_pump",  # 弱体化 (リーダーパワー -N) cost
    "rest_self_target_name",
    "discard_hand_with_filter",
}
R2_KNOWN_FILTER_KEYS = {
    # 特徴 OR フィルタ (= 「特徴《魚人族》か《人魚族》」 等)
    "feature_in",
}


def overlay_if_keys(effects: list[dict]) -> set[str]:
    keys: set[str] = set()
    for e in effects:
        if not isinstance(e, dict):
            continue
        cond = e.get("if") or {}
        keys.update(cond.keys())
    return keys


SIMPLIFIED_MARKERS = ("fallback", "簡略", "auto", "省略", "近似", "自動抽出")


def has_simplified_marker(effects: list[dict]) -> bool:
    """overlay に simplification marker (= 公式テキスト忠実でない兆候) があるか?"""
    for e in effects:
        if not isinstance(e, dict):
            continue
        text = e.get("_text", "") or ""
        if any(m in text for m in SIMPLIFIED_MARKERS):
            return True
    return False


def detect_issues(card: dict, effects: list[dict], qa_list: list[dict]) -> list[str]:
    """不審ヒューリスティック検出。 返り値は issue タグ。"""
    issues: list[str] = []
    text = card.get("text") or ""
    when_set = overlay_when_set(effects)
    cond_keys = overlay_if_keys(effects)

    # === 簡略化マーカー検出 (最優先: ポリシー違反) ===
    if has_simplified_marker(effects):
        issues.append("simplified_marker")

    # === when 不整合 ===
    if "【起動メイン】" in text and "activate_main" not in when_set:
        issues.append("missing_activate_main")
    if "【登場時】" in text and "on_play" not in when_set:
        issues.append("missing_on_play")
    if "【KO時】" in text and "on_ko" not in when_set:
        issues.append("missing_on_ko")
    if "【アタック時】" in text and "on_attack" not in when_set:
        issues.append("missing_on_attack")
    if "【ブロック時】" in text and "on_block" not in when_set:
        issues.append("missing_on_block")
    if "【相手のアタック時】" in text and "opp_attack" not in when_set:
        issues.append("missing_opp_attack")
    if "【自分のターン終了時】" in text and "end_of_turn" not in when_set:
        issues.append("missing_end_of_turn")
    if "【相手のターン終了時】" in text and "opp_end_of_turn" not in when_set:
        issues.append("missing_opp_end_of_turn")
    if "【トリガー】" in text and "trigger" not in when_set:
        issues.append("missing_trigger")
    if "【ターン1回】" in text and not overlay_has_once_per_turn(effects):
        issues.append("missing_once_per_turn")

    # === if (条件) 不整合 ===
    if "自分のターン中" in text and not any(
        k in cond_keys for k in ("self_turn", "is_owners_turn")
    ):
        # ただし overlay 全体に該当ロジックある可能性 (DON+1000 等は別系統) のため弱シグナル
        issues.append("self_turn_condition_unmodeled")
    if "相手のターン中" in text and "opp_turn" not in cond_keys:
        issues.append("opp_turn_condition_unmodeled")
    if "ライフが" in text and not any(
        k in cond_keys for k in (
            "self_life_le", "self_life_ge", "opp_life_le", "opp_life_ge",
        )
    ):
        issues.append("life_condition_unmodeled")
    if "リーダーが" in text and "特徴" in text and not any(
        k in cond_keys for k in ("leader_feature", "opp_leader_feature")
    ):
        issues.append("leader_feature_unmodeled")
    if "ドン!!" in text and "枚" in text and not any(
        k in cond_keys for k in (
            "self_don_ge", "self_don_active_ge", "self_attached_don_ge",
            "self_don_le", "don_count_ge", "don_count_le",
            "opp_don_count_ge", "opp_don_count_le",
        )
    ):
        # ドン!! 枚数条件の可能性
        issues.append("don_count_condition_unmodeled")

    # === FAQ 注目度 ===
    if len(qa_list) >= 3:
        issues.append(f"faq_attention_{len(qa_list)}")

    # === FAQ 否定文の存在 ===
    for qa in qa_list:
        a = qa.get("a", "")
        if "いいえ" in a or "できません" in a:
            issues.append("faq_negation")
            break

    # === 効果 0 件 (vanilla) なのに FAQ ある ===
    if len(effects) == 0 and len(qa_list) >= 1:
        issues.append("vanilla_but_has_faq")

    return issues


SEVERITY = {
    "simplified_marker": 8,        # ポリシー違反 → 高 severity
    "missing_activate_main": 5,
    "missing_on_play": 5,
    "missing_on_ko": 4,
    "missing_on_attack": 4,
    "missing_on_block": 5,
    "missing_opp_attack": 4,
    "missing_end_of_turn": 4,
    "missing_opp_end_of_turn": 4,
    "missing_trigger": 4,
    "missing_once_per_turn": 3,
    "self_turn_condition_unmodeled": 1,
    "opp_turn_condition_unmodeled": 1,
    "life_condition_unmodeled": 1,
    "leader_feature_unmodeled": 1,
    "don_count_condition_unmodeled": 1,
    "faq_negation": 2,
    "vanilla_but_has_faq": 3,
}


def issue_severity(issue: str) -> int:
    if issue.startswith("faq_attention_"):
        # faq_attention_N → 1〜3 段階
        try:
            n = int(issue.split("_")[-1])
        except ValueError:
            return 1
        return min(3, max(1, n // 3))
    return SEVERITY.get(issue, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--top", type=int, default=80,
        help="出力する上位件数 (severity 順)",
    )
    parser.add_argument(
        "--include-meta", action="store_true",
        help="cardrush メタリーダー (= 手書き対象) も含める (default: 除外)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="severity = 0 のカードも全件出力 (= 完全レポート、 巨大)",
    )
    args = parser.parse_args()

    cards = load_cards()
    overlay = load_overlay()
    qa_by_card = load_all_qa()

    # メタデッキの leader はスキップ (= 手書きで信頼度高)
    meta_leaders: set[str] = set()
    if not args.include_meta:
        for f in (ROOT / "decks").glob("cardrush_*.json"):
            if f.name.endswith(".analysis.json"):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                if d.get("leader"):
                    meta_leaders.add(d["leader"])
            except Exception:
                continue

    rows: list[dict] = []
    for cid, card in cards.items():
        if cid in meta_leaders:
            continue
        effects = overlay.get(cid, [])
        qa_list = qa_by_card.get(cid, [])
        if not qa_list and not effects:
            continue
        issues = detect_issues(card, effects, qa_list)
        if not issues and not args.all:
            continue
        severity = sum(issue_severity(i) for i in issues)
        rows.append({
            "card_id": cid,
            "name": card.get("name", ""),
            "category": card.get("category", ""),
            "cost": card.get("cost"),
            "power": card.get("power"),
            "text": card.get("text") or "",
            "effects": effects,
            "qa_list": qa_list,
            "issues": issues,
            "severity": severity,
        })

    rows.sort(key=lambda r: -r["severity"])

    # JSON 出力 (全件)
    OUTPUT_JSON.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Markdown 出力 (上位 N 件)
    out = OUTPUT_MD.open("w", encoding="utf-8")
    out.write(f"# Overlay vs FAQ 監査レポート\n\n")
    out.write(f"- 対象カード総数: {len(cards)}\n")
    out.write(f"- 突合対象 (overlay or FAQ あり): {len(rows)}\n")
    out.write(f"- メタリーダー除外: {len(meta_leaders)} 枚 (手書きで信頼度高)\n\n")
    out.write("## 凡例\n\n")
    out.write("- `missing_*`: 公式テキストに記載のキーワードが overlay の when に無い\n")
    out.write("- `*_condition_unmodeled`: 条件節が overlay の if に無い (弱シグナル: コードロジックで吸収されている可能性あり)\n")
    out.write("- `faq_attention_N`: 公式 FAQ で N 件以上言及 = 注目度高い\n")
    out.write("- `faq_negation`: FAQ に 「いいえ、できません」 を含む (= overlay が誤って許可している可能性)\n")
    out.write("- `vanilla_but_has_faq`: overlay 0 件なのに FAQ あり\n\n")
    out.write(f"## 上位 {args.top} 件 (severity 順)\n\n")

    for i, row in enumerate(rows[: args.top]):
        out.write(f"### {i+1}. `{row['card_id']}` {row['name']}  (severity={row['severity']})\n\n")
        out.write(f"- 種別: {row['category']} / コスト: {row['cost']} / パワー: {row['power']}\n")
        out.write(f"- 検出 issue: `{', '.join(row['issues'])}`\n\n")
        out.write(f"**公式テキスト:**\n\n```\n{row['text'] or '(なし)'}\n```\n\n")
        out.write(f"**Overlay ({len(row['effects'])} 件):**\n\n")
        if row["effects"]:
            out.write("```json\n")
            out.write(json.dumps(row["effects"], ensure_ascii=False, indent=2))
            out.write("\n```\n\n")
        else:
            out.write("(空)\n\n")
        out.write(f"**FAQ ({len(row['qa_list'])} 件):**\n\n")
        for qa in row["qa_list"][:5]:
            out.write(f"- Q: {qa['q']}\n  A: {qa['a']}\n")
        if len(row["qa_list"]) > 5:
            out.write(f"- ... (残り {len(row['qa_list']) - 5} 件は JSON 出力参照)\n")
        out.write("\n---\n\n")

    out.close()
    print(f"完了: {OUTPUT_MD} (上位 {min(args.top, len(rows))} 件)")
    print(f"     {OUTPUT_JSON} (全 {len(rows)} 件)")
    # severity 分布のサマリ
    from collections import Counter
    sev_buckets = Counter()
    for r in rows:
        if r["severity"] >= 10:
            sev_buckets["10+"] += 1
        elif r["severity"] >= 5:
            sev_buckets["5-9"] += 1
        elif r["severity"] >= 3:
            sev_buckets["3-4"] += 1
        elif r["severity"] >= 1:
            sev_buckets["1-2"] += 1
        else:
            sev_buckets["0"] += 1
    print(f"\n=== severity 分布 ===")
    for k in ("10+", "5-9", "3-4", "1-2", "0"):
        if sev_buckets.get(k):
            print(f"  {k}: {sev_buckets[k]} 件")


if __name__ == "__main__":
    main()
