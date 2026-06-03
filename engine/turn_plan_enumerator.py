# -*- coding: utf-8 -*-
"""層1: ターンプラン網羅列挙 (= 2026-06-03、 [[project_superhuman_ai_distillation]] / 塊プラン)。

ohtsuki さん設計の 6 層パイプラインの土台。 現盤面 (= MAIN フェーズ開始) から、
そのターン DON 的に「出来ること」 = cost-feasible な行動列を**到達盤面で dedup** して
全列挙する。

## 爆発しない理由 (= ohtsuki 仮説、 ここで実測検証)

- DON は knapsack 制約 (= T ターン目は ~T DON) → 払えるカードの組合せが限定的。
- **「出来ること」 = 到達できる盤面の数**。 多くの行動順 (= play A→B vs B→A) は同じ盤面に
  至るので、 **transposition table (= 到達盤面の visited set)** で源泉から畳む。
- よって「プラン数 ≈ 到達可能な相異 MAIN 盤面の数」。 これを measure_enumeration で実測する。

## 抽象の境界線 (= role パラメータ化)

- 具体: 出すカードの card_id (= signature の一部)
- 抽象: 効果/攻撃の**対象** (= signature では iid を落とす)。 攻撃対象 role / 効果対象は
  層4 (plan_binding) で目標盤面に最も近づくよう束縛する。

## 第一カット (= 2026-06-03)

play/attach/activate/attack の**行動スケルトン**を列挙し、 到達盤面で dedup。
効果対象 (= KO する敵の role) の枝分かれは engine の auto-pick に委ね、 後続カットで
role パラメータ化する。 まず「スケルトン空間が爆発しないか」 を確定させる。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from .eval import compute_score
from .game import (
    AttachDonToCharacter,
    AttachDonToLeader,
    AttackCharacter,
    AttackLeader,
    ActivateMain,
    EndPhase,
    Phase,
    PlayCharacter,
    PlayEvent,
    PlayStage,
    legal_actions,
)
from .plan_search import _apply_with_defense, fast_clone


# ===========================================================================
# AbstractPlan
# ===========================================================================


@dataclass(frozen=True)
class AbstractPlan:
    """1 ターンの塊プラン (= 抽象スケルトン + 到達盤面)。

    Attributes:
        signature: 順序つき抽象トークン列 (= cascade で緩和可能)。 対象 iid は落とす。
            例: (("play","OP13-016"), ("attach_don","leader",1), ("attack","leader_face"))
        board_sig: 到達盤面の正準ハッシュ (= dedup / 同一性キー)。
        concrete_template: 実行用の具体 action 列 (= turn 開始 state から in-order 再生可能)。
            実 iid / hand_idx を含むので**この turn 開始 state でのみ**有効。 推論時は
            signature から plan_binding が再束縛する。
        cost_used: 消費 DON (= feasibility 確認 / 分析用)。
        depth: 行動数 (= EndPhase 除く)。
        eval_score: 到達盤面 (= canonical 束縛) の compute_score (= 層3 の value 補完用)。
            学習 bonus が無い局面で argmax の基準になる (= Q1「勝率bonus主 + 盤面value補完」)。
    """

    signature: tuple
    board_sig: tuple
    concrete_template: tuple
    cost_used: int
    depth: int
    eval_score: float = 0.0


# ===========================================================================
# 盤面正準署名 (= dedup 用、 axes より細かい「実盤面」)
# ===========================================================================


def _inplay_sig(ip: Any) -> tuple:
    """InPlay の正準タプル (= 順序非依存 dedup 用)。"""
    return (
        getattr(ip.card, "card_id", "?"),
        int(getattr(ip, "power", 0)),
        bool(getattr(ip, "rested", False)),
        int(getattr(ip, "attached_dons", 0)),
        bool(getattr(ip, "summoning_sickness", False)),
    )


def board_signature(state: Any, me_idx: int) -> tuple:
    """ターン中の意味ある盤面差を捉える正準署名 (= hashable)。

    両プレイヤーの leader/characters/don/life + 自分の手札 multiset を含む。
    自分の attack/除去 で opp 盤面が変わる、 play で自手札・自場・DON が変わる、 を全て反映。
    順序非依存にするため characters/hand は sorted。
    """
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    me_leader = (
        bool(getattr(me.leader, "rested", False)),
        int(getattr(me.leader, "attached_dons", 0)),
    )
    opp_leader = (bool(getattr(opp.leader, "rested", False)),)

    me_chars = tuple(sorted(_inplay_sig(c) for c in me.characters))
    opp_chars = tuple(sorted(_inplay_sig(c) for c in opp.characters))
    # 手札要素は CardDef 直 (= .card_id)。 InPlay (leader/characters) のみ .card を持つ。
    me_hand = tuple(sorted(c.card_id for c in me.hand))

    return (
        # me resources
        int(getattr(me, "don_active", 0)),
        int(getattr(me, "don_rested", 0)),
        len(me.life),
        me_leader,
        me_chars,
        me_hand,
        # opp board (= 自分の行動で変わる部分)
        len(opp.life),
        opp_leader,
        opp_chars,
        len(opp.hand),
        int(getattr(opp, "don_active", 0)),
    )


# ===========================================================================
# 抽象トークン (= concrete action + 現 state → 抽象 token)
# ===========================================================================


def _resolve_hand_card_id(state: Any, me_idx: int, hand_idx: int) -> Optional[str]:
    me = state.players[me_idx]
    if 0 <= hand_idx < len(me.hand):
        return me.hand[hand_idx].card_id  # 手札は CardDef 直
    return None


def _resolve_iid_card_id(state: Any, me_idx: int, iid: int) -> Optional[str]:
    me = state.players[me_idx]
    for ip in [me.leader, *me.characters]:
        if getattr(ip, "instance_id", None) == iid:
            return getattr(ip.card, "card_id", None)
    return None


def abstract_token(action: Any, state: Any, me_idx: int) -> tuple:
    """concrete action + その action を取る直前の state → 抽象トークン。

    対象 iid は落とす (= 抽象)。 攻撃は leader_face / enemy_chara の粗分類 (= role は後続カット)。
    """
    if isinstance(action, PlayCharacter):
        return ("play", _resolve_hand_card_id(state, me_idx, action.hand_idx))
    if isinstance(action, PlayEvent):
        return ("play", _resolve_hand_card_id(state, me_idx, action.hand_idx))
    if isinstance(action, PlayStage):
        return ("play", _resolve_hand_card_id(state, me_idx, action.hand_idx))
    if isinstance(action, AttachDonToLeader):
        return ("attach_don", "leader", int(action.n))
    if isinstance(action, AttachDonToCharacter):
        return ("attach_don", "chara", int(action.n))
    if isinstance(action, ActivateMain):
        # corpus snapshot は field に instance_id を持たず source_iid→card_id を解決できない。
        # corpus と一致させるため card 識別を落とした bare marker にする (= ActivateMain は少数)。
        return ("activate",)
    if isinstance(action, AttackLeader):
        return ("attack", "leader_face")
    if isinstance(action, AttackCharacter):
        return ("attack", "enemy_chara")
    return (action.__class__.__name__,)


# ===========================================================================
# 列挙本体
# ===========================================================================


def _is_main(state: Any, me_idx: int) -> bool:
    return (
        not state.game_over
        and state.phase == Phase.MAIN
        and state.turn_player_idx == me_idx
    )


def _unused_attached_don_penalty(child: Any, me_idx: int, plan: tuple,
                                 w_attached_don: float) -> float:
    """plan_search._unused_attached_don_penalty と同ロジック。

    attached DON は次の相手ターンで失効する (= +1000 が反映されない)。 plan 中で攻撃に
    使われていない (= 非 rested で attacker でない) キャラ/リーダーの attached DON は死に投資。
    board_eval の +W_ATTACHED_DON を帳消し + 追加 penalty で抑制 (= 「attach するなら attack も」)。

    これが無いと enumerate の max-board_eval プランが「DON 全部キャラに乗せて end」 の死に手に
    なる (= 2026-06-04 実測: 未適用で vs Greedy 2%)。
    """
    me = child.players[me_idx]
    attacked: set = set()
    for a in plan:
        if isinstance(a, (AttackLeader, AttackCharacter)):
            attacked.add(getattr(a, "attacker_iid", -1))
    wasted = 0
    for ip in [me.leader, *me.characters]:
        if getattr(ip, "attached_dons", 0) <= 0:
            continue
        if getattr(ip, "rested", False):
            continue  # rested = 攻撃済 = OK
        if getattr(ip, "instance_id", None) in attacked:
            continue
        wasted += ip.attached_dons
    return -wasted * (w_attached_don + 1000)


def enumerate_turn_plans(
    state: Any,
    me_idx: Optional[int] = None,
    *,
    defender_ai: Any = None,
    node_cap: int = 50000,
    max_depth: int = 14,
    prune_waste: bool = True,
) -> tuple[list[AbstractPlan], dict]:
    """MAIN フェーズ開始 state から cost-feasible な全プランを到達盤面 dedup で列挙。

    「到達可能な相異 MAIN 盤面」 = プラン集合 (= 各盤面から EndPhase で停止可能)。
    transposition table (= visited board_sig) で行動順の重複を源泉から畳む。

    Args:
        state: MAIN フェーズの GameState (= 副作用なく読むだけ、 内部で fast_clone)。
        me_idx: 手番プレイヤー (= None なら state.turn_player_idx)。
        defender_ai: 攻撃 sim 時に choose_defense を呼ぶ相手 AI (= None なら GreedyAI)。
        node_cap: 展開ノード上限 (= 爆発時の安全網、 hit したら capped=True)。
        max_depth: プラン最大長 (= EndPhase 除く行動数)。
        prune_waste: ai.prune_mechanical_waste で機械的悪手を除外。

    Returns:
        (plans, stats):
          plans = list[AbstractPlan] (= 到達盤面で dedup 済、 turn 開始盤面自体は除く)。
          stats = {"distinct_boards", "nodes_expanded", "capped", "start_legal"}。
    """
    if me_idx is None:
        me_idx = state.turn_player_idx

    if defender_ai is None:
        from .ai import GreedyAI

        defender_ai = GreedyAI(rng=getattr(state, "rng", None))

    if prune_waste:
        from .ai import prune_mechanical_waste
    else:
        prune_mechanical_waste = None  # type: ignore

    start = fast_clone(state)
    if not _is_main(start, me_idx):
        return [], {"distinct_boards": 0, "nodes_expanded": 0, "capped": False,
                    "start_legal": 0}

    start_don = int(getattr(start.players[me_idx], "don_active", 0))
    # plan-level penalty 用 W (= 1 回だけ取得)
    try:
        from .eval import BoardEvalWeights
        _w_adon = float(BoardEvalWeights().W_ATTACHED_DON)
    except Exception:
        _w_adon = 400.0

    # === multiset signature dedup (= 2026-06-03 実測知見) ===
    # 2 つの爆発を実測で切り分け:
    #  - board dedup: 可換な行動順 (= attach 順 / play 順) は畳むが、 **束縛変種** (= どの char に
    #    DON / どの敵を攻撃) で高turn 数千 fine 盤面に膨らむ。
    #  - ordered-sig dedup: 可換順を畳まず permutation で 40k に爆発。
    #  - **multiset signature** (= 順序非依存 token 多重集合) が唯一安定 (T4=59/T6=167/T8≈600-950)。
    # multiset = 「このターン出来ることの網羅」 そのもの (= ohtsuki vision)。 順序は (a) 多くは
    # legality で強制 (= searcher を先に出す等)、 (b) 残りは層5 execution / 層4 binding が最適化。
    # → **multiset を dedup 鍵** = clone 前に skip で高速 + library 規模が turn 不問で数百。
    visited_keys: set = {frozenset_count(())}  # 既出の multiset key (= 空 = 開始盤面)
    # out: multiset_key → (canonical_ordered_sig, concrete_template, board_sig, cost_used, depth)
    out: dict[frozenset, tuple] = {}
    board_sigs: set = set()

    q: deque = deque()
    q.append((start, (), ()))  # (state, concrete_plan, ordered_abstract_sig)
    nodes = 0
    capped = False
    start_legal = len(legal_actions(start))

    while q:
        cur, plan, sig = q.popleft()
        if len(plan) >= max_depth:
            continue
        la = legal_actions(cur)
        if prune_mechanical_waste is not None:
            la = prune_mechanical_waste(cur, la)
        for action in la:
            if isinstance(action, EndPhase):
                continue  # EndPhase = 停止 (= 各 multiset から常に可能、 展開不要)
            token = abstract_token(action, cur, me_idx)
            new_sig = sig + (token,)
            mkey = frozenset_count(new_sig)
            if mkey in visited_keys:
                continue  # multiset transposition: clone 前に skip (= 可換順 + 重複束縛を畳む)
            if nodes >= node_cap:
                capped = True
                break
            child = fast_clone(cur)
            try:
                _apply_with_defense(child, action, defender_ai)
            except Exception:
                continue
            nodes += 1
            # turn が opp に渡った / game_over = 終端 (= MAIN 中 attack で通常 turn は変わらない)。
            if child.game_over or child.turn_player_idx != me_idx or child.phase != Phase.MAIN:
                continue
            visited_keys.add(mkey)
            new_plan = plan + (action,)
            bsig = board_signature(child, me_idx)
            board_sigs.add(bsig)
            cost_used = start_don - int(getattr(child.players[me_idx], "don_active", 0))
            try:
                escore = float(compute_score(child, me_idx))
                escore += _unused_attached_don_penalty(child, me_idx, new_plan, _w_adon)
            except Exception:
                escore = 0.0
            out[mkey] = (new_sig, new_plan, bsig, cost_used, len(new_plan), escore)
            q.append((child, new_plan, new_sig))
        if capped:
            break

    plans: list[AbstractPlan] = []
    for mkey, (sig, plan, bsig, cost_used, depth, escore) in out.items():
        plans.append(
            AbstractPlan(
                signature=sig,
                board_sig=bsig,
                concrete_template=plan,
                cost_used=cost_used,
                depth=depth,
                eval_score=escore,
            )
        )

    stats = {
        "distinct_plans": len(plans),            # = multiset plan 種類数 (= library 規模)
        "distinct_multiset_sigs": len(plans),
        "distinct_boards": len(board_sigs),      # canonical 束縛での到達 fine 盤面数 (参考)
        "nodes_expanded": nodes,
        "capped": capped,
        "start_legal": start_legal,
    }
    return plans, stats


def frozenset_count(signature: tuple) -> frozenset:
    """順序非依存の multiset 鍵 (= token, count のペア集合)。"""
    from collections import Counter

    return frozenset(Counter(signature).items())
