#!/usr/bin/env python3
"""逆方向 (phantom) detector = overlay に primitive が**有る**のに 公式テキストに対応動作語が**無い**。

[[project_full_db_audit_phase]] の forward detector (audit_text_overlay_consistency.py) は
「text に動作語あるが overlay に primitive 無し」 (= under-implementation, type1/2/3/5) を拾う。
これはその **逆** = type4 phantom (= over-implementation、 overlay が公式に無い効果を生やしている)。

forward detector の flagged_queue を 0 にした後の残路程 = unflagged ~3,790 card の inline 監査。
そのうち phantom は機械検出可能 (= 高精度 primitive が text の動作語と 1:1 対応するため)。
これで phantom 濃厚 card を優先 queue 化し、 inline 監査を集中させる。

検出する主な phantom (= 高精度・低 FP のみ採用):
- overlay に draw primitive あるが text に「引く/ドロー」 無し         → phantom draw
- overlay に draw:N あるが text の数字と不一致                       → draw count drift
- overlay に ko/ko_multi primitive あるが text に「KO」 無し          → phantom KO
- overlay に give_keyword/give_rush あるが text に対応【keyword】無し → phantom keyword
- overlay に extra_turn あるが text に「追加」「もう一度」 無し       → phantom extra turn

注意:
- _text (overlay 自身の説明) は walk から除外。 動作語判定は cards.json の text のみ。
- heuristic ゆえ FP あり (= cost 文脈の trash=KO 同義、 trigger 内 別表現等)。 flag は
  「優先 inline 監査せよ」 であって 確定 bug ではない。
- forward と違い **数 (count/threshold) drift** も拾う (= phantom と並ぶ type4 の主成分)。

使い方:
  python scripts/audit_overlay_text_phantom.py            # 全カード → db/audit_llm/phantom.json
  python scripts/audit_overlay_text_phantom.py --top 60   # 上位 N 件 stdout
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
EFFECTS_PATH = ROOT / "db" / "card_effects.json"
OUT_PATH = ROOT / "db" / "audit_llm" / "phantom.json"

# 全角→半角 数字 正規化
ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def _walk_prims(obj, skip_text=True) -> list[tuple[str, object]]:
    """overlay を walk し (primitive_key, value) を集める。 _text は除外 (= 説明文)。"""
    out: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if skip_text and k == "_text":
                continue
            out.append((k, v))
            out.extend(_walk_prims(v, skip_text))
    elif isinstance(obj, list):
        for x in obj:
            out.extend(_walk_prims(x, skip_text))
    return out


def _draw_amount(v) -> int | None:
    """draw primitive の値から「引く枚数」を取り出す (int / {amount:N} 両形式)。"""
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        for key in ("amount", "n", "count"):
            if isinstance(v.get(key), int):
                return v[key]
    return None


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
        # 公式テキスト corpus = text + trigger (overlay の when:"trigger" entry は
        # cards.json の別 field `trigger` (= 【トリガー】行) を実装する。 text だけ見ると
        # trigger 由来の KO/draw を全件 phantom 誤判定する FP 源になる)。
        text = ((card.get("text") or "") + "\n" + (card.get("trigger") or "")).strip()
        if not text:
            continue
        text_n = text.translate(ZEN)
        prims = _walk_prims(entries)
        keys = {k for k, _ in prims}
        flags: list[str] = []

        # 1) phantom draw: draw 系 primitive あるが text に 引く/ドロー 無し
        #    活用形に注意: 「引く」 終止形 + 「引き」 連用形 (= 〜を引き、〜を捨てる) 両対応。
        draw_keys = {"draw"}  # draw_per_* は条件付きなので別扱い (FP 回避で除外)
        if (keys & draw_keys) and not re.search(r"引く|引き|ドロー", text):
            flags.append("overlay draw あるが text に「引く/ドロー」無し (= phantom draw 濃厚)")
        else:
            # 1b) draw count drift: draw:N だが text の「N枚引く」 と不一致
            for k, v in prims:
                if k != "draw":
                    continue
                amt = _draw_amount(v)
                if amt is None:
                    continue
                nums = [int(m) for m in re.findall(r"([0-9]+)枚引く", text_n)]
                if nums and amt not in nums:
                    flags.append(f"draw:{amt} だが text は「{nums}枚引く」 (= count drift)")

        # 2) phantom KO: ko/ko_multi primitive あるが text に KO 無し
        if (keys & {"ko", "ko_multi"}) and "KO" not in text:
            flags.append("overlay ko あるが text に「KO」無し (= phantom KO 濃厚)")

        # 3) phantom keyword: give_keyword/give_rush あるが 対応 keyword 表現 無し。
        #    keyword は 「与える」 (与え) / 「得る」 (得る/得て) で付与されるほか、
        #    【ブロッカー】無効化系 (= ブロック不可) は 「発動できない」 表現になる。
        #    活用形・無効化表現を網羅して FP を抑える。
        if keys & {"give_keyword", "give_rush"}:
            if not re.search(r"与え|得る|得て|発動できない|アタックできる|ブロックできない", text):
                flags.append("overlay give_keyword あるが text に keyword 付与表現無し (= phantom keyword)")

        # 4) phantom extra_turn: 追加ターンは破滅的誤実装なので 単独でも flag
        if "extra_turn" in keys and not re.search(r"追加|もう[1一]度|連続", text):
            flags.append("overlay extra_turn あるが text に「追加/もう一度」無し (= phantom extra turn)")

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
    args = ap.parse_args()

    findings = audit()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    by_flagtype: Counter = Counter()
    for f in findings:
        for fl in f["flags"]:
            tag = fl.split(" (=")[0].split("だが")[0].strip()[:24]
            by_flagtype[tag] += 1
    print(f"flagged {len(findings)} 件 → {OUT_PATH.relative_to(ROOT)}")
    print(f"  flag 種別: {dict(by_flagtype.most_common())}")
    if args.top:
        print(f"\n=== 上位 {args.top} ===")
        for f in findings[:args.top]:
            print(f"  [{f['score']}] {f['card_id']} {f['name']} ({f['category']})")
            for fl in f["flags"]:
                print(f"        - {fl}")
            print(f"        text: {f['text'][:90]}")


if __name__ == "__main__":
    main()
