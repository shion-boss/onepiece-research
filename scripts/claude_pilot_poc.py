# -*- coding: utf-8 -*-
"""Claude 操縦 PoC(2026-07-07): 「Claude 提案 → rollout オラクル検証 → 蒸留」ループの土台。

extract: 配備エネル AI の実対局から hero(エネル)の判断局面を抽出 → 人間可読レンダリング(公式テキスト付)
         + 再現情報(決定論 replay の ordinal)+ 各局面の legal actions と配備 AI の選択を json 保存。
verify : Claude が選んだ手 index を受け、 各局面を replay → 「Claude の手 vs 配備 AI の手」を残りデッキ
         再シャッフルの paired rollout で実勝率比較。 Claude の手が勝てば「探索が拾えない改善」の証拠。

  .venv/bin/python scripts/claude_pilot_poc.py extract --n 10
  .venv/bin/python scripts/claude_pilot_poc.py verify --choices 3,1,0,... --rollouts 16
"""
from __future__ import annotations
import argparse, json, random, sys, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import (setup_game, play_until_main, legal_actions, apply_action,
                         AttackLeader, AttackCharacter, ActivateMain, PlayCharacter,
                         PlayEvent, PlayStage, AttachDonToLeader, AttachDonToCharacter, EndPhase)
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.plan_search import fast_clone

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")

# ── 固定ゲーム設定(extract と verify で共有 = 決定論 replay)──────────────────
# ⭐ env で hero/opp を差し替え可能 (2026-07-27、 grind-control 検証用):
#   PILOT_HERO=cardrush_1342 PILOT_OPP=cardrush_1385 = ドフラ(control) vs クロコ(大型midrange)
import os as _os
HERO_DECK = _os.environ.get("PILOT_HERO", "cardrush_1454")   # 既定 エネル(後方互換)
OPP_DECK = _os.environ.get("PILOT_OPP", "tcgportal_calgara")
GAME_SEED = int(_os.environ.get("PILOT_SEED", "12345"))
HERO_AI_SEED = 555
OPP_AI_SEED = 777
FIRST_PLAYER = 0                  # hero = player 0
POS_FILE = ROOT / "db" / "_analyst" / "claude_pilot_positions.json"
CORPUS_FILE = ROOT / "db" / "_analyst" / "claude_pilot_corpus.jsonl"  # 検証済み改善の蓄積(蒸留元)


def _deck(slug):
    return make_deck_from_dict(json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO)


def _mk_ai(slug, seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": slug})


def _name(state, iid):
    for p in state.players:
        for c in [p.leader] + list(p.characters):
            if getattr(c, "instance_id", None) == iid:
                return c.card.name, int(getattr(c, "power", 0) or 0)
    return f"iid{iid}", 0


def _kw(c):
    ks = []
    for k in ("ブロッカー", "速攻", "ダブルアタック", "バニッシュ"):
        try:
            if c.has_keyword_active(k):
                ks.append(k)
        except Exception:
            pass
    return ks


def render_action(state, a, me_idx):
    if isinstance(a, AttackLeader):
        n, p = _name(state, a.attacker_iid)
        return f"攻撃: {n}(pow {p}) → 相手リーダー"
    if isinstance(a, AttackCharacter):
        n, p = _name(state, a.attacker_iid)
        tn, tp = _name(state, a.target_iid)
        return f"攻撃: {n}(pow {p}) → 相手キャラ {tn}(pow {tp})"
    if isinstance(a, ActivateMain):
        n, _ = _name(state, a.source_iid)
        return f"効果発動: {n} の起動メイン効果[{a.effect_index}]"
    if isinstance(a, PlayCharacter):
        c = state.players[me_idx].hand[a.hand_idx]
        sac = ""
        if getattr(a, "sacrifice_iid", None):
            sn, _ = _name(state, a.sacrifice_iid)
            sac = f" (生贄 {sn})"
        return f"登場: {c.name}(cost {c.cost}, pow {c.power}){sac}"
    if isinstance(a, PlayEvent):
        c = state.players[me_idx].hand[a.hand_idx]
        return f"イベント: {c.name}(cost {c.cost})"
    if isinstance(a, PlayStage):
        c = state.players[me_idx].hand[a.hand_idx]
        return f"ステージ: {c.name}(cost {c.cost})"
    if isinstance(a, AttachDonToLeader):
        return f"DON付与: リーダーに ×{a.n}"
    if isinstance(a, AttachDonToCharacter):
        n, p = _name(state, a.target_iid)
        return f"DON付与: {n}(pow {p}) に ×{a.n}"
    if isinstance(a, EndPhase):
        return "ターン終了"
    return type(a).__name__


def render_position(state, me_idx):
    me = state.players[me_idx]; opp = state.players[1 - me_idx]
    L = []
    L.append(f"### ターン {state.turn_number} — 手番: あなた(hero {HERO_DECK} P{me_idx})")
    lead = me.leader
    L.append(f"**自リーダー**: {lead.card.name}(pow {int(lead.power)}) 付与DON {lead.attached_dons}")
    if lead.card.text:
        L.append(f"    効果: {lead.card.text.strip()}")
    L.append(f"**自DON**: active {me.don_active} / rested {getattr(me,'don_rested',0)} / 総 {me.total_don}"
             f"(山残 {getattr(me,'don_remaining_in_deck','?')})")
    L.append(f"**自ライフ**: {len(me.life)}")
    if me.characters:
        L.append("**自キャラ**:")
        for c in me.characters:
            tags = []
            if c.rested: tags.append("レスト")
            if getattr(c, "summoning_sickness", False) and not getattr(c, "is_rush_now", False): tags.append("召喚酔い")
            if c.attached_dons: tags.append(f"DON{c.attached_dons}")
            tags += _kw(c)
            tg = f" [{', '.join(tags)}]" if tags else ""
            L.append(f"  - {c.card.name}(pow {int(c.power)}){tg}")
            if c.card.text: L.append(f"      効果: {c.card.text.strip()[:180]}")
    else:
        L.append("**自キャラ**: なし")
    L.append("**自手札**:")
    for c in me.hand:
        cnt = f" counter{c.counter}" if c.counter else " counter-"
        L.append(f"  - {c.card.name if hasattr(c,'card') else c.name}(cost {c.cost}, pow {c.power},{cnt}, {c.category})")
        txt = (c.text or "").strip()
        if txt: L.append(f"      {txt[:180]}")
    # 相手
    ol = opp.leader
    L.append(f"\n**相手リーダー**: {ol.card.name}(pow {int(ol.power)}) 付与DON {ol.attached_dons}")
    L.append(f"**相手ライフ**: {len(opp.life)} / **相手手札**: {len(opp.hand)}枚 / "
             f"**相手DON**: active {opp.don_active} 総 {opp.total_don}")
    if opp.characters:
        L.append("**相手キャラ**:")
        for c in opp.characters:
            tags = []
            if c.rested: tags.append("レスト")
            if c.attached_dons: tags.append(f"DON{c.attached_dons}")
            tags += _kw(c)
            tg = f" [{', '.join(tags)}]" if tags else ""
            L.append(f"  - {c.card.name}(pow {int(c.power)}){tg}")
    else:
        L.append("**相手キャラ**: なし")
    return "\n".join(L)


def _interesting(state, acts):
    non_end = [a for a in acts if not isinstance(a, EndPhase)]
    return len(non_end) >= 4


def _winrate_of(st, action_idx, n=8, base_seed=0):
    """局面 st で action_idx を打った後の hero 勝率(quick rollout、 balanced 判定用)。"""
    w = 0.0
    for si in range(n):
        b = fast_clone(st); _reshuffle(b, base_seed + si)
        w += _rollout(b, legal_actions(b)[action_idx], [_mk_ai(HERO_DECK, 300 + si), _mk_ai(OPP_DECK, 400 + si)])
    return w / n


def do_extract(n_positions, seed_base=GAME_SEED):
    positions = []
    md = [f"# Claude 操縦 PoC — {HERO_DECK} 判断局面(競り合いのみ)\n",
          f"対戦: {HERO_DECK}(P0)vs {OPP_DECK}(P1)。 各局面で **あなた(hero)** の最善手を 1 つ選ぶ。\n",
          "配備 AI の手で勝率 0.3-0.7 の decidable 局面だけ抽出(負け/勝ち確定局面は手の質を測れない)。\n"]
    g = 0
    scanned = 0
    while len(positions) < n_positions and g < 60:
        st = setup_game(_deck(HERO_DECK), _deck(OPP_DECK), rng=random.Random(seed_base + g),
                        first_player=FIRST_PLAYER, effects_overlay=_OVERLAY)
        play_until_main(st)
        ais = [_mk_ai(HERO_DECK, HERO_AI_SEED + seed_base + g), _mk_ai(OPP_DECK, OPP_AI_SEED + seed_base + g)]
        ordinal = -1
        steps = 0
        while not st.game_over and st.turn_number < 50 and steps < 500 and len(positions) < n_positions:
            tp = st.turn_player_idx
            acts = legal_actions(st)
            if tp == 0:
                ordinal += 1
                if _interesting(st, acts) and st.turn_number >= 3 and ordinal % 2 == 0:
                    dep_idx = None
                    try:
                        dep = ais[0].choose_action(fast_clone(st))
                        for i, a in enumerate(acts):
                            if a == dep: dep_idx = i; break
                    except Exception:
                        pass
                    scanned += 1
                    # balanced フィルタ: 配備手の勝率が decidable 範囲か
                    if dep_idx is not None:
                        wr = _winrate_of(fast_clone(st), dep_idx, n=8, base_seed=91 * scanned)
                        if 0.30 <= wr <= 0.70:
                            pid = len(positions)
                            rendered = render_position(st, 0)
                            md.append(f"\n---\n\n## 局面 {pid}(game {seed_base}+{g}, 配備手勝率≈{wr:.2f})\n")
                            md.append(rendered)
                            md.append("\n**選択肢**:")
                            for i, a in enumerate(acts):
                                md.append(f"  [{i}] {render_action(st, a, 0)}")
                            pkl = POS_FILE.parent / f"pilot_pos_{seed_base}_{pid}.pkl"
                            pkl.write_bytes(pickle.dumps(fast_clone(st)))
                            positions.append({"pid": pid, "game": seed_base + g, "n_actions": len(acts),
                                              "deployed_idx": dep_idx, "pkl": str(pkl),
                                              "dep_winrate": round(wr, 3), "render": rendered,
                                              "action_reprs": [render_action(st, a, 0) for a in acts]})
                            print(f"  局面 {pid} 採用(game {seed_base}+{g}, 配備手勝率 {wr:.2f}), scanned {scanned}", flush=True)
            try:
                play_one_action(st, ais[tp], ais[1 - tp])
            except Exception:
                break
            steps += 1
        g += 1
    POS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POS_FILE.write_text(json.dumps({"positions": positions}, ensure_ascii=False, indent=1), encoding="utf-8")
    md_path = ROOT / "db" / "_analyst" / "claude_pilot_positions.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"[extract] {len(positions)} 局面 → {md_path}")
    print(f"          配備 AI の選択(deployed_idx)は json に格納(md には非表示 = bias 回避)")


# ── verify ───────────────────────────────────────────────────────────────
def _replay_to(ordinal):
    """決定論 replay で hero の ordinal 番目の判断局面まで進めて返す。"""
    st = setup_game(_deck(HERO_DECK), _deck(OPP_DECK), rng=random.Random(GAME_SEED),
                    first_player=FIRST_PLAYER, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [_mk_ai(HERO_DECK, HERO_AI_SEED), _mk_ai(OPP_DECK, OPP_AI_SEED)]
    ord_cur = -1
    steps = 0
    while not st.game_over and steps < 500:
        tp = st.turn_player_idx
        if tp == 0:
            ord_cur += 1
            if ord_cur == ordinal:
                return st, ais
        try:
            play_one_action(st, ais[tp], ais[1 - tp])
        except Exception:
            break
        steps += 1
    return None, None


def _reshuffle(state, seed):
    r = random.Random(seed)
    for p in state.players:
        d = list(getattr(p, "deck", []))
        r.shuffle(d); p.deck = d


def _rollout(state, action, drivers):
    try:
        apply_action(state, action)
    except Exception:
        return 0.5
    steps = 0
    while not state.game_over and state.turn_number < 50 and steps < 400:
        cur = state.turn_player_idx
        try:
            play_one_action(state, drivers[cur], drivers[1 - cur])
        except Exception:
            break
        steps += 1
    if not state.game_over:
        return 0.5
    w = getattr(state, "winner", -1)
    return 1.0 if w == 0 else (0.0 if w == 1 else 0.5)


def do_verify(choices, rollouts):
    data = json.loads(POS_FILE.read_text(encoding="utf-8"))["positions"]
    if len(choices) != len(data):
        print(f"⚠ choices {len(choices)} != positions {len(data)}");
    sum_c = sum_d = 0.0; n = 0
    claude_better = dep_better = tie = 0
    for pos, my_idx in zip(data, choices):
        st = pickle.loads(Path(pos["pkl"]).read_bytes())  # 正確な保存局面(replay 不要)
        acts = legal_actions(st)
        if my_idx >= len(acts):
            print(f"  局面{pos['pid']}: index {my_idx} 範囲外(n={len(acts)})"); continue
        dep_idx = pos["deployed_idx"]
        if dep_idx is not None and dep_idx >= len(acts):
            dep_idx = None
        wc = wd = 0.0
        for si in range(rollouts):
            seed = 4441 * (pos["pid"] + 1) + si
            b1 = fast_clone(st); _reshuffle(b1, seed)
            wc += _rollout(b1, legal_actions(b1)[my_idx], [_mk_ai(HERO_DECK, 100 + si), _mk_ai(OPP_DECK, 200 + si)])
            if dep_idx is not None:
                b2 = fast_clone(st); _reshuffle(b2, seed)
                wd += _rollout(b2, legal_actions(b2)[dep_idx], [_mk_ai(HERO_DECK, 100 + si), _mk_ai(OPP_DECK, 200 + si)])
            else:
                wd += 0.5
        wc /= rollouts; wd /= rollouts
        sum_c += wc; sum_d += wd; n += 1
        d = wc - wd
        if d > 0.08: claude_better += 1
        elif d < -0.08: dep_better += 1
        else: tie += 1
        my_r = pos["action_reprs"][my_idx]
        dep_r = pos["action_reprs"][dep_idx] if dep_idx is not None else "?"
        print(f"  局面{pos['pid']}: Claude {wc:.2f}[{my_r}] vs 配備 {wd:.2f}[{dep_r}]  Δ{d:+.2f}")
        # ⭐ 検証済み改善(Claude が明確に良い)を corpus に蓄積 = 蒸留元
        if d >= 0.15 and dep_idx is not None:
            with open(CORPUS_FILE, "a", encoding="utf-8") as cf:
                cf.write(json.dumps({"pid": pos["pid"], "game": pos.get("game"),
                                     "dep_winrate": pos.get("dep_winrate"),
                                     "claude_move": my_r, "deployed_move": dep_r,
                                     "win_claude": round(wc, 3), "win_deployed": round(wd, 3),
                                     "delta": round(d, 3), "render": pos.get("render", "")},
                                    ensure_ascii=False) + "\n")
    if n:
        print(f"\n=== PoC 結果({n}局面 × {rollouts} rollouts)===")
        print(f"平均勝率: Claude {sum_c/n:.3f} vs 配備 {sum_d/n:.3f}  (Δ {(sum_c-sum_d)/n:+.3f})")
        print(f"Claude が明確に良い: {claude_better} / 配備が良い: {dep_better} / 互角: {tie}")
        print(f"corpus(検証済み改善 Δ≥0.15)= {CORPUS_FILE}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    pe = sub.add_parser("extract"); pe.add_argument("--n", type=int, default=10)
    pe.add_argument("--seed-base", type=int, default=GAME_SEED)
    pv = sub.add_parser("verify")
    pv.add_argument("--choices", required=True, help="カンマ区切りの index(局面順)")
    pv.add_argument("--rollouts", type=int, default=16)
    a = ap.parse_args()
    if a.mode == "extract":
        do_extract(a.n, a.seed_base)
    else:
        choices = [int(x) for x in a.choices.split(",")]
        do_verify(choices, a.rollouts)


if __name__ == "__main__":
    main()
