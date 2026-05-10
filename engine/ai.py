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

    def __init__(
        self,
        rng: Optional[random.Random] = None,
        deck_analysis: Optional[dict] = None,
    ):
        self.rng = rng or random.Random()
        self.deck_analysis = deck_analysis  # 使わない (Random は分析無視)

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

    def __init__(
        self,
        rng: Optional[random.Random] = None,
        deck_analysis: Optional[dict] = None,
    ):
        self.rng = rng or random.Random()
        self.deck_analysis = deck_analysis
        # アーキタイプ別ヒューリスティックパラメータ
        # default = ミッドレンジ (= 既存の挙動)
        self.archetype = "ミッドレンジ"
        # 防御パラメータ: ライフ別に counter を切る上限と枚数
        # 値: { life: (max_total, max_cards) }
        self.defense_thresholds = {
            1: (99999, 99),  # 致命: 全力
            2: (8000, 3),
            3: (6000, 2),
            4: (2000, 1),
        }
        # 攻撃パラメータ: gap_tolerance = リーダー攻撃の安全マージン
        # (= attacker.power >= leader.power + tolerance なら攻撃)
        self.attack_gap_tolerance = 0
        # フィニッシャー温存判定の閾値 (高コスト = key_cards 由来)
        self.finisher_card_ids: set[str] = set()
        # ramp 系優先 (起動メイン無条件発動)
        self.prioritize_ramp = False

        if deck_analysis:
            self._apply_archetype_profile(deck_analysis)

    def _apply_archetype_profile(self, analysis: dict) -> None:
        """deck_analysis からアーキタイプ別の挙動パラメータを設定。"""
        arche = analysis.get("archetype", "ミッドレンジ")
        self.archetype = arche
        if arche == "アグロ":
            # ライフ詰め優先、 counter 控えめ、 攻撃 gap=0 でも積極的
            self.defense_thresholds = {
                1: (99999, 99),
                2: (5000, 2),    # 控えめ
                3: (3000, 1),    # かなり控えめ
                4: (0, 0),       # ライフ余裕時はほぼ counter 切らず攻める
            }
            self.attack_gap_tolerance = -1000  # gap = atk - def が +tolerance 以上で攻撃 → -1000 = 1000 不足でも攻めて良い (= ぎりぎり通る攻撃も)
        elif arche == "コントロール":
            # 序盤耐え、 counter 厚め、 リーダー攻撃は安全策のみ
            self.defense_thresholds = {
                1: (99999, 99),
                2: (10000, 4),
                3: (8000, 3),
                4: (5000, 2),    # 余裕時も counter で予防
            }
            self.attack_gap_tolerance = 1000  # gap+1000 確保した攻撃のみ (確実に通る)
        elif arche == "ランプ":
            # DON 加速優先、 攻撃は中盤以降
            self.prioritize_ramp = True
            self.defense_thresholds = {
                1: (99999, 99),
                2: (8000, 3),
                3: (7000, 2),
                4: (3000, 1),
            }
            self.attack_gap_tolerance = 0
        # ミッドレンジは default

        # フィニッシャー (= role: finisher) のカード ID をストア
        for k in analysis.get("key_cards", []):
            if k.get("role") == "finisher":
                self.finisher_card_ids.add(k.get("card_id", ""))

    def choose_action(self, state: GameState) -> Action:
        actions = legal_actions(state)
        me = state.turn_player
        opp = state.opponent

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

        # 2) アタック判断
        atk_char_actions: list[AttackCharacter] = [a for a in actions if isinstance(a, AttackCharacter)]
        atk_leader_actions: list[AttackLeader] = [a for a in actions if isinstance(a, AttackLeader)]

        def _atk_inplay(iid: int) -> Optional[InPlay]:
            if me.leader.instance_id == iid:
                return me.leader
            for c in me.characters:
                if c.instance_id == iid:
                    return c
            return None

        def _opp_chara(iid: int) -> Optional[InPlay]:
            for c in opp.characters:
                if c.instance_id == iid:
                    return c
            return None

        # 2a) キャラ KO 狙い: atk.power >= target.power のものから (相手コスト高優先)
        viable_char: list[tuple[AttackCharacter, InPlay, InPlay]] = []
        for a in atk_char_actions:
            attacker = _atk_inplay(a.attacker_iid)
            target = _opp_chara(a.target_iid)
            if attacker and target and attacker.power >= target.power:
                viable_char.append((a, attacker, target))
        if viable_char:
            a, _, _ = max(viable_char, key=lambda x: (x[2].card.cost, x[2].power))
            return a

        # 防御側のリアクティブ buff (opp_attack で opp.leader を強化する効果) を見積。
        # 例: 紫ドフラ / 赤青エース 等の「相手アタック時 リーダー +N」効果が発動した時、
        # 実際の defender_power は opp.leader.power + est_buff になる。
        est_opp_buff = 0
        if state.effects_overlay:
            from .effects import estimate_opp_attack_buff_to_leader
            est_opp_buff = estimate_opp_attack_buff_to_leader(
                state, opp, state.effects_overlay
            )
        est_defender_power = opp.leader.power + est_opp_buff

        # 2b) ドン付与で leader 攻撃を成立させる
        # 候補: gap=est_defender_power - attacker.power が 0 < gap <= 1000 (1ドンで届く)
        # または gap == 0 (届くが、念押しで上乗せして counter 抗力を上げる)
        if me.don_active >= 1 and atk_leader_actions:
            don_candidates: list[tuple[int, InPlay]] = []
            for a in atk_leader_actions:
                attacker = _atk_inplay(a.attacker_iid)
                if attacker is None or attacker.attached_dons >= 4:
                    continue
                gap = est_defender_power - attacker.power
                if 0 <= gap <= 1000:
                    don_candidates.append((gap, attacker))
            if don_candidates:
                # 小さい gap 優先 (= 1ドンで成立)。同 gap なら attached_dons 少ない方
                don_candidates.sort(key=lambda x: (x[0], x[1].attached_dons))
                _, attacker = don_candidates[0]
                if attacker is me.leader:
                    return AttachDonToLeader(n=1)
                else:
                    return AttachDonToCharacter(target_iid=attacker.instance_id, n=1)

        # 2c) リーダー攻撃判定。リーサル可能なら全力、そうでなければアタック順を最適化。
        # est_defender_power + アーキタイプ別 gap_tolerance に基づいてフィルタ
        # (アグロ: tolerance=-1000 で攻めっ気、 コントロール: +1000 で安全策)
        attack_threshold = est_defender_power + self.attack_gap_tolerance
        viable_leader: list[tuple[AttackLeader, InPlay]] = []
        for a in atk_leader_actions:
            attacker = _atk_inplay(a.attacker_iid)
            if attacker and attacker.power >= attack_threshold:
                viable_leader.append((a, attacker))
        if viable_leader:
            # リーサル判定: 自分の合計打点で相手 life + 防御パワー を超えるか?
            # 相手 counter で +N 防御される可能性は手札枚数 × 平均カウンター値で見積
            opp_life = len(opp.life)
            opp_hand = len(opp.hand)
            # 平均カウンター推定: 手札 1 枚あたり 1500 (= 1k〜2k カウンター混合)
            est_counter_per_card = 1500
            # ライフ 1 枚 = 1 ヒット必要 (ダブルアタックは無視、簡略)
            hits_to_lethal = opp_life
            if hits_to_lethal == 0:
                # life 0 状態 = 次ヒットで勝利
                hits_to_lethal = 1
            # 各 attacker の打点 - opp_leader.power を打点として集計
            damage_potentials = sorted(
                [(a, atk.power - opp.leader.power) for a, atk in viable_leader],
                key=lambda x: -x[1],  # 大打点から
            )
            top_n = damage_potentials[:hits_to_lethal]
            total_excess = sum(d for _, d in top_n)
            # リーサル成立条件: 上位 hits_to_lethal 攻撃の合計 excess >
            # (相手の使えるカウンター総量) → 全部受け止められない
            est_max_defense = est_counter_per_card * opp_hand
            is_lethal = (
                len(top_n) >= hits_to_lethal
                and total_excess >= est_max_defense
            )
            if is_lethal:
                # リーサル: 最大打点から順に攻撃 (確実に通る)
                return top_n[0][0]
            # 通常: 「弱→強」順で攻撃 (相手の counter 抗力を消費させる)
            # 低 excess (= ぎりぎり通る) を先、高 excess を最後に
            ordered = sorted(viable_leader, key=lambda x: x[1].power)
            return ordered[0][0]

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
        # attacker のリアクティブ自己強化 (= on_attack で self/self_leader +N)
        # を予測して実効攻撃力を見積もる。 これを忘れると 「6000 攻撃に 1000 counter で
        # 6000 vs 6000 = 攻撃成功」 となり counter が無駄になる。
        est_attacker_buff = 0
        if state.effects_overlay:
            from .effects import estimate_attacker_self_buff
            est_attacker_buff = estimate_attacker_self_buff(
                state, attacker, state.effects_overlay
            )
        atk_p = attacker.power + est_attacker_buff
        life_left = len(defender.life)

        # ステップ1: ブロッカー候補を評価 (実効 atk_p で生存判定)
        block_iid: Optional[int] = None
        if not attacker.has_no_block_now and is_leader_attack:
            best = None
            for c in defender.characters:
                if c.rested or c.summoning_sickness or not c.is_blocker_now:
                    continue
                survives = c.power >= atk_p
                score = (1 if survives else 0, c.power)
                if best is None or score > best[0]:
                    best = (score, c)
            if best is not None:
                survives, blocker = best[0][0], best[1]
                if survives:
                    block_iid = blocker.instance_id
                elif life_left <= 1:
                    block_iid = blocker.instance_id

        # ステップ2: 防御パワー算出 (ブロッカー切ってたらブロッカー、それ以外は元の対象)
        target_power = defender.leader.power if is_leader_attack else target.power
        if block_iid is not None:
            blocker = next(c for c in defender.characters if c.instance_id == block_iid)
            target_power = blocker.power

        # gap = 実効攻撃力 - 防御パワー。 公式 7-1-4: atk >= def で攻撃側勝ち、
        # よって defender は gap+1 以上の counter を切らないと意味がない。
        gap = atk_p - target_power
        if gap < 0:
            # 既に防御パワーが上回る → カウンター不要
            return block_iid, ()

        spent = self._optimal_counter_combo(defender.hand, gap)
        if not spent:
            return block_iid, ()
        counter_total = sum(defender.hand[i].counter for i in spent)

        if is_leader_attack:
            # アーキタイプ別の閾値テーブルを参照 (defense_thresholds)
            life_key = max(1, min(life_left, 4))
            max_total, max_cards = self.defense_thresholds.get(
                life_key, (2000, 1)
            )
            if life_left <= 1:
                # 致命: 閾値無視で全力
                return block_iid, tuple(spent)
            if counter_total <= max_total and len(spent) <= max_cards:
                return block_iid, tuple(spent)
            return block_iid, ()

        # キャラ攻撃 (= KO) の防御: コスト4以上の高価値ターゲットを 1 枚 (≤2000) で守る
        if target.card.cost >= 4 and len(spent) <= 1 and counter_total <= 2000:
            return block_iid, tuple(spent)
        return block_iid, ()

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


class EvalGreedyAI(GreedyAI):
    """GreedyAI の高速ヒューリスティックフィルタ + 1-ply eval tie-break。

    GreedyAI の choose_action は「これは絶対やる」「これは絶対やらない」の判定で
    候補を 1 つに絞ることが多いが、 同点・複数候補のケースで eval (9 指標) を使って
    最善を選ぶ。 LookaheadAI より高速 (= 全手探索でなく Greedy の filter 通過手のみ評価)。

    - 起動メイン / イベント / ステージ / キャラ登場: GreedyAI の判定をそのまま使う
    - キャラ攻撃 / リーダー攻撃: viable な候補から eval で最高 score の手を選ぶ
    - 防御選択 (choose_defense): GreedyAI を継承
    """

    name = "EvalGreedy"

    def choose_action(self, state: GameState) -> Action:
        actions = legal_actions(state)
        me = state.turn_player
        opp = state.opponent

        # 0)〜1) 起動メイン / イベント / ステージ / キャラ登場 → GreedyAI と同じ
        act_main = [a for a in actions if isinstance(a, ActivateMain)]
        if act_main:
            return self._eval_pick(state, act_main)

        play_event_actions = [a for a in actions if isinstance(a, PlayEvent)]
        if play_event_actions:
            return self._eval_pick(state, play_event_actions)

        play_stage_actions = [a for a in actions if isinstance(a, PlayStage)]
        if play_stage_actions and len(me.stages) == 0:
            return min(play_stage_actions, key=lambda a: me.hand[a.hand_idx].cost)

        play_actions = [a for a in actions if isinstance(a, PlayCharacter)]
        if play_actions:
            return self._eval_pick(state, play_actions)

        # 2) アタック判断: GreedyAI のフィルタを再利用してから eval で tie-break
        atk_char_actions = [a for a in actions if isinstance(a, AttackCharacter)]
        atk_leader_actions = [a for a in actions if isinstance(a, AttackLeader)]

        # 候補リスト (GreedyAI と同様のロジックで viable なものだけ)
        viable_atks: list[Action] = []

        def _atk_inplay(iid: int) -> Optional[InPlay]:
            if me.leader.instance_id == iid:
                return me.leader
            for c in me.characters:
                if c.instance_id == iid:
                    return c
            return None

        def _opp_chara(iid: int) -> Optional[InPlay]:
            for c in opp.characters:
                if c.instance_id == iid:
                    return c
            return None

        for a in atk_char_actions:
            attacker = _atk_inplay(a.attacker_iid)
            target = _opp_chara(a.target_iid)
            if attacker and target and attacker.power >= target.power:
                viable_atks.append(a)

        # opp の reactive buff 推定 (GreedyAI と同じ)
        est_opp_buff = 0
        if state.effects_overlay:
            from .effects import estimate_opp_attack_buff_to_leader
            est_opp_buff = estimate_opp_attack_buff_to_leader(
                state, opp, state.effects_overlay
            )
        est_defender_power = opp.leader.power + est_opp_buff

        for a in atk_leader_actions:
            attacker = _atk_inplay(a.attacker_iid)
            if attacker and attacker.power >= est_defender_power:
                viable_atks.append(a)

        if viable_atks:
            return self._eval_pick(state, viable_atks)

        # ドン付与 / EndPhase は GreedyAI のロジックに委譲
        return super().choose_action(state)

    def _eval_pick(self, state: GameState, candidates: list[Action]) -> Action:
        """候補 1〜N 個から 1-ply eval で最高 score の手を選ぶ。
        候補 1 個ならそのまま返す (= deepcopy コスト節約)。"""
        if len(candidates) <= 1:
            return candidates[0]
        from .eval import compute_score
        me_idx = state.turn_player_idx
        best = candidates[0]
        best_score = -float("inf")
        for action in candidates:
            sim = copy.deepcopy(state)
            try:
                apply_action(sim, action)
            except Exception:
                continue
            score = compute_score(sim, me_idx)
            if score > best_score:
                best_score = score
                best = action
        return best


class MCTSAI(GreedyAI):
    """Monte Carlo Tree Search AI (UCT-based)。

    各 choose_action で:
      1. Selection: UCB1 で子ノードを再帰選択
      2. Expansion: 未展開アクション 1 つを子ノードに追加
      3. Simulation: GreedyAI でロールアウト (深度制限) + ヒューリスティック評価
      4. Backprop: 値を経路に伝播
      最終的に最も訪問されたアクションを返す。

    防御選択 (choose_defense) は GreedyAI を継承 (展開爆発回避)。

    パラメータ:
      n_simulations: 1 アクション選択あたりのシミュレーション数 (既定 30)
      c_uct        : UCB1 の探索係数 (既定 1.41 = sqrt(2))
      rollout_depth: ロールアウト最大ステップ (既定 12)
    """

    name = "MCTS"

    # ヒューリスティック評価重み (LookaheadAI と同方針、0-1 にスケール)
    H_LIFE = 0.05
    H_FIELD = 0.02
    H_HAND = 0.005

    def __init__(
        self,
        rng: Optional[random.Random] = None,
        n_simulations: int = 30,
        c_uct: float = 1.41,
        rollout_depth: int = 12,
        deck_analysis: Optional[dict] = None,
    ):
        super().__init__(rng, deck_analysis=deck_analysis)
        self.n_simulations = n_simulations
        self.c_uct = c_uct
        self.rollout_depth = rollout_depth

    def choose_action(self, state: "GameState") -> "Action":
        actions = legal_actions(state)
        if len(actions) <= 1:
            return actions[0] if actions else EndPhase()

        me_idx = state.turn_player_idx
        # ルートノード: state は各 simulation で deepcopy するため保存しない
        root = _MCTSNode(parent=None, action=None)
        root.unexpanded = list(actions)

        import math

        for _ in range(self.n_simulations):
            sim_state = copy.deepcopy(state)
            node = root
            path = [node]

            # 1. Selection
            while (
                not node.unexpanded
                and node.children
                and not sim_state.game_over
            ):
                node = self._best_child(node, math)
                try:
                    apply_action(sim_state, node.action)
                except Exception:
                    break
                path.append(node)

            # 2. Expansion
            if not sim_state.game_over and node.unexpanded:
                idx = self.rng.randrange(len(node.unexpanded))
                action = node.unexpanded.pop(idx)
                try:
                    apply_action(sim_state, action)
                    child = _MCTSNode(parent=node, action=action)
                    if not sim_state.game_over:
                        try:
                            child.unexpanded = list(legal_actions(sim_state))
                        except Exception:
                            child.unexpanded = []
                    node.children.append(child)
                    node = child
                    path.append(node)
                except Exception:
                    # 不正手はスキップ
                    pass

            # 3. Simulation
            value = self._rollout(sim_state, me_idx)

            # 4. Backprop
            for n in path:
                n.visits += 1
                n.total_value += value

        # 最も訪問された子を選ぶ (探索ではなく実プレイ用なので robust)
        if not root.children:
            return self.rng.choice(actions)
        best = max(root.children, key=lambda c: c.visits)
        return best.action

    def _best_child(self, node: "_MCTSNode", math_mod) -> "_MCTSNode":
        """UCB1 で子を選ぶ。"""
        log_n = math_mod.log(node.visits) if node.visits > 0 else 0.0
        best = None
        best_score = -float("inf")
        for child in node.children:
            if child.visits == 0:
                return child
            avg = child.total_value / child.visits
            ucb = avg + self.c_uct * math_mod.sqrt(log_n / child.visits)
            if ucb > best_score:
                best_score = ucb
                best = child
        return best if best else node.children[0]

    def _rollout(self, state: "GameState", me_idx: int) -> float:
        """state を深度 rollout_depth まで GreedyAI でプレイ → 終局/打切で 0-1 値を返す。"""
        rollout_ai = GreedyAI(self.rng)
        depth = 0
        while not state.game_over and depth < self.rollout_depth:
            try:
                play_one_action(state, rollout_ai, rollout_ai)
            except Exception:
                break
            depth += 1
        if state.game_over:
            if state.winner == me_idx:
                return 1.0
            elif state.winner is None:
                return 0.5
            else:
                return 0.0
        return self._heuristic_eval(state, me_idx)

    def _heuristic_eval(self, state: "GameState", me_idx: int) -> float:
        """非終局状態のヒューリスティック評価 (0-1 スケール)。
        9 指標 eval (engine/eval.py) を tanh 正規化で 0.5 ± 0.5 にマップ。"""
        from .eval import compute_score, normalized_score
        score = compute_score(state, me_idx)
        # normalized_score は -1〜+1。 0.5 + 0.5×x で 0〜1 に
        return 0.5 + 0.5 * normalized_score(score)


class _MCTSNode:
    """MCTS の探索ノード。state は保存せず action のみ記録 (root から replay)。"""

    __slots__ = ("parent", "action", "children", "unexpanded", "visits", "total_value")

    def __init__(self, parent=None, action=None):
        self.parent = parent
        self.action = action
        self.children: list["_MCTSNode"] = []
        self.unexpanded: list[Action] = []
        self.visits: int = 0
        self.total_value: float = 0.0


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
        # 9 指標の評価関数 (engine/eval.py) に委譲。
        # 旧 5 指標 (W_LIFE 等) は engine/eval.py の DEFAULT_WEIGHTS に移行済。
        from .eval import compute_score
        return compute_score(state, me_idx)


# --------------------------------------------------------------------------- #
# 攻撃時の防御を組み込んだ apply ラッパー
# --------------------------------------------------------------------------- #
def play_one_action(state: GameState, ai_self, ai_opp, referee=None) -> Action:
    """ターンプレイヤーの 1 アクションを選んで適用。攻撃時は防御側の判断を入れる。

    referee (RuleReferee) を渡すと:
      - 適用前: AI の選択が legal_actions に含まれるかチェック
      - 適用後: 不変条件 (DON 総数、フィールド超過、instance_id 重複等) をチェック
    """
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

    if referee is not None:
        referee.before_action(state, action)

    apply_action(state, action)

    if referee is not None:
        referee.after_action(state)

    return action
