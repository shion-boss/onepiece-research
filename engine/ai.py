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
import re
from typing import Optional

from . import card_intents, card_role, hand_estimator, matchup_model
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


# =========================================================================== #
# 機械的悪手の事前剪定 (= self-play 学習に頼らず deterministic に排除できる手)
# =========================================================================== #
# 観戦コメント由来:
#   #4 ガンマナイフ (-5000) 系イベントを 弱小キャラに撃つ → 過剰除去 = 無駄
#
# 設計方針: legal_actions 後に prune_mechanical_waste(state, la) を挟むだけで
# plan_search / GreedyAI / EvalGreedyAI 全てに効く。 全 action が消える場合は
# 元リストを返して AI を破綻させない (= safety fallback)。

# 確定 KO する場合の target.power 閾値。 これ未満を確定 KO する除去 event は
# 「過剰除去」 とみなして候補から外す。
_OVERKILL_MIN_TARGET_POWER = 3000
# 戦略的に高価値な役割 — 弱小でも除去優先で OK
_OVERKILL_HIGH_VALUE_ROLES = {"finisher", "removal", "negation", "disruption"}


def _resolve_event_target_for_pruning(target_spec: str, opp_chars: list) -> list:
    """target_spec を解釈し、 該当する opp.characters 候補を返す (pruning 用簡略版)。

    effects.py の target_resolver と完全には一致しないが、 主要な single-target
    spec は網羅。 不明なら全 opp.characters を返す (= 保守側 = 過小評価で
    safety、 overkill 判定は False に倒れる)。
    """
    if not target_spec:
        return list(opp_chars)
    if target_spec == "one_opponent_character_any":
        return list(opp_chars)
    m = re.match(r"one_opponent_character_le_(\d+)$", target_spec)
    if m:
        thr = int(m.group(1))
        return [c for c in opp_chars if c.power <= thr]
    m = re.match(r"one_opponent_character_power_le_(\d+)$", target_spec)
    if m:
        thr = int(m.group(1))
        return [c for c in opp_chars if c.power <= thr]
    m = re.match(r"one_opponent_character_cost_le_(\d+)$", target_spec)
    if m:
        thr = int(m.group(1))
        return [c for c in opp_chars if c.card.cost <= thr]
    # 不明な spec: 安全側 = 全 opp.characters
    return list(opp_chars)


def _is_event_overkill(
    state: GameState,
    me: Player,
    opp: Player,
    event_card,
    overlay: dict,
) -> bool:
    """event の発動が 「過剰除去 = 弱小キャラへの 戦略的無駄」 か判定。

    True なら撃つに値しない。 例:
    - ガンマナイフ (cost 1, -5000 to opp_chara_le_5000) を P=1000 vanilla に
      確定 KO 撃つ場合: True (= -5000 を温存して強キャラ出現後に撃つべき)

    False を返すケース:
    - 強キャラ (power >= 3000) を確定 KO できる
    - 確定 KO せず debuff のみ (= 後続 attacker と connect する可能性あり)
    - target が finisher/removal/negation 等の 高価値 role
    - overlay 不在 (= 判定不能なら撃つに任せる)
    """
    if not overlay or event_card is None:
        return False
    bundle = overlay.get(event_card.card_id)
    if not bundle:
        return False
    for eff in bundle.effects:
        if eff.get("when") != "main":
            continue
        for prim in eff.get("do", []):
            if not isinstance(prim, dict):
                continue
            pp = prim.get("power_pump")
            if not isinstance(pp, dict):
                continue
            amount = int(pp.get("amount", 0))
            if amount >= 0:
                continue  # buff 系は対象外
            target_spec = pp.get("target", "")
            if "opponent" not in target_spec or "character" not in target_spec:
                continue
            candidates = _resolve_event_target_for_pruning(
                target_spec, opp.characters
            )
            if not candidates:
                # 撃てる target なし = そもそも legal_actions が弾く想定。 保険で False
                return False
            best = max(candidates, key=lambda c: c.power)
            # 確定 KO 条件: best.power + amount <= 0 (= power が 0 以下 = 場から除去)
            if best.power + amount > 0:
                continue  # debuff のみ = follow-up 余地あり、 撃ってよい
            # 確定 KO する場合
            if best.power >= _OVERKILL_MIN_TARGET_POWER:
                continue  # 強キャラを倒せる、 撃つ価値あり
            # 弱小確定 KO → role 例外
            try:
                role_info = card_role.get_card_role(best.card.card_id)
            except Exception:
                role_info = None
            primary = (
                role_info.get("primary_role")
                if isinstance(role_info, dict) else None
            )
            if primary in _OVERKILL_HIGH_VALUE_ROLES:
                continue  # finisher/removal 等は弱小でも除去で構わない
            return True  # 過剰除去確定
    return False


def _can_attack_this_turn(state: GameState, target: InPlay, is_leader: bool) -> bool:
    """このターン中に target が attack に出れるか判定 (= attach 効果が活きるか)。

    判定:
    - turn ≤ 2 (= 両 player の 1 ターン目) は battle 不可 → False
    - rested = 既に攻撃済 → False
    - cannot_attack_until_turn_end / cannot_attack_static / cannot_attack_through_opp_turn → False
    - キャラのみ: summoning_sickness かつ rush 無し → False

    True なら attach DON は power 強化として活きる可能性あり → mask しない。
    """
    if state.turn_number <= 2:
        return False
    if target.rested:
        return False
    if target.cannot_attack_until_turn_end:
        return False
    if target.cannot_attack_static:
        return False
    if target.cannot_attack_through_opp_turn:
        return False
    if not is_leader:
        # キャラ: 召喚酔い かつ Rush なし は今ターン攻撃不可
        if target.summoning_sickness and not target.is_rush_now and not target.is_rush_chara_only_now:
            return False
    return True


def _is_attach_don_wasteful(state: GameState, action) -> bool:
    """AttachDon が今ターンに無意味か判定 (= 「rested キャラに DON」 系の悪手)。

    True なら撃つに値しない。 観戦コメント #7/#9 由来:
    - #7: T17 P0 attach to leader (= leader rested) → 攻撃不可なのに attach
    - #9: T1 P0 attach to leader (= turn 1 で battle 不可) → 完全に意味なし
    """
    me = state.turn_player
    if isinstance(action, AttachDonToLeader):
        return not _can_attack_this_turn(state, me.leader, is_leader=True)
    if isinstance(action, AttachDonToCharacter):
        target = next(
            (c for c in me.characters if c.instance_id == action.target_iid),
            None,
        )
        if target is None:
            return True  # 対象消失 = 不正、 剪定
        return not _can_attack_this_turn(state, target, is_leader=False)
    return False


def _is_attack_confirmed_fail_no_effect(
    state: GameState, action, overlay: dict
) -> bool:
    """attack が「確定失敗 + on_attack 効果なし」 = 完全な空打ち か判定。

    cluster #2 由来: P=2000 chara で P=5000-6000 のリーダー/キャラに突撃 → 失敗
    で attacker は rested になるだけ、 副次効果もなし。 user 視点で「この攻撃の意味は？」
    と言われる典型的な悪手。 plan_search の eval では「attacker tap」 を ペナルティに
    計上してない (= field_count 不変、 power 不変) ため、 抑制が効きにくい。

    判定条件 (= 全部満たす時のみ mask):
    - attacker.power < target_power (= counter 無くても KO 不可、 確定 fail)
    - attacker.card の overlay に when=on_attack 効果がない (= 攻撃そのものの副次効果なし)

    Trade-off:
    - 厳しめにすると bluff (= 意図的な空打ち) を消す可能性。 ただし bluff は別 logic
      (= GreedyAI._is_desperate_losing_position 経由) で扱うのでここでは厳しめに ok。
    - on_attack 効果ありなら mask しない (= 弱体化 follow-up 期待。 task #12 領域)。
    """
    me = state.turn_player
    opp = state.opponent
    # attacker 取得
    attacker = None
    if me.leader.instance_id == action.attacker_iid:
        attacker = me.leader
    else:
        for c in me.characters:
            if c.instance_id == action.attacker_iid:
                attacker = c
                break
    if attacker is None:
        return False
    # target_power 取得
    if isinstance(action, AttackLeader):
        target_power = opp.leader.power
    else:  # AttackCharacter
        target = None
        for c in opp.characters:
            if c.instance_id == action.target_iid:
                target = c
                break
        if target is None:
            return False
        target_power = target.power
    # 確定失敗判定 (= 公式 7-1-4: attacker.power < target_power なら 失敗。 同値は attacker 勝ち)
    if attacker.power >= target_power:
        return False
    # on_attack 効果あり → mask しない (= 副次効果に期待)
    if overlay:
        bundle = overlay.get(attacker.card.card_id)
        if bundle:
            for eff in bundle.effects:
                if eff.get("when") == "on_attack":
                    return False
    # 確定失敗 + 副次効果なし → 空打ち
    return True


def prune_mechanical_waste(state: GameState, actions: list) -> list:
    """機械的悪手を action リストから除外。 副作用なし。

    現在排除する手:
    - PlayEvent: 過剰除去判定 (_is_event_overkill が True)
    - AttachDonToLeader / AttachDonToCharacter: 今ターン attack 不可な target への attach
    - AttackLeader / AttackCharacter: 確定失敗 + on_attack 効果なし の空打ち attack

    全 action が剪定されたら元リストを返す (= AI を破綻させない safety)。
    """
    if not actions:
        return actions
    me = state.turn_player
    opp = state.opponent
    overlay = state.effects_overlay or {}
    pruned = []
    for a in actions:
        if isinstance(a, PlayEvent):
            if 0 <= a.hand_idx < len(me.hand):
                card = me.hand[a.hand_idx]
                if _is_event_overkill(state, me, opp, card, overlay):
                    continue
        elif isinstance(a, (AttachDonToLeader, AttachDonToCharacter)):
            if _is_attach_don_wasteful(state, a):
                continue
        elif isinstance(a, (AttackLeader, AttackCharacter)):
            if _is_attack_confirmed_fail_no_effect(state, a, overlay):
                continue
        pruned.append(a)
    if not pruned:
        return actions
    return pruned


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

        # Phase 7D 追加: deck_analysis 適用後の値を base として snapshot。
        # 毎ターン MatchupProfile を再評価する際、 base に戻してから override を再適用する
        # (= classifier 出力の更新を反映、 旧 override を「上塗り」 で残さない)。
        self._base_defense_thresholds: dict = dict(self.defense_thresholds)
        self._base_attack_gap_tolerance: int = self.attack_gap_tolerance
        self._base_finisher_hold_life: int = self.finisher_hold_life
        # 直近で MatchupProfile を評価したターン番号 (= 同ターン重複評価を抑制)。
        # -1 は未評価マーカー。
        self._last_matchup_eval_turn: int = -1

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
        """ターン毎に MatchupProfile を再評価し、 上書き値を base から再適用 (Phase 7D)。

        - 同一ターン内は skip (= _last_matchup_eval_turn で抑制、 cost 削減)
        - ターン変わったら: base 値 (= deck_analysis 適用後) にリセット → classifier で
          再評価 (= 観測カードが増えると classifier 出力も変わる) → overrides を再適用

        旧挙動 (R67 まで): 初回 choose_action で 1 回だけ評価、 以後固定。
        新挙動 (Phase 7D): ターン毎に再評価で classifier の確信度向上を取り込む。

        (my, opp) ペアごとに defense_thresholds / attack_gap_tolerance /
        finisher_hold_life を override。 該当エントリ無しなら base 値が残る。
        """
        current_turn = state.turn_number
        if self._last_matchup_eval_turn == current_turn:
            return
        self._last_matchup_eval_turn = current_turn

        # base 値にリセット (= 旧 override を上塗りで残さないように)
        self.defense_thresholds = dict(self._base_defense_thresholds)
        self.attack_gap_tolerance = self._base_attack_gap_tolerance
        self.finisher_hold_life = self._base_finisher_hold_life

        try:
            profile = matchup_model.build_matchup_profile(
                state, me_idx, self.archetype
            )
        except Exception:
            return
        self._matchup_profile = profile
        self._matchup_overrides_applied = True  # 既存 flag は維持 (= 後方互換)

        overrides = matchup_model.lookup_matchup_overrides(
            profile.my_archetype, profile.opp_archetype
        )
        if not overrides:
            # 旧 archetype 評価結果は活かす (= role priority キャッシュ)
            self._apply_role_priorities(profile.opp_archetype)
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

    def _intent_score(self, card_id: str, state: GameState) -> int:
        """card_intents.json メタデータから現状況に対する適合スコアを返す。

        annotate 無いカードは 0 (= 既存挙動を変えない)。
        """
        try:
            return card_intents.compute_intent_score(
                card_id, state, state.turn_player, state.opponent,
            )
        except Exception:
            return 0

    def _is_desperate_losing_position(self, state: GameState, me_idx: int) -> bool:
        """負け確定気味の状況か判定 (Phase 7G + 7I、 2026-05-14)。

        判定基準 (全て満たす場合 = desperate、 bluff モード推奨):
        - 今ターンリーサル確率 < 0.4 (= 詰めれない)
        - 相手次ターンリーサル確率 ≥ 0.6 (= 受けきれない)
        - 自分の手札の未知率 ≥ 0.5 (Phase 7I 追加: bluff 効果見込み)

        Phase 7I 追加: 自分の手札の半分以上が公開済 (= opp が見えている) なら、
        DON を温存しても「counter event 持ってるフリ」 が opp に通用しない。
        → bluff 諦め、 通常プレイで残り資源を有効活用。
        """
        try:
            from .eval import lethal_estimate, project_opp_next_turn_lethal
            my_lethal = lethal_estimate(state, me_idx)
            opp_next_lethal = project_opp_next_turn_lethal(state, me_idx)
        except Exception:
            return False
        if my_lethal >= 0.4:
            return False  # 詰めれる可能性 → 全力で行く
        if opp_next_lethal < 0.6:
            return False  # まだ受けれそう → 普通プレイ

        # Phase 7I: 自分の手札未知率 check (= bluff 効果見込み)
        me = state.players[me_idx]
        hand_size = len(me.hand)
        if hand_size > 0:
            known_count = len(me.known_hand_card_ids)
            unknown_ratio = (hand_size - known_count) / hand_size
            if unknown_ratio < 0.5:
                # 手札の半分以上が公開済 → bluff 効果薄い → 通常プレイ
                return False
        return True

    # Phase 7G: counter event bluff 用に温存する active DON の最低数
    BLUFF_DON_RESERVE: int = 2

    def _bluff_filter_actions(
        self, state: GameState, actions: list,
    ) -> list:
        """bluff モードで DON 温存を保つための action filter (Phase 7G)。

        ユーザー指摘 (= counter event は DON 必要なので 1-2 DON を残す bluff):
        - 攻撃は許容 (= 相手キャラ削減等の積極的価値あり)
        - AttachDon は active DON が BLUFF_DON_RESERVE を割らない範囲で許容
        - DON cost ActivateMain も同様

        除外する action:
        - AttachDonToLeader / AttachDonToCharacter で active DON が BLUFF_DON_RESERVE 以下になる
        - DON cost ActivateMain で 同上

        残す action:
        - 攻撃 (= 既にパワー十分なら DON 不要、 そのまま実行可)
        - PlayCharacter / PlayEvent / PlayStage (= 場の構築は別 cost、 DON 直接消費しない)
        - 無料 ActivateMain
        - EndPhase
        """
        me = state.turn_player
        filtered = []
        for a in actions:
            if isinstance(a, (AttachDonToLeader, AttachDonToCharacter)):
                # 付与すると active DON が reserve 以下になる → skip
                n = getattr(a, "n", 1)
                if me.don_active - n < self.BLUFF_DON_RESERVE:
                    continue
            elif isinstance(a, ActivateMain):
                pay = self._activate_main_pay_don(state, a)
                if pay > 0 and me.don_active - pay < self.BLUFF_DON_RESERVE:
                    continue
            filtered.append(a)
        return filtered

    def choose_action(self, state: GameState) -> Action:
        self._ensure_matchup_overrides(state, state.turn_player_idx)
        actions = legal_actions(state)
        # Phase 7G: 負け確定気味なら bluff モード (= 攻撃放棄 + DON 温存)
        if self._is_desperate_losing_position(state, state.turn_player_idx):
            filtered = self._bluff_filter_actions(state, actions)
            if filtered:
                # bluff モード残された候補で 既存ロジック (= play / blocker 優先) に流す
                actions = filtered
            else:
                # 何もできない (= 場も手札も空) → EndPhase
                return EndPhase()
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
        # ただし 「過剰除去」 系 (= ガンマナイフを弱小キャラに撃つ等) は剪定して除外。
        play_event_actions: list[PlayEvent] = [a for a in actions if isinstance(a, PlayEvent)]
        if play_event_actions:
            non_wasteful = [
                a for a in play_event_actions
                if not _is_event_overkill(state, me, opp, me.hand[a.hand_idx],
                                           state.effects_overlay or {})
            ]
            chosen_pool = non_wasteful if non_wasteful else play_event_actions
            # non_wasteful が空 = 全部 overkill → 結局撃たないのが正解 (= 後続 action へ)。
            # PlayEvent そのものを skip して 他 action にフォールバック。
            if non_wasteful:
                return min(chosen_pool, key=lambda a: me.hand[a.hand_idx].cost)
            # 全部 overkill: ここでは event を選ばず後続 (= キャラ play / attack 等) へ進む

        # 0.7) ステージは現状空のとき登場 (差替の判断はしない、安全側)
        play_stage_actions: list[PlayStage] = [a for a in actions if isinstance(a, PlayStage)]
        if play_stage_actions and len(me.stages) == 0:
            return min(play_stage_actions, key=lambda a: me.hand[a.hand_idx].cost)

        # 0.8) Phase 7K: リーダー攻撃を PlayCharacter より先行 (= 不確実性最大化、 ノーリスク機会)
        # OPTCG コミュニティ知見: 「ドンを使う順番を間違えると相手の読みが容易になる」
        # → リーダー攻撃は手札を消費せず、 相手のブロッカー / 手札を削れる ノーリスク機会
        # 条件: リーダー active + 単独で opp.leader 超え (or 1 DON で届く)
        # desperate bluff モード時 / 起動メイン後回しケースは skip (= 既に上で処理済)
        # 防御側の reactive buff を見越して est_defender_power を計算
        if not me.leader.rested and not me.leader.summoning_sickness:
            est_opp_buff_for_leader = 0
            if state.effects_overlay:
                from .effects import estimate_opp_attack_buff_to_leader
                est_opp_buff_for_leader = estimate_opp_attack_buff_to_leader(
                    state, opp, state.effects_overlay
                )
            est_def_for_early = opp.leader.power + est_opp_buff_for_leader
            early_leader_attacks = [
                a for a in actions
                if isinstance(a, AttackLeader) and a.attacker_iid == me.leader.instance_id
            ]
            if early_leader_attacks:
                la = early_leader_attacks[0]
                # 単独で届く (= 即攻撃)
                if me.leader.power >= est_def_for_early:
                    return la
                # 1 DON で届く (= DON 付与で攻撃成立)
                gap = est_def_for_early - me.leader.power
                if 0 < gap <= 1000 and me.don_active >= 1 and me.leader.attached_dons < 4:
                    return AttachDonToLeader(n=1)

        # 1) 出せるキャラがあれば優先順位で選ぶ:
        #    (a) synergy_feature_priority があれば該当特徴のキャラを優先
        #    (b) early_finisher_hold: 高コストフィニッシャーは life>=3 では温存 (= プレイ候補から外す)
        #    (c) 残りの中で最大コストを選ぶ (= コスト効率)
        play_actions: list[PlayCharacter] = [a for a in actions if isinstance(a, PlayCharacter)]
        # Phase 7K extend (2026-05-14): blocker は attack 後に play (= life trigger 対策)
        # 攻撃可能なら blocker play を defer。 攻撃通った後で blocker 設置 = 安全。
        has_attack_actions = any(
            isinstance(a, (AttackLeader, AttackCharacter)) for a in actions
        )
        if play_actions and has_attack_actions:
            non_blocker_plays = [
                a for a in play_actions
                if not me.hand[a.hand_idx].is_blocker
            ]
            if non_blocker_plays:
                play_actions = non_blocker_plays
            # 全 blocker しかない + 攻撃あり → blocker 出さず attack 優先
            elif play_actions:
                play_actions = []  # blocker は後回し、 attack に流す
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
            # intent score (Phase Intent): card_intents.json metadata で「使うべき盤面か」 を加味
            #   (純 tiebreaker、 cost が同じ複数候補から選ぶ時のみ使用)
            def _play_sort_key(a: PlayCharacter):
                cid = me.hand[a.hand_idx].card_id
                eff = self._get_role_priority(cid)
                cost = me.hand[a.hand_idx].cost
                # 主軸: tier (= 効果性 70+ なら上位)、 cost 降順
                tier = 1 if eff >= 70 else 0
                # tiebreak: intent score (= 同 cost 同 tier 内での選択基準)
                intent = self._intent_score(cid, state)
                return (tier, eff, cost, intent)
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

        # ============================================================ #
        # 2-pre) リーサル判定 (= キャラ KO より優先)
        # ============================================================ #
        # 「リーサル圏内なのにキャラ攻撃」 を防ぐため、 まず「このターン勝てるか」 を判定。
        # DON ブーストも考慮 (= 不足分を DON で埋めれば成立する attacker も含める)。
        if atk_leader_actions:
            lethal_action = self._compute_lethal_action(
                state, atk_leader_actions, est_defender_power, _atk_inplay,
            )
            if lethal_action is not None:
                return lethal_action

        # 2a) キャラ KO 狙い: atk.power >= target.power のものから (相手コスト高優先)
        # role priority (R67): target の primary_role が finisher / removal / negation
        # の場合は KO 優先度を上げる (= 相手の鍵カードを潰す)。 既存の cost/power 並びに
        # 補助 boost として加算する形。
        # 注: opp.life ≤ 1 の near-lethal 局面では、 リーダー攻撃 viable があれば
        # キャラ KO より leader 攻撃を優先 (= 1 ヒットで勝ちに王手)。
        opp_life = len(opp.life)
        near_lethal = (opp_life <= 1)
        viable_char: list[tuple[AttackCharacter, InPlay, InPlay]] = []
        for a in atk_char_actions:
            attacker = _atk_inplay(a.attacker_iid)
            target = _opp_chara(a.target_iid)
            if attacker and target and attacker.power >= target.power:
                viable_char.append((a, attacker, target))

        # near-lethal で viable_leader があれば leader 優先 (= 詰めに行く)
        if near_lethal and atk_leader_actions:
            quick_leader = self._pick_best_leader_attack(
                atk_leader_actions, est_defender_power, _atk_inplay,
            )
            if quick_leader is not None:
                return quick_leader

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
            # リーサル判定 (Phase 7B 化): ハイパージオメトリックで「opp が止める確率」 を計算
            # P_block = P(hand counter total >= total_excess)
            # P_lethal = 1 - P_block、 ≥ 0.70 でリーサル成立 (= 70% 信頼度)
            opp_life = len(opp.life)
            opp_idx = 1 - state.turn_player_idx
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
            # Phase 7G: counter event bluff を加味
            # Phase 7H: archetype bluff factor + risk-adjusted threshold
            bluff_counter = hand_estimator.expected_counter_from_don_bluff(state, opp_idx)
            effective_excess = max(0, total_excess - bluff_counter)
            p_block = hand_estimator.probability_counter_total_at_least(
                state, opp_idx, effective_excess,
            )
            p_lethal = 1.0 - p_block
            try:
                from .eval import project_opp_next_turn_lethal
                fallback_win_prob = 1.0 - project_opp_next_turn_lethal(state, state.turn_player_idx)
            except Exception:
                fallback_win_prob = 0.5
            if fallback_win_prob >= 0.7:
                threshold = 0.75
            elif fallback_win_prob >= 0.4:
                threshold = 0.70
            elif fallback_win_prob >= 0.2:
                threshold = 0.55
            else:
                threshold = 0.40
            is_lethal = (
                len(top_n) >= hits_to_lethal
                and p_lethal >= threshold
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

    def _compute_lethal_action(
        self,
        state: GameState,
        atk_leader_actions: list[AttackLeader],
        est_defender_power: int,
        get_inplay,
    ) -> Optional[Action]:
        """このターンで相手 leader を倒せる (= 勝てる) なら、 最初の 1 アクションを返す。

        Phase 7J 統合 (2026-05-14): lethal_planner.plan_optimal_attack_sequence で
        最適な DON 配分 (= 均等化 + ±2k マージン) を求めてから lethal 判定。

        勝てない場合 None を返す。
        """
        from .lethal_planner import plan_optimal_attack_sequence

        me = state.turn_player
        opp = state.opponent
        opp_life = len(opp.life)
        hits_needed = max(1, opp_life)

        # attacker 候補を (iid, base_power) リスト化
        attacker_specs: list[tuple[int, int]] = []
        action_by_iid: dict[int, AttackLeader] = {}
        for a in atk_leader_actions:
            attacker = get_inplay(a.attacker_iid)
            if attacker is None:
                continue
            # 既に attached_dons を含む base_power でプランナーに渡す
            attacker_specs.append((a.attacker_iid, attacker.power))
            action_by_iid[a.attacker_iid] = a

        if len(attacker_specs) < hits_needed:
            return None

        # Phase 7J: 配分最適化プランナーで attack plan を構築
        plan = plan_optimal_attack_sequence(
            attackers=attacker_specs,
            available_don=me.don_active,
            opp_leader_power=est_defender_power,
            opp_shields=opp_life,
        )
        if not plan.is_lethal or len(plan.sequence) < hits_needed:
            return None

        # Phase 7J: 最適配分 plan の total excess + 確率判定 (Phase 7B/G/H 連動)
        total_excess = plan.expected_excess
        opp_idx = 1 - state.turn_player_idx
        bluff_counter = hand_estimator.expected_counter_from_don_bluff(state, opp_idx)
        effective_excess = max(0, total_excess - bluff_counter)
        p_block = hand_estimator.probability_counter_total_at_least(
            state, opp_idx, effective_excess,
        )
        p_lethal = 1.0 - p_block

        # Phase 7H: risk-adjusted lethal threshold
        me_idx = state.turn_player_idx
        try:
            from .eval import project_opp_next_turn_lethal
            opp_next_lethal = project_opp_next_turn_lethal(state, me_idx)
            fallback_win_prob = 1.0 - opp_next_lethal
        except Exception:
            fallback_win_prob = 0.5
        if fallback_win_prob >= 0.7:
            LETHAL_THRESHOLD = 0.75
        elif fallback_win_prob >= 0.4:
            LETHAL_THRESHOLD = 0.70
        elif fallback_win_prob >= 0.2:
            LETHAL_THRESHOLD = 0.55
        else:
            LETHAL_THRESHOLD = 0.40

        if p_lethal < LETHAL_THRESHOLD:
            return None

        # 🎯 リーサル成立! plan の最初の attacker から DON 配分 or 攻撃
        # 1) 最初の attacker で DON 必要なら付与
        for planned in plan.sequence:
            attacker = get_inplay(planned.attacker_iid)
            if attacker is None:
                continue
            already = attacker.attached_dons
            needed = planned.dons_to_attach - already
            if needed > 0:
                if attacker is me.leader:
                    return AttachDonToLeader(n=1)
                else:
                    return AttachDonToCharacter(target_iid=planned.attacker_iid, n=1)
        # 2) 全 attacker が必要 DON を装着済 → 弱い attacker から攻撃 (= plan order)
        first_planned = plan.sequence[0]
        return action_by_iid[first_planned.attacker_iid]

    def _pick_best_leader_attack(
        self,
        atk_leader_actions: list[AttackLeader],
        est_defender_power: int,
        get_inplay,
    ) -> Optional[AttackLeader]:
        """near-lethal 用: 最も power 高い attacker で leader を attack。"""
        viable: list[tuple[AttackLeader, InPlay]] = []
        for a in atk_leader_actions:
            attacker = get_inplay(a.attacker_iid)
            if attacker and attacker.power >= est_defender_power:
                viable.append((a, attacker))
        if not viable:
            return None
        viable.sort(key=lambda x: -x[1].power)
        return viable[0][0]

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
        """Phase 7A 改修: 3-tier ブロッカー選択 (= safe / rescue / sacrifice) + 既存防御閾値ロジック。

        ブロッカー選択を 3 候補で並列評価:
        - Tier 1 (block_safe): 自力で生存 (= c.power > atk_p、 公式 7-1-4 準拠) → counter 不要
        - Tier 2 (block_rescue): counter で救う (= valuable blocker + cost reasonable) → 強制 counter
        - Tier 3 (block_sacrifice): life ≤ 1 の特攻 (= blocker 失うが leader 守る)

        rule fix: 旧 `c.power >= atk_p` (= 同値生存) → `c.power > atk_p` (= strictly greater)。
        公式 7-1-4: atk ≥ def で攻撃側勝ち、 defender は atk より strictly higher な power が必要。
        """
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

        # === ブロッカー選択 (3-tier) ===
        block_iid: Optional[int] = None
        forced_counter: tuple[int, ...] = ()  # rescue 戦略時の確定 counter

        can_block = (
            is_leader_attack
            and not attacker.has_no_block_now
            and not attacker.attacker_prevents_blocker_until_turn_end
        )
        if can_block:
            available = [
                c for c in defender.characters
                if not c.rested and not c.summoning_sickness and c.is_blocker_now
            ]
            # Tier 1: 自力生存 (= 公式 7-1-4: c.power > atk_p で defender 勝ち)
            safe = [c for c in available if c.power > atk_p]
            if safe:
                block_iid = max(safe, key=lambda c: c.power).instance_id

            # Tier 2: counter で救う (= 価値ある blocker を温存)
            if block_iid is None:
                rescue_options = []
                # 同じ counter combo で leader 直接受けの方が得か判定用 (= cluster #3 対応)。
                # 「5000 blocker に +1000 counter 払うなら、 同じ +1000 counter で leader を
                # 守って blocker は温存」 が原則。 blocker rescue は blocker を rested に
                # するコスト (= 攻撃手の喪失) を背負うので、 同 counter で leader が守れる
                # なら rescue 不要。
                leader_p = defender.leader.power
                for c in available:
                    if not self._is_valuable_blocker(c):
                        continue
                    rescue_gap = atk_p - c.power
                    if rescue_gap < 0:
                        continue  # Tier 1 で拾われるはずだが念のため
                    combo = self._optimal_counter_combo(defender.hand, rescue_gap)
                    if not combo:
                        continue
                    rescue_total = sum(defender.hand[i].counter for i in combo)
                    # 公式 7-1-4: defender は atk_p より STRICTLY 上回る必要。 leader 直接受けで
                    # 同じ counter total を使い leader_p + rescue_total > atk_p なら rescue 不要。
                    if leader_p + rescue_total > atk_p:
                        continue  # 同 counter で leader も守れる → blocker は temporal に温存
                    if self._is_rescue_worthwhile(c, rescue_total, len(combo), life_left):
                        rescue_options.append((c, tuple(combo), rescue_total))
                if rescue_options:
                    # 最安 rescue を採用
                    chosen_c, chosen_combo, _ = min(rescue_options, key=lambda x: x[2])
                    block_iid = chosen_c.instance_id
                    forced_counter = chosen_combo

            # Tier 3: 特攻 (= life ≤ 1 で blocker 失っても leader 守る)
            if block_iid is None and life_left <= 1 and available:
                block_iid = max(available, key=lambda c: c.power).instance_id

        # rescue で counter 確定済なら直接返す (= 防御閾値 check をスキップ)
        if forced_counter:
            return block_iid, forced_counter

        # === 既存 防御閾値ロジック (= leader / chara 攻撃別) ===
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

    def _is_valuable_blocker(self, c: InPlay) -> bool:
        """ブロッカーを「counter で救う価値あり」 と判定するか (Phase 7A)。

        以下のいずれかなら True:
        - power ≥ 5000: 次ターン攻撃に使える戦力
        - role が finisher / removal / blocker: 戦略的重要カード
        - cost ≥ 4: 投資コストが高い (= 再展開コスト高)
        """
        if c.power >= 5000:
            return True
        role = self._get_card_primary_role(c.card.card_id)
        if role in ("finisher", "removal", "blocker"):
            return True
        if c.card.cost >= 4:
            return True
        return False

    def _is_rescue_worthwhile(
        self,
        blocker: InPlay,
        rescue_total: int,
        rescue_count: int,
        life_left: int,
    ) -> bool:
        """この blocker を rescue_total / rescue_count で救う価値があるか (Phase 7A)。

        判定基準:
        - power ≥ 5000: 2 枚 / 2000 counter まで許容 (= 高 power blocker は積極温存)
        - power 3000-4999: 1 枚 / 1000 counter まで (= 控えめ)
        - life ≤ 2 で finisher/blocker role: 2 枚 / 3000 まで (= 場のキャラ死守)
        - その他: rescue しない (= sacrifice 待ち)
        """
        if blocker.power >= 5000:
            if rescue_total <= 2000 and rescue_count <= 2:
                return True
        if blocker.power >= 3000:
            if rescue_total <= 1000 and rescue_count <= 1:
                return True
        if life_left <= 2:
            role = self._get_card_primary_role(blocker.card.card_id)
            if role in ("finisher", "blocker"):
                if rescue_total <= 3000 and rescue_count <= 2:
                    return True
        return False

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
            # 過剰除去を剪定 (= ガンマナイフを弱小キャラに撃つ等は撃たない)。
            non_wasteful = [
                a for a in play_event_actions
                if not _is_event_overkill(state, me, opp, me.hand[a.hand_idx],
                                           state.effects_overlay or {})
            ]
            if non_wasteful:
                return self._eval_pick(state, non_wasteful)
            # 全 event が overkill = event は撃たず後続 action へフォールスルー

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
        expose_root_tree: bool = False,
    ):
        super().__init__(rng, deck_analysis=deck_analysis)
        self.n_simulations = n_simulations
        self.c_uct = c_uct
        self.rollout_depth = rollout_depth
        # tree 可視化用 (Phase B.7): True なら choose_action 後に self.last_root を保存
        self.expose_root_tree = expose_root_tree
        self.last_root: Optional["_MCTSNode"] = None
        self.last_chosen_action: Optional["Action"] = None

    def choose_action(self, state: "GameState") -> "Action":
        actions = legal_actions(state)
        if len(actions) <= 1:
            chosen = actions[0] if actions else EndPhase()
            if self.expose_root_tree:
                # tree 不要なので簡易 root 保存
                self.last_root = _MCTSNode(parent=None, action=None)
                self.last_chosen_action = chosen
            return chosen

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
            chosen = self.rng.choice(actions)
            if self.expose_root_tree:
                self.last_root = root
                self.last_chosen_action = chosen
            return chosen
        best = max(root.children, key=lambda c: c.visits)
        if self.expose_root_tree:
            self.last_root = root
            self.last_chosen_action = best.action
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


def action_label(action: Optional["Action"], owner_state: Optional["GameState"] = None) -> str:
    """Action を人間可読 string に変換。 owner_state があれば手札カード名で表示。"""
    if action is None:
        return "(root)"
    from .game import (
        ActivateMain, AttachDonToCharacter, AttachDonToLeader,
        AttackCharacter, AttackLeader, EndPhase, PlayCharacter,
        PlayEvent, PlayStage,
    )
    if isinstance(action, EndPhase):
        return "EndPhase"
    if isinstance(action, AttachDonToLeader):
        return f"AttachDonLeader(n={action.n})"
    if isinstance(action, AttachDonToCharacter):
        return f"AttachDonChar(iid={action.target_iid}, n={action.n})"
    if isinstance(action, PlayCharacter):
        if owner_state:
            me = owner_state.turn_player
            if 0 <= action.hand_idx < len(me.hand):
                return f"play: {me.hand[action.hand_idx].name}"
        return f"PlayChar(hand={action.hand_idx})"
    if isinstance(action, PlayEvent):
        if owner_state:
            me = owner_state.turn_player
            if 0 <= action.hand_idx < len(me.hand):
                return f"event: {me.hand[action.hand_idx].name}"
        return f"PlayEvent(hand={action.hand_idx})"
    if isinstance(action, PlayStage):
        if owner_state:
            me = owner_state.turn_player
            if 0 <= action.hand_idx < len(me.hand):
                return f"stage: {me.hand[action.hand_idx].name}"
        return f"PlayStage(hand={action.hand_idx})"
    if isinstance(action, ActivateMain):
        return f"ActivateMain(src_iid={action.source_iid})"
    if isinstance(action, AttackLeader):
        return f"AttackLeader(atk_iid={action.attacker_iid})"
    if isinstance(action, AttackCharacter):
        return f"AttackChar(atk_iid={action.attacker_iid} → tgt_iid={action.target_iid})"
    return type(action).__name__


def serialize_mcts_tree(
    root: "_MCTSNode",
    chosen_action: Optional["Action"] = None,
    state: Optional["GameState"] = None,
    max_depth: int = 2,
) -> dict:
    """_MCTSNode の root を JSON シリアライズ可能な dict に変換。

    Args:
        root: ルートノード
        chosen_action: 最終選択された action (= is_chosen フラグ用)
        state: 元 state (= action label 生成用、 任意)。 root から depth 1 (= 直接の子) までは
               この state で label するが、 depth ≥ 2 は state 不明で fallback label
        max_depth: 子の最大深度 (default 2、 root + 子 + 孫)

    Returns:
        {
          "visits": int, "avg_value": float,
          "children": [
            {"action_label": str, "visits": int, "avg_value": float, "is_chosen": bool, "children": [...]}, ...
          ]
        }
    """

    def _recurse(node: "_MCTSNode", depth: int, owner_state: Optional["GameState"]) -> dict:
        avg = (node.total_value / node.visits) if node.visits > 0 else 0.0
        is_chosen = (
            chosen_action is not None
            and node.action is not None
            and node.action == chosen_action
        )
        children_serialized: list[dict] = []
        if depth < max_depth:
            # visits 降順で並べる
            sorted_children = sorted(node.children, key=lambda c: -c.visits)
            # depth 1 (= root の直接の子) は owner_state で label できる
            child_state = owner_state if depth == 0 else None
            for child in sorted_children:
                children_serialized.append(_recurse(child, depth + 1, child_state))
        return {
            "action_label": action_label(node.action, owner_state),
            "visits": node.visits,
            "avg_value": round(avg, 3),
            "is_chosen": is_chosen,
            "n_children": len(node.children),
            "children": children_serialized,
        }

    return _recurse(root, 0, state)


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


class HybridLookaheadAI(GreedyAI):
    """GreedyAI baseline + threshold 超え時のみ同 type 候補で 1-ply override。

    GreedyAI の choose_action を super() 呼んで baseline (= 単一 action) を取得。
    legal_actions から baseline と「同 action type」 の候補を抜き出し、 1-ply
    シミュレーション → board_eval で比較。 ただし baseline_score + override_threshold
    を超えた場合のみ採用 (= conservative override)。 これにより Greedy heuristic を
    広く尊重しつつ、 明らかに優位な alternative のみ採用する。

    naive LookaheadAI (= 0% 勝率) と naive Hybrid (= -30pt 劣化) の反省から、
    板上 eval が Greedy の domain knowledge に届かない領域ではあえて Greedy を
    優先する設計。 override_threshold は W_LIFE (= 1500) より小さい場合、 ほぼ
    全候補で override が起き、 大きい場合は Greedy とほぼ同じ挙動になる。
    """

    name = "HybridLookahead"
    override_threshold: float = 1000.0

    def choose_action(self, state: "GameState") -> "Action":
        baseline = super().choose_action(state)
        all_actions = legal_actions(state)
        same_type = [a for a in all_actions if type(a) is type(baseline)]
        if len(same_type) <= 1:
            return baseline

        me_idx = state.turn_player_idx
        baseline_score = self._sim_score(state, baseline, me_idx)
        best_action = baseline
        # threshold を超えた候補のみ採用候補に。 採用候補内では最高スコアを取る。
        best_alt_score = baseline_score + self.override_threshold
        for action in same_type:
            score = self._sim_score(state, action, me_idx)
            if score > best_alt_score:
                best_alt_score = score
                best_action = action
        return best_action

    def _sim_score(self, state: "GameState", action: "Action", me_idx: int) -> float:
        sim = copy.deepcopy(state)
        try:
            apply_action(sim, action)
        except Exception:
            return -float("inf")
        from .eval import compute_score
        return compute_score(sim, me_idx)


# Phase 1 (R72+): adaptive multi-turn lookahead 用の安全上限。
# game 平均長 6-9 ターンを想定、 cap 8 で plan-to-end mode の暴走を防ぐ。
MAX_TURNS_HARD_CAP = 8


class DeepPlanningAI(GreedyAI):
    """ターン全体プランを beam search する AI (R70+ / Phase 4 → Phase 1 R72+ DeepPlanningAI 化)。

    MAIN フェーズ開始時に EndPhase までの行動列を探索 (search_turn_plan)、
    終端 board_eval が最良のプランの 1 手目を返す。 次手は再計画 (= receding horizon)。

    GreedyAI の choose_action が「event 全部 → キャラ play 全部 → attack 全部」 と
    ジャンル別に固まる構造を捨て、 「event → attack → event」 のコンボや「ハンド剥がし
    後に通すアタック」 のような連動を pricing する。

    Phase 1 (R72+) で adaptive multi-turn lookahead に拡張:
    - T1-2: (beam=4, max_turns=1, per_turn_depth=6) = 旧挙動
    - T3-5: (beam=4, max_turns=2, per_turn_depth=5) = 自+相手 1 ターン読み
    - T6+ AND classifier 信頼度 ≥ 0.95: (beam=3, max_turns=8, per_turn_depth=4) = plan-to-end
    - T6+ AND 信頼度 < 0.95: (beam=3, max_turns=3, per_turn_depth=4) = downgrade

    plan-to-end mode では terminal leaf (= game_over) は ±W_GAME_OVER で確定値、
    評価関数の誤差が late-game で伝播しない (= endgame solver と同じ発想)。

    防御 (choose_defense) は GreedyAI を継承。 攻撃時の defense sim は plan_search 内で
    ai_opp.choose_defense を呼ぶ。 ai_opp が None の場合は self を defense sim にも使う
    (= self-play 想定)。
    """

    name = "Planning"

    def __init__(
        self,
        rng=None,
        deck_analysis=None,
        beam_width: int = 4,
        max_depth: int = 6,
        ai_opp=None,
        adaptive: bool = True,
    ):
        super().__init__(rng=rng, deck_analysis=deck_analysis)
        # adaptive=False で旧挙動 (= 固定 beam_width / max_depth、 max_turns=1)
        # 後方互換 + テスト用 escape hatch
        self.beam_width = beam_width
        self.max_depth = max_depth
        self.adaptive = adaptive
        # ai_opp が未指定なら self を defense sim 用に流用 (= self-play 簡略モデル)
        self._ai_opp = ai_opp

    def set_ai_opp(self, ai_opp) -> None:
        """harness 側で対戦相手 AI を渡す用。 plan_search 内の choose_defense sim に使う。"""
        self._ai_opp = ai_opp

    def _compute_adaptive_params(self, state: GameState) -> tuple[int, int, int]:
        """ターン数 + classifier 信頼度から (beam_width, max_turns, per_turn_depth) を返す。

        T1-2: (4, 1, 6)              旧挙動 (序盤は手札情報少なく深読み無意味)
        T3-5: (4, 2, 5)              自 + 相手 1 ターン
        T6+ AND conf ≥ 0.95: (3, MAX_TURNS_HARD_CAP, 4)  plan-to-end
        T6+ AND conf < 0.95: (3, 3, 4)  downgrade (信頼度不足、 過度な深読みは誤差伝播の元)
        """
        turn = state.turn_number
        me_idx = state.turn_player_idx
        opp_idx = 1 - me_idx

        # classifier 信頼度の取得 (= exception 時は 0.5)
        try:
            _, conf = matchup_model.infer_opponent_archetype_with_confidence(state, opp_idx)
        except Exception:
            conf = 0.5

        if turn <= 2:
            return (4, 1, 6)
        if turn <= 5:
            return (4, 2, 5)
        # T6+ = ゲーム終了射程、 plan-to-end mode
        if conf >= 0.95:
            return (3, MAX_TURNS_HARD_CAP, 4)
        return (3, 3, 4)

    def choose_action(self, state: GameState) -> Action:
        from .plan_search import search_turn_plan

        # MatchupProfile / role priority のロード (= GreedyAI._ensure_matchup_overrides)
        self._ensure_matchup_overrides(state, state.turn_player_idx)

        actions = legal_actions(state)
        if not actions:
            return EndPhase()
        if len(actions) == 1:
            return actions[0]

        # Phase 7G: 負け確定気味なら bluff モード (= GreedyAI fallback、 plan search skip)
        # plan_search は最適手探索なので「絶望時に DON 温存」 という心理戦的判断はしない。
        # GreedyAI の bluff filter を経由させる。
        if self._is_desperate_losing_position(state, state.turn_player_idx):
            return super().choose_action(state)

        # adaptive params の決定 (= R72+)
        if self.adaptive:
            beam_width, max_turns, per_turn_depth = self._compute_adaptive_params(state)
            max_depth = max_turns * per_turn_depth
        else:
            beam_width = self.beam_width
            max_turns = 1
            max_depth = self.max_depth

        ai_opp = self._ai_opp if self._ai_opp is not None else self
        try:
            best_plan, _best_score = search_turn_plan(
                state,
                ai_opp,
                beam_width=beam_width,
                max_depth=max_depth,
                max_turns=max_turns,
                ai_self=self,
            )
        except Exception:
            # search 失敗時は GreedyAI 動作に fallback
            return super().choose_action(state)

        if not best_plan:
            return super().choose_action(state)
        return best_plan[0]


# 後方互換 alias: 既存コード (= harness / scripts / tests) が `PlanningAI` を import している。
# Phase 1 R72+ で DeepPlanningAI が新名、 PlanningAI は同一 class への alias。
# isinstance(x, PlanningAI) と isinstance(x, DeepPlanningAI) は等価。
PlanningAI = DeepPlanningAI


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
