# -*- coding: utf-8 -*-
"""Claude (= 私) が ExploitBeam と 1 手ずつ対戦する CLI。 ミラー対戦専用。

私が「人間」の位置 (deck_a / human_idx) に座り、 盤面と合法手を読んで手を選ぶ。
ExploitBeam (= SmartOpponentAI) の手番は自動。 状態は db/claude_play/session.pkl に
保存し、 コマンドごとに 1 手進める (= Claude Code は 1 コマンド = 1 観測 のため)。

AI (SmartOpponentAI / HumanAI) は session 参照や GBM を含むため pickle から除外し、
load 時に meta.json の deck slug から再注入する (= state/rng/pending だけ永続化)。

  start [--deck SLUG] [--first|--second|--random] [--seed N]
  show
  mulligan keep|redraw|ok
  move <idx>
  choice [<idx> ...]
  defense <blocker_iid|none> [--counter <hand_idx> ...]
  counter-event <hand_idx>
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import pickle
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (
    AttachDonToCharacter,
    AttachDonToLeader,
    AttackCharacter,
    AttackLeader,
    legal_actions,
)
from engine.human_session import HumanAI, HumanSession
from engine.llm_player_ai import LLMPlayerAI
from engine.smart_opponent_ai import SmartOpponentAI  # noqa: F401 (後方互換: 旧 mirror session)
from engine.exploit_beam_ai import ExploitBeamAI
import engine.core as _core

STATE = ROOT / "db" / "claude_play" / "session.pkl"
META = ROOT / "db" / "claude_play" / "meta.json"


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _load_deck(slug: str, repo: CardRepository):
    p = ROOT / "decks" / f"{slug}.json"
    if not p.exists():
        raise SystemExit(f"deck not found: {p}")
    return make_deck_from_dict(json.loads(p.read_text(encoding="utf-8")), repo)


def _load_analysis(slug: str):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _opp_ai(rng, opp_slug: str):
    """対戦相手 = 配備 ExploitBeam (per-deck GBM + analysis、 gauntlet/matrix と同一構成)。
    set_ai_opp は呼ばない (= matrix/gauntlet の ExploitBeam は内部 greedy opp model を使う = 同条件)。"""
    ana = _load_analysis(opp_slug)
    return ExploitBeamAI(rng=rng, deck_analysis={**(ana or {}), "deck_slug": opp_slug})


def _attach_ai(session: HumanSession, opp_slug: str) -> None:
    """対戦相手 ExploitBeam + HumanAI を session に (再)注入。 opp_slug = AI 側のデッキ (非ミラー可)。"""
    session.ai = _opp_ai(session.rng, opp_slug)
    session.human_ai = HumanAI(session)


def _peek_next_iid() -> int:
    """engine.core._iid (グローバル itertools.count) の次値を消費せず覗く。"""
    v = next(_core._iid)
    _core._iid = itertools.count(v)
    return v


def _save(session: HumanSession) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    ai, hai = session.ai, session.human_ai
    session.ai = None
    session.human_ai = None
    try:
        with open(STATE, "wb") as f:
            pickle.dump(session, f)
    finally:
        session.ai, session.human_ai = ai, hai
    # instance_id カウンタ (engine.core._iid グローバル) はプロセス終了で消える。
    # meta に次値を保存し load 時に復元 → 1 コマンド 1 プロセスでも iid 連続 (衝突防止)。
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    meta["next_iid"] = _peek_next_iid()
    META.write_text(json.dumps(meta), encoding="utf-8")


def _load() -> HumanSession:
    if not STATE.exists():
        raise SystemExit("no active game. run `start` first.")
    meta = json.loads(META.read_text(encoding="utf-8"))
    if "next_iid" in meta:
        _core._iid = itertools.count(meta["next_iid"])
    with open(STATE, "rb") as f:
        session = pickle.load(f)
    _attach_ai(session, meta.get("opp", meta["deck"]))
    return session


# --------------------------------------------------------------------------- #
# iid ベースの安全なアクション解決 (= 番号ずれ防止、 2026-06-08 1戦目の操作ミス対策)
# --------------------------------------------------------------------------- #
def _leader_iid(session: HumanSession) -> int:
    return session.state.players[session.human_idx].leader.instance_id


# --------------------------------------------------------------------------- #
# divergence ロギング (= 2026-06-12): 私(強プレイ) の手 vs 配備 ExploitBeam の手 を
# 各 MAIN 決定で記録 → AI の系統的盲点を後で機械抽出 (= heuristic 8修正の systematic 版)。
# session.ai (= SmartOpponentAI→ExploitBeam) を 同 state に 通すだけ (= state 復元不要・正確)。
# --------------------------------------------------------------------------- #
def _act_sig(state, human_idx: int, a) -> str:
    """action を card_id / iid ベースの正準シグネチャに (= hand_idx 並べ替えに頑健、 比較用)。"""
    t = type(a).__name__
    hand = state.players[human_idx].hand
    hi = getattr(a, "hand_idx", None)
    card = hand[hi].card_id if (hi is not None and 0 <= hi < len(hand)) else None
    if t == "AttackLeader":
        return f"AttackLeader(atk={getattr(a,'attacker_iid',None)})"
    if t == "AttackCharacter":
        return f"AttackCharacter(atk={getattr(a,'attacker_iid',None)},tgt={getattr(a,'target_iid',None)})"
    if t in ("PlayCharacter", "PlayEvent", "PlayStage"):
        return f"{t}({card})"
    if t in ("AttachDonToLeader", "AttachDonToCharacter"):
        return f"{t}(tgt={getattr(a,'target_iid','leader')})"
    if t == "ActivateMain":
        return f"ActivateMain(src={getattr(a,'source_iid',None)},e={getattr(a,'effect_index',None)})"
    return t


def _record_divergence(session: HumanSession, idx: int) -> None:
    # 既定 OFF (= 1手毎に my-side ExploitBeam を回すので重い)。 ONEPIECE_DIVLOG=1 で有効化。
    if not os.environ.get("ONEPIECE_DIVLOG"):
        return
    st = session.state
    try:
        from engine.core import Phase
        from engine.game import legal_actions
        from engine.plan_search import fast_clone
        if st.game_over or st.phase != Phase.MAIN or st.turn_player_idx != session.human_idx:
            return
        acts = legal_actions(st)
        if not (0 <= idx < len(acts)):
            return
        meta0 = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
        my_slug = meta0.get("deck", "unknown")
        # 私のデッキ (croc) を 配備 ExploitBeam が操縦したら何を選ぶか = 私の手との差 = AI 改善の信号
        ref_ai = _opp_ai(random.Random(0), my_slug)
        my_act = acts[idx]
        ai_act = ref_ai.choose_action(fast_clone(st))
        my_sig = _act_sig(st, session.human_idx, my_act)
        ai_sig = _act_sig(st, session.human_idx, ai_act)
        me = st.players[session.human_idx]; opp = st.players[1 - session.human_idx]
        rec = {
            "turn": st.turn_number, "my": my_sig, "ai": ai_sig, "agree": my_sig == ai_sig,
            "n_legal": len(acts),
            "board": {"my_life": len(me.life), "opp_life": len(opp.life),
                      "my_hand": len(me.hand), "opp_hand": len(opp.hand),
                      "my_don": me.don_active, "my_field": len(me.characters),
                      "opp_field": len(opp.characters)},
        }
        meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
        slug = meta.get("deck", "unknown")
        path = ROOT / "db" / "claude_play" / f"divergence_{slug}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # divergence ロギングはベストエフォート (= 対戦を止めない)


def _find_don_idx(session: HumanSession, iid: str):
    """iid (= leader iid or キャラ iid) への DON+1 アクション idx を返す。"""
    actions = legal_actions(session.state)
    lid = _leader_iid(session)
    for i, a in enumerate(actions):
        if isinstance(a, AttachDonToLeader) and int(iid) == lid:
            return i
        if isinstance(a, AttachDonToCharacter) and a.target_iid == int(iid):
            return i
    return None


def _find_attack_idx(session: HumanSession, attacker_iid: int, target: str):
    """attacker_iid が target (= "leader" or 相手キャラ iid) を攻撃する idx を返す。"""
    actions = legal_actions(session.state)
    for i, a in enumerate(actions):
        if isinstance(a, AttackLeader) and a.attacker_iid == attacker_iid and target == "leader":
            return i
        if (
            isinstance(a, AttackCharacter)
            and a.attacker_iid == attacker_iid
            and str(a.target_iid) == str(target)
        ):
            return i
    return None


# --------------------------------------------------------------------------- #
# 私視点 (human_idx 固定) の盤面 + pending 表示
# --------------------------------------------------------------------------- #
def _render(session: HumanSession) -> None:
    R = LLMPlayerAI(rng=random.Random(0))  # render 専用 (LLM は呼ばない)
    st = session.state
    me = st.players[session.human_idx]
    opp = st.players[session.ai_idx]

    print()
    print(R._render_side("[私 Claude]", me, hidden_hand=False))
    print(R._render_side("[ExploitBeam]", opp, hidden_hand=True))
    ph = getattr(st.phase, "name", st.phase)
    first = "私" if session.human_idx == 0 else "ExploitBeam"
    print(f"-- ターン{st.turn_number} phase={ph} 先攻={first}")

    if st.game_over:
        w = st.winner
        who = (
            "私(Claude)"
            if w == session.human_idx
            else ("ExploitBeam" if w == session.ai_idx else "引き分け/時間切れ")
        )
        print(f"\n*** ゲーム終了: 勝者 = {who} (turn {st.turn_number}) ***")
        return

    pk = session.pending_kind
    pp = session.pending_payload or {}
    print()
    if pk == "choice":
        kind = pp.get("kind")
        if kind == "mulligan_confirm":
            print("[判断] マリガン: この初手で keep するか引き直すか")
            print("  keep      -> mulligan keep")
            print("  引き直し   -> mulligan redraw")
        elif kind == "mulligan_redrawn":
            print("[判断] 引き直し後の新手札。 確定するなら -> mulligan ok")
        else:
            print(f"[判断] 効果による選択 kind={kind}:")
            print(json.dumps(pp, ensure_ascii=False, indent=2)[:1800])
            print("  -> choice <idx> ...")
    elif pk == "action":
        actions = legal_actions(st)
        print("[私の手番] 合法手:")
        for i, a in enumerate(actions):
            print(f"  {i}: {R._describe_action(a, st)}")
        print("  -> move <idx>")
    elif pk == "defense":
        att = R._find_inplay(st, pp.get("attacker_iid"))
        if pp.get("is_leader_attack"):
            tgt = f"私のリーダー(Power{me.leader.power}, ライフ{len(me.life)}枚)"
        else:
            t = R._find_inplay(st, pp.get("target_iid"))
            tgt = f"私のキャラ {t.card.name if t else ''}(Power{t.power if t else '?'})"
        an = att.card.name if att else "?"
        print(f"[防御] {an}(Power{pp.get('attacker_power')}) が {tgt} を攻撃!")
        blockers = pp.get("legal_blocker_iids", []) or []
        if blockers:
            print("  ブロッカー候補:")
            for b in blockers:
                ip = R._find_inplay(st, b)
                print(f"    iid{b} {ip.card.name if ip else ''}(Power{ip.power if ip else '?'})")
        cvals = pp.get("counter_values", {}) or {}
        counters = pp.get("legal_counter_card_idxs", []) or []
        if counters:
            print("  カウンター候補(手札):")
            for ci in counters:
                c = me.hand[ci]
                cv = cvals.get(ci) or cvals.get(str(ci)) or 0
                print(f"    hand[{ci}] {c.name} +{cv} (cost{c.cost})")
        print("  -> defense <blocker_iid|none> [--counter <hand_idx> ...]")
    print()


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Claude vs ExploitBeam (ミラー)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start")
    s.add_argument("--deck", default="cardrush_1342", help="私(Claude)のデッキ slug")
    s.add_argument("--opp", default=None, help="相手AIのデッキ slug (省略時=ミラー)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--first", action="store_true", help="私が先攻")
    g.add_argument("--second", action="store_true", help="私が後攻")
    g.add_argument("--random", action="store_true", help="先後ランダム")
    s.add_argument("--seed", type=int, default=42)

    sub.add_parser("show")
    m = sub.add_parser("mulligan")
    m.add_argument("what", choices=["keep", "redraw", "ok"])
    mv = sub.add_parser("move")
    mv.add_argument("idx", type=int)
    ch = sub.add_parser("choice")
    ch.add_argument("idx", type=int, nargs="*")
    d = sub.add_parser("defense")
    d.add_argument("blocker", help="ブロッカーの iid、 ブロックしないなら none")
    # action="extend" so both `--counter 4 7` and `--counter 4 --counter 7`
    # accumulate (plain nargs="*" silently dropped all but the last flag).
    d.add_argument("--counter", type=int, nargs="*", action="extend", default=[])
    ce = sub.add_parser("counter-event")
    ce.add_argument("hand_idx", type=int)
    at = sub.add_parser("attack", help="iidベースの安全なアタック (番号ずれ無し)")
    at.add_argument("attacker_iid", type=int, help="自分のアタッカーの iid")
    at.add_argument("target", help='"leader" または相手キャラの iid')
    at.add_argument("--don", type=int, default=0, help="アタック前に attacker へ付与する DON 数")
    dn = sub.add_parser("don", help="iidベースの DON 付与")
    dn.add_argument("iid", help='"自リーダーの iid" または自キャラの iid')
    dn.add_argument("n", type=int, help="付与する DON 数")
    rd = sub.add_parser(
        "redirect",
        help="防御中: リーダーの【相手のアタック時】redirect を発動 (DON-1)。続けて choice で対象指定",
    )
    rd.add_argument("--source", type=int, default=None, help="効果source iid (省略時=自リーダー)")
    rd.add_argument("--effect", type=int, default=0, help="effect_idx (default 0)")

    args = ap.parse_args()

    if args.cmd == "start":
        repo = _repo()
        opp_slug = args.opp or args.deck
        deck_me = _load_deck(args.deck, repo)
        deck_ai = _load_deck(opp_slug, repo)
        my_ana = _load_analysis(args.deck)
        opp_ana = _load_analysis(opp_slug)
        overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
        human_first = (
            True if args.first else False if args.second else None if args.random else True
        )
        session = HumanSession(
            deck_a=deck_me,
            deck_b=deck_ai,
            ai_factory=lambda rng, da=None: _opp_ai(rng, opp_slug),
            seed=args.seed,
            effects_overlay=overlay,
            deck_a_analysis=my_ana,
            deck_b_analysis=opp_ana,
            human_first=human_first,
        )
        META.parent.mkdir(parents=True, exist_ok=True)
        META.write_text(
            json.dumps({"deck": args.deck, "opp": opp_slug, "seed": args.seed}),
            encoding="utf-8",
        )
        _save(session)
        mode = f"{args.deck} (私) vs {opp_slug} (AI)" if opp_slug != args.deck else f"ミラー {args.deck}"
        first = "私(先攻)" if session.human_idx == 0 else "ExploitBeam(先攻)"
        print(f"=== 新ゲーム: {mode} / {first} ===")
        _render(session)
        return

    session = _load()
    if args.cmd == "show":
        _render(session)
        return

    try:
        if args.cmd == "mulligan":
            picks = [1] if args.what == "redraw" else []
            session.apply_human_choice(picks)
        elif args.cmd == "move":
            _record_divergence(session, args.idx)
            session.apply_human_action(args.idx)
        elif args.cmd == "choice":
            session.apply_human_choice(list(args.idx))
        elif args.cmd == "defense":
            b = args.blocker.lower()
            blocker = None if b in ("none", "-", "pass", "no") else int(args.blocker)
            session.apply_human_defense(blocker, list(args.counter))
        elif args.cmd == "counter-event":
            session.apply_human_use_counter_event(args.hand_idx)
        elif args.cmd == "redirect":
            src = args.source if args.source is not None else _leader_iid(session)
            session.apply_human_use_opp_attack_effect(src, args.effect)
        elif args.cmd == "don":
            for _ in range(args.n):
                idx = _find_don_idx(session, args.iid)
                if idx is None:
                    print(f"[不正] DON 付与先 iid={args.iid} が見つからない")
                    break
                session.apply_human_action(idx)
        elif args.cmd == "attack":
            # 先に DON を付与 (iid 指定なので番号ずれ無し)
            for _ in range(args.don):
                idx = _find_don_idx(session, str(args.attacker_iid))
                if idx is None:
                    print(f"[不正] DON 付与先 iid={args.attacker_iid} が見つからない")
                    break
                session.apply_human_action(idx)
            idx = _find_attack_idx(session, args.attacker_iid, args.target)
            if idx is None:
                print(f"[不正] iid={args.attacker_iid} → {args.target} のアタックが見つからない")
                _render(session)
                return
            _record_divergence(session, idx)
            session.apply_human_action(idx)
    except ValueError as e:
        print(f"[不正な手] {e}")
        _render(session)
        return

    _save(session)
    _render(session)


if __name__ == "__main__":
    main()
