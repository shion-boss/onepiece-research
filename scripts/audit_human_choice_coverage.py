#!/usr/bin/env python3
"""人間プレイで「選択肢が欠落 / 自動化されている」 カードを検出する static detector。

[[project_full_db_audit_phase]] の forward/phantom detector と同系統。 動機: イム OP13-079
起動メイン (= 「天竜人キャラ か 手札1枚」 の 2 択を 人間に提示せず手札一択に潰していた) を
ohtsuki さんが手で見つけるのは大変、 という指摘 (2026-06-01)。 これを機械検出に置き換える。

公式テキストが **人間に選択を要求する構造** を持つのに、 overlay 実装が その選択肢を
表現していない (= 単一 do に潰す / コストを欠落) カードを flag する。 人間 vs AI で
「選べるべき選択肢が出ない」 系バグの優先 queue を生成する。

検出する mismatch (= 高精度・低 FP):
- **A) 択一「AかB」**: text に「…か、…(を/に)<動作語>」 があるのに overlay に choice/
  choice_effect/options が無い (= 片方しか実装していない疑い)。
- **B) 任意コスト欠落**: text に「…できる：」 or 「…してもよい」 (= 任意コスト/任意効果)
  があるのに、 該当 entry に cost も optional も無い (= コスト踏み倒し疑い、 OP06-033 型)。
- **C) 「以下から1つ」**: text に「以下から[1]つを選ぶ」 があるのに overlay に
  choice/choice_effect が無い。

注意: heuristic ゆえ FP あり (= cost が别 primitive 内蔵 / 選択が target spec に内包 等)。
flag は「優先 inline 確認せよ」 であって 確定 bug ではない。 動作語を伴う択一に絞り FP を抑える。

使い方:
  python scripts/audit_human_choice_coverage.py            # 全カード → db/audit_llm/human_choice.json
  python scripts/audit_human_choice_coverage.py --top 40   # 上位 N 件 stdout
  python scripts/audit_human_choice_coverage.py --deck-pool # 16-deck pool に絞る
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
EFFECTS_PATH = ROOT / "db" / "card_effects.json"
DECKS_DIR = ROOT / "decks"
OUT_PATH = ROOT / "db" / "audit_llm" / "human_choice.json"

# 択一「AかB」: A節 か、 B節 を/に <動作語>。 動作語を伴うものだけ拾う (= 単なる名詞「か」を排除)。
ACTION_WORD = r"(トラッシュに置|捨て|レストに|KOする|KOし|登場させ|手札に(加え|戻)|デッキの下|アクティブ)"
CHOICE_KA = re.compile(r"[^。、：]{2,40}か、[^。：]{0,40}?" + ACTION_WORD)
# 任意コスト/任意効果: 「…できる：」 (コスト記号) or 「…してもよい」 / 「…することができる」
OPTIONAL_COST = re.compile(r"(を?捨て|をトラッシュに置|をレストに|を[^。]{0,8}戻)[^。：]{0,20}(ことが)?でき(る|ます)?：")
OPTIONAL_DO = re.compile(r"してもよい|することができる(?!：)")
# 「以下から1つ」
ONE_OF = re.compile(r"以下から[0-9０-９]?[1１]?つを?選")

# overlay に choice 構造があるか判定するキー
CHOICE_KEYS = {"choice", "choice_effect", "options", "optional_cost_then",
               "discard_hand_or_trash_filtered_chara"}


def _walk_keys(obj) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= _walk_keys(v)
    elif isinstance(obj, list):
        for x in obj:
            found |= _walk_keys(x)
    return found


def _entries_have_cost_or_optional(entries) -> bool:
    """どれかの entry が cost / optional / optional_cost_then を持つか。"""
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        if e.get("cost") or e.get("optional"):
            return True
        # do 内 optional_cost_then も任意コスト表現
        for d in e.get("do", []) or []:
            if isinstance(d, dict) and "optional_cost_then" in d:
                return True
    return False


def load_deck_pool_ids() -> set[str]:
    ids: set[str] = set()
    for f in DECKS_DIR.glob("*.json"):
        if ".analysis." in f.name or ".target_v" in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("leader"):
            ids.add(d["leader"])
        for entry in d.get("main", []) or d.get("cards", []):
            cid = entry.get("card_id") if isinstance(entry, dict) else entry
            if cid:
                ids.add(cid)
    return ids


def audit() -> list[dict]:
    cards = {c["card_id"]: c for c in json.loads(CARDS_PATH.read_text(encoding="utf-8"))}
    effects = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    findings: list[dict] = []

    for cid, entries in effects.items():
        if not entries:
            continue
        card = cards.get(cid)
        if not card:
            continue
        text = ((card.get("text") or "") + "\n" + (card.get("trigger") or "")).strip()
        if not text:
            continue
        keys = _walk_keys(entries)
        has_choice = bool(keys & CHOICE_KEYS)
        flags: list[str] = []

        # A) 択一「AかB」 + 動作語 だが choice 構造無し
        if CHOICE_KA.search(text) and not has_choice:
            flags.append("text「AかB」択一だが overlay に choice 構造無し (= 片方のみ実装疑い)")

        # B) 任意コスト「できる：」 / 任意効果「してもよい」 だが cost/optional 無し
        if (OPTIONAL_COST.search(text) or OPTIONAL_DO.search(text)) \
                and not _entries_have_cost_or_optional(entries):
            flags.append("text「〜できる：/してもよい」(任意コスト/効果)だが overlay に cost/optional 無し (= コスト踏み倒し疑い)")

        # C) 「以下から1つ」 だが choice 無し
        if ONE_OF.search(text) and not has_choice:
            flags.append("text「以下から1つを選ぶ」だが overlay に choice 構造無し")

        if flags:
            findings.append({
                "card_id": cid,
                "name": card.get("name"),
                "category": card.get("category"),
                "score": len(flags),
                "flags": flags,
                "text": text,
            })

    findings.sort(key=lambda f: (-f["score"], f["card_id"]))
    return findings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--deck-pool", action="store_true", help="16-deck pool に絞る")
    args = ap.parse_args()

    findings = audit()
    if args.deck_pool:
        pool = load_deck_pool_ids()
        findings = [f for f in findings if f["card_id"] in pool]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    by_flag: Counter = Counter()
    for f in findings:
        for fl in f["flags"]:
            by_flag[fl.split(" (=")[0].split("だが")[0].strip()[:30]] += 1
    print(f"flagged {len(findings)} 件 → {OUT_PATH.relative_to(ROOT)}")
    print(f"  flag 種別: {dict(by_flag.most_common())}")
    if args.top:
        print(f"\n=== 上位 {args.top} ===")
        for f in findings[:args.top]:
            print(f"  [{f['score']}] {f['card_id']} {f['name']} ({f['category']})")
            for fl in f["flags"]:
                print(f"        - {fl}")
            print(f"        text: {f['text'][:100]}")


if __name__ == "__main__":
    main()
