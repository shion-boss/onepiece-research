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

# ジャッジする do-primitive (= 発火すれば必ず観測可能な footprint を残す系)。
# 各 primitive は feasibility を確定 (= 資源/対象を注入) してから footprint を照合 → false positive ゼロ。
MODELED = {
    "draw", "mill_self_top",            # デッキ減 (v1)
    "add_don", "add_don_active", "add_rested_don",  # 場ドン増 (v2)
    "life_to_hand",                     # ライフ減 (v2)
}

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
    "look_top_reorder", "scry_deck_reorder", "hand_to_deck_bottom", "hand_to_deck_top",
}
# ライフを増やす primitive (= life_to_hand の「ライフ減」 を相殺して masking する)。
LIFE_ADD = {
    "put_top_to_life", "hand_to_self_life", "chara_to_self_life", "put_hand_to_life",
}
# 場のドンを減らす key (cost/do どちらも、 = add_don の「ドン増」 を相殺して masking する)。
DON_REMOVE = {"pay_don", "return_self_don_to_deck"}


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
    do_keys = {k for p in do if isinstance(p, dict) for k in p}
    cost_keys = set(eff.get("cost")) if isinstance(eff.get("cost"), dict) else set()
    has_deck_add = bool(do_keys & DECK_ADD)
    has_life_add = bool(do_keys & LIFE_ADD)
    has_don_remove = bool((do_keys | cost_keys) & DON_REMOVE)
    out = []
    for p in do:
        if not isinstance(p, dict) or "if" in p:
            continue
        for k, v in p.items():
            if k not in MODELED:
                continue
            # masking 抑止: cost/do の相殺 primitive があると 枚数判定が無効。
            if k == "draw" and has_deck_add:
                continue
            if k == "life_to_hand" and has_life_add:
                continue
            if k in ("add_don", "add_don_active", "add_rested_don") and has_don_remove:
                continue
            amt = _fixed_amount(v)
            if amt is not None and amt >= 1:
                out.append((k, amt))
    return out


def _make_do_feasible(me, opp, repo, do):
    """do primitive が実際に作用できるよう資源を注入 (= feasibility 確定で false positive 回避)。
    フィルタ無しで完全制御できる資源系のみ (= 対象選択系 ko/play は別途 confirm-or-skip)。"""
    keys = {k for p in do if isinstance(p, dict) for k in p}
    if keys & {"add_don", "add_don_active", "add_rested_don"}:
        # make_state は don_remaining=0 → add_don が作用できない。 ドンデッキに残を作る (total 10 維持)。
        me.don_remaining_in_deck = 5
        me.don_active = 3
        me.don_rested = 2
    # life_to_hand は make_state の life=4 で足りる (= 追加注入不要)。


def _missing(prim_key, b, a):
    """発火後、 期待 footprint が動いていなければ理由文字列を返す (= 空振り)。"""
    if prim_key == "draw":
        if b["deck"] > 0 and a["deck"] >= b["deck"]:
            return "draw: デッキが減っていない"
    elif prim_key == "mill_self_top":
        if b["deck"] > 0 and a["deck"] >= b["deck"] and a["trash"] <= b["trash"]:
            return "mill_self_top: デッキ/トラッシュが動いていない"
    elif prim_key in ("add_don", "add_don_active"):
        if b["don_deck"] > 0 and a["don_field"] <= b["don_field"]:
            return "add_don: 場のドンが増えていない"
    elif prim_key == "add_rested_don":
        if b["don_deck"] > 0 and a["don_rested"] <= b["don_rested"]:
            return "add_rested_don: レストドンが増えていない"
    elif prim_key == "life_to_hand":
        if b["life"] > 0 and a["life"] >= b["life"]:
            return "life_to_hand: ライフが減っていない"
    return None


# opp のキャラを場から退場させる primitive (= 発火後に opp.characters が減るはず)。
OPP_LEAVE_PRIMS = ("ko", "ko_multi", "return_to_hand", "return_to_hand_multi",
                   "return_to_deck_bottom", "chara_to_opp_life")


def _opp_leave_count(eff, state, me, opp, src):
    """do の ko/return 系が **opp 側に解決する対象数** を engine の resolver で求める。
    >0 なら fire 後に opp.characters が減るはず。 解決失敗/0 なら期待しない (= feasibility
    未確定では照合しない = false positive を出さない)。"""
    from engine.effects import _resolve_target
    n = 0
    for p in eff.get("do", []):
        if not isinstance(p, dict) or "if" in p:
            continue
        for k in OPP_LEAVE_PRIMS:
            if k not in p:
                continue
            v = p[k]
            try:
                targets = _resolve_target(v, state, me, opp, src,
                                          outer_kind=k, outer_value=v)
            except Exception:
                continue
            n += sum(1 for t in targets if t in opp.characters)
    return n


def _rest_opp_active_iids(eff, state, me, opp, src):
    """do の rest が opp 側に解決する **現在アクティブな** 対象の iid 集合 (= resolver で確定)。
    fire 後、 これらが (場に残るなら) rested になっているはず。"""
    from engine.effects import _resolve_target
    iids = set()
    for p in eff.get("do", []):
        if not isinstance(p, dict) or "if" in p or "rest" not in p:
            continue
        v = p["rest"]
        try:
            targets = _resolve_target(v, state, me, opp, src,
                                      outer_kind="rest", outer_value=v)
        except Exception:
            continue
        for t in targets:
            if t in opp.characters and not t.rested:
                iids.add(t.instance_id)
    return iids


def _power_pump_targets(eff, state, me, opp, src):
    """do の power_pump (固定 amount) の対象を resolver で確定し [(iid, power_before, sign)] を返す。
    fire 後、 その対象 (場に残れば) の power が sign 方向に動くはず。 amount 動的/0 は対象外。
    set_base_power 系で上書きされる do は masking 除外 (= 後段)。"""
    from engine.effects import _resolve_target
    out = []
    for p in eff.get("do", []):
        if not isinstance(p, dict) or "if" in p or "power_pump" not in p:
            continue
        spec = p["power_pump"]
        if not isinstance(spec, dict):
            continue
        amt = spec.get("amount")
        if not isinstance(amt, int) or amt == 0:
            continue
        tgt = spec.get("target")
        # 動的対象 (= 同 do の前段 primitive で対象プールが変わる) は fire 前解決と不一致になる
        # → 照合不能なので除外 (= false positive 回避)。 attached_don 依存が代表例 (OP15-015)。
        if isinstance(tgt, str) and "attached_don" in tgt:
            continue
        try:
            targets = _resolve_target(tgt, state, me, opp, src,
                                      outer_kind="power_pump", outer_value=tgt)
        except Exception:
            continue
        sign = 1 if amt > 0 else -1
        for t in targets:
            out.append((t.instance_id, t.power, sign))
    return out


# power_pump の符号デルタを打ち消しうる primitive (= masking → power_pump 照合を抑止)。
POWER_OVERRIDE = {"set_base_power", "set_base_power_timed", "set_base_power_copy",
                  "swap_opp_power", "power_pump_per_target_attached_don"}

_LEAD_BY_FEAT: dict = {}
_LEAD_BY_NAME: dict = {}


def _build_leader_maps(repo):
    if _LEAD_BY_FEAT:
        return
    for c in repo._by_id.values():
        if c.category == Category.LEADER:
            for f in (c.features or ()):
                _LEAD_BY_FEAT.setdefault(f, c)
            _LEAD_BY_NAME.setdefault(c.name, c)


def _satisfy_conditions(eff, state, me, opp, src, card, repo):
    """eff の if/conditions を満たすよう state を調整 (= leader/life/don/hand gate された効果も
    silent no-op 検査の対象にする)。 満たせたら True、 未対応条件は False (= 検査しない)。"""
    _build_leader_maps(repo)
    ifc = dict(eff.get("if") or {})
    for c in (eff.get("conditions") or []):
        if isinstance(c, dict):
            ifc.update(c)
    if not ifc:
        return True
    for k, v in ifc.items():
        if k in ("leader_feature", "leader_features_any", "leader_name"):
            if k == "leader_name":
                ld = _LEAD_BY_NAME.get(v)
            elif k == "leader_features_any":
                ld = next((_LEAD_BY_FEAT.get(f) for f in (v or []) if _LEAD_BY_FEAT.get(f)), None)
            else:
                ld = _LEAD_BY_FEAT.get(v)
            if ld is None:
                return False
            if card.category != Category.LEADER:
                me.leader = InPlay.of(ld, sickness=False)
        elif k == "self_life_le":
            me.life = me.life[:int(v)]
        elif k == "self_hand_count_le":
            n = int(v)
            keep = [c for c in me.hand if c is card][:1]  # source event は残す (main 発火に必要)
            others = [c for c in me.hand if c is not card]
            me.hand = keep + others[:max(0, n - len(keep))]
        elif k == "self_attached_don_ge":
            if src is not None:
                src.attached_dons = max(src.attached_dons, int(v))
        elif k == "opp_life_le":
            opp.life = opp.life[:int(v)]
        else:
            return False  # 未対応条件 → 諦める (= false positive を出さない)
    return eval_all_conditions(eff, state, me, src)


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
        do0 = eff.get("do", [])
        has_opp_leave = any(
            isinstance(p, dict) and "if" not in p and (set(p) & set(OPP_LEAVE_PRIMS))
            for p in do0)
        # 同 do 内で 相手キャラを「増やす」 primitive (OP13-119 の opp 報酬 force_opp_play_from_hand)
        # があると bounce が net-neutral になり opp_chars が減らない = ここは正常なので leave 判定を外す。
        _do_keys0 = {k for p in do0 if isinstance(p, dict) for k in p}
        if _do_keys0 & {"force_opp_play_from_hand"}:
            has_opp_leave = False
        has_rest = any(isinstance(p, dict) and "if" not in p and "rest" in p for p in do0)
        do_keys0 = {k for p in do0 if isinstance(p, dict) for k in p}
        has_pp = ("power_pump" in do_keys0) and not (do_keys0 & POWER_OVERRIDE)
        if not modeled and not has_opp_leave and not has_rest and not has_pp:
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
        _make_do_feasible(me, opp, repo, eff.get("do", []))
        # 効果の if/conditions が満たされていなければ、 充足できるなら満たして検査対象にする
        # (= leader/life/don gate された効果も silent no-op を検出。 充足不能なら skip)。
        if not eval_all_conditions(eff, state, me, src_inplay):
            if not _satisfy_conditions(eff, state, me, opp, src_inplay, card, repo):
                continue
        # ko/return: fire 前に engine resolver で opp 退場対象数を確定 (= cost 適用前の盤面で
        #     解決されるのと同じ。 ここでは cost が opp 盤面を変えないので一致する)。
        opp_leave_n = _opp_leave_count(eff, state, me, opp, src_inplay) if has_opp_leave else 0
        rest_iids = _rest_opp_active_iids(eff, state, me, opp, src_inplay) if has_rest else set()
        pp_targets = _power_pump_targets(eff, state, me, opp, src_inplay) if has_pp else []
        # ⚠ 公式 「**相手は**…する」 (bundle 直下 actor:"opp") は **相手の側** に作用する
        #   (cardqa_op_12、 OP12-075)。 me 基準で測ると 「空振り」 と誤判定するので陣営を入替える。
        _snap_me, _snap_opp = (opp, me) if eff.get("actor") == "opp" else (me, opp)
        b = costoracle._snap(_snap_me, _snap_opp, src_inplay)
        try:
            smoke.fire_one_effect(state, card, src_inplay, eff, repo)
        except Exception:
            continue
        a = costoracle._snap(_snap_me, _snap_opp, src_inplay)
        for k, _amt in modeled:
            miss = _missing(k, b, a)
            if miss:
                flags.append({
                    "card_id": card_id, "name": card.name, "idx": idx,
                    "when": when, "miss": miss,
                    "text": (eff.get("_text", "") or "")[:70],
                })
        # ko/return: 解決した opp 退場対象 ≥1 なら fire 後に opp.characters が減るはず。
        if opp_leave_n > 0 and a["opp_chars"] >= b["opp_chars"]:
            flags.append({
                "card_id": card_id, "name": card.name, "idx": idx,
                "when": when, "miss": f"ko/return: 相手キャラが減っていない (解決対象 {opp_leave_n})",
                "text": (eff.get("_text", "") or "")[:70],
            })
        # rest: 解決した opp アクティブ対象が、 場に残るなら rested になっているはず。
        if rest_iids:
            still_active = [t for t in opp.characters
                            if t.instance_id in rest_iids and not t.rested]
            if still_active:
                flags.append({
                    "card_id": card_id, "name": card.name, "idx": idx,
                    "when": when,
                    "miss": f"rest: 対象がレストされていない ({len(still_active)}/{len(rest_iids)})",
                    "text": (eff.get("_text", "") or "")[:70],
                })
        # power_pump: 解決した対象が (場に残れば) amount の符号方向に power が動くはず。
        if pp_targets:
            allip = {ip.instance_id: ip for ip in
                     [me.leader, *me.characters, *me.stages,
                      opp.leader, *opp.characters, *opp.stages]}
            for iid, pwr_before, sign in pp_targets:
                ip = allip.get(iid)
                if ip is None:
                    continue  # 対象が場を離れた → 照合不能
                delta = ip.power - pwr_before
                if (sign > 0 and delta <= 0) or (sign < 0 and delta >= 0):
                    flags.append({
                        "card_id": card_id, "name": card.name, "idx": idx,
                        "when": when,
                        "miss": f"power_pump: パワーが{'上' if sign > 0 else '下'}がっていない "
                                f"(delta={delta})",
                        "text": (eff.get("_text", "") or "")[:70],
                    })
                    break
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
