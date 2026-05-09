# -*- coding: utf-8 -*-
"""
AI プレイヤー
============

* RandomAI       : 合法手から完全ランダム
* GreedyAI       : 単純なヒューリスティック
                   - 出せるなら一番高コストのキャラを出す
                   - キャラが場にいたら攻撃可能
                   - ドンはリーダーに付与
                   - 攻撃対象は「相手のレストキャラを優先」
                   - ブロッカーは「攻撃が通る場合のみ」使う
                   - カウンターは「リーダーへの攻撃が通りそうな時のみ」使う
* LookaheadAI    : 1-ply 先読み評価
                   - 各候補手を仮想実行 (deepcopy) → 評価関数で最善を選ぶ
                   - 評価: ライフ差 + 場キャラパワー差 + 手札差 + ドン差
                   - 防御は GreedyAI のロジックを継承
"""

from __future__ import annotations

import copy
import random
from typing import Optional

from .core import GameState, InPlay, Phase, Player, Category
from .game import (
    Action,
    ActivateMain,
    AttachDonToCharacter,
    AttachDonToLeader,
    AttackCharacter,
    AttackLeader,
    EndPhase,
    PlayCharacter,
    PlayEvent,
    PlayStage,
    apply_action,
    legal_actions,
)


class RandomAI:
    name = "Random"

    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()

    # メインフェーズの行動選択
    def choose_action(self, state: GameState) -> Action:
        actions = legal_actions(state)
        return self.rng.choice(actions)

    # 防御側の選択(ブロッカー、カウンター) - 防御側が手番を取る部分
    def choose_defense(
        self,
        state: GameState,
        attacker: InPlay,
        target: InPlay,
        is_leader_attack: bool,
        defender: Player,
    ) -> tuple[Optional[int], tuple[int, ...]]:
        """戻り値: (blocker_iid or None, 使うカウンター手札 idx タプル)"""
        # ランダム: 50% で防御
        if self.rng.random() < 0.3:
            counters = [i for i, c in enumerate(defender.hand) if c.counter > 0]
            if counters:
                return None, (self.rng.choice(counters),)
        return None, ()


class GreedyAI:
    name = "Greedy"

    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()

    def choose_action(self, state: GameState) -> Action:
        actions = legal_actions(state)
        me = state.turn_player

        # 0) 起動メイン効果は基本撃つ(ノーコスト寄りなので)
        act_main = [a for a in actions if isinstance(a, ActivateMain)]
        if act_main:
            return act_main[0]

        # 0.5) 撃てるイベントは安い順で消化 (リソース消費を抑える)
        play_event_actions: list[PlayEvent] = [a for a in actions if isinstance(a, PlayEvent)]
        if play_event_actions:
            return min(play_event_actions, key=lambda a: me.hand[a.hand_idx].cost)

        # 0.7) ステージは現状空のとき登場 (差替の判断はしない、安全側)
        play_stage_actions: list[PlayStage] = [a for a in actions if isinstance(a, PlayStage)]
        if play_stage_actions and len(me.stages) == 0:
            return min(play_stage_actions, key=lambda a: me.hand[a.hand_idx].cost)

        # 1) 出せるキャラがあれば、一番コストが高いものを出す(コスト効率優先)
        play_actions: list[PlayCharacter] = [a for a in actions if isinstance(a, PlayCharacter)]
        if play_actions:
            best = max(play_actions, key=lambda a: me.hand[a.hand_idx].cost)
            return best

        # 2) 攻撃可能ならアタック(ドンを足してから)
        atk_char_actions = [a for a in actions if isinstance(a, AttackCharacter)]
        atk_leader_actions = [a for a in actions if isinstance(a, AttackLeader)]

        # ドンを攻撃前にリーダー or キャラに付与(打点を上げる)
        if me.don_active >= 1 and (atk_char_actions or atk_leader_actions):
            # まずリーダーで攻撃するなら、リーダーに付与
            attach_leader = [a for a in actions if isinstance(a, AttachDonToLeader)]
            if not me.leader.rested and attach_leader and me.leader.attached_dons < 4:
                return AttachDonToLeader(n=1)

        if atk_char_actions:
            return self.rng.choice(atk_char_actions)
        if atk_leader_actions:
            return self.rng.choice(atk_leader_actions)

        # 4) フェーズ終了
        return EndPhase()

    def choose_defense(
        self,
        state: GameState,
        attacker: InPlay,
        target: InPlay,
        is_leader_attack: bool,
        defender: Player,
    ) -> tuple[Optional[int], tuple[int, ...]]:
        atk_p = attacker.power
        life_left = len(defender.life)
        # ライフ残量による defensive weight (低いほど守りに行く)
        # life=0 はそもそもアタックが通る = 敗北なので必死、life>=4 は余裕
        defensive_weight = max(0, 5 - life_left)  # 0..5

        # ステップ1: ブロッカー候補を評価
        block_iid: Optional[int] = None
        block_kept_alive = False
        if not attacker.has_no_block_now and is_leader_attack:
            best = None
            for c in defender.characters:
                if c.rested or c.summoning_sickness or not c.is_blocker_now:
                    continue
                survives = c.power >= atk_p
                # 評価: 生き残るブロッカーが最優先、次にパワー高いもの
                score = (1 if survives else 0, c.power)
                if best is None or score > best[0]:
                    best = (score, c)
            if best is not None:
                survives, blocker = best[0][0], best[1]
                # ブロッカー使う条件:
                #  - 生存できる: 常に使う (ライフを守れて損失ゼロ)
                #  - 生存できない: ライフ残量 1〜2 (致命) 時のみ犠牲ブロック
                if survives:
                    block_iid = blocker.instance_id
                    block_kept_alive = True
                elif life_left <= 1:
                    block_iid = blocker.instance_id

        # ステップ2: カウンター値を決定
        target_power = defender.leader.power if is_leader_attack else target.power
        if block_iid is not None:
            blocker = next(c for c in defender.characters if c.instance_id == block_iid)
            target_power = blocker.power

        gap = atk_p - target_power
        if gap < 0:
            # 既に防御パワーが上回る → カウンター不要
            return block_iid, ()

        # キャラ攻撃にカウンター切らない (resource 温存)
        if not is_leader_attack:
            return block_iid, ()

        # ライフ残量別ポリシー
        # life >= 4: 1ヒット許容OK。カウンター切らずに落とす
        if life_left >= 4 and gap <= 1000:
            return block_iid, ()
        # life >= 3 で gap が大きい (>3000) なら、カウンター高くつくので諦める
        if life_left >= 3 and gap > 4000:
            return block_iid, ()

        # 最適カウンター組み合わせ: gap を超える最小コンボ (合計カウンター値最小化)
        spent = self._optimal_counter_combo(defender.hand, gap)
        if not spent:
            return block_iid, ()

        # 防御コスト過多チェック: life>=2 で 3 枚以上のカウンターを使うのは過剰防衛
        if life_left >= 2 and len(spent) >= 3:
            return block_iid, ()

        return block_iid, tuple(spent)

    def _optimal_counter_combo(self, hand: list, gap: int) -> list[int]:
        """gap を超える最小コンボを brute force で探す (手札 < 12 想定)。
        同点なら使うカウンター値合計が小さい方を選ぶ。
        """
        counter_idxs = [i for i, c in enumerate(hand) if c.counter > 0]
        if not counter_idxs:
            return []

        # 全 subset 生成 (最大 2^11 = 2048)
        n = len(counter_idxs)
        if n > 11:
            # 多すぎる場合は降順 greedy fallback
            counter_idxs.sort(key=lambda i: -hand[i].counter)
            spent = []
            total = 0
            for i in counter_idxs:
                spent.append(i)
                total += hand[i].counter
                if total > gap:
                    return spent
            return []

        best: tuple[int, int, list[int]] | None = None  # (size, sum, idxs)
        for mask in range(1, 1 << n):
            picked = [counter_idxs[i] for i in range(n) if mask & (1 << i)]
            total = sum(hand[i].counter for i in picked)
            if total <= gap:
                continue
            key = (len(picked), total)
            if best is None or key < best[:2]:
                best = (len(picked), total, picked)
        return best[2] if best else []


class LookaheadAI(GreedyAI):
    """1-ply 先読み AI。各合法手を仮想実行 → 評価関数で最善を選択。

    防御選択 (choose_defense) は GreedyAI のロジックを継承。
    """

    name = "Lookahead"

    # 評価関数の重み
    W_LIFE = 1500
    W_FIELD_COUNT = 1200
    W_FIELD_POWER = 1
    W_HAND = 250
    W_DON = 200
    W_GAME_OVER = 1_000_000

    def choose_action(self, state: "GameState") -> "Action":
        actions = legal_actions(state)
        if len(actions) <= 1:
            return actions[0] if actions else EndPhase()

        me_idx = state.turn_player_idx
        best_action = actions[0]
        best_score = -float("inf")

        for action in actions:
            # state を deepcopy して仮想実行 (副作用を本物に出さない)
            sim = copy.deepcopy(state)
            try:
                apply_action(sim, action)
            except Exception:
                # 不正手はスキップ
                continue
            score = self._evaluate(sim, me_idx)
            if score > best_score:
                best_score = score
                best_action = action

        return best_action

    def _evaluate(self, state: "GameState", me_idx: int) -> float:
        # ゲーム終了は決定的シグナル
        if state.game_over:
            return self.W_GAME_OVER if state.winner == me_idx else -self.W_GAME_OVER

        me = state.players[me_idx]
        opp = state.players[1 - me_idx]

        life_diff = len(me.life) - len(opp.life)
        field_count_diff = len(me.characters) - len(opp.characters)
        field_power_diff = sum(c.power for c in me.characters) - sum(
            c.power for c in opp.characters
        )
        hand_diff = len(me.hand) - len(opp.hand)
        don_diff = me.total_don - opp.total_don

        return (
            life_diff * self.W_LIFE
            + field_count_diff * self.W_FIELD_COUNT
            + field_power_diff * self.W_FIELD_POWER
            + hand_diff * self.W_HAND
            + don_diff * self.W_DON
        )


# --------------------------------------------------------------------------- #
# 攻撃時の防御を組み込んだ apply ラッパー
# --------------------------------------------------------------------------- #
def play_one_action(state: GameState, ai_self, ai_opp) -> Action:
    """ターンプレイヤーの 1 アクションを選んで適用。攻撃時は防御側の判断を入れる。"""
    action = ai_self.choose_action(state)

    # 攻撃時: ブロッカー / カウンターを差し込む
    if isinstance(action, AttackLeader):
        from .game import _find_attacker  # noqa
        attacker = _find_attacker(state.turn_player, action.attacker_iid)
        block_iid, counters = ai_opp.choose_defense(
            state, attacker, state.opponent.leader, True, state.opponent
        )
        # AttackLeader にはブロッカー枠がないが MVP では無視
        action = AttackLeader(attacker_iid=action.attacker_iid, counter_card_idxs=counters)

    elif isinstance(action, AttackCharacter):
        from .game import _find_attacker, _find_character  # noqa
        attacker = _find_attacker(state.turn_player, action.attacker_iid)
        target = _find_character(state.opponent, action.target_iid)
        block_iid, counters = ai_opp.choose_defense(
            state, attacker, target, False, state.opponent
        )
        action = AttackCharacter(
            attacker_iid=action.attacker_iid,
            target_iid=action.target_iid,
            counter_card_idxs=counters,
            blocker_iid=block_iid,
        )

    apply_action(state, action)
    return action
