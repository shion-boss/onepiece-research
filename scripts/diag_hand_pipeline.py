# -*- coding: utf-8 -*-
"""手札削りパイプライン診断 (2026-07-27、 ohtsuki の staged model 検証)。

ohtsuki のモデル: 削り続ける → 相手手札枯渇 → ライフが通る → リーサル圏 → 詰める、 で勝つ。
これが EBV2 vs EBV2 で実際どこまで進むかを測る:
  (Q1) 勝ちは相手手札の枯渇から来るか? = 敗者の手札は負ける前に枯渇(≤2)していたか。
  (Q2) 枯渇 → 負け か? = 手札が ≤2 になったプレイヤーのその後の勝率。
  (Q3) 枯渇せず勝つ(ライフレース)割合 = 敗者の手札が最後まで高いまま負けた割合。
  (Q4) 補充 vs 削り = 手札はターンと共に減るか(枯渇に向かうか)。
  (Q5) 枯渇時にライフは通っているか = 手札 ≤2 の局面での相手ライフ。

各ターン頭の (hand, life) を両者記録し、 終局 winner と突合。

  DIAG_SLUG=cardrush_1454 DIAG_N=100 DIAG_WORKERS=12 .venv/bin/python scripts/diag_hand_pipeline.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("DIAG_SLUG", "cardrush_1454")
LOW = 2   # 「枯渇」閾値


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _ebv2(seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": SLUG})


def _one(seed):
    fp = seed % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [_ebv2(seed * 5 + 1), _ebv2(seed * 7 + 3)]
    # 各手番の切替時に両者の (hand,life) を記録
    traj = []   # list of (turn, p0_hand, p0_life, p1_hand, p1_life)
    n = 0
    last_turn = -1
    while not state.game_over and state.turn_number < 60 and n < 1500:
        cur = state.turn_player_idx
        if state.turn_number != last_turn:
            p = state.players
            traj.append((state.turn_number, len(p[0].hand), len(p[0].life),
                         len(p[1].hand), len(p[1].life)))
            last_turn = state.turn_number
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    winner = getattr(state, "winner", -1)
    if winner not in (0, 1):
        return None
    # 終局時の hand/life
    fp0h, fp0l = len(state.players[0].hand), len(state.players[0].life)
    fp1h, fp1l = len(state.players[1].hand), len(state.players[1].life)
    return {"winner": winner, "traj": traj,
            "final": (fp0h, fp0l, fp1h, fp1l)}


def main():
    n = int(os.environ.get("DIAG_N", "100"))
    workers = int(os.environ.get("DIAG_WORKERS", "12"))
    seeds = list(range(7000, 7000 + n))
    t0 = time.time()
    print(f"[diag_pipeline] {SLUG}  EBV2 vs EBV2  N={n} (枯渇閾値 hand<={LOW})", flush=True)
    with mp.Pool(workers) as p:
        games = [g for g in p.map(_one, seeds) if g]

    ng = len(games)
    # Q1: 敗者の手札は負ける前(終局)に枯渇していたか
    loser_depleted_at_end = 0
    # Q3: 敗者の手札が最後まで高い(>LOW)まま負けた = ライフレース勝ち
    loser_high_at_end = 0
    # Q2: 「手札が LOW 以下になった」プレイヤーのその後の勝敗
    dep_then_win = 0; dep_then_lose = 0
    # Q5: 枯渇局面での相手ライフ(通っているか)
    life_at_depletion = []
    # Q4: ターン別 平均手札(全ゲーム、 手番プレイヤー視点でなく p0/p1 平均)
    hand_by_turn = defaultdict(list)

    for g in games:
        w = g["winner"]; loser = 1 - w
        fp0h, fp0l, fp1h, fp1l = g["final"]
        loser_final_hand = fp0h if loser == 0 else fp1h
        if loser_final_hand <= LOW:
            loser_depleted_at_end += 1
        else:
            loser_high_at_end += 1
        # 各プレイヤーが LOW 到達した最初のターン以降の勝敗 (= 枯渇→勝敗)
        reached = {0: False, 1: False}
        for (t, h0, l0, h1, l1) in g["traj"]:
            hand_by_turn[t].append(h0); hand_by_turn[t].append(h1)
            for pl, h, opp_life in ((0, h0, l1), (1, h1, l0)):
                if h <= LOW and not reached[pl]:
                    reached[pl] = True
                    if pl == w:
                        dep_then_win += 1
                    else:
                        dep_then_lose += 1
                    life_at_depletion.append(opp_life)

    print(f"  有効 {ng} games ({time.time()-t0:.0f}s)", flush=True)
    print(f"  [Q1] 敗者の手札が終局時に枯渇(≤{LOW})していた割合 = "
          f"{loser_depleted_at_end/max(1,ng)*100:.0f}%  (= 勝ちは枯渇から来るか)", flush=True)
    print(f"  [Q3] 敗者の手札が終局時に高い(>{LOW})まま負け = "
          f"{loser_high_at_end/max(1,ng)*100:.0f}%  (= 枯渇せずライフレースで負けた割合)", flush=True)
    dtot = dep_then_win + dep_then_lose
    print(f"  [Q2] 手札が枯渇(≤{LOW})に到達したプレイヤーのその後勝率 = "
          f"{dep_then_win/max(1,dtot)*100:.0f}%  (低いほど『枯渇→負け』= モード通り)  "
          f"[枯渇到達 {dtot} 回]", flush=True)
    if life_at_depletion:
        import statistics
        print(f"  [Q5] 枯渇した瞬間の相手ライフ 平均 = {statistics.mean(life_at_depletion):.1f}枚 "
              f"(低いほど『枯渇時にはリーサル圏』)", flush=True)
    # Q4: 手札トレンド (序盤/中盤/終盤)
    turns_sorted = sorted(hand_by_turn.keys())
    if turns_sorted:
        import statistics
        def _mh(ts):
            vals = [v for t in ts for v in hand_by_turn.get(t, [])]
            return statistics.mean(vals) if vals else 0
        early = _mh([t for t in turns_sorted if t <= 4])
        mid = _mh([t for t in turns_sorted if 5 <= t <= 8])
        late = _mh([t for t in turns_sorted if t >= 9])
        print(f"  [Q4] 平均手札トレンド: 序盤(T≤4)={early:.1f} → 中盤(T5-8)={mid:.1f} → "
              f"終盤(T≥9)={late:.1f}  (減れば枯渇に向かう、 横ばいなら補充が削りに勝つ)", flush=True)


if __name__ == "__main__":
    main()
