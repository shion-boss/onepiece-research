# -*- coding: utf-8 -*-
"""コスト支払いオラクル: 「効果は発火したのに コストが払われていない」 を全カード自動検出。

背景 (2026-06-04 ohtsuki 指摘「言われれば直せるのに発見できないのはおかしい」):
カード保存則 (fuzz INV1) や 召喚制約 (conformance) は コスト踏み倒しを **構造的に見逃す**
(= イベント捨てずにドロー しても カード総数は保存される)。 どの不変条件も「コスト支払いの
次元」 を検査していなかった。 → そこを検査する一般オラクルを作る。

方式: 各カードの cost 付き効果を、 コストが払える state で発火 → 効果が何か変えた
(signature 変化) のに 当該 cost の資源が cost 方向に動いていなければ FLAG。
これは「言われなくても」 コスト踏み倒し候補を機械が提案する = 発見の機械化。

FLAG は候補 (= 人間/LLM が verify)。 false negative (= 条件未達で発火せず) は許容、
原則 false positive は出さない (発火 + 資源不変 = 実際に踏み倒し)。 稀な masking
(cost で減らし do で同資源を足す) のみ手動確認。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import smoke_test_card_effects as smoke  # noqa: E402
from engine.core import Category, InPlay  # noqa: E402
from engine.deck import CardRepository  # noqa: E402
from engine.effects import load_effect_overlay, _matches_filter  # noqa: E402

# 検査対象の cost キー (= 観測可能な資源を消費するもの)。 reveal_*/once_per_turn は資源を
# 消費しない (情報コスト / フラグ) ので 支払い検査からは除外 (= payable にはする)。
RESOURCE_COST_KEYS = {
    "discard_hand", "discard_hand_with_filter", "discard_hand_or_trash_filtered_chara",
    "pay_don", "return_self_don_to_deck", "rest_self_don", "rest_self",
    "trash_self", "self_ko", "life_to_hand", "life_top_or_bottom_to_hand",
    "trash_to_deck", "return_self_to_hand", "return_self_chara_to_hand",
    "ko_self_with_filter", "rest_self_target_name", "rest_self_target",
}
SKIP_KEYS = {"once_per_turn", "reveal_hand_with_filter"}


def _snap(me, opp, src_inplay):
    return {
        "hand": len(me.hand),
        "don_field": me.don_active + me.don_rested,
        "don_active": me.don_active,
        "don_rested": me.don_rested,
        "don_deck": me.don_remaining_in_deck,
        "life": len(me.life),
        "trash": len(me.trash),
        "deck": len(me.deck),
        "src_rested": bool(src_inplay.rested) if src_inplay else None,
        "src_in_field": bool(src_inplay in me.characters or src_inplay in me.stages)
        if src_inplay else None,
        "n_chars": len(me.characters),
        "n_chars_rested": sum(1 for c in me.characters if c.rested),
        "opp_chars": len(opp.characters),
        "opp_life": len(opp.life),
        "opp_hand": len(opp.hand),
    }


def _do_fired(b, a):
    """効果の『do』 が実際に何かを起こしたか (= cost 支払いや source 除去とは別の盤面変化)。

    on_ko で harness が src を trash に移すと global signature は変わるが それは『do 発火』 では
    ない。 do の footprint (= 召喚で自場増 / draw で手札増&デッキ減 / 相手盤面変化 / ライフ変化) を
    見て、 条件未達で発火しなかったケースを除外する。
    """
    return (
        a["n_chars"] > b["n_chars"]      # 召喚 (自場増)
        or a["hand"] > b["hand"]          # draw/手札追加
        or a["deck"] < b["deck"]          # draw/サーチ/召喚 (デッキ減)
        or a["life"] != b["life"]         # ライフ操作
        or a["opp_chars"] != b["opp_chars"]   # 相手 KO/バウンス
        or a["opp_life"] != b["opp_life"]     # 相手ライフ操作
        or a["opp_hand"] != b["opp_hand"]     # 相手手札操作
    )


def _make_payable(me, repo, cost):
    """cost が払えるよう state に資源を足す (= filter 一致カードを手札/場に注入)。"""
    for key in ("discard_hand_with_filter", "reveal_hand_with_filter"):
        spec = cost.get(key)
        if isinstance(spec, dict):
            filt = spec.get("filter", {k: v for k, v in spec.items() if k != "count"})
            cnt = int(spec.get("count", 1))
            have = sum(1 for c in me.hand if _matches_filter(c, filt))
            if have < cnt:
                match = _find_card(repo, filt)
                if match:
                    me.hand.extend([match] * (cnt - have))
    cc = cost.get("discard_hand_or_trash_filtered_chara")
    if isinstance(cc, dict):
        filt = cc.get("filter", {})
        match = _find_card(repo, filt)
        if match:  # 手札に該当を1枚 (= 手札捨て側で払える)
            me.hand.append(match)
    kf = cost.get("ko_self_with_filter")
    if isinstance(kf, dict):
        match = _find_card(repo, kf)
        if match:
            me.characters.append(InPlay.of(match, sickness=False))
    rn = cost.get("rest_self_target_name") or cost.get("rest_self_target")
    if rn:
        name = rn.get("name") if isinstance(rn, dict) else str(rn)
        match = next((c for c in repo._by_id.values() if c.name == name
                      and c.category in (Category.CHARACTER, Category.STAGE)), None)
        if match:
            me.characters.append(InPlay.of(match, sickness=False))


def _find_card(repo, filt):
    for c in repo._by_id.values():
        if c.card_id.endswith(("_p1", "_p2", "_p3", "_r1", "_r2")):
            continue
        if _matches_filter(c, filt):
            return c
    return None


def _unpaid_keys(cost, b, a):
    """発火後、 各 cost キーが未払いのものを返す。

    ⚠ masking 対策: 「資源が cost 方向に純減したか」 ではなく **「捨て先/移動先が増えたか」**
    (= destination ベース) で見る。 例: discard_hand は do=draw で手札が純増するので 手札数では
    判定不能 → 捨て札の行き先 trash の増加で見る。 do が同じ destination を触る稀な masking
    のみ false negative (= 見逃し) で許容、 false positive は出さない方針。
    """
    u = []
    # discard 系: 手札 → trash。 trash が増えていなければ未払い (draw で手札純増しても誤検出しない)。
    if int(cost.get("discard_hand", 0)) > 0 and a["trash"] <= b["trash"]:
        u.append("discard_hand")
    if cost.get("discard_hand_with_filter") and a["trash"] <= b["trash"]:
        u.append("discard_hand_with_filter")
    if cost.get("discard_hand_or_trash_filtered_chara") and a["trash"] <= b["trash"]:
        u.append("discard_hand_or_trash_filtered_chara")
    # pay_don/return_don: 場のドン → ドンデッキ。 don_deck が増えていなければ未払い。
    if (int(cost.get("pay_don", 0)) > 0 or int(cost.get("return_self_don_to_deck", 0)) > 0) \
            and a["don_deck"] <= b["don_deck"]:
        u.append("pay_don/return_don")
    # rest_self_don: active → rested。 don_rested が増えていなければ未払い。
    if int(cost.get("rest_self_don", 0)) > 0 and a["don_rested"] <= b["don_rested"]:
        u.append("rest_self_don")
    # rest_self: source 自身がレストに (= 直接観測、 masking なし)。
    if cost.get("rest_self") and not b["src_rested"] and not a["src_rested"]:
        u.append("rest_self")
    # trash_self/self_ko/return_self: source が場から消える (= 直接観測、 masking なし)。
    if (cost.get("trash_self") or cost.get("self_ko")) and b["src_in_field"] and a["src_in_field"]:
        u.append("trash_self/self_ko")
    if cost.get("return_self_to_hand") and b["src_in_field"] and a["src_in_field"]:
        u.append("return_self_to_hand")
    # life 系: ライフ → 手札。 ライフが減っておらず **かつ** 手札も増えていなければ未払い。
    # ⚠ do が同ターンにライフを補充する (put_top_to_life / hand_to_self_life 等) と life 数は
    #   純変化 0 になり source 側 (life 減) では判定できない。 その場合 destination = 手札 の
    #   増加で payment を確認する (= 関数冒頭の destination ベース原則どおり)。 do の draw で
    #   手札が増えるケースは false negative (見逃し) となるが、 false positive は出さない方針
    #   (docstring)。 実例: OP15-109 ニコ・ロビン (cost=life_to_hand → do=put_top_to_life で
    #   ライフ補充 = life 純変化0 だが 手札はライフ由来カードで +1)。
    if (int(cost.get("life_to_hand", 0)) > 0 or int(cost.get("life_top_or_bottom_to_hand", 0)) > 0) \
            and a["life"] >= b["life"] and a["hand"] <= b["hand"]:
        u.append("life_cost")
    # trash_to_deck: trash → デッキ。 trash が減っていなければ未払い。
    if int(cost.get("trash_to_deck", 0)) > 0 and a["trash"] >= b["trash"]:
        u.append("trash_to_deck")
    # ko_self_with_filter: 自キャラ1体 KO。 自キャラ数が減っていなければ未払い (do の summon で
    # 相殺される masking は false negative 許容)。
    if cost.get("ko_self_with_filter") and a["n_chars"] >= b["n_chars"]:
        u.append("ko_self_with_filter")
    # rest_self_target_name: 自キャラ/ステージ1体レスト。 レスト数が増えていなければ未払い。
    if (cost.get("rest_self_target_name") or cost.get("rest_self_target")) \
            and a["n_chars_rested"] <= b["n_chars_rested"]:
        u.append("rest_self_target_name")
    return u


def audit_card(repo, overlay, card_id):
    card = repo._by_id[card_id]
    bundle = overlay.get(card_id)
    if not bundle or not bundle.effects:
        return []
    flags = []
    for idx, eff in enumerate(bundle.effects):
        cost = eff.get("cost")
        if not isinstance(cost, dict):
            continue
        if not (set(cost) & RESOURCE_COST_KEYS):
            continue  # 検査対象の資源コストなし (once_per_turn のみ等)
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
        _make_payable(me, repo, cost)
        # harness は trigger (ライフトリガー) を opp 側で発火する → actor は opp。
        when = eff.get("when")
        actor, actor_opp = (opp, me) if when == "trigger" else (me, opp)
        b = _snap(actor, actor_opp, src_inplay)
        try:
            smoke.fire_one_effect(state, card, src_inplay, eff, repo)
        except Exception:
            continue  # ERROR は smoke 側の責務、 ここでは無視
        a = _snap(actor, actor_opp, src_inplay)
        if not _do_fired(b, a):
            continue  # do が発火せず (条件未達等) → inconclusive (= cost も払わなくて正しい)
        unpaid = _unpaid_keys(cost, b, a)
        if unpaid:
            flags.append({
                "card_id": card_id, "name": card.name, "idx": idx,
                "when": eff.get("when"), "unpaid": unpaid,
                "cost": {k: cost[k] for k in cost if k != "once_per_turn"},
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
    all_flags = []
    for cid in ids:
        all_flags.extend(audit_card(repo, overlay, cid))
    print(f"検査カード: {len(ids)}  /  コスト踏み倒し候補 FLAG: {len(all_flags)}")
    for f in all_flags:
        print(f"  [{','.join(f['unpaid'])}] {f['card_id']} ({f['name']}) when={f['when']}")
        print(f"      cost={f['cost']}  text={f['text']}")
    sys.exit(1 if all_flags else 0)


if __name__ == "__main__":
    main()
