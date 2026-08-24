#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式 Q&A の **カード紐付け** (`db/faq/cardqa_*.json` の card_id) を cards.json と突合する。

なぜ要るか:
  スクレイパは公式ページの `dd.qaTit` (例: 「OP15-106 ジュエリー・ボニー」) からカード番号を
  拾う。 これが無いと 「この【登場時】効果」 がどのカードか特定できず、 conformance 検査が
  n/a / escalated に落ちる (2026-08-12 に P-009 / OP02-004 の 2 件で実際に起きた)。

  ただし **公式ページ側の番号が間違っていることがある**。 番号と名前の両方が載っているので、
  cards.json の名前と突合すれば検出できる。 番号を鵜呑みにすると **別のカードを見て裁定** する
  (実際に OP15-106 = タコバルーン を見て 「効果が無い」 と誤読しかけた)。

使い方:
  .venv/bin/python scripts/verify_cardqa_card_ids.py          # 不一致を一覧
  .venv/bin/python scripts/verify_cardqa_card_ids.py --assert # 既知以外の不一致で exit 1
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 公式ページ側の **既知の誤り** (= 番号と名前が食い違う。 名前の方が正しい)。
# 「公式 QA の番号 → 実際のカード」 を記録して、 裁定時に正しい方を見るための台帳。
KNOWN_PAGE_TYPOS = {
    "OP15-106": ("ジュエリー・ボニー", "OP15-105"),  # cards.json の OP15-106 は タコバルーン
    "ST29-012": ("ロブ・ルッチ", "ST29-013"),        # cards.json の ST29-012 は モンキー・D・ルフィ
}


def _norm(s: str) -> str:
    """表記ゆれ (‼ / !!! / … / 中黒 / 全角英字) を吸収して名前を比較可能にする。"""
    s = (s or "").replace("‼", "!!").replace("！", "!")
    s = s.replace("…", "...").replace("Ｄ", "D")
    # 小書き仮名の揺れ (ねぇ / ネェ 等) も吸収する (公式ページと cards.json で混在)。
    s = s.translate(str.maketrans("ぁぃぅぇぉゃゅょっ", "アイウエオヤユヨツ"))
    s = s.translate(str.maketrans("ァィゥェォャュョッ", "アイウエオヤユヨツ"))
    s = "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in s)
    return re.sub(r"[\s・･.!\"”'’]", "", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true",
                    help="既知以外の不一致があれば exit 1 (CI 用)")
    args = ap.parse_args()

    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ok = 0
    unknown_id: list[tuple[str, str]] = []
    mismatch: dict[tuple[str, str, str], int] = {}

    for f in sorted(glob.glob(str(ROOT / "db" / "faq" / "cardqa_*.json"))):
        for it in json.loads(Path(f).read_text(encoding="utf-8")).get("items", []):
            cid, title = it.get("card_id"), it.get("title")
            if not cid:
                continue
            name = (title or "")[len(cid):].strip()
            c = cards.get(cid)
            if c is None:
                # ⚠ 一部のプロモは **パラレルしか cards.json に無い** (P-081/P-082 等)。
                #   テキストは同じなので裁定には使える → 欠落扱いにしない。
                par = next((cards[k] for k in cards
                            if k.startswith(cid + "_")), None)
                if par is not None:
                    c = par
                else:
                    unknown_id.append((cid, name))
                    continue
            if _norm(c["name"]) == _norm(name):
                ok += 1
            else:
                key = (cid, name, c["name"])
                mismatch[key] = mismatch.get(key, 0) + 1

    print(f"名前一致 {ok} 件 / 不一致 {len(mismatch)} 種 / cards.json に無い card_id {len(unknown_id)} 件")
    unexpected = []
    for (cid, qa_name, db_name), n in sorted(mismatch.items(), key=lambda x: -x[1]):
        known = KNOWN_PAGE_TYPOS.get(cid)
        tag = ""
        if known and _norm(known[0]) == _norm(qa_name):
            tag = f"  [既知の公式ページ誤り → 実体は {known[1]}]"
        else:
            unexpected.append((cid, qa_name, db_name))
        print(f"  {cid}: 公式QA='{qa_name}' vs cards.json='{db_name}' ×{n}{tag}")
    for cid, name in unknown_id[:10]:
        print(f"  ⚠ cards.json に無い: {cid} ({name})")

    if unexpected:
        print("\n⚠ 未知の不一致 = **裁定前にどちらが正しいか確認する** "
              "(番号を鵜呑みにすると別のカードを見て誤判定する)")
    if args.do_assert and (unexpected or unknown_id):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
