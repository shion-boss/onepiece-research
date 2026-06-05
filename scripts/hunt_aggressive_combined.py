# -*- coding: utf-8 -*-
"""max-aggression 戦術 × 全オラクル統合 の エンジンバグ hunt (= 2026-06-05)。

⭐ ねらい: 攻撃を最大化すると **off-turn トリガー解決** (= ライフトリガー /【KO時】/ カウンター /
【相手のアタック時】) が多発する。 これは actor 文脈 (= modal を跨ぐ me/opp) を最も酷使する経路。
2026-06-05 の actor-context 修正 (execute_effect chokepoint + _actor_idx 中央復元) の検証 +
関連バグ hunt を兼ねる。

戦術 = max-aggression: 毎ターン 全キャラ・リーダーで攻撃、 キャラ展開、 防御は 全手段
(ブロッカー + counter 値 + カウンターイベント click +【相手のアタック時】効果) を使う。

オラクル (settled = action待ち / game_over で適用、 false-positive 原理ゼロのみ):
  - INV-P  各プレイヤーのメインデッキ札 (deck+hand+trash+life+chars+stages) = baseline (= 50) 不変
           (= SemanticReferee 相当、 複製/消失/相手ゾーン誤操作 を捕捉)
  - INV-DON  active+rested+attached+remaining = deck_size 不変 (= DON 台帳)
  - INV-REF  RuleReferee 構造 (フィールド≤5 / カテゴリ整合 / instance一意 / 非負)
  - crash / STUCK / NO_ACT / engine-error(log)

  python scripts/hunt_aggressive_combined.py [N_PER_PAIR]
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fuzz_human_play as F  # noqa: E402
from engine.referee import RuleReferee  # noqa: E402

F._setup()
DECKS = F.DECKS


def _per_player_card_counts(state):
    return [
        len(p.deck) + len(p.hand) + len(p.trash) + len(p.life)
        + len(p.characters) + len(p.stages)
        for p in state.players
    ]


def _don_ledger(p):
    att = sum(getattr(ip, "attached_dons", 0) or 0 for ip in [p.leader, *p.characters])
    return p.don_active + p.don_rested + att + p.don_remaining_in_deck


def check_all(state, base_cards, base_don):
    """全オラクルを settled 点で適用。 違反メッセージ (空=OK)。"""
    # INV-P: 各プレイヤー保存則
    counts = _per_player_card_counts(state)
    for pi, (now, b) in enumerate(zip(counts, base_cards)):
        if now != b:
            return f"INV-P p{pi} 札数 {now}!={b} (複製/消失/相手ゾーン誤操作)"
    # INV-DON
    for pi, p in enumerate(state.players):
        if _don_ledger(p) != base_don[pi]:
            return f"INV-DON p{pi} 台帳 {_don_ledger(p)}!={base_don[pi]}"
    # INV-REF: RuleReferee 構造
    ref = RuleReferee(strict=False)
    ref.after_action(state)
    if ref.violations:
        return f"INV-REF {ref.violations[0][:90]}"
    return None


def modal_pick(pl, rng):
    """攻撃的: 効果は発動寄り、 候補は多めに pick。"""
    k = pl.get("kind")
    lim = int(pl.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]
    if k in ("optional_cost_confirm", "replace_ko_optional", "reveal_top_play_confirm",
             "on_attack_optional", "on_opp_attack_optional", "end_of_turn_optional",
             "life_taken_choice", "view_life_top_choose_position", "option_pick"):
        return [1]  # 常に発動/最初の選択肢 (= 効果連鎖を最大化)
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        cs = pl.get("candidates") or pl.get("cards") or []
        o = list(range(len(cs)))
        rng.shuffle(o)
        return o
    if k == "search_top_n":
        cs = pl.get("cards", [])
        m = [c["idx"] for c in cs if c.get("matches_filter")]
        return m[:lim] if m else ([cs[0]["idx"]] if cs else [])
    cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    return list(range(min(lim, len(cs)))) if cs else []


def do_defense(s, pl, rng):
    """全防御手段を使う: counter event click → opp_attack 効果 → blocker + counter 値。"""
    ce = pl.get("counter_event_idxs") or []
    avail = pl.get("available_opp_attack_effects") or []
    blk = pl.get("legal_blocker_iids") or []
    cnt = pl.get("legal_counter_card_idxs") or []
    cnt_val = [i for i in cnt if i not in ce]
    if ce and rng.random() < 0.7:
        s.apply_human_use_counter_event(ce[0])
        return
    if avail and rng.random() < 0.6:
        e = avail[0]
        s.apply_human_use_opp_attack_effect(e["source_iid"], e["effect_idx"])
        return
    s.apply_human_defense(blk[0] if blk else None, cnt_val[:3])


def pick_action(acts, rng):
    """max-aggression: 攻撃 > 展開 > 効果 > ドン付与 > End。"""
    atk = [x for x in acts if x.get("kind") in ("AttackLeader", "AttackCharacter")]
    plays = [x for x in acts if x.get("kind") in ("PlayCharacter", "PlayStage")]
    main = [x for x in acts if x.get("kind") == "ActivateMain"]
    att = [x for x in acts if x.get("kind") in ("AttachDonToCharacter", "AttachDonToLeader")]
    if atk and rng.random() < 0.7:
        return rng.choice(atk)
    if plays and rng.random() < 0.7:
        return rng.choice(plays)
    if main and rng.random() < 0.5:
        return rng.choice(main)
    if att and rng.random() < 0.5:
        return rng.choice(att)
    non_end = [x for x in acts if x.get("kind") != "EndPhase"]
    if non_end and rng.random() < 0.5:
        return rng.choice(non_end)
    return next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])


def play(a, b, seed, hf):
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None
    same = 0
    base_cards = None
    base_don = None
    while not s.state.game_over and steps < 3000:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(s.state.players[0].hand), len(s.state.players[1].hand),
               len(s.state.players[0].characters), len(s.state.players[1].characters))
        if sig == last:
            same += 1
            if same > 120:
                return ("STUCK", steps, sig)
        else:
            same = 0
            last = sig
        if pk == "action":
            if base_cards is None:
                base_cards = _per_player_card_counts(s.state)
                base_don = [_don_ledger(p) for p in s.state.players]
            v = check_all(s.state, base_cards, base_don)
            if v:
                return ("ORACLE", steps, f"turn{s.state.turn_number} :: {v}")
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None)
                s.apply_human_action(pick_action(acts, rng)["idx"])
            elif pk == "choice":
                s.apply_human_choice(modal_pick(pl, rng))
            elif pk == "defense":
                do_defense(s, pl, rng)
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps,
                    f"{type(e).__name__}: {str(e)[:70]} | {traceback.format_exc().splitlines()[-2][:70]}")
    if base_cards is not None:
        v = check_all(s.state, base_cards, base_don)
        if v:
            return ("ORACLE", steps, f"(final) {v}")
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90])
    return ("OK", steps, None)


def _pairs():
    ps = [(d, d) for d in DECKS]
    for i, d in enumerate(DECKS):
        for j in (1, 2, 3):
            ps.append((d, DECKS[(i + j) % len(DECKS)]))
    return ps


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    n = nums[0] if nums else 8
    pairs = _pairs()
    bugs = []
    res = Counter()
    total = 0
    for idx, (a, b) in enumerate(pairs):
        for sd in range(n):
            gs = 100000 + sd * 17
            st, steps, info = play(a, b, gs, sd % 2 == 0)
            res[st] += 1
            total += 1
            if st != "OK":
                bugs.append((a, b, gs, sd % 2 == 0, st, info))
        if idx % 8 == 0:
            print(f"  ... {a} vs {b} | total {total} bugs {len(bugs)}", flush=True)
    print(f"\n=== max-aggression × 全オラクル hunt {total} 試合 ===")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭30):")
        for a, b, sd, hf, st, info in bugs[:30]:
            print(f"  ★[{st}] {a} vs {b} seed={sd} hf={hf}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
