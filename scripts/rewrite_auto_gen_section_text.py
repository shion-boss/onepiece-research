#!/usr/bin/env python3
"""Step C+D: give_keyword 以外 の 自動生成 marker entries (= 172 件) の _text を
公式テキスト中 の 該当 section に 書き戻す。

各 entry の when から 公式テキスト中 の 対応 marker (= 【起動メイン】 等) を 探索し、
そこから 次の 【】 タグ または 文末 までを 抽出。 内容自体 (= when/if/do) は 触らない。

抽出失敗時 は _text を `{cid} {public_text} (= 公式テキスト 全文 引用)` に。

run: .venv/bin/python scripts/rewrite_auto_gen_section_text.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OV_PATH = ROOT / "db" / "card_effects.json"
ov = json.load(open(OV_PATH, encoding="utf-8"))


def get_text(cid: str) -> str:
    t = (CARDS.get(cid, {}).get("text") or "").strip()
    if not t:
        base = cid.split("_")[0]
        t = (CARDS.get(base, {}).get("text") or "").strip()
    return t


# when -> 公式テキスト中 marker 候補
WHEN_MARKERS = {
    "activate_main": ["【起動メイン】"],
    "on_attack": ["【アタック時】"],
    "on_play": ["【登場時】"],
    "trigger": ["【トリガー】"],
    "end_of_turn": ["【自分のターン終了時】", "【ターン終了時】"],
    "opp_attack": ["【相手のアタック時】"],
    "on_block": ["【ブロック時】"],
    "on_ko": ["【KO時】", "【ＫＯ時】"],
}


def extract_section(text: str, when: str) -> str | None:
    """公式テキストから when 対応 section を 抽出。
    marker 〜 次の 【】 タグ or 文末 まで。"""
    markers = WHEN_MARKERS.get(when, [])
    for m in markers:
        idx = text.find(m)
        if idx < 0:
            continue
        # marker 開始位置から末尾まで取り、 次の【で 区切る
        rest = text[idx:]
        # marker 自体を含む。 次の トリガー的タグ (= 別 when 開始) で 切る
        # 但し 【ブロッカー】 等 keyword tags は 切らない
        # next when marker
        end = len(rest)
        for other_when, other_markers in WHEN_MARKERS.items():
            if other_when == when:
                continue
            for om in other_markers:
                pos = rest.find(om, len(m))  # marker 自体 の 後 から 探索
                if pos > 0 and pos < end:
                    end = pos
        section = rest[:end].strip()
        # 末尾 () の 注釈 は 残す
        return section
    return None


def main():
    changed = 0
    skipped = []
    for cid, es in ov.items():
        if not isinstance(es, list):
            continue
        text = get_text(cid)
        if not text:
            continue
        for e in es:
            if not isinstance(e, dict):
                continue
            t = e.get("_text") or ""
            if "自動生成" not in t:
                continue
            # give_keyword 系 は Step A で 処理 済 → skip (= 念のため)
            has_kw = any(
                isinstance(a, dict) and "give_keyword" in a
                for a in (e.get("do") or [])
            )
            if has_kw:
                continue
            when = e.get("when")
            section = extract_section(text, when) if when else None
            if section:
                new_text = f"{cid} {section}"
                if new_text != t:
                    e["_text"] = new_text
                    changed += 1
            else:
                # fallback: 公式テキスト 全文を 引用
                new_text = f"{cid} {text}"
                if new_text != t:
                    e["_text"] = new_text
                    changed += 1
                else:
                    skipped.append((cid, when, t[:60]))
    OV_PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"changed: {changed}")
    print(f"skipped: {len(skipped)}")
    for cid, when, t in skipped[:10]:
        print(f"  {cid} when={when}: {t}")
    print(f"wrote: {OV_PATH}")


if __name__ == "__main__":
    main()
