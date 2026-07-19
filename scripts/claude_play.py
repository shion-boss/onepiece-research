# -*- coding: utf-8 -*-
"""Claude (= 私) が ExploitBeam と 1 手ずつ対戦する CLI。 ミラー対戦専用。

私が「人間」の位置 (deck_a / human_idx) に座り、 盤面と合法手を読んで手を選ぶ。
ExploitBeam (= SmartOpponentAI) の手番は自動。 状態は db/claude_play/session.pkl に
保存し、 コマンドごとに 1 手進める (= Claude Code は 1 コマンド = 1 観測 のため)。

AI (SmartOpponentAI / HumanAI) は session 参照や GBM を含むため pickle から除外し、
load 時に meta.json の deck slug から再注入する (= state/rng/pending だけ永続化)。

  start [--deck SLUG] [--first|--second|--random] [--seed N]
  show
  plan | lethal                     # リーサル/防御の補助サマリ (相手ライフ/DON/ブロッカー/自アタッカー)
  mulligan keep|redraw|ok
  move <idx>
  choice [<idx> ...]
  defense <blocker_iid|none> [--counter <hand_idx> ...]
  counter-event <hand_idx>

attack/defense/counter-event の後は「[結果]」 行で相手ライフ/手札の増減・カウンター消費・
ブロッカーのレスト等の帰結を 1〜2 行で表示する (= 攻撃が通ったかを session.pkl inspect なしで読める)。
show の自リーダー行には iid を表示する (= attack/don の iid 指定に使える)。
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

# 並列収集用 (2026-07-02): ONEPIECE_PLAY_DIR で session / DIVLOG 出力先を分離可能
# (既定 db/claude_play)。 各 subagent に別 dir を渡せば衝突せず並列で claude_play を回せる。
import os as _os
_pd = _os.environ.get("ONEPIECE_PLAY_DIR")
PLAY_DIR = Path(_pd) if _pd else ROOT / "db" / "claude_play"
PLAY_DIR.mkdir(parents=True, exist_ok=True)
STATE = PLAY_DIR / "session.pkl"
META = PLAY_DIR / "meta.json"


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
        path = PLAY_DIR / f"divergence_{slug}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # divergence ロギングはベストエフォート (= 対戦を止めない)


def _record_distill_state(session) -> None:
    """Claude の決定局面の v6 (38次元) 特徴量を pending buffer に記録。 game_over で outcome を付与し
    distill corpus (= value 学習用) にする。 divergence(サマリ)と違い**全特徴量**を保存 = distill 可能。
    ONEPIECE_DIVLOG=1 の時のみ (= 収集モード)。 ベストエフォート。"""
    if not os.environ.get("ONEPIECE_DIVLOG"):
        return
    try:
        from engine.core import Phase
        from engine.gbm_value import features
        st = session.state
        if st.game_over or st.phase != Phase.MAIN or st.turn_player_idx != session.human_idx:
            return
        feat = features(st, session.human_idx, v6=True)  # 38-dim、 env 非依存
        meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
        slug = meta.get("deck", "unknown")
        path = PLAY_DIR / f"pending_{slug}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"feat": feat, "turn": int(getattr(st, "turn_number", 0))}) + "\n")
    except Exception:
        pass


def _flush_distill(session) -> None:
    """game_over 時、 pending 特徴量に outcome (Claude 勝=1/負=0) を付与し distill_<slug>.jsonl へ移す。
    = 「Claude の良い play の局面 → 勝敗」 = value 学習データ (循環を破る expert 分布)。"""
    try:
        st = session.state
        if not st.game_over:
            return
        meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
        slug = meta.get("deck", "unknown")
        pending = PLAY_DIR / f"pending_{slug}.jsonl"
        if not pending.exists():
            return
        y = 1 if getattr(st, "winner", -1) == session.human_idx else 0
        out = PLAY_DIR / f"distill_{slug}.jsonl"
        with open(pending, encoding="utf-8") as pf, open(out, "a", encoding="utf-8") as of:
            for line in pf:
                try:
                    r = json.loads(line); r["y"] = y
                    of.write(json.dumps(r) + "\n")
                except Exception:
                    pass
        pending.unlink()  # 次局のためにクリア
    except Exception:
        pass


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
# バトル結果サマリ (= 2026-07-19): attack/defense/counter-event 後、 相手ライフ/手札の
# 増減・カウンター消費・ブロッカーのレストを 1〜2 行で表示。 教師(cloud/ローカル)が
# session.pkl を手動 inspect せず攻防の帰結を読めるようにする (= 教師データ品質↑)。
# action 適用の前後で state を snapshot し diff する (= 新探索は不要、 engine 値の差分のみ)。
# --------------------------------------------------------------------------- #
def _board_snapshot(session: HumanSession) -> dict:
    """diff 用の軽量スナップショット (= life/hand 枚数 + 場キャラ {iid: (name, power, rested)})。"""
    st = session.state
    me = st.players[session.human_idx]
    opp = st.players[session.ai_idx]

    def _chars(p):
        return {
            c.instance_id: (c.card.name, c.power, c.rested, c.is_blocker_now)
            for c in p.characters
        }

    return {
        "my_life": len(me.life),
        "opp_life": len(opp.life),
        "my_hand": len(me.hand),
        "opp_hand": len(opp.hand),
        "opp_don_active": opp.don_active,
        "my_chars": _chars(me),
        "opp_chars": _chars(opp),
    }


def _battle_summary(before: dict, after: dict) -> None:
    """before/after スナップショットの差分を「[結果]」 として 1〜2 行で表示。 攻防コマンド後は
    必ず 1 行出す (= 変化ゼロなら「通らず/凌いだ」 と明示 → 教師が結果を必ず読める)。"""
    life_hand: list[str] = []
    for label, key in (
        ("相手ライフ", "opp_life"),
        ("相手手札", "opp_hand"),
        ("自ライフ", "my_life"),
        ("自手札", "my_hand"),
        ("相手アクティブDON", "opp_don_active"),
    ):
        b, a = before[key], after[key]
        if b != a:
            life_hand.append(f"{label} {b}→{a}({a - b:+d})")

    # KO / レスト変化 (= ブロッカーが立った/寝た、 相手キャラが消えた 等)
    events: list[str] = []
    for side_label, key in (("相手", "opp_chars"), ("自", "my_chars")):
        bch, ach = before[key], after[key]
        for iid, (name, pw, rested, _blk) in bch.items():
            if iid not in ach:
                events.append(f"{side_label}キャラ {name}(P{pw}) がKO/退場")
            else:
                _, apw, arested, _ = ach[iid]
                if (not rested) and arested:
                    events.append(f"{side_label}キャラ {name} がレスト(ブロック等)")
                elif rested and (not arested):
                    events.append(f"{side_label}キャラ {name} がアクティブ化")
        for iid, (name, pw, _rested, _blk) in ach.items():
            if iid not in bch:
                events.append(f"{side_label}キャラ {name}(P{pw}) が登場")

    print("[結果]")
    if life_hand:
        print("  " + "  ".join(life_hand))
    if events:
        print("  " + " / ".join(events))
    if not life_hand and not events:
        # 攻撃がパワー差で通らなかった / 完全にブロック+カウンターで凌がれた 等 = 盤面変化なし
        print("  盤面に変化なし (= アタックがパワー差で通らず、 または完全に防御された)")


# --------------------------------------------------------------------------- #
# plan / lethal 補助 (= 2026-07-19): 詰め判断を engine 値から要約。 新探索は不要。
#   - 相手リーダー現ライフ / 相手アクティブDON (ブロック・パンプ余力)
#   - 相手の場のブロッカー一覧 (power)
#   - 自分の各アタッカーの現パワーと攻撃可能性
#   - 相手が手札を全カウンターに使った場合の粗い想定防御力 (手札枚数×2000 上限)
# --------------------------------------------------------------------------- #
def _print_plan(session: HumanSession) -> None:
    st = session.state
    me = st.players[session.human_idx]
    opp = st.players[session.ai_idx]

    print()
    print("[plan / リーサル補助] (粗い見積り、 engine 値のみ。 相手手札の中身は不可視)")
    print(
        f"  相手リーダー: {opp.leader.card.name} ライフ{len(opp.life)}枚 / "
        f"相手アクティブDON {opp.don_active}枚 (ブロック/パンプ余力)"
    )

    # 相手ブロッカー
    blockers = [c for c in opp.characters if c.is_blocker_now and not c.rested]
    if blockers:
        print("  相手ブロッカー(アクティブ):")
        for c in blockers:
            print(f"    - iid{c.instance_id} {c.card.name}(Power{c.power})")
    else:
        print("  相手ブロッカー(アクティブ): なし")

    # 相手の粗い想定防御力 (手札全カウンター上限 + DON パンプ)
    opp_hand = len(opp.hand)
    counter_cap = opp_hand * 2000
    don_pump = opp.don_active * 1000
    print(
        f"  相手の想定最大防御(粗い上限): 手札{opp_hand}枚×2000 = {counter_cap} "
        f"+ DONパンプ {don_pump} = ~{counter_cap + don_pump}"
    )

    # 自分のアタッカー
    attackers = [
        c
        for c in me.characters
        if not c.rested and not (c.summoning_sickness and not c.is_rush_now)
    ]
    leader_can_attack = not me.leader.rested
    print("  自アタッカー:")
    if leader_can_attack:
        print(f"    - リーダー iid{me.leader.instance_id} {me.leader.card.name}(Power{me.leader.power})")
    for c in attackers:
        kw = []
        if c.is_rush_now:
            kw.append("速攻")
        tag = f" [{','.join(kw)}]" if kw else ""
        print(f"    - iid{c.instance_id} {c.card.name}(Power{c.power}){tag}")
    if not leader_can_attack and not attackers:
        print("    (攻撃可能なアタッカーなし)")

    # 合計攻撃力 (リーダー攻撃想定) と相手ライフを対比
    total_atk = (me.leader.power if leader_can_attack else 0) + sum(c.power for c in attackers)
    n_atk = (1 if leader_can_attack else 0) + len(attackers)
    print(
        f"  参考: アタッカー{n_atk}体の合計パワー {total_atk} / 相手ライフ{len(opp.life)}枚。 "
        f"リーサルは 各攻撃が相手の要求値(=手札カウンター+DON)を貫くかで判断。"
    )
    print()


# --------------------------------------------------------------------------- #
# トリガー無しの life_taken_choice を自動解決 (= 2026-07-19 任意改善#4)。
# ライフを受けたカードにトリガーが無い場合、 選択の余地は無い (= 手札に加わるだけ) ので、
# 教師が毎回 `choice` を打つ手間を省く。 トリガー有りは判断が要るので触らない。
# --------------------------------------------------------------------------- #
def _auto_resolve_trivial_life_choices(session: HumanSession) -> bool:
    """no-trigger の life_taken_choice を最大数回まで自動解決。 1 つでも解決したら True。"""
    resolved = False
    for _ in range(12):  # 多段ヒット (= 複数ライフ同時) でも収束させる上限ガード
        if session.pending_kind != "choice":
            break
        pp = session.pending_payload or {}
        if pp.get("kind") != "life_taken_choice" or pp.get("has_trigger"):
            break
        try:
            name = pp.get("name", "?")
            session.apply_human_choice([])  # picks=[] = トリガー不使用 (= 手札に加えるだけ)
            print(f"[自動] ライフ受け ({name}) トリガー無し → 手札に加えて続行")
            resolved = True
        except Exception:
            break
    return resolved


# --------------------------------------------------------------------------- #
# 私視点 (human_idx 固定) の盤面 + pending 表示
# --------------------------------------------------------------------------- #
def _render(session: HumanSession) -> None:
    R = LLMPlayerAI(rng=random.Random(0))  # render 専用 (LLM は呼ばない)
    st = session.state
    me = st.players[session.human_idx]
    opp = st.players[session.ai_idx]

    print()
    # 自リーダーの iid を表示 (= attack/don の iid 指定に必要。 従来は pickle inspect が必要だった)。
    # _render_side はリーダー行に iid を出さないので、 自側だけ後付けで iid を注入する。
    my_side = R._render_side("[私 Claude]", me, hidden_hand=False)
    lid = me.leader.instance_id
    my_side = my_side.replace(
        f"  リーダー: {me.leader.card.name}",
        f"  リーダー: iid{lid} {me.leader.card.name}",
        1,
    )
    print(my_side)
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

    # A軸(自リーダー使い方 prior) + B軸(相手が握る/積む脅威 belief、 見えた札で事後 sharpening)
    # を Claude に提示 → 良手 demonstrate の材料。 これで教師(Claude)の判断が上がり、 蒸留 value
    # の label 品質が上がる (= 教師の質が生徒の天井、 [[project_superhuman_ai_distillation]])。
    # render を絶対に壊さない (try/except)。 cloud agent も同 render を観測に使う。
    try:
        from engine import matchup_context as _mc
        _ctx = _mc.format_context_text(_mc.describe_matchup_context(st, session.human_idx))
        if _ctx.strip():
            print()
            print("[マッチ情報 (prior)]")
            print(_ctx)
    except Exception:
        pass

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
        print("  ⚠ idx は 1 手ごとに再構成され変わる。move を盲目連打せず、毎手 show で読み直せ。")
        print("     攻撃/DON付与は idx シフトしない iid 版を優先: attack <iid> <target|leader> [--don N] / don <iid> <n>")
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
    sub.add_parser("plan", help="リーサル/防御の補助サマリ (相手ライフ/DON/ブロッカー/自アタッカー)")
    sub.add_parser("lethal", help="plan の別名")
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
        (PLAY_DIR / f"pending_{args.deck}.jsonl").unlink(missing_ok=True)
        _save(session)
        mode = f"{args.deck} (私) vs {opp_slug} (AI)" if opp_slug != args.deck else f"ミラー {args.deck}"
        first = "私(先攻)" if session.human_idx == 0 else "ExploitBeam(先攻)"
        print(f"=== 新ゲーム: {mode} / {first} ===")
        _render(session)
        return

    session = _load()
    if args.cmd == "show":
        if _auto_resolve_trivial_life_choices(session):
            _flush_distill(session)
            _save(session)
        _render(session)
        return
    if args.cmd in ("plan", "lethal"):
        _auto_resolve_trivial_life_choices(session) and _save(session)
        _print_plan(session)
        return

    # 攻防コマンドは適用の前後で盤面 diff を取り「[結果]」 として帰結を 1〜2 行表示する
    # (= 教師が session.pkl を inspect せず攻撃が通ったか/カウンター/ブロックを読める)。
    _battle_before = None
    if args.cmd in ("attack", "defense", "counter-event"):
        _battle_before = _board_snapshot(session)

    try:
        if args.cmd == "mulligan":
            picks = [1] if args.what == "redraw" else []
            session.apply_human_choice(picks)
        elif args.cmd == "move":
            _record_divergence(session, args.idx)
            _record_distill_state(session)
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
            _record_distill_state(session)
            session.apply_human_action(idx)
    except ValueError as e:
        print(f"[不正な手] {e}")
        _render(session)
        return

    # トリガー無しの life_taken_choice は自動解決 (= 攻防後に相手/自分がライフを受けて手札に
    # 加わるだけの局面で、 教師が余計な `choice` を打たずに済む)。 攻防サマリの前に解決して
    # 最終盤面を diff に反映する。
    _auto_resolve_trivial_life_choices(session)

    # 攻防の帰結サマリ (= 相手ライフ/手札の増減・カウンター消費・ブロッカーのレスト) を表示
    if _battle_before is not None:
        try:
            _battle_summary(_battle_before, _board_snapshot(session))
        except Exception:
            pass  # サマリはベストエフォート (= 対戦を止めない)

    _flush_distill(session)  # game_over なら pending 特徴量に勝敗ラベルを付与し distill corpus へ
    _save(session)
    _render(session)


if __name__ == "__main__":
    main()
