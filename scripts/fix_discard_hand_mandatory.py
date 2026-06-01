#!/usr/bin/env python3
"""二重discard systematic 是正 — mand型 (強制 draw+discard / 強制 discard)。

「カードN枚を引き、手札M枚を捨てる」 等の強制効果で discard が cost:{discard_hand:M}
(action-cost) と do:[trash_self_hand_random:M] の両方に入り二重 discard だった分。
discard は効果 (do) 側が正 なので entry cost:{discard_hand} を除去 (once_per_turn 温存)。
「カードN枚を引[きい]」 があり do に draw が無ければ draw:N を do 先頭に補填 (= 欠落是正)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF = ROOT / "db" / "card_effects.json"
CARDS = ROOT / "db" / "cards.json"

Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
KANJI = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}


def draw_count(text: str) -> int | None:
    """「カードN枚を引き … 捨てる」 と draw→discard が **同一節** の時だけ N を返す。
    別 ability の draw を discard entry に誤付与しない (= EB03-028/EB02-030 等の FP 防止)。"""
    t = text.translate(Z2H)
    m = re.search(r"カード(\d+)枚を?引[きい][^。]{0,18}捨て", t)
    if m:
        return int(m.group(1))
    m = re.search(r"カード([一二三四五])枚を?引[きい][^。]{0,18}捨て", t)
    if m:
        return KANJI.get(m.group(1))
    return None


def main() -> None:
    eff = json.loads(EFF.read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in json.loads(CARDS.read_text(encoding="utf-8"))}
    decost = []
    drawfix = []
    for cid, ents in eff.items():
        if not isinstance(ents, list) or cid not in cards:
            continue
        text = (cards[cid].get("text") or "") + (cards[cid].get("trigger") or "")
        # opt型 (できる：) は別 script で処理済。 ここは mand型のみ。
        if "捨てることができる：" in text or "捨てることができます：" in text:
            continue
        for e in ents:
            if not isinstance(e, dict):
                continue
            cost = e.get("cost")
            if not (isinstance(cost, dict) and "discard_hand" in cost):
                continue
            do = e.get("do", [])
            if not any(isinstance(d, dict) and "trash_self_hand_random" in d for d in do):
                continue
            # discard は do (強制効果) 側を残し、 entry cost の discard_hand を除去
            cost.pop("discard_hand", None)
            if not cost:
                e.pop("cost", None)
            decost.append(cid)
            # 欠落 draw 補填
            n = draw_count(text)
            has_draw = any(isinstance(d, dict) and "draw" in d for d in do)
            if n and not has_draw:
                e["do"] = [{"draw": n}] + do
                drawfix.append(f"{cid}(+draw{n})")
            if "_text" in e and "[dd-mand]" not in e["_text"]:
                e["_text"] += " [dd-mand]"
    EFF.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"mand型 entry cost.discard_hand 除去: {len(set(decost))} card")
    print(f"欠落 draw 補填: {len(drawfix)} — {drawfix[:20]}")


if __name__ == "__main__":
    main()
