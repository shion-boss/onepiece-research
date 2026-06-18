# -*- coding: utf-8 -*-
"""そのターンに「できること」を全て洗い出す列挙器 (= 2026-06-18、 ohtsuki さん要望)。

2 つの独立した関数:

- `enumerate_turn_offense(state, me_idx)`:
    自分のターンの**攻撃側**の全行動ライン (= プレイ / DON付与 / 起動 / 各キャラ・リーダーの
    攻撃する/しない) を **順序つき** で列挙。 同じ到達盤面に至る並べ替えは 1 つに畳む
    (= transposition prune、 順序依存で結果が変わる手は別ラインで残る)。 効果の対象・任意選択は
    **抽象化** (= engine auto-pick、 enumerate_turn_plans と同方針)。 既定で **相手はリーダーのみ**
    に縮小 (= 「相手状態なし」、 攻撃先 = 相手リーダー、 ブロッカー/カウンターなし)。

- `enumerate_turn_defense(state, me_idx, incoming_attacks)`:
    相手の攻撃集合 (= incoming_attacks) を入力に、 自分の**守備側**の全組合せ
    (= 各攻撃へのブロッカー割当 × カウンター(手札の counter 値 / カウンターイベント)) を列挙。

どちらも `node_cap` で安全弁 (= 到達したら capped=True)。 中盤の多 DON ターンは順序まで数えると
組合せが膨らむため cap で頭打ちする。

CLI: PYTHONPATH=. .venv/bin/python -m engine.turn_action_enumerator --deck cardrush_1478 --turn 5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Optional

from .game import (
    ActivateMain,
    AttachDonToCharacter,
    AttachDonToLeader,
    AttackCharacter,
    AttackLeader,
    EndPhase,
    Phase,
    PlayCharacter,
    PlayEvent,
    PlayStage,
    legal_actions,
)
from .turn_plan_enumerator import board_signature, fast_clone, _apply_with_defense, _is_main


# =========================================================================== #
# 出力データ型
# =========================================================================== #
@dataclass(frozen=True)
class TurnLine:
    """攻撃側の 1 ライン (= ターン終了可能な 1 到達盤面への順序つき行動列)。"""
    actions: tuple          # 順序つきトークン列。 例: (("play","OP14-102"),("attack","OP13-042→leader"))
    cost_used: int          # 消費 DON
    n_attacks: int          # 攻撃回数
    depth: int              # 行動数


@dataclass(frozen=True)
class DefensePlan:
    """守備側の 1 組合せ (= 各 incoming attack への対応)。"""
    decisions: tuple        # 各攻撃の (target, "take"|"block:<cid>", counters:tuple)
    blockers_used: tuple    # 使ったブロッカー card_id
    counters_used: tuple    # 使ったカウンター card_id (手札)


# =========================================================================== #
# 攻撃者・対象を含むトークン (= abstract_token と違い「どのキャラが攻撃か」を保持)
# =========================================================================== #
def _iid_card_id(state: Any, me_idx: int, iid: int) -> str:
    me = state.players[me_idx]
    for ip in [me.leader, *me.characters, *me.stages]:
        if getattr(ip, "instance_id", None) == iid:
            return getattr(ip.card, "card_id", "?")
    opp = state.players[1 - me_idx]
    for ip in [opp.leader, *opp.characters]:
        if getattr(ip, "instance_id", None) == iid:
            return "opp:" + getattr(ip.card, "card_id", "?")
    return "?"


def offense_token(action: Any, state: Any, me_idx: int) -> tuple:
    """攻撃側 action → 順序つき出力用トークン (= 攻撃者 card_id を含む)。"""
    me = state.players[me_idx]
    if isinstance(action, (PlayCharacter, PlayEvent, PlayStage)):
        i = action.hand_idx
        cid = me.hand[i].card_id if 0 <= i < len(me.hand) else "?"
        return ("play", cid)
    if isinstance(action, AttachDonToLeader):
        return ("don→leader", int(action.n))
    if isinstance(action, AttachDonToCharacter):
        return ("don→" + _iid_card_id(state, me_idx, action.target_iid), int(action.n))
    if isinstance(action, ActivateMain):
        return ("activate", _iid_card_id(state, me_idx, action.source_iid))
    if isinstance(action, AttackLeader):
        return ("attack", _iid_card_id(state, me_idx, action.attacker_iid) + "→leader")
    if isinstance(action, AttackCharacter):
        atk = _iid_card_id(state, me_idx, action.attacker_iid)
        tgt = _iid_card_id(state, me_idx, action.target_iid)
        return ("attack", f"{atk}→{tgt}")
    return (action.__class__.__name__,)


# =========================================================================== #
# 攻撃側 列挙
# =========================================================================== #
def _minimize_opponent(state: Any, me_idx: int) -> None:
    """相手をリーダーのみに縮小 (= 「相手状態なし」)。 攻撃先=相手リーダー、 ブロッカー/カウンターなし。
    ライフは残す (= 攻撃が通ると減る差分を到達盤面 dedup で捉えるため)。"""
    opp = state.players[1 - me_idx]
    opp.characters = []
    opp.stages = []
    opp.hand = []


def enumerate_turn_offense(
    state: Any,
    me_idx: Optional[int] = None,
    *,
    ignore_opponent: bool = True,
    node_cap: int = 20000,
    max_depth: int = 24,
    prune_waste: bool = False,
    defender_ai: Any = None,
) -> tuple[list[TurnLine], dict]:
    """MAIN フェーズ state から、 そのターンの攻撃側の全ラインを順序つき・到達盤面 dedup で列挙。

    Returns: (lines, stats)。 lines は空ライン (= パス) を含む。

    prune_waste (= 既定 False): 「全部洗い出す」 が目的なので既定は**剪定なし** = 全合法手を列挙
    (= 2000キャラ→5000リーダー の無駄攻撃や各 DON 付与分配も「できること」として含む =
    「各キャラの攻撃するしない」 を完全網羅)。 True にすると ai.prune_mechanical_waste で
    機械的悪手 (= 確定失敗攻撃 / 無駄 DON 付与 / 過剰イベント) を除いた軽量ビューになるが、
    打点の立たない攻撃が消える点に注意。
    """
    if me_idx is None:
        me_idx = state.turn_player_idx
    if defender_ai is None:
        from .ai import GreedyAI
        defender_ai = GreedyAI(rng=getattr(state, "rng", None))
    prune_fn = None
    if prune_waste:
        from .ai import prune_mechanical_waste
        prune_fn = prune_mechanical_waste

    start = fast_clone(state)
    if ignore_opponent:
        _minimize_opponent(start, me_idx)
    if not _is_main(start, me_idx):
        return [], {"distinct": 0, "nodes": 0, "capped": False, "reason": "not_main"}

    start_don = int(getattr(start.players[me_idx], "don_active", 0))
    visited: set = set()
    lines: list[TurnLine] = []
    nodes = [0]
    capped = [False]

    def record(cur: Any, path: tuple) -> None:
        cost_used = start_don - int(getattr(cur.players[me_idx], "don_active", 0))
        n_atk = sum(1 for t in path if t and t[0] == "attack")
        lines.append(TurnLine(actions=path, cost_used=cost_used, n_attacks=n_atk, depth=len(path)))

    def dfs(cur: Any, path: tuple) -> None:
        bsig = board_signature(cur, me_idx)
        if bsig in visited:
            return  # transposition: 同じ到達盤面 = 同結果 → 1 ラインに畳む
        visited.add(bsig)
        record(cur, path)
        if len(path) >= max_depth:
            return
        la = legal_actions(cur)
        if prune_fn is not None:
            la = prune_fn(cur, la)
        for action in la:
            if isinstance(action, EndPhase):
                continue
            if nodes[0] >= node_cap:
                capped[0] = True
                return
            child = fast_clone(cur)
            try:
                _apply_with_defense(child, action, defender_ai)
            except Exception:
                continue
            nodes[0] += 1
            if child.game_over or child.turn_player_idx != me_idx or child.phase != Phase.MAIN:
                continue
            dfs(child, path + (offense_token(action, cur, me_idx),))
            if capped[0]:
                return

    dfs(start, ())
    stats = {"distinct": len(lines), "nodes": nodes[0], "capped": capped[0],
             "start_don": start_don}
    return lines, stats


# =========================================================================== #
# 守備側 列挙
# =========================================================================== #
def _available_blockers(state: Any, me_idx: int) -> list:
    me = state.players[me_idx]
    return [
        c for c in me.characters
        if not getattr(c, "rested", False)
        and getattr(c, "is_blocker_now", False)
        and not getattr(c, "blocker_disabled_until_turn_end", False)
    ]


def _available_counters(state: Any, me_idx: int) -> tuple[list, list]:
    """(counter_cards, counter_events): 手札の counter 値持ち / カウンターイベント。"""
    me = state.players[me_idx]
    overlay = getattr(state, "effects_overlay", None) or {}
    don = int(getattr(me, "don_active", 0))
    cards, events = [], []
    for i, c in enumerate(me.hand):
        cval = int(c.counter) if getattr(c, "counter", 0) else 0
        if cval > 0:
            cards.append((i, c.card_id, cval))
        if str(getattr(c, "category", "")).endswith("EVENT") and int(getattr(c, "cost", 0)) <= don:
            bundle = overlay.get(c.card_id)
            eff_list = getattr(bundle, "effects", bundle) if bundle is not None else []
            if isinstance(eff_list, list) and any(
                isinstance(e, dict) and e.get("when") == "counter" for e in eff_list
            ):
                events.append((i, c.card_id))
    return cards, events


def enumerate_turn_defense(
    state: Any,
    me_idx: Optional[int] = None,
    incoming_attacks: Optional[list] = None,
    *,
    node_cap: int = 20000,
    max_counters_per_attack: int = 3,
) -> tuple[list[DefensePlan], dict]:
    """相手の攻撃集合 incoming_attacks を入力に、 守備の全組合せを列挙。

    incoming_attacks: [{"target": "leader"|<defender char card_id>, "power": int}, ...] (= 攻撃順)。
    各攻撃へ: ブロッカー割当 (= 使用可能ブロッカーの各々 or no-block) × 適用カウンター部分集合。
    ブロッカー/カウンターは 1 度使うと消費 (= 攻撃間で資源競合)。
    """
    if me_idx is None:
        me_idx = state.turn_player_idx
    incoming_attacks = list(incoming_attacks or [])

    blockers = [(b.instance_id, b.card.card_id) for b in _available_blockers(state, me_idx)]
    counter_cards, counter_events = _available_counters(state, me_idx)
    all_counters = [(i, cid) for (i, cid, _v) in counter_cards] + counter_events

    plans: list[DefensePlan] = []
    nodes = [0]
    capped = [False]

    def dfs(ai: int, used_blk: frozenset, used_ctr: frozenset, acc: tuple) -> None:
        if capped[0]:
            return
        if ai >= len(incoming_attacks):
            plans.append(DefensePlan(
                decisions=acc,
                blockers_used=tuple(sorted(cid for (iid, cid) in blockers if iid in used_blk)),
                counters_used=tuple(sorted(cid for (i, cid) in all_counters if i in used_ctr)),
            ))
            return
        atk = incoming_attacks[ai]
        tgt = atk.get("target", "leader")
        avail_blk = [(iid, cid) for (iid, cid) in blockers if iid not in used_blk]
        avail_ctr = [(i, cid) for (i, cid) in all_counters if i not in used_ctr]
        # この攻撃に適用するカウンター部分集合 (= 0..max_counters_per_attack 枚)
        ctr_subsets: list[tuple] = [()]
        for k in range(1, min(max_counters_per_attack, len(avail_ctr)) + 1):
            ctr_subsets.extend(combinations(avail_ctr, k))
        block_opts = [None] + avail_blk  # no-block or 各ブロッカー
        for ctr in ctr_subsets:
            for blk in block_opts:
                if nodes[0] >= node_cap:
                    capped[0] = True
                    return
                nodes[0] += 1
                ctr_ids = tuple(cid for (_i, cid) in ctr)
                if blk is None:
                    label = "take"
                else:
                    label = f"block:{blk[1]}"
                decision = (tgt, label, ctr_ids)
                dfs(
                    ai + 1,
                    used_blk | ({blk[0]} if blk is not None else frozenset()),
                    used_ctr | {i for (i, _cid) in ctr},
                    acc + (decision,),
                )

    dfs(0, frozenset(), frozenset(), ())
    stats = {"distinct": len(plans), "nodes": nodes[0], "capped": capped[0],
             "n_blockers": len(blockers), "n_counters": len(all_counters),
             "n_attacks": len(incoming_attacks)}
    return plans, stats


# =========================================================================== #
# CLI / デモ
# =========================================================================== #
def _demo() -> None:
    import argparse
    import random
    from .deck import CardRepository, DeckList
    from .game import setup_game, play_until_main, advance_phase
    from .effects import load_effect_overlay
    from .ai import GreedyAI, play_one_action

    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1478")
    ap.add_argument("--opp", default="cardrush_1342")
    ap.add_argument("--turn", type=int, default=5, help="この turn_number の自分 MAIN まで進める")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--prune", action="store_true",
                    help="機械的悪手を剪定した軽量ビュー (= 既定は全列挙)")
    args = ap.parse_args()

    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    me = DeckList.from_json(f"decks/{args.deck}.json", repo)
    opp = DeckList.from_json(f"decks/{args.opp}.json", repo)
    rng = random.Random(args.seed)
    st = setup_game(me, opp, rng=rng, first_player=0, effects_overlay=overlay,
                    do_mulligan_and_finalize=True)
    play_until_main(st)
    ai = GreedyAI(rng=rng)
    guard = 0
    # 目標 turn の 自分(P0) MAIN まで両者 greedy で進める
    while not st.game_over and not (st.turn_number == args.turn
                                    and st.turn_player_idx == 0 and st.phase == Phase.MAIN):
        guard += 1
        if guard > 2000:
            break
        if st.phase == Phase.MAIN:
            play_one_action(st, ai, ai)
        else:
            advance_phase(st)

    print(f"deck={me.name} turn={st.turn_number} P0 MAIN | "
          f"DON={st.players[0].don_active} hand={len(st.players[0].hand)} "
          f"chars={len(st.players[0].characters)}")
    lines, stats = enumerate_turn_offense(st, 0, prune_waste=args.prune)
    print(f"\n=== 攻撃側 (相手リーダーのみ、 {'剪定' if args.prune else '全列挙'}) ===")
    print(f"  distinct ライン数: {stats['distinct']} | nodes={stats['nodes']} capped={stats['capped']}")
    shown = sorted(lines, key=lambda l: (l.depth, l.actions))[: args.show]
    for i, ln in enumerate(shown):
        seq = "パス" if not ln.actions else " → ".join(
            (f"{t[1]}出す" if t[0] == "play" else
             f"攻撃[{t[1]}]" if t[0] == "attack" else
             f"{t[0]}{t[1] if len(t) > 1 else ''}") for t in ln.actions)
        print(f"  {i+1:2}. (cost{ln.cost_used}, atk{ln.n_attacks}) {seq}")

    # 守備デモ: リーダーへ 6000 攻撃 1 本が来た想定
    print(f"\n=== 守備側 (例: リーダーに6000攻撃が1本) ===")
    dplans, dstats = enumerate_turn_defense(
        st, 0, [{"target": "leader", "power": 6000}])
    print(f"  使用可能ブロッカー={dstats['n_blockers']} カウンター={dstats['n_counters']} "
          f"→ 組合せ={dstats['distinct']} capped={dstats['capped']}")
    for i, dp in enumerate(dplans[: args.show]):
        print(f"  {i+1:2}. {dp.decisions}")


if __name__ == "__main__":
    _demo()
