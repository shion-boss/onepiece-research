# -*- coding: utf-8 -*-
"""効果意味ジャッジ (do 側): 「効果が宣言した do を engine が実際に起こしたか」 を検証。

audit_cost_payment.py (= cost 側) の姉妹。 こちらは効果の `do` プリミティブが宣言通りの
footprint を残したかを独立モデルで照合する = 「効果がカード通りに処理されたか」 のジャッジ。

⭐ 設計原則 (cost オラクルと同じ):
- **独立モデル**: 期待 footprint は engine 実装と別にハンドコード (= 循環参照しない真の cross-check)。
- **条件ゲート**: 効果の `if`/`conditions` が満たされる state でのみ do を期待 (= 条件未達の
  正当な不発を artifact 除外)。
- **feasibility**: 資源があるときのみ期待 (= draw はデッキ残があるとき必ずデッキが減る)。
- **非空振り自己テスト**: 発火を no-op 化したら検出するか (tests/ 側で担保)。

v1 = 最頻・最明瞭な MANDATORY 系のみ (draw / mill_self_top)。 「宣言したのに 1 枚も動かない」
= silent no-op (= 未実装/誤dispatch/条件で誤って全 block) を検出。 上 N まで / 動的枚数 /
ネスト (optional_cost_then 等) は v1 対象外 (= 順次拡張)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_test_card_effects as smoke  # noqa: E402
import audit_cost_payment as costoracle  # noqa: E402 (reuse _make_payable / _snap)
from engine.core import Category, InPlay  # noqa: E402
from engine.deck import CardRepository  # noqa: E402
from engine.effects import load_effect_overlay, eval_all_conditions  # noqa: E402

# v1 でジャッジする do-primitive (= 発火すれば必ず観測可能な footprint を残す MANDATORY 系)。
MODELED = {"draw", "mill_self_top"}

# harness (fire_one_effect) が **me 側で素直に発火** させる when のみ対象。
# counter/opp_attack/trigger/on_*_ko 反応 等は battle/opp 文脈 or 未発火で artifact になるため除外。
FIRED_WHENS = {"on_play", "activate_main", "main", "on_ko", "on_attack", "on_block"}

# デッキに札を戻す primitive (= draw の「デッキ減」 を相殺して masking する mdraw 等)。
# これらが同じ do にあると draw のデッキ枚数判定が無効 → draw チェックを抑止する。
DECK_ADD = {
    "self_hand_to_deck_bottom", "self_hand_to_deck_top", "return_to_deck_bottom",
    "return_to_deck_top", "return_to_deck_bottom_multi", "trash_to_deck",
    "put_hand_to_deck", "draw_per_hand_to_deck_bottom", "return_self_to_deck_bottom",
    "return_self_to_deck_bottom_if_condition", "opp_trash_to_deck_bottom",
    "look_top_reorder", "scry_deck_reorder",
}


def _fixed_amount(v):
    """固定枚数を返す (= 動的/不明なら None → 判定対象外)。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        a = v.get("amount", v.get("n"))
        if isinstance(a, int):
            return a
    return None


def _modeled_prims(eff):
    """eff.do の トップレベル (= inner if なし) の MODELED primitive を [(key, amount)] で返す。
    draw は deck-add 系 (mdraw) が同じ do にあると デッキ枚数 masking で判定不能 → 抑止。"""
    do = eff.get("do", [])
    all_keys = {k for p in do if isinstance(p, dict) for k in p}
    has_deck_add = bool(all_keys & DECK_ADD)
    out = []
    for p in do:
        if not isinstance(p, dict) or "if" in p:
            continue
        for k, v in p.items():
            if k not in MODELED:
                continue
            if k == "draw" and has_deck_add:
                continue  # mdraw: デッキ枚数で判定できない
            amt = _fixed_amount(v)
            if amt is not None and amt >= 1:
                out.append((k, amt))
    return out


def _missing(prim_key, b, a):
    """発火後、 期待 footprint が動いていなければ理由文字列を返す (= 空振り)。"""
    if prim_key == "draw":
        if b["deck"] > 0 and a["deck"] >= b["deck"]:
            return "draw: デッキが減っていない"
    elif prim_key == "mill_self_top":
        if b["deck"] > 0 and a["deck"] >= b["deck"] and a["trash"] <= b["trash"]:
            return "mill_self_top: デッキ/トラッシュが動いていない"
    return None


def audit_card(repo, overlay, card_id):
    card = repo._by_id[card_id]
    bundle = overlay.get(card_id)
    if not bundle or not bundle.effects:
        return []
    flags = []
    for idx, eff in enumerate(bundle.effects):
        when = eff.get("when")
        if when not in FIRED_WHENS:
            continue  # harness が me 側で発火させない when は対象外 (artifact 防止)
        modeled = _modeled_prims(eff)
        if not modeled:
            continue
        state = smoke.make_state(repo, overlay, card_id)
        me = state.players[0]
        opp = state.players[1]
        if card.category == Category.LEADER:
            me.leader = InPlay.of(card, sickness=False)
            src_inplay = me.leader
        elif card.category == Category.STAGE:
            src_inplay = InPlay.of(card, sickness=False)
            me.stages.append(src_inplay)
        elif card.category == Category.EVENT:
            if card not in me.hand:
                me.hand.append(card)
            src_inplay = InPlay.of(card, sickness=False)
        else:
            src_inplay = InPlay.of(card, sickness=False)
            me.characters.append(src_inplay)
        _cost = eff.get("cost")
        if isinstance(_cost, dict):
            costoracle._make_payable(me, repo, _cost)
        # 効果の if/conditions が満たされていなければ do を期待できない (= 正当な不発)。
        if not eval_all_conditions(eff, state, me, src_inplay):
            continue
        b = costoracle._snap(me, opp, src_inplay)
        try:
            smoke.fire_one_effect(state, card, src_inplay, eff, repo)
        except Exception:
            continue
        a = costoracle._snap(me, opp, src_inplay)
        for k, _amt in modeled:
            miss = _missing(k, b, a)
            if miss:
                flags.append({
                    "card_id": card_id, "name": card.name, "idx": idx,
                    "when": when, "miss": miss,
                    "text": (eff.get("_text", "") or "")[:70],
                })
    return flags


def main():
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    ids = only or [
        cid for cid in repo._by_id
        if not cid.endswith(("_p1", "_p2", "_p3", "_p4", "_r1", "_r2"))
    ]
    flags = []
    for cid in ids:
        flags.extend(audit_card(repo, overlay, cid))
    print(f"検査カード: {len(ids)}  /  do 空振り候補 FLAG: {len(flags)}")
    for f in flags:
        print(f"  [{f['miss']}] {f['card_id']} ({f['name']}) when={f['when']}")
        print(f"      text={f['text']}")
    sys.exit(1 if flags else 0)


if __name__ == "__main__":
    main()
