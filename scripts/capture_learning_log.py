# -*- coding: utf-8 -*-
"""現最強AI(ExploitBeam)同士の self-play を、 学習用の"精密 decision log"で記録するテスト。

各 AI 決定時に(完全 state で):行動 / 戦闘詳細(攻撃power・付与DON・相手counter) /
自他の DON・手札・ライフ / **相手 counter 上界の確率推定(belief model)** / **相手の実手札
counter(ground truth)** を記録 → game_over で勝敗ラベル付与。 = counterfactual/read 学習の土台。

  .venv/bin/python scripts/capture_learning_log.py --a cardrush_1467 --b tcgportal_bonney
"""
import sys, os, random, argparse, json
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, AttackLeader, AttackCharacter)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.opponent_deck_model import get_default_model

R = Path(os.getcwd())
_REPO = CardRepository.from_json(R / "db" / "cards.json")
_OV = load_effect_overlay(R / "db" / "card_effects.json")
_raw = json.load(open(R / "db" / "cards.json"))
_cardsL = _raw if isinstance(_raw, list) else _raw["cards"]
_CTR = {c["card_id"]: (int(c["counter"]) if str(c.get("counter", "")).isdigit() else 0) for c in _cardsL}
_MODEL = get_default_model()


def _deck(slug):
    return make_deck_from_dict(json.loads((R / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


from engine.core import _player_snapshot as _psnap  # engine のフル player 直列化を再利用


def _full_state(state):
    """decision 時点の game の完全な state (両プレイヤーの全ゾーン: leader/characters/stages
    の card_id・power・base_power・rested・attached_don・keywords、 hand 中身、 trash 中身、
    life/deck/don 全数)。 = ログが「game の全情報」を持つための核。 隠匿情報 (deck/life の
    順序) のみ非記録 (= それは本質的に不可視、 count は持つ)。"""
    return {
        "turn": state.turn_number,
        "turn_player_idx": state.turn_player_idx,
        "phase": state.phase.name if hasattr(state.phase, "name") else str(state.phase),
        "players": [_psnap(p) for p in state.players],
    }


def _action_detail(action):
    """選ばれた action の全パラメータ (= どのカードを/どの対象に/何ドン等) を直列化。"""
    d = {}
    if hasattr(action, "__dict__"):
        for k, v in vars(action).items():
            if isinstance(v, (int, str, bool, float)) or v is None:
                d[k] = v
    return d


def _counter_ceiling(opp_leader_id, opp, K=40, rng=None):
    """相手 leader + seen(trash/board)から 相手手札の counter 総量分布を推定 → (p50,p80,p95)。"""
    rng = rng or random.Random(1)
    from collections import Counter as C
    seen = C()
    for c in opp.trash:
        seen[c.card_id] += 1
    for ch in opp.characters:
        seen[ch.card.card_id] += 1
    hc = len(opp.hand)
    if hc == 0:
        return (0, 0, 0)
    samples = []
    for _ in range(K):
        m = _MODEL.sample_main(opp_leader_id, rng, dict(seen))
        if not m:
            return None
        hidden = []
        for cid, cnt in m:
            hidden += [cid] * cnt
        sc = dict(seen)
        rem = []
        for cid in hidden:
            if sc.get(cid, 0) > 0:
                sc[cid] -= 1
            else:
                rem.append(cid)
        hand = rem if len(rem) < hc else rng.sample(rem, hc)
        samples.append(sum(_CTR.get(c, 0) for c in hand))
    samples.sort()
    return (samples[len(samples)//2], samples[int(len(samples)*0.8)], samples[int(len(samples)*0.95)])


def _record(state, action, me_idx):
    me = state.players[me_idx]; opp = state.players[1 - me_idx]
    rec = {
        "turn": state.turn_number, "player_idx": me_idx,
        "action": type(action).__name__,
        "my_don_active": me.don_active, "my_hand": len(me.hand), "my_life": len(me.life),
        "opp_leader": opp.leader.card.card_id, "opp_hand": len(opp.hand),
        "opp_life": len(opp.life), "opp_trash_n": len(opp.trash),
    }
    # 戦闘詳細
    if isinstance(action, (AttackLeader, AttackCharacter)):
        atk = me.leader if me.leader.instance_id == action.attacker_iid else next(
            (c for c in me.characters if c.instance_id == action.attacker_iid), None)
        if atk:
            rec["atk_power"] = int(atk.power); rec["atk_attached_don"] = atk.attached_dons
        rec["target_kind"] = "leader" if isinstance(action, AttackLeader) else "char"
    # 相手 counter 上界の確率推定(read)+ 実 counter(ground truth) — 攻撃決定のみ(高速化)
    if isinstance(action, (AttackLeader, AttackCharacter)):
        try:
            cc = _counter_ceiling(opp.leader.card.card_id, opp)
            if cc:
                rec["opp_counter_ceil_p50"], rec["opp_counter_ceil_p80"], rec["opp_counter_ceil_p95"] = cc
                rec["opp_leader_power"] = int(opp.leader.power)
        except Exception:
            pass
    rec["opp_actual_counter_total"] = sum(_CTR.get(c.card_id, 0) for c in opp.hand)
    rec["action_detail"] = _action_detail(action)  # どのカード/対象/ドン数
    rec["state"] = _full_state(state)               # game の完全 state
    return rec


def _record_defense(state, attacker, target, is_leader_attack, defender, result, def_idx):
    """防御決定 (choose_defense の帰結) を記録。 = メインフェーズ外の盲点を埋める。
    block_iid=ブロッカー instance_id (or None)、 counters=手札 index tuple。"""
    block_iid, counters = result
    # ⚠ engine は attacker.power + on-attack 自己バフ で守る。 素 power だと過小評価 → 実効値を使う
    est_buff = 0
    try:
        if state.effects_overlay:
            from engine.effects import estimate_attacker_self_buff
            est_buff = estimate_attacker_self_buff(state, attacker, state.effects_overlay)
    except Exception:
        est_buff = 0
    atk_p = int(attacker.power) + int(est_buff); tgt_p = int(target.power)
    ctot = 0
    for idx in (counters or ()):
        if 0 <= idx < len(defender.hand):
            ctot += _CTR.get(defender.hand[idx].card_id, 0)
    bpow = None
    if block_iid is not None:
        b = next((c for c in defender.characters if c.instance_id == block_iid), None)
        bpow = int(b.power) if b else None
    cap = sum(_CTR.get(c.card_id, 0) for c in defender.hand)  # 手札の総 counter 量
    blocked = block_iid is not None
    rec = {
        "kind": "defense", "turn": state.turn_number, "player_idx": def_idx,
        "action": "Defend", "is_leader_attack": is_leader_attack,
        "atk_power": atk_p, "atk_base": int(attacker.power), "atk_buff": int(est_buff),
        "target_power": tgt_p,
        "my_life": len(defender.life), "my_hand": len(defender.hand),
        "def_counter_capacity": cap,
        "blocked": blocked, "block_power": bpow,
        "counter_spent": ctot, "counter_cards": len(counters or ()),
        "opp_leader": state.players[state.turn_player_idx].leader.card.card_id,
    }
    # 実効攻撃力 atk_p で判定 (公式 7-1-4: defender は atk より strictly greater で無効化)。
    #  survivable = 手札 counter で「厳密に上回れた」(= 生存できた) — capacity > gap なら subset で超過可
    gap = atk_p - tgt_p
    survivable = (not blocked) and gap > 0 and cap > gap
    rec["nullified"] = (blocked and (bpow or 0) > atk_p) or (not blocked and (tgt_p + ctot) > atk_p)
    rec["over_counter"] = (not blocked) and ctot > 0 and (tgt_p + ctot - 1000) > atk_p
    # ⭐ 負け筋: 守れたのに counter を切らず被弾。 特に my_life==1 = 守れば死を回避できたのに死んだ
    rec["under_defense"] = survivable and ctot == 0
    rec["died_when_survivable"] = survivable and ctot == 0 and len(defender.life) == 1 and is_leader_attack
    rec["attacker_iid"] = getattr(attacker, "instance_id", None)
    rec["state"] = _full_state(state)  # game の完全 state
    return rec


def _wrap(ai, records):
    orig = ai.choose_action
    def wrapped(state):
        act = orig(state)
        try:
            if state.phase.name == "MAIN":
                records.append(_record(state, act, state.turn_player_idx))
        except Exception:
            pass
        return act
    ai.choose_action = wrapped
    return ai


def _wrap_defense(ai, records, real_st, def_idx):
    """choose_defense をラップ。 real_st と identity 一致する呼び出しのみ記録 (= beam sim
    は clone 上で走るので pollution しない)。"""
    orig = ai.choose_defense
    def wrapped(state, attacker, target, is_leader_attack, defender):
        result = orig(state, attacker, target, is_leader_attack, defender)
        try:
            if state is real_st:
                records.append(_record_defense(state, attacker, target,
                                               is_leader_attack, defender, result, def_idx))
        except Exception:
            pass
        return result
    ai.choose_defense = wrapped
    return ai


# ── 効果発動判断のフック(= trigger / optional-cost 発動 = メインフェーズ外の残る盲点)──
# should_fire_* は AI メソッドでなく effects.py のモジュール関数。 monkeypatch で包み、
# real state 同一性で beam sim の clone 呼び出しを除外して記録する。
import engine.effects as _EFF  # noqa: E402
_HCTX = {"st": None, "rec": None}  # 現在の real state と records を wrapper に橋渡し
_ORIG = {}


def _pidx(state, player):
    return 0 if player is state.players[0] else 1


def _install_effect_hooks():
    if _ORIG:
        return
    _ORIG["sft"] = _EFF.should_fire_trigger
    _ORIG["eot"] = _EFF._ai_should_fire_end_of_turn_cost
    _ORIG["oac"] = _EFF._ai_should_fire_opp_attack_cost

    def _sft(state, defender, card, overlay):
        r = _ORIG["sft"](state, defender, card, overlay)
        try:
            if state is _HCTX["st"] and _HCTX["rec"] is not None:
                _HCTX["rec"].append({
                    "kind": "trigger", "turn": state.turn_number,
                    "player_idx": _pidx(state, defender), "action": "FireTrigger",
                    "card": card.card_id, "fired": bool(r),
                    "my_life": len(defender.life), "my_hand": len(defender.hand),
                    "state": _full_state(state)})
        except Exception:
            pass
        return r

    def _eot(state, owner, source, eff):
        r = _ORIG["eot"](state, owner, source, eff)
        try:
            if state is _HCTX["st"] and _HCTX["rec"] is not None:
                _HCTX["rec"].append({
                    "kind": "opt_cost_eot", "turn": state.turn_number,
                    "player_idx": _pidx(state, owner), "action": "FireEndTurnCost",
                    "source": source.card.card_id, "fired": bool(r),
                    "my_don_active": owner.don_active, "my_hand": len(owner.hand),
                    "state": _full_state(state)})
        except Exception:
            pass
        return r

    def _oac(state, me, source_inplay, eff, attacker=None):
        r = _ORIG["oac"](state, me, source_inplay, eff, attacker)
        try:
            if state is _HCTX["st"] and _HCTX["rec"] is not None:
                _HCTX["rec"].append({
                    "kind": "opt_cost_onattack", "turn": state.turn_number,
                    "player_idx": _pidx(state, me), "action": "FireOnAttackCost",
                    "source": source_inplay.card.card_id, "fired": bool(r),
                    "my_don_active": me.don_active, "my_hand": len(me.hand),
                    "state": _full_state(state)})
        except Exception:
            pass
        return r

    _EFF.should_fire_trigger = _sft
    _EFF._ai_should_fire_end_of_turn_cost = _eot
    _EFF._ai_should_fire_opp_attack_cost = _oac


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="cardrush_1467"); ap.add_argument("--b", default="tcgportal_bonney")
    ap.add_argument("--seed", type=int, default=7001)
    ap.add_argument("--n", type=int, default=1, help="game 数")
    ap.add_argument("--first-player", type=int, default=-1,
                    help="席固定: 0=deck a(hero)先攻 / 1=deck b先攻 / -1=g%%2 で交互(既定)")
    ap.add_argument("--out", default="db/_analyst/learning_log_test.jsonl")
    a = ap.parse_args()
    _install_effect_hooks()  # trigger / optional-cost 発動判断を記録可能に
    all_records = []
    p0_wins = 0; done = 0
    for g in range(a.n):
        seed = a.seed + g
        fp = a.first_player if a.first_player in (0, 1) else (g % 2)
        st = setup_game(_deck(a.a), _deck(a.b), rng=random.Random(seed),
                        first_player=fp, effects_overlay=_OV)  # 先後(席固定 or 交互)
        play_until_main(st)
        records = []
        # マリガン決定 (setup 内で確定済) を記録 = 盲点その2
        _mul_state = _full_state(st)
        for i, slug in ((0, a.a), (1, a.b)):
            records.append({"kind": "mulligan", "player_idx": i, "turn": 0,
                            "did_mulligan": bool(getattr(st.players[i], "did_mulligan", False)),
                            "hand_after": len(st.players[i].hand),
                            "state": _mul_state})
        ais = [_wrap(ExploitBeamAI(rng=random.Random(seed*5+1), beam_width=16, max_depth=10, deck_analysis={"deck_slug": a.a}), records),
               _wrap(ExploitBeamAI(rng=random.Random(seed*7+3), beam_width=16, max_depth=10, deck_analysis={"deck_slug": a.b}), records)]
        # 防御決定を記録 (real state identity で beam sim を除外) = 盲点その1
        for i in (0, 1):
            _wrap_defense(ais[i], records, st, i)
        # 効果発動フックに現在の real state / records を橋渡し (= trigger/optional-cost)
        _HCTX["st"] = st; _HCTX["rec"] = records
        n = 0
        while not st.game_over and st.turn_number < 50 and n < 500:
            cur = st.turn_player_idx
            try:
                play_one_action(st, ais[cur], ais[1 - cur])
            except Exception:
                break
            n += 1
        winner = getattr(st, "winner", -1)
        # ⚠ setup_game は first_player で席順を入替える → deck a(Enel) は first_player==0 の時
        # players[0]、 first_player==1 の時 players[1]。
        enel_idx = 0 if fp == 0 else 1
        if st.game_over:
            done += 1
            if winner == enel_idx:
                p0_wins += 1
        for r in records:
            r["game"] = g
            r["y"] = 1 if r["player_idx"] == winner else 0
        all_records += records
    outp = R / a.out; outp.parent.mkdir(exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    records = all_records
    print(f"=== self-play: {a.a}(Enel) vs {a.b}(Bonney)  {a.n}game ===")
    print(f"Enel 勝率: {p0_wins}/{done} = {p0_wins/max(1,done)*100:.0f}%")
    kc = Counter(r.get("kind") or "main" for r in records)
    print(f"学習log: {len(records)} 決定を {outp} に保存")
    print(f"  内訳: " + " / ".join(f"{k} {v}" for k, v in kc.most_common()))
    # 攻撃決定のサンプル(defense を除く main phase 攻撃のみ)
    atks = [r for r in records if r.get("kind") is None and r.get("atk_power")]
    print(f"\n=== 攻撃決定のサンプル({len(atks)}件中2件)===")
    for r in atks[:2]:
        print(json.dumps(r, ensure_ascii=False))
    ok = [r for r in atks if "opp_counter_ceil_p95" in r]
    if ok:
        cov = sum(1 for r in ok if r["opp_actual_counter_total"] <= r["opp_counter_ceil_p95"]) / len(ok)
        print(f"calibration(攻撃{len(ok)}件): 相手実counter ≤ 推定p95 = {cov*100:.0f}%")
    # 防御決定のサンプル + 集計(新規=盲点埋め)
    defs = [r for r in records if r.get("kind") == "defense"]
    if defs:
        print(f"\n=== 防御決定のサンプル({len(defs)}件中2件)===")
        for r in defs[:2]:
            print(json.dumps(r, ensure_ascii=False))
        blk = sum(1 for r in defs if r["blocked"])
        cspent = sum(1 for r in defs if r["counter_spent"] > 0)
        over = sum(1 for r in defs if r.get("over_counter"))
        thru = sum(1 for r in defs if r.get("let_through"))
        print(f"防御集計: ブロック {blk} / counter使用 {cspent} / over_counter {over} / let_through {thru}")
    # 効果発動判断のサンプル + 集計(新規=trigger/optional-cost 盲点埋め)
    for kind, jp in (("trigger", "トリガー発動"), ("opt_cost_onattack", "被攻撃時cost効果"),
                     ("opt_cost_eot", "ターン終了時cost効果")):
        rs = [r for r in records if r.get("kind") == kind]
        if rs:
            fired = sum(1 for r in rs if r.get("fired"))
            print(f"\n=== {jp}({kind}) {len(rs)}件: 発動 {fired} / 見送り {len(rs)-fired} ===")
            print("  例: " + json.dumps(rs[0], ensure_ascii=False))


if __name__ == "__main__":
    main()
