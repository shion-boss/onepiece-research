#!/usr/bin/env python3
"""cardqa の Q&A 文中に言及される「効果」 が overlay に対応するか自動 sweep。

公式 FAQ で「【登場時】効果」 「【アタック時】効果」 等が言及されている場合、
そのカードの overlay にも対応する when を持つ effect entry があるはず。
無ければ「overlay 抜け」 の可能性。

実行:
    .venv/bin/python scripts/verify_overlay_vs_cardqa.py

出力: 各 card_id の missing when を列挙。
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# 公式テキスト中の効果マーカー → overlay when の対応
EFFECT_MARKER_TO_WHEN = {
    "登場時": "on_play",
    "アタック時": "on_attack",
    "KO時": "on_ko",
    "起動メイン": "activate_main",
    "ブロック時": "on_block",
    "相手のアタック時": "opp_attack",
    "自分のターン終了時": "end_of_turn",
    "相手のターン終了時": "opp_end_of_turn",
    "トリガー": "trigger",
    "カウンター": "counter",
    "メイン": "main",
}


def load_cardqa():
    """cardqa を card_id 別に集約。

    cardqa items は card_id を持たないので、 extract_faq_test_cases の
    referenced_card_ids 推論を流用して card → [{q, a}] dict を作る。
    """
    qa_by_card: dict[str, list[dict]] = defaultdict(list)
    sys.path.insert(0, str(_ROOT))
    from scripts.extract_faq_test_cases import extract_test_cases
    cases = extract_test_cases(limit=10000)
    for c in cases:
        for cid in c.referenced_card_ids:
            qa_by_card[cid].append({
                "q": c.q,
                "a": c.a,
                "case_id": c.case_id,
            })
    return qa_by_card


def extract_when_mentions(text: str) -> set[str]:
    """Q&A テキストから言及された when を抽出 (= 効果マーカーから)。"""
    whens = set()
    for marker, when in EFFECT_MARKER_TO_WHEN.items():
        # 【X】 or 「X」 で囲まれる、 もしくは効果に直結する形 (= X効果 / X時に)
        # シンプル: 文字列 marker が含まれていれば when 候補
        if marker in text:
            whens.add(when)
    return whens


def main():
    qa_by_card = load_cardqa()
    overlay = json.loads((_ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards_data = json.loads((_ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in cards_data}

    missing_by_card: dict[str, dict] = {}
    sweep_count = 0
    for cid, qa_list in qa_by_card.items():
        if cid not in cards:
            continue
        card = cards[cid]
        # カード自身のテキスト (= text + trigger) に出てくる when を期待値とする
        card_text = (card.get("text") or "") + " " + (card.get("trigger") or "")
        expected_whens = extract_when_mentions(card_text)
        if not expected_whens:
            continue
        # overlay の when 集合
        overlay_entries = overlay.get(cid, [])
        if not isinstance(overlay_entries, list):
            continue
        actual_whens = set()
        for e in overlay_entries:
            if isinstance(e, dict) and e.get("when"):
                actual_whens.add(e["when"])
        # 期待しているが overlay に無い when
        missing = expected_whens - actual_whens
        # 例外: 「メイン」 はイベント効果なので on_play に相当することもある
        # 「トリガー」 はトリガーとして固有
        if missing:
            # 例外フィルタ: card が EVENT で missing="main" のみなら除外
            if card.get("category") == "EVENT" and missing == {"main"}:
                continue
            missing_by_card[cid] = {
                "name": card.get("name", ""),
                "category": card.get("category"),
                "text": card_text[:100],
                "missing_whens": sorted(missing),
                "actual_whens": sorted(actual_whens),
                "qa_count": len(qa_list),
            }
        sweep_count += 1

    print(f"Sweep: {sweep_count} cards with FAQ + text")
    print(f"Missing overlay whens: {len(missing_by_card)} cards")
    print()
    # 上位 30 件 (qa_count 順)
    sorted_items = sorted(
        missing_by_card.items(),
        key=lambda kv: -kv[1]["qa_count"],
    )
    for cid, info in sorted_items[:30]:
        print(f"  {cid} ({info['name']}) — missing: {info['missing_whens']}")
        print(f"    actual: {info['actual_whens']}")
        print(f"    text: {info['text'][:80]}")
        print(f"    qa: {info['qa_count']}")
        print()

    # 保存
    out = _ROOT / "db" / "overlay_when_missing.json"
    out.write_text(json.dumps(missing_by_card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
