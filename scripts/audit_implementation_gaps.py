"""総合 implementation gap 監査。
紫ドフラ系の opp_turn 系 以外 にも 残っている 実装漏れ を 検出。

Audit項目:
  1. _unimplemented marker 残存
  2. empty do[] (= 効果が空、 仕様 として 「効果無し」 は OK だが 実装漏れ の 場合 あり)
  3. when 未設定 / 不正
  4. 公式テキスト 長い (= 100 文字+) が overlay 空 or 短い
  5. cost 持ち effect で once_per_turn 未指定 (= text に 「ターン1回」 含むのに)
  6. counter event card で counter 値+cost 両方持つ (= rare だが engine 未対応)
  7. 公式 「【○○】 系 trigger 名」 vs overlay when 値 の カバレッジ
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
OVERLAY_PATH = ROOT / "db" / "card_effects.json"


def main():
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    card_map = {c["card_id"]: c for c in cards}

    # 1. _unimplemented markers
    unimpl = []
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        for i, e in enumerate(effs):
            if isinstance(e, dict) and "_unimplemented" in e:
                unimpl.append((cid, i, e.get("_unimplemented", "")))

    # 2. empty do[]
    empty_do = []
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        for i, e in enumerate(effs):
            if not isinstance(e, dict):
                continue
            do = e.get("do")
            if isinstance(do, list) and len(do) == 0:
                # cost-only effect (= replace_leave 等 で 効果 自体 が survive のみ) は OK
                # それ以外 で empty は 怪しい
                when = e.get("when", "")
                if when not in ("replace_leave", "replace_ko", "replace_rest"):
                    empty_do.append((cid, i, when, e.get("_text", "")[:80]))

    # 3. when 未設定
    no_when = []
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        for i, e in enumerate(effs):
            if isinstance(e, dict) and not e.get("when"):
                no_when.append((cid, i, e.get("_text", "")[:80]))

    # 4. 公式テキスト 100 文字+ but overlay short or missing
    # intrinsic keyword (= cards.json で自動処理) は カウント から 除外
    INTRINSIC_KEYWORDS = [
        "【ブロッカー】", "【ダブルアタック】", "【バニッシュ】", "【速攻】",
        "【ブロック不可】", "【トリガー】", "【効果無効】", "【速攻：キャラ】",
        "【ライフ-1】", "【ライフ-2】", "【ライフ+1】",
    ]
    # キーワード後 括弧 説明 (= 「(相手のアタックの後...)」 等) 除去 用 regex
    paren_after_kw_pattern = re.compile(r"【(?:" + "|".join(re.escape(kw[1:-1]) for kw in INTRINSIC_KEYWORDS) + r")】\s*[\((][^)\)]*[\))]")

    def _normalize_text(t: str) -> str:
        # intrinsic 後の説明 (...) を 除去
        t = paren_after_kw_pattern.sub("", t)
        # intrinsic キーワード 自体 も 除去 (= bracket count に 入れない)
        for kw in INTRINSIC_KEYWORDS:
            t = t.replace(kw, "")
        return t

    text_long_but_overlay_short = []
    for c in cards:
        cid = c["card_id"]
        text = c.get("text", "") or ""
        if len(text) < 100:
            continue
        effs = overlay.get(cid, [])
        if not isinstance(effs, list):
            continue
        norm_text = _normalize_text(text)
        # 効果テキスト合計長 / 各 _text の合計
        overlay_text_len = sum(
            len(str(e.get("_text", ""))) for e in effs if isinstance(e, dict)
        )
        # 公式テキスト の "効果" 部分 (= 【○○】 含む) のみ 比較
        n_brackets_text = norm_text.count("【") + norm_text.count("(") + norm_text.count("(")
        n_brackets_overlay = sum(
            (str(e.get("_text", "")).count("【") + str(e.get("_text", "")).count("("))
            for e in effs if isinstance(e, dict)
        )
        # 公式 brackets > overlay brackets * 2 (= 大幅 不足)
        if n_brackets_text >= 3 and n_brackets_overlay * 2 < n_brackets_text:
            text_long_but_overlay_short.append({
                "card_id": cid,
                "name": card_map.get(cid, {}).get("name", "?"),
                "text_brackets": n_brackets_text,
                "overlay_brackets": n_brackets_overlay,
                "text_len": len(text),
                "overlay_text_len": overlay_text_len,
                "official": text[:150],
            })

    # 5. cost 持ち effect で once_per_turn 未指定 で _text に 「ターン1回」 含む
    missing_opt_flag = []
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        for i, e in enumerate(effs):
            if not isinstance(e, dict):
                continue
            t = str(e.get("_text", ""))
            if "ターン1回" not in t:
                continue
            cost = e.get("cost") or {}
            top_opt = e.get("once_per_turn")
            cost_opt = False
            if isinstance(cost, dict):
                cost_opt = bool(cost.get("once_per_turn"))
            elif isinstance(cost, list):
                cost_opt = any(
                    isinstance(c, dict) and c.get("once_per_turn") for c in cost
                )
            if not (top_opt or cost_opt):
                missing_opt_flag.append((cid, i, e.get("when", ""), t[:80]))

    # 6. counter event card で counter 値 + 公式 cost 両方持つ (= cost.pay_don 未対応)
    counter_event_both = []
    for cid, effs in overlay.items():
        if not isinstance(effs, list):
            continue
        c = card_map.get(cid, {})
        if c.get("category") != "EVENT":
            continue
        counter_val = 0
        try:
            counter_val = int(c.get("counter") or 0)
        except (ValueError, TypeError):
            counter_val = 0
        if counter_val <= 0:
            continue
        for e in effs:
            if isinstance(e, dict) and e.get("when") == "counter":
                counter_event_both.append({
                    "card_id": cid,
                    "name": c.get("name", "?"),
                    "counter": counter_val,
                    "cost": e.get("cost"),
                })

    # 7. 公式 trigger names coverage
    trigger_names = [
        ("【登場時】", "on_play"),
        ("【KO時】", "on_ko"),
        ("【アタック時】", "on_attack"),
        ("【ブロック時】", "on_block"),
        ("【相手のアタック時】", "opp_attack"),
        ("【ターン終了時】", "end_of_turn"),
        ("【相手のターン終了時】", "opp_end_of_turn"),
        ("【自分のターン開始時】", "on_turn_start"),
        ("【相手のターン開始時】", "opp_turn_start"),
        ("【起動メイン】", "activate_main"),
        ("【メイン】", "main"),
        ("【カウンター】", "counter"),
        ("【トリガー】", "trigger"),
    ]
    trigger_coverage = {}
    for jp, en in trigger_names:
        cards_with_text = [c["card_id"] for c in cards if jp in (c.get("text", "") or "")]
        cards_with_overlay = []
        for cid in cards_with_text:
            effs = overlay.get(cid, [])
            if isinstance(effs, list):
                if any(isinstance(e, dict) and e.get("when") == en for e in effs):
                    cards_with_overlay.append(cid)
        trigger_coverage[jp] = (len(cards_with_text), len(cards_with_overlay), [
            cid for cid in cards_with_text if cid not in cards_with_overlay
        ])

    # Output
    print("=" * 70)
    print("総合 implementation gap 監査")
    print("=" * 70)
    print()
    print(f"1. _unimplemented marker: {len(unimpl)}")
    for cid, idx, msg in unimpl[:5]:
        print(f"  {cid} #{idx}: {msg[:60]}")
    print()
    print(f"2. empty do[] (= replace_* 以外): {len(empty_do)}")
    for cid, idx, when, t in empty_do[:5]:
        print(f"  {cid} #{idx} when={when} | {t}")
    print()
    print(f"3. when 未設定: {len(no_when)}")
    for cid, idx, t in no_when[:5]:
        print(f"  {cid} #{idx} | {t}")
    print()
    print(f"4. 公式テキスト 多bracket / overlay 不足 candidate: {len(text_long_but_overlay_short)}")
    for x in text_long_but_overlay_short[:10]:
        print(f"  {x['card_id']} {x['name'][:18]} text_br={x['text_brackets']} overlay_br={x['overlay_brackets']}")
        print(f"    {x['official'][:100]}")
    print()
    print(f"5. cost 持ち で _text に 「ターン1回」 あるが once_per_turn 未指定: {len(missing_opt_flag)}")
    for cid, idx, when, t in missing_opt_flag[:10]:
        print(f"  {cid} #{idx} when={when} | {t}")
    print()
    print(f"6. counter EVENT で counter 値 + when:counter 両方: {len(counter_event_both)}")
    for x in counter_event_both[:10]:
        print(f"  {x['card_id']} {x['name'][:18]} counter={x['counter']} cost={x['cost']}")
    print()
    print("7. 公式 trigger names overlay カバレッジ:")
    for jp, (n_text, n_overlay, missing) in trigger_coverage.items():
        gap = n_text - n_overlay
        status = "✓" if gap == 0 else f"⚠ {gap} 件不足"
        print(f"  {jp:15s}: text={n_text:4d} / overlay={n_overlay:4d}  {status}")
        if missing[:3]:
            for cid in missing[:3]:
                print(f"    missing: {cid} {card_map[cid].get('name', '?')[:18]}")


if __name__ == "__main__":
    main()
