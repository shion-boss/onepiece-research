#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式テキストを **節 (clause) 単位** に割り、 各節に対応する primitive が overlay に有るか監査する。

なぜ要るか (= 既存監査との違い):
  `audit_text_overlay_consistency.py` は 「テキストに動作語が有るのに overlay に primitive が無い」
  を **カード単位** で見る。 そのため 「【登場時】A。 **その後**、 B」 の B だけが落ちていても、
  A の primitive がカードのどこかに有れば **flag されない**。

  2026-08-11 の pending 消化で、 まさにこの型の欠落が **4 回** 出た:
    - OP10-116 電磁砲   … 「ライフの上から1枚までを見て、 ライフの上か下に置く」 が丸ごと欠落
    - OP04-081 / OP04-091 … 「その後、 自分のデッキの上から2枚をトラッシュに置く」 が欠落
    - OP10-119 / OP12-031 … 「その後、 …レストのドン‼N枚までを、 付与する」 が欠落
    - OP08-114 S-ホーク  … 【ドン‼×1】の静的効果 (斬耐性 + パワー+2000) が丸ごと欠落
  実測: 既存監査は この 7 枚のうち **2 枚しか flag しない** (しかも別理由の 「場合-gate」)。
  → 節単位で見る監査を分けて持つ。

やり方:
  1. text / trigger を 【マーカー】 で **効果ブロック** に割り、 マーカーを when にマップする。
  2. ブロックを 「。」 と 「その後、」 で **節** に割る。 括弧内のリマインダーは落とす。
  3. 各節から **動作語** を拾い、 期待する primitive family を決める (曖昧な節は見ない)。
  4. その when を持つ overlay entry の primitive キーを **入れ子ごと** 全部集める
     (do / cost / optional_cost_then / conditional / choice_effect / then / effect …)。
  5. 期待 family が 1 つも無ければ flag。

⚠ これは **ヒューリスティック**。 flag は 「読むべき候補」 であって確定バグではない。
   逆に flag されないことは正しさを保証しない (= 計器の穴)。 誤検出を減らすため
   **動作語が 1 種類だけ確実に取れる節** に限って判定する。

Run:
  .venv/bin/python scripts/audit_text_clause_coverage.py            # サマリ + 上位
  .venv/bin/python scripts/audit_text_clause_coverage.py --all      # 全件
  .venv/bin/python scripts/audit_text_clause_coverage.py --card OP10-119
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "db" / "cards.json"
OVERLAY = ROOT / "db" / "card_effects.json"
OUT = ROOT / "db" / "audit_text_clause_coverage.json"

# 【マーカー】 → overlay の when。 同じマーカーが複数 when に割れる場合は集合で持つ。
MARKER_WHEN: dict[str, set[str]] = {
    "登場時": {"on_play"},
    "アタック時": {"on_attack"},
    "ブロック時": {"on_block"},
    "KO時": {"on_ko"},
    "相手のアタック時": {"opp_attack", "opp_attack_on_leader", "opp_attack_on_chara"},
    "起動メイン": {"activate_main"},
    "メイン": {"main"},
    "カウンター": {"counter"},
    "トリガー": {"trigger"},
    "自分のターン終了時": {"end_of_turn"},
    "相手のターン終了時": {"opp_end_of_turn"},
    "ターン終了時": {"end_of_turn", "opp_end_of_turn"},
    "自分のターン開始時": {"on_turn_start"},
    "相手のターン開始時": {"opp_turn_start"},
    "ドン!!×1": {"on_attached_don"},
    "ドン‼×1": {"on_attached_don"},
    "ドン!!×2": {"on_attached_don"},
    "ドン‼×2": {"on_attached_don"},
}
# 静的効果 (マーカー無し / 【自分のターン中】等) は on_attached_don entry に載る規約。
STATIC_WHENS = {"on_attached_don", "in_hand", "setup_modifier"}

# 動作語 → 期待 primitive family。 ⚠ 曖昧な語は入れない (誤検出が増えるだけ)。
FAMILIES: list[tuple[str, str, set[str]]] = [
    # (family 名, 節に現れる正規表現, 許容する primitive キーの部分文字列集合)
    ("KO", r"KOする|KOし、|KOできる|、KOする", {"ko"}),
    ("draw", r"カード\d+枚を引く|カードを引く|枚を引く", {"draw"}),
    ("mill_deck", r"デッキの上から\d+枚(まで)?を、?トラッシュに置く",
     {"mill_self_top", "mill", "trash_self_deck"}),
    ("to_deck_bottom", r"デッキの下に置く|デッキの一番下に置く",
     {"deck_bottom", "trash_to_deck", "return_to_deck", "search_top_n", "scry", "reveal"}),
    ("rest", r"レストにする|レストにし、", {"rest", "stay_rested", "keep_opp_rested"}),
    ("untap", r"アクティブにする", {"untap", "add_don", "attach_active"}),
    ("play", r"登場させる|登場させてもよい|レストで登場させる",
     {"play_", "summon_from_deck", "reveal_top_play", "force_opp_play"}),
    ("return_hand", r"持ち主の手札に戻す|手札に戻す", {"return_to_hand", "return_self_to_hand"}),
    ("attach_don", r"ドン‼?\d*枚(まで)?を、?\s*付与する|ドン!!\d*枚(まで)?を、?\s*付与する",
     {"attach_don", "attach_rested_don", "attach_active_don", "attach_opp_don"}),
    ("add_don", r"ドン‼?デッキからドン‼?\d+枚(まで)?を|ドン!!デッキからドン!!\d+枚(まで)?を",
     {"add_don", "add_rested_don"}),
    ("life_add", r"ライフの上に(表向きで|裏向きで)?加える",
     {"put_top_to_life", "hand_to_self_life", "chara_to_self_life", "hand_or_trash_to_self_life",
      # デッキから直接ライフへ入れる形は search_top_n(destination=life/life_face_up)
      "search_top_n",
      # 「相手の」 ライフへ置く形 (OP04-097 お玉)
      "chara_to_opp_life"}),
    ("life_look", r"ライフの上から\d+枚(まで)?を見て|ライフすべてを見て",
     {"scry", "peek", "life_top_or_bottom", "mill_opp_life", "life_to_hand",
      "view_life_top_choose_position"}),
    ("face_down", r"裏向きにする", {"face_down"}),
    ("keyword", r"【(速攻|ブロッカー|ダブルアタック|バニッシュ|ブロック不可)】を得る",
     {"give_keyword", "give_rush", "give_attack_active"}),
    ("power", r"パワー[+\-−]\d+", {"power_pump", "set_base_power"}),
    ("cost_mod", r"コスト[+\-−]\d+", {"cost_minus", "set_base_cost", "cost_plus"}),
]

# 節から落とす: 括弧内のリマインダー / キーワード単独宣言
PAREN = re.compile(r"[(（][^)）]*[)）]")
MARKER = re.compile(r"【([^】]+)】")


def _strip_reminder(text: str) -> str:
    return PAREN.sub("", text or "")


def _blocks(text: str) -> list[tuple[set[str], str]]:
    """テキストを 【マーカー】 で効果ブロックに割る。 返り値 = [(when 候補集合, 本文)]。

    マーカーが連続する場合 (【ドン‼×1】【アタック時】) は **最後のトリガー系** を when にする
    (前置きは gate)。 マーカーが無い先頭部分は静的効果扱い。
    """
    text = _strip_reminder(text)
    out: list[tuple[set[str], str]] = []
    pos = 0
    pending: set[str] = set()
    cur_start = 0
    marks = list(MARKER.finditer(text))
    if not marks:
        return [(STATIC_WHENS, text)] if text.strip() else []
    for i, m in enumerate(marks):
        if i == 0 and m.start() > 0:
            head = text[: m.start()].strip()
            if head:
                out.append((set(STATIC_WHENS), head))
        name = m.group(1)
        whens = MARKER_WHEN.get(name)
        # 「【登場時】効果」 のような **参照** は トリガーではない
        after = text[m.end(): m.end() + 2]
        if whens and not after.startswith("効果"):
            pending |= whens
        # 次のマーカーまでが本文
        nxt = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end(): nxt].strip()
        if body:
            out.append((set(pending) if pending else set(STATIC_WHENS), body))
            pending = set()
        pos = nxt
        cur_start = pos
    return out


def _clauses(body: str) -> list[str]:
    """効果本文を節に割る (「。」 と 「その後、」)。"""
    parts: list[str] = []
    for sent in re.split(r"。", body):
        sent = sent.strip()
        if not sent:
            continue
        for c in re.split(r"その後、", sent):
            c = c.strip("、 　")
            if c:
                parts.append(c)
    return parts


def _all_prim_keys(obj) -> set[str]:
    """overlay entry から primitive キーを **入れ子ごと** 全部集める。"""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in ("_text", "_doc", "when", "n"):
                keys.add(k)
            keys |= _all_prim_keys(v)
    elif isinstance(obj, list):
        for x in obj:
            keys |= _all_prim_keys(x)
    return keys


def _families_of(clause: str) -> list[str]:
    hits = [name for name, pat, _ in FAMILIES if re.search(pat, clause)]
    return hits


def audit(cards: list[dict], overlay: dict) -> list[dict]:
    flags: list[dict] = []
    fam_keys = {name: keys for name, _p, keys in FAMILIES}
    for c in cards:
        cid = c["card_id"]
        entries = overlay.get(cid)
        if not isinstance(entries, list) or not entries:
            continue
        for field in ("text", "trigger"):
            raw = c.get(field) or ""
            if not raw.strip() or raw.strip() == "-":
                continue
            for whens, body in _blocks(raw):
                if field == "trigger":
                    whens = {"trigger"}
                # 該当 when の entry のみを見る。
                # ⚠ ただし **マーカーの無いブロック** (= 静的効果扱い) は、 実際には
                #   「〜した時、〜」 の散文トリガー (on_ko / opp_event_played /
                #   on_self_don_returned_to_deck …) であることが多く、 when を一意に決められない。
                #   そこだけは **カード全体** を見る (= 誤検出を避ける。 2026-08-11 実測で
                #   この扱いを外すと flag が 55 → 151 に膨らみ、 増分はほぼ全部これだった)。
                ents = [e for e in entries if isinstance(e, dict) and e.get("when") in whens]
                if whens == set(STATIC_WHENS):
                    scope = entries
                else:
                    scope = ents
                have = _all_prim_keys(scope)
                # 「他の効果を発動する」 系は 中身が別 entry / 別カードにあるので判定不能 → skip
                if have & {"fire_self_effect", "fire_effect_of", "copy_effect"}:
                    continue
                for clause in _clauses(body):
                    fams = _families_of(clause)
                    # ⚠ 動作語が 1 種類だけ確実に取れる節に限る (誤検出を減らす)
                    if len(fams) != 1:
                        continue
                    fam = fams[0]
                    want = fam_keys[fam]
                    if any(any(w in k for w in want) for k in have):
                        continue
                    flags.append({
                        "card_id": cid, "name": c.get("name"), "field": field,
                        "when": sorted(whens), "family": fam, "clause": clause[:90],
                        "have": sorted(have)[:12],
                        "entry_when": sorted({e.get("when") for e in scope if isinstance(e, dict)}),
                    })
    return flags


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全件表示")
    ap.add_argument("--card", help="1 枚だけ調べる")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--overlay", help="別の overlay JSON で検査 (= 校正用。 修正前の版で "
                                      "既知バグを検出できるか確かめる)")
    args = ap.parse_args()

    cards = json.loads(CARDS.read_text(encoding="utf-8"))
    overlay = json.loads(Path(args.overlay).read_text(encoding="utf-8")
                         if args.overlay else OVERLAY.read_text(encoding="utf-8"))
    if args.card:
        cards = [c for c in cards if c["card_id"].startswith(args.card)]
    flags = audit(cards, overlay)

    # パラレルは 1 枚に畳む (同じテキスト = 同じ判定)
    seen: set[tuple] = set()
    uniq: list[dict] = []
    for f in flags:
        base = re.sub(r"_[pr]\d$", "", f["card_id"])
        key = (base, f["family"], f["clause"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append({**f, "card_id": base})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"flags": uniq}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"節カバレッジ監査: flag {len(uniq)} 件 (ユニークカード "
          f"{len({f['card_id'] for f in uniq})} 枚) → {OUT}")
    print("  family 別:", dict(Counter(f["family"] for f in uniq).most_common()))
    show = uniq if args.all else uniq[: args.top]
    for f in show:
        print(f"\n  {f['card_id']} {f['name']} [{f['field']}/{','.join(f['when'])}] "
              f"family={f['family']}")
        print(f"    節: 「{f['clause']}」")
        print(f"    overlay entry when={f['entry_when']}  keys={f['have']}")


if __name__ == "__main__":
    main()
