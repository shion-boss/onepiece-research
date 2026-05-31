#!/usr/bin/env python3
"""公式テキスト ↔ overlay の キーワード整合性 detector (= inline 監査の検出可能部分をスケール)。

[[project_16deck_inline_audit_done]] で確立した bug 7 類型のうち、 **テキストに現れる動作語と
overlay の primitive 有無の食い違い**を programmatic に flag する。 全 4,072 効果カードを
「likely-bug (要 inline 読解)」 と「likely-ok」 に振り分け、 Claude の inline 監査を bug が
集中する側へ集中させるのが目的 (= 全数読解は多 session 要、 優先度付けで効率化)。

検出する主な mismatch:
- テキストに「KO/ドロー/登場/手札に加える/デッキの下/レスト/パワー増減/コスト増減/ライフ操作/
  ドン操作/サーチ/キーワード付与」 が有るのに、 対応 primitive family が overlay に無い (= type1/2/5)。
- テキストに「場合」 (= 状態条件) が有るのに overlay の どの entry にも if/conditions gate が無い
  (= type3 missing gate、 OP15-002/EB03-053 で踏んだ class)。

注意: heuristic なので false positive を含む (= 別表現での実装、 trigger 内包条件 等)。
flag は「優先的に inline で読め」 の意味であって「確定 bug」 ではない。

使い方:
  python scripts/audit_text_overlay_consistency.py            # 全カード、 db/audit_llm/consistency.json 出力
  python scripts/audit_text_overlay_consistency.py --top 60   # 上位 60 件を stdout 表示
  python scripts/audit_text_overlay_consistency.py --exclude-deck-pool  # 16-deck 済を除外
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "db" / "cards.json"
EFFECTS_PATH = ROOT / "db" / "card_effects.json"
DECKS_DIR = ROOT / "decks"
OUT_PATH = ROOT / "db" / "audit_llm" / "consistency.json"

# --- primitive family: テキスト動作語 → これらのいずれかが overlay にあれば OK ---
# engine/effects.py の authoritative primitive 名から網羅的に構成 (= 不完全 family による FP を排除)。
FAMILIES: dict[str, set[str]] = {
    # 「相手キャラをKOする」 効果。 bounce (return_to_*) や chara_to_life も「除去」 の代替表現。
    "KO": {"ko", "ko_multi", "ko_all_others", "ko_opp_stage", "ko_self_with_filter",
           "replace_ko_complex", "chara_to_self_life", "chara_to_opp_life",
           "return_to_hand", "return_to_hand_multi", "return_to_deck_bottom",
           "return_to_deck_bottom_multi"},
    "draw": {"draw", "draw_per_self_hand_discarded", "draw_per_hand_to_deck_bottom",
             "reveal_top_then", "reveal_top_play", "look_top_reorder"},
    # 「登場させる」 効果。 search_top_n は destination=field で登場、 summon_* も登場。
    "play": {"play_from_hand", "play_from_hand_choice", "play_from_hand_named_set",
             "play_from_hand_or_trash", "play_from_trash", "play_self", "play_self_from_trash",
             "summon_from_deck", "summon_stage_from_deck_with_feature", "search_top_n",
             "play_event_from_hand", "play_from_hand_named_with_dynamic_cost", "reveal_top_play"},
    # 「レストにする」 効果 (cost の rest_self も含む = cost 文脈の FP を吸収)。
    "rest": {"rest", "rest_multi", "rest_self_cards", "rest_self_cards_filtered",
             "rest_opp_don", "rest_self", "rest_self_don", "stay_rested_next_refresh"},
    # 「パワー+N/-N」 効果。 静的条件buff は execute_effect でなく静的recompute なので
    # 別途 power 検査からは外す (= flag 過多原因)。 ここは triggered pump のみ対象。
    "power": {"power_pump", "power_pump_multi", "power_pump_per_target_attached_don",
              "set_base_power_timed", "set_base_power_copy", "swap_opp_power",
              "reveal_self_life_top_pump_per_cost"},
    "keyword": {"give_keyword", "give_rush", "give_attack_active_chara"},
}

# テキスト動作語 → family。 高精度な動作語のみ採用 + 文脈除外で FP を抑える。
# trigger timing 「…した時」 / cost 「…できる：」「…する，」 で現れる動作語は効果ではないので除外。
TEXT_CHECKS: list[tuple[str, str, str]] = [
    ("KO", "KO", r"(相手|自分)の.{0,20}をKO(する|できる)"),
    ("draw", "draw", r"カードを?[0-9０-９]+枚引く|ドローする"),
    ("play", "play", r"登場させ(る|て|られ)"),
    ("keyword", "keyword",
     r"【速攻】を与え|【ブロッカー】を与え|【ダブルアタック】を与え|【バニッシュ】を与え|【KO耐性】を与え"),
]

# 状態条件 (= gate) を示すテキスト。 type3 missing-gate を高精度に拾う:
#  - action-result の「〜した場合」 (= then-clause) は除外。
#  - 静的 self-buff 「…の場合、このキャラは(パワー|コスト)…」 は静的recompute で扱うので除外。
# 静的 self-buff 文を除去してから 残り に状態条件 場合 が在るか判定する。
STATIC_BUFF_SENT = re.compile(r"[^。]*?の場合[、,]?\s*このキャラ(は|の)[^。]*?。")
STATE_COND_HINT = re.compile(
    r"(ライフ|手札|ドン[!！‼]{0,2}|トラッシュ|コスト[0-9０-９]|特徴《|リーダーが)"
    r".{0,18}(以上|以下|より|ある|いる|持つ|枚|多い|少な|である).{0,8}場合"
)


def _walk_keys(obj) -> set[str]:
    """overlay 構造を再帰的に walk し、 全 dict キーを集める (= primitive/condition 名の集合)。"""
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= _walk_keys(v)
    elif isinstance(obj, list):
        for x in obj:
            found |= _walk_keys(x)
    return found


def _has_gate(entries: list) -> bool:
    """overlay の どれかの entry が if / conditions gate を持つか。"""
    for e in entries or []:
        if isinstance(e, dict) and (e.get("if") or e.get("conditions")):
            return True
    return False


def load_deck_pool_ids() -> set[str]:
    ids: set[str] = set()
    for f in DECKS_DIR.glob("*.json"):
        if ".analysis." in f.name or ".target_v" in f.name:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("leader"):
            ids.add(d["leader"])
        for entry in d.get("main", []) or d.get("cards", []):
            cid = entry.get("card_id") if isinstance(entry, dict) else entry
            if cid:
                ids.add(cid)
    return ids


def audit() -> list[dict]:
    cards = {c["card_id"]: c for c in json.loads(CARDS_PATH.read_text(encoding="utf-8"))}
    effects = json.loads(EFFECTS_PATH.read_text(encoding="utf-8"))
    findings: list[dict] = []

    for cid, entries in effects.items():
        if not entries:  # vanilla = skip
            continue
        card = cards.get(cid)
        if not card:
            continue
        text = card.get("text") or ""
        if not text:
            continue
        keys = _walk_keys(entries)
        flags: list[str] = []

        # 1) 動作語 → primitive family の欠落
        for label, fam, pat in TEXT_CHECKS:
            if re.search(pat, text) and not (keys & FAMILIES[fam]):
                flags.append(f"text「{label}」あるが {fam} primitive 無し")

        # 2) 状態条件「<状態> が N 以上/以下 の場合」 あるが gate (if/conditions) 皆無。
        #    静的 self-buff 文を除去した残りで判定 (= 静的条件buff は静的recompute で扱う FP を排除)。
        text_no_static = STATIC_BUFF_SENT.sub("", text)
        if STATE_COND_HINT.search(text_no_static) and not _has_gate(entries):
            flags.append("text 状態条件「…の場合」あるが if/conditions gate 皆無 (= missing gate 濃厚)")

        if flags:
            findings.append({
                "card_id": cid,
                "name": card.get("name"),
                "category": card.get("category"),
                "score": len(flags),
                "flags": flags,
                "text": text,
            })

    findings.sort(key=lambda f: (-f["score"], f["card_id"]))
    return findings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0, help=">0 で 上位 N 件を stdout")
    ap.add_argument("--exclude-deck-pool", action="store_true",
                    help="16-deck pool の card を除外 (= 監査済)")
    args = ap.parse_args()

    findings = audit()
    if args.exclude_deck_pool:
        pool = load_deck_pool_ids()
        findings = [f for f in findings if f["card_id"] not in pool]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    from collections import Counter
    by_cat = Counter(f["category"] for f in findings)
    by_flagtype: Counter = Counter()
    for f in findings:
        for fl in f["flags"]:
            by_flagtype[fl.split(" ")[0] if "場合" not in fl else "場合-gate"] += 1
    print(f"flagged {len(findings)} 件 → {OUT_PATH.relative_to(ROOT)}")
    print(f"  category 別: {dict(by_cat)}")
    print(f"  score 別: {dict(Counter(f['score'] for f in findings))}")
    print(f"  flag 種別(冒頭): {dict(by_flagtype.most_common())}")
    if args.top:
        print(f"\n=== 上位 {args.top} ===")
        for f in findings[:args.top]:
            print(f"  [{f['score']}] {f['card_id']} {f['name']} ({f['category']})")
            for fl in f["flags"]:
                print(f"        - {fl}")


if __name__ == "__main__":
    main()
