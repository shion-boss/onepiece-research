#!/usr/bin/env python3
"""overlay の 「one_opponent_character_le_5000」 を 公式テキスト に 合わせて 修正。

問題:
  overlay が target に `one_opponent_character_le_5000` を 使ってる が、
  engine 実装上 これは 「パワー5000以下 のキャラ限定 + リーダー除外」 を 強制する。
  公式テキストに この制限がない カードでは、 narrow バグ となる。

修正規則 (per entry):
  text に  「相手のリーダーかキャラ」 → one_opponent_inplay_any
  text に  「相手の特徴《X》を持つキャラ」 → one_opponent_character_any (+ filter で feature)
  text に  「相手のコストN以下のキャラ」 → one_opponent_character_cost_le_N
  text に  「相手のパワーN以下のキャラ」 (N≠5000) → one_opponent_character_le_N (engine 拡張要)
  text に  「相手のキャラ」 (qualifier なし) → one_opponent_character_any
  text に  「相手のパワー5000以下のキャラ」 → そのまま (現状正しい)
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def infer_target_from_text(entry_text: str, card_text: str) -> str | None:
    """entry の _text または card_text 全文から 正しい target を 推定。"""
    # _text > card_text の 優先で
    text = entry_text or card_text
    # 「相手のリーダーかキャラ」
    if re.search(r"相手の.{0,8}リーダーかキャラ", text):
        return "one_opponent_inplay_any"
    # 「相手のレストのキャラ」 (no power limit)
    if re.search(r"相手の.{0,5}レストのキャラ", text) and "パワー5000以下" not in text and "コスト" not in text:
        return None  # keep le_5000 or convert? -> "rested" + no power limit. 別 spec 必要
    # 「コストN以下」 (= rested + cost_le)
    m = re.search(r"相手の.{0,5}レストの.{0,10}コスト(\d+)以下のキャラ", text)
    if m:
        return f"one_opponent_rested_character_cost_le_{m.group(1)}"
    # 「相手のコストN以下のキャラ」
    m = re.search(r"相手の.{0,15}コスト(\d+)以下のキャラ", text)
    if m:
        # リーダーかキャラ も視野
        if "リーダーかキャラ" in text:
            return f"one_opponent_inplay_cost_le_{m.group(1)}"
        return f"one_opponent_character_cost_le_{m.group(1)}"
    # 「相手のパワーN以下のキャラ」
    m = re.search(r"相手の.{0,8}パワー(\d+)以下のキャラ", text)
    if m:
        n = int(m.group(1))
        if n == 5000:
            return None  # already correct
        if n == 4000:
            return "one_opponent_character_le_4000"
        # parametric 形式 (= engine 対応済)
        return f"one_opponent_character_power_le_{n}"
    # 「相手の特徴《X》のキャラ」 — keep filter-based target (= 別変換要)
    if re.search(r"相手の.{0,5}特徴《.+?》.{0,5}キャラ", text):
        return None  # filtered target が必要、 mass-fix 対象外
    # 「相手のキャラ」 (= 単純 qualifier なし)
    if re.search(r"相手の(?:キャラ|レストの.*)?キャラ", text) or re.search(r"相手のキャラ", text):
        return "one_opponent_character_any"
    return None


def fix_entry(cid: str, entry: dict, card_text: str) -> tuple[bool, list[str]]:
    """entry 内の primitive を 修正。 戻り値 = (changed, change_log)"""
    if not isinstance(entry, dict):
        return False, []
    entry_text = entry.get("_text", "")
    log = []
    changed = False

    def fix_target(target_val: str) -> str | None:
        if target_val == "one_opponent_character_le_5000":
            inferred = infer_target_from_text(entry_text, card_text)
            if inferred and inferred != target_val:
                return inferred
        elif target_val == "any_opponent_character_le_5000":
            # board wipe 系: 公式 が 「相手のキャラ全部」 なら all_opponent_characters
            text = entry_text or card_text
            if re.search(r"相手のキャラすべて|相手のキャラ全部", text):
                return "all_opponent_characters"
        return None

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k == "target" and isinstance(v, str):
                    new = fix_target(v)
                    if new:
                        node[k] = new
                        log.append(f"{k}: {v} → {new}")
                        changed = True
                elif isinstance(v, str) and v.endswith("_character_le_5000") and k in ("ko", "rest", "return_to_hand", "stay_rested_next_refresh", "untap_chara", "disable_effect"):
                    # primitive の 直接 値 が target string の場合
                    new = fix_target(v)
                    if new:
                        node[k] = new
                        log.append(f"{k}={v} → {new}")
                        changed = True
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(entry)
    return changed, log


def main():
    fixed_cards = 0
    total_changes = 0
    change_log: list[str] = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_") or not isinstance(entries, list):
            continue
        card_text = get_text(cid)
        if not card_text:
            continue
        any_changed = False
        for entry in entries:
            changed, log = fix_entry(cid, entry, card_text)
            if changed:
                any_changed = True
                for line in log:
                    change_log.append(f"  {cid}: {line}")
                    total_changes += 1
        if any_changed:
            fixed_cards += 1

    print(f"Fixed {fixed_cards} cards, {total_changes} target fixes")
    # save
    out = ROOT / "db" / "card_effects.json"
    out.write_text(json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out}")
    # change log
    log_out = ROOT / "db" / "fix_fake_power_5000_log.md"
    log_out.write_text("# fake_power_5000 修正ログ\n\n" + "\n".join(change_log), encoding="utf-8")
    print(f"Wrote: {log_out}")


if __name__ == "__main__":
    main()
