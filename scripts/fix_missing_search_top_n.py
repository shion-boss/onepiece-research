#!/usr/bin/env python3
"""overlay に search_top_n 効果が完全欠落している カードを 補完。

問題: 公式テキスト 「自分のデッキの上から N 枚を見て、 ... を 手札に加える」 を
overlay が 完全に スキップして、 関連 cost (= discard_hand) のみ 実装している ケース。
これにより 効果の 大半が 発動しない 重大バグ。

検出 / 補完規則:
  text に 「自分のデッキの上から (\d+) 枚を見て」 マッチ → search_top_n 必要
  text の 後続部分 から:
    - depth: マッチした数値
    - filter: 特徴《X》/「Y」/コストN以下/特徴《X》か《Y》
    - limit: 「N 枚 までを公開し、 手札に加える」 / 「合計 N 枚」
    - destination: 「手札に加える」 → hand / 「登場させる」 → play
    - rest_remain: 「残りを好きな順番でデッキの下に置く」 → bottom

既存の overlay に search_top_n がない 場合 のみ 追加。
on_play / on_attack / activate_main の どれか 適切な when entry に primitive 追加。
新規 when が必要な場合 (= on_play 系 entry なし) は 新 entry 作成。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}


def normalize(text: str) -> str:
    return text.replace("‼", "!!").replace("！", "!").replace("：", ":")


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def parse_filter(clause: str) -> dict:
    """clause から filter dict を 抽出 (= 特徴/コスト/カテゴリ/exclude_name 等)。"""
    flt: dict = {}
    # 特徴《X》か《Y》
    m = re.search(r"特徴《(.+?)》か《(.+?)》", clause)
    if m:
        flt["or_clauses"] = [{"feature": m.group(1)}, {"feature": m.group(2)}]
    else:
        m = re.search(r"特徴《(.+?)》", clause)
        if m:
            flt["feature"] = m.group(1)
    # 「カード名」 (= 一重括弧)
    m = re.search(r"「([^「」]+?)」", clause)
    if m and "exclude" not in clause[:m.start()]:
        flt["name"] = m.group(1)
    # exclude 「X」以外
    m = re.search(r"「([^「」]+?)」以外", clause)
    if m:
        flt["exclude_name"] = m.group(1)
    # コスト N 以下
    m = re.search(r"コスト\s*(\d+)\s*以下", clause)
    if m:
        flt["cost_le"] = int(m.group(1))
    # キャラ カード / イベント カード
    if "キャラカード" in clause:
        flt["category"] = "character"
    elif "イベントカード" in clause:
        flt["category"] = "event"
    return flt


def parse_search_top_n(text: str) -> list[dict]:
    """text から search_top_n primitive リスト を 抽出 (= 複数 clause 対応)。"""
    primitives = []
    # 「自分のデッキの上から N 枚を見て、 ... 」 を マッチ
    for m in re.finditer(r"自分のデッキの上から\s*(\d+)\s*枚を見て、(.+?)(?:。|$)", text, re.DOTALL):
        depth = int(m.group(1))
        clause = m.group(2)

        # limit: 「N 枚 までを 公開し、 手札に加える」 / 「合計 N 枚」
        limit_m = re.search(r"(?:合計\s*)?(\d+)\s*枚までを(?:公開し、)?(?:手札に加える|登場させる)", clause)
        # 「1 枚 まで」 を 公開
        if not limit_m:
            limit_m = re.search(r"(\d+)\s*枚まで", clause)
        limit = int(limit_m.group(1)) if limit_m else 1

        # destination
        if "手札に加える" in clause:
            destination = "hand"
        elif "登場させる" in clause:
            destination = "play"
        elif "好きな順番に並び替え" in clause or "好きな順番で並び替え" in clause:
            # look_top_reorder の代用 (= search_top_n だと不適)
            primitives.append({"look_top_reorder": {"depth": depth}})
            continue
        else:
            destination = "hand"

        # rest_remain
        rest_remain = "bottom" if "デッキの下" in clause else ("top" if "デッキの上" in clause else "bottom")

        flt = parse_filter(clause)
        primitives.append({
            "search_top_n": {
                "depth": depth,
                "filter": flt,
                "limit": limit,
                "destination": destination,
                "rest_remain": rest_remain,
            }
        })
    return primitives


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        if not re.search(r"自分のデッキの上から\s*\d+\s*枚を見て", text):
            continue
        # 既に search_top_n を含む 場合 は スキップ
        flat = json.dumps(entries, ensure_ascii=False)
        if "search_top_n" in flat or "look_top_reorder" in flat:
            continue
        primitives = parse_search_top_n(text)
        if not primitives:
            continue
        # 適切な when の entry を 探す
        # 公式テキスト の どこに「上から N 枚を見て」 があるか で 推定
        # 簡略: 「【登場時】」 を 含む 場合 on_play、 「【アタック時】」 → on_attack、 「【起動メイン】」 → activate_main
        when = None
        if "【登場時】" in text:
            when = "on_play"
        elif "【アタック時】" in text:
            when = "on_attack"
        elif "【起動メイン】" in text:
            when = "activate_main"
        else:
            when = "on_play"  # fallback

        # 既存 entry に when 一致 が あれば、 do に primitives を 追加
        added = False
        for entry in entries:
            if isinstance(entry, dict) and entry.get("when") == when:
                do = entry.setdefault("do", [])
                do.extend(primitives)
                log.append(f"  {cid}: append {len(primitives)} search primitives to {when} entry")
                added = True
                break
        if not added:
            # 新規 entry 作成
            entries.append({
                "_text": f"[auto] {when}: search_top_n 補完",
                "when": when,
                "do": primitives,
            })
            log.append(f"  {cid}: new {when} entry +{len(primitives)} primitives")
        fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_search_top_n_log.md").write_text(
        "# search_top_n 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
