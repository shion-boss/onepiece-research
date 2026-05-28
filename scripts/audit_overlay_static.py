#!/usr/bin/env python3
"""Phase 1 静的 lint (= 2026-05-28 着手、 ohtsuki さん 「徹底的に改善」 要件)。

db/cards.json (= 公式 text) と db/card_effects.json (= engine overlay) の **構造的 不一致**
を 検出 する 純 静的 audit。 runtime 試合 不要。 commit 毎 に CI で 走らせる 軽量 lint。

検出 pattern (= docs/AUTO_AUDIT_SYSTEM.md Layer 1 表):
- L1: optional 漏れ      もよい / ことができる → overlay の 関連 entry に optional: true
- L2: once_per_turn 漏れ ターン1回 → overlay entry に once_per_turn or cost.once_per_turn
- L3: 自他 反転         相手の X → overlay target が opp_* 系
                        自分の X → overlay target が self_* 系
- L4: 上限 漏れ          までを N → overlay に count: N
- L5: leader_feature   自分のリーダーが特徴《X》を持つ → if.leader_feature: X
- L6: trigger 漏れ       【XX時】 → overlay when (on_xx 系)
- L7: cost 範囲         コスト N 以下 → target_cost_le: N
- L8: duration         このターン中 / 次相手 end まで → duration spec

出力: db/static_audit_report.json + .md (= 上位 100 件 抜粋)

実行:
  .venv/bin/python scripts/audit_overlay_static.py
  .venv/bin/python scripts/audit_overlay_static.py --severity 3  # sev>=3 のみ
  .venv/bin/python scripts/audit_overlay_static.py --card OP14-061  # 単体 確認
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = REPO_ROOT / "db" / "cards.json"
OVERLAY_PATH = REPO_ROOT / "db" / "card_effects.json"
ACK_PATH = REPO_ROOT / "db" / "static_audit_acknowledged.json"
OUT_JSON = REPO_ROOT / "db" / "static_audit_report.json"
OUT_MD = REPO_ROOT / "db" / "static_audit_report.md"


# 検出 patterns (= 正規表現 + 期待 overlay 形)
OPTIONAL_TOKENS = ("もよい", "ことができる", "ことができます", "してもよい")
ONCE_TOKENS = ("ターン1回", "ターンに1回", "ターン１回")
# TRIGGER_MAP: text の tag → 期待 overlay when 値 (1 件 以上 マッチ で OK)。
# 値 が tuple なら どれか 1 つ あれば OK (= 同 意味 の 別表現)。
# 注意: engine の 実装 when 名 と 一致 (= main vs activate_main 等 で 大量 false positive 防止)。
TRIGGER_MAP = {
    "【登場時】": ("on_play",),
    "【アタック時】": ("on_attack",),
    "【起動メイン】": ("activate_main", "main"),
    "【KO時】": ("on_ko",),
    "【ターン終了時】": ("on_turn_end", "end_of_turn"),
    "【ブロック時】": ("on_block",),
    "【相手のアタック時】": ("opp_attack", "on_opp_attack"),
    "【トリガー】": ("trigger",),
    "【カウンター】": ("counter",),
}
REPLACE_WHEN = ("replace_ko", "replace_leave", "replace_rest")


def _load_cards() -> dict:
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    return {c["card_id"]: c for c in cards}


def _load_overlay() -> dict:
    return json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))


def _load_ack() -> set[str]:
    """static_audit_acknowledged.json に intrinsic 除外 listed の (card_id, rule_id) set。

    format:
    {
      "_comment": "...",
      "OP10-118": ["L2"],   // この card は L2 を 除外
      ...
    }
    """
    if not ACK_PATH.exists():
        return set()
    try:
        ack = json.loads(ACK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    if not isinstance(ack, dict):
        return out
    for cid, rules in ack.items():
        if cid.startswith("_"):
            continue
        if not isinstance(rules, list):
            continue
        for rule in rules:
            out.add(f"{cid}:{rule}")
    return out


def _entries_have_field(entries: list, field: str) -> bool:
    """overlay entries の どれか が field を 持つ か。"""
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        if e.get(field):
            return True
        # cost に once_per_turn が 入る pattern も 拾う
        if field == "once_per_turn":
            cost = e.get("cost")
            if isinstance(cost, dict) and cost.get("once_per_turn"):
                return True
            if isinstance(cost, list):
                for c in cost:
                    if isinstance(c, dict) and c.get("once_per_turn"):
                        return True
    return False


def _entries_have_when(entries: list, when_set: tuple) -> bool:
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("when") in when_set:
            return True
    return False


def _check_optional(cid: str, text: str, entries: list) -> list[dict]:
    """L1: 「もよい/ことができる」 含む text で replace_ko entry に optional 無し。"""
    issues = []
    if not any(t in text for t in OPTIONAL_TOKENS):
        return issues
    # replace_ko / replace_leave entry が ある なら optional: true 必須
    for i, e in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(e, dict):
            continue
        if e.get("when") not in REPLACE_WHEN:
            continue
        if not e.get("optional"):
            issues.append({
                "rule_id": "L1",
                "card_id": cid,
                "severity": 4,
                "category": "optional_missing",
                "message": f"text に 「{[t for t in OPTIONAL_TOKENS if t in text][0]}」 "
                          f"が 含まれる が {e.get('when')} entry [{i}] に optional: true なし",
                "evidence": {
                    "text_excerpt": _excerpt_around(text, OPTIONAL_TOKENS),
                    "entry_when": e.get("when"),
                    "entry_index": i,
                },
                "suggested_fix": {
                    "path": f"db/card_effects.json:{cid}[{i}]",
                    "patch": "optional: true を 追加",
                },
            })
    return issues


def _check_once_per_turn(cid: str, text: str, entries: list) -> list[dict]:
    """L2: 「ターン1回」 含む text で entry に once_per_turn 無し。"""
    issues = []
    if not any(t in text for t in ONCE_TOKENS):
        return issues
    if not entries:
        return issues
    # entry が 複数 ある と「どれが ターン1回 か」 判断 困難。
    # heuristic: 少なくとも 1 つ once_per_turn を 持つ なら OK。
    if _entries_have_field(entries, "once_per_turn"):
        return issues
    # cost.once_per_turn も 受容
    has = False
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        cost = e.get("cost")
        if isinstance(cost, dict) and cost.get("once_per_turn"):
            has = True
            break
        if isinstance(cost, list):
            for c in cost:
                if isinstance(c, dict) and c.get("once_per_turn"):
                    has = True
                    break
            if has:
                break
    if not has:
        issues.append({
            "rule_id": "L2",
            "card_id": cid,
            "severity": 4,
            "category": "once_per_turn_missing",
            "message": "text に 「ターン1回」 が 含まれる が overlay entries の どれも "
                      "once_per_turn を 持たない",
            "evidence": {
                "text_excerpt": _excerpt_around(text, ONCE_TOKENS),
                "entry_count": len(entries) if isinstance(entries, list) else 0,
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": "該当 entry に once_per_turn: true (もしくは cost.once_per_turn: true) を 追加",
            },
        })
    return issues


def _check_trigger_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L6: 【XX時】 含む text で 該当 when の entry が 1 件 も 無い。

    expected_whens は tuple = どれか 1 つ あれば OK (= main/activate_main 等 の 同義語 吸収)。
    """
    issues = []
    if not entries:
        return issues  # 効果 なし card は スキップ
    entry_whens = {e.get("when") for e in entries if isinstance(e, dict)}
    for tag, expected_whens in TRIGGER_MAP.items():
        if tag not in text:
            continue
        if any(w in entry_whens for w in expected_whens):
            continue
        issues.append({
            "rule_id": "L6",
            "card_id": cid,
            "severity": 4,
            "category": "trigger_missing",
            "message": f"text に 「{tag}」 が 含まれる が overlay に when ∈ "
                      f"{list(expected_whens)} entry なし",
            "evidence": {
                "tag": tag,
                "expected_whens": list(expected_whens),
                "actual_whens": sorted(w for w in entry_whens if w),
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": f"when: {expected_whens[0]} の entry を 追加",
            },
        })
    return issues


def _check_leader_feature_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L5: 「自分のリーダーが特徴《X》を持つ(なら|場合)」 → 任意の場所 (if / conditions[] /
    choice_effect.options[].if / nested) で leader_feature: X が 宣言 されている。
    """
    issues = []
    if not entries:
        return issues
    m = re.search(r"自分のリーダーが特徴《([^》]+)》を持つ(なら|場合)", text)
    if not m:
        return issues
    feature = m.group(1)

    # 再帰 全 走査 で leader_feature: feature を 探す
    has_feature = False
    def _walk(node):
        nonlocal has_feature
        if has_feature:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "leader_feature":
                    if v == feature or (isinstance(v, list) and feature in v):
                        has_feature = True
                        return
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
    _walk(entries)
    if not has_feature:
        issues.append({
            "rule_id": "L5",
            "card_id": cid,
            "severity": 3,
            "category": "leader_feature_missing",
            "message": f"text の 「自分のリーダーが特徴《{feature}》を持つ なら/場合」 "
                      f"に 対応 する if.leader_feature が overlay に なし",
            "evidence": {
                "feature": feature,
                "text_excerpt": _excerpt_around(text, ("特徴《" + feature + "》",)),
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": f"該当 entry の if に leader_feature: '{feature}' を 追加",
            },
        })
    return issues


def _excerpt_around(text: str, tokens: tuple, span: int = 40) -> str:
    for t in tokens:
        idx = text.find(t)
        if idx >= 0:
            start = max(0, idx - span)
            end = min(len(text), idx + len(t) + span)
            return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
    return text[:80]


def _gather_target_specs(entries: list) -> list[str]:
    """全 entry の target 風 string spec を 1 つ の list に 集める (= 再帰 走査)。

    target / target_spec / 任意 nested dict["target"] を 拾う。
    """
    found: list[str] = []
    def _walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("target", "target_spec") and isinstance(v, str):
                    found.append(v)
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
    _walk(entries)
    return found


def _check_count_limit_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L4: 「N枚まで」 chara/leader 文脈 で entry の count 制限 が 無い。

    ドン / カード(手札) / ライフ は 別 文脈 (= ドン用 amount プリミティブ持ち、
    手札 用 はカード手札枚数、 ライフ用 はライフ枚数) なので 除外。 chara/リーダー 文脈
    のみ flag。 N≥2 限定 (N=1 は target spec の `one_*` で 自然 制限)。
    """
    issues = []
    if not entries:
        return issues
    # chara/leader 文脈 + N >= 2 のみ
    # "chara/リーダー/キャラ X 枚 まで" 抽出
    pattern = r"(キャラ|リーダー)([^、。]{0,8}?)([2-9]|10|11|12)\s*(枚|体)まで"
    matches = list(re.finditer(pattern, text))
    if not matches:
        return issues
    # entries 内 で count or limit が 宣言 されている か。
    # 認識 形式:
    #   - field: count/limit/max/max_count (int >= 2)
    #   - primitive: ko_multi / return_to_hand_multi / return_to_deck_bottom_multi の
    #     list 要素数 (= N枚 targets を 表現)
    has_count_decl = False
    multi_primitives = {"ko_multi", "return_to_hand_multi", "return_to_deck_bottom_multi"}
    def _walk_count(node):
        nonlocal has_count_decl
        if has_count_decl:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("count", "limit", "max", "max_count") and isinstance(v, int) and v >= 2:
                    has_count_decl = True
                    return
                # multi primitive: value list の 長さ >= 2 で 「N 枚 まで」 を 表現
                if k in multi_primitives and isinstance(v, list) and len(v) >= 2:
                    has_count_decl = True
                    return
                _walk_count(v)
        elif isinstance(node, list):
            for item in node:
                _walk_count(item)
    _walk_count(entries)
    if has_count_decl:
        return issues
    matched_str = matches[0].group(0)
    n_str = matches[0].group(3)
    issues.append({
        "rule_id": "L4",
        "card_id": cid,
        "severity": 3,
        "category": "count_limit_missing",
        "message": f"text に chara/leader 文脈 で 「{matched_str}」 が 含まれる が "
                  f"overlay に count: {n_str} 制限 なし",
        "evidence": {
            "text_excerpt": _excerpt_around(text, (matched_str,)),
            "matched": matched_str,
        },
        "suggested_fix": {
            "path": f"db/card_effects.json:{cid}",
            "patch": f"該当 effect に count: {n_str} (or limit: {n_str}) を 追加",
        },
    })
    return issues


def _check_cost_le_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L7: 「コスト N 以下のキャラ/リーダー」 含む text で overlay target に
    target_cost_le: N が 無い。

    「コスト N 以下 の カード」 (= 手札用) や 「コスト N 以下 の ドン」 は 対象 外。
    """
    issues = []
    if not entries:
        return issues
    # chara/leader 文脈 限定
    m = re.search(r"コスト\s*(\d+)\s*以下\s*の(キャラ|リーダー)", text)
    if not m:
        return issues
    n = int(m.group(1))
    # spec 内 で target_cost_le が 宣言 されている か (= cost_le も 受容)
    # 認識 する 形式:
    #   - field: target_cost_le / cost_le / target_cost_ge / cost_ge (int)
    #   - string spec 内: "cost_le_N" / "cost_ge_N" 接尾
    #   - string spec 内 旧形式: "le_Ncost" / "ge_Ncost" (= ST18-001 等)
    found = False
    def _walk_cost(node):
        nonlocal found
        if found:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("target_cost_le", "cost_le", "target_cost_ge", "cost_ge") and isinstance(v, int):
                    found = True
                    return
                _walk_cost(v)
        elif isinstance(node, list):
            for item in node:
                _walk_cost(item)
        elif isinstance(node, str):
            # target spec 文字列内 の "cost_le_N" / "cost_ge_N" or 旧 "le_Ncost" / "ge_Ncost" も 受容
            if ("cost_le_" in node or "cost_ge_" in node
                or re.search(r"_(le|ge)_\d+cost", node)):
                found = True
                return
    _walk_cost(entries)
    if found:
        return issues
    issues.append({
        "rule_id": "L7",
        "card_id": cid,
        "severity": 4,
        "category": "cost_le_missing",
        "message": f"text に 「コスト {n} 以下」 が 含まれる が overlay に "
                  f"target_cost_le / cost_le_N spec なし",
        "evidence": {
            "text_excerpt": _excerpt_around(text, (m.group(0),)),
            "n": n,
        },
        "suggested_fix": {
            "path": f"db/card_effects.json:{cid}",
            "patch": f"target に target_cost_le: {n} を 追加 (or target_spec 文字列 を cost_le_{n} 系 へ)",
        },
    })
    return issues


def _check_duration_missing(cid: str, text: str, entries: list) -> list[dict]:
    """L8: 「次の*ターン終了時まで」 系 の 非default duration が 宣言されているか。

    「このターン中」 は engine の 多く の primitive で default なので除外 (= false-positive 多)。
    「次のターン」 「次の相手のターン」 終了時まで は 明示宣言 必須 = flag 価値 高。
    """
    issues = []
    if not entries:
        return issues
    duration_tokens = {
        "次の相手のターン終了時まで": "next_opp_turn_end",
        "次のターン終了時まで": "next_turn_end",
        "次のターンの終了時まで": "next_turn_end",
        "次の相手のターンの終了時まで": "next_opp_turn_end",
        "次のターン中": "next_turn",
    }
    matched_tokens = [(t, exp) for t, exp in duration_tokens.items() if t in text]
    if not matched_tokens:
        return issues
    # entries 内 で duration / next_*_turn_end フラグ を 探す
    found_any = False
    def _walk_dur(node):
        nonlocal found_any
        if found_any:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "duration" and isinstance(v, str) and "next" in v:
                    found_any = True
                    return
                # 静的 / next_opp_turn / static_until_turn 系 も 受容
                if k in (
                    "next_opp_turn_end", "next_turn_end",
                    "next_refresh_kept_rested_don",
                    "stay_rested_next_refresh", "set_base_power_timed",
                    "set_base_cost_timed", "set_ko_immune_timed",
                    "set_cannot_rest",  # set_cannot_rest 自体が next opp end 系
                    "keep_opp_rested_don_next_refresh",
                ):
                    found_any = True
                    return
                _walk_dur(v)
        elif isinstance(node, list):
            for item in node:
                _walk_dur(item)
    _walk_dur(entries)
    if found_any:
        return issues
    issues.append({
        "rule_id": "L8",
        "card_id": cid,
        "severity": 4,
        "category": "duration_next_turn_missing",
        "message": f"text に 「{matched_tokens[0][0]}」 (= 次ターン 跨ぎ) が 含まれる が "
                  f"overlay に 関連 next-turn duration 宣言 なし",
        "evidence": {
            "text_excerpt": _excerpt_around(text, (matched_tokens[0][0],)),
            "expected": matched_tokens[0][1],
        },
        "suggested_fix": {
            "path": f"db/card_effects.json:{cid}",
            "patch": f"該当 primitive に duration: '{matched_tokens[0][1]}' を 追加",
        },
    })
    return issues


def _check_self_opp_reversal(cid: str, text: str, entries: list) -> list[dict]:
    """L3: 「相手の X」 含む text で target spec が self_* (= 自他反転)。

    実装 注意: text が 「相手のキャラ」 「相手のリーダー」 と 言ってる の に target が
    self_leader / self_chara 系 だったら 反転 = bug 候補。
    逆 (= 「自分の」 が opp_* に なる) も 同様。

    ただし 「自分のリーダーが特徴《X》を持つ場合、 相手のキャラを KO」 のような
    複合 文 は 後段 で target spec が opp_* / self 両方 含む の が 正解。 ここ は
    「mention あり vs 該当 target spec ある か」 の 緩い 検出 に 留める。
    """
    issues = []
    if not entries:
        return issues
    mention_opp = "相手の" in text and ("相手のキャラ" in text or "相手のリーダー" in text or "相手のドン" in text)
    mention_self = "自分の" in text and ("自分のキャラ" in text or "自分のリーダー" in text or "自分のドン" in text)
    target_specs = _gather_target_specs(entries)
    if not target_specs:
        return issues
    text_joined = " ".join(target_specs)
    has_opp_spec = "opp" in text_joined or "opponent" in text_joined
    has_self_spec = "self" in text_joined

    # 「相手のキャラ」 mention あり + target spec に opp_* が 全く ない → 怪しい
    if mention_opp and not has_opp_spec and has_self_spec:
        issues.append({
            "rule_id": "L3",
            "card_id": cid,
            "severity": 3,
            "category": "self_opp_reversal_suspect",
            "message": "text に 「相手のキャラ/リーダー/ドン」 mention が ある が target spec "
                      "に opp_* 系 が 1 つ も 無い (= 自他反転 疑い)",
            "evidence": {
                "target_specs": target_specs[:8],
            },
            "suggested_fix": {
                "path": f"db/card_effects.json:{cid}",
                "patch": "該当 target を opp_* spec へ 変更 (要 手動 確認)",
            },
        })
    return issues


def audit_card(cid: str, card: dict, overlay: dict) -> list[dict]:
    text = card.get("text", "") or ""
    entries = overlay.get(cid, [])
    issues = []
    issues += _check_optional(cid, text, entries)
    issues += _check_once_per_turn(cid, text, entries)
    issues += _check_trigger_missing(cid, text, entries)
    issues += _check_leader_feature_missing(cid, text, entries)
    issues += _check_count_limit_missing(cid, text, entries)
    issues += _check_cost_le_missing(cid, text, entries)
    issues += _check_duration_missing(cid, text, entries)
    issues += _check_self_opp_reversal(cid, text, entries)
    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--severity", type=int, default=0,
                    help="この severity 以上 の issue のみ 出力")
    ap.add_argument("--card", default=None,
                    help="単体 card_id audit (= debug 用)")
    ap.add_argument("--top", type=int, default=100,
                    help=".md report の 上位 N 件 (default 100)")
    args = ap.parse_args()

    cards = _load_cards()
    overlay = _load_overlay()
    ack = _load_ack()

    all_issues = []
    if args.card:
        target_cids = [args.card]
    else:
        target_cids = sorted(cards.keys())

    for cid in target_cids:
        if cid not in cards:
            print(f"WARN: {cid} not in cards.json", file=sys.stderr)
            continue
        issues = audit_card(cid, cards[cid], overlay)
        for issue in issues:
            key = f"{issue['card_id']}:{issue['rule_id']}"
            if key in ack:
                issue["acknowledged"] = True
                continue
            if issue["severity"] < args.severity:
                continue
            all_issues.append(issue)

    # 集計
    by_rule = Counter(i["rule_id"] for i in all_issues)
    by_cat = Counter(i["category"] for i in all_issues)
    by_sev = Counter(i["severity"] for i in all_issues)

    report = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "cards_scanned": len(target_cids),
        "issues_total": len(all_issues),
        "by_rule": dict(by_rule),
        "by_category": dict(by_cat),
        "by_severity": dict(by_sev),
        "issues": all_issues,
    }
    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # md report
    lines = [
        "# Static Audit Report (Layer 1)",
        "",
        f"generated: {report['generated_at']}  ",
        f"cards scanned: {report['cards_scanned']}  ",
        f"issues total: {report['issues_total']}  ",
        "",
        "## by rule",
        "",
    ]
    for rule, count in sorted(by_rule.items()):
        lines.append(f"- `{rule}`: {count}")
    lines += ["", "## by category", ""]
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"- `{cat}`: {count}")
    lines += ["", "## by severity", ""]
    for sev in sorted(by_sev.keys(), reverse=True):
        lines.append(f"- sev {sev}: {by_sev[sev]}")
    lines += ["", f"## top {args.top} issues", ""]
    for i, issue in enumerate(all_issues[: args.top]):
        lines += [
            f"### {i+1}. {issue['card_id']} ({issue['rule_id']}, sev {issue['severity']})",
            "",
            f"**{issue['category']}**: {issue['message']}",
            "",
            f"- text: `{issue['evidence'].get('text_excerpt', '')[:120]}`",
            f"- fix: `{issue['suggested_fix']['patch']}`",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # stdout summary
    print("=" * 70)
    print(f"Static Audit (Layer 1)")
    print("=" * 70)
    print(f"cards scanned : {report['cards_scanned']}")
    print(f"issues found  : {report['issues_total']}")
    print()
    print("by rule:")
    for rule, count in sorted(by_rule.items()):
        print(f"  {rule}: {count}")
    print()
    print("by severity:")
    for sev in sorted(by_sev.keys(), reverse=True):
        print(f"  sev {sev}: {by_sev[sev]}")
    print()
    print(f"output: {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"        {OUT_MD.relative_to(REPO_ROOT)}")
    print()
    if args.card:
        print(f"=== {args.card} ===")
        card_issues = [i for i in all_issues if i["card_id"] == args.card]
        for issue in card_issues:
            print(f"  [{issue['rule_id']} sev {issue['severity']}] {issue['message']}")


if __name__ == "__main__":
    main()
