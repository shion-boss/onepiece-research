# -*- coding: utf-8 -*-
"""人間 vs AI 対戦 セッション。

人間 が action を 1 つ ずつ 選び、 AI が 自動 で 相手 ターン を 進める loop。
攻撃時 の 防御 (= ブロッカー / カウンター) も 人間 が 操作 する。

実装:
- HumanAI: choose_action / choose_defense が PauseSignal を 投げる擬似 AI。
  session が pending state を 持ち、 web 経由 で 人間 input が来たら resume。
- HumanSession: GameState + AI (= opp) + HumanAI (= self) を 保持。
  advance_until_pause() で AI 自動進行、 PauseSignal で 停止。
  apply_human_action() で 人間 input を 受けて 進行 再開。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Optional

from .core import GameState, Phase
from .deck import DeckList
from .game import (
    apply_action,
    legal_actions,
    setup_game,
    finalize_setup_after_mulligan,
    play_until_main,
    AttackLeader,
    AttackCharacter,
)


class PauseSignal(Exception):
    """HumanAI が action を 求められた 時に raise。
    session.run loop が catch して 「人間 input 待ち」 状態 に 入る。
    """

    def __init__(self, kind: str, payload: dict):
        self.kind = kind  # "action" | "defense"
        self.payload = payload


@dataclass
class PendingDefense:
    """attack の defense 選択 を 人間 から 受け付ける ための pending state。"""
    attacker_iid: int
    target_iid: Optional[int]  # None = leader
    is_leader_attack: bool
    legal_blocker_iids: list[int]  # 候補
    legal_counter_card_idxs: list[int]  # hand index の counter 候補


class HumanAI:
    """人間 を 代理 する 「擬似 AI」。 choose_* で PauseSignal を 投げる。

    session.resume_with_action / resume_with_defense で human input を 注入。
    """

    def __init__(self, session: "HumanSession"):
        self.session = session

    def set_ai_opp(self, _ai_opp):
        """harness 互換 stub (= PlanningAI が plan_search 用に 相手 AI 注入する hook)"""
        pass

    def choose_action(self, state: GameState):
        # session に resume_action が 設定 されていれば それ を 返す
        if self.session._pending_action is not None:
            action = self.session._pending_action
            self.session._pending_action = None
            return action
        # 未設定 → pause
        raise PauseSignal("action", {})

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        if self.session._pending_defense is not None:
            block_iid, counters = self.session._pending_defense
            self.session._pending_defense = None
            return block_iid, counters
        # pending_attack_redirect (= OP14-060 紫ドフラ 等 で 効果適用 済) が セット
        # されていれば 攻撃対象 を その iid に 上書き (= UI が 正しい target に 矢印 を 向ける ため)。
        redirected_iid = getattr(state, "pending_attack_redirect", None)
        if redirected_iid is not None:
            # 該当 InPlay を defender 側 から 探索 (= リーダー or キャラ)
            new_target = None
            new_is_leader = False
            if redirected_iid == defender.leader.instance_id:
                new_target = defender.leader
                new_is_leader = True
            else:
                for c in defender.characters:
                    if c.instance_id == redirected_iid:
                        new_target = c
                        new_is_leader = False
                        break
            if new_target is not None:
                target = new_target
                is_leader_attack = new_is_leader
        # 未設定 → pause
        # blocker 候補 = defender.characters の中 で is_blocker_now かつ active な もの
        # (= 公式 10-1-4: ブロッカー キーワード 持ち + アクティブ (= レスト で ない)。
        #  召喚酔い は ブロック を 妨げ ない ＝ 条件 に 含め ない。 発動不可 効果 のみ 除外)
        # is_leader_attack が False (= キャラ 攻撃) なら blocker は 通常 不可 だが redirect 後 は
        # blocker step 不要 (= 既に target 確定)。 簡略 で blocker 候補 を 出さない。
        if is_leader_attack:
            blocker_iids = [
                b.instance_id for b in defender.characters
                if b.is_blocker_now and not b.rested
                and not b.blocker_disabled_until_turn_end
                and b.instance_id != getattr(target, "instance_id", None)
            ]
        else:
            blocker_iids = [
                b.instance_id for b in defender.characters
                if b.is_blocker_now and not b.rested
                and not b.blocker_disabled_until_turn_end
                and b.instance_id != getattr(target, "instance_id", None)
            ]
        # counter 候補: hand の counter 持ち + 各 idx の counter 値
        # + 【カウンター】 EVENT カード (= when:"counter" 効果あり、 DON cost 支払い可能)。
        # 公式 7-1-3-1-2: defender は アタック宣言時 に counter event を 発動 可能。
        counter_idxs = []
        counter_values: dict[int, int] = {}
        counter_event_idxs: list[int] = []
        overlay = self.session.state.effects_overlay or {}
        don_avail = defender.don_active
        for i, c in enumerate(defender.hand):
            counter_val = int(c.counter) if (c.counter and c.counter > 0) else 0
            is_counter_event = False
            # EVENT カード で when:"counter" 効果 + DON cost 払える なら counter event 候補。
            # overlay.get() は CardEffectBundle オブジェクト を 返す (= 旧 isinstance list で
            # 常 False の bug、 2026-05-23 修正)。 .effects 属性 を 走査。
            if str(getattr(c, "category", "")).endswith("EVENT"):
                eff_bundle = overlay.get(c.card_id)
                effects_list = []
                if eff_bundle is not None:
                    if hasattr(eff_bundle, "effects"):
                        effects_list = eff_bundle.effects
                    elif isinstance(eff_bundle, list):
                        effects_list = eff_bundle
                for e in effects_list:
                    if isinstance(e, dict) and e.get("when") == "counter":
                        if c.cost <= don_avail:
                            is_counter_event = True
                        break
            if counter_val > 0 or is_counter_event:
                counter_idxs.append(i)
                # counter event のみ (= 数値なし) は表示用に 0 で記録
                counter_values[i] = counter_val
                if is_counter_event:
                    counter_event_idxs.append(i)
        # 人間 defender 用 「相手のアタック時」 効果 リスト (= clickable で 発動)。
        # ⚠ source が 現在 defender の 場 に 居る effect だけ に 限定 する。 この list は
        # apply_human_defense でしか クリアされ ず、 防御を opp_attack 効果発火で 解決 して
        # attacker が 消える 経路は それを バイパスする ため stale entry が ターン跨ぎで 残留。
        # source カードが その後 場を離れる と、 次の防御で payload に 幽霊ボタンが 出て click で
        # 「source iid not found」 crash する (= 2026-06-05 DON-ledger fuzz が検出)。
        defender_field_iids = {
            ip.instance_id
            for ip in [defender.leader, *defender.characters, *defender.stages]
        }
        available_effects = [
            e for e in (getattr(state, "_available_opp_attack_effects", []) or [])
            if e.get("source_iid") in defender_field_iids
        ]
        state._available_opp_attack_effects = list(available_effects)
        raise PauseSignal(
            "defense",
            {
                "attacker_iid": attacker.instance_id,
                "attacker_power": int(getattr(attacker, "power", 0) or 0),
                "target_iid": None if is_leader_attack else target.instance_id,
                "is_leader_attack": is_leader_attack,
                "legal_blocker_iids": blocker_iids,
                "legal_counter_card_idxs": counter_idxs,
                "counter_values": counter_values,
                "counter_event_idxs": counter_event_idxs,
                "available_opp_attack_effects": list(available_effects),
            },
        )


class HumanSession:
    """1 試合 の 人間 vs AI セッション。

    Args:
        deck_a: 人間 が 使う デッキ
        deck_b: AI が 使う デッキ
        ai_factory: AI constructor (= harness.run_matchup の ai_factory 互換)
        seed: 乱数 seed
        effects_overlay: 効果 overlay (= load_effect_overlay 結果)
        deck_a_analysis / deck_b_analysis: 任意の deck 分析 (= GoalDirectedAI 等で 使う)
        human_first: True なら 人間 が 先攻、 False なら AI 先攻、 None なら random
    """

    def __init__(
        self,
        deck_a: DeckList,
        deck_b: DeckList,
        ai_factory,
        seed: int = 42,
        effects_overlay: Optional[dict] = None,
        deck_a_analysis: Optional[dict] = None,
        deck_b_analysis: Optional[dict] = None,
        human_first: Optional[bool] = None,
        card_repo=None,
        puzzle_state: Optional[dict] = None,
        single_turn: bool = False,
    ):
        self.rng = random.Random(seed)
        self.single_turn = single_turn
        self._card_repo = card_repo
        if human_first is None:
            human_first = self.rng.random() < 0.5
        first_player = 0 if human_first else 1
        # human_idx は human_first から確定 (= setup_game に渡す = game_start ステージ選択の
        # actor 判定に必要)。 setup_game は first_player=0 強制なので players 並びは固定。
        self.human_idx = 0 if human_first else 1
        self.ai_idx = 1 - self.human_idx
        # マリガン skip path で draw 段階 で 一旦 停止 (= user に keep/引き直し 委ね)。
        # game_start ステージ選択 (= イム) は公式 FAQ で マリガン前 なので human_player_idx を
        # 渡し、 draw 前 に人間のステージ選択 pending を立てさせる。
        self.state = setup_game(
            deck_a if human_first else deck_b,
            deck_b if human_first else deck_a,
            rng=self.rng,
            first_player=0,  # 強制 0 で 並び 固定 (= human_first 判定 は 上で 済)
            effects_overlay=effects_overlay,
            deck1_analysis=deck_a_analysis if human_first else deck_b_analysis,
            deck2_analysis=deck_b_analysis if human_first else deck_a_analysis,
            do_mulligan_and_finalize=False,
            human_player_idx=self.human_idx,
        )
        self.state.record_snapshots = True
        # 効果ランタイム・レフェリー (= カード保存則を read-only 監視、 誤検出ゼロ)。
        # 人間 vs AI の実プレイ中、 効果がカードを複製/消失させたら settled 境界で検出する。
        from .semantic_referee import SemanticReferee
        self.referee = SemanticReferee(strict=False)
        self.referee.observe(self.state)  # baseline 確定 (= setup 直後 = 各50枚)
        self.referee_violations: list[str] = []
        # human_idx / ai_idx は 上 (setup_game 前) で 算出済。
        self.state.human_player_idx = self.human_idx
        # 最初の pending: game_start ステージ選択 (= イムで該当2枚) が setup_game で立っていれば
        # それを先に (公式 FAQ: マリガン前)。 無ければ通常どおりマリガン確認 pending。
        gsp = self.state.pending_choice
        if gsp is not None and gsp.get("kind") == "game_start_stage_pick":
            # ステージ選択 → apply_human_choice で resolve 後に life+draw+マリガン pending。
            self.state.push_log("ゲーム開始時: 登場ステージ選択 (マリガン前)")
        else:
            me_hand = self.state.players[self.human_idx].hand
            self.state.pending_choice = {
                "kind": "mulligan_confirm",
                "cards": [
                    {"card_id": c.card_id, "name": c.name} for c in me_hand
                ],
            }
            self.state.push_log(
                f"マリガン: {self.state.players[self.human_idx].name} 手札確認 (keep/引き直し)"
            )
        # frame 再生 用: 前回 payload を 返した 時点 の snapshot 数。
        # snapshot_payload で 新規 frames を 返却 → ベースライン 更新。
        self._last_seen_snapshot_count = 0
        # human_idx / ai_idx / human_player_idx は 上 で 設定済
        self.effects_overlay = effects_overlay
        # 試合中 に user が log を 右クリックして 残す bug 報告 / メモ (= 2026-05-27)。
        # serialize_for_log で payload に 含めて Blob upload、 後で 解析素材 に なる。
        self.log_comments: list[dict] = []
        # マリガン pending を 設定済 → pending_kind 設定
        self.pending_kind: Optional[str] = "choice"
        self.pending_payload: Optional[dict] = dict(self.state.pending_choice or {})
        # AI を 構築 (= ai_idx 側)。 ai_factory は (rng, deck_analysis) を 受ける
        deck_for_ai_analysis = (
            deck_b_analysis if human_first else deck_a_analysis
        )
        if callable(ai_factory):
            try:
                self.ai = ai_factory(self.rng, deck_for_ai_analysis)
            except TypeError:
                self.ai = ai_factory(self.rng)
        else:
            self.ai = ai_factory
        self.human_ai = HumanAI(self)
        # plan_search 等 が ai_opp として 相手 AI を 要する 場合 注入
        if hasattr(self.ai, "set_ai_opp"):
            self.ai.set_ai_opp(self.human_ai)
        # pending input 受け取り 用 buffer
        self._pending_action = None
        self._pending_defense: Optional[tuple] = None
        self.deck_a_slug = getattr(deck_a, "slug", None) or deck_a.name
        self.deck_b_slug = getattr(deck_b, "slug", None) or deck_b.name
        # パズル/操縦コース: 指定 mid-game 盤面で state を上書き (= マリガン skip、 人間ターン開始)。
        if puzzle_state is not None:
            self._inject_puzzle(puzzle_state)

    def _inject_puzzle(self, ps: dict) -> None:
        """パズル盤面 (ps) で state を上書きし、 人間の MAIN ターン開始局面にする。
        ps schema: {my_leader, my_chars[{cid,dons?,rested?}], opp_leader, opp_chars[],
                    my_hand[], opp_hand[], my_life, opp_life, my_don, opp_don?}
        human_idx 側 = my_*、 ai_idx 側 = opp_*。 mid-game なので保存則 referee は再 baseline。"""
        from .core import InPlay, Player, Phase

        repo = self._card_repo
        if repo is None:
            from .deck import CardRepository
            repo = CardRepository.from_json("db/cards.json")

        def mk_inplay(spec):
            cid = spec.get("cid") if isinstance(spec, dict) else spec
            ip = InPlay.of(repo.get(cid), sickness=bool(isinstance(spec, dict) and spec.get("sick", False)))
            if isinstance(spec, dict):
                ip.attached_dons = int(spec.get("dons", 0))
                ip.rested = bool(spec.get("rested", False))
            return ip

        st = self.state
        dummy = repo.get("ST01-004")
        me = st.players[self.human_idx]
        opp = st.players[self.ai_idx]
        me.leader = mk_inplay(ps["my_leader"])
        opp.leader = mk_inplay(ps["opp_leader"])
        me.characters = [mk_inplay(c) for c in ps.get("my_chars", [])]
        opp.characters = [mk_inplay(c) for c in ps.get("opp_chars", [])]
        me.stages = []
        opp.stages = []
        me.hand = [repo.get(h) for h in ps.get("my_hand", [])]
        opp.hand = [repo.get(h) for h in ps.get("opp_hand", [])]
        me.life = [dummy] * int(ps.get("my_life", 3))
        opp.life = [dummy] * int(ps["opp_life"])
        me.deck = [dummy] * 20
        opp.deck = [dummy] * 20
        me.trash = [repo.get(t) for t in ps.get("my_trash", [])]
        opp.trash = [repo.get(t) for t in ps.get("opp_trash", [])]
        me.don_active = int(ps["my_don"])
        me.don_rested = 0
        opp.don_active = int(ps.get("opp_don", 0))
        opp.don_rested = 0
        st.turn_player_idx = self.human_idx
        st.turn_number = int(ps.get("turn", 5))
        st.phase = Phase.MAIN
        st.pending_choice = None
        try:
            from .game import _recompute_static
            _recompute_static(st)
        except Exception:
            pass
        # 保存則 referee を新盤面で再 baseline (= mid-game 局面を基準にする)。
        try:
            self.referee.observe(st)
        except Exception:
            pass
        # snapshot を1枚生成 (= snapshot_payload が盤面を返せる様に)。
        st.push_log(f"操縦コース: {st.turn_number}ターン目 開始 (あなたの手番)")
        self.pending_kind = "action"
        self.pending_payload = {}

    def advance_until_pause(self, max_actions: int = 200) -> None:
        """ゲーム 終了 か 人間 input 必要 まで AI を 進める。"""
        from .ai import play_one_action
        from .game import Phase, play_until_main
        from .effects import _maybe_prompt_end_of_turn_optional, resolve_triggers

        for _ in range(max_actions):
            if self.state.game_over:
                self.pending_kind = None
                self.pending_payload = None
                return
            # 単ターンパズル: 人間ターン終了 → AI ターンに移ったら停止 (= AI は打たせない)。
            if (
                self.single_turn
                and self.state.pending_choice is None
                and self.state.turn_player_idx == self.ai_idx
            ):
                self.pending_kind = "turn_done"
                self.pending_payload = {}
                return
            # 余 イベント が キュー に 残って いる なら drain (= 任意効果 解決後 の cleanup)
            if (
                self.state.event_queue
                and not self.state.resolving
                and self.state.pending_choice is None
            ):
                resolve_triggers(self.state)
            # END phase で deferred な ターン終了任意効果 が 残って いれば modal を 立てる
            if self.state.pending_choice is None:
                _maybe_prompt_end_of_turn_optional(self.state)
            # 人間 選択 待ち (= search_top_n / end_of_turn_optional 等) は pause 条件
            if self.state.pending_choice is not None:
                self.pending_kind = "choice"
                self.pending_payload = dict(self.state.pending_choice)
                return
            # Phase が MAIN でない (= END/REFRESH/DRAW/DON で 止まって いる) なら MAIN まで 進める。
            # play_one_action は phase 無関係で 即 choose_action を 呼ぶ ので、 MAIN 未到達 で
            # 人間 ターンに 入る と HumanAI が PauseSignal("action") を 投げ、 legal_actions が
            # phase!=MAIN ゆえ 空 で 詰む (= NO_ACT)。 特に 人間 の ターン開始時 効果
            # (trigger_turn_start が REFRESH→DRAW で pending_choice を立てる) を 解決した 後、
            # phase が DRAW に 残った まま ここへ 来る ケースを 救う。 play_until_main は END の
            # advance_phase (= trigger_end_of_turn + ターン交代) も 内包する。
            if self.state.phase != Phase.MAIN:
                play_until_main(self.state)
                continue
            tp = self.state.turn_player_idx
            try:
                if tp == self.ai_idx:
                    # AI ターン: 通常 進行 (= AI が action 選び 適用)
                    _act = play_one_action(self.state, self.ai, self.human_ai)
                else:
                    # 人間 ターン: HumanAI が PauseSignal を 投げる
                    _act = play_one_action(self.state, self.human_ai, self.ai)
            except PauseSignal as p:
                self.pending_kind = p.kind
                self.pending_payload = p.payload
                return
            except Exception as e:
                # engine error → ゲーム 強制 終了 (= 相手 勝利 扱い)
                self.state.declare_winner(1 - tp, f"engine error: {e}")
                self.pending_kind = None
                self.pending_payload = None
                return
            # 1 action 完了 (= settled、 modal なし) → カード保存則を read-only 監視。
            if self.state.pending_choice is None:
                self._observe_conservation(type(_act).__name__ if _act is not None else "")
        # max_actions に 到達
        self.state.declare_winner(-1, "max_actions reached")
        self.pending_kind = None
        self.pending_payload = None

    def _observe_conservation(self, action_label: str = "") -> None:
        """settled 境界で カード保存則を read-only 監視。 違反は log + referee_violations に記録
        (= strict=False なので 試合は止めない、 後で 解析素材 になる)。"""
        n = self.referee.observe(self.state, action_label)
        if n > 0:
            for v in self.referee.violations[-n:]:
                self.referee_violations.append(v)
                self.state.push_log(f"[保存則違反] {v}")

    def apply_human_choice(self, picks: list[int]) -> None:
        """人間 の interactive 選択 (= search_top_n 等) を 適用 → 進行 再開。"""
        if self.pending_kind != "choice":
            raise ValueError("not waiting for human choice")
        # マリガン pending 系 は 特別処理
        choice = self.state.pending_choice or {}
        if choice.get("kind") == "game_start_stage_pick":
            # 公式 FAQ: ゲーム開始時ステージ選択はマリガン前。 選んだステージを登場 →
            # ライフ配置+手札ドロー (finish_pre_mulligan_setup) → マリガン確認 pending。
            from .effects import resolve_pending_choice
            from .game import finish_pre_mulligan_setup
            resolve_pending_choice(self.state, picks)  # 選んだステージを登場 (空=最良自動)
            finish_pre_mulligan_setup(self.state)      # life + draw (= マリガン前状態)
            me_hand = self.state.players[self.human_idx].hand
            self.state.pending_choice = {
                "kind": "mulligan_confirm",
                "cards": [
                    {"card_id": c.card_id, "name": c.name} for c in me_hand
                ],
            }
            self.state.push_log(
                f"マリガン: {self.state.players[self.human_idx].name} 手札確認 (keep/引き直し)"
            )
            self.pending_kind = "choice"
            self.pending_payload = dict(self.state.pending_choice)
            return
        if choice.get("kind") == "mulligan_confirm":
            do_mulligan = bool(picks and picks[0] == 1)
            self.state.pending_choice = None
            if do_mulligan:
                # 「引き直し」 → 手札 戻し + 新 5 枚 ドロー のみ。 user に 新手札 確認 modal
                # を 立てる (= finalize は OK 後)。
                me = self.state.players[self.human_idx]
                me.deck.extend(me.hand)
                me.hand = []
                me.shuffle_deck(self.rng)
                me.draw(5)
                self.state.push_log(
                    f"  マリガン: {me.name} (人間) 手札 引き直し"
                )
                self.state.pending_choice = {
                    "kind": "mulligan_redrawn",
                    "cards": [
                        {"card_id": c.card_id, "name": c.name} for c in me.hand
                    ],
                }
                self.pending_kind = "choice"
                self.pending_payload = dict(self.state.pending_choice)
                return
            # keep: finalize 直接
            finalize_setup_after_mulligan(
                self.state,
                rng=self.rng,
                effects_overlay=self.effects_overlay,
                human_mulligan=False,
                human_player_idx=self.human_idx,
            )
            play_until_main(self.state)
            self.pending_kind = None
            self.pending_payload = None
            self.advance_until_pause()
            return
        if choice.get("kind") == "mulligan_redrawn":
            # 新手札 OK → finalize (= ライフ配布 既済 + AI 側 mulligan + game_start)
            self.state.pending_choice = None
            # 既 マリガン適用 済 + log 済 なので human_already_processed=True で finalize 呼び
            # (= 「引き直し」 後 に 「引き直さない (keep)」 と log する 矛盾 を 防ぐ)。
            finalize_setup_after_mulligan(
                self.state,
                rng=self.rng,
                effects_overlay=self.effects_overlay,
                human_already_processed=True,
                human_player_idx=self.human_idx,
            )
            play_until_main(self.state)
            self.pending_kind = None
            self.pending_payload = None
            self.advance_until_pause()
            return
        from .effects import resolve_pending_choice
        resolve_pending_choice(self.state, picks)
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()
        # ⚠ counter event / opp_attack 効果の **chained modal** (discard/draw/target 等) を解決して
        # defense に戻った場合、 解決中に hand が変化 (= 引く/捨てる) していると defense payload の
        # counter_event_idxs / legal_counter_card_idxs が stale になる (= 別カードの index を指す)。
        # defense に復帰したら必ず現 hand から再構築する (= 2026-06-05 広プール fuzz が「非EVENTに
        # counter_event」 で検出した stale payload の root 修正)。
        if self.pending_kind == "defense" and isinstance(self.pending_payload, dict):
            self._rebuild_defense_payload()

    def legal_actions_for_human(self) -> list[dict]:
        """人間 ターン中 の legal actions を JSON-able dict 群 で 返す。"""
        if self.pending_kind != "action":
            return []
        actions = legal_actions(self.state)
        return [_action_to_dict(a, i) for i, a in enumerate(actions)]

    def apply_human_action(self, action_idx: int) -> None:
        """legal_actions の index を 指定 して 人間 action を 適用。 進行 を 再開。"""
        if self.pending_kind != "action":
            raise ValueError("not waiting for human action")
        actions = legal_actions(self.state)
        if not (0 <= action_idx < len(actions)):
            raise ValueError(f"action_idx {action_idx} out of range (0..{len(actions)-1})")
        self._pending_action = actions[action_idx]
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

    def apply_human_defense(
        self,
        blocker_iid: Optional[int],
        counter_card_idxs: list[int],
    ) -> None:
        """人間 防御 (= ブロッカー + カウンター 選択) を 適用。"""
        if self.pending_kind != "defense":
            raise ValueError("not waiting for human defense")
        # available_opp_attack_effects は defense 確定 で クリア (= 次 attack 用)
        if hasattr(self.state, "_available_opp_attack_effects"):
            self.state._available_opp_attack_effects = []
        self._pending_defense = (blocker_iid, tuple(counter_card_idxs))
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

    def apply_human_use_counter_event(self, hand_idx: int) -> None:
        """防御 pending 中、 手札 の 【カウンター】 イベント (= 神避 等) を クリック
        で 即時 発動 (= 公式 7-1-3 「使った 瞬間 に 効果 適用」)。

        旧 flow (= apply_human_defense で counter_card_idxs に event idx を 渡す):
        防御 確定 → apply_action 内 で counter event 順次 発動 で UX 不自然。
        新 flow: 防御 modal で event を click → 即 pop + cost 払い + trigger_counter_event
        → modal (= discard / target_pick) 解決 後 defense modal 再表示 (= 残り
        counter 値 カード / blocker 追加 調整 可能、 また 別 counter event 発動 可能)。
        """
        if self.pending_kind != "defense":
            raise ValueError("not waiting for human defense")
        defender_idx = self.human_idx
        defender = self.state.players[defender_idx]
        attacker_player = self.state.players[1 - defender_idx]
        # ⚠ 以下の検証は すべて **stale payload** (= counter_event_idxs が hand 変化後に古く、
        # 別カードの index を指す) で 起こりうる。 raise すると session が engine error で 落ちる
        # ため graceful skip + defense payload 再構築 (= opp_attack stale 修正と同型。 2026-06-05
        # 広デッキプール fuzz が「非EVENT に counter_event」 cardrush_1276 で検出)。
        def _stale_skip(reason: str) -> None:
            self.state.push_log(f"  counter event 不発 (stale payload): {reason}")
            self._rebuild_defense_payload()
        if not (0 <= hand_idx < len(defender.hand)):
            return _stale_skip(f"hand_idx={hand_idx} 範囲外")
        card = defender.hand[hand_idx]
        # 検証: EVENT + 【カウンター】 効果あり + DON cost 払える
        if not str(getattr(card, "category", "")).endswith("EVENT"):
            return _stale_skip(f"hand[{hand_idx}]={card.name} は EVENT でない")
        overlay = self.state.effects_overlay or {}
        bundle = overlay.get(card.card_id)
        has_counter = False
        if bundle is not None:
            effects_list = bundle.effects if hasattr(bundle, "effects") else (
                bundle if isinstance(bundle, list) else []
            )
            for e in effects_list:
                if isinstance(e, dict) and e.get("when") == "counter":
                    has_counter = True
                    break
        if not has_counter:
            return _stale_skip(f"{card.name} に counter 効果なし")
        if defender.don_active < card.cost:
            return _stale_skip(f"{card.name} DON 不足 (need {card.cost}, have {defender.don_active})")
        # cost 払い + hand → trash (= _fire_counter_events と 同 step)
        defender.hand.pop(hand_idx)
        defender.don_rested += card.cost
        defender.don_active -= card.cost
        defender.trash.append(card)
        self.state.push_log(f"  counter event: {card.name} (cost {card.cost})")
        # counter event 発動 (= 既存 trigger_counter_event を 流用)
        from .effects import trigger_counter_event
        prev_forced = getattr(self.state, "forced_human_actor_idx", None)
        self.state.forced_human_actor_idx = defender_idx
        try:
            trigger_counter_event(
                self.state, defender, attacker_player, card, self.state.effects_overlay,
            )
        finally:
            self.state.forced_human_actor_idx = prev_forced
        # modal pending (= discard / target) なら choice へ 切替
        if self.state.pending_choice is not None:
            self.pending_kind = "choice"
            self.pending_payload = dict(self.state.pending_choice)
            return
        # 全 解決済 → defense modal を 再構築 (= hand 縮小 + attacker_power 再評価)
        self._rebuild_defense_payload()

    def _rebuild_defense_payload(self) -> None:
        """defense pending payload を 現 state から 再構築 (= counter event 発動 後 の hand
        変化 / attacker_power 変動 反映)。 共通 candidate 抽出 ロジック は HumanAI.choose_defense
        と 同じ。 hand pop で idx が ずれる ため legal_counter_card_idxs / counter_event_idxs
        を 完全再計算。"""
        if self.pending_payload is None:
            return
        defender_idx = self.human_idx
        defender = self.state.players[defender_idx]
        attacker_iid = self.pending_payload.get("attacker_iid")
        # attacker_power を 最新 値 に
        for ip in [
            *self.state.players[1 - defender_idx].characters,
            self.state.players[1 - defender_idx].leader,
        ]:
            if ip.instance_id == attacker_iid:
                self.pending_payload["attacker_power"] = int(getattr(ip, "power", 0) or 0)
                break
        # legal_counter_card_idxs / counter_event_idxs / counter_values を 再計算
        overlay = self.state.effects_overlay or {}
        don_avail = defender.don_active
        counter_idxs: list[int] = []
        counter_values: dict[int, int] = {}
        counter_event_idxs: list[int] = []
        for i, c in enumerate(defender.hand):
            counter_val = int(c.counter) if (c.counter and c.counter > 0) else 0
            is_counter_event = False
            if str(getattr(c, "category", "")).endswith("EVENT"):
                eff_bundle = overlay.get(c.card_id)
                effects_list = []
                if eff_bundle is not None:
                    if hasattr(eff_bundle, "effects"):
                        effects_list = eff_bundle.effects
                    elif isinstance(eff_bundle, list):
                        effects_list = eff_bundle
                for e in effects_list:
                    if isinstance(e, dict) and e.get("when") == "counter":
                        if c.cost <= don_avail:
                            is_counter_event = True
                        break
            if counter_val > 0 or is_counter_event:
                counter_idxs.append(i)
                counter_values[i] = counter_val
                if is_counter_event:
                    counter_event_idxs.append(i)
        self.pending_payload["legal_counter_card_idxs"] = counter_idxs
        self.pending_payload["counter_values"] = counter_values
        self.pending_payload["counter_event_idxs"] = counter_event_idxs
        # available_opp_attack_effects も source が 現在 場 に 居る もの だけ に 限定
        # (= choose_defense と 同型、 stale source の 幽霊ボタンを 除去)。
        field_iids = {
            ip.instance_id
            for ip in [defender.leader, *defender.characters, *defender.stages]
        }
        avail = [
            e for e in (getattr(self.state, "_available_opp_attack_effects", []) or [])
            if e.get("source_iid") in field_iids
        ]
        self.state._available_opp_attack_effects = list(avail)
        self.pending_payload["available_opp_attack_effects"] = list(avail)

    def apply_human_use_opp_attack_effect(
        self, source_iid: int, effect_idx: int
    ) -> None:
        """防御 pending 中、 場 の カード を クリック して 【相手のアタック時】 効果 を 発動。
        cost (DON / 手札) を 支払い + 効果 fire → 更新 された defense payload で 再 pause。
        """
        if self.pending_kind != "defense":
            raise ValueError("not waiting for human defense")
        # available list から 該当 effect を 取得
        avail = getattr(self.state, "_available_opp_attack_effects", []) or []
        match = None
        for e in avail:
            if e.get("source_iid") == source_iid and e.get("effect_idx") == effect_idx:
                match = e
                break
        if match is None:
            # 既に消費済/支払い不能で除外済の効果を (= 古い payload 等で) 再指定した場合は no-op。
            # raise すると session が落ちるため graceful skip (= 2026-06-05 fuzz 検出)。
            # payload を最新の available list に同期 (= client が同じ stale effect を再指定し続けて
            # ループするのを防ぐ。 success path は line 641 で同期済だが graceful return は素通りだった)。
            if isinstance(self.pending_payload, dict):
                self.pending_payload["available_opp_attack_effects"] = list(
                    getattr(self.state, "_available_opp_attack_effects", []))
            return
        # cost 支払い + enqueue
        defender_idx = self.human_idx
        defender = self.state.players[defender_idx]
        source = None
        for ip in [defender.leader, *defender.characters, *defender.stages]:
            if ip.instance_id == source_iid:
                source = ip
                break
        if source is None:
            # source が 場 を 離れた (= stale entry / カードが KO・離脱 済) 場合は raise すると
            # session が engine error で 落ちる ため graceful skip + 候補 list を 現場に 同期。
            # producer 側 (choose_defense/_rebuild) で 既に filter 済 だが、 client が 古い payload で
            # 再指定した 場合の 防御。 match-None / cost不能 の graceful path と 同型。
            self.state._available_opp_attack_effects = [
                e for e in (getattr(self.state, "_available_opp_attack_effects", []) or [])
                if e.get("source_iid") != source_iid
            ]
            if isinstance(self.pending_payload, dict):
                self.pending_payload["available_opp_attack_effects"] = list(
                    self.state._available_opp_attack_effects)
            return
        bundle = self.state.effects_overlay.get(source.card.card_id) if self.state.effects_overlay else None
        if bundle is None:
            return
        eff = bundle.effects[effect_idx] if 0 <= effect_idx < len(bundle.effects) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        # cost 支払い: 全 cost キーを _pay_counter_cost に委譲して AI 経路と統一する
        # (= 旧実装は pay_don/rest_self_don/discard_hand のみ inline で、 rest_self/trash_self/
        #   discard_hand_with_filter 等を踏み倒していた。 2026-06-04 修正)。
        from .effects import _pay_counter_cost, _can_pay_counter_cost
        real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
        opp_pl = self.state.players[1 - defender_idx]
        if real_cost and not _can_pay_counter_cost(self.state, defender, source, real_cost):
            # 提示後に state が変わり (= 別の opp_attack 効果を先に発動して資源消費 等) 払えなく
            # なった場合は 発動せず skip + 候補から除外し、 防御 pending を維持。 raise すると
            # session が engine error で落ちるため (= 2026-06-05 人間×環境デッキ fuzz が検出)。
            self.state.push_log(
                f"  opp_attack 効果 不発: コスト支払い不能 ({source.card.name})"
            )
            self.state._available_opp_attack_effects = [
                e for e in avail
                if not (e.get("source_iid") == source_iid
                        and e.get("effect_idx") == effect_idx)
            ]
            if isinstance(self.pending_payload, dict):
                self.pending_payload["available_opp_attack_effects"] = list(
                    self.state._available_opp_attack_effects)
            return
        if real_cost:
            _pay_counter_cost(self.state, defender, opp_pl, source, real_cost)
        if cost.get("once_per_turn"):
            setattr(source, f"_opp_attack_used_{effect_idx}", True)
        when_key = str(match.get("when_key") or "opp_attack")
        from .effects import enqueue_event, resolve_triggers
        enqueue_event(
            self.state,
            when=when_key,
            owner_idx=defender_idx,
            source_card_id=source.card.card_id,
            source_iid=source.instance_id,
            payload={"effect_indexes": [effect_idx]},
        )
        prev_forced = getattr(self.state, "forced_human_actor_idx", None)
        self.state.forced_human_actor_idx = defender_idx
        try:
            resolve_triggers(self.state)
        finally:
            self.state.forced_human_actor_idx = prev_forced
        # available list から 消費 済 を 除外
        self.state._available_opp_attack_effects = [
            e for e in avail
            if not (e.get("source_iid") == source_iid and e.get("effect_idx") == effect_idx)
        ]
        # 効果 解決中 に target_pick 等 の pending_choice が 立った場合 (= OP14-060
        # ドフラ の 「リーダー or ドンキホーテ海賊団 キャラ」 選択 等) は そちら を
        # 優先 表示。 user 解決 後 advance_until_pause で defense に 戻る。
        if self.state.pending_choice is not None:
            self.pending_kind = "choice"
            self.pending_payload = dict(self.state.pending_choice)
            return
        # defense payload を 更新: attacker_power が 変動 した 可能性 があるので 再構築
        if self.pending_payload is not None:
            attacker_iid = self.pending_payload.get("attacker_iid")
            # 最新 power を 反映
            for ip in [*self.state.players[1 - defender_idx].characters, self.state.players[1 - defender_idx].leader]:
                if ip.instance_id == attacker_iid:
                    self.pending_payload["attacker_power"] = int(getattr(ip, "power", 0) or 0)
                    break
            self.pending_payload["available_opp_attack_effects"] = list(self.state._available_opp_attack_effects)

    def serialize_for_log(self) -> dict:
        """試合終了後 or 中断 試合 の full データ を 1 dict に まとめる (= Blob upload 用)。

        含むもの:
        - metadata: timestamp / deck slugs / seed / human_first / winner / turns
        - log: 全 push_log
        - snapshots: 全 snapshot (= 中間 state、 frontend 再生 と同じ)
        - action_evals: 全 action の eval_before/after/delta (= 人間 + AI 両方、
          player_idx で 分離可能。 「AI 悪手」 + 「人間 良手」 両方の 解析素材)
        - winner_for_human: 1=人間勝利、 0=AI勝利、 -1=引き分け/時間切れ/中断

        2026-05-31 fix: 旧 logic は game_over=True 必須 で 中 断 試合 (= 「対 戦 終了」
        ボタン) で 500 error → ohtsuki さん の log メモ が 消 失。 #67 で API endpoint
        の game_over check は 撤 廃 し た が、 こ こ で の check が 残 留 し て て 真因 だ っ た。
        中 断 試合 で も serialize 可 能 化、 winner_for_human=-1 (= 引き分け/中断)。
        """
        # game_over check 撤 廃 (= 中 断 試合 で も serialize)。 winner=-1 で 「中断」 を
        # 表 現 (= 既 「-1=引き分け/時間切れ」 と 同 値)。

        from datetime import datetime, timezone

        winner_for_human = -1
        if self.state.winner == self.human_idx:
            winner_for_human = 1
        elif self.state.winner == self.ai_idx:
            winner_for_human = 0

        ai_class_name = type(self.ai).__name__
        ai_spec_version = getattr(self.ai, "spec_version", None)

        return {
            "schema_version": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "deck_human_slug": self.deck_a_slug,
                "deck_ai_slug": self.deck_b_slug,
                "human_idx": self.human_idx,
                "ai_idx": self.ai_idx,
                "human_first": (self.human_idx == 0),
                "seed": getattr(self.rng, "_seed_for_log", None),
                "ai_class": ai_class_name,
                "ai_spec_version": ai_spec_version,
            },
            "result": {
                "winner_idx": self.state.winner,
                "winner_for_human": winner_for_human,
                "turns": self.state.turn_number,
                "p_human_life_left": len(self.state.players[self.human_idx].life),
                "p_ai_life_left": len(self.state.players[self.ai_idx].life),
            },
            "log": list(self.state.log),
            "snapshots": [dict(s) for s in self.state.snapshots],
            "action_evals": list(self.state.action_evals),
            "log_comments": list(self.log_comments),
            # 効果ランタイム・レフェリーの検出 (= カード保存則違反、 通常は空)。
            # 実プレイで非空なら 効果バグの確証 → Blob 解析素材になる。
            "referee_violations": list(getattr(self, "referee_violations", [])),
        }

    def add_log_comment(
        self,
        log_index: int,
        comment: str,
        log_text: Optional[str] = None,
    ) -> dict:
        """log の 指定 行 に user コメント を 紐付け。

        bug 報告 / 違和感 メモ を 蓄積し、 serialize_for_log で Blob upload に含める。
        名前 / id 不要 (= ohtsuki さん 依頼 通り 「コメント だけ」 で OK)。
        """
        from datetime import datetime, timezone

        entry = {
            "log_index": int(log_index),
            "comment": str(comment).strip(),
            "log_text": str(log_text) if log_text is not None else None,
            "turn_number": int(getattr(self.state, "turn_number", 0)),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.log_comments.append(entry)
        return entry

    def save_replay(self, max_per_pair: int = 500) -> Optional[int]:
        """試合終了後 に 棋譜 を db/match_replays.sqlite に 保存。

        Returns: replay row id (= 成功時)、 失敗 / 未完 なら None。
        """
        if not self.state.game_over:
            return None
        from .replay_recorder import save_replay

        winner_for_deck_a = -1
        if self.state.winner == self.human_idx:
            winner_for_deck_a = 0  # 人間 (deck_a) 勝利
        elif self.state.winner == self.ai_idx:
            winner_for_deck_a = 1  # AI (deck_b) 勝利

        try:
            return save_replay(
                deck_a=self.deck_a_slug,
                deck_b=self.deck_b_slug,
                game_idx=0,
                winner_for_deck_a=winner_for_deck_a,
                first_player=0 if self.human_idx == 0 else 1,
                turns=self.state.turn_number,
                log=list(self.state.log),
                snapshots=list(self.state.snapshots),
                seed=0,
                extra_meta={
                    "source": "human_vs_ai",
                    "human_idx": self.human_idx,
                    "ai_idx": self.ai_idx,
                },
                max_per_pair=max_per_pair,
            )
        except Exception:
            return None

    def _consume_new_frames(self) -> list[dict]:
        """前回 payload 返却 以降 に 追加 された snapshot を 返す + baseline 更新。

        AI ターン中 の 中間 state を frontend 側 で 順次 アニメ 再生 する 用途。
        """
        all_snaps = self.state.snapshots
        new_frames = all_snaps[self._last_seen_snapshot_count:]
        self._last_seen_snapshot_count = len(all_snaps)
        return [dict(s) for s in new_frames]

    def snapshot_payload(self) -> dict:
        """API レスポンス 用 の 全 state snapshot。"""
        # 最終 snapshot は state.snapshots 末尾 を 取る (= 既存 仕組み と整合)
        last_snap = self.state.snapshots[-1] if self.state.snapshots else None
        frames = self._consume_new_frames()
        # UI 用ログの秘匿マスク (= 内部 state.log は無改変、 表示用のみ redact)。 frames の log 文字列
        # にも同じ redact をかける (= animation 分類の keyword は残るので挙動不変)。
        for _f in frames:
            if isinstance(_f.get("log"), str):
                _f["log"] = _redact_log_line_for_ui(_f["log"], self.human_idx)
        # 相手の伏せ手札を payload から除く (= 公開分 known のみ、 内部 snapshot は無改変)。
        frames = [_redact_snapshot_for_ui(_f, self.human_idx) for _f in frames]
        if last_snap is not None:
            last_snap = _redact_snapshot_for_ui(last_snap, self.human_idx)
        # 今この盤面で人間プレイヤーの手札/場に揃っているデッキ内コンボ (= 対戦時活用)。
        try:
            from .combo_readiness import live_deck_combos
            live_combos = live_deck_combos(self.state, self.human_idx)
        except Exception:
            live_combos = []
        return {
            "game_over": self.state.game_over,
            "winner": self.state.winner,
            "turn": self.state.turn_number,
            "turn_player_idx": self.state.turn_player_idx,
            "phase": (
                self.state.phase.name
                if hasattr(self.state.phase, "name")
                else str(self.state.phase)
            ),
            "human_idx": self.human_idx,
            "ai_idx": self.ai_idx,
            "pending_kind": self.pending_kind,
            "pending_payload": self.pending_payload,
            "log": _redact_log_for_ui(list(self.state.log[-30:]), self.human_idx),  # 直近 30 行(UI用 redact)
            "snapshot": last_snap,
            "frames": frames,
            "legal_actions": self.legal_actions_for_human(),
            "snapshots_count": len(self.state.snapshots),
            "deck_a_slug": self.deck_a_slug,
            "deck_b_slug": self.deck_b_slug,
            "live_combos": live_combos,
        }


_LIFE_TAKE_PAREN_RE = re.compile(r"\([^)]*\)\s*$")
_LOG_PREFIX_RE = re.compile(r"^T\d+ P(\d+):")


def _redact_log_line_for_ui(line: str, viewer_idx: int) -> str:
    """UI 表示用ログの秘匿マスク (= 内部 state.log とは分離。 ohtsuki「UIに表示するlogと実際のlogは
    分けるべき、 トレードオフではない」)。 公式 rule_manual: リーダーがダメージを受けた時、 取った
    ライフは「自分だけ確認」= 相手はトリガーを使わない限り中身を知らない。 → 攻撃側 (= ターン
    プレイヤー P{idx}) が viewer のとき、 相手が受けたライフの中身 (ライフ受け取り / life->hand =
    トリガー不使用で手札へ) のカード名を伏せる。 trigger->* (発動=公開済) や BANISH (trash=公開
    領域) はそのまま。 「life->hand」「ライフ受け取り」 keyword は残すので frame の animation 分類は不変。"""
    if not isinstance(line, str):
        return line
    m = _LOG_PREFIX_RE.match(line)
    if (m and int(m.group(1)) == viewer_idx
            and ("ライフ受け取り" in line or "life->hand" in line)):
        return _LIFE_TAKE_PAREN_RE.sub("(相手のみ確認)", line)
    return line


def _redact_log_for_ui(lines, viewer_idx: int) -> list:
    """UI 用ログ行リストを viewer 視点で秘匿マスク (内部 state.log は無改変)。"""
    return [_redact_log_line_for_ui(l, viewer_idx) for l in lines]


def _redact_snapshot_for_ui(snap, human_idx: int):
    """UI 用 snapshot の秘匿マスク (= 内部 state.snapshots は無改変。 「UIに表示する情報と実際の情報は
    分ける」)。 相手(= ai_idx)の手札は公開分(known_hand_card_ids = サーチ「公開して手札に加える」等で
    公開したカード)だけを payload に載せ、 伏せ手札の card_id は送らない (= payload を覗いても相手の
    手札は見えない。 face-down 表示は hand_count で正しく出る)。 trash / 場 は公開領域なのでそのまま。
    自分(human)の手札は無改変。 shallow copy で内部 snapshot を破壊しない。"""
    if not isinstance(snap, dict):
        return snap
    players = snap.get("players")
    if not isinstance(players, list):
        return snap
    ai_idx = 1 - human_idx
    if ai_idx < 0 or ai_idx >= len(players):
        return snap
    opp = players[ai_idx]
    if not isinstance(opp, dict):
        return snap
    new_snap = dict(snap)
    new_players = list(players)
    opp2 = dict(opp)
    opp2["hand"] = list(opp2.get("known_hand_card_ids") or [])  # 公開分のみ (伏せ手札は送らない)
    new_players[ai_idx] = opp2
    new_snap["players"] = new_players
    return new_snap


def _action_to_dict(action, idx: int) -> dict:
    """Action を JSON-able dict に。 instance_id / hand_idx 等 を 表示する形に。"""
    cls = type(action).__name__
    out = {"idx": idx, "kind": cls}
    for f in (
        "hand_idx",
        "iid",
        "instance_id",
        "attacker_iid",
        "target_iid",
        "source_iid",
        "effect_index",
        "from_idx",
        "to_iid",
        "n",
        "card_id",
        "sacrifice_iid",  # 場 5 体 差 替 え 時 の trash 対 象 (= 3-7-6-1)
    ):
        if hasattr(action, f):
            v = getattr(action, f)
            if v is not None:
                out[f] = v
    # human 用 短文 description (= UI ボタン 文言)
    out["label"] = _action_label(action)
    return out


def _action_label(action) -> str:
    cls = type(action).__name__
    if cls == "PlayCharacter":
        sac = getattr(action, "sacrifice_iid", None)
        if sac is not None:
            return f"キャラ登場: hand[{action.hand_idx}] (差替 iid={sac})"
        return f"キャラ登場: hand[{action.hand_idx}]"
    if cls == "PlayEvent":
        return f"イベント発動: hand[{action.hand_idx}]"
    if cls == "PlayStage":
        return f"ステージ設置: hand[{action.hand_idx}]"
    if cls == "AttachDonToLeader":
        return f"DON → リーダー x{getattr(action, 'n', 1)}"
    if cls == "AttachDonToCharacter":
        return f"DON → キャラ iid={action.target_iid} x{getattr(action, 'n', 1)}"
    if cls == "AttackLeader":
        return f"リーダー攻撃: attacker={action.attacker_iid}"
    if cls == "AttackCharacter":
        return f"キャラ攻撃: attacker={action.attacker_iid} → target={action.target_iid}"
    if cls == "ActivateMain":
        return f"起動メイン: iid={action.source_iid} effect[{action.effect_index}]"
    if cls == "EndPhase":
        return "ターン終了"
    if cls == "EventPlay":
        return f"イベント: hand[{getattr(action, 'hand_idx', '?')}]"
    return cls
