#!/usr/bin/env python3
"""fix_fake_power_5000_target.py 残 59 件 を 修正。

v1 は entry._text 優先で 推論したが、 略式 (= 「相手キャラ1体」) で regex 不一致 が 多い。
v2 は card_text 全文 を ベース に 「同 when の primitive で 対応する 公式テキスト 範囲」 を 推定。

修正規則 拡張:
- 「相手のキャラN枚まで」 + power-/コスト- だけ → one_opponent_character_any
- 「相手のリーダーかキャラN枚まで」 → one_opponent_inplay_any
- 「コストN以下のキャラ」 → one_opponent_character_cost_le_N
- 「特徴《X》のキャラ」 → one_opponent_chara_filtered (feature=X)
- 「相手のキャラすべて」 → all_opponent_characters
- 「相手のレストのキャラ」 → one_opponent_chara_filtered (rested=true)

各 primitive (= ko / rest / power_pump / return_to_hand / set_base_cost_timed / give_keyword) の
context (= 公式テキスト の 対応 句) を 探して 正しい target に 置換。
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

PRIMITIVE_KEYWORDS = {
    "ko": [r"KOする", r"ＫＯする"],
    "rest": [r"レストにする", r"レストに(?:し|する)"],
    "return_to_hand": [r"手札に戻す", r"持ち主の手札に戻す"],
    "power_pump_minus": [r"パワー\s*-\s*\d+", r"パワー\s*−\s*\d+"],
    "power_pump_plus": [r"パワー\s*\+\s*\d+"],
    "cost_minus": [r"コスト\s*-\s*\d+", r"コスト\s*−\s*\d+"],
}


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def find_target_for_primitive(card_text: str, prim_name: str, amount: int | None = None) -> dict | str | None:
    """指定 primitive の text 句 を 探し、 相手 target 句 を 抽出。

    例: prim_name="power_pump_minus", amount=3000
        card_text 中で 「パワー-3000」 の 句 を 探し、 その 前後 に 「相手の...キャラ」 を find。
    """
    keywords = PRIMITIVE_KEYWORDS.get(prim_name, [])
    if prim_name in ("power_pump_minus", "power_pump_plus") and amount is not None:
        sign = "-" if "minus" in prim_name else r"\+"
        keywords = [rf"パワー\s*{sign}\s*{amount}\b", rf"パワー\s*{sign}\s*{amount}$"]
    elif prim_name == "cost_minus" and amount is not None:
        keywords = [rf"コスト\s*-\s*{amount}\b"]
    for kw in keywords:
        m = re.search(kw, card_text)
        if not m:
            continue
        # 句 の 前 80 chars に 相手 target 句
        start = max(0, m.start() - 100)
        ctx = card_text[start:m.end()]
        return _parse_opponent_target(ctx)
    # fall back: 全文 から 相手 target 句 を 抽出 (= 単独 primitive の カード)
    return _parse_opponent_target(card_text)


def _parse_opponent_target(ctx: str) -> dict | str | None:
    """ctx 内の 「相手の...キャラ」 表現を target spec に変換。 1 文脈 (= ctx) 単位 で 最も近い 表現を採用。"""
    # 「相手の、リーダーかキャラN枚」 / 「相手のリーダーかキャラN枚」
    if re.search(r"相手の.{0,3}リーダーかキャラ", ctx):
        # コスト N 以下 / 以上 修飾
        m = re.search(r"相手の.{0,3}リーダーかキャラ.{0,15}コスト(\d+)以下", ctx)
        if m:
            return f"one_opponent_inplay_cost_le_{m.group(1)}"
        m = re.search(r"相手の.{0,3}コスト(\d+)以下の.{0,3}リーダーかキャラ", ctx)
        if m:
            return f"one_opponent_inplay_cost_le_{m.group(1)}"
        return "one_opponent_inplay_any"
    # 「相手のレストのコストN以下のキャラ」
    m = re.search(r"相手の.{0,5}レストの.{0,10}コスト(\d+)以下のキャラ", ctx)
    if m:
        return {"type": "one_opponent_character_filtered", "filter": {"cost_le": int(m.group(1)), "rested": True}}
    # 「相手のレストのキャラ」
    if re.search(r"相手の.{0,5}レストのキャラ", ctx):
        return {"type": "one_opponent_character_filtered", "filter": {"rested": True}}
    # 「相手のコストN以下のキャラ」
    m = re.search(r"相手の.{0,15}コスト(\d+)以下のキャラ", ctx)
    if m:
        return f"one_opponent_character_cost_le_{m.group(1)}"
    # 「相手のパワーN以下のキャラ」
    m = re.search(r"相手の.{0,5}パワー(\d+)以下のキャラ", ctx)
    if m:
        n = int(m.group(1))
        if n == 5000:
            return "one_opponent_character_le_5000"
        if n == 4000:
            return "one_opponent_character_le_4000"
        return f"one_opponent_character_power_le_{n}"
    # 「相手の元々のパワーN以下のキャラ」
    m = re.search(r"相手の.{0,5}元々のパワー(\d+)以下のキャラ", ctx)
    if m:
        return {
            "type": "one_opponent_character_filtered",
            "filter": {"truly_original_power_le": int(m.group(1))},
        }
    # 「相手の特徴《X》(を持つ)?キャラ」
    m = re.search(r"相手の.{0,3}特徴《(.+?)》(?:を持つ)?キャラ", ctx)
    if m:
        return {"type": "one_opponent_character_filtered", "filter": {"feature": m.group(1)}}
    # 「相手のキャラすべて」 / 「相手のキャラ全部」
    if re.search(r"相手のキャラ(?:すべて|全て|全部)", ctx):
        return "all_opponent_characters"
    # 「相手のキャラN枚まで」 / 「相手のキャラ」 (汎用)
    if re.search(r"相手のキャラ", ctx):
        return "one_opponent_character_any"
    return None


def _detect_count_limit(card_text: str, primitive_keywords: list[str]) -> int | None:
    """text 全文 から 「相手のキャラ N 枚まで」 の N を 取得 (= 該当 句 が primitive にも 該当する 場合)。"""
    for kw_pat in primitive_keywords:
        m = re.search(kw_pat, card_text)
        if not m:
            continue
        # 句 周辺 100 chars に 相手のキャラ N 枚まで
        start = max(0, m.start() - 80)
        ctx = card_text[start : m.end() + 30]
        cm = re.search(r"相手のキャラ\s*(\d+)\s*枚まで", ctx)
        if cm:
            return int(cm.group(1))
    # 全文 fallback
    cm = re.search(r"相手のキャラ\s*(\d+)\s*枚まで", card_text)
    if cm:
        return int(cm.group(1))
    return None


def fix_entry(cid: str, entry: dict, card_text: str) -> tuple[bool, list[str]]:
    if not isinstance(entry, dict):
        return False, []
    log = []
    changed = False

    def walk(node, parent_key=None):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if k == "target" and isinstance(v, str) and "_le_5000" in v:
                    # parent primitive の amount を 取得
                    amount = None
                    if isinstance(node.get("amount"), int):
                        amount = abs(node["amount"])
                    sign_minus = isinstance(node.get("amount"), int) and node["amount"] < 0
                    if parent_key == "power_pump":
                        prim_name = "power_pump_minus" if sign_minus else "power_pump_plus"
                    elif parent_key == "set_base_cost_timed":
                        prim_name = "cost_minus"
                    else:
                        prim_name = parent_key or "ko"
                    # 「N 枚まで」 N≥2 で any_*_le_5000 の場合 → all_opponent_chara_filtered (limit=N)
                    if v.startswith("any_") and v.endswith("_le_5000"):
                        kw_lookup = PRIMITIVE_KEYWORDS.get(prim_name, [])
                        if prim_name in ("power_pump_minus", "power_pump_plus") and amount:
                            sign = "-" if "minus" in prim_name else r"\+"
                            kw_lookup = [rf"パワー\s*{sign}\s*{amount}\b"]
                        n_limit = _detect_count_limit(card_text, kw_lookup)
                        if n_limit and n_limit >= 2:
                            node[k] = {
                                "type": "all_opponent_chara_filtered",
                                "filter": {},
                                "limit": n_limit,
                            }
                            log.append(f"  target ({parent_key}): {v} → all_opponent_chara_filtered limit={n_limit}")
                            changed = True
                            continue
                    new = find_target_for_primitive(card_text, prim_name, amount)
                    if new and new != v:
                        node[k] = new
                        log.append(f"  target ({parent_key} amount={amount}): {v} → {new}")
                        changed = True
                elif isinstance(v, str) and v.endswith("_le_5000") and k in (
                    "ko", "rest", "return_to_hand", "stay_rested_next_refresh",
                    "untap_chara", "disable_effect", "negate_effect",
                ):
                    prim_name = k
                    new = find_target_for_primitive(card_text, prim_name)
                    if new and new != v:
                        node[k] = new
                        log.append(f"  {k}: {v} → {new}")
                        changed = True
                else:
                    walk(v, k)
        elif isinstance(node, list):
            for x in node:
                walk(x, parent_key)

    walk(entry)
    return changed, log


def main():
    fixed_cards = 0
    total_changes = 0
    log_lines: list[str] = []
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
                log_lines.append(f"## {cid}")
                log_lines.extend(log)
                total_changes += len(log)
        if any_changed:
            fixed_cards += 1

    print(f"Fixed {fixed_cards} cards, {total_changes} target changes")
    (ROOT / "db" / "card_effects.json").write_text(
        json.dumps(OVERLAY, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "db" / "fix_fake_power_5000_v2_log.md").write_text(
        "# fake_power_5000 v2 修正ログ\n\n" + "\n".join(log_lines), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
