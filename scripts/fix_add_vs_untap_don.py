#!/usr/bin/env python3
"""overlay の `add_don` を `untap_don` に 直す (= 公式テキスト に 合わせる)。

問題:
  公式テキスト 「自分のドン!!N枚までを、アクティブにする」 (= 既存ドンを活性化) を
  overlay で `add_don: N` (= ドン!!デッキから新規追加) として実装している。

  正しい区別:
    - 「ドン!!デッキから、ドン!!N枚までをアクティブで追加」 → add_don (= 新規追加)
    - 「自分のドン!!N枚までを、アクティブにする」 → untap_don (= 活性化)

検出規則 (per entry):
  公式テキストに 「自分のドン!!.*アクティブにする」 か 「ドン!!N枚までを、アクティブにする」 (デッキから 言及なし) → untap_don
  公式テキストに 「ドン!!デッキから.*アクティブで追加」 → add_don (= keep)

修正 規則:
  add_don の primitive を 持つ entry の _text が untap pattern なら add_don → untap_don
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


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def is_untap_pattern(text: str) -> bool:
    """text が 「アクティブにする」 (= untap pattern) を 含み、 「アクティブで追加」 (= add) で ない。"""
    if "アクティブにする" not in text:
        return False
    # 「デッキから ... アクティブで追加」 が ない こと
    if re.search(r"ドン.{0,3}デッキから.{0,40}アクティブで追加", text):
        return False
    return True


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        card_text = get_text(cid)
        if not card_text:
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            # 公式テキスト 全文 で 判定 (= entry の _text は 開発者ノートで信用しない)
            check_text = card_text
            if not is_untap_pattern(check_text):
                continue
            # do 内 の add_don を untap_don に
            do = entry.get("do") or []
            for prim in do:
                if isinstance(prim, dict) and "add_don" in prim:
                    val = prim["add_don"]
                    del prim["add_don"]
                    prim["untap_don"] = val
                    log.append(f"  {cid} [{i}]: add_don: {val} → untap_don: {val}")
                    fixed += 1
    print(f"Fixed {fixed} primitives")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_add_vs_untap_don_log.md").write_text(
        "# add_don → untap_don 修正ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
