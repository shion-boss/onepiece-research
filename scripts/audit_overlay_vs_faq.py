# -*- coding: utf-8 -*-
"""
overlay vs FAQ 突合監査スクリプト
================================

目的:
    `db/card_effects.json` の効果オーバーレイを、 公式 FAQ (`db/faq/cardqa_*.json`)
    と突合し、 解釈の不一致候補を洗い出す。

    現在のオーバーレイは 15 メタリーダー以外は自動生成されているため、 公式 Q&A の
    解釈と微妙にズレている可能性がある。 このスクリプトは「Q&A で言及されているのに
    overlay に対応する仕組みが無い」 ようなカードを surface することで、 手動レビューの
    優先度付けを支援する。

使い方:
    .venv/bin/python scripts/audit_overlay_vs_faq.py
    # → db/overlay_audit.md (Markdown レポート)
    # → db/overlay_audit.json (JSON データ、 後続加工用)

ロジック:
    1. cardqa_*.json から全 Q&A を集約
    2. Q+A テキストから card_id (OP/ST/EB/PRB/P-NNN) を正規表現抽出
    3. 各 card_id について overlay を引き、 効果 + 公式テキスト + 関連 Q&A を並べる
    4. 不審ヒューリスティック:
       - 公式テキストに 「【起動メイン】」 と書かれてるのに overlay に when=activate_main が無い
       - 公式テキストに 「【ターン1回】」 が含まれるのに overlay の cost に once_per_turn が無い
       - 公式テキストに 「自分のターン中」 「相手のターン中」 が含まれるのに overlay の if に対応条件が無い
       - Q&A が 「いいえ、できません」 と否定しているがその否定対象が overlay に書かれている可能性
       - Q&A 数 ≥ 3 件のカード = 公式が説明したかった = 注目度高い
    5. 不審度スコア順にソートして出力

注意: これは候補 surface ツールであって、 全件レビューを置換するものではない。
      ヒューリスティックは false positive 多め設計 (見逃しを避ける)。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDQA_DIR = ROOT / "db" / "faq"
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
OUTPUT_MD = ROOT / "db" / "overlay_audit.md"
OUTPUT_JSON = ROOT / "db" / "overlay_audit.json"

# card_id 正規表現: OPxx-yyy / STxx-yyy / EBxx-yyy / PRBxx-yyy / P-yyy
CARD_ID_RE = re.compile(r"\b(OP|ST|EB|PRB)(\d{1,2})-(\d{3})\b|\bP-(\d{3})\b")


def extract_card_ids(text: str) -> set[str]:
    out: set[str] = set()
    for m in CARD_ID_RE.finditer(text):
        if m.group(4):  # P-NNN
            out.add(f"P-{m.group(4)}")
        else:
            prefix, num1, num2 = m.group(1), m.group(2), m.group(3)
            out.add(f"{prefix}{num1.zfill(2)}-{num2}")
    return out


def load_all_qa() -> dict[str, list[dict]]:
    """各 cardqa_*.json を読み、 card_id → Q&A 群 を返す。"""
    qa_by_card: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(CARDQA_DIR.glob("cardqa_*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        series = data.get("series_slug") or f.stem
        for item in data.get("items", []):
            q = item.get("q", "")
            a = item.get("a", "")
            ids = extract_card_ids(q + " " + a)
            for cid in ids:
                qa_by_card[cid].append({"q": q, "a": a, "source": series})
    return qa_by_card


def load_cards() -> dict[str, dict]:
    with open(CARDS_JSON, encoding="utf-8") as fh:
        cards = json.load(fh)
    return {c["card_id"]: c for c in cards}


def load_overlay() -> dict[str, list[dict]]:
    with open(OVERLAY_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def overlay_when_set(effects: list[dict]) -> set[str]:
    return {e.get("when") for e in effects if isinstance(e, dict) and e.get("when")}


def overlay_has_once_per_turn(effects: list[dict]) -> bool:
    """cost.once_per_turn (= activate_main / on_attack の所有コスト) もしくは
    top-level once_per_turn (= 任意 when の trigger ガード) のどちらかが指定されているか判定。"""
    for e in effects:
        if not isinstance(e, dict):
            continue
        cost = e.get("cost") or {}
        # cost は dict (= 通常) または list (= replace_ko/leave 用) の 2 形式
        if isinstance(cost, dict) and cost.get("once_per_turn"):
            return True
        if isinstance(cost, list):
            for sub in cost:
                if isinstance(sub, dict) and sub.get("once_per_turn"):
                    return True
        # top-level (= cost 不要の trigger ガード、 engine の _check_and_set_once_per_turn 経由)
        if e.get("once_per_turn"):
            return True
    return False


# R2 拡張で engine 側に追加された新規 cost / trigger / primitive。
# audit が「未知のキー」 と勘違いしないように知識として記録。
# (audit が能動的にチェックする訳ではなく、 ドキュメンテーション目的。)
R2_KNOWN_COST_KEYS = {
    # filter 付き discard (= 「特徴X を持つカード N 枚を捨てる」)
    "discard_hand_with_filter",
    # name 一致キャラ/ステージを rest (= 「自分の『X』1 枚をレストにできる」)
    "rest_self_target_name",
    "rest_self_target",  # alias
}
R2_KNOWN_WHEN_VALUES = {
    # KO された側 (自陣) の場効果発火 (OP10-042 ウソップ等)
    "on_self_chara_ko",
    # 相手が EVENT/COUNTER/【トリガー】 を発動した時 (OP11-102 ケイミー等)
    "opp_event_or_trigger_fired",
}
R2_KNOWN_PRIMITIVE_KEYS = {
    # 名前フィルタ付き taunt (OP01-051 ユースタス・キッド系)
    "cannot_attack_target_except",
    # filter 付き base_cost 静的変更 (OP10-042 ウソップ系)
    "set_base_cost_filtered_static",
}
R2_KNOWN_OPTIONAL_COST_PRIMITIVES = {
    # optional_cost_then.cost で扱える追加 primitive (R2)
    "return_self_don_to_deck",
    "power_pump",  # 弱体化 (リーダーパワー -N) cost
    "rest_self_target_name",
    "discard_hand_with_filter",
}
R2_KNOWN_FILTER_KEYS = {
    # 特徴 OR フィルタ (= 「特徴《魚人族》か《人魚族》」 等)
    "feature_in",
}


# R3 拡張で engine 側に追加された新規 cost / trigger / primitive。
# audit が「未知のキー」 と勘違いしないように知識として記録。
R3_KNOWN_COST_KEYS = {
    # optional_cost_then.cost で扱える追加 cost (R3)
    # 「自分のステージ1枚を持ち主のデッキの下に置くことができる」 (OP06-102 / OP06-111)
    "stage_to_deck_bottom",
    # 「自分のキャラ1枚を持ち主のデッキの下に置くことができる」 (OP15-041 オオロンブス)
    "return_self_chara_to_deck_bottom",
}
R3_KNOWN_WHEN_VALUES = {
    # 「相手の効果で場を離れる場合、 代わりに〜できる」 (OP12-053 ボルサリーノ系)
    # replace_ko の上位互換: KO + return_to_hand + return_to_deck_bottom で発火。
    "replace_leave",
}
R3_KNOWN_PRIMITIVE_KEYS = {
    # 相手のライフ N 枚をトラッシュへ (OP11-102 ケイミー)
    "mill_opp_life_to_trash",
    # トラッシュから複数体登場 (unique_name 対応) (OP06-062 ヴィンスモーク・ジャッジ)
    # 既存 play_from_trash と内部統合済 (limit + unique_name 拡張)。 別名としても受け付ける。
    "play_multi_from_trash",
}
R3_KNOWN_OPTIONAL_COST_PRIMITIVES = {
    # R3 で追加された optional_cost_then.cost 用 primitive。
    "stage_to_deck_bottom",
    "return_self_chara_to_deck_bottom",
}
R3_KNOWN_REPLACE_KO_COST_PRIMITIVES = {
    # replace_ko / replace_leave の cost 配列で扱える primitive (R3)。
    "discard_hand_with_filter",  # OP15-003_p1 アルビダ, OP12-053 ボルサリーノ
    "trash_self_hand_random",
    "discard_hand",
}
R3_KNOWN_FILTER_KEYS = {
    # cards.json の trigger フィールド (= 【トリガー】持ちカード) を選別する alias。
    # 既存 has_trigger と同等。 overlay 側の表記揺れ吸収。
    "trigger",
}
R3_KNOWN_TARGET_SPECS = {
    # rest primitive 専用の特殊 target spec (= 相手キャラ or ドン 1 枚)。
    # 相手ドンは InPlay ではないので汎用 target ではなく primitive 拡張で対応。
    # (EB03-061 ウタ系)
    "one_opp_chara_or_don",
}


# R4 拡張で engine 側に追加された新規 cost / primitive / spec。
# audit が「未知のキー」 と勘違いしないように知識として記録。
R4_KNOWN_COST_KEYS = {
    # 公開コスト (= 実消費なし)。 「自分の手札から特徴X を持つカード N 枚を公開することができる：効果」
    # 影響カード: OP14-105 ゴルゴン三姉妹 / OP12-003 クロッカス / OP08-040 アトモス / OP12-009 ジンベエ 等 (23+ 枚)
    # 形式: {"reveal_hand_with_filter": {"filter": {...}, "count": N}}
    #    or {"reveal_hand_with_filter": {"feature_in": [...], "count": N}}
    "reveal_hand_with_filter",
}
R4_KNOWN_OPTIONAL_COST_PRIMITIVES = {
    # optional_cost_then.cost で扱える追加 cost (R4)。
    # 公開のみ、 実消費なし (公式 OP14-105 / OP12-003)。
    "reveal_hand_with_filter",
    # 自ライフ上/下から N 枚をトラッシュ (= ST13-005 等)。 既存 primitive を cost として認識。
    "mill_self_life_to_trash",
}
R4_KNOWN_PRIMITIVE_KEYS = {
    # 「N1 と N2 と N3 それぞれ 1 枚ずつ」 (= ST13-006 ロー/エース/サボ系)
    "play_from_hand_named_set",
    # 「自分のデッキの上から N 枚を公開し、 (filter 条件) の場合、 効果X。 その後 (rest_remain)」
    # ST22-016 / ST22-012 / ST17-001 / EB01-029 等。 reveal + cond → conditional then/else。
    "reveal_top_then",
}
R4_KNOWN_PRIMITIVE_OPTIONS = {
    # attach_don / attach_rested_don の per_target=true (= 「全員に 1 枚ずつ付与」)。
    # OP14-105 ゴルゴン三姉妹 / OP04-004 アラバスタ系。
    # spec キー自体は既存だが、 per_target オプションが追加された。
    "per_target",
}


def overlay_if_keys(effects: list[dict]) -> set[str]:
    """効果バンドル内の条件キーを集める。 単一辞書 `if` と複数条件配列 `conditions`
    両形式に対応 (R44 で `conditions` 形式が普及したため拡張)。
    """
    keys: set[str] = set()
    for e in effects:
        if not isinstance(e, dict):
            continue
        cond = e.get("if") or {}
        keys.update(cond.keys())
        conditions = e.get("conditions") or []
        if isinstance(conditions, list):
            for c in conditions:
                if isinstance(c, dict):
                    keys.update(c.keys())
    return keys


SIMPLIFIED_MARKERS = ("fallback", "簡略", "auto", "省略", "近似", "自動抽出")


def has_simplified_marker(effects: list[dict]) -> bool:
    """overlay に simplification marker (= 公式テキスト忠実でない兆候) があるか?"""
    for e in effects:
        if not isinstance(e, dict):
            continue
        text = e.get("_text", "") or ""
        if any(m in text for m in SIMPLIFIED_MARKERS):
            return True
    return False


def detect_issues(card: dict, effects: list[dict], qa_list: list[dict]) -> list[str]:
    """不審ヒューリスティック検出。 返り値は issue タグ。"""
    issues: list[str] = []
    text = card.get("text") or ""
    when_set = overlay_when_set(effects)
    cond_keys = overlay_if_keys(effects)

    # === 簡略化マーカー検出 (最優先: ポリシー違反) ===
    if has_simplified_marker(effects):
        issues.append("simplified_marker")

    # === when 不整合 ===
    if "【起動メイン】" in text and "activate_main" not in when_set:
        issues.append("missing_activate_main")
    # 「【登場時】」 のうち「【登場時】効果」 (= フィルタ参照) は trigger ではない。
    # 例: PRB01-001 サンジ 「自分のコスト8以下の【登場時】効果を持たないキャラ1枚...」
    # 該当パターン 「【登場時】効果」 を除いて素の「【登場時】」 が残るか確認。
    text_for_on_play = (text or "").replace("【登場時】効果", "")
    if "【登場時】" in text_for_on_play and "on_play" not in when_set:
        issues.append("missing_on_play")
    if "【KO時】" in text and "on_ko" not in when_set:
        issues.append("missing_on_ko")
    if "【アタック時】" in text and "on_attack" not in when_set:
        issues.append("missing_on_attack")
    if "【ブロック時】" in text and "on_block" not in when_set:
        issues.append("missing_on_block")
    if "【相手のアタック時】" in text and "opp_attack" not in when_set:
        issues.append("missing_opp_attack")
    if "【自分のターン終了時】" in text and "end_of_turn" not in when_set:
        issues.append("missing_end_of_turn")
    if "【相手のターン終了時】" in text and "opp_end_of_turn" not in when_set:
        issues.append("missing_opp_end_of_turn")
    # 「【トリガー】」 のうち
    #   - 「【トリガー】を持つ」 (= filter 参照): trigger 宣言ではない (OP14-110 ホグバック等)
    #   - 「イベントか【トリガー】を発動した」 (= opp event/trigger fired): 別 trigger 機構
    #   - 「【トリガー】効果」 (= filter 参照)
    # これらを除いて素の「【トリガー】」 が残るか確認。
    text_for_trigger = (text or "")
    text_for_trigger = text_for_trigger.replace("【トリガー】を持つ", "")
    text_for_trigger = text_for_trigger.replace("【トリガー】効果", "")
    text_for_trigger = text_for_trigger.replace("【トリガー】を発動", "")
    if "【トリガー】" in text_for_trigger and "trigger" not in when_set:
        issues.append("missing_trigger")
    if "【ターン1回】" in text and not overlay_has_once_per_turn(effects):
        issues.append("missing_once_per_turn")

    # === if (条件) 不整合 ===
    if "自分のターン中" in text and not any(
        k in cond_keys for k in ("self_turn", "is_owners_turn")
    ):
        # ただし overlay 全体に該当ロジックある可能性 (DON+1000 等は別系統) のため弱シグナル
        issues.append("self_turn_condition_unmodeled")
    if "相手のターン中" in text and "opp_turn" not in cond_keys:
        issues.append("opp_turn_condition_unmodeled")
    if "ライフが" in text and not any(
        k in cond_keys for k in (
            "self_life_le", "self_life_ge", "opp_life_le", "opp_life_ge",
        )
    ):
        issues.append("life_condition_unmodeled")
    if "リーダーが" in text and "特徴" in text and not any(
        k in cond_keys for k in (
            "leader_feature", "leader_feature_contains", "leader_features_any",
            "opp_leader_feature",
        )
    ):
        issues.append("leader_feature_unmodeled")
    if "ドン!!" in text and "枚" in text and not any(
        k in cond_keys for k in (
            "self_don_ge", "self_don_active_ge", "self_attached_don_ge",
            "self_don_le", "don_count_ge", "don_count_le",
            "opp_don_count_ge", "opp_don_count_le",
        )
    ):
        # ドン!! 枚数条件の可能性
        issues.append("don_count_condition_unmodeled")

    # === FAQ 注目度 ===
    if len(qa_list) >= 3:
        issues.append(f"faq_attention_{len(qa_list)}")

    # === FAQ 否定文の存在 ===
    for qa in qa_list:
        a = qa.get("a", "")
        if "いいえ" in a or "できません" in a:
            issues.append("faq_negation")
            break

    # === 効果 0 件 (vanilla) なのに FAQ ある ===
    if len(effects) == 0 and len(qa_list) >= 1:
        # ただし、 テキストが純粋にキーワードマーカーのみのカード
        # (= 【ブロッカー】 / 【速攻】 / 【バニッシュ】 / 【ダブルアタック】 / 【ブロック不可】 / 「-」)
        # は真の vanilla とみなし、 flag しない (FAQ はキーワード一般説明のみ)。
        stripped = re.sub(r"【[^】]+】", "", text or "")
        stripped = re.sub(r"\([^)]*\)", "", stripped)  # 「(...)」 の説明テキストを除去
        stripped = stripped.replace("-", "").strip()
        # 空 or 短い (キーワード説明のみ) なら真の vanilla
        if stripped and len(stripped) >= 4:
            issues.append("vanilla_but_has_faq")

    return issues


SEVERITY = {
    "simplified_marker": 8,        # ポリシー違反 → 高 severity
    "missing_activate_main": 5,
    "missing_on_play": 5,
    "missing_on_ko": 4,
    "missing_on_attack": 4,
    "missing_on_block": 5,
    "missing_opp_attack": 4,
    "missing_end_of_turn": 4,
    "missing_opp_end_of_turn": 4,
    "missing_trigger": 4,
    "missing_once_per_turn": 3,
    "self_turn_condition_unmodeled": 1,
    "opp_turn_condition_unmodeled": 1,
    "life_condition_unmodeled": 1,
    "leader_feature_unmodeled": 1,
    "don_count_condition_unmodeled": 1,
    "faq_negation": 2,
    "vanilla_but_has_faq": 3,
}


def issue_severity(issue: str) -> int:
    if issue.startswith("faq_attention_"):
        # faq_attention_N → 1〜3 段階
        try:
            n = int(issue.split("_")[-1])
        except ValueError:
            return 1
        return min(3, max(1, n // 3))
    return SEVERITY.get(issue, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--top", type=int, default=80,
        help="出力する上位件数 (severity 順)",
    )
    parser.add_argument(
        "--include-meta", action="store_true",
        help="cardrush メタリーダー (= 手書き対象) も含める (default: 除外)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="severity = 0 のカードも全件出力 (= 完全レポート、 巨大)",
    )
    args = parser.parse_args()

    cards = load_cards()
    overlay = load_overlay()
    qa_by_card = load_all_qa()

    # メタデッキの leader はスキップ (= 手書きで信頼度高)
    meta_leaders: set[str] = set()
    if not args.include_meta:
        for f in (ROOT / "decks").glob("cardrush_*.json"):
            if f.name.endswith(".analysis.json"):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                if d.get("leader"):
                    meta_leaders.add(d["leader"])
            except Exception:
                continue

    # Acknowledged list: 「intrinsic 解決不能」 として severity 計算から除外する
    # card_id → set(issue_name) のマッピング。 db/audit_acknowledged.json に保存。
    ack_path = Path(__file__).resolve().parent.parent / "db" / "audit_acknowledged.json"
    acknowledged: dict[str, set[str]] = {}
    if ack_path.exists():
        ack_raw = json.loads(ack_path.read_text(encoding="utf-8"))
        for cid, issues in ack_raw.items():
            acknowledged[cid] = set(issues) if isinstance(issues, list) else set()

    rows: list[dict] = []
    for cid, card in cards.items():
        if cid in meta_leaders:
            continue
        effects = overlay.get(cid, [])
        qa_list = qa_by_card.get(cid, [])
        if not qa_list and not effects:
            continue
        issues = detect_issues(card, effects, qa_list)
        if not issues and not args.all:
            continue
        # acknowledged な issue を severity 計算から除外
        ack_set = acknowledged.get(cid, set())
        scoring_issues = [i for i in issues if i not in ack_set]
        severity = sum(issue_severity(i) for i in scoring_issues)
        rows.append({
            "card_id": cid,
            "name": card.get("name", ""),
            "category": card.get("category", ""),
            "cost": card.get("cost"),
            "power": card.get("power"),
            "text": card.get("text") or "",
            "effects": effects,
            "qa_list": qa_list,
            "issues": issues,
            "severity": severity,
        })

    rows.sort(key=lambda r: -r["severity"])

    # JSON 出力 (全件)
    OUTPUT_JSON.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Markdown 出力 (上位 N 件)
    out = OUTPUT_MD.open("w", encoding="utf-8")
    out.write(f"# Overlay vs FAQ 監査レポート\n\n")
    out.write(f"- 対象カード総数: {len(cards)}\n")
    out.write(f"- 突合対象 (overlay or FAQ あり): {len(rows)}\n")
    out.write(f"- メタリーダー除外: {len(meta_leaders)} 枚 (手書きで信頼度高)\n\n")
    out.write("## 凡例\n\n")
    out.write("- `missing_*`: 公式テキストに記載のキーワードが overlay の when に無い\n")
    out.write("- `*_condition_unmodeled`: 条件節が overlay の if に無い (弱シグナル: コードロジックで吸収されている可能性あり)\n")
    out.write("- `faq_attention_N`: 公式 FAQ で N 件以上言及 = 注目度高い\n")
    out.write("- `faq_negation`: FAQ に 「いいえ、できません」 を含む (= overlay が誤って許可している可能性)\n")
    out.write("- `vanilla_but_has_faq`: overlay 0 件なのに FAQ あり\n\n")
    out.write(f"## 上位 {args.top} 件 (severity 順)\n\n")

    for i, row in enumerate(rows[: args.top]):
        out.write(f"### {i+1}. `{row['card_id']}` {row['name']}  (severity={row['severity']})\n\n")
        out.write(f"- 種別: {row['category']} / コスト: {row['cost']} / パワー: {row['power']}\n")
        out.write(f"- 検出 issue: `{', '.join(row['issues'])}`\n\n")
        out.write(f"**公式テキスト:**\n\n```\n{row['text'] or '(なし)'}\n```\n\n")
        out.write(f"**Overlay ({len(row['effects'])} 件):**\n\n")
        if row["effects"]:
            out.write("```json\n")
            out.write(json.dumps(row["effects"], ensure_ascii=False, indent=2))
            out.write("\n```\n\n")
        else:
            out.write("(空)\n\n")
        out.write(f"**FAQ ({len(row['qa_list'])} 件):**\n\n")
        for qa in row["qa_list"][:5]:
            out.write(f"- Q: {qa['q']}\n  A: {qa['a']}\n")
        if len(row["qa_list"]) > 5:
            out.write(f"- ... (残り {len(row['qa_list']) - 5} 件は JSON 出力参照)\n")
        out.write("\n---\n\n")

    out.close()
    print(f"完了: {OUTPUT_MD} (上位 {min(args.top, len(rows))} 件)")
    print(f"     {OUTPUT_JSON} (全 {len(rows)} 件)")
    # severity 分布のサマリ
    from collections import Counter
    sev_buckets = Counter()
    for r in rows:
        if r["severity"] >= 10:
            sev_buckets["10+"] += 1
        elif r["severity"] >= 5:
            sev_buckets["5-9"] += 1
        elif r["severity"] >= 3:
            sev_buckets["3-4"] += 1
        elif r["severity"] >= 1:
            sev_buckets["1-2"] += 1
        else:
            sev_buckets["0"] += 1
    print(f"\n=== severity 分布 ===")
    for k in ("10+", "5-9", "3-4", "1-2", "0"):
        if sev_buckets.get(k):
            print(f"  {k}: {sev_buckets[k]} 件")


if __name__ == "__main__":
    main()
