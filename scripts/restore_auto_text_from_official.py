"""[auto] / 簡略 / 補完 marker 残 entries の `_text` を 公式テキスト の 該当 sentence で 上書き。

対象: db/card_effects.json の 各 effect entry で `_text` に SIMPLIFIED_MARKERS が 含まれる もの。
方針: engine semantics (= when/if/do) は 変更せず、 `_text` のみ 公式テキスト 該当 sentence に
書き換える。 該当 sentence が 1 つ に 特定 できない 場合 は skip。

検出 パターン (= 公式テキスト 中 の 1 sentence と overlay の when/if/do の 対応):
1. on_attached_don + power_pump (= 静的 buff):
   - 「【(自分|相手)のターン中】(自分のリーダーが特徴《X》を持つ場合、)?このキャラのパワー[+\-]N」
   - 「自分のリーダーが特徴《X》を持つ場合、 このキャラのパワー+N」
2. (将来 拡張) その他 when/primitive の パターン

副作用 0: when/if/do は 触らない (= 既存 conditions が 正しい 場合 のみ 適用)。
副作用 がある (= 既存 condition が 公式と 一致しない) 場合 は skip して report に 出す。

実行:
  .venv/bin/python scripts/restore_auto_text_from_official.py [--apply]
  デフォルト dry-run (= 変更案 のみ 出力)。 --apply で db/card_effects.json を 書換。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_PATH = ROOT / "db" / "card_effects.json"
CARDS_PATH = ROOT / "db" / "cards.json"

SIMPLIFIED_MARKERS = ("fallback", "簡略", "[auto]", "省略", "近似", "自動抽出", "補完")


def has_marker(text: str) -> bool:
    return any(m in (text or "") for m in SIMPLIFIED_MARKERS)


# パターン: 「【(自分|相手)のターン中】(自分のリーダーが特徴《X》を持つ場合、)?このキャラのパワー[+\-]N」
PAT_TURN_FEAT_PUMP = re.compile(
    r"【(?P<turn>自分のターン中|相手のターン中)】"
    r"(?:自分のリーダーが特徴《(?P<feat>[^》]+)》を持つ場合、?)?"
    r"このキャラのパワー(?P<sign>[+\-−])(?P<n>\d+)。?"
)
# パターン: 「自分のリーダーが特徴《X》を持つ場合、このキャラのパワー+N」 (= 静的、 turn 修飾 なし)
PAT_FEAT_ONLY_PUMP = re.compile(
    r"自分のリーダーが特徴《(?P<feat>[^》]+)》を持つ場合、?このキャラのパワー(?P<sign>[+\-−])(?P<n>\d+)。?"
)


def find_matching_sentence(card_text: str, eff: dict) -> str | None:
    """eff の when/if/do に 対応する 公式テキスト sentence を 探して 返す。
    対応 1 件 のみ 特定 できれば その文字列、 0 or 2+ なら None (= skip)。
    """
    when = eff.get("when")
    if_block = eff.get("if") or {}
    do = eff.get("do", [])
    if not do or not isinstance(do[0], dict):
        return None
    prim_key = list(do[0].keys())[0]
    prim_val = do[0][prim_key]

    # ケース 1: on_attached_don + power_pump (= 静的 buff)
    if when == "on_attached_don" and prim_key == "power_pump":
        target = (prim_val or {}).get("target")
        amount = int((prim_val or {}).get("amount", 0))
        if target != "self":
            return None
        # if の condition から 期待する turn / feat を 取得
        expected_turn = None
        if if_block.get("opp_turn"):
            expected_turn = "相手のターン中"
        elif if_block.get("self_turn"):
            expected_turn = "自分のターン中"
        expected_feat = if_block.get("leader_feature")

        # パターン 1: 【ターン】 + (feat) + パワー±N
        candidates = []
        for m in PAT_TURN_FEAT_PUMP.finditer(card_text):
            cand_turn = m.group("turn")
            cand_feat = m.group("feat")
            cand_sign = m.group("sign")
            cand_n = int(m.group("n"))
            signed_n = -cand_n if cand_sign in ("-", "−") else cand_n
            if expected_turn and cand_turn != expected_turn:
                continue
            if expected_feat and cand_feat != expected_feat:
                continue
            if not expected_feat and cand_feat is not None:
                continue
            if signed_n != amount:
                continue
            candidates.append(m.group(0))

        # パターン 2: feat のみ (= turn 修飾 なし)
        if expected_turn is None:
            for m in PAT_FEAT_ONLY_PUMP.finditer(card_text):
                # turn 修飾 ない パターン だけ 拾う (= turn pattern と 重複 防止)
                if m.start() > 0 and card_text[max(0, m.start() - 12):m.start()].find("ターン中】") != -1:
                    continue
                cand_feat = m.group("feat")
                cand_sign = m.group("sign")
                cand_n = int(m.group("n"))
                signed_n = -cand_n if cand_sign in ("-", "−") else cand_n
                if expected_feat and cand_feat != expected_feat:
                    continue
                if signed_n != amount:
                    continue
                candidates.append(m.group(0))

        if len(candidates) == 1:
            return candidates[0]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    cards_list = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in cards_list}

    fixed_count = 0
    skipped_count = 0
    report: list[str] = []

    for cid, ents in overlay.items():
        if not isinstance(ents, list):
            continue
        card = cards.get(cid)
        if not card:
            continue
        card_text = card.get("text") or ""
        for i, eff in enumerate(ents):
            if not isinstance(eff, dict):
                continue
            txt = eff.get("_text") or ""
            if not has_marker(txt):
                continue
            new_text = find_matching_sentence(card_text, eff)
            if new_text is None:
                skipped_count += 1
                continue
            old_text = txt
            eff["_text"] = new_text
            fixed_count += 1
            report.append(f"{cid}[{i}]:\n  - old: {old_text}\n  + new: {new_text}")

    print(f"fixed: {fixed_count}")
    print(f"skipped (= pattern 未対応 or 曖昧): {skipped_count}")
    print("---")
    for line in report[:30]:
        print(line)
        print()

    if args.apply and fixed_count > 0:
        # 既存 _meta は 保持、 ordered dict 形式 で 書き戻し
        OVERLAY_PATH.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✓ wrote {OVERLAY_PATH}")
    elif fixed_count > 0:
        print(f"\n(dry-run) {fixed_count} entries would be fixed. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
