#!/usr/bin/env python3
"""全 4,518 カード を DSL → 日本語 renderer で 訳して 公式テキスト と side-by-side 比較。

検出するもの:
- 数値ズレ (= 公式 "5枚" だが overlay "3枚")
- 概念抜け (= 公式 "KOする" だが overlay に ko primitive なし)
- 簡略化 / 対象ズレ (= 公式 "リーダーかキャラ" だが overlay "キャラのみ")
- 条件抜け (= 公式 "ライフX以下の場合" だが overlay に if なし)
- 用語 mismatch (= 公式 "ドン!!付与" だが overlay attach_don 欠如 など)

出力:
- db/dsl_jp_audit.json  全比較データ
- db/dsl_jp_audit.md    重要度別 サマリ

severity:
  5 = 致命: 主要効果欠落 (= 全 do 配列空 / _unimplemented 残)
  4 = 大: 数値ズレ / 対象ズレ (= leader 除外 / power 制限 等)
  3 = 中: 条件節 抜け (= if 句 欠如)
  2 = 軽: 簡略化痕跡 / 不完全な対象記述
  1 = 情報: 概念上の差異 (= 用語選択 等)
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.effect_text import render_card_effects, render_effect_structured  # noqa: E402

CARDS = {c["card_id"]: c for c in json.load(open(ROOT / "db" / "cards.json"))}
OVERLAY = json.load(open(ROOT / "db" / "card_effects.json"))


def get_text(cid: str) -> str:
    text = (CARDS.get(cid, {}).get("text") or "").strip()
    if not text:
        base = cid.split("_")[0]
        text = (CARDS.get(base, {}).get("text") or "").strip()
    return text


def normalize_for_comparison(s: str) -> str:
    """比較用に 表記揺れを 吸収。"""
    s = s.replace("！", "!").replace("‼", "!!").replace("：", ":")
    s = re.sub(r"\s+", "", s)
    return s


# ---------- 個別 mismatch チェッカ ----------

def check_numbers(text: str, rendered: str, cid: str) -> list[dict]:
    """公式テキストに登場する数値 (= N 枚/N コスト/N 以上以下) で overlay に欠けてるものを検出。"""
    issues = []
    norm_overlay = normalize_for_comparison(rendered)
    # 「カードN枚を引く」 → overlay の draw N と一致確認
    for m in re.finditer(r"カード(\d+)枚を引く", text):
        n = int(m.group(1))
        if f"カード{n}枚を引く" not in norm_overlay:
            # overlay 側 で別の n を引いてるか
            other = re.search(r"カード(\d+)枚を引く", norm_overlay)
            if other and int(other.group(1)) != n:
                issues.append({"kind": "draw_count_mismatch", "expected": n, "got": int(other.group(1)), "severity": 4})
    # 「ライフN枚を手札」 vs overlay life_to_hand N
    for m in re.finditer(r"自分のライフ(\d+)枚.{0,10}手札", text):
        n = int(m.group(1))
        if f"ライフ{n}枚を手札に加える" not in norm_overlay:
            other = re.search(r"ライフ(\d+)枚を手札", norm_overlay)
            if other and int(other.group(1)) != n:
                issues.append({"kind": "life_to_hand_mismatch", "expected": n, "got": int(other.group(1)), "severity": 4})
    # 「ドン!!N枚をアクティブで追加」
    for m in re.finditer(r"ドン!!\s*(\d+)枚.{0,15}アクティブで追加", text):
        n = int(m.group(1))
        if f"ドン!!{n}枚をアクティブで追加" not in norm_overlay:
            other = re.search(r"ドン!!(\d+)枚をアクティブで追加", norm_overlay)
            if other and int(other.group(1)) != n:
                issues.append({"kind": "add_don_mismatch", "expected": n, "got": int(other.group(1)), "severity": 4})
    # power_pump 数値ズレ 検出は false positive 多い (= multi-clause で entry 別の値を混同)
    # → 個別ケース調査向けに 検出は省略 (= db/dsl_jp_audit.md の手書きレビューで対応)
    return issues


def check_concept_missing(text: str, rendered: str, entries: list, cid: str) -> list[dict]:
    """公式テキストの 主要 概念が overlay にない。"""
    issues = []
    norm_text = normalize_for_comparison(text)
    norm_over = normalize_for_comparison(rendered)
    flat_entries = json.dumps(entries, ensure_ascii=False)
    # KO: 公式 "KOする" が in text, overlay に ko primitive なし
    if ("KOする" in norm_text or "ＫＯする" in norm_text):
        ko_keys = ('"ko"', "ko_multi", "ko_all_others", "ko_opp_stage", "chara_to_opp_life",
                   "chara_to_self_life", "replace_ko",
                   "optional_after_battle_mutual_ko", "optional_battle_ko_with_self_ko")
        if "KOする" not in norm_over and not any(k in flat_entries for k in ko_keys):
            issues.append({"kind": "missing_ko_concept", "severity": 5})
    # 「手札に戻す」
    if "持ち主の手札に戻す" in norm_text or "手札に戻す" in norm_text:
        return_keys = ("return_to_hand", "return_self_to_hand", "return_self_chara_to_hand")
        if not any(k in flat_entries for k in return_keys):
            # 例外: 「自分の手札X枚を捨てる」 のような 別概念 を除外
            if (
                not re.search(r"手札\d+枚を.{0,3}捨てる", text)
                and "を手札に加える" not in text
                and "1枚を捨てる" not in text
            ):
                issues.append({"kind": "missing_return_to_hand_concept", "severity": 5})
    # 「カードN枚を引く」
    if re.search(r"カード\d+枚を引く", text):
        if "draw" not in flat_entries and "draw_per" not in flat_entries:
            issues.append({"kind": "missing_draw_concept", "severity": 5})
    # 「ライフN枚を手札に加える」
    if re.search(r"自分のライフ\d+枚.{0,10}手札に加える", text):
        if "life_to_hand" not in flat_entries and "life_top_or_bottom_to_hand" not in flat_entries:
            issues.append({"kind": "missing_life_to_hand_concept", "severity": 5})
    # 「ドン!!デッキから ドン!!N枚 まで を アクティブで追加」
    if re.search(r"ドン!!デッキから.{0,30}アクティブで追加", text):
        if "add_don" not in flat_entries and "add_don_active" not in flat_entries:
            issues.append({"kind": "missing_add_don_concept", "severity": 5})
    # 「レストにする」 — rest 系 primitive 認識
    if re.search(r"相手の.{0,20}レストにする", text):
        rest_keys = ('"rest"', "rest_opp_don", "rest_self_cards", "keep_opp_rested",
                     "set_cannot_rest", "stay_rested_next_refresh", "rest_opp_chara")
        if not any(k in flat_entries for k in rest_keys):
            issues.append({"kind": "missing_rest_concept", "severity": 5})
    # 「アクティブにする」 — untap 系 primitive 認識
    if re.search(r"アクティブにする", text):
        untap_keys = ('"untap"', "untap_chara", "untap_don")
        if not any(k in flat_entries for k in untap_keys):
            issues.append({"kind": "missing_untap_concept", "severity": 5})
    # 「速攻」 / 「ブロッカー」 / 「ダブルアタック」 等 のキーワード付与
    for kw in ["速攻", "二回攻撃", "二回アタック"]:
        if f"《{kw}》を得る" in text or f"《{kw}》を持つ" in text or kw + "を得る" in text:
            if "give_keyword" not in flat_entries and "give_rush" not in flat_entries:
                issues.append({"kind": f"missing_grant_{kw}", "severity": 4})
                break
    # 「自分のデッキの上から N 枚を見て」 → search_top_n
    if re.search(r"自分のデッキの上から\d+枚を見て", text):
        if "search_top_n" not in flat_entries and "look_top_reorder" not in flat_entries and "reveal_top" not in flat_entries:
            issues.append({"kind": "missing_search_top_n_concept", "severity": 5})
    # 「自分のデッキから...手札に加え」 → search
    if re.search(r"自分のデッキから.{0,50}手札に加える", text) and not re.search(r"上から", text):
        if '"search"' not in flat_entries and "search_top_n" not in flat_entries:
            issues.append({"kind": "missing_search_concept", "severity": 5})
    return issues


def check_target_narrowing(text: str, rendered: str, entries: list, cid: str) -> list[dict]:
    """公式 'リーダーかキャラ' が overlay で 'キャラのみ' に narrow されている等。"""
    issues = []
    flat = json.dumps(entries, ensure_ascii=False)
    # 「相手のリーダーかキャラ」 vs overlay target が "character" 限定
    leader_or_chara_count = len(re.findall(r"相手のリーダーかキャラ", text))
    # overlay に 'opponent_inplay' / 'one_opponent_inplay_any' / 'opp' team を含む?
    has_inplay_target = ("opponent_inplay" in flat or "opp_inplay" in flat or "_opponent_inplay" in flat
                          or "one_opp_inplay" in flat or "opp_inplay_any" in flat
                          or "any_opp_inplay" in flat or "opp_team" in flat)
    has_character_target = ("opponent_character" in flat or "one_opponent_character" in flat or "any_opponent_character" in flat)
    if leader_or_chara_count >= 1 and not has_inplay_target and has_character_target:
        # narrowing 検出
        issues.append({
            "kind": "target_narrowing_leader_to_chara",
            "severity": 4,
            "note": "公式 'リーダーかキャラ' を overlay は 'キャラのみ' に narrow",
        })
    # power_le_5000 が 公式テキストに 「パワー5000以下」 がない場合 → simplification suspicion
    if ("one_opponent_character_le_5000" in flat or "any_opponent_character_le_5000" in flat) \
       and "パワー5000以下" not in text and "5000以下" not in text:
        issues.append({
            "kind": "fake_power_5000_limit",
            "severity": 4,
            "note": "overlay が target に le_5000 をつけてるが 公式テキストに 5000 制限なし",
        })
    return issues


def check_conditions_missing(text: str, entries: list, cid: str) -> list[dict]:
    """公式テキストの '〜の場合' が overlay if 句に 反映されてない場合を検出。"""
    issues = []
    flat = json.dumps(entries, ensure_ascii=False)
    # 「ライフが N 以下の場合」
    for m in re.finditer(r"ライフが\s*(\d+)\s*以下の場合", text):
        n = int(m.group(1))
        if f'"self_life_le": {n}' not in flat and f'"self_life_le":{n}' not in flat:
            issues.append({"kind": "missing_if_self_life_le", "expected_n": n, "severity": 3})
    # 「ライフが N 以上の場合」
    for m in re.finditer(r"ライフが\s*(\d+)\s*以上の場合", text):
        n = int(m.group(1))
        if f'"self_life_ge": {n}' not in flat and f'"self_life_ge":{n}' not in flat:
            issues.append({"kind": "missing_if_self_life_ge", "expected_n": n, "severity": 3})
    # 「このキャラのパワーが N 以上の場合」 → if self_power_ge
    for m in re.finditer(r"このキャラのパワーが\s*(\d+)\s*以上の場合", text):
        n = int(m.group(1))
        if f'"self_power_ge": {n}' not in flat and f'"self_power_ge":{n}' not in flat:
            issues.append({"kind": "missing_if_self_power_ge", "expected_n": n, "severity": 3})
    # 「自分のリーダーが特徴《X》を持つ場合」 → leader_feature OR features_any (or X が flat に存在で許容)
    for m in re.finditer(r"自分のリーダーが特徴《(.+?)》(?:か《(.+?)》)?を持つ場合", text):
        f1, f2 = m.group(1), m.group(2)
        found = False
        if f'"leader_feature": "{f1}"' in flat:
            found = True
        if f'"leader_feature_contains": "{f1}"' in flat:
            found = True
        if "leader_features_any" in flat and f'"{f1}"' in flat:
            found = True
        if f2 and "leader_features_any" in flat and f'"{f2}"' in flat:
            found = True
        if not found:
            expected = f"{f1}/{f2}" if f2 else f1
            issues.append({"kind": "missing_if_leader_feature", "expected_feature": expected, "severity": 3})
    # 「相手のターン中」 → opp_turn condition (= when が opp_attack 系 / on_attached_don 等 reactive triggerなら 自動的に opp_turn)
    if "【相手のターン中】" in text:
        # opp_turn が flat に あるか、 もしくは when が opp_attack 系 = 自動的 opp_turn
        opp_turn_when = any(
            e.get("when") in (
                "opp_attack", "opp_attack_on_leader", "opp_attack_on_chara",
                "on_opp_chara_played", "on_opp_chara_ko", "on_opp_life_taken",
                "on_opp_blocker_use", "opp_event_or_trigger_fired",
            ) for e in entries if isinstance(e, dict)
        )
        if not opp_turn_when and '"opp_turn"' not in flat:
            issues.append({"kind": "missing_if_opp_turn", "severity": 2})
    return issues


def check_optional_marker(text: str, entries: list, cid: str) -> list[dict]:
    """公式 '〜してもよい' が overlay で optional になっているか。"""
    issues = []
    flat = json.dumps(entries, ensure_ascii=False)
    if re.search(r"してもよい", text):
        if '"optional": true' not in flat and "optional_cost_then" not in flat:
            issues.append({"kind": "missing_optional_flag", "severity": 2})
    return issues


def check_simplified_marker(text: str, entries: list, cid: str) -> list[dict]:
    """overlay 内に _unimplemented / 「簡略」 / 「近似」 / 「省略」 マーカーが残っているか。

    metadata field (= `_approx_note` / `_note` 等) は 検査対象外 (= 既知の 制約を
    明示するための 文書 フィールドであり、 効果本体の 簡略マーカー では ない)。
    """
    issues = []
    # metadata field を 除外 した entries で 検査
    filtered_entries = []
    for e in entries:
        if not isinstance(e, dict):
            filtered_entries.append(e)
            continue
        e_clean = {k: v for k, v in e.items() if k not in ("_approx_note", "_note", "_doc")}
        filtered_entries.append(e_clean)
    flat = json.dumps(filtered_entries, ensure_ascii=False)
    for marker in ["_unimplemented", "_simplified", "簡略", "近似", "省略", "fallback", "自動抽出"]:
        if marker in flat:
            issues.append({"kind": f"marker_{marker}", "severity": 5, "note": "simplification marker remains"})
            break
    return issues


def is_vanilla_or_innate_only(text: str) -> bool:
    """テキストが バニラ / 単純キーワードのみ (= 追加 overlay 不要) か判定。

    対象:
    - 純粋ブロッカー / 速攻 / ダブルアタック / バニッシュ のみ
    - キーワード キーワードの組み合わせ (= 説明 () 付き)
    - "-" / 空文字
    - 「ルール上、 このカードはカード名を「X」 としても扱う」 + キーワードのみ
      (= 光月おでん / シャーロット・リンリン 等の パラレル variant)
    """
    t = text.strip().replace("（", "(").replace("）", ")")
    if t in ("-", ""):
        return True
    # ルール文 (= 名前 alias / 何枚デッキに入れられる / 含む扱い 等) を 除去 してから 判定
    t_stripped = t
    # 「ルール上、 このカードはカード名を「X」 としても扱う。」
    t_stripped = re.sub(
        r"ルール上、\s*このカードはカード名を「[^」]+」\s*としても扱う。?\s*",
        "",
        t_stripped,
    )
    # 「ルール上、 このカードはデッキに何枚でも入れる(こと|事)ができる。」 (= P-114 / OP08-072 等)
    t_stripped = re.sub(
        r"ルール上、\s*このカードはデッキに何枚でも入れ(?:る|られる)(?:こと|事)?ができる。?\s*",
        "",
        t_stripped,
    )
    if t_stripped == "":
        return True
    # 単純キーワード列挙のみ
    # 【ブロッカー】(...説明...) 【ダブルアタック】(...説明...) 等
    if re.fullmatch(
        r"(?:【(ブロッカー|速攻|二回攻撃|ダブルアタック|バニッシュ|トリガー|カウンター)】(?:\([^()]*\))?\s*)+",
        t_stripped,
    ):
        return True
    return False


def check_empty_do(entries: list, text: str, cid: str) -> list[dict]:
    """効果テキストがあるのに overlay が 空 / do なし。"""
    issues = []
    if not text:
        return issues
    if is_vanilla_or_innate_only(text):
        return issues  # バニラは 空 overlay で正しい
    if not isinstance(entries, list) or len(entries) == 0:
        issues.append({"kind": "empty_overlay_with_text", "severity": 5})
        return issues
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        do = e.get("do") or []
        # when が non-effect (= e.g. leader_passive without do) は許容
        # replace_ko / replace_leave も cost-only で do 空が 公式 「代わりに 〜 する」 の 解釈
        if (
            len(do) == 0
            and not e.get("static")
            and e.get("when")
            not in ("leader_passive", "setup_modifier", "replace_ko", "replace_leave")
        ):
            issues.append({"kind": "empty_do_array", "entry_index": i, "severity": 4})
    return issues


def audit_card(cid: str, entries: list) -> list[dict]:
    text = get_text(cid)
    if not text:
        return []
    if not isinstance(entries, list):
        return []
    rendered = render_card_effects(cid, entries)
    issues: list[dict] = []
    issues += check_simplified_marker(text, entries, cid)
    issues += check_empty_do(entries, text, cid)
    issues += check_concept_missing(text, rendered, entries, cid)
    issues += check_numbers(text, rendered, cid)
    issues += check_target_narrowing(text, rendered, entries, cid)
    issues += check_conditions_missing(text, entries, cid)
    issues += check_optional_marker(text, entries, cid)
    for iss in issues:
        iss["card_id"] = cid
        iss["text"] = text[:200]
        iss["rendered"] = rendered[:300]
    return issues


def main():
    all_issues: list[dict] = []
    for cid, entries in OVERLAY.items():
        if cid.startswith("_"):
            continue
        all_issues.extend(audit_card(cid, entries))

    # severity 別カウント
    from collections import Counter
    by_kind = Counter(iss["kind"] for iss in all_issues)
    by_sev = Counter(iss["severity"] for iss in all_issues)

    print("=== DSL → 日本語 vs 公式テキスト audit ===")
    print(f"\nTotal issues: {len(all_issues)}")
    print("\nBy severity:")
    for sev in sorted(by_sev.keys(), reverse=True):
        print(f"  sev {sev}: {by_sev[sev]}")
    print("\nBy kind:")
    for k, n in by_kind.most_common():
        print(f"  {n:>5}  {k}")

    # ファイル出力
    out_json = ROOT / "db" / "dsl_jp_audit.json"
    out_json.write_text(json.dumps(all_issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_json}")

    # md レポート
    md_lines = [
        "# DSL → 日本語 vs 公式テキスト 比較 audit",
        "",
        f"全 {len(all_issues)} 件の mismatch を検出。",
        "",
        "## 重要度サマリ",
        "",
    ]
    for sev in sorted(by_sev.keys(), reverse=True):
        md_lines.append(f"- **sev {sev}**: {by_sev[sev]} 件")
    md_lines.append("")
    md_lines.append("## 種類別件数")
    md_lines.append("")
    for k, n in by_kind.most_common():
        md_lines.append(f"- `{k}`: {n}")
    md_lines.append("")
    # severity 5 の 上位 50 件 詳細
    md_lines.append("## sev 5 (= 致命) 上位 50 件")
    md_lines.append("")
    sev5 = [i for i in all_issues if i["severity"] == 5]
    for iss in sev5[:50]:
        md_lines.append(f"### {iss['card_id']} — {iss['kind']}")
        md_lines.append(f"- **公式**: {iss['text']}")
        md_lines.append(f"- **renderer**: {iss['rendered']}")
        if iss.get("note"):
            md_lines.append(f"- note: {iss['note']}")
        md_lines.append("")
    # sev 4 上位 50 件
    md_lines.append("## sev 4 上位 50 件")
    md_lines.append("")
    sev4 = [i for i in all_issues if i["severity"] == 4]
    for iss in sev4[:50]:
        md_lines.append(f"### {iss['card_id']} — {iss['kind']}")
        md_lines.append(f"- **公式**: {iss['text']}")
        md_lines.append(f"- **renderer**: {iss['rendered']}")
        if iss.get("note"):
            md_lines.append(f"- note: {iss['note']}")
        md_lines.append("")

    out_md = ROOT / "db" / "dsl_jp_audit.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Wrote: {out_md}")

    return len(all_issues)


if __name__ == "__main__":
    raise SystemExit(0 if main() == 0 else 1)
