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
import pickle
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import legal_actions
from engine.human_session import HumanAI, HumanSession
from engine.llm_player_ai import LLMPlayerAI
from engine.smart_opponent_ai import SmartOpponentAI
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


def _attach_ai(session: HumanSession, slug: str) -> None:
    """SmartOpponentAI(ExploitBeam) + HumanAI を session に (再)注入。"""
    ana = _load_analysis(slug)
    session.ai = SmartOpponentAI(rng=session.rng, deck_analysis=ana, deck_slug=slug)
    session.human_ai = HumanAI(session)
    if hasattr(session.ai, "set_ai_opp"):
        session.ai.set_ai_opp(session.human_ai)


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
    _attach_ai(session, meta["deck"])
    return session


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
    s.add_argument("--deck", default="cardrush_1342")
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
    d.add_argument("--counter", type=int, nargs="*", default=[])
    ce = sub.add_parser("counter-event")
    ce.add_argument("hand_idx", type=int)

    args = ap.parse_args()

    if args.cmd == "start":
        repo = _repo()
        deck_me = _load_deck(args.deck, repo)
        deck_ai = _load_deck(args.deck, repo)
        ana = _load_analysis(args.deck)
        overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
        human_first = (
            True if args.first else False if args.second else None if args.random else True
        )
        session = HumanSession(
            deck_a=deck_me,
            deck_b=deck_ai,
            ai_factory=lambda rng, da=None: SmartOpponentAI(
                rng=rng, deck_analysis=da or ana, deck_slug=args.deck
            ),
            seed=args.seed,
            effects_overlay=overlay,
            deck_a_analysis=ana,
            deck_b_analysis=ana,
            human_first=human_first,
        )
        META.parent.mkdir(parents=True, exist_ok=True)
        META.write_text(
            json.dumps({"deck": args.deck, "seed": args.seed}), encoding="utf-8"
        )
        _save(session)
        first = "私(先攻)" if session.human_idx == 0 else "ExploitBeam(先攻)"
        print(f"=== 新ゲーム: ミラー {args.deck} / {first} ===")
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
            session.apply_human_action(args.idx)
        elif args.cmd == "choice":
            session.apply_human_choice(list(args.idx))
        elif args.cmd == "defense":
            b = args.blocker.lower()
            blocker = None if b in ("none", "-", "pass", "no") else int(args.blocker)
            session.apply_human_defense(blocker, list(args.counter))
        elif args.cmd == "counter-event":
            session.apply_human_use_counter_event(args.hand_idx)
    except ValueError as e:
        print(f"[不正な手] {e}")
        _render(session)
        return

    _save(session)
    _render(session)


if __name__ == "__main__":
    main()
