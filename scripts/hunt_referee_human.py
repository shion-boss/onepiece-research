# -*- coding: utf-8 -*-
"""RuleReferee の全構造チェックを 人間セッションに当てる エンジンバグ hunt (= 2026-06-05)。

⭐ 構造ギャップ ([[project_human_play_auto_qa]] 続3): RuleReferee (engine/referee.py) は
**フィールド超過 (キャラ≤5 / ステージ≤1) / DON台帳 / instance一意 / 負値 / カテゴリ整合 / 合法手**
を検査するが、 **HumanSession は SemanticReferee (カード保存則のみ) しか配線していない**。 ⇒
人間 vs AI 実プレイでは 上記が runtime 未監視。 特に **フィールド ≤5 制約は どの人間 fuzzer も
未検査** — 召喚効果 (summon_from_deck / play_from_trash / play_from_hand) が 満杯フィールドに
キャラを突っ込んで オーバーフローしても 既存オラクルは見ない。

RuleReferee.after_action(state) は standalone (= Enel OP15-058 の deck_size=6 をハードコード判定、
baseline 不要) なので、 人間セッションの **settled 点 (action待ち / game_over) で read-only 実行**
すれば全構造チェックが効く。

tactic = field-flood: キャラ展開 + 効果発動 (= 召喚) を最優先、 攻撃を避けて場を埋め、
field_full_select_trash を反復させて 「満杯フィールドへの召喚」 を最大ストレス。

  python scripts/hunt_referee_human.py [N_PER_PAIR]
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


def referee_check(state):
    """RuleReferee の after_action を read-only で実行し、 違反メッセージ list を返す。"""
    ref = RuleReferee(strict=False)
    try:
        ref.after_action(state)
    except Exception as e:  # noqa: BLE001  (strict=False のはずだが保険)
        return [f"referee 例外: {type(e).__name__}: {e}"]
    return list(ref.violations)


def modal_pick(pl, rng):
    k = pl.get("kind")
    lim = int(pl.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]
    if k in ("optional_cost_confirm", "replace_ko_optional", "reveal_top_play_confirm",
             "on_attack_optional", "on_opp_attack_optional", "end_of_turn_optional",
             "life_taken_choice", "view_life_top_choose_position", "option_pick"):
        return [1] if rng.random() < 0.7 else [0]  # 効果発動寄り (= 召喚を誘発)
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        cs = pl.get("candidates") or pl.get("cards") or []
        o = list(range(len(cs)))
        rng.shuffle(o)
        return o
    if k == "field_full_select_trash":
        # 満杯フィールドで トラッシュ対象を選ぶ: 先頭を選んで 場を回す (= 召喚を継続させる)
        cs = pl.get("candidates") or pl.get("cards") or []
        return [0] if cs else []
    if k == "search_top_n":
        cs = pl.get("cards", [])
        matching = [c["idx"] for c in cs if c.get("matches_filter")]
        return matching[:lim] if matching else ([cs[0]["idx"]] if cs else [])
    cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    # 召喚/検索系は できるだけ多く pick (= 場を埋める)
    return list(range(min(lim, len(cs)))) if cs else []


def pick_action(acts, rng):
    """field-flood: 展開 > 効果発動 > ドン付与 >> 攻撃。 攻撃は最小限 (= 場を維持)。"""
    non_end = [x for x in acts if x.get("kind") != "EndPhase"]
    plays = [x for x in non_end if x.get("kind") in ("PlayCharacter", "PlayStage")]
    acts_main = [x for x in non_end if x.get("kind") == "ActivateMain"]
    attaches = [x for x in non_end if x.get("kind") in ("AttachDonToCharacter", "AttachDonToLeader")]
    if plays:
        return rng.choice(plays)
    if acts_main and rng.random() < 0.7:
        return rng.choice(acts_main)
    if attaches and rng.random() < 0.5:
        return rng.choice(attaches)
    if non_end and rng.random() < 0.3:  # たまに攻撃 (= KO で 場が動く局面も作る)
        return rng.choice(non_end)
    return next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])


def play(a, b, seed, hf):
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None
    same = 0
    while not s.state.game_over and steps < 3000:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(s.state.players[0].characters), len(s.state.players[1].characters),
               len(s.state.players[0].hand), len(s.state.players[1].hand))
        if sig == last:
            same += 1
            if same > 120:
                return ("STUCK", steps, sig)
        else:
            same = 0
            last = sig
        if pk == "action":
            viol = referee_check(s.state)
            if viol:
                return ("REFEREE", steps, f"turn{s.state.turn_number} :: {viol[0][:110]}")
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None)
                s.apply_human_action(pick_action(acts, rng)["idx"])
            elif pk == "choice":
                s.apply_human_choice(modal_pick(pl, rng))
            elif pk == "defense":
                # 防御は最小限 (= 攻撃を受けてキャラを温存 = 場を埋め続ける)。 たまにブロック。
                blk = pl.get("legal_blocker_iids") or []
                if blk and rng.random() < 0.2:
                    s.apply_human_defense(blk[0], [])
                else:
                    s.apply_human_defense(None, [])
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps,
                    f"{type(e).__name__}: {str(e)[:70]} | {traceback.format_exc().splitlines()[-2][:70]}")
    # 終局でも referee 検査
    viol = referee_check(s.state)
    if viol:
        return ("REFEREE", steps, f"(final) {viol[0][:120]}")
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
            gs = 90000 + sd * 11
            st, steps, info = play(a, b, gs, sd % 2 == 0)
            res[st] += 1
            total += 1
            if st != "OK":
                bugs.append((a, b, gs, sd % 2 == 0, st, info))
        if idx % 8 == 0:
            print(f"  ... {a} vs {b} | total {total} bugs {len(bugs)}", flush=True)
    print(f"\n=== RuleReferee×人間 field-flood hunt {total} 試合 ===")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭30):")
        for a, b, sd, hf, st, info in bugs[:30]:
            print(f"  ★[{st}] {a} vs {b} seed={sd} hf={hf}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
