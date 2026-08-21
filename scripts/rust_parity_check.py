#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python ↔ Rust engine 差分パリティ検証ツール (正式版、 元 scratchpad/correctness_check.py)。

Python engine を「正」(公式準拠 100% 検証済) とし、 Rust engine (optcg_engine、 maturin develop で
ビルド) が **同一状態から同一 action を適用したとき Python と bit 一致するか** を全 action 横断で測る。

判定 3 種:
  - match    : Rust apply 後の canonical digest が Python と一致 (= Rust はその action で忠実)
  - bail(Err): Rust が未実装を Err で明示 (= 黙って間違えない。 誤りではない)
  - MISMATCH : Rust が適用したが digest 不一致 (= correctness 違反。 これが 0 であることが不変条件)

⭐ **今後の運用 (Python↔Rust 同期の維持)**:
  Python engine (effects.py 等) を変更したら、 必ず `python scripts/rust_parity_check.py --assert` を実行。
  MISMATCH が出たら Rust 側 (rust_engine/) を追従修正するか、 その action を Err bail にする (= どちらも
  「黙って間違えない」 を保つ)。 CI/pytest では tests/test_rust_parity.py が小規模版を自動実行する。

使い方:
  python scripts/rust_parity_check.py                 # summary + top bail
  python scripts/rust_parity_check.py --assert        # MISMATCH>0 で exit 1 (CI/pre-commit 用)
  python scripts/rust_parity_check.py --wall          # Rust standalone 完走の壁 観測
  python scripts/rust_parity_check.py --games 3        # ゲーム数 (deck pair × seed) を絞る
"""
from __future__ import annotations
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import optcg_engine as eng
except ImportError:
    print("ERROR: optcg_engine (Rust) 未ビルド。 `.venv/bin/maturin develop --manifest-path rust_engine/Cargo.toml`")
    sys.exit(2)

# ⛔ 選択列挙モード (ONEPIECE_CHOICE_SEARCH) では Rust を使わない。
#   Rust は pending_choice / continuation 未実装なので Python と別のゲームになる。
#   ⚠ このモードだと差分ハーネスは 「Python が halt した局面を skip」 して
#     py_skip が増えるだけで **検証になっていない** (実測 match=40 / py_skip=96)。
from engine.rust_shadow import assert_rust_safe_for_choice_search  # noqa: E402
assert_rust_safe_for_choice_search("rust_parity_check.py")

from engine.core import reset_iid
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, apply_action,
                         AttackLeader, AttackCharacter, PlayCharacter, PlayEvent, PlayStage,
                         AttachDonToLeader, AttachDonToCharacter, ActivateMain, EndPhase,
                         _find_attacker_or_none)
from engine.ai import GreedyAI
from engine.plan_search import fast_clone
from engine.state_snapshot import state_digest, full_dump

_repo_cache: dict = {}


def _load():
    if "repo" not in _repo_cache:
        _repo_cache["repo"] = CardRepository.from_json(REPO / "db" / "cards.json")
        _repo_cache["ov"] = load_effect_overlay(REPO / "db" / "card_effects.json")
        eng.load_overlay(str((REPO / "db" / "card_effects.json").resolve()))
    return _repo_cache["repo"], _repo_cache["ov"]


_deck_cache: dict = {}


def _dl(slug: str):
    repo, _ = _load()
    if slug not in _deck_cache:
        _deck_cache[slug] = json.loads((REPO / "decks" / f"{slug}.json").read_text())
    return make_deck_from_dict(_deck_cache[slug], repo)


def deck_analysis(slug: str) -> dict | None:
    """decks/<slug>.analysis.json (無ければ None)。 マリガン判定 tier1 の keep card 群を持つ。"""
    p = REPO / "decks" / f"{slug}.analysis.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


_dv_cache: dict = {}


def deck_value(slug: str) -> str:
    """Rust self_play / setup_full に渡す deck Value (JSON 文字列)。

    leader/main に加え **マリガン判定材料** を載せる (Rust 側 should_mulligan の tier1/tier2)。
    - mulligan_keep_card_ids: decks/<slug>.analysis.json のキープ札 (tier1)
    - mulligan_prior_card_ids: imitation prior (大会採用率) が 0.5 以上の card_id (tier2)
    これを渡さないと Rust は tier3 (コスト3以下キャラの有無) だけで判断し、 Python の AI と挙動が
    ズレる (= 初手分布が変わる)。 game.py:_should_mulligan と対応。
    """
    if slug in _dv_cache:
        return _dv_cache[slug]
    from engine.state_snapshot import _ser_full

    d = _dl(slug)
    v = {"leader": _ser_full(d.leader), "main": [_ser_full(c) for c in d.main]}
    an = deck_analysis(slug) or {}
    v["mulligan_keep_card_ids"] = list(an.get("mulligan_keep_card_ids") or [])
    prior: list[str] = []
    if not v["mulligan_keep_card_ids"]:
        try:
            from engine.imitation_prior import get_mulligan_priority

            lid = d.leader.card_id
            seen = {c.card_id for c in d.main}
            prior = sorted(i for i in seen if get_mulligan_priority(lid, i) >= 0.5)
        except Exception:
            prior = []
    v["mulligan_prior_card_ids"] = prior
    # setup_modifier / set_don_deck_size (OP15-058 紫エネル: ドンデッキ 6 枚)。 Python は
    # game.py:419 で leader overlay を読んで反映するので、 Rust にも同じ値を渡す
    # (渡さないと Rust は常に 10 枚で回り、 該当リーダーだけ silent に別ゲームになる)。
    _, _ov = _load()
    _b = _ov.get(d.leader.card_id) if _ov else None
    _dds = 10
    if _b is not None:
        for _e in _b.effects:
            if _e.get("when") != "setup_modifier":
                continue
            for _p in _e.get("do", []) or []:
                if "set_don_deck_size" in _p:
                    _dds = int(_p["set_don_deck_size"])
    v["don_deck_size"] = _dds
    _dv_cache[slug] = json.dumps(v)
    return _dv_cache[slug]


def _kidx(p, iid):
    if iid == p.leader.instance_id:
        return "leader", 0
    for i, c in enumerate(p.characters):
        if c.instance_id == iid:
            return "char", i
    for i, c in enumerate(p.stages):
        if c.instance_id == iid:
            return "stage", i
    return None, None


def _enc(st, a):
    """Python action → Rust が解釈する canonical action dict (instance_id を index に畳む)。"""
    me, opp = st.turn_player, st.opponent
    if isinstance(a, EndPhase):
        return {"t": "EndPhase"}
    if isinstance(a, PlayCharacter):
        d = {"t": "PlayCharacter", "hand_idx": a.hand_idx}
        if a.sacrifice_iid is not None:
            d["sacrifice_idx"] = _kidx(me, a.sacrifice_iid)[1]
        return d
    if isinstance(a, PlayEvent):
        return {"t": "PlayEvent", "hand_idx": a.hand_idx}
    if isinstance(a, PlayStage):
        return {"t": "PlayStage", "hand_idx": a.hand_idx}
    if isinstance(a, AttachDonToLeader):
        return {"t": "AttachDonToLeader", "n": a.n}
    if isinstance(a, AttachDonToCharacter):
        return {"t": "AttachDonToCharacter", "target_idx": _kidx(me, a.target_iid)[1], "n": a.n}
    if isinstance(a, ActivateMain):
        k, i = _kidx(me, a.source_iid)
        return {"t": "ActivateMain", "source_kind": k, "source_idx": i, "effect_index": a.effect_index}
    if isinstance(a, (AttackLeader, AttackCharacter)):
        ak, ai = _kidx(me, a.attacker_iid)
        d = {"attacker_kind": ak, "attacker_idx": ai,
             "counter_card_idxs": list(a.counter_card_idxs), "counter_event_idxs": list(a.counter_event_idxs)}
        d["blocker"] = ({"kind": _kidx(opp, a.blocker_iid)[0], "idx": _kidx(opp, a.blocker_iid)[1]}
                        if a.blocker_iid is not None else None)
        if isinstance(a, AttackLeader):
            d["t"] = "AttackLeader"
        else:
            d["t"] = "AttackCharacter"
            d["target_idx"] = _kidx(opp, a.target_iid)[1]
        return d
    return {"t": "?"}


def _defended(st, action, aio):
    me, opp = st.turn_player, st.opponent
    at = _find_attacker_or_none(me, action.attacker_iid)
    if at is None:
        return action
    isl = isinstance(action, AttackLeader)
    tgt = opp.leader if isl else next((c for c in opp.characters if c.instance_id == action.target_iid), None)
    if tgt is None:
        return action
    bi, counters = aio.choose_defense(st, at, tgt, isl, opp)
    ev, cd = [], []
    for idx in counters:
        if 0 <= idx < len(opp.hand):
            (ev if str(getattr(opp.hand[idx], "category", "")).endswith("EVENT") else cd).append(idx)
    kw = dict(attacker_iid=action.attacker_iid, counter_card_idxs=tuple(cd),
              counter_event_idxs=tuple(ev), blocker_iid=bi)
    return AttackLeader(**kw) if isl else AttackCharacter(target_iid=action.target_iid, **kw)


DECKS = ["cardrush_1342", "cardrush_1385", "cardrush_1454", "cardrush_1466", "cardrush_1478",
         "cardrush_1491", "cardrush_1512", "cardrush_1548", "cardrush_1574", "cardrush_1592",
         "tcgportal_calgara", "tcgportal_bonney", "tcgportal_hancock", "tcgportal_op13_luffy",
         "pros02_zoro_g", "pros02_kid_y"]


def _pairs(n_games: int | None, seeds=(1, 7)):
    ps = [(DECKS[i], DECKS[(i + 3) % len(DECKS)], s) for i in range(len(DECKS)) for s in seeds]
    return ps[:n_games] if n_games else ps


def run_parity(n_games: int | None = None, seeds=(1, 7), max_turns=220):
    """全 action 横断で match/bail/MISMATCH を集計。 (tot Counter, bail_msgs Counter, mismatch_cards Counter)。"""
    _, ov = _load()
    tot = Counter()
    bail_msgs = Counter()
    mismatch = Counter()
    for a, b, s in _pairs(n_games, seeds):
        reset_iid()
        st = setup_game(_dl(a), _dl(b), rng=random.Random(s), first_player=s % 2, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(s * 3 + 1)), GreedyAI(rng=random.Random(s * 5 + 2))]
        for _ in range(max_turns):
            if st.game_over:
                break
            mi = st.turn_player_idx
            act = ais[mi].choose_action(st)
            if act is None:
                break
            if isinstance(act, (AttackLeader, AttackCharacter)):
                act = _defended(st, act, ais[1 - mi])
            e = _enc(st, act)
            if e.get("t") != "?":
                dump = json.dumps(full_dump(st))
                # static-diff は combat 忠実性の対象外 (evaluate_static のズレは別軸) → skip。
                # ⚠ ただし **黙って** 飛ばすと 「静的効果の乖離」 が MISMATCH にも bail にも
                #   出ず match 数が減るだけで不可視になる → 必ず数える (2026-08-04)。
                if eng.recompute_static_digest(dump) != state_digest(st):
                    tot["static_skip"] += 1
                if eng.recompute_static_digest(dump) == state_digest(st):
                    c = fast_clone(st)
                    # ⭐ rng を full_dump が capture した state (= Rust が入力に使う _rng_state) に揃える。
                    # fast_clone は clone に軽い別 rng を与える (探索速度用) が、 差分パリティでは Python 参照
                    # clone も Rust と同じ rng 列を消費すべき (rng は starting state の一部)。 これで rng 依存
                    # effect (trash_opp_hand_random / shuffle 等) が bit-match 可能になる。
                    _src_rng = getattr(st, "rng", None)
                    if _src_rng is not None and hasattr(_src_rng, "getstate"):
                        _r = random.Random()
                        _r.setstate(_src_rng.getstate())
                        c.rng = _r
                    try:
                        apply_action(c, act)
                        ok = c.pending_choice is None
                    except Exception:
                        ok = False
                    # ⚠ Python 側が pending_choice で止まった / 例外を投げた局面も比較不能で
                    #   skip している。 数えないと 「ゲームが壊れて比較点が消えた」 のを
                    #   MISMATCH=0 のまま見逃す (実際に 2037→724 の激減を見逃しかけた)。
                    if not ok:
                        tot["py_skip"] += 1
                    if ok:
                        dpy = state_digest(c)
                        try:
                            dr = eng.apply_action_digest(dump, json.dumps(e))
                            if dr == dpy:
                                tot["match"] += 1
                            else:
                                tot["MISMATCH"] += 1
                                cid = "?"
                                if e["t"] in ("PlayCharacter", "PlayEvent", "PlayStage") and 0 <= act.hand_idx < len(st.turn_player.hand):
                                    cid = st.turn_player.hand[act.hand_idx].card_id
                                mismatch[f"{e['t']}:{cid}"] += 1
                                import os as _os
                                if _os.environ.get("ONEPIECE_PARITY_DUMP"):
                                    import json as _j
                                    _pth = _os.environ["ONEPIECE_PARITY_DUMP"]
                                    if not _os.path.exists(_pth):
                                        _j.dump({"dump": _j.loads(dump), "action": e,
                                                 "py_after": full_dump(c)},
                                                open(_pth, "w"))
                        except Exception as ex:
                            tot["bail"] += 1
                            bail_msgs[str(ex).splitlines()[0][:70]] += 1
            if not st.game_over:
                try:
                    apply_action(st, act)
                except Exception:
                    break
    return tot, bail_msgs, mismatch


def run_wall(n_games: int | None = None, seeds=(1, 7, 13)):
    """Rust standalone 完走の壁: MISMATCH0 前提で「最初に bail する手まで」= 完走可能深さ。"""
    _, ov = _load()
    depths = []
    reasons = Counter()
    completed = 0
    games = 0
    ps = [(DECKS[i], DECKS[(i + j) % len(DECKS)], s)
          for i in range(len(DECKS)) for j in (3, 8) for s in seeds]
    ps = ps[:n_games] if n_games else ps
    for a, b, s in ps:
        reset_iid()
        st = setup_game(_dl(a), _dl(b), rng=random.Random(s), first_player=s % 2, effects_overlay=ov)
        play_until_main(st)
        ais = [GreedyAI(rng=random.Random(s * 3 + 1)), GreedyAI(rng=random.Random(s * 5 + 2))]
        games += 1
        depth = 0
        wall = None
        for _ in range(300):
            if st.game_over:
                completed += 1
                break
            mi = st.turn_player_idx
            act = ais[mi].choose_action(st)
            if act is None:
                break
            if isinstance(act, (AttackLeader, AttackCharacter)):
                act = _defended(st, act, ais[1 - mi])
            e = _enc(st, act)
            if e.get("t") == "?":
                break
            dump = json.dumps(full_dump(st))
            if eng.recompute_static_digest(dump) != state_digest(st):
                wall = f"STATIC-DIFF[{e['t']}]"
                break
            try:
                dr = eng.apply_action_digest(dump, json.dumps(e))
                c = fast_clone(st)
                # ⭐ 参照 clone の rng を full_dump が capture した _rng_state に揃える (run_parity と同じ)。
                # これが無いと rng 依存 effect (shuffle/random discard 等) で偽 MISMATCH を報告する。
                _src_rng = getattr(st, "rng", None)
                if _src_rng is not None and hasattr(_src_rng, "getstate"):
                    _r = random.Random()
                    _r.setstate(_src_rng.getstate())
                    c.rng = _r
                apply_action(c, act)
                if c.pending_choice is None and dr != state_digest(c):
                    wall = f"MISMATCH[{e['t']}]"
                    break
            except Exception as ex:
                wall = str(ex).splitlines()[0][:60]
                break
            depth += 1
            try:
                apply_action(st, act)
            except Exception:
                break
        depths.append(depth)
        if wall is not None:
            reasons[wall] += 1
    return depths, reasons, completed, games


def main():
    ap = argparse.ArgumentParser(description="Python↔Rust engine 差分パリティ検証")
    ap.add_argument("--games", type=int, default=None, help="ゲーム数 (deck pair×seed) を絞る")
    ap.add_argument("--assert", dest="do_assert", action="store_true", help="MISMATCH>0 で exit 1 (CI 用)")
    ap.add_argument("--wall", action="store_true", help="standalone 完走の壁を観測")
    ap.add_argument("--top", type=int, default=25, help="bail/理由の表示上位数")
    args = ap.parse_args()

    if args.wall:
        import statistics
        depths, reasons, completed, games = run_wall(args.games)
        print(f"=== Rust standalone 完走の壁 ({games} games) ===")
        print(f"完走: {completed}/{games} = {100*completed/max(1,games):.1f}%")
        print(f"壁まで深さ: median={statistics.median(depths)} mean={statistics.mean(depths):.1f} max={max(depths)}")
        print("=== 最初の壁 (top) ===")
        for r, n in reasons.most_common(args.top):
            print(f"  {n:3d}  {r}")
        return

    tot, bail_msgs, mismatch = run_parity(args.games)
    denom = tot["match"] + tot["bail"] + tot["MISMATCH"]
    print(f"match={tot['match']}  bail(Err)={tot['bail']}  MISMATCH={tot['MISMATCH']}"
          f"  static_skip={tot['static_skip']}  py_skip={tot['py_skip']}")
    print(f"correctness (match+bail、 黙って間違えない) = {100*(tot['match']+tot['bail'])/max(1,denom):.2f}%")
    if mismatch:
        print("=== ⚠ MISMATCH card (correctness 違反、 要修正) ===")
        for k, n in mismatch.most_common(args.top):
            print(f"  {n:3d}  {k}")
    print("=== bail 内訳 (top、 = Rust 未実装 = 追従候補) ===")
    for k, n in bail_msgs.most_common(args.top):
        print(f"  {n:3d}  {k}")
    if args.do_assert and tot["MISMATCH"] > 0:
        print(f"\nFAIL: MISMATCH={tot['MISMATCH']} > 0 (Python↔Rust 同期崩れ)")
        sys.exit(1)


if __name__ == "__main__":
    main()
