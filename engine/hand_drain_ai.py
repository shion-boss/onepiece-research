"""HandDrainAI = 「とにかく相手の手札を減らすことだけに専念する」実験 AI (2026-07-27)。

OPTCG の統一原則「手札を削るゲーム」を極端に純化: 自ターンを beam 探索し、 **葉の評価を
『相手の手札枚数(少ないほど良い)』だけ**にする。 lethal(勝ち)は別枠で必ず優先。

自然に出る挙動(要求値の思想が創発するか の観察用):
- 攻撃すると相手は防御でカウンター(手札)を切る → 相手手札↓ が高評価 → 攻撃を選ぶ。
- ただしリーダー攻撃を「受けられる」と ライフ→手札 で相手手札が**増える** → その攻撃は低評価に
  なる(= 受けられると損な攻撃を避け、 カウンターを強要する攻撃を好む = 要求値の萌芽)。
- hand_disrupt 効果(相手手札を捨てさせる)も相手手札↓ なので好まれる。

⚠ これは「勝つ AI」ではなく「相手手札を削る挙動」を見る実験。 配備はしない。
  比較は scripts/ab_hand_drain.py で ExploitBeam と対戦させ、 挙動と勝率を観察する。
"""
from __future__ import annotations

import random
from typing import Optional

from .ai import GreedyAI
from .core import Phase
from .game import EndPhase, apply_action, legal_actions
from .plan_search import fast_clone, _apply_with_defense

_LETHAL = 10_000_000.0


class HandDrainAI(GreedyAI):
    """自ターンを beam 探索し、 相手手札枚数のみを最小化する。 lethal は必ず取る。"""

    def __init__(self, rng: Optional[random.Random] = None, *, beam_width: int = 8,
                 max_depth: int = 8, deck_analysis: Optional[dict] = None, **kwargs) -> None:
        super().__init__(rng=rng, deck_analysis=deck_analysis)
        self.beam_width = beam_width
        self.max_depth = max_depth

    def _score(self, st, me: int, opp: int) -> float:
        """葉 (= 自ターン中の局面) の評価 = 相手の総防御資源を減らすこと。

        ⭐ ohtsuki 指摘 (2026-07-27): 相手手札だけを見ると、 ライフ攻撃を受けられて 手札が増える
        (life→手札) 局面を過剰に罰してしまう。 だが **ライフが減ると その後の攻撃でカウンターを
        強要できる (受けられなくなる) = 手札を削れる状況になる** ので、 ライフ減少は進捗であり
        罰すべきでない。 → 相手の防御資源を NNA = 手札 + ライフ×2 (docs/optcg) でモデル化して最小化。
          - ライフ攻撃を受けられた: 手札+1・ライフ-1 → 資源 -1 (net 減る) = 罰さない ✓
          - ライフ攻撃をカウンター: 手札-1 → 資源 -1 ✓  (= どう対応されても資源が減る)
        """
        if getattr(st, "game_over", False):
            w = getattr(st, "winner", -1)
            return _LETHAL if w == me else -_LETHAL
        op = st.players[opp]
        # ⭐ ohtsuki 指摘 (2026-07-27): キャラ攻撃は「手札を割かせる or 盤面を失わせる」の二択を
        # 強要する。 相手がキャラを守りたい場面ではライフ攻撃より手札を削れる。 手札+ライフだけだと
        # 「相手がキャラを見捨てて KO」 させた時に score 変化ゼロ(盤面除去を評価できない)。
        # → 相手盤面(キャラ)も総資源に算入。 これで キャラ攻撃は counter(手札減)でも KO(盤面減)でも
        # score が改善 = どちらの防御反応でも相手を削れる攻撃として正しく評価される。
        opp_board = sum(1.0 + c.power / 10000.0 for c in op.characters)   # キャラ数 + power 重み
        opp_defense = len(op.hand) + 2 * len(op.life) + opp_board   # 手札 + ライフ×2 + 盤面
        # 相手総資源が少ないほど高評価。 微小 tiebreak: 自手札は多い方が良い(次ターンの弾)。
        return -1000.0 * opp_defense + 1.0 * len(st.players[me].hand)

    def choose_action(self, state):
        me = state.turn_player_idx
        opp = 1 - me

        # === リーサル最優先 (user 要望: リーサル計算は残す、 行けそうなら狙う) ===
        # GreedyAI の lethal_planner (= 厳密化済、 DON 配分最適化 + ブロッカー/ダブル考慮) を
        # 手札削り beam の前に挟む。 勝てるなら確実に取る。 None なら手札削りへ。
        try:
            from .game import AttackLeader as _AL
            actions0 = legal_actions(state)
            atk_leader = [a for a in actions0 if isinstance(a, _AL)]
            if atk_leader:
                me_p = state.players[me]
                opp_p = state.players[opp]
                est_buff = 0
                if state.effects_overlay:
                    try:
                        from .effects import estimate_opp_attack_buff_to_leader
                        est_buff = estimate_opp_attack_buff_to_leader(
                            state, opp_p, state.effects_overlay)
                    except Exception:
                        est_buff = 0
                est_def = opp_p.leader.power + est_buff

                def _atk_inplay(iid):
                    if me_p.leader.instance_id == iid:
                        return me_p.leader
                    for c in me_p.characters:
                        if c.instance_id == iid:
                            return c
                    return None
                lethal_action = self._compute_lethal_action(
                    state, atk_leader, est_def, _atk_inplay)
                if lethal_action is not None:
                    return lethal_action
        except Exception:
            pass

        defender = GreedyAI(rng=self.rng)

        # frontier: (state, first_action, score)。 first_action = そのプランの初手 (= 実際に返す手)。
        root = fast_clone(state)
        frontier = [(root, None, self._score(root, me, opp))]
        best_first = None
        best_score = -1e18

        for _ in range(self.max_depth):
            expanded = []
            for st, first, _sc in frontier:
                # 自ターンが終わった / ゲーム終了 = 完了プラン → 評価して best 更新
                if getattr(st, "game_over", False) or st.turn_player_idx != me \
                        or st.phase != Phase.MAIN:
                    sc = self._score(st, me, opp)
                    if sc > best_score:
                        best_score, best_first = sc, first
                    continue
                las = legal_actions(st)
                if not las:
                    las = [EndPhase()]
                for a in las:
                    ch = fast_clone(st)
                    try:
                        _apply_with_defense(ch, a, defender)
                    except Exception:
                        continue
                    f = first if first is not None else a
                    expanded.append((ch, f, self._score(ch, me, opp)))
            if not expanded:
                break
            # EndPhase 到達 or 深さ上限に達した枝も完了候補として best に反映
            for st, first, sc in expanded:
                if getattr(st, "game_over", False) or st.turn_player_idx != me \
                        or st.phase != Phase.MAIN:
                    if sc > best_score:
                        best_score, best_first = sc, first
            expanded.sort(key=lambda x: x[2], reverse=True)
            frontier = expanded[: self.beam_width]

        # frontier 末端(深さ上限)も評価
        for st, first, sc in frontier:
            if sc > best_score:
                best_score, best_first = sc, first

        if best_first is not None:
            return best_first
        # fallback: 手が無ければターン終了
        las = legal_actions(state)
        return las[0] if las else EndPhase()
