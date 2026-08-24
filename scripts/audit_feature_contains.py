#!/usr/bin/env python
"""公式テキストの 「『X』を含む特徴」 と overlay の feature_contains を突合する監査。

一次情報 (`db/faq/base.json`、 公式「よくある質問」):
  Q: 「『○○』を含む特徴を持つ」 とは、 《元○○》 や 《○○傘下》 などの特徴を持つ場合も
     含まれますか？
  A: **はい、含まれます。**

= 公式は 2 通りに書き分ける:
  - 素の 「特徴《X》を持つ」          → **完全一致** (`feature` / `leader_feature`)
  - 「『X』を含む特徴を持つ」          → **部分一致** (`feature_contains` / `leader_feature_contains`)

⚠ 部分一致を完全一致で実装すると 《元X》《X傘下》 が **黙って対象外** になる。
  2026-08-21 の初回実行で 33 カード / 36 箇所 + リーダー条件 46 カード / 47 箇所を検出した
  (『白ひげ海賊団』 → 元白ひげ海賊団 12 枚 + 白ひげ海賊団傘下 23 枚 /
   『B・W』 → 元B・W 39 枚 が対象外になっていた)。

⚠ 逆向き (部分一致を使いすぎ) も撃つ。 特徴には '月' ⊂ '光月家' のような **偶然の**
  部分文字列関係があり、 素の 「特徴《月》」 に contains を使うと 光月家 まで拾ってしまう。

exit 1 = 違反あり。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 「『X』を含む特徴」 と 「特徴『X』を含む」 の 2 語形 (OP07-094 は後者)
CONTAINS_RE = re.compile(
    r"[「『]([^」』]+)[」』]\s*を含む特徴|特徴\s*[「『]([^」』]+)[」』]\s*を含む"
)
EXACT_KEYS = {"feature", "leader_feature"}
LIST_KEYS = {"feature_any", "leader_features_any"}
CONTAINS_KEYS = {"feature_contains", "leader_feature_contains"}


def _walk(o, out: list) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            out.append((k, v))
            _walk(v, out)
    elif isinstance(o, list):
        for x in o:
            _walk(x, out)


def main() -> int:
    cards = {c["card_id"]: c for c in json.loads(
        (ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    missing, extra = [], []
    for cid, entries in ov.items():
        if not isinstance(entries, list) or not entries:
            continue
        c = cards.get(cid) or {}
        text = (c.get("text") or "") + "\n" + (c.get("trigger") or "")
        wanted = {m[0] or m[1] for m in CONTAINS_RE.findall(text)}
        kv: list = []
        _walk(entries, kv)
        for k, v in kv:
            if k in EXACT_KEYS and isinstance(v, str) and v in wanted:
                missing.append((cid, k, v))
            elif k in LIST_KEYS and isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and x in wanted:
                        missing.append((cid, k, x))
            elif k in CONTAINS_KEYS and isinstance(v, str) and v not in wanted:
                extra.append((cid, k, v))

    print(f"① 公式が 「を含む特徴」 なのに完全一致キー: {len(missing)} 件")
    for cid, k, v in missing[:60]:
        print(f"   {cid}  {k}='{v}'")
    print(f"② 公式が 「を含む特徴」 でないのに contains キー: {len(extra)} 件")
    for cid, k, v in extra[:60]:
        print(f"   {cid}  {k}='{v}'")
    if missing or extra:
        print("\nNG: 公式の書き分けと overlay が不一致")
        return 1
    print("\nOK: 「を含む特徴」 の書き分けは overlay と一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
