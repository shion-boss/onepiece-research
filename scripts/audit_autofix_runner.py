#!/usr/bin/env python3
"""Phase 4 auto-fix loop dispatcher (= 2026-05-28、 docs/AUTO_AUDIT_SYSTEM.md Layer 4)。

db/auto_issues/ の issue files を consume → rule_id 別 handler で 修正案 適用 → pytest gate
→ commit/PR。 risk_tier=low のみ auto-merge、 mid/high は dry-run + 報告のみ。

## 使い方

```bash
.venv/bin/python scripts/audit_issue_generator.py     # まず issues 生成
.venv/bin/python scripts/audit_autofix_runner.py --dry-run
.venv/bin/python scripts/audit_autofix_runner.py --risk low   # low のみ 実適用
.venv/bin/python scripts/audit_autofix_runner.py --risk all   # 全 risk (= 警告)
```

## handler 登録

新規 rule の auto-fix handler は HANDLERS dict に 登録:

```python
def fix_l5_leader_feature(issue: dict, overlay: dict) -> bool:
    cid = issue["card_id"]
    feature = issue["evidence"]["feature"]
    # ... overlay 修正 logic ...
    return True  # 適用 成功

HANDLERS = {"L5": fix_l5_leader_feature, ...}
```
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ISSUES_DIR = REPO_ROOT / "db" / "auto_issues"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
CARDS_PATH = REPO_ROOT / "db" / "cards.json"
PY = REPO_ROOT / ".venv" / "bin" / "python"

_CARDS_BY_ID: dict | None = None
def _get_card_text(cid: str) -> str:
    global _CARDS_BY_ID
    if _CARDS_BY_ID is None:
        cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
        _CARDS_BY_ID = {c["card_id"]: c for c in cards}
    c = _CARDS_BY_ID.get(cid)
    return (c.get("text", "") if c else "") or ""


# ============================================================
# handler 1: L1 (optional flag 追加)
# ============================================================
def fix_l1_optional(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L1: replace_ko / replace_leave entry に optional: true 追加。"""
    cid = issue["card_id"]
    entry_idx = issue["evidence"].get("entry_index")
    entry_when = issue["evidence"].get("entry_when")
    entries = overlay.get(cid)
    if not isinstance(entries, list) or entry_idx is None or entry_idx >= len(entries):
        return False, "entry 検出 失敗"
    target = entries[entry_idx]
    if not isinstance(target, dict) or target.get("when") != entry_when:
        return False, "entry when 不一致"
    if target.get("optional"):
        return False, "既に optional 済"
    target["optional"] = True
    return True, f"{cid}[{entry_idx}].optional = True"


# ============================================================
# handler 2: L5 (leader_feature 追加)
# ============================================================
def fix_l5_leader_feature(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L5: 該当 entry の if (or conditions) に leader_feature を 追加。

    完全 自動 fix は 困難 (= 複数 entry の どれ に 追加 するか 不明) なので、
    overlay 全体 に 1 件 entry あって if 持つ もの に 追加 する simple heuristic。
    """
    cid = issue["card_id"]
    feature = issue["evidence"].get("feature")
    entries = overlay.get(cid)
    if not isinstance(entries, list) or not feature:
        return False, "entries / feature 取得 失敗"
    # 単一 entry で if 持つ場合 のみ 自動 適用
    if len(entries) != 1:
        return False, f"複数 entry ({len(entries)}) で 自動 適用 不可"
    e = entries[0]
    if not isinstance(e, dict):
        return False, "entry not dict"
    if_block = e.get("if")
    if not isinstance(if_block, dict):
        e["if"] = {"leader_feature": feature}
        return True, f"{cid}[0].if.leader_feature = {feature}"
    if "leader_feature" in if_block:
        return False, "既に leader_feature 済"
    if_block["leader_feature"] = feature
    return True, f"{cid}[0].if.leader_feature = {feature}"


# ============================================================
# handler 3: L7 (target_cost_le 追加)
# ============================================================
def fix_l7_cost_le(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L7: target spec 文字列 に cost_le_N 接尾 追加 (or target_cost_le field 追加)。

    対応 case:
    - 単一 entry + 単一 target string spec + text に コスト数 1 つ
    - 複数 entry の case では _text 内 に コスト N 以下 を 含む entry を 選んで 適用

    厳密化 (= 2026-05-28):
    - text に 複数 コスト 制限 (= N≠M) で どれ に 付与 か 不明 → 単一 entry skip
    - cost_context (self/opp) vs primitive target side 不一致 で skip (= ST10-001 防止)
    """
    cid = issue["card_id"]
    n = issue["evidence"].get("n")
    entries = overlay.get(cid)
    if not isinstance(entries, list) or not n:
        return False, "entries / n 取得 失敗"
    # text を 取得 して 複数 コスト 制限 が ある なら skip
    text = _get_card_text(cid)
    cost_nums = re.findall(r"コスト\s*(\d+)\s*以下", text)
    if len(set(cost_nums)) > 1:
        return False, f"text に 複数 コスト 制限 ({set(cost_nums)}) → 手動 review"

    # opp / self context 識別: 「コスト N 以下」 の 直前 文 を 見て 自/他 を 判定
    # 「自分の」 が 直近 で あれば self、 「相手の」 で あれば opp
    cost_pat = re.search(r"コスト\s*(\d+)\s*以下\s*の\s*(キャラ|リーダー)", text)
    if cost_pat is not None:
        prefix = text[: cost_pat.start()]
        # 直前 30 文字 で 直近 mention を 比較
        recent = prefix[-30:]
        last_self = recent.rfind("自分の")
        last_opp = recent.rfind("相手の")
        if last_self > last_opp and last_self >= 0:
            cost_context = "self"
        elif last_opp >= 0:
            cost_context = "opp"
        else:
            cost_context = "unknown"
    else:
        cost_context = "unknown"

    # 複数 entry の case: _text 内 に 「コスト N 以下」 を 含む entry を 選ぶ
    if len(entries) > 1:
        candidate_idx = None
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            etext = e.get("_text", "") or ""
            if f"コスト{n}以下" in etext or f"コスト {n} 以下" in etext:
                candidate_idx = i
                break
        if candidate_idx is None:
            return False, f"複数 entry で コスト{n}以下 を 持つ entry が ない"
        e = entries[candidate_idx]
    else:
        e = entries[0]
    if not isinstance(e, dict):
        return False, "entry not dict"
    do = e.get("do", [])
    if not isinstance(do, list) or len(do) != 1:
        return False, "do 1 件 のみ 自動 適用"
    prim = do[0]
    if not isinstance(prim, dict) or len(prim) != 1:
        return False, "primitive 1 件 のみ"
    pk, pv = next(iter(prim.items()))
    # 既 cost 制限 込み か 検査 (= 旧 le_Ncost 形 を 含む)
    def _has_cost_token(s: str) -> bool:
        return "cost_le_" in s or "cost_ge_" in s or bool(re.search(r"_(le|ge)_\d+cost", s))

    # spec の self/opp 識別: target string に "self" / "opponent" 含む か
    def _spec_target_side(s: str) -> str:
        if "opponent" in s or "opp_" in s:
            return "opp"
        if "self_" in s or s == "self":
            return "self"
        return "unknown"

    # string target spec の case
    if isinstance(pv, str) and "character" in pv and not _has_cost_token(pv):
        spec_side = _spec_target_side(pv)
        if cost_context != "unknown" and spec_side != "unknown" and cost_context != spec_side:
            return False, (f"context mismatch: text コスト{n} は {cost_context} 側 だが "
                          f"primitive target は {spec_side} 側")
        new_spec = f"{pv}_cost_le_{n}"
        prim[pk] = new_spec
        return True, f"{cid}[0].{pk}: {pv} → {new_spec}"
    if isinstance(pv, dict) and "target" in pv and isinstance(pv["target"], str):
        t = pv["target"]
        if not _has_cost_token(t):
            spec_side = _spec_target_side(t)
            if cost_context != "unknown" and spec_side != "unknown" and cost_context != spec_side:
                return False, (f"context mismatch: text コスト{n} は {cost_context} 側 だが "
                              f"primitive target は {spec_side} 側")
            new_t = f"{t}_cost_le_{n}" if "character" in t else t
            if new_t != t:
                pv["target"] = new_t
                return True, f"{cid}[0].{pk}.target: {t} → {new_t}"
    return False, "対応 target spec 形 が 検出 不可"


# ============================================================
# handler 4b: L8 missing primitive 追加 (= attack 不可 / コスト+N / power-N)
# ============================================================
def fix_l8_missing_primitive(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L8 残 cases で 「次相手 end まで X」 の X primitive 自体 が overlay に なく、
    text の trigger 部分 と 一致 する 既存 entry に 追加 する。

    現在 対応 pattern:
    - 「相手の(X)キャラ N 枚 まで は、 次の相手のターン終了時まで、 アタックできない」
      → set_cannot_attack {target: ..., duration: next_opp_turn_end} を 追加
    """
    cid = issue["card_id"]
    expected = issue["evidence"].get("expected")
    if expected != "next_opp_turn_end":
        return False, "expected が next_opp_turn_end でない"
    entries = overlay.get(cid)
    if not isinstance(entries, list) or len(entries) == 0:
        return False, "entries なし"
    text = _get_card_text(cid)
    # 「アタックできない」 の 該当 句 (= 直前 30 文字 を ターゲット 推定 に 使う)
    m_dis = re.search(r"次の相手のターン終了時まで、?\s*アタックできない", text)
    if not m_dis:
        return False, "attack-disable pattern なし"
    # 直前 文 (= 「相手の…キャラ N 枚 まで は、 次相手 end まで attack できない」 の 「…」 部分)
    before = text[: m_dis.start()]
    # 末尾 の 「は、」 / 「、」 を 除去 (= 次相手end の 前置詞 を 取り 除いて 本来 の 句 を 取る)
    before = re.sub(r"(は、|、)$", "", before)
    # 「、」 or 「：」 or 「。」 で 区切られた 直前 句 のみ
    last_delim = max(before.rfind("、"), before.rfind("："), before.rfind("。"))
    target_clause = before[last_delim+1:] if last_delim >= 0 else before
    # 単一 entry を 主 trigger と 仮定 (= 複数 entry の card は skip)
    if len(entries) > 2:
        return False, f"複数 entry ({len(entries)}) で 自動 適用 不可"
    # 既 set_cannot_attack あれば skip
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if isinstance(prim, dict) and "set_cannot_attack" in prim:
                return False, "既に set_cannot_attack あり"
    # target spec を target_clause (= 直前 句 限定) から 推定
    target = "one_opponent_character_any"
    m_cost = re.search(r"コスト\s*(\d+)\s*以下\s*のキャラ", target_clause)
    m_power = re.search(r"パワー\s*(\d+)\s*以下\s*のキャラ", target_clause)
    is_leader = "リーダー" in target_clause and "キャラ" not in target_clause
    if is_leader:
        target = "one_opponent_leader"
    elif m_cost:
        target = f"one_opponent_character_cost_le_{m_cost.group(1)}"
    elif m_power:
        target = f"one_opponent_character_power_le_{m_power.group(1)}"
    # 数 上限 (= 「N 枚 まで」、 target_clause 内 のみ)
    m_count = re.search(r"キャラ\s*(\d+)\s*枚まで", target_clause)
    if not m_count:
        m_count = re.search(r"リーダー\s*(\d+)\s*枚まで", target_clause)
    # 主 trigger entry を 選択 (= 最初 の on_play / activate_main / counter)
    main_entry = None
    for e in entries:
        if isinstance(e, dict) and e.get("when") in ("on_play", "activate_main", "main", "counter"):
            main_entry = e
            break
    if main_entry is None:
        main_entry = entries[0]
    # set_cannot_attack primitive を 構築
    new_prim_spec = {"target": target, "duration": "next_opp_turn_end"}
    if m_count and int(m_count.group(1)) >= 2:
        new_prim_spec["count"] = int(m_count.group(1))
    new_prim = {"set_cannot_attack": new_prim_spec}
    do_list = main_entry.get("do")
    if not isinstance(do_list, list):
        main_entry["do"] = [new_prim]
    else:
        do_list.append(new_prim)
    return True, f"{cid} に set_cannot_attack({target}, next_opp_turn_end) 追加"


def fix_l8_missing_power_pump(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L8: 「次相手 end まで パワー +N」 / 「-N」 missing primitive 追加。

    text pattern: 「(対象)、 次の相手のターン終了時まで、 パワー[+-]N」
    overlay に power_pump primitive ない場合 main entry に 追加。
    """
    cid = issue["card_id"]
    expected = issue["evidence"].get("expected")
    if expected != "next_opp_turn_end":
        return False, "next_opp_turn_end 以外"
    text = _get_card_text(cid)
    m_pw = re.search(r"次の相手のターン終了時まで、?\s*パワー([+-])(\d+)", text)
    if not m_pw:
        return False, "power +/- pattern なし"
    sign = m_pw.group(1)
    amount_abs = int(m_pw.group(2))
    amount = amount_abs if sign == "+" else -amount_abs

    entries = overlay.get(cid)
    if not isinstance(entries, list) or len(entries) == 0 or len(entries) > 2:
        return False, f"entry 数 unsupported ({len(entries) if isinstance(entries,list) else '?'})"
    # 既 power_pump duration next_opp_turn_end あれば skip
    for e in entries:
        if not isinstance(e, dict):
            continue
        for prim in e.get("do", []) or []:
            if isinstance(prim, dict) and "power_pump" in prim:
                pv = prim.get("power_pump", {})
                if isinstance(pv, dict) and pv.get("duration") == "next_opp_turn_end":
                    return False, "既 power_pump next_opp_turn_end あり"
    # target 推定 (= power +/- の 直前 句)
    before = text[: m_pw.start()]
    before = re.sub(r"(は、|、)$", "", before)
    last_delim = max(before.rfind("、"), before.rfind("："), before.rfind("。"))
    target_clause = before[last_delim+1:] if last_delim >= 0 else before
    if "このキャラ" in target_clause or "このリーダー" in target_clause:
        target = "self"
    elif "自分のキャラ" in target_clause:
        target = "one_self_character_any"
    elif "自分のリーダー" in target_clause:
        target = "self_leader"
    elif "相手のキャラ" in target_clause:
        target = "one_opponent_character_any"
    elif "相手のリーダー" in target_clause:
        target = "one_opponent_leader"
    else:
        return False, f"target 推定 不可: ...{target_clause[-40:]}"
    # 主 trigger entry
    main_entry = None
    for e in entries:
        if isinstance(e, dict) and e.get("when") in ("on_play", "activate_main", "main", "counter", "on_attack"):
            main_entry = e
            break
    if main_entry is None:
        main_entry = entries[0]
    new_prim = {"power_pump": {"target": target, "amount": amount, "duration": "next_opp_turn_end"}}
    do_list = main_entry.get("do")
    if not isinstance(do_list, list):
        main_entry["do"] = [new_prim]
    else:
        do_list.append(new_prim)
    return True, f"{cid} に power_pump({target}, {amount:+d}, next_opp_turn_end) 追加"


# ============================================================
# handler 4: L8 (next_*_turn_end duration 変更)
# ============================================================
def fix_l8_duration(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L8: 既 power_pump primitive の duration を turn → next_*_turn_end に 変更。

    安全 適用 条件:
    - 単一 entry
    - 単一 do primitive で `power_pump` を 含む
    - text に 「次の(相手の)ターン終了時まで」 が 一度 だけ あり、 「このターン中」 が 無い
      (= duration 候補 が 一意 に 決まる)
    """
    cid = issue["card_id"]
    expected = issue["evidence"].get("expected")
    if expected not in ("next_opp_turn_end", "next_turn_end"):
        return False, "expected duration が auto-fix 対象 外"
    entries = overlay.get(cid)
    if not isinstance(entries, list) or len(entries) != 1:
        return False, f"複数 entry ({len(entries) if isinstance(entries,list) else '?'})"
    e = entries[0]
    if not isinstance(e, dict):
        return False, "entry not dict"
    text = _get_card_text(cid)
    # text に 「このターン中」 と 両方 ある なら 曖昧 → skip
    has_this_turn = "このターン中" in text
    if has_this_turn:
        return False, "text に 「このターン中」 と 「次の…ターン終了時」 両方 = 曖昧"
    do = e.get("do", [])
    changed_any = False
    for prim in do if isinstance(do, list) else []:
        if not isinstance(prim, dict):
            continue
        for k, v in list(prim.items()):
            if k == "power_pump" and isinstance(v, dict):
                cur = v.get("duration")
                if cur == "turn":
                    v["duration"] = expected
                    changed_any = True
            elif k == "set_base_power_timed" and isinstance(v, dict):
                cur = v.get("duration")
                if cur == "turn":
                    v["duration"] = expected
                    changed_any = True
    if changed_any:
        return True, f"{cid}[0] power_pump.duration → {expected}"
    return False, "対応 primitive (power_pump duration=turn) なし"


# L8 handler chain: 3 つ の handler を 順次 試行
def fix_l8_combined(issue: dict, overlay: dict) -> tuple[bool, str]:
    for handler, label in [
        (fix_l8_duration, "duration"),
        (fix_l8_missing_primitive, "missing_attack_disable"),
        (fix_l8_missing_power_pump, "missing_power_pump"),
    ]:
        ok, msg = handler(issue, overlay)
        if ok:
            return ok, msg
    return False, "全 L8 handler が skip"


def fix_l4_to_multi(issue: dict, overlay: dict) -> tuple[bool, str]:
    """L4: 「chara N 枚 まで」 で overlay の単一 target primitive を ko_multi 等 へ 変換。

    対応 primitive: ko / return_to_hand / return_to_deck_bottom / rest
    → それぞれ の _multi 版 に N 個 同 spec を 並べる。

    安全 適用 条件:
    - text に 「(コスト/パワー) N 以下のキャラ M 枚 まで」 (M ≥ 2) が ある
    - overlay 単一 entry + 単一 primitive (= 上記 4 種 の どれか)
    - primitive value が string spec (= dict spec は skip)
    """
    cid = issue["card_id"]
    text = _get_card_text(cid)
    # 「キャラ M 枚 まで」 抽出 (M >= 2)
    m_count = re.search(r"キャラ(?:[^、。]{0,5})?([2-9]|10|11|12)\s*(枚|体)まで", text)
    if not m_count:
        return False, "「キャラ N 枚 まで」 pattern なし"
    count = int(m_count.group(1))
    entries = overlay.get(cid)
    if not isinstance(entries, list) or len(entries) != 1:
        return False, f"単一 entry 限定 (現 {len(entries) if isinstance(entries,list) else '?'})"
    e = entries[0]
    if not isinstance(e, dict):
        return False, "entry not dict"
    do = e.get("do", [])
    if not isinstance(do, list) or len(do) != 1:
        return False, "do 1 件 のみ 対応"
    prim = do[0]
    if not isinstance(prim, dict) or len(prim) != 1:
        return False, "primitive 1 件 のみ"
    pk, pv = next(iter(prim.items()))
    base_to_multi = {
        "ko": "ko_multi",
        "return_to_hand": "return_to_hand_multi",
        "return_to_deck_bottom": "return_to_deck_bottom_multi",
    }
    if pk not in base_to_multi:
        return False, f"primitive {pk} は multi 変換 非対応"
    if not isinstance(pv, str):
        return False, "string target spec のみ 対応"
    new_pk = base_to_multi[pk]
    do[0] = {new_pk: [pv] * count}
    return True, f"{cid}[0]: {pk} → {new_pk} × {count}"


HANDLERS = {
    "L1": fix_l1_optional,
    "L4": fix_l4_to_multi,
    "L5": fix_l5_leader_feature,
    "L7": fix_l7_cost_le,
    "L8": fix_l8_combined,
}


def load_issues() -> list[dict]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(ISSUES_DIR.glob("*.json"))
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--risk", choices=["low", "mid", "high", "all"], default="low")
    ap.add_argument("--rule", default=None, help="特定 rule_id のみ")
    ap.add_argument("--no-pytest", action="store_true", help="pytest gate skip")
    args = ap.parse_args()

    if not ISSUES_DIR.exists():
        print(f"ERROR: {ISSUES_DIR} not found. Run audit_issue_generator.py first.",
              file=sys.stderr)
        sys.exit(1)

    issues = load_issues()
    print(f"loaded {len(issues)} issues from {ISSUES_DIR.relative_to(REPO_ROOT)}")

    # filter
    if args.risk != "all":
        issues = [i for i in issues if i.get("risk_tier") == args.risk]
    if args.rule:
        issues = [i for i in issues if i.get("rule_id") == args.rule]
    print(f"after filter: {len(issues)} issues")

    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    applied = 0
    skipped = 0
    failed = []
    no_handler = []

    for issue in issues:
        rule = issue.get("rule_id")
        handler = HANDLERS.get(rule)
        if handler is None:
            no_handler.append(issue)
            continue
        ok, msg = handler(issue, overlay)
        if ok:
            applied += 1
            print(f"  ✓ {msg}")
        else:
            skipped += 1
            failed.append((issue, msg))

    print()
    print(f"applied      : {applied}")
    print(f"skipped      : {skipped}")
    print(f"no handler   : {len(no_handler)} (rules: "
          f"{sorted(set(i['rule_id'] for i in no_handler))})")

    if args.dry_run:
        print("\n[dry-run] 変更は書き戻さず")
        return

    if applied == 0:
        print("nothing to apply")
        return

    # 書き戻し
    OVERLAY_PATH.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {OVERLAY_PATH.relative_to(REPO_ROOT)}")

    # pytest gate
    if not args.no_pytest:
        print("\nrunning pytest gate ...")
        r = subprocess.run(
            [str(PY), "-m", "pytest",
             "tests/test_audit_invariants.py",
             "tests/test_human_play_bug_fixes.py",
             "tests/test_effects.py",
             "-q", "--timeout=30"],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
        print(r.stdout[-2000:])
        if r.returncode != 0:
            print("\n✗ pytest 失敗 → 変更 を rollback")
            subprocess.run(["git", "checkout", "--", str(OVERLAY_PATH)],
                          cwd=str(REPO_ROOT))
            sys.exit(1)
        print("\n✓ pytest pass")


if __name__ == "__main__":
    main()
