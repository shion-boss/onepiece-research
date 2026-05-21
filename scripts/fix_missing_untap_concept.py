#!/usr/bin/env python3
"""overlay が 「アクティブにする」 効果を 別 primitive (= draw 等) で 代用している ケースを 修正。

実例:
  OP05-022 text: 「リーダーをアクティブにする」 → overlay [draw: 1] (誤)
  OP15-022 text: 「自分のキャラ1枚をアクティブにする」 → overlay [draw: 1] (誤)
  OP11-021 text: 「特徴X キャラ1枚 + ドン1枚 アクティブにする」 → overlay [draw: 1] (誤)
  OP11-067 text: 「特徴 BM キャラ2枚 アクティブにする + ドン1枚レスト追加」 → overlay [add_rested_don: 1] のみ (キャラ untap 欠落)

修正:
  text に 「アクティブにする」 がある + overlay に untap 系 primitive なし の 場合、
  text を 解析して 適切な untap primitive を 追加 / 入れ替え。

検出 untap 種別:
  「リーダーをアクティブにする」 → untap: self_leader
  「自分のキャラ N 枚 までを、 アクティブにする」 → untap_chara N
  「自分のドン!! N 枚 までを、 アクティブにする」 → untap_don: N (= reactive、 add_don でない)
  「特徴《X》... キャラ N 枚 までを、 アクティブにする」 → untap_chara with filter
  「このキャラを アクティブにする」 → untap: self
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


def parse_untap_primitives(text: str) -> list[dict]:
    """text の 「アクティブにする」 関連 phrase から untap primitive list を 生成。"""
    primitives = []
    t = text.replace("‼", "!!").replace("！", "!")

    # 「このリーダーをアクティブにする」
    if re.search(r"(?:この)?リーダー(?:を|は)?アクティブにする", t):
        primitives.append({"untap": "self_leader"})

    # 「このキャラをアクティブにする」
    if re.search(r"このキャラをアクティブにする", t):
        primitives.append({"untap": "self"})

    # 「自分の(特徴《X》(か《Y》)?を持つ)?キャラN枚までを、アクティブにする」
    m = re.search(
        r"自分の.{0,30}キャラ\s*(\d+)\s*枚までを、?\s*アクティブにする",
        t,
    )
    if m:
        n = int(m.group(1))
        # filter 抽出
        # 前 30 chars (= 「自分の」 から このマッチ start まで) で 特徴等
        # 簡略: 同じ clause で 「特徴《X》」/「コスト N 以上」 を 探す
        clause_start = max(0, m.start() - 60)
        clause = t[clause_start:m.end()]
        flt = {}
        fm = re.search(r"特徴《(.+?)》(?:か《(.+?)》)?を持つ", clause)
        if fm:
            if fm.group(2):
                flt["or_clauses"] = [{"feature": fm.group(1)}, {"feature": fm.group(2)}]
            else:
                flt["feature"] = fm.group(1)
        cm = re.search(r"コスト\s*(\d+)\s*以上", clause)
        if cm:
            flt["cost_ge"] = int(cm.group(1))
        cm2 = re.search(r"コスト\s*(\d+)\s*以下", clause)
        if cm2:
            flt["cost_le"] = int(cm2.group(1))
        # power_ge
        pm = re.search(r"パワー\s*(\d+)\s*以上", clause)
        if pm:
            flt["power_ge"] = int(pm.group(1))
        if flt:
            primitives.append({"untap_chara": {"target": "self_chara_filtered", "filter": flt, "count": n}})
        else:
            primitives.append({"untap_chara": {"count": n}})

    # 「自分のドン!! N 枚 まで を、 アクティブにする」 (= untap_don)
    m = re.search(r"自分のドン!!\s*(\d+)\s*枚までを、?\s*アクティブにする", t)
    if m:
        primitives.append({"untap_don": int(m.group(1))})

    return primitives


def main():
    fixed = 0
    log = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list) or not entries:
            continue
        text = get_text(cid)
        if not text or "アクティブにする" not in text:
            continue
        flat = json.dumps(entries, ensure_ascii=False)
        if '"untap"' in flat or "untap_chara" in flat or "untap_don" in flat:
            continue  # 既に untap 系 あり、 別 entry の問題
        new_prims = parse_untap_primitives(text)
        if not new_prims:
            continue
        # 適切な when の entry を 探す
        # text の どの 区間 に 「アクティブにする」 があるか で 推定
        when = None
        if "【自分のターン終了時】" in text or "【ターン終了時】" in text:
            when = "end_of_turn"
        elif "【登場時】" in text:
            when = "on_play"
        elif "【アタック時】" in text:
            when = "on_attack"
        elif "【起動メイン】" in text:
            when = "activate_main"
        else:
            when = "on_play"
        added = False
        for entry in entries:
            if isinstance(entry, dict) and entry.get("when") == when:
                do = entry.setdefault("do", [])
                # 既存の `draw: 1` placeholder を削除 (= 誤実装)
                # placeholder 検出: draw のみ あり / 他効果なし
                if len(do) == 1 and "draw" in do[0] and "カード1枚を引く" not in text and "カード\\d+枚を引く" not in text:
                    log.append(f"  {cid} [{when}]: replaced placeholder draw with {[list(p.keys())[0] for p in new_prims]}")
                    do.clear()
                do.extend(new_prims)
                added = True
                break
        if not added:
            entries.append({
                "_text": f"[auto] {when}: untap 補完",
                "when": when,
                "do": new_prims,
            })
            log.append(f"  {cid}: new {when} entry with {[list(p.keys())[0] for p in new_prims]}")
        fixed += 1

    print(f"Fixed {fixed} cards")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_missing_untap_log.md").write_text(
        "# untap_concept 補完ログ\n\n" + "\n".join(log), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
