"""cards.json の公式テキストから「ルール上、このカードはカード名を「X」としても扱う」を抽出する。

出力: db/card_alt_names.json ({"alt_names": {card_id: [別名...]}})。
新弾取込後に再生成する (scripts/refresh_all.py から呼んでもよい)。

    .venv/bin/python scripts/build_card_alt_names.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"ルール上、このカードはカード名を(.+?)としても扱う")


def main() -> None:
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    lst = cards if isinstance(cards, list) else (cards.get("cards") or [])
    out: dict[str, list[str]] = {}
    for c in lst:
        m = PAT.search(c.get("text") or "")
        if not m:
            continue
        names = re.findall(r"「([^」]+)」", m.group(1))
        if names:
            out[c["card_id"]] = names
    doc = {
        "_doc": (
            "公式ルール 「ルール上、このカードはカード名を「X」としても扱う」 の別名テーブル。"
            " cards.json の text から機械抽出 (このスクリプト)。"
            " 名前一致 (filter name/name_in/exclude_name/feature_or_name、 target spec *_named_X、"
            " サーチ等) はこの別名も一致とみなす。"
            " ⚠ 「カード名の異なるキャラ」 の種類数えでは別名を数えない (公式 Q&A、 EB04-038 は 1 種類)。"
        ),
        "alt_names": out,
    }
    (ROOT / "db" / "card_alt_names.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"別名を持つカード: {len(out)} 枚 → db/card_alt_names.json")


if __name__ == "__main__":
    main()
