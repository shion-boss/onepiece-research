# -*- coding: utf-8 -*-
"""ターン1「できる動き」全パターン列挙 (= 選択分岐まで展開)。

ohtsuki さんの問い「青黄ナミ デッキ 1ターン目にできる動きは全てで何パターンあるか」を
**効果の対象・任意選択まで別パターンとして展開**して確定算出する一回性の解析スクリプト。

定義: 1「パターン」= 自分のターンを終える時点で到達しうる相異なる盤面
  (= 出すカードの組合せ + 各効果の対象選択 / 任意Yes-No / どの手札をライフに等の分岐を全展開)。
  → 異なる選択は異なる盤面に至るので自然に別パターン、 同一結果に至る選択順は畳まれる。

機構: engine は「AI=自動pick / 人間=PauseSignal で候補提示」。ナミ側を「人間」にした
  HumanSession を、 行動 (= play) と choice (= 対象/任意) の両 pause で全 pick DFS 展開し、
  各 action-pause (= ここでターン終了可能) の到達盤面 signature を集合に貯める。

mechanical waste の DON 付与 (= ターン1はバトル不可ゆえ無意味) は「動き」に数えない (= 除外)。

usage: .venv/bin/python scripts/enumerate_turn1_lines.py --deck cardrush_1478 --seeds 200
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter

from engine.deck import CardRepository, DeckList
from engine.game import legal_actions
from engine.human_session import HumanSession
from engine.ai import GreedyAI
from engine.effects import load_effect_overlay


# --------------------------------------------------------------------------- #
# 到達盤面 signature (= ターン終了時点で意味ある差を全部捉える)
# --------------------------------------------------------------------------- #
def _ip_sig(ip):
    return (
        getattr(ip.card, "card_id", "?"),
        int(getattr(ip, "power", 0)),
        bool(getattr(ip, "rested", False)),
        int(getattr(ip, "attached_dons", 0)),
        bool(getattr(ip, "summoning_sickness", False)),
    )


def end_board_signature(state, me_idx):
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]
    return (
        # 自分: 手札 multiset / 場 / DON / ライフ枚数 / リーダー付与DON
        tuple(sorted(c.card_id for c in me.hand)),
        tuple(sorted(_ip_sig(c) for c in me.characters)),
        int(getattr(me, "don_active", 0)),
        int(getattr(me, "don_rested", 0)),
        len(me.life),
        int(getattr(me.leader, "attached_dons", 0)),
        # 相手: 場 / ライフ枚数 (= KO や手札→ライフ等の波及を捉える)
        tuple(sorted(_ip_sig(c) for c in opp.characters)),
        len(opp.life),
        tuple(sorted(c.card_id for c in opp.hand)),
    )


# --------------------------------------------------------------------------- #
# choice pause → 試す picks 候補 (= 全分岐)。 無効な picks は DFS 側で skip。
# --------------------------------------------------------------------------- #
def candidate_picks(payload):
    kind = payload.get("kind")
    cands = payload.get("candidates")
    if kind == "optional_cost_confirm":
        return [[0], [1]]  # やらない / やる
    if cands is None:
        # candidates 無し確認系 → yes/no 的に両方試す
        return [[0], [1], []]
    n = len(cands)
    picks = [[]]  # 「何も選ばない / スキップ」 (= 任意 / 上限まで の枝)
    picks += [[i] for i in range(n)]  # 各単一候補
    return picks


# --------------------------------------------------------------------------- #
# play 行動 index (= PlayCharacter/Event/Stage のみ。 AttachDon/EndPhase は除外)
# --------------------------------------------------------------------------- #
PLAY_TYPES = {"PlayCharacter", "PlayEvent", "PlayStage"}


def play_action_indices(state):
    out = []
    for i, a in enumerate(legal_actions(state)):
        if type(a).__name__ in PLAY_TYPES:
            out.append((i, a))
    return out


# --------------------------------------------------------------------------- #
# DFS: 人間ターン中の全ライン → 到達盤面集合
# --------------------------------------------------------------------------- #
def _choice_token(payload, picks):
    kind = payload.get("kind")
    cands = payload.get("candidates") or []
    if kind == "optional_cost_confirm":
        return ("opt", "yes" if picks == [1] else "no")
    if not picks:
        return (kind, "none")
    chosen = tuple(
        (cands[i].get("card_id") or cands[i].get("name") or str(cands[i]))
        for i in picks if 0 <= i < len(cands)
    )
    return (kind, chosen)


def enumerate_lines(session, me_idx, patterns, node_cap=20000, _nodes=None, path=()):
    """patterns: dict[board_sig -> token_path]。 各 action-pause の到達盤面を記録。"""
    if _nodes is None:
        _nodes = [0]
    if session.state.game_over:
        return
    pk = session.pending_kind
    if pk == "action":
        sig = end_board_signature(session.state, me_idx)
        if sig not in patterns:
            patterns[sig] = path  # 代表トークン列 (= 最初に到達したもの)
        for idx, a in play_action_indices(session.state):
            if _nodes[0] >= node_cap:
                return
            _nodes[0] += 1
            cid = session.state.players[me_idx].hand[a.hand_idx].card_id
            child = copy.deepcopy(session)
            try:
                child.apply_human_action(idx)
            except Exception:
                continue
            enumerate_lines(child, me_idx, patterns, node_cap, _nodes,
                            path + (("play", cid),))
    elif pk == "choice":
        payload = session.pending_payload or {}
        for picks in candidate_picks(payload):
            if _nodes[0] >= node_cap:
                return
            _nodes[0] += 1
            child = copy.deepcopy(session)
            try:
                child.apply_human_choice(picks)
            except Exception:
                continue
            enumerate_lines(child, me_idx, patterns, node_cap, _nodes,
                            path + (_choice_token(payload, picks),))
    # それ以外 (defense/game_over/None) = 人間ターン外 → 終端


# --------------------------------------------------------------------------- #
def build_session(nami, opp, overlay, seed, human_first):
    ai_factory = lambda rng, ana=None: GreedyAI(rng=rng)
    s = HumanSession(nami, opp, ai_factory, seed=seed,
                     effects_overlay=overlay, human_first=human_first)
    s.apply_human_choice([0])  # マリガン keep → 人間 MAIN まで進む (後攻なら相手 turn1 消化込み)
    return s


def run_side(nami, opp, overlay, human_first, seeds):
    label = "先攻 (turn1, 1DON)" if human_first else "後攻 (turn2, 2DON)"
    per_hand = []          # seed ごとの distinct パターン数
    breakdown = Counter()  # 出せた play カード別の出現手札数
    opp_target_seen = 0
    best = None            # (n, seed, hand_ids, patterns_dict) = 最大パターンの手札
    for seed in range(seeds):
        s = build_session(nami, opp, overlay, seed, human_first)
        if s.state.game_over or s.pending_kind != "action":
            continue
        me = s.human_idx
        if not human_first:
            if any(getattr(c.card, "cost", 99) is not None and
                   getattr(c.card, "cost", 99) <= 5 for c in s.state.players[1 - me].characters):
                opp_target_seen += 1
        for _i, a in play_action_indices(s.state):
            breakdown[s.state.players[me].hand[a.hand_idx].card_id] += 1
        hand_ids = sorted(c.card_id for c in s.state.players[me].hand)
        patterns = {}
        enumerate_lines(s, me, patterns)
        n = len(patterns)
        per_hand.append(n)
        if best is None or n > best[0]:
            best = (n, seed, hand_ids, patterns)
    per_hand.sort()
    print(f"==== {label} ====")
    print(f"  解析手札数 (= seeds 到達): {len(per_hand)}")
    if per_hand:
        mn, mx = per_hand[0], per_hand[-1]
        med = per_hand[len(per_hand) // 2]
        print(f"  1手札あたり distinct パターン数 (= 選択展開込み): min={mn} median={med} max={mx}")
        dist = Counter(per_hand)
        print("  分布 (パターン数 -> 手札数): " +
              ", ".join(f"{k}:{dist[k]}" for k in sorted(dist)))
    if not human_first:
        print(f"  相手に KO 可能キャラが居た手札: {opp_target_seen}/{len(per_hand)} "
              f"(= ゼウス KO 分岐が立つ前提)")
    print(f"  出せた play カード内訳 (出現手札数): " +
          ", ".join(f"{cid}:{breakdown[cid]}" for cid, _ in breakdown.most_common()))
    if best is not None:
        n, seed, hand_ids, patterns = best
        print(f"  --- 最大手札の全パターン catalog (seed={seed}, n={n}) ---")
        print(f"      手札: {hand_ids}")
        for i, (sig, path) in enumerate(sorted(patterns.items(),
                                               key=lambda kv: (len(kv[1]), str(kv[1])))):
            desc = "パス(何もしない)" if not path else " → ".join(
                (f"{t[1]}出す" if t[0] == "play" else f"[{t[0]}:{t[1]}]") for t in path)
            print(f"      {i+1:2}. {desc}")
    print()
    return per_hand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1478")
    ap.add_argument("--opp", default="cardrush_1342")
    ap.add_argument("--seeds", type=int, default=200)
    args = ap.parse_args()

    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    nami = DeckList.from_json(f"decks/{args.deck}.json", repo)
    opp = DeckList.from_json(f"decks/{args.opp}.json", repo)
    print(f"deck={nami.name} ({args.deck}) leader={nami.leader.card_id} vs opp={args.opp}")
    print(f"seeds={args.seeds}\n")

    run_side(nami, opp, overlay, human_first=True, seeds=args.seeds)
    run_side(nami, opp, overlay, human_first=False, seeds=args.seeds)


if __name__ == "__main__":
    main()
