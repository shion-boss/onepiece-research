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

from . import card_role, hand_estimator, matchup_model
from .ai_params import AIParams
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
        ai_params: Optional[AIParams] = None,
    ):
        self.rng = rng or random.Random()
        self.deck_analysis = deck_analysis
        # AI 全体共有パラメータ (= 学習対象)。 未指定なら db/ai_params.json から読み込み。
        self.ai_params = ai_params if ai_params is not None else AIParams.load()
        # アーキタイプ別ヒューリスティックパラメータ
        # default = ミッドレンジ (= 既存の挙動)
        self.archetype = "ミッドレンジ"
        # 防御パラメータ: ライフ別に counter を切る上限と枚数
        # 値: { life: (max_total, max_cards) }
        # ai_params の base 値を初期化に使う (= ミッドレンジ default)
        self.defense_thresholds = self._default_defense_thresholds()
        # 攻撃パラメータ: gap_tolerance = リーダー攻撃の安全マージン
        # (= attacker.power >= leader.power + tolerance なら攻撃)
        self.attack_gap_tolerance = self.ai_params.attack_gap_tolerance_default
        # フィニッシャー温存判定の閾値 (高コスト = key_cards 由来)
        self.finisher_card_ids: set[str] = set()
        # ramp 系優先 (起動メイン無条件発動)
        self.prioritize_ramp = False
        # 構造化シグナル由来のフラグ (default: 全て無効)
        self.synergy_feature: Optional[str] = None
        self.tank_lifeup_ok = False
        self.avoid_life_loss = False
        self.blocker_scarce = False
        self.early_finisher_hold_ids: set[str] = set()
        self.counter_aggression = "mid"
        self.keep_field_synergy_only: Optional[str] = None
        self.preferred_search_target_ids: list[str] = []

        # マッチアップ別の override は state が確認できる初回 choose_action で 適用 (lazy)。
        # __init__ では opp.leader が分からないため、 ここでは flag のみ初期化。
        self._matchup_overrides_applied = False
        self._matchup_profile: Optional[matchup_model.MatchupProfile] = None
        self.finisher_hold_life: int = 3

        # role priority (R67): MatchupProfile 確定後に opp_archetype をキャッシュ。
        # choose_action / choose_defense で _get_role_priority() 経由で参照する。
        self._opp_archetype_for_priority: Optional[str] = None

        if deck_analysis:
            self._apply_archetype_profile(deck_analysis)

    def _default_defense_thresholds(self) -> dict:
        """AIParams から base 防御閾値 dict を構築。"""
        p = self.ai_params
        return {
            1: (p.defense_threshold_life_le_1, 99),  # 致命: 全力
            2: (p.defense_threshold_life_eq_2, 3),
            3: (p.defense_threshold_life_eq_3, 2),
            4: (p.defense_threshold_life_ge_4, 1),
        }

    def _apply_archetype_profile(self, analysis: dict) -> None:
        """deck_analysis からアーキタイプ別の挙動パラメータを設定。"""
        arche = analysis.get("archetype", "ミッドレンジ")
        self.archetype = arche

        # 構造化シグナル (ai_hint_signals) を読み取り、 各種フラグへ反映
        signals = analysis.get("ai_hint_signals") or []
        self.synergy_feature: Optional[str] = None
        self.tank_lifeup_ok = False
        self.avoid_life_loss = False
        self.blocker_scarce = False
        self.early_finisher_hold_ids: set[str] = set()
        self.counter_aggression = "mid"  # low / mid / high
        # 起動メインの「場が特徴 X のみ」 条件を守るためのシナジー外 play 抑制
        self.keep_field_synergy_only: Optional[str] = None
        # サーチ系効果の優先ターゲット ID リスト (フィニッシャー/ドロー)
        self.preferred_search_target_ids: list[str] = []
        for sig in signals:
            t = sig.get("type")
            v = sig.get("value")
            if t == "synergy_feature_priority":
                self.synergy_feature = v
            elif t == "tank_lifeup_ok":
                self.tank_lifeup_ok = bool(v)
            elif t == "avoid_life_loss":
                self.avoid_life_loss = bool(v)
            elif t == "blocker_scarce":
                self.blocker_scarce = bool(v)
            elif t == "early_finisher_hold" and isinstance(v, list):
                self.early_finisher_hold_ids = set(v)
            elif t == "counter_aggression":
                self.counter_aggression = str(v)
            elif t == "keep_field_synergy_only":
                self.keep_field_synergy_only = str(v) if v else None
            elif t == "preferred_search_target_ids" and isinstance(v, list):
                self.preferred_search_target_ids = list(v)
        if arche == "アグロ":
            # ライフ詰め優先、 counter 控えめ、 攻撃は power 不足でも狙う
            self.defense_thresholds = {
                1: (99999, 99),
                2: (5000, 2),    # 控えめ
                3: (3000, 1),    # かなり控えめ
                4: (0, 0),       # ライフ余裕時はほぼ counter 切らず攻める
            }
            # tolerance = -2000: 2000 不足でも攻撃 (= 相手 counter を強制消費させる)
            self.attack_gap_tolerance = -2000
        elif arche == "コントロール":
            # 序盤耐え、 counter 厚め、 リーダー攻撃は ほぼ等パワーで GO
            # (= +1000 の安全マージンは慎重すぎ。 中型コントロールは攻撃機会を逃すと
            #   後半リソース勝負で押し負ける)
            self.defense_thresholds = {
                1: (99999, 99),
                2: (10000, 4),
                3: (8000, 3),
                4: (5000, 2),    # 余裕時も counter で予防
            }
            # tolerance = 0 (等パワー以上で攻撃)。 「確実」 から 「等価」 へ緩和。
            self.attack_gap_tolerance = 0
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
        else:  # ミッドレンジ
            # default: ai_params.attack_gap_tolerance_default を使う (= 学習対象)。
            # defense_thresholds も __init__ で ai_params から既に初期化済み。
            self.attack_gap_tolerance = self.ai_params.attack_gap_tolerance_default
            self.defense_thresholds = self._default_defense_thresholds()

        # フィニッシャー (= role: finisher) のカード ID をストア
        for k in analysis.get("key_cards", []):
            if k.get("role") == "finisher":
                self.finisher_card_ids.add(k.get("card_id", ""))

    def _ensure_matchup_overrides(self, state: GameState, me_idx: int) -> None:
        """初回のみ MatchupProfile を構築し、 db/matchup_strategies.json の上書き値を適用。

        (my, opp) ペアごとに defense_thresholds / attack_gap_tolerance /
        finisher_hold_life を override。 該当エントリ無しなら base 値が残る。
        opp.leader.card_id が未知なら fallback で archetype を推定 (= 安全な default)。
        """
        if self._matchup_overrides_applied:
            return
        self._matchup_overrides_applied = True  # 同一試合中は 1 度のみ
        try:
            profile = matchup_model.build_matchup_profile(
                state, me_idx, self.archetype
            )
        except Exception:
            return
        self._matchup_profile = profile
        overrides = matchup_model.lookup_matchup_overrides(
            profile.my_archetype, profile.opp_archetype
        )
        if not overrides:
            return
        # attack_gap_tolerance 上書き
        if "attack_gap_tolerance" in overrides:
            self.attack_gap_tolerance = int(overrides["attack_gap_tolerance"])
        # defense_thresholds 上書き (JSON 形式 {"2": [v, n], ...} → int キー dict へ変換)
        dt_override = overrides.get("defense_thresholds")
        if isinstance(dt_override, dict):
            merged = dict(self.defense_thresholds)
            for k, v in dt_override.items():
                try:
                    life = int(k)
                except (TypeError, ValueError):
                    continue
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    merged[life] = (int(v[0]), int(v[1]))
            self.defense_thresholds = merged
        # finisher_hold_life 上書き
        if "finisher_hold_life" in overrides:
            self.finisher_hold_life = int(overrides["finisher_hold_life"])
        # role priority (R67) 用に opp_archetype をキャッシュ
        self._apply_role_priorities(profile.opp_archetype)

    def _apply_role_priorities(self, opp_archetype: str) -> None:
        """相手 archetype を保存し、 以降 choose_action で role 別 effectiveness を参照可能に。

        既存ヒント (synergy_feature / early_finisher_hold / lethal) は破壊しない。
        role priority は同点候補のタイブレーク + 高 effectiveness カードの優先選択に使う。
        """
        self._opp_archetype_for_priority = opp_archetype

    def _get_role_priority(self, card_id: str) -> int:
        """カード ID の対戦相手アーキタイプに対する有効性スコア (0..100)。

        相手 archetype 未確定 / role_db 未登録の場合は中性 50 を返す。
        """
        opp_arche = self._opp_archetype_for_priority
        if not opp_arche:
            return 50
        role_db = card_role.load_card_role_db()
        v = role_db.get(card_id)
        if not isinstance(v, dict):
            return 50
        return card_role.compute_effectiveness(
            v.get("primary_role", "synergy"),
            v.get("tags", []),
            opp_arche,
        )

    def _get_card_primary_role(self, card_id: str) -> Optional[str]:
        """カード ID の primary_role を返す。 未登録は None。"""
        role_db = card_role.load_card_role_db()
        v = role_db.get(card_id)
        if not isinstance(v, dict):
            return None
        return v.get("primary_role")

    def choose_action(self, state: GameState) -> Action:
        self._ensure_matchup_overrides(state, state.turn_player_idx)
        actions = legal_actions(state)
        me = state.turn_player
        opp = state.opponent

        # 0) 起動メイン効果: コスト無しは即発動、 ドン消費型は payoff 評価。
        # ただし「untap_don 系で don_rested が refunded 未満」 のもの (= 効果不発) は
        # PlayCharacter の後ろに後回し (= キャラ play で don_rested を貯めてから再評価)。
        act_main = [a for a in actions if isinstance(a, ActivateMain)]
        deferred_act_main: list[ActivateMain] = []
        if act_main:
            eligible = []
            for a in act_main:
                eff = self._get_activate_eff(state, a)
                if eff and self._has_useless_untap(eff, me):
                    # untap が機能しないので後回し
                    deferred_act_main.append(a)
                else:
                    eligible.append(a)
            if eligible:
                chosen = self._pick_activate_main(state, eligible)
                if chosen is not None:
                    return chosen

        # 0.5) 撃てるイベントは安い順で消化 (リソース消費を抑える)
        play_event_actions: list[PlayEvent] = [a for a in actions if isinstance(a, PlayEvent)]
        if play_event_actions:
            return min(play_event_actions, key=lambda a: me.hand[a.hand_idx].cost)

        # 0.7) ステージは現状空のとき登場 (差替の判断はしない、安全側)
        play_stage_actions: list[PlayStage] = [a for a in actions if isinstance(a, PlayStage)]
        if play_stage_actions and len(me.stages) == 0:
            return min(play_stage_actions, key=lambda a: me.hand[a.hand_idx].cost)

        # 1) 出せるキャラがあれば優先順位で選ぶ:
        #    (a) synergy_feature_priority があれば該当特徴のキャラを優先
        #    (b) early_finisher_hold: 高コストフィニッシャーは life>=3 では温存 (= プレイ候補から外す)
        #    (c) 残りの中で最大コストを選ぶ (= コスト効率)
        play_actions: list[PlayCharacter] = [a for a in actions if isinstance(a, PlayCharacter)]
        if play_actions:
            life_left = len(me.life)
            # keep_field_synergy_only: 起動メイン「場が特徴 X のみ」 条件を守る。
            # 場が既に全部シナジー特徴のキャラなら、 シナジー外を play すると条件破壊 → 除外。
            # (場にシナジー外が混在している場合は条件既に破壊済みなので何でも play 可)
            if self.keep_field_synergy_only and me.characters:
                feat = self.keep_field_synergy_only
                field_all_synergy = all(
                    feat in c.card.features for c in me.characters
                )
                if field_all_synergy:
                    synergy_only_plays = [
                        a for a in play_actions
                        if feat in me.hand[a.hand_idx].features
                    ]
                    if synergy_only_plays:
                        play_actions = synergy_only_plays
                    # シナジー候補が無ければ play_actions を絞らず、 後段の判断に委ねる
            elif self.keep_field_synergy_only and not me.characters:
                # 場が空 = これから建てる。 1 体目は必ずシナジー特徴で揃える
                feat = self.keep_field_synergy_only
                synergy_only_plays = [
                    a for a in play_actions
                    if feat in me.hand[a.hand_idx].features
                ]
                if synergy_only_plays:
                    play_actions = synergy_only_plays
            # フィニッシャー温存: ライフが finisher_hold_life 以上なら hold 対象は除外。
            # finisher_hold_life は MatchupProfile 由来 (= 相手 archetype 別調整、 default 3)。
            if life_left >= self.finisher_hold_life and self.early_finisher_hold_ids:
                non_hold = [
                    a for a in play_actions
                    if me.hand[a.hand_idx].card_id not in self.early_finisher_hold_ids
                ]
                if non_hold:
                    play_actions = non_hold
            # synergy 優先: 該当特徴を持つカードがあれば、 そこから最大コストを
            # role priority (R67): 同点候補のタイブレーク + effectiveness ≥ 70 の
            # カードがあれば cost より effectiveness を優先 (= 役割理解した選択)
            def _play_sort_key(a: PlayCharacter):
                cid = me.hand[a.hand_idx].card_id
                eff = self._get_role_priority(cid)
                # effectiveness ≥ 70 を上位ティアに、 同ティア内では cost 降順
                tier = 1 if eff >= 70 else 0
                return (tier, eff, me.hand[a.hand_idx].cost)
            if self.synergy_feature:
                synergy_plays = [
                    a for a in play_actions
                    if self.synergy_feature in me.hand[a.hand_idx].features
                ]
                if synergy_plays:
                    return max(synergy_plays, key=_play_sort_key)
            return max(play_actions, key=_play_sort_key)

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
        # role priority (R67): target の primary_role が finisher / removal / negation
        # の場合は KO 優先度を上げる (= 相手の鍵カードを潰す)。 既存の cost/power 並びに
        # 補助 boost として加算する形。
        viable_char: list[tuple[AttackCharacter, InPlay, InPlay]] = []
        for a in atk_char_actions:
            attacker = _atk_inplay(a.attacker_iid)
            target = _opp_chara(a.target_iid)
            if attacker and target and attacker.power >= target.power:
                viable_char.append((a, attacker, target))
        if viable_char:
            _high_value_roles = {"finisher", "removal", "negation"}

            def _atk_char_sort_key(x: tuple[AttackCharacter, InPlay, InPlay]):
                _, _, target = x
                role_boost = 1 if (
                    self._get_card_primary_role(target.card.card_id) in _high_value_roles
                ) else 0
                return (role_boost, target.card.cost, target.power)
            a, _, _ = max(viable_char, key=_atk_char_sort_key)
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
        # ライフトリガー (= 雷迎系) で attacker が KO されるリスクを期待損失で見積。
        # opp.life ≥ 1 かつ デッキに KO トリガーが多い場合に高コスト attacker での
        # リーダー攻撃を抑制する。 expected_loss = attacker_power × prob。
        viable_leader: list[tuple[AttackLeader, InPlay]] = []
        for a in atk_leader_actions:
            attacker = _atk_inplay(a.attacker_iid)
            if not attacker or attacker.power < attack_threshold:
                continue
            # KO リスク見積もり (= attacker_power 損失見込み)
            ko_risk = 0.0
            if state.effects_overlay and opp.life and attacker.card.cost >= 5:
                from .effects import estimate_opp_life_trigger_attacker_ko_risk
                ko_risk = estimate_opp_life_trigger_attacker_ko_risk(
                    state, opp, attacker.power, state.effects_overlay
                )
            # ライフ取得の期待利益 (= W_LIFE) = 1500 (boardEval 規模)
            life_gain = 1500
            # KO リスクが ライフ利益を超える → 攻撃を控える
            if ko_risk > life_gain * 1.5:
                continue
            viable_leader.append((a, attacker))
        if viable_leader:
            # リーサル判定: 自分の合計打点で相手 life + 防御パワー を超えるか?
            # 相手 counter は hand_estimator で公開情報 (= opp.deck+hand プール) から
            # 期待値推定。 トラッシュ済カウンター持ちは自動的にプールから外れる。
            opp_life = len(opp.life)
            opp_idx = 1 - state.turn_player_idx
            est_counter_per_card = hand_estimator.expected_counter_per_card(state, opp_idx)
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
            est_max_defense = int(est_counter_per_card * len(opp.hand))
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

        # 3) 後回しにしていた起動メイン (untap 系) を再評価
        # PlayCharacter / 攻撃で don_rested が貯まっている可能性
        if deferred_act_main:
            # 再度フィルタ: 今は don_rested が十分か?
            still_eligible = [
                a for a in deferred_act_main
                if not self._has_useless_untap(
                    self._get_activate_eff(state, a) or {}, me
                )
            ]
            if still_eligible:
                chosen = self._pick_activate_main(state, still_eligible)
                if chosen is not None:
                    return chosen

        # 4) フェーズ終了
        return EndPhase()

    def _has_useless_untap(self, eff: dict, me: Player) -> bool:
        """この起動メイン効果が untap_don を含み、 現状 don_rested 不足で発動しても
        0 ドンしか活性化できない (= 焚き損) か判定。 PlayCharacter 後に再評価するため。

        注意: untap_don 限定で判定する。 add_don / add_rested_don は「**新しい ドンをデッキから出す**」
        効果で、 don_rested に依存しないため untap 系には含めない。
        """
        untap_required = 0
        for prim in eff.get("do", []):
            for k, v in prim.items():
                if k == "untap_don":
                    if isinstance(v, int):
                        untap_required += v
                    elif isinstance(v, str) and v == "all":
                        untap_required += 1  # 1 以上なら良い
                    elif isinstance(v, dict):
                        untap_required += int(v.get("amount", 0))
        if untap_required == 0:
            return False  # untap_don 系効果なし
        # 現時点 で actually untap できる枚数 < untap_required なら無駄打ち
        return me.don_rested < untap_required

    def choose_defense(
        self,
        state: GameState,
        attacker: InPlay,
        target: InPlay,
        is_leader_attack: bool,
        defender: Player,
    ) -> tuple[Optional[int], tuple[int, ...]]:
        # defender 視点で MatchupProfile 由来の override を 初回のみ適用。
        # 防御中なので turn_player_idx は attacker、 defender_idx は その逆。
        self._ensure_matchup_overrides(state, 1 - state.turn_player_idx)
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
        if (
            not attacker.has_no_block_now
            and not attacker.attacker_prevents_blocker_until_turn_end
            and is_leader_attack
        ):
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
            # シグナル微調整: avoid_life_loss なら閾値+50%、 tank_lifeup_ok なら -30% (= 受けて手札補充重視)
            if self.avoid_life_loss:
                max_total = int(max_total * 1.5)
                max_cards = max_cards + 1
            elif self.tank_lifeup_ok:
                max_total = int(max_total * 0.7)
            # role priority (R67): attacker の primary_role が finisher なら
            # 「決め手は通すな」 で防御閾値を 1.3x 緩和 (= より積極的に counter を切る)
            if self._get_card_primary_role(attacker.card.card_id) == "finisher":
                max_total = int(max_total * 1.3)
                max_cards = max_cards + 1
            if life_left <= 1:
                return block_iid, tuple(spent)
            if counter_total <= max_total and len(spent) <= max_cards:
                return block_iid, tuple(spent)
            return block_iid, ()

        # キャラ攻撃 (= KO) の防御: コスト4以上の高価値ターゲットを 1 枚 (≤2000) で守る
        if target.card.cost >= 4 and len(spent) <= 1 and counter_total <= 2000:
            return block_iid, tuple(spent)
        return block_iid, ()

    def _get_activate_eff(self, state: GameState, act: ActivateMain) -> Optional[dict]:
        """ActivateMain の対応 effect dict を返す。 失敗時 None。"""
        overlay = state.effects_overlay
        if not overlay:
            return None
        me = state.turn_player
        src = None
        if me.leader.instance_id == act.source_iid:
            src = me.leader
        else:
            src = next(
                (c for c in me.characters if c.instance_id == act.source_iid), None
            )
        if src is None:
            return None
        bundle = overlay.get(src.card.card_id)
        if bundle is None or act.effect_index >= len(bundle.effects):
            return None
        return bundle.effects[act.effect_index]

    def _activate_main_pay_don(self, state: GameState, act: ActivateMain) -> int:
        """この ActivateMain が消費する pay_don 数を返す。 取得失敗時 0。"""
        eff = self._get_activate_eff(state, act)
        if eff is None:
            return 0
        return int(eff.get("cost", {}).get("pay_don", 0))

    def _activate_main_don_compensated(self, eff: dict) -> bool:
        """pay_don コストが do 内の untap_don/add_don で相殺される効果か?

        例: 緑紫ルフィ leader 「ドン-2 + untap_don 2」 → ドン純消費 0、 リーダーパワー up。
        この種の効果は eval delta が小さくても積極的に発動すべき (将来価値含めて中立)。
        """
        pay_don = int(eff.get("cost", {}).get("pay_don", 0))
        if pay_don == 0:
            return False
        refunded = 0
        for prim in eff.get("do", []):
            for k, v in prim.items():
                if k == "untap_don":
                    refunded += int(v) if isinstance(v, int) else int(v.get("amount", 0))
                elif k == "add_don":
                    refunded += int(v) if isinstance(v, int) else int(v.get("amount", 0))
                elif k == "add_rested_don":
                    refunded += int(v) if isinstance(v, int) else int(v.get("amount", 0))
        return refunded >= pay_don

    def _pick_activate_main(
        self, state: GameState, candidates: list[ActivateMain]
    ) -> Optional[Action]:
        """activate_main 候補から payoff の良いものを選ぶ。

        - pay_don=0 のコスト無し効果: 即 1 つ目を返す (=従来通り)
        - pay_don≥1 のドン消費型: 1-ply eval で post-pre delta を測り、 改善あれば発動。
          delta が「ドン消費分の損失」を超えるなら発動価値あり (eval 内 W_DON で
          ドン消失は既に減算されるので、 純 delta > 0 なら net gain)。
        - 全候補で payoff ≤ 0 → None (フォールスルーで他アクションへ)

        ai_params 由来のゲート (= 学習可能):
        - activate_main_don_compensated_strict: ドン相殺型でも 「DON 再投資先あり」 のみ採用
        - activate_main_min_payoff_global: ドン相殺型でも eval delta が指定値未満なら不採用
        """
        if not candidates:
            return None
        # ノーコスト効果は最優先
        free = [a for a in candidates if self._activate_main_pay_don(state, a) == 0]
        if free:
            return free[0]

        # don 相殺型 (pay_don を untap_don/add_don で取り戻す)
        # ai_params のゲート: strict=True なら「DON 再投資先あり」 のみ、
        # min_payoff_global > 0 なら eval delta チェック
        strict = self.ai_params.activate_main_don_compensated_strict
        min_payoff = self.ai_params.activate_main_min_payoff_global
        from .eval import compute_score
        me_idx = state.turn_player_idx
        for a in candidates:
            eff = self._get_activate_eff(state, a)
            if not (eff and self._activate_main_don_compensated(eff)):
                continue
            # gate 1: strict モード = DON 再投資先 / power_pump 利用先があるか
            if strict and not self._don_compensated_useful_now(state, eff):
                continue
            # gate 2: min_payoff > 0 なら eval delta 要求
            if min_payoff > 0:
                pre = compute_score(state, me_idx)
                sim = copy.deepcopy(state)
                try:
                    apply_action(sim, a)
                except Exception:
                    continue
                post = compute_score(sim, me_idx)
                if post - pre < min_payoff:
                    continue
            return a

        # 純粋なドン消費型: 仮想実行 → eval delta が正のものを採用
        pre = compute_score(state, me_idx)
        best_action: Optional[Action] = None
        best_delta = 0
        for a in candidates:
            sim = copy.deepcopy(state)
            try:
                apply_action(sim, a)
            except Exception:
                continue
            post = compute_score(sim, me_idx)
            delta = post - pre
            if delta > best_delta:
                best_delta = delta
                best_action = a
        return best_action

    def _don_compensated_useful_now(
        self, state: GameState, eff: dict
    ) -> bool:
        """ドン相殺型起動メインを「今打つ価値あるか」 判定。

        判定基準 (厳密):
        - untap_don 系: untap した DON が **追加で必要** な再投資先があるか
          (= 「現 don_active では出せないが、 untap_don 後なら出せる」 カードがある)
        - power_pump 効果: 対象が **今ターン未だ攻撃しておらず**、 かつ pump がリターンを生む
        - 純粋な「DON ぐるぐる回し」 (= 再投資先なし) は False (= 浪費)

        どちらも該当しなければ False = 今焚くだけ DON 浪費。
        """
        me = state.turn_player
        untap_amount = 0       # untap_don: rested ドンを active 化
        new_don_amount = 0     # add_don / add_rested_don: 新規ドン発生 (rested 依存なし)
        has_power_pump = False
        for prim in eff.get("do", []):
            for k, v in prim.items():
                amount = 0
                if isinstance(v, int):
                    amount = v
                elif isinstance(v, dict):
                    amount = int(v.get("amount", 0))
                if k == "untap_don":
                    untap_amount += amount if amount else 1
                elif k in ("add_don", "add_rested_don"):
                    new_don_amount += amount
                elif k == "power_pump":
                    has_power_pump = True

        # 1) untap_don の有用性: untap_don は rested ドンしか活性化できない。
        # 現状 me.don_rested が untap_amount 未満なら、 実際に得られる active ドンはそれだけ。
        # 一方で add_don / add_rested_don は新規ドンなので don_rested 不足の影響を受けない。
        total_don_gain = min(untap_amount, me.don_rested) + new_don_amount
        if untap_amount > 0 and total_don_gain <= 0:
            # untap も new_don も得るものなし → untap 効果は実質無価値
            if not has_power_pump:
                return False
            # power_pump はあるが ドン獲得部分は無価値 → power_pump 判定にフォールスルー
        elif total_don_gain > 0:
            # 得た DON で「追加で出せるカード」 を作れるか
            useful = False
            for c in me.hand:
                cost = getattr(c, "cost", 99)
                if cost > me.don_active and cost <= me.don_active + total_don_gain:
                    useful = True
                    break
            if useful:
                return True
            if not has_power_pump:
                return False

        # 2) power_pump の有用性: 「pump 無しでも (= 既存 DON を付与すれば) 攻撃成立」 なら False
        if has_power_pump:
            opp = state.opponent
            if me.leader.rested:
                # リーダー既に攻撃済み → リーダー対象 pump は無価値、 キャラ pump のみ評価
                for chara in me.characters:
                    if (not chara.rested and not chara.summoning_sickness
                            and chara.attached_dons < 2):
                        return True
                return False
            # リーダー未 rest = 攻撃予定。
            # 「起動メインを焚かず、 既存の don_active を leader に付与した場合」 の最大攻撃力
            # でも opp.leader を倒せるなら pump は不要 (= 浪費)。
            opp_lp = opp.leader.power
            pay_don = int(eff.get("cost", {}).get("pay_don", 0))
            # 起動メインを撃つ場合の純 DON 増減 (= untap で実際に活性化できる枚数 + 新規ドン - 支払い)
            don_if_skip = me.don_active  # 撃たない場合の使える DON
            don_if_play = me.don_active - pay_don + min(untap_amount, me.don_rested) + new_don_amount
            # 撃たない方が DON 多いか同等 = まず False を検討
            max_atk_no_pump = me.leader.power + min(4, don_if_skip) * 1000
            if max_atk_no_pump >= opp_lp:
                # pump 無しで届く → pump はリーダー +1000 = リーサル助力でなければ不要
                # リーサルチェック: 相手 life=1 で hand が薄い場合は +1000 が活きる
                if len(opp.life) >= 2 or len(opp.hand) >= 3:
                    return False
            # pump がないと届かない → pump は本当に必要
            return True

        # 3) その他の効果型 (search / draw 等): 通常通り発動
        return True

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
        action = AttackLeader(
            attacker_iid=action.attacker_iid,
            counter_card_idxs=counters,
            blocker_iid=block_iid,
        )

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
