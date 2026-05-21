#!/usr/bin/env python3
"""base card の overlay を 全 variant (= _p1/_p2/_r1/etc) に コピー。

問題:
  engine は `overlay.get(card_id)` で 厳密一致 lookup する。 variant `OP01-001_p1` が
  デッキに入ると、 overlay[OP01-001_p1] が 空なら 効果なし になる。 base の OP01-001 と
  同一カードなのに 別実装扱い。

修正:
  base card の overlay が non-empty なら、 variant の overlay も 同じ内容に。
  variant の overlay が 既に non-empty で 異なる場合は スキップ (= variant固有実装 を 尊重)。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


VARIANT_RE = re.compile(r"^(.+?)_(p\d+|r\d+|sr\d+|sec\d+|sp\d+|alt\d+|R\d+)$")


def base_id(cid: str) -> str | None:
    m = VARIANT_RE.match(cid)
    return m.group(1) if m else None


def main():
    copied = 0
    skipped_has_own = 0
    log = []
    for cid in list(OVERLAY.keys()):
        if cid.startswith("_"):
            continue
        b = base_id(cid)
        if b is None:
            continue
        base_entries = OVERLAY.get(b)
        if not isinstance(base_entries, list) or len(base_entries) == 0:
            continue  # base 側 が 空 → 補完できない
        cur = OVERLAY.get(cid)
        if isinstance(cur, list) and len(cur) > 0:
            skipped_has_own += 1
            continue  # variant 側 既に non-empty
        # copy
        OVERLAY[cid] = json.loads(json.dumps(base_entries, ensure_ascii=False))  # deep copy
        copied += 1
        log.append(f"  {cid} ← {b}: {len(base_entries)} entries copied")

    print(f"Copied to {copied} variants ({skipped_has_own} variants had own overlay, skipped)")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "duplicate_variant_overlay_log.md").write_text(
        "# variant overlay 自動コピーログ\n\n" + "\n".join(log[:200]), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
