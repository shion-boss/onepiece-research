# -*- coding: utf-8 -*-
"""
効果 DSL
=========

ワンピカードのカード効果を JSON で記述するためのプリミティブ群。

# 効果の記述例 (db/card_effects.json):
{
  "OP01-013": [
    {
      "when": "on_play",
      "if": {"leader_feature": "麦わらの一味"},
      "do": [{"draw": 1}]
    }
  ],
  "OP02-002": [
    {
      "when": "activate_main",
      "cost": {"rest_self": true},
      "do": [{"draw": 1}, {"trash_self_hand_random": 1}]
    }
  ]
}

# プリミティブ
| primitive             | 意味                                                |
| --------------------- | ------------------------------------------------- |
| draw N                | N 枚ドロー                                            |
| trash_self N          | 自分のトラッシュに手札 N 枚                                  |
| ko target             | 対象を KO                                            |
| power_pump T:N        | T のパワーを +N (このターン中)                              |
| rest target           | 対象をレスト                                            |
| return_to_hand target | 対象を手札に戻す                                          |
| search filter limit   | デッキから条件に合うカードを探して手札へ                              |
| life_to_hand N        | 自分のライフ N 枚を手札に                                   |
| add_don N             | ドン+N (アクティブ)                                      |

# when (トリガー)
| trigger              | 意味                                                |
| -------------------- | ------------------------------------------------- |
| on_play              | 登場時 (キャラ自身)                                       |
| activate_main        | 起動メイン (能動的に発動。コストあり)                              |
| end_of_turn          | 自分のターン終了時                                         |
| on_attack            | このカードでアタック時                                       |
| on_attached_don N    | ドン!!N 枚付与時 (常時条件)                                |

最小実装。まずは on_play, activate_main, on_attack の 3 種類のみサポート。
"""

from __future__ import annotations

import itertools
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .core import CardDef, Category, GameState, InPlay, Player, normalize_card_name


# --------------------------------------------------------------------------- #
# 効果オーバーレイの読み込み
# --------------------------------------------------------------------------- #
EffectSpec = dict[str, Any]


@dataclass
class CardEffectBundle:
    """1 枚のカードに紐づく効果のリスト。"""

    card_id: str
    effects: list[EffectSpec] = field(default_factory=list)


_NAME_KEYS = {"name", "exclude_name"}


def _normalize_overlay_names(obj):
    """overlay 内の カード名参照 (name / exclude_name / name_in) を 正準形 (半角D) に揃える。

    公式データの 全角Ｄ↔半角D 混在に対し、 card.name 側 (= normalize_card_name) と
    overlay 側 の双方を 正規化して 名前一致 を成立させる (silent no-op 防止)。
    """
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in _NAME_KEYS and isinstance(v, str):
                obj[k] = normalize_card_name(v)
            elif k == "name_in" and isinstance(v, list):
                obj[k] = [normalize_card_name(x) if isinstance(x, str) else x for x in v]
            else:
                _normalize_overlay_names(v)
    elif isinstance(obj, list):
        for x in obj:
            _normalize_overlay_names(x)
    return obj


def load_effect_overlay(path: str | Path) -> dict[str, CardEffectBundle]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, CardEffectBundle] = {}
    for cid, effects in raw.items():
        if cid.startswith("_"):  # _meta などは無視
            continue
        if not isinstance(effects, list):
            continue
        out[cid] = CardEffectBundle(card_id=cid, effects=_normalize_overlay_names(effects))
    return out


# --------------------------------------------------------------------------- #
# トリガーループ (FIFO + アクティブプレイヤー優先)
# --------------------------------------------------------------------------- #
# 設計概要:
#   各 trigger_* (= イベント発火点) は同期で「fire するか」 「replace するか」 等の
#   即時決定を行い、 実体の効果実行は TriggerEvent としてキューに積む。
#   apply_action / advance_phase の最後に resolve_triggers(state) を一度呼ぶと、
#   キューが空になるまで FIFO + アクティブプレイヤー優先で順次実行する。
#
#   公式 8-1-2: 効果は発動プレイヤーがすべて解決後、 相手プレイヤーが解決。
#   公式 8-1-3: 同時発火の同陣営内順序は発動プレイヤーが任意 (= AI フックで選択可)。
@dataclass
class TriggerEvent:
    """トリガー解決キューの 1 エントリ。

    when:           "on_play" / "on_ko" / "on_attack" / "opp_attack" / "on_block" /
                    "on_turn_start" / "opp_turn_start" / "end_of_turn" /
                    "opp_end_of_turn" / "main" / "counter" / "trigger" /
                    "activate_main"
    owner_idx:      この効果の「自分」側プレイヤー idx (0 or 1)。
                    AI フック / アクティブプレイヤー優先判定に使う。
    source_card_id: 効果バンドル検索キー (= card.card_id)。
                    on_ko 等で InPlay が場から消えた後でも参照可能。
    source_iid:     発火元 InPlay の instance_id (= 場に残っていれば bundle 起点として使える)。
                    on_ko / counter / main 等、 発火時点で既に場にないならば None。
    payload:        when ごとの追加情報。
                    - on_attack/opp_attack/on_block: attacker_iid
                    - lifecard trigger: defender_idx, attacker_idx (固定値)
                    - activate_main: effect_index (= bundle.effects 内の index)
    """

    when: str
    owner_idx: int
    source_card_id: str
    source_iid: Optional[int] = None
    payload: dict = field(default_factory=dict)


def enqueue_event(
    state: GameState,
    when: str,
    owner_idx: int,
    source_card_id: str,
    source_iid: Optional[int] = None,
    payload: Optional[dict] = None,
) -> None:
    """トリガーをキューに追加。 resolve_triggers を別途呼ぶ必要あり。"""
    state.event_queue.append(
        TriggerEvent(
            when=when,
            owner_idx=owner_idx,
            source_card_id=source_card_id,
            source_iid=source_iid,
            payload=payload or {},
        )
    )


def _pop_next_event(state: GameState) -> Optional[TriggerEvent]:
    """次に解決すべきイベントを 1 つ取り出す。

    優先順序:
    1. owner_idx == turn_player_idx のものを先に
    2. 同 owner 内では FIFO (= enqueue 順)
    3. event_order_hook があれば 同 owner / 同 when グループ内で AI が再順序付け可能
    """
    if not state.event_queue:
        return None
    turn_idx = state.turn_player_idx
    # まずアクティブプレイヤー側を探す
    active_events = [e for e in state.event_queue if e.owner_idx == turn_idx]
    if not active_events:
        # 非アクティブ側のみ → FIFO 先頭
        evt = state.event_queue[0]
        state.event_queue.remove(evt)
        return evt
    # AI フックがあれば 同 when の連続グループを取り出して順序選択
    hook = state.event_order_hook
    if hook is not None and len(active_events) > 1:
        # 同 when の先頭グループを抽出 (FIFO 順)
        first_when = active_events[0].when
        group = [e for e in active_events if e.when == first_when]
        if len(group) > 1:
            ordered = hook(state, group)
            if ordered:
                evt = ordered[0]
                state.event_queue.remove(evt)
                return evt
    evt = active_events[0]
    state.event_queue.remove(evt)
    return evt


def resolve_triggers(state: GameState) -> None:
    """イベントキューが空になるまでドレイン。

    再入呼び出し (= 効果実行中に資源解放のため別ルートから呼ばれた) は no-op。
    apply_action 末尾、 advance_phase 末尾、 ライフトリガー処理直後など、
    「アクション境界」 で 1 回だけ呼べば良い。
    """
    if state.resolving:
        return
    if not state.event_queue:
        return
    state.resolving = True
    try:
        while state.event_queue:
            evt = _pop_next_event(state)
            if evt is None:
                break
            _execute_event(state, evt)
            if state.pending_choice is not None:
                # 人間 target pick 待ち → queue drain を halt。 残り event は queue に
                # 残し、 pick 解決後 (resolve_pending_choice 末尾) に 再 drain する。
                # これが無いと 次 event が pending_choice を 上書き し、 friendly pick が
                # 喪失 する (= 温度レアァストライク ST29-015 の friendly +2000 / opp -2000 が
                # 別 enqueue の counter event で、 +2000 の pick が -2000 に潰されていた bug)。
                break
    finally:
        state.resolving = False


def _execute_event(state: GameState, evt: TriggerEvent) -> None:
    """1 イベントを実行。 owner / opp を解決し、 該当 bundle の when 効果を発火。

    on_play / on_attack / on_block / on_ko / on_turn_start / opp_turn_start /
    end_of_turn / opp_end_of_turn / opp_attack / main / counter / trigger /
    activate_main / replace_ko を分岐処理。
    """
    overlay = state.effects_overlay
    if not overlay:
        return
    bundle = overlay.get(evt.source_card_id)
    if bundle is None:
        return

    me = state.players[evt.owner_idx]
    opp = state.players[1 - evt.owner_idx]

    # source_iid が指定されていれば、 場に残っているかチェック
    self_inplay: Optional[InPlay] = None
    if evt.source_iid is not None:
        for ip in [me.leader, *me.characters, *me.stages]:
            if ip.instance_id == evt.source_iid:
                self_inplay = ip
                break
        # 場から消えている場合: on_ko 等は self_inplay=None で許容、
        # cost で 既に 自身 trash 済 (= effect_indexes で 既払い 明示) の 場合 も 許容。
        # それ以外 (on_attack/on_block 等) は途中で KO されたので発火中止。
        cost_paid_explicit = (
            evt.payload.get("effect_indexes") is not None
            and evt.when in ("activate_main", "end_of_turn", "opp_end_of_turn")
        )
        if (
            self_inplay is None
            and not cost_paid_explicit
            and evt.when not in ("on_ko", "main", "counter", "trigger")
        ):
            return
        # 効果無効化 (negate_effect/disable_effect プリミティブで付与)。 場にいて、 かつ
        # source が「効果無効」 キーワード or ターン跨ぎ無効フラグを持っているなら抑止。
        # ⚠ 公式 「効果を無効にする」 に when の区別は無い = 発動する効果は全て抑止される。
        #   旧実装は 「主要効果のみ (on_play/on_attack/activate_main/main/counter)」 に絞って
        #   おり、 【相手のアタック時】/【ブロック時】 が **無効化されても発動していた**
        #   (2026-08-04 発覚)。 静的効果は _recompute_static 側で別途抑止している。
        #   ⚠ 【KO時】 も公式 Q&A (cardqa_op_09/op_10 「効果を無効にされたキャラがKOされた
        #   場合、 そのキャラの持つ【KO時】効果は発動できますか？」→「いいえ」) で抑止だが、
        #   on_ko は source が既に場外 (self_inplay=None) でここを通らない → 別途対応が要る。
        if (
            self_inplay is not None
            and (
                "効果無効" in self_inplay.granted_keywords
                or self_inplay.effect_disabled_through_opp_turn
            )
            and evt.when in ("on_play", "on_attack", "activate_main", "main", "counter",
                             "opp_attack", "on_block")
        ):
            state.push_log(
                f"  効果無効: {self_inplay.card.name} の【{evt.when}】 は発動されない"
            )
            return

    when = evt.when

    # play_self / fire_self_effect が self_inplay=None でも source_card_id を参照できるよう、
    # state にスタック (元の値を退避 → 復元)。
    prev_src_cid = getattr(state, "current_source_card_id", None)
    state.current_source_card_id = evt.source_card_id

    # forced_human_actor_idx を 「この event の owner が human なら 設定、 AI なら -1
    # (= 強制 block)」 で 上書き。 AI-owned event の choice が 人間 に 出ない 様 に。
    # 元値 は finally で 復元。
    prev_forced = getattr(state, "forced_human_actor_idx", None)
    if state.human_player_idx is None:
        state.forced_human_actor_idx = None  # AI vs AI: 通常挙動
    elif evt.owner_idx == state.human_player_idx:
        state.forced_human_actor_idx = state.human_player_idx
    else:
        state.forced_human_actor_idx = -1  # AI-owned event: human pick 禁止

    # on_ko の by_opp_effect コンテキストを 一時的に state に設定 (= 条件評価用)
    prev_ko_by_opp = getattr(state, "last_ko_by_opp_effect", None)
    if when == "on_ko" and "by_opp_effect" in evt.payload:
        state.last_ko_by_opp_effect = bool(evt.payload["by_opp_effect"])

    try:
        # payload.effect_indexes が指定されていれば、 その index の効果のみ発火 (cost 既払い)。
        # activate_main / on_attack (cost 持ち) で使う。
        explicit_idxs = evt.payload.get("effect_indexes")
        if explicit_idxs is not None:
            for idx in explicit_idxs:
                if not (0 <= idx < len(bundle.effects)):
                    continue
                eff = bundle.effects[idx]
                if eff.get("when") != when:
                    continue
                # cost 既払いなので if 句のみ再評価 (条件変動の可能性に備える)
                if not eval_all_conditions(eff, state, me, self_inplay):
                    continue
                # 【ターン1回】 ガード (cost 経由ではない top-level once_per_turn)。
                # cost 持ち効果は trigger_on_attack/fire_activate_main 側で支払い時にチェック済み。
                # ここは「cost 不要の once_per_turn」 (= on_play / on_attack 非コスト等) を扱う。
                if _check_and_set_once_per_turn(
                    state, me, eff, evt.source_card_id, idx,
                    source_iid=evt.source_iid,
                ) is False:
                    continue
                run_do_array(eff.get("do", []), state, me, opp, self_inplay)
            return

        # 通常の when 一致 effects を全て発火
        for idx, eff in enumerate(bundle.effects):
            if eff.get("when") != when:
                continue
            if not eval_all_conditions(eff, state, me, self_inplay):
                # silent skip だと AI が 無駄 play しても 観戦/ Human Play log に 痕跡 なし。
                # Phase 1.2 (= 2026-05-26): if 条件 不一致 を 明示 ログ 化 し、
                # 解析 skill (= analyze-human-play-log / analyze-ai-matchup-log) で 検出可能 に。
                state.push_log(
                    f"  {when} 効果: if 条件 不一致 → skip ({evt.source_card_id})"
                )
                continue
            # 【ターン1回】 ガード: spec.once_per_turn が True/str なら使用済みチェック
            if _check_and_set_once_per_turn(
                state, me, eff, evt.source_card_id, idx,
                source_iid=evt.source_iid,
            ) is False:
                continue
            # event cost (= 「自分の手札 1 枚を捨てる」 等 任意 コスト):
            # 公式 「コスト：効果」 で コスト 払えない なら 効果 不発 (= 4-10)。
            # 旧 engine は cost を 無視 して 効果 発動 (= bug、 player は コスト 払わず 効果 取得)。
            # 対象 when: counter / on_play / on_ko / on_block / main / trigger /
            #            on_*_X (= on_self_chara_played 等)、 計 500+ cards 影響。
            # cost が 既 払い 済 (= explicit_idxs) や 別 path で 処理 (= activate_main /
            # on_attack / end_of_turn / opp_attack) の when は ここに 来ない。
            # 人間 acting + discard_hand cost なら modal で 捨てる カード を 選ばせる。
            # AI / その他 cost は auto-pay (= random discard / DON 等)。
            cost = eff.get("cost") or {}
            # cost が array (= replace_ko 等 の 特殊 形式) は ここでは scope 外。
            if isinstance(cost, dict) and cost and when in (
                "counter", "on_play", "on_ko", "on_block", "main", "trigger",
                "on_self_chara_played", "on_opp_chara_played",
                "on_self_chara_ko", "on_opp_chara_ko",
                "on_self_chara_leave_by_self_effect",
                "on_self_chara_leave_by_opp_effect",
                "on_opp_chara_returned_to_hand_by_self_effect",
                "on_self_rested", "on_self_chara_rested_by_self_effect",
                "on_self_hand_discarded", "on_self_don_returned_to_deck",
                "on_self_event_played", "on_opp_event_or_trigger_fired",
                "opp_event_played",
                "on_self_life_taken", "on_opp_life_taken",
                "on_self_life_to_hand", "on_self_life_to_trash",
                "on_self_draw_non_draw_phase", "on_life_zero",
                "opp_attack_on_chara", "opp_attack_on_leader",
                "on_opp_blocker_use",
            ):
                # once_per_turn のみ の cost は 既に _check_and_set_once_per_turn で 処理 済
                # (= 上の if で gate)。 ここに 来た 時点 で 実 cost (= discard/pay_don 等) なし
                # の 場合 は no-op で 通す。
                real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
                if real_cost:
                    if not _can_pay_counter_cost(state, me, self_inplay, real_cost):
                        state.push_log(
                            f"  {when} 効果: cost 支払い不能 → skip ({evt.source_card_id})"
                        )
                        continue
                    discard_n = int(real_cost.get("discard_hand", 0))
                    if discard_n > 0 and _should_human_pick(state) and len(me.hand) >= discard_n:
                        cand_list = [
                            {
                                "hand_idx": i,
                                "card_id": c.card_id,
                                "name": c.name,
                                "cost": int(c.cost) if c.cost is not None else 0,
                                "power": int(c.power) if c.power is not None else 0,
                            }
                            for i, c in enumerate(me.hand)
                        ]
                        state.pending_choice = {
                            "kind": "counter_discard_pick",
                            "when_key": when,
                            "card_id": evt.source_card_id,
                            "owner_idx": evt.owner_idx,
                            "source_iid": evt.source_iid,
                            "effect_idx": idx,
                            "discard_n": discard_n,
                            "cost": real_cost,
                            "candidates": cand_list,
                            "limit": discard_n,
                        }
                        state.push_log(
                            f"  {when} コスト: 手札 {discard_n} 枚 捨てる 対象 を 選択 待ち"
                        )
                        return
                    # discard_hand_with_filter (= 特定カード捨て、 例 OP10-072 イベント1枚)。
                    # 人間 acting なら どのカードを捨てるか modal で 選ばせる (= 該当のみ候補、
                    # 0 枚 = skip で 任意コスト 見送り も 可)。 2026-06-04 追加。
                    dwf = real_cost.get("discard_hand_with_filter")
                    if isinstance(dwf, dict) and _should_human_pick(state):
                        df = dwf.get("filter", {}) if isinstance(dwf.get("filter"), dict) else {}
                        dcnt = int(dwf.get("count", 1))
                        matching = [(i, c) for i, c in enumerate(me.hand)
                                    if _matches_filter(c, df)]
                        if len(matching) >= dcnt:
                            cand_list = [
                                {"hand_idx": i, "card_id": c.card_id, "name": c.name,
                                 "cost": int(c.cost) if c.cost is not None else 0,
                                 "power": int(c.power) if c.power is not None else 0}
                                for i, c in matching
                            ]
                            state.pending_choice = {
                                "kind": "counter_discard_pick", "when_key": when,
                                "card_id": evt.source_card_id, "owner_idx": evt.owner_idx,
                                "source_iid": evt.source_iid, "effect_idx": idx,
                                "discard_n": dcnt, "cost": real_cost,
                                "candidates": cand_list, "limit": dcnt,
                            }
                            state.push_log(
                                f"  {when} コスト: 該当手札 {dcnt} 枚 捨てる 対象 を 選択 待ち"
                            )
                            return
                    # 非discard の任意コスト (= pay_don / life_to_hand / rest_self_don 等) も
                    # 公式「〜することができる：効果」 は 払う/払わない を 本人 に 委ねる
                    # (= discard と一貫、 2026-06-18)。 既存 optional_cost_then 機構経由で
                    # optional_cost_confirm → 承認時に cost+effect を実行 (= 効果解決は共通パス)。
                    # AI (= _should_human_pick False) は この branch を通らず 従来 auto-pay の
                    # ため AI/matrix は不変。 discard 系は上で prompt 済 (= ここは非discardのみ)。
                    nondiscard_real = {
                        k: v for k, v in real_cost.items()
                        if k not in ("discard_hand", "discard_hand_with_filter")
                    }
                    if nondiscard_real and _should_human_pick(state):
                        oct_spec = {
                            "cost": [{k: v} for k, v in nondiscard_real.items()],
                            "effect": eff.get("do", []),
                        }
                        execute_effect(
                            {"optional_cost_then": oct_spec}, state, me, opp, self_inplay
                        )
                        if state.pending_choice is not None:
                            return  # optional_cost_confirm 待ち (= resume は resolve_pending_choice)
                        continue  # 効果は optional_cost_then が解決済 → run_do_array skip
                    _pay_counter_cost(state, me, opp, self_inplay, real_cost)
            run_do_array(eff.get("do", []), state, me, opp, self_inplay)
            if state.pending_choice is not None:
                # 同 bundle の 残り matching entry (= 別 counter/trigger entry) を、
                # 条件を満たす分だけ pending_choice の _continuation に退避 → pick 解決後に
                # 実行する。 これが無いと 次 entry の run_do_array が pending_choice を
                # 上書きし、 先頭 entry の friendly pick が喪失する
                # (= 温度レアァストライク ST29-015 の friendly +2000 / opp -2000 が
                #    別 counter entry で、 +2000 の pick が -2000 に潰されていた bug)。
                # cost 持ち entry は continuation 経路 未対応 の ため append しない (= 安全側)。
                extra_do: list = []
                for j in range(idx + 1, len(bundle.effects)):
                    e2 = bundle.effects[j]
                    if e2.get("when") != when:
                        continue
                    if e2.get("cost"):
                        continue
                    if not eval_all_conditions(e2, state, me, self_inplay):
                        continue
                    extra_do.extend(e2.get("do", []))
                if extra_do:
                    cont = state.pending_choice.get("_continuation")
                    if cont is None:
                        state.pending_choice["_continuation"] = {
                            "do": extra_do,
                            "owner_idx": state.players.index(me),
                            "source_iid": (self_inplay.instance_id
                                           if self_inplay is not None else None),
                        }
                    else:
                        cont["do"] = list(cont.get("do", [])) + extra_do
                break
    finally:
        state.current_source_card_id = prev_src_cid
        state.forced_human_actor_idx = prev_forced
        if when == "on_ko":
            state.last_ko_by_opp_effect = prev_ko_by_opp


def _can_pay_counter_cost(
    state: GameState,
    me: Player,
    self_inplay: Optional[InPlay],
    cost: dict,
) -> bool:
    """counter event の cost が 支払い可能 か 判定。

    counter event は 「コスト：効果」 で コスト 払えない なら 効果 不発 (公式 4-10)。
    typical cost: discard_hand: 1 / pay_don: N / rest_self_don: N。
    """
    if not isinstance(cost, dict):
        return True
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0 and len(me.hand) < discard_n:
        return False
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0 and _pay_don_capacity(state, me) < pay_don:
        return False
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0 and me.don_active < rest_don:
        return False
    # discard_hand_with_filter (= 「手札から特定カードを捨てる」 例: OP10-072 イベント1枚):
    # 該当カードが count 枚 未満なら 払えない (= 効果不発)。 旧実装は未チェックで効果が
    # コスト無視で発動していた (2026-06-04 修正)。
    dwf = cost.get("discard_hand_with_filter")
    if isinstance(dwf, dict):
        f = dwf.get("filter", {}) if isinstance(dwf.get("filter"), dict) else {}
        cnt = int(dwf.get("count", 1))
        matching = sum(1 for c in me.hand if _matches_filter(c, f))
        if matching < cnt:
            return False
    # --- source 系/特殊コスト (= 旧実装で未処理 → コスト踏み倒しだった、 2026-06-04 修正) ---
    # rest_self (= このキャラ/ステージをレスト): 既にレスト or source 不在なら払えない。
    if cost.get("rest_self"):
        if self_inplay is None or getattr(self_inplay, "rested", False):
            return False
    # return_self_don_to_deck N (= 場のドン N 枚をドンデッキに戻す)
    rdon = int(cost.get("return_self_don_to_deck", 0) or 0)
    if rdon > 0 and (me.don_active + me.don_rested) < rdon:
        return False
    # life → hand 系 (= ライフ上から N 枚を手札に): ライフ不足なら払えない。
    lth = int(cost.get("life_to_hand", 0) or 0)
    if lth > 0 and len(me.life) < lth:
        return False
    ltob = int(cost.get("life_top_or_bottom_to_hand", 0) or 0)
    if ltob > 0 and len(me.life) < ltob:
        return False
    # trash_to_deck N (= トラッシュ N 枚をデッキに): トラッシュ不足なら払えない。
    ttd = int(cost.get("trash_to_deck", 0) or 0)
    if ttd > 0 and len(me.trash) < ttd:
        return False
    # reveal_hand_with_filter (= 手札から該当を N 枚見せる、 情報コスト): 該当不足なら払えない。
    rhf = cost.get("reveal_hand_with_filter")
    if isinstance(rhf, dict):
        f = rhf.get("filter", {}) if isinstance(rhf.get("filter"), dict) else {}
        cnt = int(rhf.get("count", 1))
        if sum(1 for c in me.hand if _matches_filter(c, f)) < cnt:
            return False
    # trash_self / self_ko (= このキャラ自身をトラッシュ/KO): source 不在なら払えない。
    if (cost.get("trash_self") or cost.get("self_ko")) and self_inplay is None:
        return False
    # flip_life_face_down (= 「自分のライフの上か下から1枚を裏向きにできる：」 cost、 ST36-005 キッド):
    # 表向きのライフが 1 枚以上 必要 (= leader 等で表向きにした分を裏向きに戻す)。
    if cost.get("flip_life_face_down"):
        if min(me.face_up_life_count, len(me.life)) < 1:
            return False
    # flip_life_face_up (= 「自分のライフの上か下から1枚を表向きにできる：」 cost、 ST36-005 キッド):
    # 裏向き (= 通常) のライフが 1 枚以上 必要 (= 表向き枚数 < ライフ総数)。
    if cost.get("flip_life_face_up"):
        fu = min(me.face_up_life_count, len(me.life))
        if len(me.life) - fu < 1:
            return False
    return True


def _pay_don_capacity(state: GameState, me: Player) -> int:
    """ドン-N で返却可能な「場のドン」総数 = cost area(active/rested)+ 各キャラ/リーダーの付与ドン。
    公式通り付与ドンも返却可(FAQ 準拠)= AI も含め全員。 既定支払いは area 優先なので通常時の挙動は
    従来通り、 area 不足時のみ付与ドンで払える(= エネル等が自分の ドン‼-X カードを正しく撃てる)。
    2026-07-08 ohtsuki 指摘(matrix 不変より正確性優先)。"""
    return (me.don_active + me.don_rested
            + sum(getattr(ip, "attached_dons", 0) for ip in [me.leader, *me.characters]))


_DO_LABEL_JP = {
    "draw": "カードを引く", "ko": "KOする", "ko_multi": "KOする", "power_pump": "パワー増減",
    "life_to_hand": "ライフを手札に", "life_top_or_bottom_to_hand": "ライフを手札に",
    "put_top_to_life": "デッキ上をライフに", "hand_to_self_life": "手札をライフに",
    "search": "デッキから手札に", "play_from_trash": "トラッシュから登場", "play_from_hand": "手札から登場",
    "rest": "レストにする", "rest_opp_don": "相手ドンをレスト", "add_don": "ドンを追加",
    "add_rested_don": "レストドンを追加", "attach_don": "ドンを付与", "untap_don": "ドンをアクティブに",
    "trash_opp_hand_random": "相手手札を捨てさせる", "trash_self_hand_random": "手札を捨てる",
    "return_to_hand": "手札に戻す", "return_to_deck_bottom": "デッキ下に戻す",
    "give_keyword": "キーワード付与", "give_rush": "速攻付与", "set_base_power": "パワーを変更",
    "reduce_play_cost": "コスト軽減", "set_base_cost": "コストを変更", "cost_minus": "コスト減",
    "draw_per_self_hand_discarded": "捨てた分引く", "mill_opp_life_to_trash": "相手ライフをトラッシュ",
}


def _describe_do_list(do_list: list) -> str:
    """choice の option(do-spec リスト)を人間向け短文ラベルに。 主要 primitive の日本語 + 数値。"""
    parts: list[str] = []
    for d in (do_list or [])[:3]:
        if not isinstance(d, dict):
            continue
        for key in d:
            jp = _DO_LABEL_JP.get(key)
            if jp:
                val = d[key]
                if isinstance(val, (int, float)) and key in ("draw", "add_don"):
                    parts.append(f"{jp}{int(val)}")
                else:
                    parts.append(jp)
            break
    return " → ".join(parts) if parts else "この効果"


def _chara_cost_cand(c) -> dict:
    """self_chara_cost_pick / target_pick 用のキャラ候補 dict(盤面と同じ状態表示付き)。"""
    return {
        "iid": c.instance_id, "card_id": c.card.card_id, "name": c.card.name,
        "power": c.power, "rested": c.rested, "attached_dons": c.attached_dons,
        "summoning_sickness": getattr(c, "summoning_sickness", False),
        "keywords": sorted({
            *(["速攻"] if getattr(c, "is_rush_now", False) else []),
            *(["ブロッカー"] if getattr(c, "is_blocker_now", False) else []),
            *(["ダブルアタック"] if getattr(c, "is_double_attack_now", False) else []),
            *(["バニッシュ"] if getattr(c, "is_banish_now", False) else []),
        }),
        "owner": "self", "is_leader": False,
    }


def _maybe_pick_self_chara_cost(state: GameState, me: Player, self_inplay: Optional[InPlay],
                                cands: list, count: int, action: str, remaining_do: list) -> bool:
    """コストで自キャラを KO/手札/デッキ下 にする時、 人間なら「どのキャラを犠牲にするか」を選ばせる。
    action = "ko" | "hand" | "deck_bottom"。 remaining_do = 残りコスト+効果(continuation)。
    人間 + 候補 > count で self_chara_cost_pick modal を立て True。 AI/候補<=count は False(呼び元 auto)。
    2026-07-08 監査(inline cost のキャラ自動選択)。"""
    if not (_should_human_pick(state) and count > 0 and len(cands) > count):
        return False
    state.pending_choice = {
        "kind": "self_chara_cost_pick", "action": action, "limit": count,
        "candidates": [_chara_cost_cand(c) for c in cands],
        "source_iid": self_inplay.instance_id if self_inplay is not None else None,
        "description": {"ko": "コスト: KOする自キャラを選択",
                        "hand": "コスト: 手札に戻す自キャラを選択",
                        "deck_bottom": "コスト: デッキ下に置く自キャラを選択"}.get(action, "コスト: 自キャラを選択"),
        "_continuation": {"do": list(remaining_do),
                          "owner_idx": state.players.index(me),
                          "source_iid": self_inplay.instance_id if self_inplay is not None else None},
    }
    state.push_log(f"  効果コスト: 自キャラ {count} 枚 ({action}) → 人間 選択 待ち(候補 {len(cands)})")
    return True


def _request_self_hand_discard(state: GameState, me: Player, self_inplay: Optional[InPlay], limit: int) -> bool:
    """人間操作中 + 候補 > limit なら self_hand_discard_pick(discard_only)modal を立て True。
    AI/候補<=limit は False(呼び元が従来の random discard)。 = 自手札 discard の人間選択(2026-07-08 監査)。"""
    if not (_should_human_pick(state) and limit > 0 and len(me.hand) > limit):
        return False
    state.pending_choice = {
        "kind": "self_hand_discard_pick",
        "discard_only": True,
        "candidates": [{"hand_idx": i, "card_id": c.card_id, "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0}
                       for i, c in enumerate(me.hand)],
        "limit": limit,
        "source_iid": self_inplay.instance_id if self_inplay else None,
    }
    state.push_log(f"  効果: 自手札 {limit} 枚 トラッシュ → 人間 選択 待ち(候補 {len(me.hand)})")
    return True


def _option_score(opt: dict, state: GameState, me: Player, opp: Player) -> float:
    """choice_effect の選択肢を、 **その局面で実際に効くか** で採点する (2026-07-24)。

    従来は列挙順の先頭を撃っていたため、 相手キャラが 0 体なのに「1 体を KO」を選ぶ等の
    空振りが起きていた。 まず「対象が存在するか」で足切りし、 次に効果量で並べる。
    ⚠ 手書きの重みなので上限は人間並み。 データ由来に置き換えるのは rollout の仕事。
    """
    try:
        do = opt.get("do") if isinstance(opt, dict) else None
        if not do:
            return -1.0
        prims: set = set()
        _walk_prim_names(do, prims)
        n_opp = len(getattr(opp, "characters", []) or [])
        n_me = len(getattr(me, "characters", []) or [])
        my_life = len(getattr(me, "life", []) or [])
        score = 0.0
        for pr in prims:
            if pr in ("ko", "ko_multi", "ko_all_others", "return_to_hand",
                      "return_to_hand_multi", "return_to_deck_bottom"):
                score += 3.0 if n_opp > 0 else -0.5     # 相手が居ない除去は空振り
            elif pr in ("rest", "rest_opp_don", "keep_opp_rested_don_next_refresh"):
                score += 1.5 if n_opp > 0 else -0.5
            elif pr in ("draw", "draw_per_self_hand_discarded"):
                score += 2.0
            elif pr in ("search", "search_top_n", "play_from_hand", "play_from_trash",
                        "summon_from_deck", "reveal_hand_play_split"):
                score += 1.8
            elif pr in ("add_don", "add_rested_don", "attach_don", "attach_rested_don",
                        "attach_active_don", "untap_don"):
                score += 1.5
            elif pr in ("power_pump", "give_keyword", "give_rush"):
                score += 1.0 if n_me > 0 else -0.5      # 自分の駒が居ないパンプは空振り
            elif pr in ("put_top_to_life", "hand_to_self_life", "life_to_hand"):
                score += 2.5 if my_life <= 2 else 0.8   # ライフが薄い時ほど回復が効く
            elif pr in ("trash_opp_hand_random",):
                score += 1.2
            else:
                score += 0.3
        return score
    except Exception:
        return 0.0


def _walk_prim_names(node, out: set) -> None:
    """do ツリーからプリミティブ名を集める。"""
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            _walk_prim_names(v, out)
    elif isinstance(node, list):
        for x in node:
            _walk_prim_names(x, out)

def _threat_key(ip) -> tuple:
    """相手キャラを「対処すべき順」に並べる key (降順ソート用に負値)。

    ⚠ 2026-07-24 revert: 一度 opp_threat の脅威度を第 1 キーにしたが、 ko_multi の nested
    filter (cost≤3 + cost≤2) で「広い方が cost2 を先取り → 狭い方が枯れて cost3 が生き残る」
    regression を起こした (test_op01_096_king)。 未計測の変更だったため power 降順 (従来挙動) に
    戻す。 identity-aware な対象選択を再導入する時は multi-target の coordination + test が要る。
    """
    return (-float(getattr(ip, "power", 0) or 0),)


def _sacrifice_key(ip) -> tuple:
    """自キャラを「捨ててよい順」に並べる key (昇順ソート用)。 従来挙動 = power 昇順 (上記 revert)。"""
    return (float(getattr(ip, "power", 0) or 0),)

def _worst_hand_idx(hand: list, known: Optional[list] = None) -> int:
    """最も捨てて惜しくない手札の index(counter 低 → cost 低 → power 低)。 高 counter の防御札を温存。
    AI が手札を捨てる場面で random を使うと 探索(beam)の value 評価が その手札選択の分だけ無意味に
    なる(= random 解決を前提に action を評価してしまう)。 AI の discard は常にこれで決める
    (2026-07-08 ohtsuki 指摘「ランダムなところがあると折角の value が意味なくなる」)。

    ⭐ 全て同点なら **相手にバレている札** から捨てる (2026-07-24 ohtsuki 指摘)。 どれを捨てても
    同じなら、 既に割れている札を消費した方が「相手が知らない手札」の不確実性を保てる。
    known = 自分の known_hand_card_ids (= 公開サーチ/バウンス等で相手に判明している card_id)。"""
    known_set = set(known or ())
    return min(
        range(len(hand)),
        key=lambda i: (
            int(getattr(hand[i], "counter", 0) or 0),
            int(hand[i].cost) if hand[i].cost is not None else 0,
            int(hand[i].power) if hand[i].power is not None else 0,
            0 if getattr(hand[i], "card_id", None) in known_set else 1,
        ),
    )


def _don_return_sources(me: Player) -> list:
    """ドン返却の選択元(area active/rested + 各キャラ/リーダーの付与ドン)。 UI modal 用。"""
    sources: list = []
    if me.don_active > 0:
        sources.append({"key": "active", "label": "アクティブのドン", "avail": me.don_active})
    if me.don_rested > 0:
        sources.append({"key": "rested", "label": "レストのドン", "avail": me.don_rested})
    for ip in [me.leader, *me.characters]:
        ad = getattr(ip, "attached_dons", 0)
        if ad > 0:
            sources.append({"key": str(ip.instance_id),
                            "label": f"{ip.card.name}の付与ドン", "avail": ad, "attached": True})
    return sources


def _pay_don_from_field(state: GameState, me: Player, n: int, alloc: Optional[dict] = None) -> int:
    """ドン-N のコスト支払い: 場のドン(cost area の active/rested + キャラ/リーダーの付与ドン)を n 枚
    ドンデッキに戻す。 「場のドン」に付与ドンを含むのは公式(FAQ 準拠、 ohtsuki 指摘 2026-07-08)。
    alloc={"active":a,"rested":r,"attached":{iid:cnt}} 指定時はその割当(= 人間の選択)。 未指定は
    area active→rested→付与ドン(power 低い順で温存)の既定。 戻した総数を返す。"""
    removed = 0
    if alloc is not None:
        a = min(int(alloc.get("active", 0)), me.don_active)
        me.don_active -= a; me.don_remaining_in_deck += a; removed += a
        r = min(int(alloc.get("rested", 0)), me.don_rested)
        me.don_rested -= r; me.don_remaining_in_deck += r; removed += r
        for iid_s, cnt in (alloc.get("attached") or {}).items():
            iid = int(iid_s)
            for ip in [me.leader, *me.characters]:
                if ip.instance_id == iid:
                    k2 = min(int(cnt), ip.attached_dons)
                    ip.attached_dons -= k2; me.don_remaining_in_deck += k2; removed += k2
                    break
        return removed
    # 既定(alloc 未指定 = AI): area active → rested → 付与ドン。 area で足りる通常ケースは従来通り
    # (= AI 挙動不変)、 area 不足時のみ付与ドンで払える(公式通り、 = AI も自分の ドン‼-X カードを撃てる)。
    taken = min(n, me.don_active); me.don_active -= taken; me.don_remaining_in_deck += taken; removed += taken
    if removed < n:
        more = min(n - removed, me.don_rested); me.don_rested -= more; me.don_remaining_in_deck += more; removed += more
    if removed < n:  # area 不足 → 付与ドンから(power 低い順で温存)
        for ip in sorted([*me.characters, me.leader], key=lambda x: x.power):
            if removed >= n:
                break
            take = min(n - removed, ip.attached_dons)
            ip.attached_dons -= take; me.don_remaining_in_deck += take; removed += take
    return removed


def _pay_counter_cost(
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay],
    cost: dict,
) -> None:
    """counter event の cost を 実支払い (= 簡易: discard 系 は random)。

    将来 「counter_optional」 modal で 人間 が discard 対象 を 選べる ように 拡張 予定。
    現状: AI/人間 共 random discard で 動作。
    """
    if not isinstance(cost, dict):
        return
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0:
        actual = min(discard_n, len(me.hand))
        for _ in range(actual):
            # AI/fallback: random でなく「最も価値の低い札」を捨てる(counter 低→cost 低→power 低)。
            # 高 counter の防御札を温存。 2026-07-08 監査(AI の discard は常に最悪札)。
            me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
        state.push_log(f"  counter コスト: 手札 {actual} 枚 捨て")
        if actual > 0 and state.effects_overlay:
            trigger_on_self_hand_discarded(
                state, me, opp, self_inplay, actual, state.effects_overlay
            )
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0:
        # area active→rested→付与ドン(既定)。 人間が alloc を選んでいればそれを尊重(= AI も人間も
        # 同じ選択肢: 付与ドンも返却可、 2026-07-08)。
        removed = _pay_don_from_field(state, me, pay_don, getattr(state, "_don_return_alloc", None))
        state._don_return_alloc = None
        state.push_log(f"  counter コスト: ドン-{removed}")
        if removed > 0 and state.effects_overlay:
            trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay, count=removed)
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0:
        actual = min(rest_don, me.don_active)
        me.don_active -= actual
        me.don_rested += actual
        state.push_log(f"  counter コスト: アクティブドン {actual} レスト")
    # discard_hand_with_filter (= 特定カードを捨てる、 例: OP10-072 イベント1枚)。
    # 旧実装は未処理で コスト払わず 効果だけ発動していた (2026-06-04 修正)。
    dwf = cost.get("discard_hand_with_filter")
    if isinstance(dwf, dict):
        f = dwf.get("filter", {}) if isinstance(dwf.get("filter"), dict) else {}
        cnt = int(dwf.get("count", 1))
        matching_idxs = [i for i, c in enumerate(me.hand) if _matches_filter(c, f)]
        chosen = sorted(matching_idxs[:cnt], reverse=True)
        for i in chosen:
            me.trash.append(me.hand.pop(i))
        if chosen:
            state.push_log(f"  cost: 手札から該当 {len(chosen)} 枚 捨て")
            if state.effects_overlay:
                trigger_on_self_hand_discarded(
                    state, me, opp, self_inplay, len(chosen), state.effects_overlay)
    # --- source 系/特殊コスト (= 旧実装で未処理 → 効果だけ無償発動だった、 2026-06-04 修正) ---
    # rest_self: source をレスト (= このキャラ/ステージ自身)。
    if cost.get("rest_self") and self_inplay is not None:
        self_inplay.rested = True
        state.push_log(f"  cost: {self_inplay.card.name} をレスト")
    # return_self_don_to_deck N: 場のドン N 枚を ドンデッキへ。 ⭐ rested (= 既に使用済) を
    # 優先して返す (ohtsuki 2026-07-17「アクティブでなくレストのドンを戻したい」)。 総ドンは
    # どちらを返しても -1 だが、 rested を返せば今ターン使える active DON を温存できる = 常に
    # tempo が同等以上 (= active を先に返すのは純粋に損。 人間が最適に選ぶ手を自動で採る)。
    rdon = int(cost.get("return_self_don_to_deck", 0) or 0)
    if rdon > 0:
        from_rested = min(me.don_rested, rdon)
        me.don_rested -= from_rested
        me.don_remaining_in_deck += from_rested
        from_active = min(rdon - from_rested, me.don_active)
        me.don_active -= from_active
        me.don_remaining_in_deck += from_active
        moved = from_rested + from_active
        if moved:
            state.push_log(f"  cost: 自ドン {moved} 枚をドンデッキに戻す")
            if state.effects_overlay:
                trigger_on_self_don_returned_to_deck(
                    state, me, opp, state.effects_overlay, count=moved)
    # life → hand 系: ライフ上から N 枚を手札へ (top を取る)。
    lth_total = int(cost.get("life_to_hand", 0) or 0) + int(cost.get("life_top_or_bottom_to_hand", 0) or 0)
    if lth_total > 0:
        actual = min(lth_total, len(me.life))
        for _ in range(actual):
            me.hand.append(me.life.pop(0))
        if actual:
            state.push_log(f"  cost: ライフ上から {actual} 枚を手札に")
    # trash_to_deck N: トラッシュ上から N 枚をデッキ下へ。
    ttd = int(cost.get("trash_to_deck", 0) or 0)
    if ttd > 0:
        actual = min(ttd, len(me.trash))
        for _ in range(actual):
            me.deck.append(me.trash.pop(0))
        if actual:
            state.push_log(f"  cost: トラッシュ {actual} 枚をデッキ下に")
    # reveal_hand_with_filter: 情報コスト (= 見せるだけ、 札は移動しない)。
    rhf = cost.get("reveal_hand_with_filter")
    if isinstance(rhf, dict):
        cnt = int(rhf.get("count", 1))
        state.push_log(f"  cost: 手札から該当 {cnt} 枚を公開")
    # flip_life_face_down: ライフ1枚を裏向きに (= face_up_life_count を 1 減らす)、 ST36-005 キッド。
    # engine のライフモデルは「上か下」 の物理位置を区別せず face_up_life_count で表向き枚数のみ管理。
    if cost.get("flip_life_face_down"):
        me.face_up_life_count = max(0, min(me.face_up_life_count, len(me.life)) - 1)
        state.push_log("  cost: ライフ1枚を裏向き")
    # flip_life_face_up: ライフ1枚を表向きに (= face_up_life_count を 1 増やす)、 ST36-005 キッド。
    if cost.get("flip_life_face_up"):
        me.face_up_life_count = min(me.face_up_life_count + 1, len(me.life))
        state.push_log("  cost: ライフ1枚を表向き")
    # trash_self / self_ko: source 自身を 場から除去 → トラッシュ。
    if (cost.get("trash_self") or cost.get("self_ko")) and self_inplay is not None:
        is_ko = bool(cost.get("self_ko"))
        src = self_inplay
        removed = False
        if src in me.characters:
            me.characters.remove(src); removed = True
        elif src in me.stages:
            me.stages.remove(src); removed = True
        if removed:
            me.trash.append(src.card)
            if src.attached_dons > 0:  # 6-5-5-4: 付与ドンはレストで戻る
                me.don_rested += src.attached_dons
                src.attached_dons = 0
            state.push_log(
                f"  cost: {src.card.name} を{'KO' if is_ko else 'トラッシュに置く'}")
            if state.effects_overlay:
                if is_ko:
                    trigger_on_ko(state, me, opp, src.card, state.effects_overlay,
                                  by_opp_effect=False, victim_attached_don=src.attached_dons, victim_effect_negated=_ip_effect_negated(src))
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay,
                                             victim_card=src.card)
                else:
                    trigger_on_self_chara_leave_by_self_effect(
                        state, me, opp, state.effects_overlay)


def _check_and_set_once_per_turn(
    state: GameState,
    me: Player,
    eff: EffectSpec,
    card_id: str,
    idx: int,
    source_iid: Optional[int] = None,
) -> bool:
    """effect spec の `once_per_turn` をチェックし、 未使用なら使用済みフラグを立てる。

    戻り値:
    - True: once_per_turn 指定なし、 もしくは未使用 → 発動許可
    - False: 既に使用済み → 発動拒否 (= 呼び出し元は continue でスキップ)

    once_per_turn の値:
    - True: 自動キー。 source_iid あれば instance 単位 (= 同 card_id 複数 instance を
      別 個体 として 扱う、 公式 7-5-3 通り)、 なければ card_id 単位 fallback。
    - "<str>": 明示キー (= 複数 effect で同一キーを共有可、 instance 跨ぎ も 共有)

    cost 経由の once_per_turn (= activate_main / on_attack の `cost.once_per_turn`) は
    InPlay 側のフラグで別管理されているのでここでは触れない。

    一方、 field-when (= on_self_chara_leave_by_self_effect 等、 resolve_triggers 経由) で
    `cost: {once_per_turn: true}` 形式 で 指定 された 場合 は、 cost 払い path が なく
    InPlay フラグ も 立たない ので、 ここ で 同じ key で gate する。

    2026-05-27 fix: 同 card_id 複数 instance あるとき 1 体 発動 で 全 instance blocked
    に なる bug を 修正 (= ohtsuki さん 観戦時 報告)。 source_iid 渡せれば instance 単位
    で 区別。
    """
    opt = eff.get("once_per_turn")
    if not opt:
        cost = eff.get("cost")
        if isinstance(cost, dict):
            opt = cost.get("once_per_turn")
    if not opt:
        return True
    if opt is True:
        if source_iid is not None:
            key = f"iid:{source_iid}:{eff.get('when', '')}:{idx}"
        else:
            key = f"{card_id}:{eff.get('when', '')}:{idx}"
    else:
        # 文字列 opt = 名前付き共有キー (= プレイヤー横断の共有 namespace、 複数 when [KO / 離脱] を
        # 跨いで「ターン1回」を束ねる用途。 OP13-002 / OP16-041 バギー。 単一 instance では正確、
        # 同名 2 枚は共有される既存仕様 = test_once_per_turn_explicit_key_shared_across_instances)。
        key = f"key:{opt}"
    if key in me.once_per_turn_used:
        return False
    me.once_per_turn_used.add(key)
    # 明示キー (共有 namespace) は instance_id 非依存 → canonical mirror に並行記録 (Rust 同期)。
    # source_iid が無い場合 (= ライフトリガー / イベント等、 場に InPlay が無い source) の
    # 自動キーも card_id ベースで instance 非依存なので同じく mirror する (2026-08-02、
    # これが無いと Rust が「ターン1回」を追跡できず該当トリガーが丸ごと bail する)。
    if (opt is not True or source_iid is None) and key not in me.once_shared_used:
        me.once_shared_used.append(key)
        me.once_shared_used.sort()
    # Rust 同期用 canonical mirror: field-when (fire_field_when で発火する持続 source 由来) の once を
    # InPlay.event_once_used に "{when}:{idx}" で並行記録 (iid 非依存 = digest 可)。 Python の判定は上の
    # once_per_turn_used のまま (additive)。 on_play/on_ko/main/counter/on_attack/end_of_turn は対象外
    # (= それぞれ別経路で Rust 処理、 mirror すると二重管理で不一致になる)。
    when_s = eff.get("when", "")
    if opt is True and source_iid is not None and when_s in _FIELD_WHEN_ONCE_MIRROR:
        for ip in [me.leader, *me.characters, *me.stages]:
            if ip.instance_id == source_iid:
                ip.mark_event_once(when_s, idx)
                break
    return True


# fire_field_when (Rust) で once を追跡する field-when when-type。 _check_and_set_once_per_turn の
# canonical mirror (event_once_used) 対象。 ここに無い when は mirror されない (Rust も別経路)。
_FIELD_WHEN_ONCE_MIRROR = frozenset({
    "on_self_life_to_hand", "on_self_life_to_trash", "on_self_life_taken", "on_opp_life_taken",
    "on_self_chara_played", "on_opp_chara_played", "on_self_chara_ko", "on_opp_chara_ko",
    "on_self_hand_discarded", "on_self_don_returned_to_deck", "on_self_event_played",
    # ⚠ 実際の when キーは "opp_event_or_trigger_fired" (on_ 無し、 _enqueue_field_when の実引数)。
    # 旧 "on_opp_event_or_trigger_fired" は綴り違いで一度も一致せず mirror されていなかった
    # (= Rust が「ターン1回」を追跡できず該当効果が丸ごと bail、 2026-08-02 修正)。 両方載せる。
    "opp_event_or_trigger_fired", "on_opp_event_or_trigger_fired",
    # 「相手がイベントを発動した時」 (= イベント発動のみ、 ライフ【トリガー】発動では発火しない、
    #  cardqa_op_11 = OP11-012 フランキー / OP06-044 ギオン 等)。 opp_event_or_trigger_fired とは
    #  別 when で、 event-play 経路のみ enqueue する (trigger_opp_event_played)。
    "opp_event_played",
    "on_self_chara_leave_by_self_effect", "on_self_rested",
    "on_self_trigger_fired",
    # ライフ 0 トリガー (OP05-098 紫エネル)。 source はリーダー (= 永続 InPlay) なので mirror 可能。
    # これが無いと Rust 側で「ターン1回」を追跡できず、 該当効果が丸ごと bail する (2026-07-31)。
    "on_life_zero",
    # 【登場時】/【ブロック時】 (2026-08-02)。 source が場の InPlay なので mirror できる。
    # ⚠ Python の発動判定は従来通り once_per_turn_used (= 挙動不変)。 ここへの追加は
    # InPlay.event_once_used への **記録** を増やすだけ = canonical digest に載せて Rust が
    # 「ターン1回」を追跡できるようにするためのもの。
    "on_play",
    "on_block",
})


def _maybe_resolve(state: GameState) -> None:
    """resolve_triggers をネスト呼び出ししない安全ラッパ。 trigger_* の末尾で呼ぶ。"""
    if state.resolving:
        return
    resolve_triggers(state)


# --------------------------------------------------------------------------- #
# 条件評価
# --------------------------------------------------------------------------- #
def _ip_effect_negated(ip) -> bool:
    """InPlay が 「効果無効」 状態か (negate_effect / disable_effect / 静的無効)。

    KO 直前に呼んで trigger_on_ko(victim_effect_negated=...) に渡す。
    公式 Q&A (cardqa_op_09 / op_10): 「効果を無効にされたキャラがKOされた場合、 そのキャラの
    持つ【KO時】効果は発動できますか？」 → 「いいえ、 できません」。
    on_ko は source が既に場外 (self_inplay=None) なので _execute_event の gate を通らない。
    """
    if ip is None:
        return False
    return (
        "効果無効" in getattr(ip, "granted_keywords", set())
        or "効果無効" in getattr(ip, "static_granted_keywords", set())
        or bool(getattr(ip, "effect_disabled_through_opp_turn", False))
    )



def eval_all_conditions(
    eff: dict[str, Any],
    state: GameState,
    me: Player,
    self_inplay: Optional[InPlay] = None,
) -> bool:
    """effect dict から `if` (単一辞書) と `conditions` (辞書のリスト) を両方評価。
    AND 結合。 両方未指定なら True。

    R44 で conditions リスト形式が普及したため、 すべての call site で
    この関数を経由させて互換性を担保する。
    """
    if_cond = eff.get("if") or {}
    conditions = eff.get("conditions") or []
    if if_cond and not eval_condition(if_cond, state, me, self_inplay):
        return False
    if isinstance(conditions, list):
        for c in conditions:
            if isinstance(c, dict) and not eval_condition(c, state, me, self_inplay):
                return False
    return True


def eval_condition(
    cond: dict[str, Any],
    state: GameState,
    me: Player,
    self_inplay: Optional[InPlay] = None,
) -> bool:
    """条件式を評価。すべての key について True なら全体 True (AND)。

    対応条件:
    - leader_feature: str/list — 自リーダーが特徴を持つか
    - leader_features_any: list — 自リーダーがいずれかの特徴を持つか (alias of leader_feature with list)
    - leader_color: str — 自リーダーが指定色を持つか (例: "多色" は色2つ以上)
    - always: bool — 常に True (テスト用)
    - self_life_le: int — 自ライフ N 以下
    - self_life_ge: int — 自ライフ N 以上
    - opp_life_le: int — 相手ライフ N 以下
    - self_field_count_ge: int — 自場のキャラ数 N 以上
    - self_field_count_le: int — 自場のキャラ数 N 以下
    - self_trash_count_ge: int — 自トラッシュ N 枚以上
    - self_don_ge: int — 自場のドン!!合計 N 以上
    - self_don_active_ge: int — 自アクティブドン N 以上
    - self_chara_feature_count_ge: {feature, count} — 特徴 X のキャラ N 以上
    """
    if not cond:
        return True

    # 相手プレイヤー解決 (state.players を逆引き)
    opp = next((p for p in state.players if p is not me), None)

    for k, v in cond.items():
        if k == "leader_feature" or k == "leader_features_any":
            features = me.leader.card.features
            if isinstance(v, str):
                if v not in features:
                    return False
            elif isinstance(v, list):
                if not any(f in features for f in v):
                    return False
        elif k == "leader_color":
            colors = list(me.leader.card.color)
            if v == "多色":
                if len(colors) < 2:
                    return False
            elif isinstance(v, str):
                if v not in colors:
                    return False
        elif k == "always":
            if not v:
                return False
        elif k == "self_life_le":
            if len(me.life) > int(v):
                return False
        elif k == "self_life_ge":
            if len(me.life) < int(v):
                return False
        elif k == "has_face_up_life":
            # 「自分の表向きのライフがある場合」 (PRB02-018/EB03-051 等)。
            present = min(me.face_up_life_count, len(me.life)) > 0
            if bool(v) != present:
                return False
        elif k == "opp_just_battled_present":
            # 直前にバトルした相手キャラがまだ場にいるか (ST08-013 そうしたら自身KO の gate)。
            iid = getattr(state, "last_battled_opp_iid", None)
            present = opp is not None and iid is not None and any(
                ip.instance_id == iid for ip in opp.characters)
            if bool(v) != present:
                return False
        elif k == "opp_just_battled_cost_le":
            # 直前にバトルした相手キャラのコストが v 以下か (OP04-047 氷鬼)。
            iid = getattr(state, "last_battled_opp_iid", None)
            ip = None
            if opp is not None and iid is not None:
                ip = next((c for c in opp.characters if c.instance_id == iid), None)
            if ip is None or int(getattr(ip.card, "cost", 0) or 0) > int(v):
                return False
        elif k == "either_side_chara_named_absent":
            # 「キャラの「<name>」がいる場合 この効果は無効」 = 両陣営に該当 name のキャラが
            # 存在しないか (OP05-100 エネル: ルフィ present で replace 無効)。
            name = v.get("name", "") if isinstance(v, dict) else str(v)
            present = any(c.card.name == name for c in me.characters)
            if opp is not None:
                present = present or any(c.card.name == name for c in opp.characters)
            if present:  # いる → 条件不成立 (= 効果無効)
                return False
        elif k == "opp_life_lost_this_turn":
            # 「相手のライフが離れているターン中」 (P-120)。 opp が今ターン ライフを失ったか。
            lost = opp is not None and getattr(opp, "life_lost_this_turn", False)
            if bool(v) != lost:
                return False
        elif k == "self_chara_count_lt_opp":
            # 「自分のキャラが相手のキャラより少ない場合」 (EB04-059 等)。
            if opp is None or len(me.characters) >= len(opp.characters):
                return False
        elif k == "self_life_eq":
            if len(me.life) != int(v):
                return False
        elif k == "self_power_ge":
            # self_inplay のパワーが N 以上 (= 自身に対する条件)
            if self_inplay is None or self_inplay.power < int(v):
                return False
        elif k == "opp_life_le" and opp is not None:
            if len(opp.life) > int(v):
                return False
        elif k == "opp_life_ge" and opp is not None:
            if len(opp.life) < int(v):
                return False
        elif k == "self_field_count_ge":
            if len(me.characters) < int(v):
                return False
        elif k == "opp_field_count_ge":
            # 相手の場のキャラ (= リーダー含めず) が N 枚以上 (OP07-073 ルフィ等)。
            if len(opp.characters) < int(v):
                return False
        elif k == "self_field_count_le":
            if len(me.characters) > int(v):
                return False
        elif k == "self_trash_count_ge":
            if len(me.trash) < int(v):
                return False
        elif k == "self_event_cost_used_ge":
            # このターン中に自分がコスト N 以上のイベントを使用していたか (= OP15-002 ルーシー)。
            if getattr(me, "max_event_cost_this_turn", 0) < int(v):
                return False
        elif k == "self_hand_discarded_by_effect_this_turn":
            # このターン中に効果で自分の手札が捨てられたか (= ST33-004 ボルサリーノ コスト-3 条件)。
            flag = bool(getattr(me, "hand_discarded_by_effect_this_turn", False))
            if bool(v) != flag:
                return False
        elif k == "exists_chara_cost_ge":
            # どちらかの場にコスト N 以上のキャラがいるか (= OP10-058 「コスト8以上のキャラがいる場合」)。
            # キャラのみ (= leader 除く)。 現在コスト (base_cost) で判定。
            n = int(v)
            allc = list(me.characters) + (list(opp.characters) if opp else [])
            if not any(getattr(c, "base_cost", 0) >= n for c in allc):
                return False
        elif k == "self_inplay_summoning_sickness":
            # この効果source のキャラが召喚酔い中か (= 「このキャラが登場したターン」 proxy、
            # EB03-013 キャロット)。 非ラッシュなら登場ターン = sickness True。
            if self_inplay is None or not getattr(self_inplay, "summoning_sickness", False):
                return False
        elif k == "self_chara_named_absent":
            # 自分の場に カード名 v のキャラが いない 場合 True (= OP08-005「自分のクロマーリモが
            # いない場合」 / OP03-027「自分のブチがいない場合」)。
            if any(c.card.name == v for c in me.characters):
                return False
        elif k == "self_field_named_all_with_power":
            # 自分の場 (リーダー+キャラ) に、 指定の全カード名が それぞれ存在する場合 True。
            # power_eq (= truly_original_power_eq) 指定時は「元々のパワー (= card.power, 印刷値)」
            # がその値のキャラに限定。 公式テキストが 「元々のパワー」 の場合は
            # `truly_original_power_eq` key を使う (= 表記と spec key の整合、 overlay 命名規約)。
            # 例: ST30-016「自分の元々のパワー6000のキャラの、『エース』と『ルフィ』がいる場合」。
            spec = v if isinstance(v, dict) else {"names": v}
            names = [normalize_card_name(n) for n in spec.get("names", [])]
            power_eq = spec.get("power_eq")
            if power_eq is None:
                power_eq = spec.get("truly_original_power_eq")
            pool = [me.leader, *me.characters]
            ok = True
            for nm in names:
                if power_eq is not None:
                    found = any(c.card.name == nm and c.card.power == int(power_eq) for c in pool)
                else:
                    found = any(c.card.name == nm for c in pool)
                if not found:
                    ok = False
                    break
            if not ok:
                return False
        elif k == "self_chara_cost_sum_ge":
            # 自分のキャラ (leader 除く) の現在コスト合計が N 以上か (= OP10-022 ロー)。
            total = sum(getattr(c, "base_cost", 0) for c in me.characters)
            if total < int(v):
                return False
        elif k == "exists_opp_chara_cost_le":
            # 相手の場にコスト N 以下のキャラがいるか (= EB01-045「相手のコスト0のキャラがいる場合」)。
            n = int(v)
            if opp is None or not any(getattr(c, "base_cost", 99) <= n for c in opp.characters):
                return False
        elif k == "exists_opp_chara_power_ge":
            # 相手の場に (現在) パワー N 以上のキャラがいるか (= ST10-004「相手のパワー5000以上の
            # キャラがいる場合」)。 「元々の」 でなければ現在パワー (InPlay.power) で判定。
            n = int(v)
            if opp is None or not any(c.power >= n for c in opp.characters):
                return False
        elif k == "exists_chara_cost_le":
            # どちらかの場にコスト N 以下のキャラがいるか (= OP02-093/101/102/113「コスト0のキャラがいる場合」)。
            n = int(v)
            allc = list(me.characters) + (list(opp.characters) if opp else [])
            if not any(getattr(c, "base_cost", 99) <= n for c in allc):
                return False
        elif k == "opp_rested_chara_count_ge":
            # 相手のレストのキャラが N 枚以上いるか (= OP01-032 アシュラ童子)。
            if opp is None or sum(1 for c in opp.characters if c.rested) < int(v):
                return False
        elif k == "self_field_don_zero_or_ge_3":
            # 自分の場のドン!! が 0 枚 か 3 枚以上 (= OP05-060 ルフィ)。 場のドン = active + rested。
            fd = me.don_active + me.don_rested
            if not (fd == 0 or fd >= 3):
                return False
        elif k == "self_field_don_zero_or_ge_8":
            # 自分の場のドン!! が 0 枚 か 8 枚以上 (= ST10-002 ルフィ)。 場のドン = active + rested。
            fd = me.don_active + me.don_rested
            if not (fd == 0 or fd >= 8):
                return False
        elif k == "leader_power_ge":
            # 自リーダーの現在パワーが N 以上か (= OP09-017 ワイヤー「リーダーがパワー7000以上」)。
            if me.leader is None or me.leader.power < int(v):
                return False
        elif k == "or":
            # OR 結合: v = [cond1, cond2, ...] のいずれかが True なら True
            # (= 「特徴Xか属性Y」「リーダーがXか「Y」」 等の 選言 gate)。 eval_all_conditions の
            # AND 枠内で 1 つの選言 block として機能する。
            subs = v if isinstance(v, list) else [v]
            if not any(eval_condition(s, state, me, self_inplay) for s in subs):
                return False
        elif k == "not":
            # 否定: v = <condition dict> が False の場合に True (= 「~でない場合」、 OP12-096 等)。
            if eval_condition(v if isinstance(v, dict) else {}, state, me, self_inplay):
                return False
        elif k == "leader_attribute":
            # 自リーダーが属性 v を持つか (= OP13-025「属性(打)」)。
            if me.leader is None or str(v) not in (me.leader.card.attribute or ""):
                return False
        elif k == "self_life_le_opp":
            # 自ライフ枚数 ≤ 相手ライフ枚数 (= OP10-114 ドレーク「自ライフが相手以下」)。
            if opp is None or len(me.life) > len(opp.life):
                return False
        elif k == "opp_attached_don_ge":
            # 相手の場の付与ドン合計が N 以上か (= OP15-005 カバジ「相手の付与されているドンがある」)。
            if opp is None:
                return False
            total = sum(getattr(c, "attached_dons", 0)
                        for c in [opp.leader, *opp.characters] if c is not None)
            if total < int(v):
                return False
        elif k == "total_life_ge":
            # お互いのライフ合計が N 枚以上 (= OP11-114「両ライフ合計5以上」)。
            if opp is None or (len(me.life) + len(opp.life)) < int(v):
                return False
        elif k == "self_hand_diff_le":
            # 自手札枚数 - 相手手札枚数 が N 以下か (= OP09-092「自手札が相手より3枚以上少ない」= -3)。
            if opp is None or (len(me.hand) - len(opp.hand)) > int(v):
                return False
        elif k == "self_don_ge":
            total = me.don_active + me.don_rested + me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
            if total < int(v):
                return False
        elif k == "self_don_active_ge":
            if me.don_active < int(v):
                return False
        elif k == "self_don_active_le":
            if me.don_active > int(v):
                return False
        elif k == "self_chara_count_le":
            if len(me.characters) > int(v):
                return False
        elif k == "self_chara_count_ge":
            if len(me.characters) < int(v):
                return False
        # --- 2026-05-31 横展開: silently-ignored だった未handled condition を実装 ---
        elif k == "self_hand_eq":
            if len(me.hand) != int(v):
                return False
        elif k == "self_not_rested":
            if self_inplay is None or self_inplay.rested:
                return False
        elif k == "self_rested_chara_count_ge":
            if sum(1 for c in me.characters if c.rested) < int(v):
                return False
        elif k == "self_don_rested_ge":
            if me.don_rested < int(v):
                return False
        elif k == "self_leader_power_le":
            if me.leader is None or me.leader.power > int(v):
                return False
        elif k == "self_leader_attached_don_ge":
            if me.leader is None or me.leader.attached_dons < int(v):
                return False
        elif k == "self_life_plus_hand_le":
            if (len(me.life) + len(me.hand)) > int(v):
                return False
        elif k == "total_life_le":
            opp_life = len(opp.life) if opp is not None else 0
            if (len(me.life) + opp_life) > int(v):
                return False
        elif k == "self_all_chara_feature":
            # 自分のキャラすべてが特徴《v》を「持つ」 (= 特徴名の完全一致)。
            # 公式「特徴《X》を持つキャラのみ」 (= OP15-001 東の海 / OP13-097 天竜人 等)。
            # ⚠ **キャラ 0 枚は不成立** (vacuously True にしない)。 公式裁定
            # (cardqa_op_13, OP13-097「自分の場にキャラが0枚の場合…KOできますか？→いいえ」):
            # 「特徴Xを持つキャラのみの場合」 は キャラが 1 枚以上 存在することを要求する。
            if not me.characters:
                return False
            if not all(str(v) in (c.card.features or ()) for c in me.characters):
                return False
        elif k == "self_all_chara_feature_contains":
            # 自分のキャラすべてが「v を含む特徴」を持つ (= 特徴名の部分一致)。
            # 公式「『X』を含む特徴を持つキャラのみ」 (= OP11-046 ジェルマ: 特徴 'ジェルマ66' が 'ジェルマ' を含む)。
            # ⚠ self_all_chara_feature と同じく **キャラ 0 枚は不成立** (上記裁定)。
            if not me.characters:
                return False
            if not all(
                any(str(v) in f for f in (c.card.features or ()))
                for c in me.characters
            ):
                return False
        elif k == "either_player_don_total_eq_10":
            if not any((p.don_active + p.don_rested) == 10 for p in state.players):
                return False
        elif k == "opp_attacker_attribute":
            # opp_attack 系で「アタックしてきた相手キャラの属性が v か」 (= OP11-088 シュウ)。
            atk_iid = getattr(state, "current_attacker_iid", None)
            atk = None
            if atk_iid is not None and opp is not None:
                atk = next((ip for ip in [opp.leader, *opp.characters]
                            if ip.instance_id == atk_iid), None)
            if atk is None or str(v) not in (atk.card.attribute or ""):
                return False
        elif k == "returned_don_count_ge":
            # on_self_don_returned_to_deck で「一度に N 枚以上 戻された」 (= EB02-035 / P-077)。
            # don 返却 primitive が state.last_returned_don_count に保存。
            if int(getattr(state, "last_returned_don_count", 0) or 0) < int(v):
                return False
        elif k == "self_deck_count_le":
            if len(me.deck) > int(v):
                return False
        elif k == "self_don_active_eq":
            if me.don_active != int(v):
                return False
        elif k == "self_don_count_eq":
            # 「自分の場のドン (= don area: active+rested) が N 枚」 (OP05-060 の「0枚」 等)
            if (me.don_active + me.don_rested) != int(v):
                return False
        elif k == "self_don_count_ge":
            if (me.don_active + me.don_rested) < int(v):
                return False
        elif k == "self_leader_active":
            is_active = me.leader is not None and not me.leader.rested
            if is_active != bool(v):
                return False
        elif k == "opp_inplay_truly_original_power_ge_6000_count_ge":
            # 相手の元々パワー6000以上の リーダーかキャラ が N 体以上 (= OP06-012 ベアキング)
            if opp is None:
                return False
            n = sum(1 for ip in [opp.leader, *opp.characters]
                    if ip is not None and ip.truly_original_power >= 6000)
            if n < int(v):
                return False
        elif k == "opp_inplay_truly_original_power_ge_count":
            # 相手の元々パワー X 以上の キャラ (任意で リーダー含む) が N 体以上 (= OP09-005 レイリー)
            # spec: {"power_ge": 5000, "count": 2, "include_leader": false}
            if opp is None:
                return False
            spec = v if isinstance(v, dict) else {}
            thr = int(spec.get("power_ge", 0))
            need = int(spec.get("count", 1))
            pool = list(opp.characters)
            if spec.get("include_leader") and opp.leader is not None:
                pool.append(opp.leader)
            n = sum(1 for ip in pool if ip is not None and ip.truly_original_power >= thr)
            if n < need:
                return False
        elif k == "exists_chara_cost_0_or_ge_8":
            # 「コスト0か8以上のキャラがいる場合」 (= クロコダイル OP14-090/094/120)。
            # 現在コスト (base_cost = cost_minus 反映) で 両者の場のキャラ を判定。 v=True 要求。
            all_chara = list(me.characters) + (list(opp.characters) if opp else [])
            found = any(c.base_cost == 0 or c.base_cost >= 8 for c in all_chara)
            if bool(v) != found:
                return False
        elif k == "self_chara_feature_count_ge":
            spec = v if isinstance(v, dict) else {}
            feature = spec.get("feature", "")
            need = int(spec.get("count", 1))
            count = sum(1 for c in me.characters if feature in c.card.features)
            if count < need:
                return False
        elif k == "victim_truly_original_power_ge":
            # 直近の KO victim カードの 「元々のパワー」 (= card.power) が N 以上
            # OP14-041 ハンコック 「自分の元々のパワー5000以上 + 特徴X を持つキャラが KO された時」
            vic = getattr(state, "last_chara_ko_victim_card", None)
            if vic is None or int(getattr(vic, "power", 0) or 0) < int(v):
                return False
        elif k == "victim_feature_in":
            # 直近の KO victim カードの特徴に v (リスト) のいずれかを含むか
            vic = getattr(state, "last_chara_ko_victim_card", None)
            if vic is None:
                return False
            feats = v if isinstance(v, list) else [v]
            if not any(f in vic.features for f in feats):
                return False
        elif k == "by_opp_effect":
            # on_ko / on_self_chara_ko 等で直近 KO が「相手の効果由来」だったか。
            # trigger_on_ko の by_opp_effect=True 引数が state.last_ko_by_opp_effect に伝搬する。
            # 公式 「相手の効果でKOされた時」 系 (OP11-035 / OP11-024 等)。
            actual = bool(getattr(state, "last_ko_by_opp_effect", False))
            if bool(v) != actual:
                return False
        elif k == "by_battle":
            # on_ko 等で直近 KO がバトル由来 (= 効果由来でない) だったか。
            # 公式 「バトルでKOされた時」 系 (= 効果KO 除外)。
            actual_by_opp_eff = bool(getattr(state, "last_ko_by_opp_effect", False))
            # by_battle: True = バトル由来 (= 効果由来ではない)
            actual_by_battle = not actual_by_opp_eff
            if bool(v) != actual_by_battle:
                return False
        elif k == "played_chara_truly_original_cost_ge":
            # 直近の opp_chara_played カードの 「元々のコスト」 が N 以上 (OP12-081 コアラ)
            pc = getattr(state, "last_opp_chara_played_card", None)
            if pc is None or int(getattr(pc, "cost", 0) or 0) < int(v):
                return False
        elif k == "played_self_chara_has_no_effect":
            # 直近の self_chara_played カードに overlay 効果が無いか (OP02-026 サンジ用)。
            # 公式: 「元々の効果のないキャラ」 = カードテキストが効果文を持たないバニラ。
            # 簡略: overlay にエントリが無い or 空配列 (= []) なら 効果なし扱い。
            pc = getattr(state, "last_self_chara_played_card", None)
            if pc is None:
                return False
            ov = state.effects_overlay.get(pc.card_id) if state.effects_overlay else None
            if ov is None:
                # 効果オーバーレイ未登録 = vanilla
                effects_count = 0
            else:
                # CardEffectBundle なら .effects、 list なら自身
                eff_list = getattr(ov, "effects", ov)
                effects_count = len(eff_list) if hasattr(eff_list, "__len__") else 0
            if bool(v) != (effects_count == 0):
                return False
        elif k == "played_self_chara_has_trigger":
            # 直近の self_chara_played カードが 【トリガー】 を持つか (= OP13-100 ボニー用)。
            # 公式: 「自分の【トリガー】を持つキャラが登場した時」。 CardDef.trigger (str) が
            # 非空なら トリガー持ち。 on_self_chara_played の if gate で使う。
            pc = getattr(state, "last_self_chara_played_card", None)
            if pc is None:
                return False
            has_trigger = bool(getattr(pc, "trigger", "") or "")
            if bool(v) != has_trigger:
                return False
        elif k == "played_from_trash":
            # 直近に登場したキャラがトラッシュ起源か (= OP16-079 ヤマト「トラッシュから…登場した時」)。
            if bool(v) != bool(getattr(state, "last_self_chara_played_from_trash", False)):
                return False
        elif k == "played_self_chara_feature_in":
            # 直近に登場したキャラが特徴 v (list) のいずれかを持つか (= OP16-079 ヤマト《ワノ国》)。
            pc = getattr(state, "last_self_chara_played_card", None)
            if pc is None:
                return False
            feats = set(getattr(pc, "features", []) or [])
            if not (feats & set(v if isinstance(v, list) else [v])):
                return False
        elif k == "actor_source_feature_contains":
            # 直近の効果発動 source カードの特徴に v を含むか (= OP12-040 クザン用)。
            # trigger_on_self_hand_discarded が state.last_discard_source_inplay を一時設定。
            src = getattr(state, "last_discard_source_inplay", None)
            if src is None:
                return False
            features_text = "/".join(src.card.features)
            if v not in features_text:
                return False
        elif k == "self_chara_no_truly_original_power_ge":
            # 自場 の キャラ (= リーダー 含めない、 me.characters のみ) に、
            # 元々パワー が N 以上 の カード が 「いない」 場合 True (= EB04-051 エメト)。
            # 「元々パワー」 = truly_original_power (= レベル原本)。
            need = int(v)
            for c in me.characters:
                tp = getattr(c, "truly_original_power", c.power)
                if tp is not None and int(tp) >= need:
                    return False
        elif k == "self_chara_truly_original_power_ge":
            # 自場 の キャラ (= me.characters) に、 元々パワー N 以上 が 「いる」 場合 True。
            # 「元々のパワー」 = truly_original_power (= バフ込みの現在値ではなく原本)。
            # ST30-001 「自分の元々のパワー7000以上のキャラがいる場合」 等。
            need = int(v)
            if not any(
                int(getattr(c, "truly_original_power", c.power) or 0) >= need
                for c in me.characters
            ):
                return False
        elif k == "self_chara_filtered_count_ge":
            # 複合 filter (色 + 特徴 + 除外名 等) でカウント条件判定。
            # OP11-096 リッパー 「リッパー以外の自分の黒の特徴《海軍》を持つキャラがいる場合」 等。
            # spec: {"filter": {...}, "count": N, "rested_required": false}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 1))
            rested_required = bool(spec.get("rested_required", False))
            # current_power_ge/le は InPlay の現在パワー (= バフ込み) で絞る。 _matches_filter は
            # CardDef ベース (= 元々パワー) なので filter には入れず ここで判定する
            # (= OP16-005 サッチ「自分のパワー8000以上の白ひげ海賊団キャラがいる場合」)。
            cpge = filt.get("current_power_ge")
            cple = filt.get("current_power_le")
            base_filt = {fk: fv for fk, fv in filt.items()
                         if fk not in ("current_power_ge", "current_power_le")}
            def _ip_matches(ip):
                if not _matches_filter_ip(ip, base_filt):
                    return False
                if rested_required and not ip.rested:
                    return False
                if cpge is not None and ip.power < int(cpge):
                    return False
                if cple is not None and ip.power > int(cple):
                    return False
                return True
            count = sum(1 for c in me.characters if _ip_matches(c))
            if count < need:
                return False
        elif k == "self_chara_filtered_count_le":
            # 自場の filter 一致キャラ数が N 以下 (= 「他の<name>がいない場合」 等)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 0))
            cnt = sum(1 for c in me.characters if _matches_filter_ip(c, filt))
            if cnt > need:
                return False
        elif k == "opp_chara_filtered_count_ge" and opp is not None:
            # 相手場の キャラ で filter にマッチ する 数 N 以上 (= 「相手のコスト0のキャラがいる場合」 等)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 1))
            count = sum(1 for c in opp.characters if _matches_filter_ip(c, filt))
            if count < need:
                return False
        elif k == "opp_chara_filtered_count_le" and opp is not None:
            # 相手場 キャラ で filter にマッチ する 数 N 以下 (= 「相手のパワー5000+のキャラが2以上いない (= ≤1)」 等)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            limit = int(spec.get("count", 0))
            count = sum(1 for c in opp.characters if _matches_filter_ip(c, filt))
            if count > limit:
                return False
        elif k == "self_trash_has_named_all":
            # 自分のトラッシュに 指定 名 すべて が ある (= AND)
            # OP08-006 「自分のトラッシュに「クロマーリモ」と「チェス」がある場合」 等
            names = v if isinstance(v, list) else [v]
            for name in names:
                if not any(c.name == name for c in me.trash):
                    return False
        elif k == "self_hand_count_le":
            if len(me.hand) > int(v):
                return False
        elif k == "self_hand_count_ge":
            if len(me.hand) < int(v):
                return False
        elif k == "opp_hand_count_ge" and opp is not None:
            if len(opp.hand) < int(v):
                return False
        elif k == "self_hand_has_feature":
            # 自分の手札に 指定特徴 (の一部) を含むカードがあるか (= 公開コストの gate)。
            feat = str(v)
            if not any(
                any(feat in f for f in (c.features or ())) for c in me.hand
            ):
                return False
        elif k == "opp_turn":
            # 相手のターン中であれば True (= bool 値で発動条件をトグル)
            is_opp_turn = state.turn_player is not me
            if bool(v) != is_opp_turn:
                return False
        elif k == "self_turn":
            is_self_turn = state.turn_player is me
            if bool(v) != is_self_turn:
                return False
        elif k == "self_rested":
            # 自身 (self_inplay) がレストかどうか。相手ターン中の常在条件で多用
            if self_inplay is None:
                return False
            if bool(v) != self_inplay.rested:
                return False
        elif k == "don_diff_le":
            # 自分のドン総数 - 相手のドン総数 が N 以下 (= 「相手より N 以上少ない」 を表現)
            # 例: don_diff_le: -2 → 自分のドンが相手より 2 枚以上少ない
            n = int(v)
            self_don = (
                me.don_active + me.don_rested + me.leader.attached_dons
                + sum(c.attached_dons for c in me.characters)
            )
            opp_don = (
                opp.don_active + opp.don_rested + opp.leader.attached_dons
                + sum(c.attached_dons for c in opp.characters)
            )
            if (self_don - opp_don) > n:
                return False
        elif k == "chara_diff_le":
            # 自分のキャラ数 - 相手のキャラ数 が N 以下 (= 「相手より N 以上少ない」 を表現、
            # don_diff_le と同形)。 例: chara_diff_le: -2 → 自キャラが相手より 2 枚以上少ない (OP10-098)。
            n = int(v)
            if (len(me.characters) - len(opp.characters)) > n:
                return False
        elif k == "life_zero_either":
            # 自分か相手のライフが 0 (OR)。 OP09-118 用
            if bool(v) != (len(me.life) == 0 or len(opp.life) == 0):
                return False
        elif k == "self_chara_cost_ge_count":
            # 自場のキャラのうち cost N 以上が n_required 枚以上いるか
            # spec: {"cost_ge": N, "n": M}
            spec_val = v if isinstance(v, dict) else {}
            cost_ge = int(spec_val.get("cost_ge", 0))
            n_req = int(spec_val.get("n", 1))
            count = sum(1 for c in me.characters if c.card.cost >= cost_ge)
            if count < n_req:
                return False
        elif k == "self_chara_power_ge_count_le":
            # 自場のキャラ (= me.characters) のうち パワー (現在値) N 以上が count 枚【以下】 なら True。
            # EB02-022 ウソップ 「自分のパワー5000以上のキャラが2枚以下の場合」 等。
            spec_val = v if isinstance(v, dict) else {}
            power_ge = int(spec_val.get("power", spec_val.get("power_ge", 5000)))
            cap = int(spec_val.get("count", 2))
            cnt = sum(1 for c in me.characters if c.power >= power_ge)
            if cnt > cap:
                return False
        elif k == "leader_multicolor":
            # 自リーダーが多色 (= color が 2 色以上) であるか。
            # card.color は tuple (例: ('赤','黄')) なので "/" 文字列判定は常に False だった
            # (= leader_multicolor:True が全 29 枚で不発の systematic bug)。 len で判定。
            is_multi = len(me.leader.card.color) >= 2
            if bool(v) != is_multi:
                return False
        elif k == "leader_feature_contains":
            # 自リーダーの特徴に文字列 v を含む特徴があるか (= 『CP』を含む特徴等)
            if not any(v in f for f in me.leader.card.features):
                return False
        elif k == "self_summoning_sickness":
            # 「このキャラが登場したターンの場合」 = 召喚酔い中。 OP09-093 黒ひげ等
            if self_inplay is None:
                return False
            if bool(v) != self_inplay.summoning_sickness:
                return False
        elif k == "opp_leader_attribute" and opp is not None:
            # 相手リーダーの属性 (例: "斬"、緑ミホーク "斬がある場合 +1000")
            if v != opp.leader.card.attribute:
                return False
        elif k == "self_leader_attribute":
            # 自リーダーの属性 (= 「自分のリーダーが属性(斬) を持つ場合」 等)
            if v != me.leader.card.attribute:
                return False
        elif k == "self_chara_only_feature":
            # 自分の場のキャラがすべて指定特徴を持つ (空でも True)
            if not all(v in c.card.features for c in me.characters):
                return False
        elif k == "self_chara_only_feature_contains":
            # 自分の場のキャラがすべて『指定文字列を含む特徴』を持つ (空でも True)。
            # 公式「自分のキャラが『X』を含む特徴を持つキャラのみの場合」 (EB03-038 ジェルマ:
            #   実特徴は『ジェルマ66』 等のため exact ではなく部分一致で判定)。
            if not all(any(str(v) in f for f in c.card.features) for c in me.characters):
                return False
        elif k == "self_don_le":
            # 自分の場のドン!! (active+rested+attached) が N 以下
            total = me.don_active + me.don_rested + me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
            if total > int(v):
                return False
        elif k == "self_turn_number_ge":
            # 自分の N ターン目以降 (turn_number でなく自分視点のターン数)。
            # 公式 turn_number は両者通算なので、自分の 2 ターン目 = turn_number ≥ 3
            # ヒューリスティック: turn_number ≥ 2*N - 1 (先攻) or 2*N (後攻)
            # 簡略: turn_number >= 2*v - 1 でフィルタ (両者対応)
            if state.turn_number < 2 * int(v) - 1:
                return False
        elif k == "self_attached_don_ge":
            # 自分のリーダー or キャラに合計 N 枚以上のドンが付与されている
            total = me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
            # 【ドン‼×N】【KO時】 等、 source が場を離れた後 (self_inplay=None) は その付与ドンが
            # sum に含まれない → KO 時に退避した枚数を足し戻す (= 常に False になるバグ修正、
            # OP01-038/OP14-051/ST21-004。 2026-06-05)。
            if self_inplay is None:
                total += int(getattr(state, "_on_ko_victim_attached_don", 0) or 0)
            if total < int(v):
                return False
        elif k == "self_chara_unique_name":
            # 「自分の他の <name> が存在しない」 = 自身を除いた同名キャラ 0 (= 唯一性)
            if self_inplay is None:
                return False
            target_name = str(v)
            same = [
                c for c in me.characters
                if c is not self_inplay and c.card.name == target_name
            ]
            if same:
                return False
        elif k == "leader_name":
            # リーダーのカード名一致 (例: "サンジ" / "イム" / "ルーシー")。
            # 半角/全角 D の表記揺れ (「ゴール・Ｄ・ロジャー」 vs CardDef.name の半角D) を
            # normalize_card_name で吸収 (leader_name_contains と同じ。 これが無いと OP13-075 /
            # モンキー・Ｄ・ルフィ 系 overlay の leader_name 条件が silent no-op になる)。
            if normalize_card_name(me.leader.card.name) != normalize_card_name(str(v)):
                return False
        elif k == "leader_name_in":
            # リーダー名がリストに含まれる (半角/全角 D を normalize してから判定)。
            ldr_name = normalize_card_name(me.leader.card.name)
            if ldr_name not in [normalize_card_name(str(x)) for x in (v or [])]:
                return False
        elif k == "leader_name_contains":
            # リーダーのカード名が文字列 v を含む (= 公式『X』を含むカード名)。
            # OP16-015 ルフィ「自分のリーダーが『エース』を含むカード名で…」。
            # 半角/全角 D 等の表記揺れを normalize_card_name で吸収してから判定。
            ldr_name = normalize_card_name(me.leader.card.name)
            if normalize_card_name(str(v)) not in ldr_name:
                return False
        elif k == "opp_chara_ko_this_turn":
            # このターン中に相手のキャラが (バトル/効果いずれでも) KO されたか
            # (= OP16-100 氷諸斬り「このターン中、相手のキャラがKOされている場合」)。
            # state.opp_chara_ko_count_this_turn は trigger_on_opp_chara_ko / KO 処理で加算、
            # _reset_turn_buff でリセット。 ⚠ me 視点で「相手 (= opp) のキャラ」 が KO されたか。
            actual = int(getattr(opp, "chara_ko_taken_this_turn", 0) or 0) > 0 if opp is not None else False
            if bool(v) != actual:
                return False
        elif k == "self_distinct_name_count_filtered_ge":
            # 自場の filter 一致キャラの「カード名の異なる」 数が N 以上
            # (= OP16-038「カード名の異なる特徴《インペルダウン》を持つキャラが5枚いる場合」)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 1))
            distinct = {c.card.name for c in me.characters if _matches_filter_ip(c, filt)}
            if len(distinct) < need:
                return False
        elif k == "self_trash_event_count_ge":
            # 自トラッシュのイベントカード数 N 以上
            count = sum(1 for c in me.trash if c.category == Category.EVENT)
            if count < int(v):
                return False
        elif k == "self_rested_cards_count_ge":
            # 自場のレストカード数 (レストキャラ+レストドン+レストリーダー+レストステージ) ≥ N
            count = me.don_rested
            count += sum(1 for c in me.characters if c.rested)
            if me.leader.rested:
                count += 1
            count += sum(1 for s in me.stages if s.rested)
            if count < int(v):
                return False
        elif k == "opp_rested_cards_count_ge":
            # 相手の場のレストカード数 ≥ N。 公式cardqa: 「レストのカード」 =
            # レストのドン‼ + レストのリーダー + レストのキャラ + レストのステージ の合計。
            # OP08-028 / OP08-033 / OP11-023 「相手のレストのカードがN枚以上ある場合」。
            count = opp.don_rested
            count += sum(1 for c in opp.characters if c.rested)
            if opp.leader is not None and opp.leader.rested:
                count += 1
            count += sum(1 for s in opp.stages if s.rested)
            if count < int(v):
                return False
        elif k == "self_chara_power_ge":
            # 自場に N パワー以上のキャラがいる
            need = int(v)
            if not any(c.power >= need for c in me.characters):
                return False
        elif k == "self_inplay_power_ge":
            # このキャラ自身 (self_inplay) の power が N 以上
            # OP06-002 イナズマ「このキャラのパワーが7000以上の場合」 等
            if self_inplay is None:
                return False
            if self_inplay.power < int(v):
                return False
        elif k == "self_inplay_attached_dons_ge":
            # このキャラ自身 の attached_dons (= 付与されているドン) が N 以上
            # OP13-112 ベガパンク「自分の付与されているドン‼が合計2枚以上ある場合」
            if self_inplay is None:
                return False
            if self_inplay.attached_dons < int(v):
                return False
        elif k == "self_inplay_cost_ge":
            # このキャラ自身 (self_inplay) の現在コスト (base_cost = コスト修正込み) が N 以上。
            # OP16-084 光月モモの助「コスト20以上のこのキャラをトラッシュに置くことができる」
            # (= しのぶ OP16-087 の「コスト+20」 を受けた状態で起動可能になる combo の gate)。
            if self_inplay is None:
                return False
            if getattr(self_inplay, "base_cost", self_inplay.card.cost) < int(v):
                return False
        elif k == "self_life_lt_opp" and opp is not None:
            # 自分のライフ枚数 が 相手より少ない
            # OP03-108 等「自分のライフの枚数が相手より少ない場合」
            if bool(v) != (len(me.life) < len(opp.life)):
                return False
        elif k == "leader_color_multi":
            # 自リーダー が 多色 (= 2 色以上)
            colors = list(me.leader.card.color)
            if bool(v) != (len(colors) >= 2):
                return False
        elif k == "self_stage_named":
            # 自分の場 (stages) に 指定名 の ステージカード あり
            # EB02-033 「自分の場に『ゴーイング・メリー号』がある場合」 等
            target_name = str(v)
            if not any(s.card.name == target_name for s in me.stages):
                return False
        elif k == "opp_or_self_chara_cost_eq_0_exists" and opp is not None:
            # 自場 or 相手場 に コスト0 の キャラ が いる
            # OP02-095 シャーロット・モスカート 「コスト0のキャラがいる場合」 等
            target_cost = int(v)
            has = any(c.card.cost == target_cost for c in me.characters) or any(
                c.card.cost == target_cost for c in opp.characters
            )
            if not has:
                return False
        elif k == "don_count_ge":
            # 統一 alias: 自分のドン!! 合算 (active + rested + attached) ≥ N。
            # = self_don_ge と同義。 overlay 側で表現の揺れを吸収するため両方対応。
            total = (
                me.don_active + me.don_rested + me.leader.attached_dons
                + sum(c.attached_dons for c in me.characters)
            )
            if total < int(v):
                return False
        elif k == "don_count_le":
            # 統一 alias: 自分のドン!! 合算 ≤ N。 = self_don_le と同義。
            total = (
                me.don_active + me.don_rested + me.leader.attached_dons
                + sum(c.attached_dons for c in me.characters)
            )
            if total > int(v):
                return False
        elif k == "opp_don_count_ge" and opp is not None:
            # 相手のドン!! 合算 ≥ N。
            total = (
                opp.don_active + opp.don_rested + opp.leader.attached_dons
                + sum(c.attached_dons for c in opp.characters)
            )
            if total < int(v):
                return False
        elif k == "opp_don_count_le" and opp is not None:
            # 相手のドン!! 合算 ≤ N。
            total = (
                opp.don_active + opp.don_rested + opp.leader.attached_dons
                + sum(c.attached_dons for c in opp.characters)
            )
            if total > int(v):
                return False
        elif k == "opp_leader_feature" and opp is not None:
            # 相手リーダーが特徴 X を持つか (str or list)。 leader_feature の opp 版。
            features = opp.leader.card.features
            if isinstance(v, str):
                if v not in features:
                    return False
            elif isinstance(v, list):
                if not any(f in features for f in v):
                    return False
        elif k == "_unimplemented":
            # 「未対応条件」 マーカー: True 扱いにする (= 効果は試行する、 ただし忠実でない可能性あり)
            # 上位レビューで埋める前提
            continue
        else:
            # 未対応の条件は False 扱い(暴発防止)
            return False
    return True


# --------------------------------------------------------------------------- #
# 対象選択ヘルパ
# --------------------------------------------------------------------------- #
def _should_human_pick(state: GameState) -> bool:  # noqa: F811
    """人間 操作中 か (= state.human_player_idx == 現 turn_player_idx)。

    forced_human_actor_idx の 値:
    - = human_player_idx: 強制 True (= counter event 等 自ターン外 で human actor)
    - = -1: 強制 False (= AI-owned event 中、 human の choice modal を 出さない)
    - = None: 通常 (= turn_player_idx 判定)
    """
    forced = getattr(state, "forced_human_actor_idx", None)
    if (
        forced is not None
        and state.human_player_idx is not None
        and forced == state.human_player_idx
    ):
        return True
    if forced == -1:
        # AI-owned event 中 で human の choice を 出さない (= AI の 隠匿 情報 流出 防止)
        return False
    return (
        state.human_player_idx is not None
        and state.turn_player_idx == state.human_player_idx
    )


def _describe_filter_jp(filt: dict) -> str:
    """filter spec を 日本語 短文 で 記述 (= UI 説明用)。"""
    parts: list[str] = []
    if not isinstance(filt, dict):
        return ""
    if "cost_le" in filt:
        parts.append(f"コスト{filt['cost_le']}以下")
    if "cost_ge" in filt:
        parts.append(f"コスト{filt['cost_ge']}以上")
    if "power_le" in filt:
        parts.append(f"パワー{filt['power_le']}以下")
    if "power_ge" in filt:
        parts.append(f"パワー{filt['power_ge']}以上")
    if "feature" in filt:
        parts.append(f"特徴《{filt['feature']}》")
    if "feature_any" in filt:
        feats = filt["feature_any"]
        if isinstance(feats, list):
            parts.append(f"特徴《{'/'.join(feats)}》")
    if "color" in filt:
        parts.append(f"{filt['color']}")
    if "name" in filt:
        parts.append(f"「{filt['name']}」")
    if "name_in" in filt:
        names = filt["name_in"]
        if isinstance(names, list):
            parts.append(f"「{', '.join(names[:3])}」")
    return " ".join(parts) if parts else ""


def _maybe_request_target_pick(
    state: GameState,
    candidates: list,
    limit: int,
    primitive_kind: str,
    primitive_value: Any,
    self_inplay: Optional[InPlay],
    description: str = "",
) -> bool:
    """候補 が 1 枚以上 + 人間 操作中 なら pending_choice を 立てて True を 返す。

    旧挙動 (= candidates <= limit で 自動 pick) は 「相手キャラ 1 枚 のみ → 勝手に KO」
    現象 を 起こす。 ohtsuki さん 要望 「決定権 を 人間 に」 に従い、 候補 ≥ 1 で
    必ず modal で 確認。 0 picks (= skip) も 公式 「N 枚 まで」 で 許容。

    True 返却 時 は 呼び出し側 で 該当 primitive を 中断する (= 空 list を 返す等)。
    """
    if not _should_human_pick(state):
        return False
    if len(candidates) < 1:
        return False
    # 「self / opp」 ラベル は ACTOR (= 効果 の owner) 基準。 forced_human_actor_idx が
    # human に セット 済 (= human が actor) なら、 human の 場 を self に。 通常 は turn_player。
    forced = getattr(state, "forced_human_actor_idx", None)
    if (
        forced is not None and forced >= 0
        and state.human_player_idx is not None
        and forced == state.human_player_idx
    ):
        actor_idx = forced
    else:
        actor_idx = state.turn_player_idx
    me = state.players[actor_idx]
    opp = state.players[1 - actor_idx]
    cand_list = []
    for c in candidates:
        owner = "self" if c in [me.leader, *me.characters, *me.stages] else "opp"
        cand_list.append({
            "iid": c.instance_id,
            "card_id": c.card.card_id,
            "name": c.card.name,
            "power": c.power,
            "rested": c.rested,
            "attached_dons": c.attached_dons,
            # 盤面と同じ状態表示のため summoning_sickness / keywords を含める (2026-07-08、 ohtsuki 要望)。
            # _inplay_snapshot と同じフィールド → モーダルでも召喚酔い/速攻/ブロッカー等が判る。
            "summoning_sickness": getattr(c, "summoning_sickness", False),
            "keywords": sorted({
                *(["速攻"] if getattr(c, "is_rush_now", False) else []),
                *(["ブロッカー"] if getattr(c, "is_blocker_now", False) else []),
                *(["ダブルアタック"] if getattr(c, "is_double_attack_now", False) else []),
                *(["バニッシュ"] if getattr(c, "is_banish_now", False) else []),
            }),
            "owner": owner,
            "is_leader": c is (me.leader if owner == "self" else opp.leader),
        })
    state.pending_choice = {
        "kind": "target_pick",
        "primitive_kind": primitive_kind,
        "primitive_value": primitive_value,
        "candidates": cand_list,
        "limit": limit,
        "self_inplay_iid": self_inplay.instance_id if self_inplay else None,
        "description": description or f"対象 {limit} 枚 を 選択",
    }
    state.push_log(
        f"  効果: {primitive_kind} 選択 待ち ({len(candidates)}枚 候補 から {limit}枚)"
    )
    return True


def _resolve_target(
    target_spec: Any,
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay],
    outer_kind: Optional[str] = None,
    outer_value: Any = None,
) -> list[InPlay]:
    """target 指定文字列または辞書から対象 InPlay リストを返す。

    内部 hooks:
    - target_spec が dict で `_iid_picks` を 持つ 場合、 候補 から その iid のみ 残す
      (= 人間 選択 resolved 後 の 再実行 で 使用)
    - outer_kind が 与えられて 候補が limit を 超える + 人間 操作中 なら
      pending_choice を 立てて [] を 返す (= halt)。 outer_kind は resolver が
      再実行 する 際 の 外側 primitive 名 (= "ko" / "power_pump" 等)。
    - outer_value: pending_choice に 記録する 元 spec (= 再実行時に そのまま 使う)
    """
    # ⭐ 公式は 「コストN以下」 と 「**元々の**コストN以下」 を区別する (2026-08-04)。
    #   - 「コストN以下」        = 効果修正を反映した **現在のコスト** (InPlay.base_cost)
    #     cardqa_op_02「本来のコストが8以上のキャラが、他の効果で7コスト以下になった場合…はい、できます」
    #   - 「元々のコストN以下」   = **印刷コスト** (CardDef.cost)
    #     cardqa_eb_03「元々のコストが4以上で、他の効果によって現在のコストが3以下になっている
    #                  キャラを…」→「いいえ、できません」
    #   spec 名に `_truly_original_cost_` が入っていれば印刷コスト、 それ以外は現在コスト。
    #   ⚠ 分岐ごとに regex を増やすと保守が破綻するので **入口で正規化** し、 各分岐は
    #     `_cost_of(ip)` を通す (= どちらのコストを見るかは 1 箇所で決まる)。
    _use_printed_cost = False
    if isinstance(target_spec, str) and "_truly_original_cost_" in target_spec:
        _use_printed_cost = True
        target_spec = target_spec.replace("_truly_original_cost_", "_cost_")
    # パワーも同じ書き分け (公式 cardqa: 「元々のパワーが6000以下のキャラが効果で7000以上に
    # なっている場合、 この【メイン】効果でKOできますか？」 → 「いいえ。 **現在のパワー**が
    # 6000以下のキャラをKOできます」)。 素の 「パワーN以下」 = 現在値 / 「元々のパワー」 = 印刷値。
    _use_printed_power = False
    if isinstance(target_spec, str) and "_truly_original_power_" in target_spec:
        _use_printed_power = True
        target_spec = target_spec.replace("_truly_original_power_", "_power_")

    def _cost_of(ip) -> int:
        """target spec のコスト判定に使う値 (公式: 既定は現在コスト)。"""
        return ip.card.cost if _use_printed_cost else ip.base_cost

    def _power_of(ip) -> int:
        """target spec のパワー判定に使う値 (公式: 既定は現在パワー)。"""
        return ip.card.power if _use_printed_power else ip.power

    # opp target 「実害 評価」 (= AI が pick する 際 の eval 良い順)。
    # ohtsuki さん 要望 「AI も最善手 考えるよう target expansion」。
    # 排除 価値 = cost + power + blocker bonus + finisher role bonus
    def _opp_value(c) -> float:
        val = float(c.card.cost) * 1000 + float(c.power)
        if getattr(c, "is_blocker_now", False):
            val += 3000
        try:
            from . import card_role as _cr
            # ⚠ 旧: get_primary_role (存在しない関数) を try/except で握り潰しており role 加点が
            # 一切効いていなかった → サーチ/ドローエンジン等 (低コスト・低パワー) の除去優先度が
            # 最低になり「盤面エンジンを放置してバニラアタッカーを除去」する誤判断をしていた。
            _rec = _cr.get_card_role(c.card.card_id) or {}
            role = _rec.get("primary_role")
            if role == "finisher":
                val += 5000
            elif role in ("blocker",):
                val += 2500
            # 起動メイン/登場時の draw/search エンジンは盤面に残すと毎ターン相手を利する脅威 →
            # 優先除去対象に (= ohtsuki 指摘「サーチ系キャラが除去対象になっていない」)。
            elif role in ("draw", "search"):
                val += 2000
            elif role in ("removal", "negation", "disruption", "ramp", "recovery", "support", "synergy"):
                val += 1500
        except Exception:
            pass
        return val

    def _either_pick_one(
        opp_cands: list, self_cands: list, description: str
    ) -> Optional[list]:
        """両陣営候補から 1 枚選ぶ (公式: 修飾なし 「キャラ1枚まで」 は自陣も対象)。

        一次情報 (複数の弾で繰り返し = 一般則): 「この【登場時】/【アタック時】/【メイン】/
        【カウンター】/【トリガー】/【ブロック時】/【起動メイン】/【KO時】効果で **自分の
        キャラ** を手札に戻す/デッキの下に置く/ライフに置く ことはできますか？」 →
        「はい、できます」。 「このキャラ自身」 も選べる。

        human は modal で **両陣営** から選ぶ (= 選択肢の平等)。

        ⚠ **AI は自陣を auto-pick しない**。 この spec 群を使う効果は全て 公式が
        「キャラN枚**まで**」 = **0 枚を選べる** (2026-08-04 に overlay 全 64 件を確認済、
        「N枚を」 の必須形は 1 件も無い)。 相手が居ない局面で自分のキャラを
        デッキの下/手札/ライフへ送るのは ほぼ常に悪手なので、 相手候補が無ければ
        **何も選ばない** (= 0 枚) のが正しい auto-pick。
        (自キャラを戻して【登場時】を撃ち直す等の意図的な自陣選択は 人間の判断に委ねる。
         AI にやらせるには 「戻す価値」 の評価が要る = 現状の 1-ply auto-pick では測れない)

        **None を返したら 呼び出し側は [] を返して halt** (= modal 待ち)。
        """
        cands = list(opp_cands) + list(self_cands)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description=description,
        ):
            return None
        ranked = sorted(opp_cands, key=lambda c: -_opp_value(c))
        return ranked[:1]

    # _iid_picks bypass (= resolve_pending_choice 経由 の 再実行)
    # ユーザ の 選択した iid から 該当 InPlay を 全 場 から 直接 解決 する。
    # 元 の target_spec の filter は 既に user 選択 で 通過 済 と 見なす。
    iid_picks: Optional[list[int]] = None
    if isinstance(target_spec, dict) and "_iid_picks" in target_spec:
        iid_picks = target_spec["_iid_picks"]
    if iid_picks is not None:
        all_inplay = (
            [me.leader, opp.leader]
            + list(me.characters) + list(opp.characters)
            + list(me.stages) + list(opp.stages)
        )
        return [ip for ip in all_inplay if ip.instance_id in iid_picks]
    # 辞書 spec の filter に dynamic key (= cost_le_dynamic 等) が あれば 静的化。
    # 元 spec は 変更せず、 解決後 の spec を 以降 の dispatch で 使う。
    if isinstance(target_spec, dict) and "filter" in target_spec:
        resolved_filter = _resolve_dynamic_filter(target_spec.get("filter") or {}, state, me, opp)
        if resolved_filter is not target_spec.get("filter"):
            target_spec = {**target_spec, "filter": resolved_filter}
    # 辞書 spec で type-based dispatch
    if isinstance(target_spec, dict) and "type" in target_spec:
        t = target_spec["type"]
        # chara / character 表記揺れ alias (= 短縮形 を 長形 に 正規化)
        # 既存 overlay 8 件 が "one_opp_chara_filtered" を 使っていて 全 silent no-op だった bug 対策。
        _TYPE_ALIASES = {
            "one_opp_chara_filtered": "one_opponent_character_filtered",
            "one_opp_chara_any": "one_opponent_character_any",
            # chara/character 表記揺れ (= P-029 等 14 件が dict 形で silent no-op だった、 2026-06-05)
            "one_self_character_filtered": "one_self_chara_filtered",
        }
        if t in _TYPE_ALIASES:
            t = _TYPE_ALIASES[t]
        if t == "self_chara_named":
            name = target_spec.get("name", "")
            return [ip for ip in me.characters if name_matches(ip.card, name)][:1]
        if t == "self_chara_or_leader_named":
            name = target_spec.get("name", "")
            cands = [ip for ip in [me.leader, *me.characters] if name_matches(ip.card, name)]
            # 同名(例「エネル」)が リーダーとキャラで複数居る場合、 人間は modal で選べる
            # (2026-07-08、 ohtsuki 指摘: 放電/神の裁き counter でキャラのエネルを選べなかった bug)。
            if len(cands) > 1 and outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"「{name}」1枚を選択(リーダー/キャラ)",
            ):
                return []
            return cands[:1]
        if t == "all_self_chara_named":
            name = target_spec.get("name", "")
            return [ip for ip in me.characters if name_matches(ip.card, name)]
        if t == "one_self_chara_or_leader_filtered":
            # 自リーダー / キャラから filter にマッチする 1 枚 (パワー高い順、 human は modal で選択)
            filt = target_spec.get("filter", {})
            cands = [ip for ip in [me.leader, *me.characters]
                     if _matches_filter_ip(ip, filt)]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自リーダー or キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "one_self_chara_filtered":
            # 自キャラのみから filter にマッチする 1 枚 (パワー高い順、 human は modal で選択)
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.characters
                     if _matches_filter_ip(ip, filt)]
            # 「(現在の) パワー N 以下/以上」 (= 元々のパワー でなく バフ込み 現在値)。
            # _matches_filter は CardDef ベースで現在値を見られないため ここで InPlay.power を判定。
            if "current_power_le" in filt:
                cands = [ip for ip in cands if ip.power <= int(filt["current_power_le"])]
            if "current_power_ge" in filt:
                cands = [ip for ip in cands if ip.power >= int(filt["current_power_ge"])]
            # 「自分のレストの…」 (= OP10-029) は target-spec 直下の rested_required で
            # レスト限定を honor する (公式テキスト「自分のレストの…をアクティブにする」)。
            # 未指定 (= false) なら active/rested 問わず。
            # ⚠ filter 側に rested/active を書いた overlay も許容する: _matches_filter は
            # CardDef ベースで rested を知らない (= 未知キーは黙って無視) ため、 filter 直書きを
            # honor しないと 「レスト限定」 が silent に消える (= ST02-009_r1 で実害)。
            # one_opponent_character_filtered は filter 側で honor しており 記法が割れている。
            if bool(target_spec.get("rested_required", False)) or bool(filt.get("rested", False)):
                cands = [ip for ip in cands if ip.rested]
            if bool(filt.get("active", False)):
                cands = [ip for ip in cands if not ip.rested]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "all_chara_filtered":
            # 両陣営のキャラ全員 (filter マッチ)。 = ST08-005「コスト1以下のキャラすべてをKO」
            # (自他両方)。 未処理で 0 対象 = silent no-op だった (2026-06-05 target dict 次元 sweep)。
            filt = target_spec.get("filter", {})
            return [ip for ip in [*me.characters, *opp.characters]
                    if _matches_filter_ip(ip, filt)]
        if t == "all_self_chara_filtered":
            # 自キャラ全員 (filter マッチ)。 limit 指定で上限あり (= 「N 枚まで」)。
            # rested フィールド (= optional) で active/rested を 絞れる。
            # human + 候補 > limit なら modal で 選択。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.characters if _matches_filter_ip(ip, filt)]
            if "rested" in target_spec:
                rested_required = bool(target_spec["rested"])
                cands = [ip for ip in cands if ip.rested == rested_required]
            elif "rested" in filt:
                # filter 直書きも honor (= 記法揺れによる silent no-op 防止、 上の
                # one_self_chara_filtered と同じ理由)。
                cands = [ip for ip in cands if ip.rested == bool(filt["rested"])]
            # 現在パワー (= DON 付与等の修正込み) での絞り込み。 ⚠ filter の power_ge は _matches_filter
            # 経由で「元々パワー (CardDef 印刷値)」 を見るので、 「(元々でない) パワーN以上」 は別キー
            # current_power_ge/le で InPlay.power を見る (= OP16-001 エース「自分のパワー8000以上の…」)。
            cpge = target_spec.get("current_power_ge")
            cple = target_spec.get("current_power_le")
            if cpge is not None:
                cands = [ip for ip in cands if ip.power >= int(cpge)]
            if cple is not None:
                cands = [ip for ip in cands if ip.power <= int(cple)]
            limit = target_spec.get("limit")
            if iid_picks is not None and limit is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:int(limit)]
            if limit is not None:
                if outer_kind and len(cands) > int(limit) and _maybe_request_target_pick(
                    state, cands, int(limit), outer_kind, outer_value, self_inplay,
                    description=f"自キャラ から {limit} 枚 まで 選択",
                ):
                    return []
                # 脅威度 (効果) 優先 + power tie-break (= カードを区別して選ぶ)
                cands.sort(key=_threat_key)
                return cands[:int(limit)]
            return cands
        if t == "all_self_team_filtered":
            # 自リーダー + キャラ全員 (filter マッチ)。 limit 指定で上限 (= 「合計N枚まで」、
            # EB02-007 等)。 AI は power 高い順に limit 枚。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in [me.leader, *me.characters]
                     if _matches_filter_ip(ip, filt)]
            if "limit" in target_spec:
                cands = sorted(cands, key=lambda ip: -ip.power)[:int(target_spec["limit"])]
            return cands
        if t in ("one_opponent_character_filtered", "one_character_either_filtered"):
            # 相手キャラから filter にマッチする 1 枚 (= パワー高い順、 attached_don 等の属性条件も追加サポート)
            # `one_character_either_filtered` は 公式が 「相手の」 と書いていない場合 (= 両陣営) 用。
            filt = target_spec.get("filter", {})
            attached_don_ge = int(filt.get("attached_don_ge", 0))
            rested_required = bool(filt.get("rested", False))
            active_required = bool(filt.get("active", False))
            blocker_required = bool(filt.get("blocker", False))

            def _chara_filter_ok(ip) -> bool:
                if not _matches_filter_ip(ip, filt):
                    return False
                if attached_don_ge > 0 and ip.attached_dons < attached_don_ge:
                    return False
                if rested_required and not ip.rested:
                    return False
                if active_required and ip.rested:
                    return False
                # 公式 「【ブロッカー】を持つキャラ」 (= 付与込みの現在の blocker 状態)
                if blocker_required and not ip.is_blocker_now:
                    return False
                if "current_power_le" in filt and ip.power > int(filt["current_power_le"]):
                    return False
                # 現在(実効)コスト条件 (= base_cost、 cost_minus/軽減 反映)。 公式の 平文
                # 「コスト N の…」 は現在コスト参照 (「元々のコスト」 は printed=_matches_filter の
                # cost_eq を使う)。 CardDef を受ける _matches_filter では実効コストを見られない
                # ため、 InPlay を持つ この resolver で判定する (= current_power_le と同じ扱い)。
                # 例: EB01-040 キュロス「相手のコスト0のキャラをKO」 = 軽減で0になったキャラも対象。
                if "current_cost_eq" in filt and ip.base_cost != int(filt["current_cost_eq"]):
                    return False
                if "current_cost_le" in filt and ip.base_cost > int(filt["current_cost_le"]):
                    return False
                if "current_cost_ge" in filt and ip.base_cost < int(filt["current_cost_ge"]):
                    return False
                return True

            cands = [ip for ip in opp.characters if _chara_filter_ok(ip)]
            if t == "one_character_either_filtered":
                self_cands = [ip for ip in me.characters if _chara_filter_ok(ip)]
                if iid_picks is not None:
                    return [ip for ip in (cands + self_cands)
                            if ip.instance_id in iid_picks][:1]
                picked = _either_pick_one(cands, self_cands, "両陣営のキャラ から 1 枚 選択")
                return [] if picked is None else picked
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="相手キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]
        if t == "all_opponent_chara_filtered":
            # 相手キャラ全員 (filter マッチ)。 limit 指定で上限あり (= 「N 枚まで」)。
            # 公式 「相手のキャラ N 枚まで」 で、 power 5000 制限がないケースに使う。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in opp.characters if _matches_filter_ip(ip, filt)]
            limit = target_spec.get("limit")
            if iid_picks is not None and limit is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:int(limit)]
            if limit is not None:
                # 人間 acting + 候補 > limit で modal (= 自分が 「相手キャラ N 枚 まで」 を 選ぶ)
                if outer_kind and len(cands) > int(limit) and _maybe_request_target_pick(
                    state, cands, int(limit), outer_kind, outer_value, self_inplay,
                    description=f"相手キャラ から {limit} 枚 まで 選択",
                ):
                    return []
                cands.sort(key=lambda ip: -_opp_value(ip))
                return cands[:int(limit)]
            return cands
        if t == "one_inplay_either_filtered":
            # 両陣営のリーダー/キャラ から filter にマッチする 1 枚 (公式が 「相手の」 と
            # 書いていない場合)。 = one_opponent_inplay_filtered の両陣営版。
            filt = target_spec.get("filter", {})
            opp_cands = [ip for ip in [opp.leader, *opp.characters]
                         if _matches_filter_ip(ip, filt)]
            self_cands = [ip for ip in [me.leader, *me.characters]
                          if _matches_filter_ip(ip, filt)]
            if iid_picks is not None:
                return [ip for ip in (opp_cands + self_cands)
                        if ip.instance_id in iid_picks][:1]
            picked = _either_pick_one(
                opp_cands, self_cands, "両陣営のリーダー/キャラ から 1 枚 選択")
            return [] if picked is None else picked
        if t == "one_opponent_inplay_filtered":
            # 相手リーダー or キャラ から filter にマッチする 1 枚
            filt = target_spec.get("filter", {})
            cands = [opp.leader, *opp.characters]
            cands = [ip for ip in cands if _matches_filter_ip(ip, filt)]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="相手リーダー or キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]
        if t == "one_self_stage_filtered":
            # 自分のステージから filter にマッチする 1 枚 (= レスト中優先、 human は modal で選択)。
            # 公式 「自分の紫のステージ1枚までを、 アクティブにする」 (P-077 等)。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.stages if _matches_filter_ip(ip, filt)]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自ステージ から 1 枚 選択",
            ):
                return []
            # untap 用途なら rested を優先、 そうでなければ任意 1 枚
            cands.sort(key=lambda ip: (0 if ip.rested else 1))
            return cands[:1]
    if target_spec == "victim":
        # replace_ko / replace_leave / replace_rest 内 で 「KO/離脱対象 自身」 を 対象 とする 際 に 使う。
        # state.last_replace_victim を 参照 (= try_replace_ko 等 が セット)。
        vic = getattr(state, "last_replace_victim", None)
        return [vic] if vic is not None else []
    if target_spec == "opp_just_negated_any":
        # 直前に negate した相手のリーダー or キャラ (= 「1 枚までを、 効果を無効にし、 パワー-N」 の
        # 後半。 公式は 同一の 1 枚 に 両方 適用する ので、 target を 2 回 解決すると 別カードに
        # 当たりうる (human なら modal が 2 回 出て 実際に 割れる)。 OP09-097 闇水 等)。
        iid = getattr(state, "last_negated_iid", None)
        if iid is not None:
            for ip in [opp.leader, *opp.characters]:
                if ip is not None and ip.instance_id == iid:
                    return [ip]
        return []
    if isinstance(target_spec, str):
        # opp_just_negated_power_le_N / _cost_le_N: 直前に negate した相手キャラを、
        # power/cost 閾値を満たす場合のみ返す (= 「その後、 そのキャラのパワー/コストがX以下ならKO」、
        # OP06-074/OP09-098)。 元々パワー/コストで判定。
        m = re.match(r"opp_just_negated_(power|cost)_le_(\d+)$", target_spec)
        if m:
            kind = m.group(1); thr = int(m.group(2))
            iid = getattr(state, "last_negated_iid", None)
            if iid is not None:
                for ip in opp.characters:
                    if ip.instance_id == iid:
                        val = ip.power if kind == "power" else ip.base_cost
                        return [ip] if val <= thr else []
            return []
    if target_spec == "opp_just_battled":
        # 直前にバトルした相手キャラ (ST08-013)。 バトルKO で既に場を離れていれば [] (= 不発)。
        iid = getattr(state, "last_battled_opp_iid", None)
        if iid is not None:
            for ip in opp.characters:
                if ip.instance_id == iid:
                    return [ip]
        return []
    if target_spec == "self_team_except_self":
        # 「このキャラ以外の自分のリーダーかキャラ1枚まで」 (ST01-005)。 発動元を除外。
        cands = [ip for ip in [me.leader, *me.characters]
                 if self_inplay is None or ip.instance_id != self_inplay.instance_id]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自リーダー or 他キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda ip: -ip.power)
        return cands[:1]
    if target_spec == "self_just_buffed":
        # soshite (= 「その後、 そのカードを〜」) で直前の power_pump 対象を再参照。
        iid = getattr(state, "last_pumped_iid", None)
        if iid is not None:
            for ip in [me.leader, *me.characters]:
                if ip.instance_id == iid:
                    return [ip]
        return []
    if target_spec in (None, "self") and self_inplay is not None:
        return [self_inplay]
    # "self_inplay" は 「自分のリーダーかキャラ 1 枚 まで」 の shorthand
    # (overlay 249 件 で 使用、 主に counter event / trigger 等 で
    # 「自分のリーダーかキャラ1枚までを、 このバトル中、 パワー+N」 系)。
    # one_self_team_any と 同 semantics で 解決 (= 人間 acting で modal、 AI auto-pick)。
    if target_spec == "self_inplay":
        cands = [me.leader] + list(me.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自リーダー or キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda ip: -ip.power)
        return cands[:1]
    if target_spec in ("opponent_leader", "one_opponent_leader"):
        # one_opponent_leader: overlay の別名表記 (= OP06-023 等)。 未処理だと 0 対象で
        # 効果が silent no-op (= set_cannot_attack が相手リーダーに付かない、 2026-06-05 検出)。
        return [opp.leader]
    if target_spec == "self_leader":
        return [me.leader]
    if target_spec == "last_self_played_chara":
        # 直近に登場した「そのキャラ」 (= OP16-079 ヤマト)。 last_self_chara_played_iid で me の場から特定。
        iid = getattr(state, "last_self_chara_played_iid", None)
        if iid is None:
            return []
        return [ip for ip in me.characters if ip.instance_id == iid]
    if target_spec in ("all_opponent_characters", "all_opp_characters"):
        return list(opp.characters)
    if target_spec == "all_opponent_characters_power_le_0":
        # 「相手のパワー0以下のキャラすべて」 (= OP15-114 ワイパー 等)。 現在 power で判定。
        return [c for c in opp.characters if _power_of(c) <= 0]
    if target_spec == "any_self_chara":
        # 「自分のキャラ 1 枚」 を 表す 別名 (= 25 overlay 使用)。
        # 公式 「自分のキャラ 1 枚を、 〜」 系。 one_self_character_any と 同 semantics。
        cands = list(me.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_opp_character_any":
        # `one_opponent_character_any` の typo / 短縮形 (= 2 overlay 使用)。
        return _resolve_target(
            "one_opponent_character_any", state, me, opp, self_inplay,
            outer_kind=outer_kind, outer_value=outer_value,
        )
    if target_spec == "one_opp_chara_or_leader":
        # 相手リーダー or キャラ 1 枚 (= one_opponent_inplay_any の alias、 3 overlay 使用)。
        return _resolve_target(
            "one_opponent_inplay_any", state, me, opp, self_inplay,
            outer_kind=outer_kind, outer_value=outer_value,
        )
    if target_spec == "all_opp_chara_blocker_filtered":
        # 相手の【ブロッカー】 を持つ キャラ 全員 (= OP11-013 等)。
        return [c for c in opp.characters if c.is_blocker_now]
    if target_spec == "one_self_chara_no_on_attack_effect":
        # 「自分の【アタック時】効果を持たないキャラ 1 枚」 (= EB03-001 ビビ の 速攻付与対象)。
        # overlay に when=="on_attack" が 無い キャラを候補 (= アタック時効果を持たない)。
        overlay_map = state.effects_overlay or {}
        def _no_on_attack(card):
            bundle = overlay_map.get(card.card_id)
            if bundle is None:
                return True
            return not any(e.get("when") == "on_attack" for e in bundle.effects)
        cands = [c for c in me.characters if _no_on_attack(c.card)]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自キャラ から 1 枚 選択 (【アタック時】効果なし)",
        ):
            return []
        cands.sort(key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_self_chara_no_effect":
        # 「自分の元々の効果のないキャラ 1 枚」 (= EB03-009 等)。
        # overlay に effect が 登録されてない (= effects=[]) を 「効果なし」 と判定。
        overlay_map = state.effects_overlay or {}
        def _no_effect(card):
            bundle = overlay_map.get(card.card_id)
            return bundle is None or len(bundle.effects) == 0
        cands = [c for c in me.characters if _no_effect(c.card)]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自キャラ から 1 枚 選択 (元々の効果なし)",
        ):
            return []
        cands.sort(key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_opp_chara_no_effect":
        # 「相手の元々の効果のないキャラ 1 枚」 (= OP03-091 等)。 one_self_chara_no_effect の相手版。
        # ⚠ no_effect は _matches_filter で honor されない (state 依存) ため、 filter ではなく
        # 専用 target type で解決する必要がある (one_opponent_character_filtered + filter:no_effect は
        # silent に全キャラ対象になる bug)。
        overlay_map = state.effects_overlay or {}
        def _no_effect_opp(card):
            bundle = overlay_map.get(card.card_id)
            return bundle is None or len(bundle.effects) == 0
        cands = [c for c in opp.characters if _no_effect_opp(c.card)]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手キャラ から 1 枚 選択 (元々の効果なし)",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "opponent_attacker":
        # 公式 「相手のアタックしているリーダーかキャラ」 (= opp_attack コンテキスト)。
        # state.current_attacker_iid から 引く。 OP04-069 等。
        attacker_iid = getattr(state, "current_attacker_iid", None)
        if attacker_iid is None:
            return []
        for ip in [opp.leader, *opp.characters]:
            if ip.instance_id == attacker_iid:
                return [ip]
        return []
    if target_spec == "any_opponent_character_le_5000":
        # 全員対象 (board wipe 系)。普通のカード「1枚まで」は one_* を使うこと
        return [c for c in opp.characters if c.power <= 5000]
    # --- single-target (公式テキスト「1 枚まで」相当) ---
    # 候補を 脅威度 (効果) 優先 + power tie-break で並べる (= 「最も対処すべき駒」を狙う)。
    # 人間 acting + outer_kind あり なら modal で 選ばせる (= ohtsuki さん 要望
    # 「本来 人間判断 すべき箇所が auto 実行」 修正)。
    if target_spec == "one_opponent_character_le_5000":
        cands = [c for c in opp.characters if c.power <= 5000]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手キャラ から 1 枚 選択 (パワー≤5000)",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "one_opponent_character_le_4000":
        cands = [c for c in opp.characters if c.power <= 4000]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手キャラ から 1 枚 選択 (パワー≤4000)",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "one_character_either_any":
        # 公式 「キャラ1枚まで」 (= 修飾なし → 両陣営)。 OP03-057 三・千・世・界 等。
        picked = _either_pick_one(
            list(opp.characters), list(me.characters), "両陣営のキャラ から 1 枚 選択")
        return [] if picked is None else picked
    if target_spec == "one_opponent_character_any":
        cands = list(opp.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "one_opp_chara_blocker":
        # 相手の【ブロッカー】 を持つキャラ 1 枚 (= 実害評価高い順)
        cands = [c for c in opp.characters if c.is_blocker_now]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手ブロッカー から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda ip: -_opp_value(ip))
        return cands[:1]
    if target_spec == "one_opponent_inplay_any":
        # リーダー or キャラ 1 枚 (= 「相手のリーダーかキャラ 1 枚まで」)。
        cands = [opp.leader] + list(opp.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手リーダー or キャラ から 1 枚 選択",
        ):
            return []
        # AI: 脅威優先: 実害評価高いキャラ → なければリーダー
        chara_cands = sorted(opp.characters, key=lambda c: -_opp_value(c))
        if chara_cands:
            return chara_cands[:1]
        return [opp.leader]
    if target_spec == "one_self_character_filtered":
        # spec が辞書じゃないと filter は外から渡せないので、 caller 側でラップ済みを期待。
        # 単独で来た場合は全自キャラから最強を返す (= フォールバック、 human は modal で選択)
        cands = list(me.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_opponent_rested_character_le_5000":
        cands = [c for c in opp.characters if c.rested and c.power <= 5000]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手レストキャラ から 1 枚 選択 (パワー≤5000)",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "one_opponent_rested_character_don_eq_cost":
        # 「相手のレストのキャラ1枚までを選ぶ。 選んだキャラのコストが付与ドン枚数と同じ場合、 KO」
        # (= OP15-031 プリンプリン)。 簡略: cost==attached_dons を満たす rested キャラだけを候補化
        # (= KO が成立する選択のみ行う)。
        cands = [
            c for c in opp.characters
            if c.rested and getattr(c, "base_cost", -1) == getattr(c, "attached_dons", -2)
        ]
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="相手レストキャラ から 1 枚 選択 (コスト=付与ドン枚数)",
        ):
            return []
        cands.sort(key=lambda c: -_opp_value(c))
        return cands[:1]
    if target_spec == "all_self_characters":
        return list(me.characters)
    # all_self_chara(racters)_cost_le_N: 自分のコストN以下のキャラ すべて (= OP06-096 等)。
    # 未処理だと 0 対象で silent no-op (= set_battle_ko_immune が付かない、 2026-06-05 検出)。
    # ⚠ この位置は str-guard 外 (= target_spec が dict もありうる) なので isinstance ガード必須。
    _m_all_self = (re.match(r"all_self_chara(?:cters?)?_cost_le_(\d+)$", target_spec)
                   if isinstance(target_spec, str) else None)
    if _m_all_self:
        cap = int(_m_all_self.group(1))
        return [c for c in me.characters if _cost_of(c) <= cap]
    if target_spec == "all_self_team":
        return [me.leader] + list(me.characters)
    if target_spec == "one_self_team_any":
        # 自分のリーダー or キャラ 1 枚 (power 高い順、 human は modal で選択)。
        # 公式: 「自分のリーダーかキャラ1枚まで」 用。 OP11-119 コビー 等。
        cands = [me.leader] + list(me.characters)
        if outer_kind and _maybe_request_target_pick(
            state, cands, 1, outer_kind, outer_value, self_inplay,
            description="自リーダー or キャラ から 1 枚 選択",
        ):
            return []
        cands.sort(key=lambda ip: -ip.power)
        return cands[:1]

    # --- パラメトリック target (regex マッチ) ---
    if isinstance(target_spec, str):
        # one_opponent_character_cost_le_N (1 体、 実害評価 高い順)
        # `any_` infix は冗長 alias (= 「相手のコストN以下のキャラ」)。 既存 overlay 多数が
        # one_opponent_character_any_cost_le_N で書いており、 これを許容しないと silent no-op
        # (= KO/bounce 不発) になる bug があった (OP01-070/OP06-043/OP05-045 等 ~15 base)。
        m = re.match(r"one_opponent_character_(?:any_)?cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if _cost_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -_opp_value(c))
            return cands[:1]
        # all_chara_either_cost_le_N (両陣営すべて、 元々コスト)。
        # 「コストN以下のキャラすべて(両陣営)を、 持ち主のデッキの下に置く」 (OP05-058 等)。
        m = re.match(r"all_chara_either_cost_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in (list(opp.characters) + list(me.characters)) if _cost_of(c) <= n]
        # one_character_either(_except_self)_cost_le_N (両陣営 1 体、 元々コスト)。
        # 公式 「コストN以下のキャラ1枚まで(両陣営)、 持ち主の手札/デッキの下に戻す」
        # (OP10-046/OP07-040/OP03-122/OP05-051/P-030/OP12-054 等)。 AI は相手キャラ優先
        # (= 除去価値)、 human は modal で両陣営から選ぶ。
        # ⚠ overlay には `one_inplay_cost_le_N` 表記も存在する (OP02-062 等 4 箇所)。
        # 未処理だと 0 対象で silent no-op (= 効果が丸ごと不発) だったので同 semantics で受ける
        # (2026-08-02。 「コストN以下のキャラ1枚」 = 両陣営、 AI は相手優先)。
        m = (
            re.match(r"one_character_either(_except_self)?_(?:any_)?cost_le_(\d+)(?:cost)?$",
                     target_spec)
            or re.match(r"one_inplay(_except_self)?_cost_le_(\d+)(?:cost)?$", target_spec)
        )
        if m:
            except_self = bool(m.group(1))
            n = int(m.group(2))
            opp_cands = [c for c in opp.characters if _cost_of(c) <= n]
            self_cands = [c for c in me.characters if _cost_of(c) <= n
                          and not (except_self and self_inplay is not None
                                   and c.instance_id == self_inplay.instance_id)]
            picked = _either_pick_one(
                opp_cands, self_cands, f"両陣営のキャラ から 1 枚 選択 (コスト≤{n})")
            return [] if picked is None else picked
        # 現在コスト (= base_cost、 cost_minus 反映) 版。 クロコダイル「コスト0」 系 (= leader が
        # cost-10 して 作った コスト0 を 拾う)。 通常の cost_le_N は「元々のコスト」 (card.cost) のまま。
        m = re.match(r"one_opponent_character_current_cost_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.base_cost <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (現在コスト≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -_opp_value(c))
            return cands[:1]

        # any_opponent_character_cost_le_N (全員)
        # OP14-069 ドフラ で `any_opponent_character_le_Ncost` 表記 も 使用 (= 引数順序違い)
        # → 両方 同 semantics で 受け付ける。
        m = (
            re.match(r"any_opponent_character_cost_le_(\d+)(?:cost)?$", target_spec)
            or re.match(r"any_opponent_character_le_(\d+)cost$", target_spec)
        )
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if _cost_of(c) <= n]

        # any_opponent_character_power_le_N (全員、パワー N 以下)
        # set_cannot_attack 等の count 指定と併用 (= EB04-028 アイスタイム
        # 「相手のパワー10000以下のキャラ2枚まで」)。count は呼び出し側で適用。
        m = re.match(r"any_opponent_character_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if _power_of(c) <= n]

        # one_opponent_rested_character_cost_le_N (レスト + コスト N 以下、1 体)
        m = re.match(r"one_opponent_rested_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.rested and _cost_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手レストキャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -_opp_value(c))
            return cands[:1]

        # one_opponent_character_power_le_N (パワー N 以下、1 体)
        m = re.match(r"one_opponent_character_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if _power_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (パワー≤{n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # one_character_either_power_eq_N (両陣営、 パワー N ぴったり、 1 体)。
        # 公式 「元々のパワー N のキャラ1枚まで」 (= 修飾なし → 両陣営)。 EB03-027 マーガレット等。
        m = re.match(r"one_character_either_power_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            picked = _either_pick_one(
                [c for c in opp.characters if _power_of(c) == n],
                [c for c in me.characters if _power_of(c) == n],
                f"両陣営のキャラ から 1 枚 選択 (元々のパワー={n})",
            )
            return [] if picked is None else picked
        # one_character_either_cost_eq_N (両陣営、 コスト N ぴったり、 1 体)。
        # 素の 「コストN の」 は現在コスト、 「元々のコストN の」 は spec 名の
        # `_truly_original_cost_` で入口正規化されて印刷コストになる (= _cost_of)。
        m = re.match(r"one_character_either_cost_eq_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            picked = _either_pick_one(
                [c for c in opp.characters if _cost_of(c) == n],
                [c for c in me.characters if _cost_of(c) == n],
                f"両陣営のキャラ から 1 枚 選択 (コスト={n})",
            )
            return [] if picked is None else picked
        # one_opponent_character_power_eq_N (パワー N ぴったり、 1 体)。
        # 公式「元々のパワー N」 用 (= CardDef.power で判定)。
        m = re.match(r"one_opponent_character_power_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if _power_of(c) == n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (元々のパワー={n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # one_opponent_character_attached_don_ge_N (= 相手のドン N 枚以上付与キャラ、 1 体)
        # OP15-001 等
        m = re.match(r"one_opponent_character_attached_don_ge_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.attached_dons >= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (付与ドン≥{n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # one_self_character_cost_le_N (= 自分のキャラ コスト N 以下、 1 体, power 最大)
        m = re.match(r"one_self_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in me.characters if _cost_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_self_chara_no_on_play_cost_le_N (= 自分のキャラ コスト N 以下 で 【登場時】 効果を
        # 「持たない」 もの、 1 体)。 PRB01-001 サンジ 等 「自分のコスト8以下の【登場時】効果を持たないキャラ1枚」。
        # state.effects_overlay の bundle を参照し、 when=="on_play" を持たないものをフィルタ。
        m = re.match(r"one_self_chara_no_on_play_cost_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            overlay = state.effects_overlay or {}

            def _has_on_play(card):
                bundle = overlay.get(card.card_id)
                if bundle is None:
                    return False
                return any(e.get("when") == "on_play" for e in bundle.effects)

            cands = [
                c for c in me.characters
                if _cost_of(c) <= n and not _has_on_play(c.card)
            ]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 (コスト≤{n}, 登場時効果なし)",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_opponent_rested_character_power_le_N (レスト + パワー N 以下)
        m = re.match(r"one_opponent_rested_character_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.rested and _power_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手レストキャラ から 1 枚 選択 (パワー≤{n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # one_opponent_character_cost_eq_N / cost_0 等 (= ぴったり N コスト)
        m = re.match(r"one_opponent_character_cost_(?:eq_)?(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if _cost_of(c) == n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (コスト={n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # all_opponent_rested_characters_le_Ncost
        m = re.match(r"all_opponent_rested_characters_le_(\d+)cost$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if c.rested and _cost_of(c) <= n]

        # one_self_character_le_Ncost (= 自分の cost N 以下キャラ 1 枚、 パワー高い順)
        m = re.match(r"one_self_character_le_(\d+)cost$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in me.characters if _cost_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_self_character_cost_eq_N (= 自分の cost N ぴったりキャラ 1 枚)
        m = re.match(r"one_self_character_cost_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in me.characters if _cost_of(c) == n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 (コスト={n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # any_opp_inplay_n_N (= 相手のリーダーかキャラ 合計 N 枚まで)
        # 脅威優先: パワー高いキャラ N 体 (キャラが N 未満なら リーダーも追加)
        m = re.match(r"any_opp_inplay_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [opp.leader] + list(opp.characters)
            if outer_kind and len(cands) > n and _maybe_request_target_pick(
                state, cands, n, outer_kind, outer_value, self_inplay,
                description=f"相手リーダー or キャラ から {n} 枚 まで 選択",
            ):
                return []
            # AI: chara 優先、 N 体未満ならリーダー補充
            sorted_chara = sorted(opp.characters, key=lambda c: -c.power)
            if len(sorted_chara) < n:
                sorted_chara = list(sorted_chara) + [opp.leader]
            return sorted_chara[:n]

        # any_opp_rested_chara_cost_le_C_n_N (= 相手のレストのコスト C 以下のキャラ N 体まで)
        m = re.match(r"any_opp_rested_chara_cost_le_(\d+)_n_(\d+)$", target_spec)
        if m:
            cost_cap = int(m.group(1))
            n = int(m.group(2))
            cands = [c for c in opp.characters if c.rested and _cost_of(c) <= cost_cap]
            if outer_kind and len(cands) > n and _maybe_request_target_pick(
                state, cands, n, outer_kind, outer_value, self_inplay,
                description=f"相手レストキャラ(コスト{cost_cap}以下) から {n} 枚 まで 選択",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:n]

        # any_opp_rested_chara_n_N (= 相手のレストのキャラ N 体まで)
        m = re.match(r"any_opp_rested_chara_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.rested]
            if outer_kind and len(cands) > n and _maybe_request_target_pick(
                state, cands, n, outer_kind, outer_value, self_inplay,
                description=f"相手レストキャラ から {n} 枚 まで 選択",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:n]

        # any_opp_rested_chara_or_stage_n_N (= 相手のレストの キャラ か ステージ 合計 N 枚 まで、
        # OP14-021 イッショウ)。 キャラ + レストステージ を候補に (AI は threat 優先 = キャラ先)。
        m = re.match(r"any_opp_rested_chara_or_stage_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands: list[InPlay] = [c for c in opp.characters if c.rested]
            cands.extend([s for s in opp.stages if s.rested])
            if outer_kind and len(cands) > n and _maybe_request_target_pick(
                state, cands, n, outer_kind, outer_value, self_inplay,
                description=f"相手レスト キャラ/ステージ から {n} 枚 まで 選択",
            ):
                return []
            cands.sort(key=_threat_key)
            return cands[:n]

        # any_opp_rested_inplay_n_N (= 相手のレスト の リーダー と キャラ 合計 N 枚 まで)
        m = re.match(r"any_opp_rested_inplay_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands: list[InPlay] = []
            if opp.leader.rested:
                cands.append(opp.leader)
            cands.extend([c for c in opp.characters if c.rested])
            if outer_kind and len(cands) > n and _maybe_request_target_pick(
                state, cands, n, outer_kind, outer_value, self_inplay,
                description=f"相手レスト リーダー/キャラ から {n} 枚 まで 選択",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:n]

        # one_opponent_character_filtered_by_truly_power_le_N (= 元々のパワー N 以下、 1 体)
        # OP13-077 等 「相手の元々のパワー N 以下のキャラ 1 枚」。
        m = re.match(r"one_opponent_character_filtered_by_truly_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.card.power <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (元々のパワー≤{n})",
            ):
                return []
            cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
            return cands[:1]

        # one_self_character_named_X / one_self_chara_named_X (名前一致セレクタ。 X は 「エネル」 等)
        # chara / character 両表記 を 救済 (= 1 overlay 使用 のため alias)。
        m = re.match(r"one_self_(?:character|chara)_named_(.+)$", target_spec)
        if m:
            target_name = m.group(1)
            cands = [c for c in me.characters if name_matches(c.card, target_name)]
            if outer_kind and len(cands) > 1 and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 ({target_name})",
            ):
                return []
            return cands[:1]

        # all_self_characters_named_X (名前一致全員)
        m = re.match(r"all_self_characters_named_(.+)$", target_spec)
        if m:
            target_name = m.group(1)
            return [c for c in me.characters if name_matches(c.card, target_name)]

        # one_self_character_feature_X (= 自分の特徴 X を持つキャラ 1 体、 power 高い順)
        # OP11-031 ジンベエ系。
        m = re.match(r"one_self_character_feature_(.+)$", target_spec)
        if m:
            feat = m.group(1)
            cands = [c for c in me.characters if feat in c.card.features]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自キャラ から 1 枚 選択 (特徴《{feat}》)",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # all_self_characters_feature_X (= 自分の特徴 X を持つキャラ 全員)
        m = re.match(r"all_self_characters_feature_(.+)$", target_spec)
        if m:
            feat = m.group(1)
            return [c for c in me.characters if feat in c.card.features]

        # one_self_inplay_feature_X (= 自分のリーダーかキャラ 特徴 X を持つ 1 体)
        # OP14-114 ラン 等。
        m = re.match(r"one_self_inplay_feature_(.+)$", target_spec)
        if m:
            feat = m.group(1)
            cands = [me.leader] + list(me.characters)
            cands = [c for c in cands if feat in c.card.features]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"自リーダー or キャラ から 1 枚 選択 (特徴《{feat}》)",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # all_self_inplay_feature_X (= 自分のリーダーかキャラ 特徴 X を持つ 全員)
        m = re.match(r"all_self_inplay_feature_(.+)$", target_spec)
        if m:
            feat = m.group(1)
            cands = [me.leader] + list(me.characters)
            return [c for c in cands if feat in c.card.features]

        # one_opponent_inplay_cost_le_N (= 相手のリーダーかコスト N 以下のキャラ 1 体)
        # 脅威優先: パワー高いキャラ → なければリーダー
        m = re.match(r"one_opponent_inplay_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [opp.leader] + [c for c in opp.characters if _cost_of(c) <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手リーダー or キャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            sorted_chara = sorted(
                [c for c in opp.characters if _cost_of(c) <= n],
                key=lambda c: -c.power,
            )
            if sorted_chara:
                return sorted_chara[:1]
            return [opp.leader]

        # one_self_character_any (= 自分の任意 1 体、 パワー高い順)
        if target_spec == "one_self_character_any":
            cands = list(me.characters)
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # other_self_chara (= self 以外の自キャラ 1 体)
        if target_spec == "other_self_chara":
            cands = [c for c in me.characters if c is not self_inplay]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自キャラ から 1 枚 選択 (このキャラ以外)",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # self_inplay_choice (= 自リーダーまたはキャラ 1 体、 リーダー優先)
        if target_spec == "self_inplay_choice":
            cands = [me.leader] + list(me.characters)
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自リーダー or キャラ から 1 枚 選択",
            ):
                return []
            return [me.leader]

    return []


# --------------------------------------------------------------------------- #
# 効果実行
# --------------------------------------------------------------------------- #
def _audit_snapshot(state: "GameState") -> dict:
    """Phase 2 effect_event log 用 の 軽量 state snapshot (= 比較用 集計値)。"""
    out = {}
    for i, p in enumerate(state.players):
        out[f"P{i}"] = {
            "hand": len(p.hand),
            "deck": len(p.deck),
            "life": len(p.life),
            "trash": len(p.trash),
            "characters": len(p.characters),
            "don_active": p.don_active,
            "don_rested": p.don_rested,
            "leader_rested": p.leader.rested if p.leader else None,
            "leader_power": p.leader.power if p.leader else None,
        }
    return out


def execute_effect(
    spec: EffectSpec,
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay] = None,
) -> bool:
    """単一の効果(`do` 配列の1要素)を実行。

    戻り値: 効果が「解決された」(True) / 解決不能だった (False)。
    公式 4-10 「場合」前文不実行 → 後文不実行 のために使う。
    解決不能の典型例: ko 対象が 0 枚だった、search 対象が見つからない 等。
    現実装ではすべて True 返却 (= 単純実装)。要拡張時に各プリミティブで判定可。

    Phase 2 audit hook (= 2026-05-28、 ONEPIECE_AUDIT_INVARIANTS=1 で 有効化):
      entry/exit で snapshot を 取り、 (card_id, primitive, before, after) を
      state.effect_events に 蓄積。 default off で zero overhead。
    """
    # Phase 2 audit hook (= entry)
    _audit_on = os.environ.get("ONEPIECE_AUDIT_INVARIANTS", "0") in ("1", "true", "True")
    _event = None
    # ⭐ 軽量な効果発動ログ (常時 ON、 2026-07-24)。 従来は audit モード時のみ、 しかも前後の
    # 全盤面スナップショット付きで重かったため既定 OFF = corpus の effect 履歴が常に空だった。
    # 「相手はこの試合で何回効果を使ったか」「直前に何が起きたか」は人間が当然使う情報。
    # tuple 1 個 (turn, actor, primitive, source) に抑え、 直近 60 件 + 通算カウンタで保持
    # (= fast_clone の複製コストを一定に保つ)。
    try:
        _prim = next(iter(spec.keys())) if spec else "_empty"
        _log = getattr(state, "_effect_events", None)
        if _log is None:
            _log = state._effect_events = []
        _log.append((getattr(state, "turn_number", 0),
                     state.players.index(me) if me in state.players else -1,
                     _prim,
                     self_inplay.card.card_id if self_inplay else None))
        if len(_log) > 60:
            del _log[:-60]
        state._effect_events_n = int(getattr(state, "_effect_events_n", 0)) + 1
        _by = getattr(state, "_effect_events_by", None)
        if _by is None:
            _by = state._effect_events_by = [0, 0]
        _ai = state.players.index(me) if me in state.players else -1
        if _ai in (0, 1):
            _by[_ai] += 1
    except Exception:
        pass
    if _audit_on:
        primitive_kind = next(iter(spec.keys())) if spec else "_empty"
        _event = {
            "turn": getattr(state, "turn_number", None),
            "phase": getattr(state.phase, "name", None) if getattr(state, "phase", None) else None,
            "source_card_id": self_inplay.card.card_id if self_inplay else None,
            "primitive": primitive_kind,
            "before": _audit_snapshot(state),
        }
        # state に effect_events 用 slot を 確保 (= 初期化、 既存 状態 と 共存)
        if not hasattr(state, "_audit_effect_events"):
            state._audit_effect_events = []

    # actor 文脈の保全: この呼び出しが **新たに** 人間 pending_choice を立てたら、 その actor
    # (= me) の index を stamp する。 解決時 (_resolve_pending_choice_inner 冒頭) が turn_player
    # でなく この actor の zone を操作する (= on_ko 等 非ターンプレイヤーのトリガーで召喚/検索が
    # 相手の hand/trash/deck を触るバグを根絶。 2026-06-05 RuleReferee field-flood が play_from_
    # hand_or_trash で検出、 同根が summon/play_from_trash/play_from_hand に潜在)。 identity 比較で
    # 「この body が立てた新規 choice」 のみ対象 + 既 _actor_idx は尊重 (= 内側 actor 優先)。
    _pc_before = state.pending_choice
    try:
        return _execute_effect_body(spec, state, me, opp, self_inplay)
    finally:
        _pc_after = state.pending_choice
        if (isinstance(_pc_after, dict) and _pc_after is not _pc_before
                and "_actor_idx" not in _pc_after):
            try:
                _pc_after["_actor_idx"] = state.players.index(me)
            except ValueError:
                pass
        if _audit_on and _event is not None:
            _event["after"] = _audit_snapshot(state)
            state._audit_effect_events.append(_event)


def _execute_effect_body(
    spec: EffectSpec,
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay] = None,
) -> bool:
    """execute_effect の 本体 (= audit hook を 外した 純粋 logic)。"""
    for k, v in spec.items():
        if k == "choice_effect":
            # 公式: 「以下から 1 つを選ぶ: ・効果A ・効果B」 等 の 分岐 効果。
            # spec: {"optional": bool, "actor": "self"|"opp", "options": [...]}
            #   actor: 「相手は以下から1つを選ぶ」 系 では "opp"。 既定 "self"。
            # AI: 1 つ目 valid option を 発動 (= 簡略、 actor=opp なら opp 視点 で 1 つ目)。
            # 人間 (= actor=self の とき): pending_choice "option_pick" → user 選択。
            # 人間 (= actor=opp): opp が AI なので AI が 1 つ目 valid を pick。
            spec_val = v if isinstance(v, dict) else {}
            optional = bool(spec_val.get("optional", False))
            actor = spec_val.get("actor", "self")
            options = spec_val.get("options", []) or []
            if not options:
                continue
            # if 条件 が 満たされる option を filter
            valid_options: list[tuple[int, dict]] = []
            for i, opt in enumerate(options):
                cond = opt.get("if") if isinstance(opt, dict) else None
                if cond and not eval_condition(cond, state, me, self_inplay):
                    continue
                valid_options.append((i, opt))
            if not valid_options:
                continue
            # actor=self + 人間 操作中 なら user に 選ばせる
            if actor == "self" and _should_human_pick(state):
                state.pending_choice = {
                    "kind": "option_pick",
                    "optional": optional,
                    "options": [
                        {
                            "idx": i,
                            "label": opt.get("label", f"効果 {i+1}"),
                        }
                        for i, opt in valid_options
                    ],
                    "_full_options": options,
                    "_self_inplay_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: choice_effect 選択 待ち ({len(valid_options)}個 候補, optional={optional})"
                )
                return True
            # AI: 文脈を見て最良の option を選ぶ (2026-07-24、 従来は「1 つ目」= 選んでいなかった)。
            # ⚠ フル sim は不可: effects 実行中に fast_clone すると plan_search →
            # _pick_activate_main → deepcopy 連鎖で hang した実例がある。 局面で「何も起きない」
            # 選択肢を外し、 効果量で並べる軽量スコアにする。
            chosen_idx, chosen_opt = max(
                valid_options, key=lambda io: _option_score(io[1], state, me, opp))
            chosen_do = chosen_opt.get("do", []) if isinstance(chosen_opt, dict) else []
            state.push_log(
                f"  効果: choice_effect [{actor}] → option {chosen_idx} ({chosen_opt.get('label','?')})"
            )
            for sub in chosen_do:
                if isinstance(sub, dict):
                    execute_effect(sub, state, me, opp, self_inplay)
                    if state.pending_choice is not None:
                        return True
            continue
        if k == "draw":
            n = int(v)
            if getattr(me, "block_self_draw_until_turn_end", False):
                # 公式: 「このターン中、 自分の効果でドロー不可」 ペナルティ下では発動しない
                state.push_log(f"  効果: ドロー {n} (このターン中ドロー禁止のため不発)")
                continue
            drawn = me.draw(n)
            # 2026-05-31 fix: card name を log に 出 力 す る と 相 手 view で も 見 え る
            # (= state.log は public)。 count のみ で 隠 ぺ い 情 報 保 護。
            state.push_log(f"  効果: ドロー {n}")
            # do-primitive の draw は 全て ドローフェイズ以外 (= 効果ドロー) なので
            # 「ドローフェイズ以外でカードを引いた時」 トリガー発火 (OP05-053)。
            if drawn and state.effects_overlay:
                trigger_on_self_draw_non_draw_phase(state, me, opp, state.effects_overlay)
        elif k == "draw_per_self_hand_discarded":
            # OP12-040 クザン等: 「捨てた枚数分カードを引く」 動的 N ドロー。
            # state.last_discard_count を読み取る。 trigger_on_self_hand_discarded で設定済み。
            n = int(getattr(state, "last_discard_count", 0))
            if n <= 0:
                return False
            if getattr(me, "block_self_draw_until_turn_end", False):
                state.push_log(f"  効果: 動的ドロー {n} 不発 (ドロー禁止)")
                continue
            drawn = me.draw(n)
            # 2026-05-31 fix: card name 漏 洩 防 止 (= 同 上、 隠 ぺい 情 報 保 護)
            state.push_log(f"  効果: 動的ドロー {n}")
        elif k == "trash_self_hand_random":
            # 公式: 「自分の手札 N 枚を捨てる」 = プレイヤー が 選んで 捨てる
            # (= 公式 ルール 「捨てる」 の 通常 意味。 「ランダム」 表記 なし)。
            # 2026-05-31: 人間 acting + 候補 > N で modal halt → 人間 が pick。
            # AI / 候補 <= N は 旧 「random」 挙動 (= 簡略、 ただし 候補 全部 捨てる ので 影響 軽微)。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            picks_idx = None
            if isinstance(v, dict) and "_picked_hand_idxs" in v:
                picks_idx = list(v["_picked_hand_idxs"])
            if picks_idx is None and _should_human_pick(state) and len(me.hand) > n and n > 0:
                state.pending_choice = {
                    "kind": "self_hand_discard_pick",
                    "primitive_kind": "trash_self_hand_random",
                    "primitive_value": v,
                    "candidates": [
                        {
                            "hand_idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "cost": int(c.cost) if c.cost is not None else 0,
                            "power": int(c.power) if c.power is not None else 0,
                        }
                        for i, c in enumerate(me.hand)
                    ],
                    "limit": n,
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: 自手札 {n} 枚 トラッシュ → 人間 選択 待ち "
                    f"(候補 {len(me.hand)} 枚)"
                )
                return True
            actually_discarded = 0
            if picks_idx is not None:
                # 人間 modal で 選 ば れ た hand index を 使う (= 降順 で pop)
                idxs = sorted(set(int(i) for i in picks_idx if 0 <= int(i) < len(me.hand)),
                              reverse=True)
                for hi in idxs[:n]:
                    me.trash.append(me.hand.pop(hi))
                    actually_discarded += 1
            else:
                # AI / 候補 <= n: 最悪札から捨てる(random だと beam の value 評価が薄まる)。
                for _ in range(n):
                    if not me.hand:
                        break
                    me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
                    actually_discarded += 1
            state.push_log(f"  効果: 自手札 {actually_discarded} 枚 トラッシュ")
            if actually_discarded > 0 and state.effects_overlay:
                trigger_on_self_hand_discarded(
                    state, me, opp, self_inplay, actually_discarded, state.effects_overlay
                )
        elif k == "trash_opp_hand_random":
            # 相手手札からランダム N 枚捨て (公式の「相手の手札から〜捨てさせる」表現)。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            for _ in range(n):
                if not opp.hand:
                    break
                idx = state.rng.randrange(len(opp.hand))
                opp.trash.append(opp.hand.pop(idx))
            state.push_log(f"  効果: 相手手札 {n} 枚 トラッシュ")
        elif k == "opp_hand_to_deck_then_draw":
            # OP06-047 シャーロット・プリン: 「相手は自身の手札すべてをデッキに戻し
            # シャッフルする。 その後、 相手はカード N 枚を引く。」 = 相手の手札リセット
            # (= 手札 >N なら撹乱、 <N なら相手有利だが net で N 枚固定)。
            n = int(v) if not isinstance(v, dict) else int(v.get("draw", 5))
            returned = len(opp.hand)
            opp.deck.extend(opp.hand)
            opp.hand.clear()
            state.rng.shuffle(opp.deck)
            opp.known_bottom_card_ids.clear()
            opp.known_top_card_ids.clear()
            drawn = opp.draw(n)
            state.push_log(
                f"  効果: 相手手札 {returned} 枚 → デッキに戻しシャッフル、 相手 {len(drawn)} 枚 ドロー"
            )
        elif k == "trash_all_self_chara":
            # OP13-082 五老星 等。 公式: 「自分のキャラすべてをトラッシュに置く」。
            # 全 自陣 キャラ を trash へ 移送 + 付与 ドン は レスト で コスト エリア に 戻す
            # (= 公式 6-5-5-4)。 これは ルール 処理 で あり 【KO 時】 は 発火 しない
            # (= 公式 3-7-6-1-1 と 同 趣旨、 「自分 で 主動 的 に 場 を 離れさ せ た」
            # 効果 起点)。 ただし 「自分 の 効果 で 場 を 離れ た」 系 trigger
            # (= trigger_on_self_chara_leave_by_self_effect) は 発火 する。
            removed_any = False
            for chara in list(me.characters):
                me.characters.remove(chara)
                me.trash.append(chara.card)
                if chara.attached_dons > 0:
                    me.don_rested += chara.attached_dons
                removed_any = True
            if removed_any:
                state.push_log(
                    f"  効果: 自分のキャラすべてをトラッシュに置く ({state.players.index(me)} 側)"
                )
                if state.effects_overlay:
                    trigger_on_self_chara_leave_by_self_effect(
                        state, me, opp, state.effects_overlay
                    )
        elif k == "ko_self":
            # このキャラ (発動元=holder) 自身を KO する (OP16-014 マルコ の replace_leave do
            # 「代わりにこのキャラをKO」)。 trigger_on_ko + on_self_chara_ko を発火 (= マルコの
            # 【KO時】蘇生に繋がる)。 付与ドンはレストへ。 self_ko (cost) の DO 版。
            src = self_inplay
            if src is not None:
                vad = int(getattr(src, "attached_dons", 0) or 0)
                removed = False
                if src in me.characters:
                    me.characters.remove(src); removed = True
                elif src in me.stages:
                    me.stages.remove(src); removed = True
                if removed:
                    me.trash.append(src.card)
                    if vad > 0:
                        me.don_rested += vad
                        src.attached_dons = 0
                    state.push_log(f"  効果: {src.card.name} を KO (このキャラ)")
                    if state.effects_overlay:
                        trigger_on_ko(state, me, opp, src.card, state.effects_overlay,
                                      by_opp_effect=False, victim_attached_don=vad)
                        trigger_on_self_chara_ko(state, me, opp, state.effects_overlay,
                                                 victim_card=src.card)
        elif k == "ko":
            targets = _resolve_target(
                v, state, me, opp, self_inplay,
                outer_kind="ko", outer_value=v,
            )
            if not targets:
                return False  # 公式 4-10 「対象 0 枚」= 解決不能
            _ko_any = False
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect:
                        state.push_log(
                            f"  保護効果: {t.card.name} は相手の効果で離れない"
                        )
                        continue
                    if t.ko_per_turn_immune_remaining > 0:
                        t.ko_per_turn_immune_remaining -= 1
                        state.push_log(f"  KO 耐性 (per-turn 残{t.ko_per_turn_immune_remaining+1}→{t.ko_per_turn_immune_remaining}): {t.card.name}")
                        continue
                    if t.ko_immune_until_turn_end or t.static_ko_immune or t.ko_immune_through_opp_turn:
                        state.push_log(f"  KO 耐性: {t.card.name} は効果で KO されない")
                        continue
                    # source-power-scoped KO 耐性 (= OP14-003 カポネ・ベッジ)
                    thr = t.static_ko_immune_from_source_power_le
                    if thr >= 0 and self_inplay is not None:
                        src_power = int(getattr(self_inplay.card, "power", 0) or 0)
                        if src_power <= thr:
                            state.push_log(
                                f"  KO 耐性 (source パワー≤{thr}): {t.card.name} は {self_inplay.card.name}(P={src_power}) の効果でKO不能"
                            )
                            continue
                    # source-attribute-scoped KO 耐性 (= OP11-005「属性(特)を持たないキャラの効果でKOされない」)。
                    req_attr = t.static_ko_immune_from_non_attribute
                    if req_attr and self_inplay is not None:
                        if req_attr not in (self_inplay.card.attribute or ""):
                            state.push_log(
                                f"  KO 耐性 (source 属性≠{req_attr}): {t.card.name} は {self_inplay.card.name} の効果でKO不能"
                            )
                            continue
                    # 置換効果 (KOされる場合、代わりに〜) のチェック
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay, by_opp_effect=True
                    ):
                        continue
                    opp.characters.remove(t)
                    opp.trash.append(t.card)
                    # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: KO {t.card.name}")
                    _ko_any = True
                    if state.effects_overlay:
                        # 効果による KO も【KO時】を発動 (10-2-1-3)
                        # KO 側 から 見ると 「相手 (= me) の効果」 由来 なので by_opp_effect=True
                        trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                        # 「相手のキャラが KO された時」 (= 自分の効果で KO した側)
                        trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                        # 「自分のキャラが KO された時」 (= KO された側の場効果)
                        trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            if _ko_any and state.effects_overlay:
                # 「キャラが自分の効果で場を離れた時」 (OP07-038 ハンコック等)
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "ko_self_chara":
            # 公式: 「自分の (filter) キャラ N 枚を、 KO する」 (= 自軍 KO drawback、 OP04-079 等)。
            # cost 版 (optional_cost_then 内) と異なり do-effect として【KO時】等を発火する。
            # spec: {"filter": {...}, "count": N, "exclude_self": bool}  もしくは short int (=count)。
            spec_val = v if isinstance(v, dict) else {"count": int(v)}
            kc_count = int(spec_val.get("count", 1))
            kc_filt = spec_val.get("filter", {})
            kc_excl = bool(spec_val.get("exclude_self", False))
            cands = [
                c for c in me.characters
                if _matches_filter_ip(c, kc_filt)
                and not (kc_excl and self_inplay is not None
                         and c.instance_id == self_inplay.instance_id)
            ]
            cands.sort(key=_sacrifice_key)  # 価値 (効果) の低い駒から犠牲 + power tie-break
            victims = cands[:kc_count]
            _ksc_any = False
            for t in victims:
                if t not in me.characters:
                    continue
                me.characters.remove(t)
                me.trash.append(t.card)
                if t.attached_dons > 0:
                    me.don_rested += t.attached_dons
                state.push_log(f"  効果: 自キャラKO → {t.card.name}")
                _ksc_any = True
                if state.effects_overlay:
                    # 効果による KO も【KO時】を発動 (10-2-1-3)。 自分の効果なので by_opp_effect=False。
                    trigger_on_ko(state, me, opp, t.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
            if _ksc_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "ko_self_chara_then_pump_leader_per":
            # 「自分の(filter)キャラを任意の枚数KOしてもよい。 KOした1枚につきリーダーをパワー+M」
            # (OP06-095 影の集合地等)。 AI: 全該当をKO → KO数×M でリーダー pump。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            amount = int(spec_val.get("amount", 1000))
            duration = spec_val.get("duration", "turn")
            victims = [c for c in list(me.characters) if _matches_filter_ip(c, filt)]
            ko_count = 0
            for tch in victims:
                if tch not in me.characters:
                    continue
                me.characters.remove(tch)
                me.trash.append(tch.card)
                if tch.attached_dons > 0:
                    me.don_rested += tch.attached_dons
                ko_count += 1
                if state.effects_overlay:
                    trigger_on_ko(state, me, opp, tch.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=tch.attached_dons, victim_effect_negated=_ip_effect_negated(tch))
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
            if ko_count > 0:
                execute_effect({"power_pump": {"target": "self_leader",
                                               "amount": amount * ko_count, "duration": duration}},
                               state, me, opp, self_inplay)
                state.push_log(f"  効果: 自KO{ko_count}枚 → リーダー+{amount*ko_count}")
        elif k == "trash_self_named_hand_or_field":
            # 公式: 「自分の手札か場の「<name>」1枚をトラッシュに置く」 (= OP06-033 方舟ノア コスト)。
            # 場 (stages) 優先 → なければ手札 から、 name 一致 1 枚 を トラッシュ。
            nm = v.get("name") if isinstance(v, dict) else str(v)
            _tn_done = False
            for s in list(me.stages):
                if s.card.name == nm:
                    me.stages.remove(s)
                    me.trash.append(s.card)
                    if s.attached_dons > 0:
                        me.don_rested += s.attached_dons
                    state.push_log(f"  効果: 場の「{nm}」をトラッシュ")
                    _tn_done = True
                    break
            if not _tn_done:
                for i, c in enumerate(me.hand):
                    if c.name == nm:
                        me.trash.append(me.hand.pop(i))
                        state.push_log(f"  効果: 手札の「{nm}」をトラッシュ")
                        break
        elif k == "chara_to_trash":
            # 「相手の…キャラを、 トラッシュに置く」 (= 戦闘以外の非 KO トラッシュ送り)。
            # 公式 (総合 10-2-1 / rules skill §232,507): 「トラッシュに置く」 は KO ではない。
            # → ① KO 耐性 (ko_immune_*/static_ko_immune/per_turn/source-power) を 受けない
            #    ② 【KO時】 (trigger_on_ko/on_opp_chara_ko/on_self_chara_ko) を 発動しない。
            # 一方、 場を離れる事象なので: protect_from_opp_effect (= 効果で離れない) は 尊重し、
            # 置換効果 (try_replace_ko, leave_kind="chara_to_trash") と
            # 「自分の効果で場を離れた時」 トリガーは 発火する。 構造は return_to_deck_bottom と同型
            # (= 非 KO leave) で、 行き先のみ trash。
            targets = _resolve_target(
                v, state, me, opp, self_inplay,
                outer_kind="chara_to_trash", outer_value=v,
            )
            if not targets:
                return False  # 対象 0 枚 = 解決不能
            _ctt_any = False
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect:
                        state.push_log(f"  保護効果: {t.card.name} は相手の効果で離れない")
                        continue
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay,
                        by_opp_effect=True, leave_kind="chara_to_trash",
                    ):
                        continue
                    opp.characters.remove(t)
                    opp.trash.append(t.card)
                    if t.attached_dons > 0:  # 6-5-5-4: 付与ドンはレストでコストエリアへ
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} をトラッシュへ (非KO)")
                    _ctt_any = True
                elif t in me.characters:
                    me.characters.remove(t)
                    me.trash.append(t.card)
                    if t.attached_dons > 0:
                        me.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} を自トラッシュへ (非KO)")
                    _ctt_any = True
            if _ctt_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "power_pump":
            # {"target": "self", "amount": 2000, "duration": "turn"|"static",
            #  "feature": "麦わらの一味" (特徴フィルタ),
            #  "amount_per": {"source": "self_don_rest", "multiplier": 1000, "divisor": 3}
            #     (動的計算: 自分のレストドン3枚毎に+1000)}
            target_spec = v.get("target", "self")
            duration = v.get("duration", "turn")
            feature_filter = v.get("feature")

            # 動的計算 (amount_per): source 値 × multiplier // divisor
            amount = int(v.get("amount", 0))
            amount_per = v.get("amount_per")
            if amount_per:
                src = amount_per.get("source", "")
                mult = int(amount_per.get("multiplier", 1000))
                divisor = max(1, int(amount_per.get("divisor", 1)))
                src_val = 0
                if src == "self_don_rest":
                    src_val = me.don_rested
                elif src == "self_don_active":
                    src_val = me.don_active
                elif src == "self_don_total":
                    src_val = me.don_active + me.don_rested + me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
                elif src == "self_field_count":
                    src_val = len(me.characters)
                elif src == "self_hand_count":
                    # 「自分の手札1枚につき パワー+N」 (= OP01-072 スマイリー 等)。
                    src_val = len(me.hand)
                elif src == "self_trash_count":
                    src_val = len(me.trash)
                elif src == "self_trash_event_count":
                    src_val = sum(1 for c in me.trash if c.category == Category.EVENT)
                elif src == "self_trash_chara_count":
                    src_val = sum(1 for c in me.trash if c.category == Category.CHARACTER)
                elif src == "self_chara_feature_count":
                    feat = amount_per.get("feature", "")
                    src_val = sum(1 for c in me.characters if feat in c.card.features)
                elif src == "self_distinct_chara_name_count":
                    # 自分のキャラの「カード名の異なる」 数 (= OP16-034 ルフィ
                    # 「自分のカード名の異なるキャラ1枚につき、 このキャラのパワー+1000」)。
                    src_val = len({c.card.name for c in me.characters})
                elif src == "opp_don_total":
                    src_val = opp.don_active + opp.don_rested + opp.leader.attached_dons + sum(c.attached_dons for c in opp.characters)
                amount += (src_val // divisor) * mult

            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="power_pump", outer_value=v,
            )
            if state.pending_choice is not None:
                # 人間 target pick 待ち → halt。 この check が 無いと +N が [] に 適用 され、
                # 後続 do (= 「その後」 の -N 等) が pending_choice を 上書き して friendly
                # pump が 喪失 する (= 温度レアァストライク ST29-015 等、 「自分のリーダーか
                # キャラ1枚まで+N。 その後、 相手…-N」 系 counter の bug)。 power_pump_multi と
                # 同様に halt → run_do_array が 残り do を _continuation 退避 → pick 解決後 再実行。
                return True
            if feature_filter:
                targets = [
                    t for t in targets
                    if feature_filter in t.card.features
                ]
            for t in targets:
                if duration == "static":
                    t.static_buff += amount
                elif duration == "battle":
                    t.battle_buff += amount
                elif duration == "next_self_turn_start":
                    # 「次の自分のターン開始時まで」 = ターン跨ぎ。 REFRESH 時に clear
                    t.next_turn_buff += amount
                elif duration in ("next_opp_turn_end", "next_opp_end_phase"):
                    # 「次の相手のターン (= エンドフェイズ) 終了時まで」
                    # applier-tracking で _reset_turn_buff にてクリア。
                    me_idx = state.players.index(me)
                    t.next_opp_turn_end_buff += amount
                    t.next_opp_turn_end_applier_idx = me_idx
                    t.next_opp_turn_end_applied_turn = state.turn_number
                elif duration == "next_self_turn_end":
                    # 「次の自分のターン終了時まで」 = applier の次の自身ターン終了
                    me_idx = state.players.index(me)
                    t.next_self_turn_end_buff += amount
                    t.next_self_turn_end_applier_idx = me_idx
                    t.next_self_turn_end_applied_turn = state.turn_number
                else:
                    t.turn_buff += amount
            # soshite (= 「その後、 そのカードを〜」) 用に直近 pump 対象を記録。
            # 「リーダーかキャラ1枚+N。 その後、 そのカードを+M」 (OP07-095/OP11-059 等) で
            # target=self_just_buffed が この iid を参照する。
            # ⚠ 対象 0 のときは **None で clear** する。 clear しないと前の action で pump した
            #   カードの iid が残り、 「その後、 選んだキャラは〜」 が **選んでいないカード**に
            #   適用される (EB02-021 ゴムゴムの巨人の銃 が 対象 0 なのにリーダーを
            #   stay_rested_next_refresh にしていた、 2026-08-03 全カード差分掃引で発覚)。
            #   公式も 「選んだキャラ」 = この効果で選んだもの なので 0 なら不発が正。
            state.last_pumped_iid = targets[0].instance_id if targets else None
            # 静的効果 (= on_attached_don) は evaluate_static_effects で
            # 毎回 リセット → 再加算されるためログ noise になる。 値は正常 (= +amount 一定)。
            if duration != "static":
                state.push_log(f"  効果: パワー{amount:+d} → {[t.card.name for t in targets]}")
        elif k == "power_pump_multi":
            # 「自分のキャラ N 枚 まで を、 このターン中、 パワー+M」 等。
            # spec: {target_specs: [...], amount: M, duration: "turn"|"next_opp_turn_end"}
            # 同 target を 二重 pump しない よう dedup。
            #
            # 動的 target 数 (count_source): 対象数 N を場の状況から算出し、 同一
            # target_spec を N 回 並べる。 公式 「自分の場の特徴《F》を持つカード1枚に
            # つき、 相手のキャラ1枚までを、 パワー-M」 (= ST31-004 ルフィ) 用。
            #   spec: {"count_target": "one_opponent_character_any",
            #          "count_source": "self_field_feature_count", "feature": "麦わらの一味",
            #          "amount": -1000, "duration": "turn"}
            #   count_source:
            #     - self_field_feature_count: 自分の場 (リーダー+キャラ+ステージ) の
            #       特徴《feature》を持つカード数 (公式「自分の場の…カード」)。
            #     - self_chara_feature_count: 自分のキャラのみ で 特徴《feature》を持つ数。
            if not isinstance(v, dict):
                continue
            target_specs = v.get("target_specs", [])
            amount = int(v.get("amount", 0))
            duration = v.get("duration", "turn")
            count_source = v.get("count_source")
            if count_source:
                feat = v.get("feature", "")
                if count_source == "self_field_feature_count":
                    field = [me.leader, *me.characters, *me.stages]
                    n_targets = sum(1 for ip in field if feat in ip.card.features)
                elif count_source == "self_chara_feature_count":
                    n_targets = sum(1 for c in me.characters if feat in c.card.features)
                else:
                    n_targets = 0
                ct = v.get("count_target", "one_opponent_character_any")
                target_specs = [ct for _ in range(n_targets)]
            if not isinstance(target_specs, list):
                continue
            already = set()
            for spec in target_specs:
                target_spec = spec if isinstance(spec, str) else (spec or {}).get("target", "self")
                # 人間 target_pick 解決時、 outer_value が power_pump 再実行の spec になる
                # (= _resolve_pending_choice_inner が {primitive_kind: outer_value+_iid_picks} を
                #  execute_effect する)。 amount / duration を載せないと再実行 power_pump が
                #  amount=0 になり debuff/buff が喪失する (ST31-004 ルフィ 等の count_source 系)。
                outer_v = {"target": target_spec, "amount": amount, "duration": duration}
                targets = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="power_pump", outer_value=outer_v,
                )
                if state.pending_choice is not None:
                    return True
                for t in targets:
                    if id(t) in already:
                        continue
                    if duration == "next_opp_turn_end":
                        t.next_opp_turn_end_buff += amount
                        me_idx = state.players.index(me)
                        t.next_opp_turn_end_applier_idx = me_idx
                        t.next_opp_turn_end_applied_turn = state.turn_number
                    else:
                        # 通常 power_pump (turn) と同じく turn_buff を使う。
                        # 旧コードは存在しない power_buff_until_turn_end を参照し
                        # AttributeError (= power_pump_multi turn-duration 全カードで発火) だった。
                        t.turn_buff += amount
                    already.add(id(t))
            state.push_log(
                f"  効果: power+{amount} multi ({duration}) → "
                f"{len(already)} 体"
            )
        elif k == "rest_multi":
            # 「(範囲) のキャラ N 枚 まで を、 レストにする」 (= 公式 OP03-024 等)。
            # spec 2 形式:
            #   - list[target_spec]: 各要素 が rest 対象 spec、 list 長 = 上限 (= 異 cost cap を
            #     並べる 用)。 同 spec を 並べても 1 体しか rest されない (target が deterministic
            #     top を 再選択 し dedup される) ので、 同 cap で N 体 は dict 形式 を 使う。
            #   - {"target": any_*, "count": N}: target を 全 解決 → アクティブ優先で top N 体 rest。
            #     OP10-023「コスト5以下のキャラ2枚まで」 等の「同 cap で N 体」 用。
            if isinstance(v, dict) and "count" in v:
                target_spec = v.get("target", "any_opponent_character_any")
                count = int(v.get("count", 1))
                cands = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="rest", outer_value=target_spec,
                )
                if state.pending_choice is not None:
                    return True
                # アクティブ かつ レスト可能 を 脅威順 (= power 高) に 上限まで
                cands = [t for t in cands if not t.rested and not t.cannot_be_rested_buff and not t.static_cannot_be_rested]
                cands.sort(key=lambda ip: -ip.power)
                for t in cands[:count]:
                    t.rested = True
                    state.push_log(f"  効果: rest {t.card.name}")
                continue
            if not isinstance(v, list):
                continue
            already = set()
            for sub in v:
                # 「相手のキャラかドン」 特殊 spec (= OP06-035 等): _resolve_target は ドン を
                # 解決できない (InPlay でない) ため、 rest primitive と 同じ 分岐で 1 スロット
                # = 相手アクティブキャラ (脅威順) 優先 → 無ければ アクティブドン 1 枚。 dedup は
                # `already` で キャラ側のみ (ドンは don_active 減で 自然に 上限)。
                _is_chara_or_don = (
                    sub == "one_opp_chara_or_don"
                    or (isinstance(sub, dict) and sub.get("type") == "one_opp_chara_or_don")
                )
                if _is_chara_or_don:
                    _cost_le = sub.get("cost_le") if isinstance(sub, dict) else None
                    active_charas = [
                        c for c in opp.characters
                        if not c.rested and not c.cannot_be_rested_buff and not c.static_cannot_be_rested and id(c) not in already
                    ]
                    if _cost_le is not None:
                        active_charas = [
                            c for c in active_charas
                            if int(getattr(c.card, "cost", 0) or 0) <= int(_cost_le)
                        ]
                    active_charas.sort(key=lambda ip: -ip.power)
                    if active_charas:
                        t = active_charas[0]
                        t.rested = True
                        already.add(id(t))
                        state.push_log(f"  効果: レスト → 相手キャラ {t.card.name}")
                    elif opp.don_active > 0:
                        opp.don_active -= 1
                        opp.don_rested += 1
                        state.push_log(f"  効果: レスト → 相手アクティブドン 1 枚")
                    continue
                target_spec = sub if isinstance(sub, str) else (sub or {}).get("target", "one_opponent_character_any")
                targets = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="rest", outer_value=target_spec,
                )
                if state.pending_choice is not None:
                    return True
                for t in targets:
                    if id(t) in already:
                        continue
                    if t.cannot_be_rested_buff or t.static_cannot_be_rested:
                        state.push_log(f"  レスト不能保護: {t.card.name}")
                        continue
                    t.rested = True
                    already.add(id(t))
                    state.push_log(f"  効果: rest {t.card.name}")
        elif k == "rest":
            # 「相手のキャラかドン1枚までを、 レストにする」 用 特殊 target spec。
            # 通常の target spec で相手のドンは表現できないため (ドンは InPlay ではない)、
            # rest primitive 内で one_opp_chara_or_don を分岐処理。
            is_chara_or_don = (
                v == "one_opp_chara_or_don"
                or (isinstance(v, dict) and v.get("type") == "one_opp_chara_or_don")
            )
            if is_chara_or_don:
                # _iid_picks 注入 (= 人間 modal 解決後 の 再実行 path)
                iid_picks = None
                if isinstance(v, dict) and "_iid_picks" in v:
                    iid_picks = v["_iid_picks"]
                active_charas = [c for c in opp.characters if not c.rested and not c.cannot_be_rested_buff and not c.static_cannot_be_rested]
                # cost_le 制約 (= ST26-002 「コスト1以下のキャラかドン1枚」 等)。 dict spec のみ、
                # string form は 後方互換で 無制約のまま。 DON 側は cost 概念なしで常に対象。
                _cost_le = v.get("cost_le") if isinstance(v, dict) else None
                if _cost_le is not None:
                    active_charas = [
                        c for c in active_charas
                        if int(getattr(c.card, "cost", 0) or 0) <= int(_cost_le)
                    ]
                # 人間 acting + active chara 候補あり (= 複数 chara or chara + DON 両方 可能)
                # → chara から 選ばせる modal を 出す。
                # 選ばない (= 空 picks) なら DON 側 へ fallback。
                if iid_picks is None and active_charas and (opp.don_active > 0 or len(active_charas) > 1):
                    if _maybe_request_target_pick(
                        state, active_charas, 1, "rest",
                        {"type": "one_opp_chara_or_don"}, self_inplay,
                        description="相手キャラ から 1 枚 レスト (skip で 相手ドン 1 枚 レスト)",
                    ):
                        return False
                # 解決 path: iid_picks が 与えられ かつ 中身あり → そのキャラ を レスト
                if iid_picks is not None and iid_picks:
                    target = next((c for c in active_charas if c.instance_id in iid_picks), None)
                    if target is not None:
                        target.rested = True
                        state.push_log(f"  効果: レスト → 相手キャラ {target.card.name}")
                        return True
                    # iid mismatch (= 不正 pick) は fallthrough
                # 解決 path: iid_picks が 空 list → DON 側 で 処理 (= human 「キャラ pick せず」)
                if iid_picks is not None and not iid_picks:
                    if opp.don_active > 0:
                        opp.don_active -= 1
                        opp.don_rested += 1
                        state.push_log(f"  効果: レスト → 相手アクティブドン 1 枚")
                        return True
                    state.push_log(f"  効果: レスト → 対象なし (不発)")
                    return False
                # AI 優先順位: 相手アクティブキャラ (最も脅威) > opp.don_active > opp.don_rested
                active_charas.sort(key=lambda ip: -ip.power)
                if active_charas:
                    target = active_charas[0]
                    target.rested = True
                    state.push_log(f"  効果: レスト → 相手キャラ {target.card.name}")
                elif opp.don_active > 0:
                    opp.don_active -= 1
                    opp.don_rested += 1
                    state.push_log(f"  効果: レスト → 相手アクティブドン 1 枚")
                else:
                    state.push_log(f"  効果: レスト → 対象なし (不発)")
                    return False
                return True
            # {"target": T, "count": N} 形式 = 「(範囲)のキャラ N 枚まで を レスト」
            # (OP14-031 ナミ / ST05-011_r1 等)。 plain `rest` に この dict を 渡すと
            # _resolve_target が "type"/str 以外を dispatch できず [] を返し silent no-op
            # だった bug (2026-06-12 発見)。 候補を any_ 形で 全解決 → 人間 pick (up to N) /
            # AI top-N (power) で rest。 _iid_picks 再実行時は 下の汎用 path で 解決する。
            if (
                isinstance(v, dict) and "count" in v and "target" in v
                and "type" not in v and "_iid_picks" not in v
            ):
                rest_count = int(v.get("count", 1))
                inner = v.get("target")
                # one_opponent_character_..._cost_le_N → any_opponent_character_cost_le_N
                # (= 全候補 を 返す 形) に 正規化 (= top-1 でなく 候補全部 から N 枚 選ぶ)。
                cand_target = inner
                if isinstance(inner, str) and inner.startswith("one_opponent_character_"):
                    cand_target = "any_" + inner[len("one_"):]
                cand_list = _resolve_target(cand_target, state, me, opp, self_inplay)
                cand_list = [
                    c for c in cand_list
                    if not c.rested and not c.cannot_be_rested_buff and not c.static_cannot_be_rested
                ]
                if _maybe_request_target_pick(
                    state, cand_list, rest_count, "rest", v, self_inplay,
                    description=f"レスト 対象 {rest_count} 枚 まで を 選択",
                ):
                    return False
                cand_list.sort(key=lambda ip: -ip.power)
                targets = cand_list[:rest_count]
            else:
                targets = _resolve_target(
                    v, state, me, opp, self_inplay,
                    outer_kind="rest", outer_value=v,
                )
            actually_rested = []
            already_rested_skipped: list[str] = []
            # 「相手のキャラの効果で」 判定: effect の source (self_inplay) が CHARACTER。
            by_opp_chara_eff = (
                self_inplay is not None
                and self_inplay.card.category == Category.CHARACTER
            )
            for t in targets:
                # 「レストにできない」 保護 (OP14-033 の buff / OP12-021 の static rest 免疫)
                if t.cannot_be_rested_buff or t.static_cannot_be_rested:
                    state.push_log(f"  レスト不能保護: {t.card.name}")
                    continue
                # 既に rested → 効果が no-op (= 観戦コメント由来: 「リーダー既に rested
                # → trigger 効果使う必要なし」)。 actually_rested に入れず skip 扱い。
                if t.rested:
                    already_rested_skipped.append(t.card.name)
                    continue
                # 置換効果 (replace_rest): 「このキャラがレストになる場合、 代わりに〜」 (PRB02-006 ゾロ等)
                # actor (= me) と victim_owner を確定して置換チェック。
                if t in me.characters or t is me.leader:
                    v_owner, v_actor = me, opp
                elif t in opp.characters or t is opp.leader:
                    v_owner, v_actor = opp, me
                else:
                    v_owner, v_actor = None, None
                if v_owner is not None and state.effects_overlay and try_replace_rest(
                    state, v_owner, v_actor, t, state.effects_overlay, by_opp_chara_eff
                ):
                    continue
                t.rested = True
                actually_rested.append(t)
                # 「このキャラがレストになった時」 trigger (OP14-027 シャンクス等)
                if state.effects_overlay and v_owner is not None:
                    trigger_on_self_rested(state, v_owner, v_actor, t, state.effects_overlay)
                    # 「キャラが自分の効果でレストになった時」 (field-wide、 OP10-036 ペローナ 等)。
                    # actor (= me) 視点で「自分の効果」 由来。
                    # 効果発動者 (= me) と victim_owner が 同陣営の 場合 のみ 発火 (= 「自分の効果で 自陣 キャラを レスト」)。
                    if v_owner is me:
                        _enqueue_field_when(
                            state, me, "on_self_chara_rested_by_self_effect",
                            state.effects_overlay,
                        )
                        _maybe_resolve(state)
            if actually_rested:
                state.push_log(f"  効果: レスト → {[t.card.name for t in actually_rested]}")
            elif already_rested_skipped:
                state.push_log(
                    f"  効果: レスト 不発 (= {already_rested_skipped} は既に rested)"
                )
            else:
                state.push_log(f"  効果: レスト → 対象なし (不発)")
        elif k == "rest_self_cards":
            # 自分のリーダー/キャラから N 枚をレスト。 AI 簡易: アクティブの中から power 低い順。
            # 人間 acting + 候補 > N なら modal で 選ばせる。
            spec_val = v if isinstance(v, dict) else {"count": int(v)}
            n = int(spec_val.get("count", 1))
            iid_picks = spec_val.get("_iid_picks") if isinstance(v, dict) else None
            actives = [me.leader] + list(me.characters)
            actives = [ip for ip in actives if not ip.rested]
            if iid_picks is not None:
                chosen = [ip for ip in actives if ip.instance_id in iid_picks][:n]
            else:
                if len(actives) > n and _maybe_request_target_pick(
                    state, actives, n, "rest_self_cards", v, self_inplay,
                    description=f"自リーダー or キャラ から {n} 枚 を レスト",
                ):
                    return False
                actives.sort(key=lambda ip: ip.power)
                chosen = actives[:n]
            for ip in chosen:
                ip.rested = True
            state.push_log(f"  効果: 自カード{n}枚レスト → {[ip.card.name for ip in chosen]}")
        elif k == "return_to_hand":
            targets = _resolve_target(
                v, state, me, opp, self_inplay,
                outer_kind="return_to_hand", outer_value=v,
            )
            _ret_any = False
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect:
                        state.push_log(
                            f"  保護効果: {t.card.name} は相手の効果で離れない"
                        )
                        continue
                    if t.static_ko_immune:
                        state.push_log(f"  KO 耐性: {t.card.name} は効果で場を離れない")
                        continue
                    # 置換効果: 「相手の効果で場を離れる場合、代わりに〜」(ペローナ等)
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay,
                        by_opp_effect=True, leave_kind="return_to_hand",
                    ):
                        continue
                    opp.characters.remove(t)
                    # Phase 7I: 場 → 手札 は公開経路 (opp に既に見えていた)
                    opp.add_to_hand_publicly(t.card)
                    # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: 手札に戻す {t.card.name}")
                    _ret_any = True
                    # 相手効果による離脱 → victim 側の on_self_chara_leave_by_opp_effect (OP09-080)
                    if state.effects_overlay:
                        trigger_on_self_chara_leave_by_opp_effect(
                            state, opp, me, state.effects_overlay, victim_card=t.card)
                elif t in me.characters:
                    # 両陣営 target (= 「コストN以下のキャラ1枚まで」 自陣も対象) の
                    # 自キャラ bounce。 持ち主 (= me) の手札へ。
                    me.characters.remove(t)
                    me.hand.append(t.card)
                    if t.attached_dons > 0:
                        me.don_rested += t.attached_dons
                    state.push_log(f"  効果: 自キャラを手札に戻す {t.card.name}")
                    _ret_any = True
            # OP13-119 「そうした場合、〜」: 直前 bounce が実際に起きたかを記録 (opp報酬の gate 用)。
            state.last_return_to_hand_success = bool(_ret_any)
            if _ret_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
                trigger_on_opp_chara_returned_to_hand_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "play_event_from_hand":
            # 手札から filter 一致のイベント1枚を 0 コストで発動 (青紫サンジ起動メイン)。
            # 通常の PlayEvent と異なり「コストを払って発動」の代替 (発動本体は overlay の when:"main" を引き起こす)。
            # spec: {"filter": {"feature": "麦わらの一味", "cost_le": 3}}
            # 人間 acting + 候補 > 1 なら modal で 選ばせる。
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            candidates: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.hand)
                if c.category == Category.EVENT and _matches_filter(c, filt)
            ]
            if picks_idx is None and _should_human_pick(state) and len(candidates) > 1:
                cand_list = [
                    {
                        "hand_idx": i,
                        "card_id": c.card_id,
                        "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": 0,
                    }
                    for i, c in candidates
                ]
                state.pending_choice = {
                    "kind": "play_event_from_hand_pick",
                    "primitive_value": v,
                    "candidates": cand_list,
                    "limit": 1,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: イベント発動 候補 {len(candidates)} 枚 → 人間 選択 待ち"
                )
                return True
            # picks 解決 path: 指定 idx を 1 枚 発動
            if picks_idx is not None and picks_idx:
                # 1 枚 のみ 採用 (= limit=1)
                i = picks_idx[0]
                if 0 <= i < len(me.hand):
                    card = me.hand.pop(i)
                    me.trash.append(card)
                    state.push_log(f"  効果: イベント発動 → {card.name}")
                    if state.effects_overlay:
                        trigger_main_event(state, me, opp, card, state.effects_overlay)
                    continue
            # AI: 先頭 一致 を 発動
            for i, card in enumerate(me.hand):
                if card.category != Category.EVENT:
                    continue
                if not _matches_filter(card, filt):
                    continue
                me.hand.pop(i)
                me.trash.append(card)
                state.push_log(f"  効果: イベント発動 → {card.name}")
                if state.effects_overlay:
                    trigger_main_event(state, me, opp, card, state.effects_overlay)
                break
            else:
                state.push_log(f"  効果: イベント発動 (該当なし)")
        elif k == "summon_from_deck":
            # デッキから filter 一致のキャラを 1 枚場に登場 (search の "場へ" 版)。
            # OP11-022 緑黄しらほし起動メイン (海王類/メガロをデッキから登場) 等。
            # spec: {"filter": {...}, "limit": 1, "rested": false, "sickness": true}
            # 公式 search 系 で 「持ち主だけ デッキを 見る」 ので 人間 acting で 候補 > limit
            # なら modal で 選ばせる (= deck 検索 効果 は 隠匿情報 流出 OK の 公式 例外)。
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            sickness = bool(spec.get("sickness", True))
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補 抽出 (deck index + CardDef)
            candidates: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.deck)
                if c.category == Category.CHARACTER and _matches_filter(c, filt)
            ]
            if picks_idx is None and _should_human_pick(state) and len(candidates) > limit:
                cand_list = [
                    {
                        "deck_idx": i,
                        "card_id": c.card_id,
                        "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    }
                    for i, c in candidates
                ]
                state.pending_choice = {
                    "kind": "summon_from_deck_pick",
                    "primitive_value": v,
                    "candidates": cand_list,
                    "limit": limit,
                    "rested": rested,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: デッキ から 登場 候補 {len(candidates)} 枚 → 人間 選択 待ち (= {limit} 枚 まで)"
                )
                return True
            # picks 解決 path
            if picks_idx is not None:
                if not picks_idx:
                    state.push_log("  効果: デッキ 登場 0 枚 選択 (= skip)")
                    # 検索 後 は シャッフル (= 公式 8-7-3-3)
                    state.rng.shuffle(me.deck)
                    me.known_bottom_card_ids.clear()
                    me.known_top_card_ids.clear()
                    return False
                chosen_indexes = sorted(
                    [i for i in picks_idx if 0 <= i < len(me.deck)],
                    reverse=True,
                )
                played_count = 0
                for i in chosen_indexes[:limit]:
                    card = me.deck[i]
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    me.deck.pop(i)
                    ip = InPlay.of(card, rested=rested, sickness=sickness)
                    me.characters.append(ip)
                    played_count += 1
                    state.push_log(f"  効果: デッキから登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                state.rng.shuffle(me.deck)
                me.known_bottom_card_ids.clear()
                me.known_top_card_ids.clear()
                if played_count == 0:
                    return False
                continue
            # AI / 候補 <= limit: 既存 挙動 (= 先頭 から filter 一致 を 登場)
            found = 0
            picked: list[CardDef] = []
            remaining: list[CardDef] = []
            for c in me.deck:
                if (
                    found < limit
                    and c.category == Category.CHARACTER
                    and _matches_filter(c, filt)
                ):
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    ip = InPlay.of(c, rested=rested, sickness=sickness)
                    me.characters.append(ip)
                    picked.append(c)
                    found += 1
                    state.push_log(f"  効果: デッキから登場 → {c.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    remaining.append(c)
            me.deck = remaining
            state.rng.shuffle(me.deck)
            me.known_bottom_card_ids.clear()
            me.known_top_card_ids.clear()
            if not picked:
                state.push_log(f"  効果: デッキ登場 (該当なし)")
        elif k == "search_top_n":
            # 公式: 「自分のデッキの上から N 枚を見て、 (filter) M 枚までを (destination)、
            #       残りを (rest_remain) に置く」
            # spec: {"depth": 5, "filter": {...}, "limit": 1,
            #        "destination": "hand"|"play", "rested": false,
            #        "rest_remain": "bottom"|"top_or_bottom"|"trash"}
            spec_val = v if isinstance(v, dict) else {}
            depth = int(spec_val.get("depth", 5))
            filt = spec_val.get("filter", {})
            limit = int(spec_val.get("limit", 1))
            destination = spec_val.get("destination", "hand")
            rested_flag = bool(spec_val.get("rested", False))
            rest_remain = spec_val.get("rest_remain", "bottom")
            if not me.deck:
                return False
            # 人間 プレイヤー が 「効果の actor (= owner)」 なら、 該当 候補 が 1 枚以上
            # ある or depth>=2 で 確認余地 ある場合 は interactive 選択 を 要求。
            # _should_human_pick は event owner (= forced_human_actor_idx) を 考慮 する
            # ので、 AI-owned chained event 中 は False (= AI の 隠匿 情報 流出 防止)。
            is_human_acting = _should_human_pick(state)
            seen_preview = me.deck[:depth]
            matching = [
                i for i, c in enumerate(seen_preview)
                if _matches_filter(c, filt)
            ]
            # interactive 条件:
            # - 人間 ターン中
            # - 該当 候補 ≥ 1 (= 「選ばない (= skip)」 含めて 人間 が 判断 する 余地 あり)
            # - 「全該当 を 必ず 取らされる」 ケース (= matching == limit && depth==matching)
            #   は 自動 で 良い が、 「seen に matching 以外 が 混じる (= 公開情報 知れる)」
            #   なら 人間 確認価値 あり → 条件 緩和
            if is_human_acting and len(matching) >= 1:
                # 候補 多数 → 人間 に 選ばせる
                state.pending_choice = {
                    "kind": "search_top_n",
                    "cards": [
                        {
                            "idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "matches_filter": i in matching,
                        }
                        for i, c in enumerate(seen_preview)
                    ],
                    "depth": depth,
                    "limit": limit,
                    "destination": destination,
                    "rest_remain": rest_remain,
                    "rested": rested_flag,
                    "filter": filt,
                }
                state.push_log(
                    f"  効果: search_top_n 上{depth}枚 公開 → 人間 選択 待ち"
                    f" ({len(matching)}枚 候補 から {limit}枚)"
                )
                return True
            seen = me.deck[:depth]
            me.deck = me.deck[depth:]
            picked: list[CardDef] = []
            remaining: list[CardDef] = []
            for c in seen:
                if len(picked) < limit and _matches_filter(c, filt):
                    picked.append(c)
                else:
                    remaining.append(c)
            for c in picked:
                if destination == "play":
                    if c.category == Category.STAGE:
                        # STAGE を「登場させる」 (= OP08-100 サウスバード→アッパーヤード)。
                        # game.py:PlayStage / effects.py:6039 と同様、 3-8-5-1 既存ステージ
                        # (MAX 超) は持ち主のトラッシュへ、 stages へ配置 (sickness/rested 無関係)。
                        # 3-8-3: ステージエリアに置くことも「登場」 → 【登場時】発動可。
                        if len(me.stages) >= Player.MAX_STAGES:
                            old = me.stages.pop()
                            me.trash.append(old.card)
                            if old.attached_dons > 0:
                                me.don_rested += old.attached_dons
                            state.push_log(f"  既存ステージ {old.card.name} をトラッシュへ")
                        ip = InPlay.of(c, rested=False, sickness=False)
                        me.stages.append(ip)
                        state.push_log(f"  効果: search_top_n → 登場 {c.name} (ステージ)")
                        if state.effects_overlay:
                            trigger_on_play(state, me, opp, ip, state.effects_overlay)
                        continue
                    if c.category != Category.CHARACTER:
                        # LEADER 等 登場不可 → 手札にもどす (フォールバック)
                        me.hand.append(c)
                        continue
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    ip = InPlay.of(c, rested=rested_flag, sickness=True)
                    me.characters.append(ip)
                    state.push_log(f"  効果: search_top_n → 登場 {c.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                elif destination in ("life", "life_face_up"):
                    # 「ライフの上に加える」 (= OP16-119 ティーチ)。 公式 表記なし は裏向き (life 既定)。
                    # life_face_up = 表向きで加える (= ST13-002)。 count-only モデルで表向き +1。
                    me.life.insert(0, c)
                    if destination == "life_face_up":
                        me.face_up_life_count = min(me.face_up_life_count + 1, len(me.life))
                    state.push_log(
                        f"  効果: search_top_n → ライフ上に加える"
                        f"{'(表向き)' if destination == 'life_face_up' else ''} ({len(me.life)} 枚)")
                elif destination == "trash":
                    # 「〜枚をトラッシュに置く」 (= OP03-083 コルギー等)。 picked を直接 trash へ。
                    me.trash.append(c)
                    state.push_log(f"  効果: search_top_n → トラッシュ")
                else:  # hand
                    # 公式テキストが「公開し、手札に加える」なら相手にカードが割れる
                    # (= known_hand_card_ids に記録)。 「見て」だけの非公開サーチは記録しない
                    # (= 記録すると AI が知り得ない情報を持つチートになる)。 overlay の
                    # public フラグは _text の「公開」有無から機械付与済み。
                    if spec_val.get("public"):
                        me.add_to_hand_publicly(c)
                    else:
                        me.hand.append(c)
                    # 隠 ぺい 情 報: 手 札 入 り は card name を log に 出 さ ない (= 相 手 view 漏 洩 防 止)
                    state.push_log(f"  効果: search_top_n → 手札")
            # 残り処理
            if rest_remain == "trash":
                me.trash.extend(remaining)
                state.push_log(
                    f"  効果: search_top_n 残り{len(remaining)}枚 → トラッシュ"
                )
            elif rest_remain == "top_or_bottom" and remaining:
                # 公式「残りをデッキの上または下に置く」 = **上に置けば次のドローを確定できる**
                # 強力な選択肢。 従来は一律で底に送っていた (= AI 簡易) ため、 ルール上できる
                # ことを engine が捨てていた (2026-07-24、 ohtsuki「全部直して」)。
                # 判断: 今すぐ払えるコストで、 最も価値の高い 1 枚を上に。 残りは底へ。
                best_i, best_v = None, 0.0
                for i, c in enumerate(remaining):
                    try:
                        cost = int(getattr(c, "cost", 0) or 0)
                        if cost > me.don_active + 1:
                            continue      # 次ターンでも払えない札を上に置いても腐る
                        v = float(getattr(c, "power", 0) or 0) / 1000.0 \
                            + float(getattr(c, "counter", 0) or 0) / 1000.0
                        if v > best_v:
                            best_i, best_v = i, v
                    except Exception:
                        continue
                if best_i is not None:
                    top_card = remaining.pop(best_i)
                    me.deck.insert(0, top_card)
                    # 上に置いた札は本人が知っている (= 次のドローが確定)
                    try:
                        me.known_top_card_ids.append(top_card.card_id)
                    except Exception:
                        pass
                    state.push_log("  効果: 残り1枚をデッキの上へ (= 次ドロー確定)")
                me.deck.extend(remaining)
                try:
                    me.known_bottom_card_ids.extend(c.card_id for c in remaining)
                except Exception:
                    pass
            else:
                # bottom 指定 = 底へ
                me.deck.extend(remaining)
                # 見た上で底に送った札 = 内容も位置も本人には判る (= 当分引かない札が確定)
                try:
                    me.known_bottom_card_ids.extend(c.card_id for c in remaining)
                except Exception:
                    pass
            if not picked:
                state.push_log(f"  効果: search_top_n 該当なし")
        elif k == "declare_cost_reveal_then":
            # 公式 「任意のコストを宣言し、 相手のデッキの上から1枚を公開する。 公開したカードが
            # 宣言したコストと同じ場合、 効果X」 (OP11-066/071/073/074/079/081 ビッグ・マム宣言系)。
            # AI: 相手デッキの最頻コストを宣言 (= 命中率最大化)。 公開トップと一致なら effect 発動。
            spec_val = v if isinstance(v, dict) else {}
            effect_specs = spec_val.get("effect", [])
            if not opp.deck:
                state.push_log("  効果: 宣言 (相手デッキ空、 不発)")
                return False
            from collections import Counter as _Counter
            cost_counts = _Counter(c.cost for c in opp.deck)
            # 最頻コスト (tie は 低コスト優先 = 序盤札が多い傾向)
            declared = min(cost_counts, key=lambda c: (-cost_counts[c], c))
            revealed = opp.deck[0]
            state.push_log(f"  効果: コスト{declared}を宣言 → 相手デッキ上公開 {revealed.name}(コスト{revealed.cost})")
            if revealed.cost == declared:
                state.push_log("  効果: 宣言一致！ 効果発動")
                for es in effect_specs:
                    execute_effect(es, state, me, opp, self_inplay)
            else:
                state.push_log("  効果: 宣言不一致 (不発)")
        elif k == "reveal_top_then":
            # R4: 公式 「自分のデッキの上から N 枚を公開し、 (filter 条件) の場合、 効果X」 ;
            #       その後、 公開したカードを デッキの (上/下/トラッシュ) に置く。
            # ST22-016 / ST22-012 / ST17-001 / EB01-029 等 (5+ 枚)。
            # spec: {"depth": 1, "filter": {...},
            #        "then": [<do_spec>...],
            #        "else": [<do_spec>...]  (optional),
            #        "rest_remain": "bottom"|"top"|"trash"  (default bottom)}
            # 条件は depth=1 のとき公開 1 枚が filter にマッチすれば then を発動。
            # depth>1 なら 1 枚でも マッチ で then 発動 (= 公式 「~の場合」 個別条件)。
            spec_val = v if isinstance(v, dict) else {}
            depth = int(spec_val.get("depth", 1))
            filt = spec_val.get("filter", {})
            then_specs = spec_val.get("then", [])
            else_specs = spec_val.get("else", [])
            rest_remain = spec_val.get("rest_remain", "bottom")
            # 「(条件)の場合、…。その後、公開したカードをデッキの下に置く」= 「デッキの下に置く」が
            # 条件節の中に入っているカード用。 条件不成立時は公開カードを別の場所 (通常はデッキの上へ
            # 裏向きで戻す = 動かさない) に戻す。 EB01-029 わりいおれ死んだ: cardqa_eb_01 「公開した
            # カードのコストが3以下だった場合、…デッキの上に裏向きで戻します」。 未指定なら rest_remain。
            rest_remain_unmatched = spec_val.get("rest_remain_unmatched", rest_remain)
            if not me.deck:
                state.push_log(f"  効果: reveal_top_then デッキ空 (不発)")
                return False
            revealed_cards = me.deck[:depth]
            me.deck = me.deck[depth:]
            matched = any(_matches_filter(c, filt) for c in revealed_cards)
            state.push_log(
                f"  効果: デッキ上 {depth} 枚公開 → {[c.name for c in revealed_cards]} "
                f"(マッチ={matched})"
            )
            if matched:
                for spec in then_specs:
                    execute_effect(spec, state, me, opp, self_inplay)
            else:
                for spec in else_specs:
                    execute_effect(spec, state, me, opp, self_inplay)
            # 公開済カードを rest_remain (マッチ時) / rest_remain_unmatched (非マッチ時) へ
            rest_remain = rest_remain if matched else rest_remain_unmatched
            if rest_remain == "top":
                # 公開順を保持して 上へ戻す (公式: 「~好きな順」 は AI 簡易で revealed 順)
                me.deck = list(revealed_cards) + me.deck
            elif rest_remain == "trash":
                me.trash.extend(revealed_cards)
            else:
                # bottom (default)
                me.deck.extend(revealed_cards)
        elif k == "reveal_top_play":
            # 公式: 「デッキの一番上を公開し、 (条件) の場合、 登場させてもよい。 残りをデッキの下/上下に置く」
            # spec: {"filter": {...}, "rested": false, "rest_remain": "bottom"|"top_or_bottom"|"top"}
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            rested_flag = bool(spec_val.get("rested", False))
            rest_remain = spec_val.get("rest_remain", "bottom")
            if not me.deck:
                return False
            revealed = me.deck.pop(0)
            matched = (
                revealed.category == Category.CHARACTER
                and _matches_filter(revealed, filt)
            )
            state.push_log(
                f"  効果: デッキ上1枚公開 → {revealed.name} ({'マッチ' if matched else '不マッチ'})"
            )
            # 人間 操作中 + マッチ なら user に「登場 / skip」 を 委ねる
            if matched and _should_human_pick(state):
                state.pending_choice = {
                    "kind": "reveal_top_play_confirm",
                    "card": {
                        "card_id": revealed.card_id,
                        "name": revealed.name,
                        "cost": int(getattr(revealed, "cost", 0) or 0),
                        "power": int(getattr(revealed, "power", 0) or 0),
                    },
                    "rested": rested_flag,
                    "rest_remain": rest_remain,
                    "description": f"{revealed.name} を 登場 させますか?",
                }
                state.push_log(
                    f"  効果: reveal_top_play 登場 選択 待ち ({revealed.name})"
                )
                # revealed は pending_choice 解決 まで 仮預かり (= state.pending_choice に 残し)
                state.pending_choice["_revealed_card_id"] = revealed.card_id
                # revealed を deck から 既に pop しているので restoration 用に保存
                state.pending_choice["_revealed_index"] = 0
                state.pending_choice["_revealed_card"] = revealed
                return True
            if matched:
                # AI 簡易: マッチなら必ず登場 (公式テキストでは任意だが期待値プラス)
                if not me.can_play_character():
                    me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                ip = InPlay.of(revealed, rested=rested_flag, sickness=True)
                me.characters.append(ip)
                # 「登場させた場合、 そのキャラは 【keyword】 を得る」 (= OP12-058 速攻)。
                pk = spec_val.get("played_keyword")
                if pk:
                    ip.granted_keywords.add(str(pk))
                    state.push_log(f"  効果: 登場キャラに【{pk}】付与 → {revealed.name}")
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, ip, state.effects_overlay)
            else:
                # マッチしなければ rest_remain に従ってデッキへ戻す
                # AI 簡易: top_or_bottom は底に固定 (上下選択の判断は後追い)
                if rest_remain == "top":
                    me.deck.insert(0, revealed)
                else:
                    me.deck.append(revealed)
        elif k == "search":
            # {"filter": {"category": "CHARACTER", "cost_le": 4}, "limit": 1}
            # 公式: 「自分のデッキから (filter) のカード N 枚 まで を 探し、 手札 に
            # 加える。 その後 デッキ を シャッフル する」。 候補 が 限度 を 超える 場合、
            # プレイヤー が 任意 で 選ぶ (= 公式 ルール 「探す」 の 基本 挙動)。
            # 2026-05-31 fix: 人間 操作 中 + 候補 > limit なら pending_choice
            # "search_pick" を 立てて 待機。 AI / 候補 ≤ limit は 旧 自動 pick。
            filt = v.get("filter", {})
            limit = int(v.get("limit", 1))
            # 既 resolved picks (= resolve_pending_choice 経由) bypass
            picks_idx = v.get("_picked_deck_idxs")
            # 解決前 = 全 deck から filter マッチ idx を 列挙
            matching_idxs = [i for i, c in enumerate(me.deck) if _matches_filter(c, filt)]
            if picks_idx is None and _should_human_pick(state) and len(matching_idxs) > limit:
                # 人間 + 候補 多数 → 選択 modal halt
                state.pending_choice = {
                    "kind": "search_pick",
                    "primitive_kind": "search",
                    "primitive_value": v,
                    "candidates": [
                        {
                            "idx": i,
                            "card_id": me.deck[i].card_id,
                            "name": me.deck[i].name,
                            "cost": int(getattr(me.deck[i], "cost", 0) or 0),
                            "power": int(getattr(me.deck[i], "power", 0) or 0),
                        }
                        for i in matching_idxs
                    ],
                    "limit": limit,
                    "destination": "hand",
                }
                state.push_log(
                    f"  効果: サーチ デッキ全体 → 人間 選 択 待 ち "
                    f"({len(matching_idxs)} 候 補 から {limit} 枚)"
                )
                return True
            # picks_idx 指定時 = 人間 選 択 解 決 後 の 再実行
            if picks_idx is not None:
                # ⚠ filter 該当のみ + limit で cap + 重複除去 (= 人間が候補超/非該当/重複を
                #   送っても防御。 AI path と同等。 2026-06-04 修正: 旧実装は picks をそのまま
                #   全件手札へで limit/filter 無視だった)。
                seen_i: set[int] = set()
                ordered_i: list[int] = []
                for i in picks_idx:
                    if (isinstance(i, int) and 0 <= i < len(me.deck)
                            and i not in seen_i and _matches_filter(me.deck[i], filt)):
                        seen_i.add(i)
                        ordered_i.append(i)
                chosen_i = ordered_i[:limit]
                picked: list[CardDef] = [me.deck.pop(i) for i in sorted(chosen_i, reverse=True)]
            else:
                # AI / 候補 ≤ limit: filter マッチから 価値順 に N 枚。 旧実装は「デッキ順先頭N」
                # だったが 探索前デッキはシャッフル済 = 実質ランダム抽出だった。 2026-07-08 監査:
                # AI は最も価値の高い札(= コスト高→パワー高、 環境で最も影響が大きい)を取る。
                # 人間は上の search_pick modal で任意選択(候補≤limit の局面のみ この自動 path)。
                match_pos = sorted(
                    (i for i in matching_idxs),
                    key=lambda i: (int(getattr(me.deck[i], "cost", 0) or 0),
                                   int(getattr(me.deck[i], "power", 0) or 0)),
                    reverse=True,
                )[:limit]
                chosen = set(match_pos)
                picked = [me.deck[i] for i in match_pos]
                me.deck = [c for i, c in enumerate(me.deck) if i not in chosen]
            # Phase 7I: search 経路は公開して手札に加える (opp に見える)
            for c in picked:
                me.add_to_hand_publicly(c)
            # サーチ後はシャッフル
            state.rng.shuffle(me.deck)
            me.known_bottom_card_ids.clear()
            me.known_top_card_ids.clear()
            state.push_log(f"  効果: サーチ → {[c.name for c in picked]}")
        elif k == "reveal_hand_play_split":
            # 公式: 「自分の手札から、 (filter) キャラカード reveal_limit 枚までを公開する。
            #   公開したカードのうち1枚を登場させ、 残りがコスト extra_rested_cost_le 以下なら
            #   レストで登場させる。」 (= OP10-058 レベッカ)。
            # search primitive はデッキ検索専用で from:hand / reveal→登場 を持たないため専用化。
            # 公開 (reveal) = 相手に見える (公式「公開する」)。 登場は play_from_hand と同じ
            # 経路 (InPlay.of + trigger_on_play、 場が満杯なら最弱を退避)。
            # active/rested の割当は決定的: コスト extra_rested_cost_le 超のカードは レストで
            # 登場できない (= 「残り」節が適用外) ので active 枠に置く。 残り (コスト以下) を
            # レストで登場。 これで盤面が最大化する (公式選択の最適形)。
            # spec: {"filter": {...}, "reveal_limit": 2, "extra_rested_cost_le": 4}
            spec = v if isinstance(v, dict) else {}
            filt = _resolve_dynamic_filter(spec.get("filter", {}), state, me, opp)
            reveal_limit = int(spec.get("reveal_limit", 2))
            rest_cost_le = int(spec.get("extra_rested_cost_le", 4))
            # 候補 = 手札の CHARACTER で filter 一致、 効果で登場可能なもの
            candidates: list[tuple[int, CardDef]] = []
            for i, card in enumerate(me.hand):
                if card.category != Category.CHARACTER:
                    continue
                if _no_play_from_hand_via_effect(card, state.effects_overlay):
                    continue
                if not _matches_filter(card, filt):
                    continue
                candidates.append((i, card))
            if not candidates:
                state.push_log("  効果: reveal_hand_play_split 該当 手札 なし (不発)")
            else:
                picks_idx: Optional[list[int]] = None
                if isinstance(v, dict) and "_picks_idx" in v:
                    picks_idx = list(v["_picks_idx"])
                # 人間 acting + picks 未指定 → 公開候補を最大 reveal_limit 枚 選ばせる modal
                if picks_idx is None and _should_human_pick(state):
                    state.pending_choice = {
                        "kind": "reveal_hand_play_split_pick",
                        "primitive_value": v,
                        "candidates": [
                            {
                                "hand_idx": i,
                                "card_id": c.card_id,
                                "name": c.name,
                                "cost": int(c.cost) if c.cost is not None else 0,
                                "power": int(c.power) if c.power is not None else 0,
                            }
                            for i, c in candidates
                        ],
                        "limit": reveal_limit,
                        "source_iid": self_inplay.instance_id if self_inplay else None,
                    }
                    state.push_log(
                        f"  効果: 手札公開 候補 {len(candidates)} 枚 → 人間 選択 待ち "
                        f"(= {reveal_limit} 枚 まで)"
                    )
                    return True
                valid_idxs = {i for i, _ in candidates}
                if picks_idx is not None:
                    # 人間選択: filter 通過 hand idx に限定 + reveal_limit で cap + 重複除去
                    reveal_set: list[int] = []
                    for i in picks_idx:
                        if i in valid_idxs and i not in reveal_set:
                            reveal_set.append(i)
                    reveal_set = reveal_set[:reveal_limit]
                else:
                    # AI: 盤面最大化 = 最良候補を active、 コスト以下の別候補を rested (最大 2 体)。
                    ordered = sorted(
                        candidates,
                        key=lambda t: (int(t[1].cost or 0), int(t[1].power or 0)),
                        reverse=True,
                    )
                    active_i = ordered[0][0]
                    rested_i: Optional[int] = None
                    for i, c in ordered[1:]:
                        if int(c.cost or 0) <= rest_cost_le:
                            rested_i = i
                            break
                    reveal_set = [active_i] + ([rested_i] if rested_i is not None else [])
                    reveal_set = reveal_set[:reveal_limit]
                if not reveal_set:
                    state.push_log("  効果: reveal_hand_play_split 公開 0 枚 (= skip)")
                else:
                    # 公開 (= 相手に見える)
                    state.push_log(
                        f"  効果: 手札から公開 → {[me.hand[i].name for i in reveal_set]}"
                    )
                    # active 枠 = コスト超のカード優先 (レストにできない為)、 なければ最良。
                    def _val(i: int) -> tuple[int, int]:
                        c = me.hand[i]
                        return (int(c.cost or 0), int(c.power or 0))
                    big_idxs = [i for i in reveal_set if int(me.hand[i].cost or 0) > rest_cost_le]
                    active_idx = max(big_idxs or reveal_set, key=_val)
                    # 登場する (card, rested) を hand から抜く前に確定
                    plays: list[tuple[int, bool]] = [(active_idx, False)]
                    for i in reveal_set:
                        if i == active_idx:
                            continue
                        if int(me.hand[i].cost or 0) <= rest_cost_le:
                            plays.append((i, True))
                        else:
                            state.push_log(
                                f"  効果: {me.hand[i].name} は コスト{rest_cost_le}超で"
                                f"レスト登場できず 公開のみ (手札に残る)"
                            )
                    play_cards = [(me.hand[i], rested) for i, rested in plays]
                    for i in sorted((i for i, _ in plays), reverse=True):
                        me.hand.pop(i)
                    for card, rested in play_cards:
                        if not me.can_play_character():
                            me.trash_weakest_chara_for_field_full(
                                state, owner_idx=state.players.index(me))
                        ip = InPlay.of(card, rested=rested, sickness=True)
                        me.characters.append(ip)
                        label = "レストで" if rested else ""
                        state.push_log(f"  効果: 手札公開から{label}登場 → {card.name}")
                        if state.effects_overlay:
                            trigger_on_play(state, me, opp, ip, state.effects_overlay)
        elif k == "life_to_hand":
            if getattr(me, "prevent_self_life_to_hand_until_turn_end", False):
                state.push_log(f"  効果: ライフ→手札 禁止 (OP02-023 効果中)")
                return False
            n = int(v)
            moved = 0
            for _ in range(n):
                if me.life:
                    me.hand.append(me.life.pop(0))
                    moved += 1
            state.push_log(f"  効果: ライフ{n}枚を手札へ")
            if moved:
                fire_self_life_to_hand(state, me)
        elif k == "add_don" or k == "add_don_active":
            # add_don_active は add_don の明示 alias (= ドンデッキから N 枚アクティブで追加)。
            # 公式: 「自分のドン!! デッキから、 ドン!! N 枚を自分の場にアクティブで追加する」
            n = int(v)
            n = min(n, me.don_remaining_in_deck)
            me.don_active += n
            me.don_remaining_in_deck -= n
            state.push_log(f"  効果: ドン+{n}")
        elif k == "add_rested_don":
            # ドンデッキから N 枚をレストでコストエリアに追加 (紫エネル等)
            n = int(v)
            n = min(n, me.don_remaining_in_deck)
            me.don_rested += n
            me.don_remaining_in_deck -= n
            state.push_log(f"  効果: レストドン+{n}")
        elif k == "untap_don":
            # レストドンを N 枚アクティブにする (緑紫ルフィ / 緑ミホーク等)
            # v="all" は「自分のドン!! すべてを、アクティブにする」(OP13-028)
            # ⚠ 「このターン中、 キャラの効果でドン‼をアクティブにできない」 が立っていれば不発
            #   (EB04-016 / OP10-030 の自己ロック)。 self_inplay がキャラの時だけ効く。
            if (getattr(me, "block_chara_effect_untap_don_until_turn_end", False)
                    and self_inplay is not None
                    and self_inplay.card.category == Category.CHARACTER):
                state.push_log("  効果: ドン アクティブ化は このターン禁止 (不発)")
                continue
            if isinstance(v, str) and v == "all":
                n = me.don_rested
            else:
                n = int(v)
            n = min(n, me.don_rested)
            me.don_rested -= n
            me.don_active += n
            state.push_log(f"  効果: ドン{n}枚をアクティブに")
        elif k == "pay_don":
            # ドン-N: 場のドン N 枚をドンデッキに戻す。 「場のドン」= cost area(active/rested)+ キャラ/リーダーに
            # 付与されたドン (公式: 付与ドンも返却可、 FAQ 準拠、 ohtsuki 指摘 2026-07-08)。
            # 既定は area active→rested→(不足なら)付与ドン(= AI/従来を保ちつつ付与 fallback で払える様に)。
            # 人間が don_return_pick modal で割当を選んだ場合 state._don_return_alloc を尊重(付与ドン含む)。
            n = int(v)
            removed = _pay_don_from_field(state, me, n, getattr(state, "_don_return_alloc", None))
            state._don_return_alloc = None
            state.push_log(f"  効果: 自ドン -{removed} (ドンデッキへ)")
            if removed > 0 and state.effects_overlay:
                trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay, count=removed)
        elif k == "untap":
            # 対象を rested=False に。target = self / self_leader / all_self_characters
            target_spec = v if isinstance(v, str) else "self"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="untap", outer_value=target_spec)
            for t in targets:
                t.rested = False
            state.push_log(f"  効果: アクティブ化 → {[t.card.name for t in targets]}")
        elif k == "give_rush":
            # 速攻付与 (登場ターン中もアタック可)。target = str (parametric) / dict (filter)
            # dict 形式は give_keyword と同様に target_spec を _resolve_target に渡す。
            # 例: {"type": "one_self_chara_filtered", "filter": {"feature_in": [...]}}
            # 例: {"target": "one_self_character_feature_X"}
            if isinstance(v, dict):
                if "type" in v:
                    target_spec = v
                elif "target" in v:
                    target_spec = v.get("target", "self")
                else:
                    target_spec = "self"
            elif isinstance(v, str):
                target_spec = v
            else:
                target_spec = "self"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="give_rush", outer_value=target_spec)
            for t in targets:
                t.summoning_sickness = False
            state.push_log(f"  効果: 速攻 → {[t.card.name for t in targets]}")
        elif k == "don_minus_opp":
            # 「ドン!! -N: 相手のドンを N 枚 ドン!!デッキに戻す」
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            # active から優先で減らし、足りなければ rested から
            removed = 0
            taken = min(n, opp.don_active)
            opp.don_active -= taken
            opp.don_remaining_in_deck += taken
            removed += taken
            if removed < n:
                taken = min(n - removed, opp.don_rested)
                opp.don_rested -= taken
                opp.don_remaining_in_deck += taken
                removed += taken
            state.push_log(f"  効果: 相手ドン -{removed}")
            # 公式 Q&A (cardqa_op_06 / op_02): 「自分のターン中に、 **相手のカードの効果で**
            # 自分のドン!!がドン!!デッキに戻された時、 この効果を発動できますか？」 → 「はい」。
            # 「場のドン!!が戻された時」 は 誰が戻したかを問わない (op_02 で相手側も含むと明記)。
            # ⚠ ここで発火していなかったため 相手側の on_self_don_returned_to_deck が
            #   丸ごと落ちていた (2026-08-04、 db/_pending_review.md の裁定で確定)。
            if removed > 0 and state.effects_overlay:
                trigger_on_self_don_returned_to_deck(
                    state, opp, me, state.effects_overlay, count=removed)
        elif k == "mill":
            # 「相手 (or 自) のデッキ上 N 枚をトラッシュ」
            spec = v if isinstance(v, dict) else {"target": "opp", "count": int(v)}
            target = spec.get("target", "opp")
            n = int(spec.get("count", 1))
            who = opp if target == "opp" else me
            milled = []
            for _ in range(n):
                if not who.deck:
                    break
                c = who.deck.pop(0)
                who.trash.append(c)
                milled.append(c.name)
            state.push_log(f"  効果: {target} mill {n} → {milled}")
        elif k == "put_top_to_life":
            # 「自デッキ上 N 枚を 自分のライフへ」
            n = int(v)
            for _ in range(n):
                if not me.deck:
                    break
                c = me.deck.pop(0)
                me.life.append(c)  # ライフ上 (技術的には先頭追加だが簡略)
            state.push_log(f"  効果: デッキ上 {n} 枚をライフへ")
        elif k == "give_keyword":
            # 動的キーワード付与。spec: {"target": "self", "keyword": "ダブルアタック"}
            #                         or "self" 文字列なら速攻 (デフォルト)
            # 拡張: "keywords": [<kw>, ...] で AI 簡易選択 (= ブロッカー優先 → ダブルアタック → バニッシュ → 速攻)。
            # 拡張: "duration": "turn"(既定) | "next_opp_turn_end"。
            #       "next_opp_turn_end" は granted_keywords_through_opp_turn に積み applier-tracking でクリア。
            spec = v if isinstance(v, dict) else {"target": "self", "keyword": "速攻"}
            target_spec = spec.get("target", "self")
            duration = spec.get("duration", "turn")
            # 選択肢があれば: 人間は modal で選択、 AI は優先順位で自動
            # (= ブロッカー(守備) > ダブルアタック(攻撃) > バニッシュ > 速攻)。
            # カタリーナ・デボン OP09-084 等「ダブルアタックかバニッシュかブロッカーを得る」の3択。
            if "keywords" in spec:
                kws = list(spec["keywords"])
                chosen_kw = spec.get("_chosen_keyword")
                if chosen_kw is None and len(kws) > 1 and _should_human_pick(state):
                    state.pending_choice = {
                        "kind": "give_keyword_choice",
                        "options": [{"idx": i, "label": kw} for i, kw in enumerate(kws)],
                        "keywords": kws,
                        "spec": v,
                        "self_inplay_iid": (self_inplay.instance_id if self_inplay is not None else None),
                        "prompt": "付与するキーワードを選んでください。",
                    }
                    return  # 選択待ち(resolve_pending_choice で _chosen_keyword 付き再実行)
                if chosen_kw is not None and chosen_kw in kws:
                    keyword = chosen_kw
                else:
                    priority = ["ブロッカー", "ダブルアタック", "バニッシュ", "速攻", "ブロック不可"]
                    keyword = next((p for p in priority if p in kws), kws[0] if kws else "速攻")
            else:
                keyword = spec.get("keyword", "速攻")
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="give_keyword", outer_value=v,
            )
            me_idx = state.players.index(me)
            for t in targets:
                if duration == "next_opp_turn_end":
                    t.granted_keywords_through_opp_turn.add(keyword)
                    t.granted_keywords_through_opp_turn_applier_idx = me_idx
                    t.granted_keywords_through_opp_turn_applied_turn = state.turn_number
                else:
                    t.granted_keywords.add(keyword)
            state.push_log(f"  効果: {keyword} 付与 ({duration}) → {[t.card.name for t in targets]}")
        elif k == "set_base_power_timed":
            # 「元々のパワーを X にする (期限付き)」 (ST26-005 ルフィ 等)。
            # spec: {"target": "self_leader", "amount": 7000, "duration": "next_opp_turn_end"}
            # duration: "turn" | "next_self_turn_start" | "next_opp_turn_end"
            spec = v if isinstance(v, dict) else {}
            target_spec = spec.get("target", "self")
            amount = int(spec.get("amount", 0))
            duration = spec.get("duration", "turn")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_base_power_timed", outer_value=v)
            me_idx = state.players.index(me)
            for t in targets:
                if duration == "turn":
                    t.turn_base_power_override = amount
                elif duration == "next_self_turn_start":
                    t.next_turn_base_power_override = amount
                elif duration in ("next_opp_turn_end", "next_opp_end_phase"):
                    t.next_opp_turn_end_base_power_override = amount
                    t.next_opp_turn_end_base_power_override_applier_idx = me_idx
                    t.next_opp_turn_end_base_power_override_applied_turn = state.turn_number
                else:
                    t.base_power_override = amount
            state.push_log(
                f"  効果: 元々のパワー={amount} ({duration}) → {[t.card.name for t in targets]}"
            )
        elif k == "set_base_power_copy":
            # 「このキャラの元々のパワーは、 このターン中、 選んだキャラと同じパワーになる」
            # (EB01-061 Mr.2 等)。 from_target で選んだキャラの current power を
            # to_target (default: self_inplay) の turn_base_power_override に書き込む。
            # spec: {"from_target": "one_opponent_character_any", "to_target": "self",
            #        "duration": "turn"}
            spec = v if isinstance(v, dict) else {"from_target": "one_opponent_character_any"}
            from_target = spec.get("from_target", "one_opponent_character_any")
            to_target = spec.get("to_target", "self")
            duration = spec.get("duration", "turn")
            # 人間 target_pick 解決後の再実行 (= v に _iid_picks) は from_target に適用
            # (= from_target キーは target_pick 解決の _iid_picks 注入先 "target" と異なるため、
            #  明示的に拾わないと default に戻り 無限 target_pick 再表示する)
            if isinstance(v, dict) and "_iid_picks" in v:
                from_target = {"_iid_picks": v["_iid_picks"]}
            from_cands = _resolve_target(from_target, state, me, opp, self_inplay, outer_kind="set_base_power_copy", outer_value=v)
            if not from_cands:
                state.push_log("  効果: power-copy 対象なし (不発)")
                return False
            source_ip = from_cands[0]
            to_cands = _resolve_target(to_target, state, me, opp, self_inplay, outer_kind="set_base_power_copy", outer_value=to_target)
            if not to_cands:
                state.push_log("  効果: power-copy 適用先なし (不発)")
                return False
            copied_power = source_ip.power
            for t in to_cands:
                if duration == "turn":
                    t.turn_base_power_override = copied_power
                elif duration == "next_self_turn_start":
                    t.next_turn_base_power_override = copied_power
                else:
                    t.base_power_override = copied_power
            state.push_log(
                f"  効果: 元々のパワー {copied_power} (= {source_ip.card.name}) を "
                f"{[t.card.name for t in to_cands]} に複写 ({duration})"
            )
        elif k == "play_from_trash" or k == "play_multi_from_trash":
            # 「自分のトラッシュからキャラ1枚を登場」 (limit>1 で複数体)
            # spec: {"filter": {"category": "CHARACTER", "feature": "...", "cost_le": N},
            #        "limit": 1, "rested": bool, "unique_name": false}
            # play_multi_from_trash は alias (= 公式 「~まで」 N 枚指定の意図を明示)。
            # unique_name=true で カード名が重複しないように複数体登場 (OP06-062 ジャッジ)。
            # 人間 acting + 候補 > limit なら modal で 選ばせる。
            # 2026-05-31: filter の cost_le_dynamic も 静的化 (= 動的 cost cap 対応)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = _resolve_dynamic_filter(spec.get("filter", {}), state, me, opp)
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            unique_name = bool(spec.get("unique_name", False))
            # 一時登場: このターン終了時にデッキ下へ戻す (= OP11-092 ヘルメッポ)
            want_return_eot = bool(spec.get("return_to_deck_bottom_at_turn_end", False))
            # 「登場させたキャラは、 このターン中、 【keyword】 を得る」 (= OP15-086 速攻)。
            # reveal_top_play の played_keyword と同機構: 召喚 ip の granted_keywords に積む
            # (= turn-scoped、 _reset_turn_buff でクリア = 「このターン中」)。
            pk_grant = spec.get("played_keyword")
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 2026-05-31 拡張: filter.category が STAGE なら ステージ として 登場 (= OP13-092 等)。
            # filter.category 未指定 / CHARACTER → 従来挙動 (= キャラ として 登場)。
            # 公式 「登場させる」 は カテゴリ に 応じて 適切 な zone (= chara / stage) に 配置。
            target_category_str = filt.get("category", "CHARACTER")
            try:
                target_category = Category[target_category_str] if isinstance(target_category_str, str) else Category.CHARACTER
            except KeyError:
                target_category = Category.CHARACTER
            # 候補 抽出 (= trash idx + CardDef)。 category は filter 指定 を 優先。
            # no_effect (= 元々効果なし) も ここで除外 (= _matches_filter は no_effect を
            # 見ないので、 modal に効果持ちを出さないため明示的に弾く)。
            candidates: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.trash)
                if c.category == target_category and _matches_filter(c, filt)
                and not (filt.get("no_effect") and not _card_has_no_effect(c, state))
            ]
            # or_to_life (= ゲッコー・モリア OP14-104【登場時】「ライフの上に表向きで加えるか
            # 登場させる」): human acting 時は 各候補 × {登場 / ライフ} の 行き先 を modal で 選ばせる。
            # AI は 従来通り 登場 (= 下の通常 path に fall-through、 matrix/AI 不変)。
            # picks_idx 指定済 (= 再帰呼出) は ここを 通らない (無限ループ 防止)。
            if (spec.get("or_to_life") and picks_idx is None
                    and _should_human_pick(state) and candidates):
                or_actions = []
                for ti, c in candidates:
                    cp = int(c.cost) if c.cost is not None else 0
                    pw = int(c.power) if c.power is not None else 0
                    or_actions.append({"trash_idx": ti, "dest": "play",
                                       "label": f"{c.name}(c{cp}/P{pw}) を登場させる"})
                    or_actions.append({"trash_idx": ti, "dest": "life",
                                       "label": f"{c.name}(c{cp}/P{pw}) をライフの上に表向きで加える"})
                state.pending_choice = {
                    "kind": "play_from_trash_or_life_pick",
                    "primitive_value": v,
                    "actions": or_actions,
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: トラッシュ → 登場/ライフ 選択 待ち ({len(candidates)} 候補、 0=skip)"
                )
                return True
            # 人間 acting + 候補 > limit + picks 未指定 → modal
            if picks_idx is None and _should_human_pick(state) and len(candidates) > limit:
                cand_list = [
                    {
                        "trash_idx": i,
                        "card_id": c.card_id,
                        "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    }
                    for i, c in candidates
                ]
                state.pending_choice = {
                    "kind": "play_from_trash_pick",
                    "primitive_value": v,
                    "candidates": cand_list,
                    "limit": limit,
                    "rested": rested,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: トラッシュ から 登場 候補 {len(candidates)} 枚 → 人間 選択 待ち (= {limit} 枚 まで)"
                )
                return True
            # picks 解決 path: 指定 trash idx を 順 に 登場 (= 後ろ から で trash 削除 安全)
            if picks_idx is not None:
                if not picks_idx:
                    state.push_log("  効果: トラッシュ から 登場 0 枚 選択 (= skip)")
                    return False
                # 後ろ から 取り出し で index ずれ 防止
                chosen_indexes = sorted(
                    [i for i in picks_idx if 0 <= i < len(me.trash)],
                    reverse=True,
                )
                played_count = 0
                seen_names: set[str] = set()
                for i in chosen_indexes:
                    if played_count >= limit:
                        break
                    card = me.trash[i]
                    # ⚠ pick path でも AI path と同じ制約を全て enforce する
                    #   (= 人間経路だけ制約が抜けるバグ類型の根絶)。
                    # filter / category / no_effect (= 元々効果なし) を確認。
                    if card.category != target_category or not _matches_filter(card, filt):
                        continue
                    if filt.get("no_effect") and not _card_has_no_effect(card, state):
                        state.push_log(f"  効果: {card.name} は効果持ちのため登場せず (元々効果のないキャラ)")
                        continue
                    # 公式「カード名の異なる」: unique_name 指定時は重複名を登場させない。
                    if unique_name and card.name in seen_names:
                        state.push_log(f"  効果: {card.name} は同名重複のため登場せず (カード名の異なる)")
                        continue
                    if target_category == Category.STAGE:
                        # 既 ステージ ある なら 入れ替え (= 公式 上限 1)。
                        if me.stages:
                            old = me.stages.pop(0)
                            me.trash.append(old.card)
                            if old.attached_dons > 0:
                                me.don_rested += old.attached_dons
                            state.push_log(f"  効果: 既存ステージ {old.card.name} → trash")
                        me.trash.pop(i)
                        ip = InPlay.of(card, rested=False, sickness=False)
                        me.stages.append(ip)
                        state.push_log(f"  効果: トラッシュから ステージ 登場 → {card.name}")
                    else:
                        if not me.can_play_character():
                            me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                        me.trash.pop(i)
                        ip = InPlay.of(card, rested=rested, sickness=True)
                        ip.return_to_deck_bottom_at_turn_end = want_return_eot
                        ip.played_from_trash = True
                        me.characters.append(ip)
                        if pk_grant:
                            ip.granted_keywords.add(str(pk_grant))
                        label = "レストで" if rested else ""
                        state.push_log(f"  効果: トラッシュから{label}登場 → {card.name}")
                        if state.effects_overlay:
                            trigger_on_play(state, me, opp, ip, state.effects_overlay)
                    seen_names.add(card.name)
                    played_count += 1
                if played_count == 0:
                    return False
                continue
            # AI / 候補 <= limit: 先頭から filter 一致を 登場。
            # ⚠ 公式: 「登場でトラッシュを離れて**から** on_play」。 旧実装は me.trash[:] = new_trash を
            # loop 後に行い、 trigger_on_play が「登場済カードがまだ trash にいる」 stale を見ていた
            # → source-zone を触る on_play (= OP06-090 ホグバック の trash_to_deck+登場 等) で 人間 pick
            # 経路 (= pop 後 on_play で正しい) と divergence。 2026-06-05 wide lockstep が検出。
            # ⇒ **先に play 対象を選定して me.trash から除去** してから append + on_play する。
            found = 0
            seen_names: set[str] = set()
            to_play = []
            remaining = []
            for card in me.trash:
                if (found < limit and card.category == target_category
                        and _matches_filter(card, filt)
                        and not (filt.get("no_effect") and not _card_has_no_effect(card, state))
                        and not (unique_name and card.name in seen_names)):
                    to_play.append(card)
                    found += 1
                    seen_names.add(card.name)
                else:
                    remaining.append(card)
            me.trash[:] = remaining  # 先に trash 更新 (= 登場でトラッシュを離れる)
            for card in to_play:
                if target_category == Category.STAGE:
                    if me.stages:
                        old = me.stages.pop(0)
                        me.trash.append(old.card)
                        if old.attached_dons > 0:
                            me.don_rested += old.attached_dons
                        state.push_log(f"  効果: 既存ステージ {old.card.name} → trash")
                    ip = InPlay.of(card, rested=False, sickness=False)
                    me.stages.append(ip)
                    state.push_log(f"  効果: トラッシュから ステージ 登場 → {card.name}")
                    continue
                if not me.can_play_character():
                    me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                ip = InPlay.of(card, rested=rested, sickness=True)
                ip.return_to_deck_bottom_at_turn_end = want_return_eot
                ip.played_from_trash = True
                me.characters.append(ip)
                if pk_grant:
                    ip.granted_keywords.add(str(pk_grant))
                label = "レストで" if rested else ""
                state.push_log(f"  効果: トラッシュから{label}登場 → {card.name}")
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, ip, state.effects_overlay)
        elif k == "bounce_self_chara_then_play_diff_color":
            # 「自分のキャラ1枚を持ち主の手札に戻し、 戻したキャラと異なる色のコストN以下の
            # キャラ1枚までを登場させる」 (EB01-020/OP01-002)。 戻したキャラの色を動的除外。
            spec_val = v if isinstance(v, dict) else {}
            cost_le = int(spec_val.get("play_cost_le", 2))
            if not me.characters:
                state.push_log("  効果: 戻す自キャラなし (不発)")
                return False
            # 2026-07-08 監査: 人間は「どの自キャラを手札に戻すか」を選べる(target_pick modal)。
            picks_iids = spec_val.get("_iid_picks")
            if picks_iids is None and len(me.characters) > 1 and _maybe_request_target_pick(
                    state, list(me.characters), 1, k, dict(spec_val), self_inplay,
                    description="手札に戻す自キャラを選択(その後 異なる色のキャラを登場)"):
                return True
            if picks_iids:
                victim = next((c for c in me.characters if c.instance_id in picks_iids),
                              min(me.characters, key=lambda c: (c.power, c.card.cost)))
            else:
                victim = min(me.characters, key=lambda c: (c.power, c.card.cost))
            bounced_colors = set(victim.card.color)
            me.characters.remove(victim)
            me.hand.append(victim.card)
            if victim.attached_dons > 0:
                me.don_rested += victim.attached_dons
            state.push_log(f"  効果: {victim.card.name} を手札に戻す (色={bounced_colors})")
            cands = [(i, c) for i, c in enumerate(me.hand)
                     if c.category == Category.CHARACTER and c.cost <= cost_le
                     and not (set(c.color) & bounced_colors)]
            if not cands:
                state.push_log("  効果: 異色キャラ手札になし (登場なし)")
            else:
                cands.sort(key=lambda ic: -ic[1].power)
                idx, card = cands[0]
                me.hand.pop(idx)
                me.characters.append(InPlay.of(card, sickness=True))
                state.push_log(f"  効果: 異色キャラ登場 {card.name}")
        elif k == "play_stage_from_hand":
            # 「自分の手札から[name/filter]のステージ1枚を登場させる」 (EB02-013 ゾウ /
            # EB03-044 鬼ヶ島 / OP08-110 アッパーヤード / EB02-032 ガレーラ 等)。
            # play_from_hand は CHARACTER 専用なので STAGE は本 primitive。 既存ステージは置換。
            spec = v if isinstance(v, dict) else {"filter": {}}
            filt = spec.get("filter", {}) if isinstance(spec, dict) else {}
            idx = None
            for i, card in enumerate(me.hand):
                if card.category == Category.STAGE and _matches_filter(card, filt):
                    idx = i
                    break
            if idx is None:
                state.push_log("  効果: play_stage_from_hand 該当 ステージ なし (不発)")
            else:
                card = me.hand.pop(idx)
                # 公式: ステージは1枚まで → 既存ステージはトラッシュへ置換。
                for s in list(me.stages):
                    me.stages.remove(s)
                    me.trash.append(s.card)
                    if s.attached_dons > 0:
                        me.don_rested += s.attached_dons
                stage_ip = InPlay.of(card, sickness=False)
                me.stages.append(stage_ip)
                state.push_log(f"  効果: 手札からステージ登場 {card.name}")
                # 3-8-3: ステージエリアに置くことも「登場」 → 【登場時】を発動可。
                # 通常の PlayStage action (game.py) と対称。 効果経路 (OP08-110 アッパーヤード /
                # EB02-013 ゾウ / EB03-044 鬼ヶ島 等) でも stage の on_play を発火させる。
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, stage_ip, state.effects_overlay)
        elif k == "play_from_hand":
            # 「自分の手札からキャラ1枚を 0 コストで登場」(緑紫ルフィ起動メイン / OP10-071 ドフラ 等)。
            # spec: {"filter": {"feature": "...", "cost_le": N}, "limit": 1, "rested": bool}
            # 通常の PlayCharacter と異なり、 コスト無視 (= 効果代替の登場)。
            # 人間 acting + 複数候補 + 0 < limit < 候補数 なら modal 選択 (= 2026-05-23 修正、
            # ohtsuki さん 指摘: OP10-071 ドフラ 登場時 で 勝手 に 選ばれる)。
            # 2026-05-31 追加: filter の cost_le_dynamic (= self_don_total 等) を 静的化
            # (= OP13-099 虚の玉座 「場のドン!!の枚数以下のコスト」)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = _resolve_dynamic_filter(spec.get("filter", {}), state, me, opp)
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            # 既 解決 picks (= resolve_pending_choice 経由) の場合 は直接実行
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補抽出
            # ⚠ 「コストN以下」 の登場 filter は **手札での現在コスト** で判定する
            #   (= ST23-001 ウタ 「手札のこのカードは…コスト-4」 → OP01-047 ロー cost3以下 で
            #   登場可、 cardqa_st_23)。 手札コスト修正 (in_hand_cost_minus) を持たない大多数の
            #   カードは in_hand_cost_minus=0 → `_matches_filter` と完全一致 = 挙動不変。
            from .game import _compute_in_hand_cost_minus as _pfh_ihm
            candidates: list[tuple[int, CardDef]] = []
            for i, card in enumerate(me.hand):
                if card.category != Category.CHARACTER:
                    continue
                if _no_play_from_hand_via_effect(card, state.effects_overlay):
                    continue   # OP12-036: 効果で登場できないカードは候補外
                _ihm = _pfh_ihm(state, me, card)
                if not _matches_filter_hand(card, filt, _ihm):
                    continue
                if filt.get("no_effect") and not _card_has_no_effect(card, state):
                    continue
                candidates.append((i, card))
            if not candidates:
                state.push_log(f"  効果: play_from_hand 該当 手札 なし (不発)")
            else:
                # 人間 acting + 候補 > limit + picks 未指定 → modal で選択 (= 0 picks 含む)
                if picks_idx is None and _should_human_pick(state) and len(candidates) > limit:
                    cand_list = [
                        {
                            "hand_idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "cost": int(c.cost) if c.cost is not None else 0,
                            "power": int(c.power) if c.power is not None else 0,
                        }
                        for i, c in candidates
                    ]
                    state.pending_choice = {
                        "kind": "play_from_hand_pick",
                        "primitive_value": v,
                        "candidates": cand_list,
                        "limit": limit,
                        "rested": rested,
                        "filter_desc": _describe_filter_jp(filt),
                        "source_iid": self_inplay.instance_id if self_inplay else None,
                    }
                    state.push_log(
                        f"  効果: 手札 から 登場 候補 {len(candidates)} 枚 → 人間 選択 待ち (= {limit} 枚 まで)"
                    )
                    return True
                # picks 指定 or AI or 候補 <= limit → 既存挙動
                # 公式「カード名の異なる」: unique_name=true なら同名は1枚まで (= OP16-060 センゴク
                # 「カード名の異なる《大将》3枚」)。 既定 false なので既存の play_from_hand には無影響。
                unique_name = bool(spec.get("unique_name", False))
                _name_by_idx = {i: c.name for i, c in candidates}
                if picks_idx is not None:
                    # ⚠ 候補 (= filter/no_effect 通過済) に限定 + limit で cap する
                    #   (= AI path と同等。 人間が候補外/上限超を送っても防御。 2026-06-04 修正:
                    #   旧実装は picks をそのまま全召喚で limit/filter を無視していた)。
                    valid_hand_idxs = {i for i, _ in candidates}
                    sel = [i for i in picks_idx if i in valid_hand_idxs]
                    if unique_name:
                        seen_n: set[str] = set()
                        sel = [i for i in sel
                               if not (_name_by_idx[i] in seen_n or seen_n.add(_name_by_idx[i]))]
                    chosen_indexes = sorted(sel[:limit], reverse=True)
                else:
                    # ヒューリスティック並び: cost 降順 → power 降順 → name (安定)
                    candidates.sort(key=lambda t: (-t[1].cost, -t[1].power, t[1].name))
                    if unique_name:
                        seen_n2: set[str] = set()
                        candidates = [(i, c) for i, c in candidates
                                      if not (c.name in seen_n2 or seen_n2.add(c.name))]
                    chosen = candidates[:limit]
                    chosen_indexes = sorted([i for i, _ in chosen], reverse=True)
                chosen_cards: list[CardDef] = []
                for idx in chosen_indexes:
                    chosen_cards.append(me.hand.pop(idx))
                for card in chosen_cards:
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    label = "レストで" if rested else ""
                    state.push_log(f"  効果: 手札から{label}登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                # 「登場させた場合」 の後続 (= OP08-098 カルガラ: 登場できた時のみライフ上 N 枚を手札へ)。
                # 登場 0 枚 (= 該当手札なし) なら不発 = 公式「場合」 前文不成立。
                if chosen_cards and isinstance(v, dict) and v.get("then_life_to_hand"):
                    if getattr(me, "prevent_self_life_to_hand_until_turn_end", False):
                        state.push_log(f"  効果: ライフ→手札 禁止 (登場後ライフ獲得 不発)")
                    else:
                        n_life = int(v.get("then_life_to_hand"))
                        moved = 0
                        for _ in range(n_life):
                            if me.life:
                                me.hand.append(me.life.pop(0))
                                moved += 1
                        state.push_log(f"  効果: 登場に伴いライフ上{n_life}枚を手札へ ({len(me.life)} 残)")
                        if moved:
                            fire_self_life_to_hand(state, me)
        elif k == "play_from_hand_choice":
            # 「自分の手札から filter 一致のキャラ N 枚までを (任意で) 0 コストで登場」
            # play_from_hand との差分: 「~してもよい」 表現 (= 任意の選択) を表現する。
            # 候補が複数あれば最も影響の大きいキャラ (cost 高 → power 高) を 1 体選ぶヒューリスティック。
            # filter 一致 0 件は False (公式 4-10 「場合」 前文不実行)。
            # spec: {"filter": {...}, "limit": N (default 1), "rested": bool, "category": "CHARACTER" (default)}
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            target_category = spec.get("category", "CHARACTER")
            # _iid_picks bypass (= resolve_pending_choice 経由 の 再実行)。
            # picks_idx (= hand_idx list) は modal で 人間 が 選んだ 結果。
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補抽出 (= (original_index, card) のリスト)
            candidates: list[tuple[int, CardDef]] = []
            for i, card in enumerate(me.hand):
                if target_category == "CHARACTER" and card.category != Category.CHARACTER:
                    continue
                if not _matches_filter(card, filt):
                    continue
                candidates.append((i, card))
            if not candidates:
                state.push_log(f"  効果: play_from_hand_choice 該当なし (不発)")
                return False
            # 人間 acting + 候補 > limit + picks 未指定 → modal で選択 (= 0 picks 含む)
            # play_from_hand と 同じ pattern (= line 2878)。
            if picks_idx is None and _should_human_pick(state) and len(candidates) > limit:
                cand_list = [
                    {
                        "hand_idx": i,
                        "card_id": c.card_id,
                        "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    }
                    for i, c in candidates
                ]
                state.pending_choice = {
                    "kind": "play_from_hand_pick",
                    "primitive_value": v,
                    "candidates": cand_list,
                    "limit": limit,
                    "rested": rested,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: 手札 から 任意 登場 候補 {len(candidates)} 枚 → 人間 選択 待ち (= {limit} 枚 まで)"
                )
                return True
            # picks 指定 / AI / 候補 <= limit → 既存 ヒューリスティック
            if picks_idx is not None:
                # ⚠ 候補限定 + limit cap (= 人間が候補外/上限超を送っても防御。 AI path と同等。
                #   2026-06-04 修正: 旧実装は cap/filter 無視だった)。
                valid_hand_idxs = {i for i, _ in candidates}
                chosen_indexes = sorted(
                    [i for i in picks_idx if i in valid_hand_idxs][:limit],
                    reverse=True,
                )
            else:
                # ヒューリスティック並び: cost 降順 → power 降順 → name (安定)
                candidates.sort(key=lambda t: (-t[1].cost, -t[1].power, t[1].name))
                chosen = candidates[:limit]
                chosen_indexes = sorted([i for i, _ in chosen], reverse=True)
            chosen_cards: list[CardDef] = []
            for i in chosen_indexes:
                chosen_cards.append(me.hand.pop(i))
            for card in chosen_cards:
                if not me.can_play_character():
                    me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                ip = InPlay.of(card, rested=rested, sickness=True)
                me.characters.append(ip)
                label = "レストで" if rested else ""
                state.push_log(f"  効果: 手札から{label}任意登場 → {card.name}")
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, ip, state.effects_overlay)
        elif k == "play_from_hand_named_with_dynamic_cost":
            # 公式: 「自分の手札からコスト N 以上でかつ、 (動的閾値) 以下のコストを持つ 『XXX』 1 枚を登場」
            # OP08-062 シャーロット・カタクリ起動メイン 等。
            # spec: {"name": "シャーロット・カタクリ", "cost_ge": 3, "cost_le_source": "opp_don_total"}
            # 別形: name の代わりに name_filter (= _matches_filter 互換 dict、 特徴/名前除外 等) を
            #       取り、 動的コスト上限内で該当キャラ 1 枚までを登場 (P-090 シャーロット・スムージー
            #       「特徴《ビッグ・マム海賊団》を持ち『シャーロット・スムージー』以外の、 相手の場の
            #       ドン以下のコストのキャラ1枚まで」)。 name / name_filter のいずれかを持つ。
            spec = v if isinstance(v, dict) else {}
            name = spec.get("name", "")
            name_filter = spec.get("name_filter")
            cost_ge = int(spec.get("cost_ge", 0))
            src = spec.get("cost_le_source", "opp_don_total")
            if src == "opp_don_total":
                cost_le = opp.don_active + opp.don_rested + opp.leader.attached_dons + sum(c.attached_dons for c in opp.characters)
            elif src == "self_don_total":
                cost_le = me.don_active + me.don_rested + me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
            else:
                cost_le = int(spec.get("cost_le", 99))
            # 候補抽出: name (完全一致) か name_filter (_matches_filter) + 動的コスト境界。
            candidates: list[tuple[int, CardDef]] = []
            for i, card in enumerate(me.hand):
                if card.category != Category.CHARACTER:
                    continue
                if name_filter is not None:
                    if not _matches_filter(card, name_filter):
                        continue
                elif card.name != name:
                    continue
                if card.cost < cost_ge or card.cost > cost_le:
                    continue
                candidates.append((i, card))
            if not candidates:
                label = name or _describe_filter_jp(name_filter or {})
                state.push_log(f"  効果: {label} 該当なし (cost_ge={cost_ge}, cost_le={cost_le})")
                return False
            # 「1 枚まで」 = 任意で 1 枚。 ヒューリスティック: cost 降順 → power 降順 → name
            # (= play_from_hand と同じ、 動的上限に最も近い/最も強いキャラを登場)。
            candidates.sort(key=lambda t: (-t[1].cost, -t[1].power, t[1].name))
            idx, card = candidates[0]
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
            ip = InPlay.of(card, rested=False, sickness=True)
            me.characters.append(ip)
            me.hand.pop(idx)
            state.push_log(f"  効果: {card.name} を手札から登場 (動的cost_le={cost_le})")
            if state.effects_overlay:
                trigger_on_play(state, me, opp, ip, state.effects_overlay)
            return True
        elif k == "play_from_hand_named_set":
            # R4: 「自分の手札から、 N1 と N2 と N3 ... それぞれ 1 枚ずつまでを、 登場させる」 (ST13-006 等)。
            # spec: {"names": ["サボ", "ポートガス・D・エース", "モンキー・D・ルフィ"],
            #        "cost_eq": 2, "rested": false, "filter": {...}}
            # - cost_eq/cost_le 制約を filter として追加可。
            # - filter は names 制約とAND結合。
            # 各 name について 手札先頭の 1 枚を取り出し登場 (= AI 簡易: 最も若い index)。
            spec = v if isinstance(v, dict) else {"names": []}
            # overlay 側 names は 未正規化 (= _NAME_KEYS に 'names' が無い) だが card.name は
            # load 時に normalize_card_name 済 (全角Ｄ→半角D)。 両者を 揃えないと 全角Ｄ名
            # (マーシャル・Ｄ・ティーチ 等) が silent no-op になる (self_field_named_all_with_power と同じ扱い)。
            names = [normalize_card_name(n) for n in spec.get("names", [])]
            rested = bool(spec.get("rested", False))
            extra_filt = spec.get("filter", {})
            # cost 制約も filter 互換に統合
            if "cost_eq" in spec:
                extra_filt = {**extra_filt, "cost_eq": spec["cost_eq"]}
            if "cost_le" in spec:
                extra_filt = {**extra_filt, "cost_le": spec["cost_le"]}
            played: list[str] = []
            consumed_indexes: set[int] = set()
            for nm in names:
                for i, card in enumerate(me.hand):
                    if i in consumed_indexes:
                        continue
                    if card.category != Category.CHARACTER:
                        continue
                    if card.name != nm:
                        continue
                    if not _matches_filter(card, extra_filt):
                        continue
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    consumed_indexes.add(i)
                    played.append(card.name)
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                    break
            # 消費インデックス降順で手札から除去
            for i in sorted(consumed_indexes, reverse=True):
                me.hand.pop(i)
            state.push_log(
                f"  効果: play_from_hand_named_set → {played} (該当 {len(played)}/{len(names)})"
            )
        elif k == "mill_opp_life_to_hand":
            # 相手のライフ上から N 枚を相手の手札へ (= ライフ削り、 相手リーダーに対するダメージとほぼ等価)
            # 公式: ヒット時にトリガー判定するが、 「効果で」 ライフを取る場合は trigger は発動しない (10-1-5)。
            # 簡略実装: ライフ上から取り出して相手手札に入れるだけ (トリガー判定なし)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            _moved = 0
            for _ in range(n):
                if not opp.life:
                    break
                taken = opp.life.pop(0)
                opp.hand.append(taken)
                _moved += 1
            state.push_log(f"  効果: 相手ライフ上 {n} 枚を相手手札へ")
            _fire_opp_life_left_by_effect(state, me, opp, _moved, "hand")
        elif k == "mill_self_life_to_trash":
            # 自分のライフ上から N 枚をトラッシュへ (= 自害効果)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            for _ in range(n):
                if not me.life:
                    break
                taken = me.life.pop(0)
                me.trash.append(taken)
            state.push_log(f"  効果: 自ライフ上 {n} 枚をトラッシュへ")
        elif k == "mill_opp_life_to_trash":
            # 公式 「相手のライフの上から N 枚をトラッシュに置く」 (OP11-102 ケイミー等)。
            # mill_self_life_to_trash と対称。 ライフトリガーは発動しない (= 効果でのライフ移動 10-1-5)。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            _moved = 0
            for _ in range(n):
                if not opp.life:
                    break
                taken = opp.life.pop(0)
                opp.trash.append(taken)
                _moved += 1
            state.push_log(f"  効果: 相手ライフ上 {n} 枚をトラッシュへ")
            _fire_opp_life_left_by_effect(state, me, opp, _moved, "trash")
        elif k == "return_self_don_to_deck":
            # 自分の場のドン (active 優先 → rested) を N 枚ドンデッキに戻す
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            from_active = min(me.don_active, n)
            me.don_active -= from_active
            me.don_remaining_in_deck += from_active
            remaining = n - from_active
            from_rested = min(me.don_rested, remaining)
            me.don_rested -= from_rested
            me.don_remaining_in_deck += from_rested
            state.push_log(f"  効果: 自ドン {n} 枚をドンデッキに戻す")
            if (from_active + from_rested) > 0 and state.effects_overlay:
                trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay, count=from_active + from_rested)
        elif k == "rest_self_don":
            # 自分のアクティブドン N 枚をレストにする (= 起動メイン代替コスト)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            actual = min(me.don_active, n)
            me.don_active -= actual
            me.don_rested += actual
            state.push_log(f"  効果: 自アクティブドン {actual} 枚をレストへ")
        elif k == "deal_opp_leader_damage":
            # 相手リーダーに N ダメージ (= 相手ライフ N を damage 経路で処理)。
            # ⚠ ライフ0で受けると【敗北】(効果ダメージも戦闘同様)。 戦闘 (game.py:1691-1699) と
            # 対称に、 まず on_life_zero (エネル等の回復) を試み、 まだ 0 なら declare_winner。
            # (旧実装は `if not opp.life: break` で 0ライフ相手を詰められない bug、
            #  7ロビン EB03-055 の『相手ライフ0でKOされると即敗北』が機能しなかった)
            # ⭐ 効果ダメージでも **ライフ札の【トリガー】は発動できる** (公式 cardqa_eb_03 /
            #   rules 7-1-4-1-1-2: 「1ダメージ → 相手はライフ上1枚を手札へ or トリガー発動」)。
            #   旧実装は opp.hand.append で直行 = トリガーを握り潰していた (= 「ダメージを与える」
            #   と 「ライフを手札に加える」 を混同、 両エンジンが同型なので差分検証では沈黙)。
            #   → 戦闘と同じ per-hit 処理 (_resolve_life_taken) を by_effect=True で通す。
            from .game import _resolve_life_taken
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            for _ in range(n):
                if not opp.life:
                    if state.effects_overlay:
                        trigger_on_life_zero(state, opp, me, state.effects_overlay)
                    if not opp.life:
                        state.declare_winner(
                            state.players.index(me), f"{opp.name} life=0 (効果ダメージ)")
                        return True
                    continue
                taken = opp.life.pop(0)
                _resolve_life_taken(state, me, opp, taken, by_effect=True)
            state.push_log(f"  効果: 相手リーダーに {n} ダメージ")
        elif k == "force_opp_play_from_hand":
            # OP13-119: 「相手は自身の手札から (cost_le) キャラ1枚までを登場させる」 (opp 報酬)。
            # = 相手プレイヤーの行動。 AI opp / 人間 opp いずれも「無料でキャラを出せる」ので最善は
            # 出すこと → 最も価値の高い (power高) char を count 枚 登場 (= opp の最適 = 人間も同様)。
            spec_val = v if isinstance(v, dict) else {}
            # OP13-119: 「そうした場合 (= bounce した場合)」 のみ発動。 直前 return_to_hand が
            # 実際に bounce したかを gate (bounce なしなら opp 報酬なし)。
            if spec_val.get("require_prior_bounce") and not getattr(
                    state, "last_return_to_hand_success", False):
                continue
            _cle = spec_val.get("cost_le")
            _cnt = int(spec_val.get("count", 1))
            cands = [(i, c) for i, c in enumerate(opp.hand)
                     if c.category == Category.CHARACTER
                     and (_cle is None or int(getattr(c, "cost", 0) or 0) <= int(_cle))]
            cands.sort(key=lambda ic: -(int(getattr(ic[1], "power", 0) or 0)))
            picked_idxs, played = set(), 0
            for i, c in cands:
                if played >= _cnt or not opp.can_play_character():
                    break
                opp.characters.append(InPlay.of(c, sickness=True))
                picked_idxs.add(i)
                played += 1
                state.push_log(f"  効果: 相手が手札からコスト{_cle}以下を登場 → {c.name}")
            if picked_idxs:
                opp.hand = [c for i, c in enumerate(opp.hand) if i not in picked_idxs]
        elif k == "force_opp_discard":
            # 相手手札からランダム N 枚捨てさせる (= trash_opp_hand_random と同義のエイリアス)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            for _ in range(n):
                if not opp.hand:
                    break
                idx = state.rng.randrange(len(opp.hand))
                opp.trash.append(opp.hand.pop(idx))
            state.push_log(f"  効果: 相手手札 {n} 枚捨て (force)")
        elif k == "return_to_deck_bottom":
            # 対象 (相手 or 自分のキャラ) を持ち主のデッキの下に置く
            #   v の 3 形式に対応 (ko / return_to_hand と 同じ target 解決):
            #     (1) str        → そのまま target 文字列
            #     (2) {type,filter} → v を そのまま _resolve_target へ (canonical、
            #         current_power_le 等の filter を 正しく効かせる。 EB02-027 等)
            #     (3) {target: ...} → 従来通り 内側 spec を 抽出 (OP04-056 等)
            if isinstance(v, dict) and "target" in v:
                target_spec = v.get("target", "one_opponent_character_le_5000")
            elif isinstance(v, dict):
                target_spec = v
            elif isinstance(v, str):
                target_spec = v
            else:
                target_spec = "one_opponent_character_le_5000"
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="return_to_deck_bottom", outer_value=v,
            )
            _rtd_any = False
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect or t.static_ko_immune:
                        continue
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay,
                        by_opp_effect=True, leave_kind="return_to_deck_bottom",
                    ):
                        continue
                    opp.characters.remove(t)
                    opp.deck.append(t.card)
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} を相手デッキ底へ")
                    _rtd_any = True
                    if state.effects_overlay:
                        trigger_on_self_chara_leave_by_opp_effect(
                            state, opp, me, state.effects_overlay, victim_card=t.card)
                elif t in me.characters:
                    me.characters.remove(t)
                    me.deck.append(t.card)
                    if t.attached_dons > 0:
                        me.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} を自デッキ底へ")
                    _rtd_any = True
            if _rtd_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "untap_chara":
            # 「自分のキャラ N 枚をアクティブにする」 (= rested→active)
            spec = v if isinstance(v, dict) else {"target": "one_self_character_any", "limit": 1}
            target_spec = spec.get("target", "one_self_character_any")
            limit = int(spec.get("limit", 1))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="untap_chara", outer_value=target_spec)
            for t in targets[:limit]:
                t.rested = False
            state.push_log(f"  効果: 自キャラ untap → {[t.card.name for t in targets[:limit]]}")
        elif k == "shuffle_self_deck":
            # 自分のデッキをシャッフル
            state.rng.shuffle(me.deck)
            me.known_bottom_card_ids.clear()
            me.known_top_card_ids.clear()
            state.push_log(f"  効果: 自デッキシャッフル")
        elif k == "trash_to_hand":
            # 自分のトラッシュからカード N 枚 (filter 付き) を手札に
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            found = 0
            new_trash = []
            for card in me.trash:
                if found < limit and _matches_filter(card, filt):
                    me.hand.append(card)
                    found += 1
                else:
                    new_trash.append(card)
            me.trash[:] = new_trash
            if found > 0:
                state.push_log(f"  効果: trash {found} 枚を手札へ")
        elif k == "trash_to_deck":
            # 自分のトラッシュから filter 一致のカード N 枚をデッキに戻す。
            # spec: {"filter": {...}, "limit": N, "to": "top"|"bottom" (default bottom),
            #        "shuffle": bool (default False)}
            # 公式: 「自分のトラッシュからカード N 枚を好きな順番でデッキの下/上に置く」 等。
            # 一致 0 件なら False (= 公式 4-10 「場合」 前文不実行 → 後文不実行)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            to_pos = spec.get("to", "bottom")
            shuffle_after = bool(spec.get("shuffle", False))
            picked: list[CardDef] = []
            new_trash: list[CardDef] = []
            for card in me.trash:
                if len(picked) < limit and _matches_filter(card, filt):
                    picked.append(card)
                else:
                    new_trash.append(card)
            if not picked:
                # 公式 4-10: 対象 0 枚 → 解決不能 (前文不実行)
                state.push_log(f"  効果: trash_to_deck 該当なし (不発)")
                return False
            me.trash[:] = new_trash
            if to_pos == "top":
                # デッキ先頭 (= 上) に挿入。 順序は picked のまま (= 先頭が一番上)
                me.deck = picked + me.deck
            else:
                # bottom (default)
                me.deck.extend(picked)
            if shuffle_after:
                state.rng.shuffle(me.deck)
                me.known_bottom_card_ids.clear()
                me.known_top_card_ids.clear()
            state.push_log(
                f"  効果: trash → deck {to_pos} {len(picked)} 枚"
                f"{' (shuffle)' if shuffle_after else ''}"
            )
        elif k == "self_hand_to_size":
            # 自分の手札が N 枚になるように手札を捨てる(捨てる札は人間が選択、 AI は最悪札から)
            target_size = int(v) if not isinstance(v, dict) else int(v.get("size", 5))
            to_discard = len(me.hand) - target_size
            if to_discard > 0 and _request_self_hand_discard(state, me, self_inplay, to_discard):
                return True
            while len(me.hand) > target_size:
                me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
            state.push_log(f"  効果: 自手札を {target_size} 枚に")
        elif k == "draw_to_hand_size":
            # 自分の手札が N 枚になるようにカードを引く (= 不足分のみドロー、 既に N 枚以上なら 0)。
            # 公式: OP02-051 イワンコフ 「自分の手札が3枚になるようにカードを引き」。 捨てはしない。
            target_size = int(v) if not isinstance(v, dict) else int(v.get("size", 3))
            if getattr(me, "block_self_draw_until_turn_end", False):
                state.push_log(f"  効果: 手札{target_size}枚ドロー (このターン中ドロー禁止のため不発)")
            else:
                need = max(0, target_size - len(me.hand))
                if need > 0:
                    me.draw(need)
                state.push_log(f"  効果: 手札が {target_size} 枚になるようドロー (+{need})")
        elif k == "block_chara_play_cost_ge":
            # このターン中、 元々のコスト N 以上のキャラを登場できない
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 7))
            # 元々のコストN以上 限定で 登場禁止 (= action 生成で除外、 OP13-023)。
            me.block_chara_play_cost_ge_threshold = n
            state.push_log(f"  効果: このターン中 元々コスト{n}+ キャラ登場禁止")
        elif k == "ko_opp_stage":
            # 相手のステージ N 枚 KO (cost フィルタオプショナル)
            # cost: int (==), cost_le: int (≤), cost_ge: int (≥)
            spec = v if isinstance(v, dict) else {"limit": 1}
            limit = int(spec.get("limit", 1))
            cost_eq = spec.get("cost")
            cost_le = spec.get("cost_le")
            cost_ge = spec.get("cost_ge")
            def _stage_matches(s):
                if cost_eq is not None and s.card.cost != int(cost_eq):
                    return False
                if cost_le is not None and s.card.cost > int(cost_le):
                    return False
                if cost_ge is not None and s.card.cost < int(cost_ge):
                    return False
                return True
            removed = 0
            kept: list = []
            for s in opp.stages:
                if removed < limit and _stage_matches(s):
                    opp.trash.append(s.card)
                    removed += 1
                else:
                    kept.append(s)
            opp.stages[:] = kept
            if removed > 0:
                state.push_log(f"  効果: 相手ステージ {removed} 枚を KO")
        elif k == "block_chara_play_turn":
            # このターン中、 自分はキャラを登場できない (= 自陣 chara play 禁止)。 OP12-014 等。
            me.block_chara_play_until_turn_end = True
            state.push_log(f"  効果: このターン中、 自キャラ登場禁止")
        elif k == "in_hand_cost_minus" or k == "in_hand_cost_plus":
            # 手札中の自身のカードコスト軽減/増加 (= overlay の in_hand effect で使用)。
            # execute_effect 経由ではなく game.py の _in_hand_cost_minus で別経路扱い。
            # ここでは log のみ (= placeholder)。 OP16-082 錦えもん「このキャラのコスト+3」。
            state.push_log(f"  効果: {k} (= 別経路で計算済)")
        elif k == "optional_after_battle_mutual_ko":
            # 公式: 「【ドン!!×1】このキャラが相手のキャラとバトルしたバトル終了時、
            # バトルした相手のキャラをKOしてもよい。 そうした場合、 このキャラをKOする」 (ST08-013)。
            # 簡略実装: 直近のバトル相手 = state.last_battle_opponent_iid (要 game.py で記録)。
            # 現状は no-op (= 後続 R で完全実装)。
            state.push_log(f"  効果: optional_after_battle_mutual_ko (no-op; ST08-013)")
        elif k == "set_don_deck_size":
            # 公式: 「ゲーム開始時、 ドンデッキの枚数を N にする」 等の setup_modifier。
            # execute_effect 経由ではなく setup_game で読まれる。 ここでは log のみ。
            state.push_log(f"  効果: set_don_deck_size (setup_modifier 経由)")
        elif k == "block_chara_effect_untap_don_turn":
            # 「自分は、 このターン中、 キャラの効果でドン‼をアクティブにできない」
            # (EB04-016 トリ / OP10-030 スモーカー の 「その後、」 節)。
            # ⚠ 公式はこの自己ロックで 【ターン1回】 の無い起動メインの無限ループを防いでいる。
            #   overlay に未実装だったため engine 側の 「起動メインは既定でターン1回」 近似が
            #   フタをしていた (2026-08-04 発覚)。
            me.block_chara_effect_untap_don_until_turn_end = True
            state.push_log("  効果: このターン中、 キャラ効果でのドン アクティブ化 禁止")
        elif k == "block_self_draw_turn":
            # このターン中、 自分の効果でカードを引くことができない
            me.block_self_draw_until_turn_end = True
            state.push_log(f"  効果: このターン中、 自効果ドロー禁止")
        elif k == "prevent_self_life_to_hand_turn":
            # 「自分は、 このターン中、 自分の効果でライフを手札に加えられない」 (OP02-023 等)。
            me.prevent_self_life_to_hand_until_turn_end = True
            state.push_log(f"  効果: このターン中、 自効果ライフ→手札 禁止")
        elif k == "prevent_ko":
            # ターン終了時まで KO 耐性付与。target = self / all_self_characters / {type/filter} dict 等。
            # dict spec ({target:..}/{type:..}/{_iid_picks:..}) も _resolve_target に渡す
            # (= 旧実装は dict を "self" に潰しており ST05-017 の FILM target を無視していた)
            if isinstance(v, str):
                target_spec = v
            elif isinstance(v, dict):
                target_spec = v.get("target", v)
            else:
                target_spec = "self"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="prevent_ko", outer_value=target_spec)
            for t in targets:
                t.ko_immune_until_turn_end = True
            state.push_log(f"  効果: KO 耐性 → {[t.card.name for t in targets]}")
        elif k == "set_cannot_attack":
            # アタック不可 効果。 spec:
            #   - 文字列 target_spec (= 旧 形式、 duration=turn 固定)
            #   - dict {"target": ..., "duration": "turn"|"next_opp_turn_end", "count": N}
            # 公式: 「次の相手のターン終了時まで、 アタックできない」 (OP06-023 / OP07-051 等)
            # count: 「N 枚まで」 上限 (= any_* target を N 枚に絞る。 set_cannot_rest と同形式、
            #   ST19-001 スモーカー「コスト4以下のキャラ2枚まで」 等)。
            if isinstance(v, dict):
                target_spec = v.get("target", "one_opponent_character_any")
                duration = v.get("duration", "turn")
                count = int(v.get("count", 99))
                iid_picks = v.get("_iid_picks")
            else:
                target_spec = v
                duration = "turn"
                count = 99
                iid_picks = None
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_cannot_attack", outer_value=v)
            if iid_picks is not None:
                targets = [t for t in targets if t.instance_id in iid_picks][:count]
            elif len(targets) > count and _should_human_pick(state):
                if _maybe_request_target_pick(
                    state, targets, count, "set_cannot_attack", v, self_inplay,
                    description=f"アタック不能 対象 を {count} 枚 まで 選択",
                ):
                    return False
                targets = targets[:count]
            else:
                targets = targets[:count]
            for t in targets:
                if duration == "next_opp_turn_end":
                    t.cannot_attack_through_opp_turn = True
                else:
                    t.cannot_attack_until_turn_end = True
            state.push_log(f"  効果: アタック不可 ({duration}) → {[t.card.name for t in targets]}")
        elif k == "stay_rested_next_refresh":
            # 「次の (相手の) リフレッシュフェイズでアクティブにならない」
            # target = "one_opponent_character_*" 文字列 か {type/filter} dict。
            # dict spec ({type:..}/{_iid_picks:..}) も _resolve_target に渡す
            # (= 旧実装は dict を "one_opponent_character_any" に潰しており、 ① {type,filter} 指定の
            #  filter 無視 ② 人間 target_pick 再実行時 _iid_picks 無視で無限 target_pick 再表示、 の
            #  人間UXバグがあった。 OP07-026/OP15-077/ST24-004 等)
            target_spec = v if isinstance(v, (str, dict)) else "one_opponent_character_any"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="stay_rested_next_refresh", outer_value=target_spec)
            for t in targets:
                t.stay_rested_next_refresh = True
            state.push_log(f"  効果: 次リフレッシュ非アクティブ → {[t.card.name for t in targets]}")
        elif k == "cost_minus":
            # 「相手/自分 キャラ N 枚のコスト-N」 base_cost 判定 反映。
            # spec: {target, amount, duration: "turn"|"next_opp_turn_end"}
            # 「コスト+N」 は amount 負 で 表現 (= cost を 増やす)。
            spec = v if isinstance(v, dict) else {"target": "one_opponent_character_any", "amount": int(v)}
            target_spec = spec.get("target", "one_opponent_character_any")
            amount = int(spec.get("amount", 1))
            duration = spec.get("duration", "turn")
            # 人間 target_pick 解決時、 outer_value が cost_minus 再実行の spec になる
            # (= resolve_pending_choice が primitive_value に _iid_picks を注入して
            #  execute_effect する)。 amount / duration を outer_value に載せないと再実行
            #  時に amount=1 default に落ち、 公式 -2 が -1 になる (EB01-042 スカーレット等、
            #  power_pump_multi と同型の bug)。 spec 全体を渡して amount/duration を保持する。
            outer_v = {"target": target_spec, "amount": amount, "duration": duration}
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="cost_minus", outer_value=outer_v)
            if state.pending_choice is not None:
                # 人間 target pick 待ち → halt (= power_pump と同様)。
                return True
            for t in targets:
                if duration == "next_opp_turn_end":
                    t.cost_minus_through_opp_turn += amount
                else:
                    t.cost_minus_until_turn_end += amount
            label = f"コスト{amount:+d} ({duration})" if amount < 0 else f"コスト-{amount} ({duration})"
            state.push_log(f"  効果: {label} → {[t.card.name for t in targets]}")
        elif k == "redirect_attack":
            # 「アタック対象変更」 primitive。 spec 形式:
            #   - 文字列: 単一 target_spec (例: "self_leader")
            #   - dict: {"candidates": [<target_spec>, ...]} (= 複数候補から 1 つ 選択)
            #   - dict: {"_iid_picks": [iid]} (= target_pick 解決後 の 再呼出 で iid 直接 指定)
            if isinstance(v, dict) and "_iid_picks" in v:
                # 人間 選択 解決後 の 再呼出
                iid_picks = v["_iid_picks"]
                if iid_picks:
                    state.pending_attack_redirect = int(iid_picks[0])
                    # 該当 InPlay を log 用 に lookup
                    for ip in [me.leader, *me.characters, opp.leader, *opp.characters]:
                        if ip.instance_id == int(iid_picks[0]):
                            state.push_log(f"  アタック対象変更: → {ip.card.name}")
                            break
            elif isinstance(v, dict) and "candidates" in v:
                # 候補 リスト から target 解決 → 複数 なら 人間 選択 modal
                all_targets: list[InPlay] = []
                for cand_spec in v.get("candidates", []):
                    sub = _resolve_target(
                        cand_spec, state, me, opp, self_inplay,
                        outer_kind="redirect_attack_candidate",
                        outer_value=cand_spec,
                    )
                    for t in sub:
                        if t not in all_targets:
                            all_targets.append(t)
                if not all_targets:
                    pass  # 候補 0 → 効果 不発
                elif len(all_targets) == 1 or not _should_human_pick(state):
                    # 1 候補 / AI 操作 中 → 自動 選択 (= リーダー 優先)
                    chosen = all_targets[0]
                    state.pending_attack_redirect = chosen.instance_id
                    state.push_log(f"  アタック対象変更: → {chosen.card.name}")
                else:
                    # 人間 操作中 + 複数候補 → target_pick modal
                    _maybe_request_target_pick(
                        state, all_targets, limit=1,
                        primitive_kind="redirect_attack",
                        primitive_value=v,
                        self_inplay=self_inplay,
                        description="アタック対象 変更 先 (= リーダー or キャラ から 1 つ)",
                    )
            else:
                # 旧 形式: 文字列 単一 target_spec
                target_spec = v if isinstance(v, str) else "self_leader"
                targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="redirect_attack", outer_value=target_spec)
                if targets:
                    state.pending_attack_redirect = targets[0].instance_id
                    state.push_log(f"  アタック対象変更: → {targets[0].card.name}")
        elif k == "block_chara_play":
            # 「このターン中、キャラを登場できない」(OP14-020 緑ミホークの起動メイン代償)。
            # bool/任意値で True 固定。Phase.END でクリア。
            me.block_chara_play_until_turn_end = True
            state.push_log(f"  効果: このターン中キャラ登場禁止")
        elif k == "reduce_play_cost":
            # 「自分の次に登場/発動するキャラ/イベントのコストを N 軽減 (このターン中)」
            # spec: int (amount) or {"amount": N}
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            me.play_cost_reduction += n
            state.push_log(f"  効果: 自プレイコスト -{n} (累積 {me.play_cost_reduction})")
        elif k == "attach_don":
            # 自キャラ/リーダーにアクティブドン N 付与。
            # 構造: {"target": "self_leader", "count": 2}
            #        {"target": "all_self_team", "count": 1, "per_target": true}
            # per_target=true は 各 target に count 枚ずつ付与 (= R4 拡張)。
            # 公式: 「自分のリーダーとキャラすべてにレストのドン!!1枚ずつまでを付与」 (OP14-105) や
            # 「自分の特徴Xを持つキャラすべてにレストのドン!!1枚ずつまでを付与」 (OP04-004) 用。
            spec = v if isinstance(v, dict) else {"target": "self_leader", "count": 1}
            target_spec = spec.get("target", "self_leader")
            n = int(spec.get("count", 1))
            per_target = bool(spec.get("per_target", False))
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="attach_don", outer_value=v,
            )
            if not targets:
                continue
            if per_target:
                # 各 target に min(n, 残り don_active) を付与。 1 体ずつ消費。
                # max_targets (= 「N 枚まで」) があれば先頭 N 体に絞る (attach_rested_don と同じ)。
                mt = spec.get("max_targets")
                if mt is not None:
                    targets = targets[: int(mt)]
                attached_log: list[str] = []
                for t in targets:
                    give = min(n, me.don_active)
                    if give <= 0:
                        break
                    me.don_active -= give
                    t.attached_dons += give
                    attached_log.append(f"{t.card.name}+{give}")
                state.push_log(f"  効果: ドン付与 (per_target) → {attached_log}")
            else:
                n = min(n, me.don_active)
                if n <= 0:
                    continue
                # 1 体目に全部付与する単純実装 (複数対象は max +N 分散)
                target = targets[0]
                me.don_active -= n
                target.attached_dons += n
                state.push_log(f"  効果: ドン{n}付与 → {target.card.name} (P={target.power})")
        elif k == "attach_rested_don":
            # 「自キャラ/リーダーに レストのドン N 枚を付与」 (ST08-001 等)。
            # ソースは me.don_rested。 付与後は attached_dons の一部として保持
            # (= レフレッシュ時にコストエリアに戻る = 通常の attached_dons と同じ動作)。
            # per_target=true: 各 target に count 枚ずつ付与 (R4 拡張、 OP14-105 用)。
            spec = v if isinstance(v, dict) else {"target": "self_leader", "count": 1}
            target_spec = spec.get("target", "self_leader")
            n = int(spec.get("count", 1))
            per_target = bool(spec.get("per_target", False))
            # to_opp: 「相手のキャラに相手の(レスト/コストエリアの)ドンを付与」 (OP15-008/025/028 等)。
            # ソースは相手のドン (= opp)、 target も相手キャラ。 相手のドンを拘束する tempo 妨害。
            to_opp = bool(spec.get("to_opp", False))
            from_cost_area = bool(spec.get("from_cost_area", False))
            don_owner = opp if to_opp else me

            def _take_rested(k):
                # コストエリア指定なら active も使う (= rested 優先)。
                taken = min(k, don_owner.don_rested)
                don_owner.don_rested -= taken
                if from_cost_area and taken < k:
                    more = min(k - taken, don_owner.don_active)
                    don_owner.don_active -= more
                    taken += more
                return taken

            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="attach_rested_don", outer_value=v,
            )
            if not targets:
                continue
            # up_to: 公式「ドン!!N枚まで付与」 = 人間は付与枚数(1..max)を選べる
            # (= OP15-058 紫エネル)。 target は既に target_pick で確定済。 human + max>=2
            # のときだけ option_pick を出す (= AI は従来通り最大付与、 max<2 は選択不要)。
            up_to = isinstance(v, dict) and bool(v.get("up_to"))
            if (up_to and not per_target and not to_opp
                    and targets and _should_human_pick(state)):
                avail = don_owner.don_rested + (
                    don_owner.don_active if from_cost_area else 0
                )
                max_n = min(n, avail)
                if max_n >= 2:
                    tgt_iid = targets[0].instance_id
                    base = {kk: vv for kk, vv in v.items() if kk != "up_to"}
                    opts = []
                    for cnt in range(max_n, 0, -1):
                        inner = dict(base)
                        inner["count"] = cnt
                        inner["target"] = {"_iid_picks": [tgt_iid]}
                        opts.append(
                            {"label": f"ドン!!{cnt}枚 付与",
                             "do": [{"attach_rested_don": inner}]}
                        )
                    state.pending_choice = {
                        "kind": "option_pick",
                        "optional": True,
                        "options": [
                            {"idx": i, "label": o["label"]}
                            for i, o in enumerate(opts)
                        ],
                        "_full_options": opts,
                        "_self_inplay_iid": (
                            self_inplay.instance_id if self_inplay else None
                        ),
                        "description": (
                            f"{targets[0].card.name} に付与するドン!!枚数を選択 "
                            f"(0〜{max_n}枚)"
                        ),
                    }
                    state.push_log(
                        f"  効果: レストドン付与 枚数選択待ち (最大 {max_n}枚)"
                    )
                    return True
            if per_target:
                # max_targets: 「キャラ N 枚まで に 1 枚ずつ」 の N (公式 OP08-001 チョッパー
                # 「自分の《動物》か《ドラム王国》キャラ **3枚まで** にレストのドン1枚ずつまで」)。
                # ⚠ 未実装で **全対象** に配っていた (2026-08-03 キー非対称走査で発覚)。
                mt = spec.get("max_targets")
                if mt is not None:
                    targets = targets[: int(mt)]
                attached_log: list[str] = []
                for t in targets:
                    give = _take_rested(n)
                    if give <= 0:
                        break
                    t.attached_dons += give
                    attached_log.append(f"{t.card.name}+{give}")
                state.push_log(f"  効果: レストドン付与 (per_target) → {attached_log}")
            else:
                give = _take_rested(n)
                if give <= 0:
                    continue
                target = targets[0]
                target.attached_dons += give
                state.push_log(f"  効果: レストドン{give}付与 → {target.card.name}")
        elif k == "power_pump_per_target_attached_don":
            # 公式: 「相手のキャラすべては、 そのキャラに付与されているドン‼1枚につき、
            # このターン中、 パワー-1000。」 (OP15-008 クリーク等)。
            # spec: {"target": "all_opponent_characters", "amount_per_don": -1000, "duration": "turn"}
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "all_opponent_characters")
            amount_per = int(spec_val.get("amount_per_don", -1000))
            duration = spec_val.get("duration", "turn")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="power_pump_per_target_attached_don", outer_value=target_spec)
            for t in targets:
                buff = amount_per * t.attached_dons
                if buff == 0:
                    continue
                if duration == "static":
                    t.static_buff += buff
                elif duration == "battle":
                    t.battle_buff += buff
                else:
                    t.turn_buff += buff
            state.push_log(
                f"  効果: 各キャラに don×{amount_per:+d} 適用 → "
                f"{[(t.card.name, t.attached_dons) for t in targets]}"
            )
        elif k == "set_attack_cost_discard_hand":
            # 公式: 「対象は、 次の相手ターン終了時まで、 アタックする際、 自身の手札 N 枚を
            # 捨てなければアタックできない」 (OP08-043 エドワード等)。
            # spec: {"target": "all_opponent_characters", "n": 2, "duration": "next_opp_turn_end"}
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "all_opponent_characters")
            n = int(spec_val.get("n", 2))
            duration = spec_val.get("duration", "next_opp_turn_end")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_attack_cost_discard_hand", outer_value=target_spec)
            me_idx = state.players.index(me)
            for t in targets:
                t.attack_cost_discard_hand_n = max(t.attack_cost_discard_hand_n, n)
                if duration == "next_opp_turn_end":
                    t.attack_cost_discard_hand_applier_idx = me_idx
                    t.attack_cost_discard_hand_applied_turn = state.turn_number
            state.push_log(
                f"  効果: アタック時手札{n}枚捨て必須 ({duration}) → {[t.card.name for t in targets]}"
            )
        elif k == "schedule_at_opp_main_phase_start":
            # 「次の相手のメインフェイズ開始時に〜」 用 delayed effect の登録 (PRB02-005 ルフィ等)。
            # spec: {"do": [<primitive>...]}
            # 効果保有側 (= me) の delayed_at_opp_main_phase_start に append → 相手 MAIN 開始時に flush。
            spec_val = v if isinstance(v, dict) else {}
            me.delayed_at_opp_main_phase_start.append(spec_val)
            state.push_log(f"  効果: 次の相手 MAIN 開始時に発動を予約")
        elif k == "peek_self_life_top":
            # 公式: 「自分のライフの上から N 枚を表向きにできる」 (OP12-102 しらほし等)。
            # ゲーム的には情報公開のみで状態変化なし。 シンプル実装で log のみ。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            peeked = me.life[:n]
            state.push_log(f"  効果: ライフ上 {n} 枚を表向き → {[c.name for c in peeked]}")
        elif k == "reveal_self_life_top_pump_per_cost":
            # 「自分のライフの上から1枚を公開。 公開カードのコスト1につき このキャラ +per_cost」
            # (= OP15-119 ルフィ)。 ライフは公開のみ (場所変えず)。 self_inplay に turn pump。
            spec_val = v if isinstance(v, dict) else {}
            per = int(spec_val.get("per_cost", 1000))
            if me.life and self_inplay is not None:
                revealed = me.life[0]
                cost = int(getattr(revealed, "cost", 0) or 0)
                self_inplay.turn_buff += per * cost
                state.push_log(f"  効果: ライフ上公開 (コスト{cost}) → 自身 +{per*cost} turn")
        elif k == "peek_opp_deck_top":
            # 公式: 「相手のデッキの上から N 枚を見る」 (OP11-070 プリン等)。
            # 「見る」 = acting player の私的情報。 状態変化なし、 カードは相手デッキ上に残る。
            # public log (= state.log は両者可視) には カード名を出さない (= draw と同じ隠ぺい保護)。
            # acting player の私的知識として state.last_peeked_opp_deck_top に記録 (= AI/UI が利用可)。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            peeked = opp.deck[:n]
            state.last_peeked_opp_deck_top = {
                "viewer_idx": state.players.index(me),
                "card_ids": [c.card_id for c in peeked],
            }
            if not peeked:
                state.push_log(f"  効果: 相手デッキ上を確認 → デッキ空")
            else:
                state.push_log(f"  効果: 相手デッキ上 {len(peeked)} 枚を確認 (私的情報)")
        elif k == "play_self_from_trash":
            # 「このキャラカードをトラッシュから登場させる」 (= OP14-120 クロコダイル on_ko)。
            # on_ko は self_inplay=None だが state.current_source_card_id に この card_id がある。
            src_cid = getattr(state, "current_source_card_id", None)
            card = next((c for c in me.trash if c.card_id == src_cid), None)
            if card is None:
                state.push_log(f"  効果: play_self_from_trash 対象なし (trash に {src_cid} なし)")
                return False
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
            me.trash.remove(card)
            ip = InPlay.of(card, rested=False, sickness=True)
            me.characters.append(ip)
            state.push_log(f"  効果: トラッシュから自身 {card.name} を登場")
            if state.effects_overlay:
                trigger_on_play(state, me, opp, ip, state.effects_overlay)
        elif k == "reveal_life_top_play":
            # 公式: 「自分のライフの上から1枚を公開し、 そのカードが <filter> の場合、 登場させてもよい。
            #   登場させた場合、 <then>」 (= OP10-022 ロー / ST13-007 サボ / ST13-010 エース)。
            # 公開のみ (= 場所変えず)。 マッチ + 登場 した時だけ life から除去 + then 実行。
            # 非マッチ / 未登場 なら life はそのまま (= ライフ枚数不変)。
            # AI 簡易: マッチなら登場 (公式は「してもよい」 任意だが ライフからの無償登場は期待値プラス)。
            # TODO: 人間 acting 時は modal で「登場/skip」 を委ねる (= reveal_top_play 同様)。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            rested_flag = bool(spec_val.get("rested", False))
            then = spec_val.get("then", []) or []
            if not me.life:
                state.push_log(f"  効果: ライフ公開 → ライフ空 (不発)")
            else:
                revealed = me.life[0]
                matched = (
                    revealed.category == Category.CHARACTER
                    and _matches_filter(revealed, filt)
                )
                state.push_log(
                    f"  効果: ライフ上1枚公開 → {revealed.name} ({'マッチ' if matched else '不マッチ'})"
                )
                if matched:
                    me.life.pop(0)
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    ip = InPlay.of(revealed, rested=rested_flag, sickness=True)
                    me.characters.append(ip)
                    state.push_log(f"  効果: ライフから登場 → {revealed.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                    # 「登場させた場合」 の後続効果 (= leader +2000 等)。 source context は self_inplay。
                    for prim in then:
                        execute_effect(prim, state, me, opp, self_inplay)
        elif k == "conditional":
            # 「その後、 <if> の場合、 <do>」 を 1 do-item で表す (= 1 entry 内の後続条件分岐)。
            # entry を分割できない activate_main (= 1 entry = 1 起動能力) 等で使う。
            # if は spec 内にネストするので dead-gate invariant (= do-item 直下の if) には該当しない。
            spec_val = v if isinstance(v, dict) else {}
            cond = spec_val.get("if", {})
            if eval_condition(cond, state, me, self_inplay):
                for prim in spec_val.get("do", []):
                    execute_effect(prim, state, me, opp, self_inplay)
        elif k == "set_base_cost_timed":
            # 公式: 「(target) は、 次の相手のターン終了時まで、 コスト+N」 (EB02-041 メリー号等)。
            # spec: {"target": <target_spec>, "delta": 2, "duration": "next_opp_turn_end"}
            # 既存 set_base_cost (static) と異なり期間限定。 cost_override は absolute or delta。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "self")
            duration = spec_val.get("duration", "next_opp_turn_end")
            # ⚠ outer_value は spec 全体 (v) を渡す。 target_spec (文字列) だと 人間 target_pick の
            # 再実行時に amount/delta/duration が失われ cost が変わらない (= 人間レビュー行きバグ修正)。
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_base_cost_timed", outer_value=v)
            me_idx = state.players.index(me)
            for t in targets:
                if "amount" in spec_val:
                    amount = int(spec_val["amount"])
                    cur = t.next_opp_turn_end_base_cost_override
                    if cur is None:
                        cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                    new_val = amount
                else:
                    delta = int(spec_val.get("delta", 0))
                    cur = t.next_opp_turn_end_base_cost_override
                    if cur is None:
                        cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                    new_val = max(0, cur + delta)
                t.next_opp_turn_end_base_cost_override = new_val
                if duration == "next_opp_turn_end":
                    t.next_opp_turn_end_base_cost_override_applier_idx = me_idx
                    t.next_opp_turn_end_base_cost_override_applied_turn = state.turn_number
            state.push_log(
                f"  効果: コスト変更 ({duration}) → {[(t.card.name, t.next_opp_turn_end_base_cost_override) for t in targets]}"
            )
        elif k == "rest_self_don_for_battle_buff_per_don":
            # 公式: 「自分のドン!! を任意の枚数レストにできる。 レストにしたドン!! 1 枚につき、
            # (target) は、 このバトル中、 パワー+N」 (OP13-001 ルフィ等)。
            # spec: {"target": "self_leader", "amount_per_rest": 2000, "max": 5}
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "self_leader")
            amount_per = int(spec_val.get("amount_per_rest", 2000))
            max_n = int(spec_val.get("max", 5))
            # AI 簡易: don_active を最大数まで rest (= 防御強化最大化)
            rest_n = min(me.don_active, max_n)
            if rest_n <= 0:
                state.push_log(f"  効果: ドンrest不可 (active=0)")
                return False
            me.don_active -= rest_n
            me.don_rested += rest_n
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="rest_self_don_for_battle_buff_per_don", outer_value=target_spec)
            buff = amount_per * rest_n
            for t in targets:
                t.battle_buff += buff
            state.push_log(
                f"  効果: 自don {rest_n} 枚 rest → battle_buff +{buff} 付与"
            )
        elif k == "keep_opp_rested_don_next_refresh":
            # 「相手のレストのドン!! N 枚までは、 次の相手のリフレッシュでアクティブにならない」
            # OP10-033 ナミ 等。 spec: int N | dict {"amount": N}
            n_spec = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            actually = min(n_spec, opp.don_rested)
            opp.next_refresh_kept_rested_don += actually
            state.push_log(f"  効果: 相手レストドン {actually} 枚 次リフレッシュで起きない")
        elif k == "set_cannot_rest":
            # 「対象 N 枚 まで は、 次の (相手) ターン終了時まで、 レストにできない」
            # (OP14-033 / OP14-069 ドフラ 等)。 spec.count で 上限指定 (= 「N 枚 まで」)。
            # rest プリミティブで cannot_be_rested_buff のあるキャラはスキップされる。
            # 適用時 applier_idx と applied_turn を記録し、 _reset_turn_buff でクリア。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = v if isinstance(v, str) else spec_val.get("target", "all_self_characters")
            count = int(spec_val.get("count", 99)) if isinstance(v, dict) else 99
            iid_picks = spec_val.get("_iid_picks") if isinstance(v, dict) else None
            # `any_*` target は 「filter 一致 全員」 を 返す ので count 上限 を 後段 で 適用。
            # outer_value に count 込み の v を 渡し て、 modal 解決後 の 再実行 で
            # 同 count + _iid_picks 経由 path に 入る ように する。
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="set_cannot_rest", outer_value=v,
            )
            if iid_picks is not None:
                # 既 picked: count 上限 適用 (= UI 側 制約 と 二重 防御)
                targets = [t for t in targets if t.instance_id in iid_picks][:count]
            elif len(targets) > count and _should_human_pick(state):
                # 人間 acting + 候補 > count → modal で 選ばせる
                if _maybe_request_target_pick(
                    state, targets, count, "set_cannot_rest", v, self_inplay,
                    description=f"レスト不能 対象 を {count} 枚 まで 選択",
                ):
                    return False
                targets = targets[:count]
            else:
                # AI / 候補 <= count: 既存 挙動 (= 先頭 N 枚)
                targets = targets[:count]
            me_idx = state.players.index(me)
            for t in targets:
                t.cannot_be_rested_buff = True
                t.cannot_be_rested_applier_idx = me_idx
                t.cannot_be_rested_applied_turn = state.turn_number
            state.push_log(f"  効果: レスト不能 → {[t.card.name for t in targets]}")
        elif k == "mill_self_top":
            # 自分のデッキ上 N 枚をトラッシュに置く。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            milled = []
            for _ in range(n):
                if not me.deck:
                    break
                c = me.deck.pop(0)
                me.trash.append(c)
                milled.append(c.name)
            state.push_log(f"  効果: 自デッキ {len(milled)} 枚 trash → {milled}")
        elif k == "mill_top_then":
            # 「自分のデッキの上から N 枚をトラッシュに置く。 置いたカードが <filter> の場合、 <then>」
            # (= OP08-096「コスト6以上だった場合」)。 N=1 default。 milled の いずれかが filter
            # 一致なら then を発動。 デッキ空で 0 枚なら filter 不一致扱い (then 不発)。
            spec_val = v if isinstance(v, dict) else {}
            n = int(spec_val.get("count", 1))
            filt = spec_val.get("filter", {})
            then_specs = spec_val.get("then", []) or []
            milled = []
            for _ in range(n):
                if me.deck:
                    milled.append(me.deck.pop(0))
                    me.trash.append(milled[-1])
            matched = any(_matches_filter(c, filt) for c in milled)
            state.push_log(
                f"  効果: デッキ上{len(milled)}枚トラッシュ → {[c.name for c in milled]} "
                f"({'条件成立' if matched else '条件不成立'})"
            )
            if matched:
                for es in then_specs:
                    execute_effect(es, state, me, opp, self_inplay)
        elif k == "look_top_reorder":
            # 自分のデッキ上 N 枚を見て、 好きな順番で デッキの上/下 に置く。
            # spec:
            #   {"depth": N, "to": "top"|"bottom"|"choice"|"split"}
            # 公開情報のみで決まる効果なので AI に判断させる余地は少ない。 簡略実装:
            #   to="top": 順番そのままで戻す (= no-op の安全選択)
            #   to="bottom": 上 N 枚をデッキ末尾に移動
            #   to="choice": ヒューリスティック → トリガー持ち / コスト低が手前に来るよう並び替え
            #   to="split": match_filter 一致は match_to、 残りは remain_to へ分割 (拡張)
            #     spec: {"depth": N, "to": "split",
            #            "match_filter": {...}, "match_to": "top"|"bottom"|"trash"|"hand",
            #            "remain_to": "top"|"bottom"|"trash"}
            spec = v if isinstance(v, dict) else {"depth": int(v), "to": "top"}
            depth = int(spec.get("depth", 1))
            to_pos = spec.get("to", "top")
            if depth <= 0 or not me.deck:
                continue
            top_n = me.deck[:depth]
            rest = me.deck[depth:]
            if to_pos == "bottom":
                me.deck = rest + top_n
                state.push_log(f"  効果: デッキ上 {len(top_n)} 枚をデッキ下へ")
            elif to_pos == "choice":
                # ヒューリスティック: 低コスト → 高コスト の順に並び替えて上に置く (早期展開優先)
                top_n.sort(key=lambda c: (c.cost, c.name))
                me.deck = top_n + rest
                state.push_log(f"  効果: デッキ上 {len(top_n)} 枚をコスト昇順に並び替え")
            elif to_pos == "split":
                # 公式表現例: 「デッキ上 5 枚を見て、 トリガー持ちカードを手札に加え、
                #              残りを好きな順番でデッキの下に置く」
                # match_filter で抽出、 match_to (= 一致先) と remain_to (= 残り先) に振り分ける。
                # 「hand」「trash」 へは順序問わず、 「top」「bottom」 はそのままの順で挿入。
                match_filter = spec.get("match_filter", {})
                match_to = spec.get("match_to", "hand")
                remain_to = spec.get("remain_to", "bottom")
                # 後で deck に戻す残り = rest を起点にする
                me.deck = rest
                matched: list[CardDef] = []
                remain: list[CardDef] = []
                for c in top_n:
                    if _matches_filter(c, match_filter):
                        matched.append(c)
                    else:
                        remain.append(c)
                # matched 振り分け
                if match_to == "hand":
                    me.hand.extend(matched)
                elif match_to == "trash":
                    me.trash.extend(matched)
                elif match_to == "top":
                    me.deck = matched + me.deck
                elif match_to == "bottom":
                    me.deck.extend(matched)
                # remain 振り分け
                if remain_to == "trash":
                    me.trash.extend(remain)
                elif remain_to == "top":
                    me.deck = remain + me.deck
                elif remain_to == "hand":
                    me.hand.extend(remain)
                else:  # bottom (default)
                    me.deck.extend(remain)
                state.push_log(
                    f"  効果: デッキ上 {depth} 枚 split"
                    f" (match={len(matched)}→{match_to}, remain={len(remain)}→{remain_to})"
                )
            else:
                # to="top": 順番維持 (= no-op)
                state.push_log(f"  効果: デッキ上 {len(top_n)} 枚を確認 (順番維持)")
        elif k == "play_self":
            # このカードを登場させる。 trigger / on_ko 等 self_inplay=None の場面で使う。
            # source_card_id は state.current_source_card_id にスタックされている。
            # 検索順: me.trash (= trigger 後 / KO 後)、 me.hand (= 通常)。
            # play_self:false は「登場させない」 = no-op (= 旧 overlay の誤用防止 guard)。
            if v is False:
                continue
            src_cid = (
                self_inplay.card.card_id if self_inplay
                else getattr(state, "current_source_card_id", None)
            )
            if not src_cid:
                continue
            # 既に場に同 iid のものが残っているなら no-op (二重登場防止)
            if self_inplay is not None and self_inplay in me.characters:
                continue
            found_card = None
            for zone_name, zone in (("trash", me.trash), ("hand", me.hand)):
                for i, c in enumerate(zone):
                    if c.card_id == src_cid and c.category in (Category.CHARACTER, Category.STAGE):
                        found_card = zone.pop(i)
                        state.push_log(f"  効果: このカードを登場 ({zone_name} → 場)")
                        break
                if found_card:
                    break
            if not found_card:
                continue
            if found_card.category == Category.STAGE:
                # STAGE 版 (= OP03-098【トリガー】このステージを登場)。 game.py:1348 と同様、 既存
                # ステージ (MAX 超) は持ち主のトラッシュへ、 stages へ配置 (sickness/rested 無関係)。
                if len(me.stages) >= me.MAX_STAGES:
                    old = me.stages.pop()
                    me.trash.append(old.card)
                    if old.attached_dons > 0:
                        me.don_rested += old.attached_dons
                    state.push_log(f"  既存ステージ {old.card.name} をトラッシュへ")
                ip = InPlay.of(found_card, rested=False, sickness=False)
                me.stages.append(ip)
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, ip, state.effects_overlay)
                continue
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
            # spec {"rested": true} で 「レストで登場」 (= 蘇生系 ST30-008/OP03-013 等) を honor。
            # 旧コードは rested=False ハードコードで「レストで」 を無視していた。
            _rested = bool(v.get("rested")) if isinstance(v, dict) else False
            ip = InPlay.of(found_card, rested=_rested, sickness=True)
            me.characters.append(ip)
            if state.effects_overlay:
                trigger_on_play(state, me, opp, ip, state.effects_overlay)
        elif k == "fire_self_main":
            # 「このカードの【メイン】効果を発動する」 (= fire_self_effect when_kind="main" の shorthand、
            # 10 cards 使用、 trigger 系)。 値 (= True) は 互換性 のため 無視 する。
            spec = {"when_kind": "main"}
            src_cid = (
                self_inplay.card.card_id if self_inplay
                else getattr(state, "current_source_card_id", None)
            )
            if not src_cid:
                continue
            depth = getattr(state, "_fire_self_depth", 0)
            if depth >= 2:
                state.push_log(f"  効果コピー: 再帰深度上限 (skip)")
                continue
            state._fire_self_depth = depth + 1
            try:
                bundle = state.effects_overlay.get(src_cid) if state.effects_overlay else None
                if bundle is None:
                    continue
                for eff in bundle.effects:
                    if eff.get("when") != "main":
                        continue
                    if not eval_all_conditions(eff, state, me, self_inplay):
                        continue
                    for prim in eff.get("do", []):
                        execute_effect(prim, state, me, opp, self_inplay)
                state.push_log(f"  効果: 自身の【メイン】効果を発動")
            finally:
                state._fire_self_depth = depth
        elif k == "opp_don_to_deck":
            # 「相手のドン N 枚を ドンデッキ に 戻す」 (= return_opp_don の alias、 OP02-085 マゼラン)。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            removed = 0
            # active 優先 で 戻す (= opp に 不利)
            from_active = min(opp.don_active, n)
            opp.don_active -= from_active
            removed += from_active
            from_rested = min(opp.don_rested, n - removed)
            opp.don_rested -= from_rested
            removed += from_rested
            opp.don_remaining_in_deck += removed
            state.push_log(f"  効果: 相手 ドン {removed} 枚 ドンデッキ へ")
            if removed > 0 and state.effects_overlay:
                # 相手 視点 の 「自分のドン が ドンデッキ に 戻った時」 trigger
                trigger_on_self_don_returned_to_deck(state, opp, me, state.effects_overlay, count=removed)
        elif k == "hand_to_deck_bottom":
            # 「自分の手札 N 枚を デッキの下 に 置く」 = self_hand_to_deck_bottom の alias。
            # 2026-07-08 監査: 旧実装は「先頭 N 枚」自動で 人間が選べなかった。 → 人間選択 modal +
            # AI ヒューリスティック(コスト最高=死札)を持つ self_hand_to_deck_bottom に委譲。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            return execute_effect({"self_hand_to_deck_bottom": {"amount": n, "to": "bottom"}},
                                  state, me, opp, self_inplay)
        elif k == "summon_stage_from_deck_with_feature":
            # 「自分の特徴 X を持つステージ 1 枚 を デッキ から 場 に 出す」 (OP13-079 等)。
            # spec: "特徴名" (= string)
            feature = str(v) if not isinstance(v, dict) else str(v.get("feature", ""))
            found_idx = None
            for i, c in enumerate(me.deck):
                if c.category == Category.STAGE and feature in c.features:
                    found_idx = i
                    break
            if found_idx is None:
                state.push_log(f"  効果: デッキから ステージ 登場 (= 特徴《{feature}》 該当 なし)")
                state.rng.shuffle(me.deck)
                me.known_bottom_card_ids.clear()
                me.known_top_card_ids.clear()
                return False
            card = me.deck.pop(found_idx)
            # 自場 ステージ 上限 (= 公式 1 枚) チェック
            if me.stages:
                old = me.stages.pop(0)
                me.trash.append(old.card)
                if old.attached_dons > 0:
                    me.don_rested += old.attached_dons
                state.push_log(f"  効果: 既存ステージ {old.card.name} → trash")
            me.stages.append(InPlay.of(card, rested=False, sickness=False))
            state.push_log(f"  効果: デッキ → ステージ 登場 {card.name} (特徴《{feature}》)")
            state.rng.shuffle(me.deck)
            me.known_bottom_card_ids.clear()
            me.known_top_card_ids.clear()
        elif k == "fire_event_main_from_trash":
            # 「自分のトラッシュにある(filter)イベント1枚までの、【メイン】効果を発動する」
            # (EB03-031 サンジ)。 AI: 該当イベントの先頭1枚の main do を発火 (イベントはトラッシュに残留)。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            depth = getattr(state, "_fire_self_depth", 0)
            if depth >= 2:
                continue
            chosen = None
            for c in me.trash:
                if c.category == Category.EVENT and _matches_filter(c, filt):
                    chosen = c
                    break
            if chosen is None:
                state.push_log("  効果: トラッシュに該当イベントなし (不発)")
            else:
                bundle = state.effects_overlay.get(chosen.card_id) if state.effects_overlay else None
                if bundle is not None:
                    state._fire_self_depth = depth + 1
                    try:
                        for ev in bundle.effects:
                            if ev.get("when") == "main" and eval_all_conditions(ev, state, me, self_inplay):
                                for prim in ev.get("do", []):
                                    execute_effect(prim, state, me, opp, self_inplay)
                                break
                    finally:
                        state._fire_self_depth = depth
                state.push_log(f"  効果: トラッシュのイベント {chosen.name} の【メイン】発動")
        elif k == "fire_self_effect":
            # このカードの【XXX】効果を発動する。 同 bundle 内の指定 when 効果を再発火。
            # 再帰防止: state._fire_self_depth で深度制限 (max 2)。
            spec = v if isinstance(v, dict) else {"when_kind": str(v)}
            when_kind = spec.get("when_kind", "main")
            src_cid = (
                self_inplay.card.card_id if self_inplay
                else getattr(state, "current_source_card_id", None)
            )
            if not src_cid:
                continue
            depth = getattr(state, "_fire_self_depth", 0)
            if depth >= 2:
                state.push_log(f"  効果コピー: 再帰深度上限 (skip)")
                continue
            state._fire_self_depth = depth + 1
            try:
                bundle = state.effects_overlay.get(src_cid) if state.effects_overlay else None
                if bundle is None:
                    continue
                for eff in bundle.effects:
                    if eff.get("when") != when_kind:
                        continue
                    if not eval_all_conditions(eff, state, me, self_inplay):
                        continue
                    for prim in eff.get("do", []):
                        execute_effect(prim, state, me, opp, self_inplay)
                state.push_log(f"  効果: 自身の【{when_kind}】効果を発動")
            finally:
                state._fire_self_depth = depth
        elif k == "rest_opp_don":
            # 相手の active ドンを N 枚レストにする (ST02-008 等)。 不足はそのまま。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            taken = min(n, opp.don_active)
            opp.don_active -= taken
            opp.don_rested += taken
            state.push_log(f"  効果: 相手ドン{taken}枚レスト")
        elif k == "opp_trash_to_deck_bottom":
            # 公式: 「相手は自身のトラッシュから (filter) カード N 枚を、 好きな順番でデッキの下に置く」
            # OP15-091 / OP05-079 / OP11-091 等。 spec: int N | {"count": N, "filter": {...}}
            if isinstance(v, dict):
                count = int(v.get("count", 1))
                filt = v.get("filter", {})
            else:
                count = int(v)
                filt = {}
            picked = []
            new_trash = []
            for c in opp.trash:
                if len(picked) < count and _matches_filter(c, filt):
                    picked.append(c)
                else:
                    new_trash.append(c)
            if not picked:
                state.push_log(f"  効果: 相手トラッシュ → デッキ下 (該当なし)")
                return False
            opp.trash[:] = new_trash
            opp.deck.extend(picked)
            state.push_log(f"  効果: 相手トラッシュ {len(picked)}枚 → 相手デッキ下")
        elif k == "draw_per_hand_to_deck_bottom":
            # 公式: 「自分の手札すべてを好きな順番でデッキの下に置いてもよい。
            # そうした場合、 置いた枚数分カードを引く」 (P-046 等)。
            n_returned = len(me.hand)
            if n_returned == 0:
                return False
            # AI 簡易: 全部戻す (= 手札リフレッシュ)
            me.deck.extend(me.hand)
            me.hand = []
            if getattr(me, "block_self_draw_until_turn_end", False):
                state.push_log(f"  効果: 手札 {n_returned} 枚 → デッキ下 (ドロー禁止のためドロー無し)")
                return True
            drawn = me.draw(n_returned)
            state.push_log(f"  効果: 手札 {n_returned} 枚 → デッキ下、 {len(drawn)} 枚ドロー")
        elif k == "return_self_to_deck_bottom_if_condition":
            # 「(条件) でない場合、 このキャラを持ち主のデッキの下に置く」 (P-098 等)。
            # spec: {"if_not": <condition>} (= 条件を満たさない場合に発動)
            spec_val = v if isinstance(v, dict) else {}
            cond = spec_val.get("if_not", {})
            if cond and eval_condition(cond, state, me, self_inplay):
                # 条件を満たす → 発動しない
                state.push_log(f"  効果: 条件成立 → デッキ下戻し不発")
                return False
            # 条件不成立 → 自身をデッキ下へ
            if self_inplay is None or self_inplay not in me.characters:
                return False
            me.characters.remove(self_inplay)
            if self_inplay.attached_dons > 0:
                me.don_rested += self_inplay.attached_dons
            me.deck.append(self_inplay.card)
            state.push_log(f"  効果: {self_inplay.card.name} を自デッキ下へ (条件不成立)")
        elif k == "swap_opp_power":
            # 公式: 「相手の (filter) キャラ 2 枚を選ぶ。 選んだキャラそれぞれの元々のパワーを、
            # このターン中、 入れ替える」 (OP14-017 等)。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {"power_le": 9000})
            cands = [c for c in opp.characters if _matches_filter_ip(c, filt)]
            if len(cands) < 2:
                state.push_log(f"  効果: swap_opp_power 該当 2 枚未満 (不発)")
                return False
            # 2026-07-08 監査: 人間は「入れ替える相手キャラ2枚」を選べる(target_pick modal)。
            picks_iids = spec_val.get("_iid_picks")
            if picks_iids is None and _maybe_request_target_pick(
                    state, list(cands), 2, k, dict(spec_val), self_inplay,
                    description="元々のパワーを入れ替える相手キャラ2枚を選択"):
                return True
            chosen = [c for c in cands if c.instance_id in picks_iids] if picks_iids else []
            if len(chosen) >= 2:
                weakest, strongest = chosen[0], chosen[1]
            else:
                # AI / 選択不足: 最強 + 最弱 を選んでスワップ (= 弱体化最大化)
                cands.sort(key=lambda c: c.card.power)
                weakest = cands[0]
                strongest = cands[-1]
            w_power = weakest.card.power
            s_power = strongest.card.power
            weakest.turn_base_power_override = s_power
            strongest.turn_base_power_override = w_power
            state.push_log(
                f"  効果: 元々のパワー入れ替え {weakest.card.name}↔{strongest.card.name} ({w_power}↔{s_power})"
            )
        elif k == "swap_self_power":
            # 公式: 「自分の (filter) キャラ 2 枚を選ぶ。 選んだキャラそれぞれの元々のパワーを、
            # このターン中、 入れ替える」 (OP14-001 ロー、 超新星/ハートの海賊団)。 swap_opp_power の自版。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            cands = [c for c in me.characters if _matches_filter_ip(c, filt)]
            if len(cands) < 2:
                state.push_log("  効果: swap_self_power 該当 2 枚未満 (不発)")
                return False
            picks_iids = spec_val.get("_iid_picks")
            if picks_iids is None and _maybe_request_target_pick(
                    state, list(cands), 2, k, dict(spec_val), self_inplay,
                    description="元々のパワーを入れ替える自分のキャラ2枚を選択"):
                return True
            chosen = [c for c in cands if c.instance_id in picks_iids] if picks_iids else []
            if len(chosen) < 2:
                # AI / 選択不足: 元々パワーの差が最大のペア (= 盤面への影響を最大化)
                cands.sort(key=lambda c: c.card.power)
                chosen = [cands[0], cands[-1]]
            a, b = chosen[0], chosen[1]
            pa, pb = a.card.power, b.card.power
            a.turn_base_power_override = pb
            b.turn_base_power_override = pa
            state.push_log(
                f"  効果: 自分 元々パワー入れ替え {a.card.name}↔{b.card.name} ({pa}↔{pb})")
        elif k == "move_attached_don":
            # OP07-001: 「自分の付与されているドン!! 合計 N 枚までを、 自分のキャラ1枚に付与する」
            # = 自分の場の付与済ドンを 1 枚のキャラへ再配分。 target (付与先) は human modal / AI 選択
            # (= 戦略的中心)。 source は target 以外の付与済カードから (rested 優先 → leader → active)。
            spec_val = v if isinstance(v, dict) else {}
            max_n = int(spec_val.get("count", spec_val.get("amount", 2)))
            target_spec = spec_val.get("target", "one_self_character_any")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay,
                                      outer_kind="move_attached_don", outer_value=v)
            if state.pending_choice is not None:
                return True   # 人間の付与先 選択待ち
            if not targets:
                continue
            tgt = targets[0]
            # source (付与元) 優先度: レスト中キャラ (このターン攻撃しない) → 他 active キャラ →
            # leader (leader の付与ドンは leader アタックに使うので最後)。 全て target 以外・付与済のみ。
            srcs = ([c for c in me.characters if c is not tgt and c.rested and c.attached_dons > 0]
                    + [c for c in me.characters if c is not tgt and not c.rested and c.attached_dons > 0]
                    + ([me.leader] if (me.leader is not None and me.leader is not tgt
                                       and me.leader.attached_dons > 0) else []))
            moved = 0
            for s in srcs:
                if moved >= max_n:
                    break
                take = min(s.attached_dons, max_n - moved)
                s.attached_dons -= take
                moved += take
            tgt.attached_dons += moved
            state.push_log(f"  効果: 付与済ドン {moved} 枚を {tgt.card.name} に移動")
        elif k == "attach_active_don":
            # アクティブドンを N 枚付与 (= attach_rested_don の active 版)。
            # spec: {"target": "self_leader", "count": 2}
            spec = v if isinstance(v, dict) else {}
            target_spec = spec.get("target", "self_leader")
            count = int(spec.get("count", 1))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="attach_active_don", outer_value=target_spec)
            if not targets:
                return False
            n = min(count, me.don_active)
            if n <= 0:
                return False
            target = targets[0]
            me.don_active -= n
            target.attached_dons += n
            state.push_log(f"  効果: アクティブドン {n} 枚付与 → {target.card.name}")
        elif k == "prevent_opp_blocker_for_cost_le":
            # 「相手は、 このバトル中、 コスト N 以下のキャラの【ブロッカー】を発動できない」
            # OP02-061 / OP02-101 等。 cost N 以下のキャラに「ブロック不可」 flag を立てる。
            spec = v if isinstance(v, dict) else {}
            cost_le = int(spec.get("cost_le", 5))
            duration = spec.get("duration", "battle")
            for c in opp.characters:
                if c.card.cost <= cost_le:
                    if duration == "turn":
                        c.granted_keywords.add("ブロック不可")
                    else:
                        c.granted_keywords.add("ブロック不可")
            state.push_log(
                f"  効果: 相手コスト{cost_le}以下キャラのブロック不可 ({duration})"
            )
        elif k == "reveal_opp_hand":
            # 「相手の手札 N 枚を公開する」 OP01-105 等。 公開のみ (= 情報公開)、 効果なし。
            # ⚠ v が bool True の場合は 「手札を(全部)公開する」 (OP07-090 モルガンズ)。
            #   int(True) == 1 になるため 以前は **1 枚しか公開していなかった** (2026-08-03 発覚)。
            if v is True:
                n = len(opp.hand)
            else:
                n = int(v) if not isinstance(v, dict) else int(v.get("count", 2))
            revealed = opp.hand[:n]
            # 公開したカードは known_hand_card_ids に記録 (= 中身バレを確定情報化)。
            # play/discard で normalize_known_hand が退場分を削除。 重複は normalize が hand 数で cap。
            for c in revealed:
                if c.card_id not in opp.known_hand_card_ids:
                    opp.known_hand_card_ids.append(c.card_id)
            state.push_log(f"  効果: 相手手札 {n} 枚公開 → {[c.name for c in revealed]}")
        elif k == "discard_self_to_deck_top":
            # 自分の手札 N 枚をデッキの上に置く (ST17-001 等)。 2026-07-08 監査: 旧実装は「先頭 N 枚」
            # 自動で 人間が どの札を上に置くか選べなかった。 → 人間選択 modal を持つ
            # self_hand_to_deck_bottom(to="top")に委譲。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            if not me.hand:
                return False
            return execute_effect({"self_hand_to_deck_bottom": {"amount": n, "to": "top"}},
                                  state, me, opp, self_inplay)
        elif k == "return_attached_don_to_cost_rested":
            # 「自分の付与されているドン!! N 枚を、 コストエリアにレストで戻す」 (ST28-004 等)。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            removed = 0
            # AI 簡易: self_inplay の attached_dons から優先消費
            if self_inplay is not None and self_inplay.attached_dons > 0:
                take = min(self_inplay.attached_dons, n)
                self_inplay.attached_dons -= take
                removed += take
            if removed < n:
                # 他キャラ/リーダーから補充
                for ip in [me.leader, *me.characters]:
                    if ip is self_inplay:
                        continue
                    if ip.attached_dons > 0:
                        take = min(ip.attached_dons, n - removed)
                        ip.attached_dons -= take
                        removed += take
                        if removed >= n:
                            break
            me.don_rested += removed
            state.push_log(f"  効果: 付与ドン {removed} 枚 → コストエリアレスト")
        elif k == "draw_per_self_chara_then_discard":
            # 「自分の(filter)キャラ1枚につき1引く。 その後、 引いた枚数分自分の手札を捨てる」
            # (EB04-011 ウロコ等)。 filter 一致の自キャラ数だけ draw → 同数 discard。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            cnt = sum(1 for c in me.characters if _matches_filter_ip(c, filt))
            if cnt <= 0:
                state.push_log("  効果: 該当キャラ0 (ドローなし)")
                return False
            drawn = me.draw(cnt)
            nd = len(drawn)
            if nd > 0 and _request_self_hand_discard(state, me, self_inplay, nd):
                return True  # draw 済み、 discard 対象は人間が選択(discard_only)
            for _ in range(nd):
                if not me.hand:
                    break
                me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
            state.push_log(f"  効果: {cnt}キャラで{nd}ドロー→{nd}捨て")
        elif k == "reduce_play_cost_filtered_turn":
            # 「このターン中、 次に登場させる(filter)キャラの支払うコストは N 少なくなる」
            # (OP02-025 等)。 ターン限定 filter 付き軽減を追加 (近似: 当ターン中の該当全play)。
            spec_val = v if isinstance(v, dict) else {}
            me.play_cost_reductions_filtered_turn.append({
                "filter": spec_val.get("filter", {}),
                "amount": int(spec_val.get("amount", 1)),
            })
            state.push_log("  効果: このターン中 登場コスト軽減 (filter)")
        elif k == "block_self_attack_leader_turn":
            # 「自分は、 このターン中、 (相手の) リーダーにアタックできない」 (OP06-026)。
            me.cannot_attack_leader_until_turn_end = True
            state.push_log("  効果: このターン中 リーダーにアタック不可")
        elif k == "opp_hand_to_size":
            # 「相手は手札が N 枚になるように、 自身の手札を捨てる」 (OP05-058 等)。 = 相手が選ぶ。
            # 相手=AI は最悪札から手放す(良い札を残す)。 相手=人間は本来選ばせるべきだが 非 actor
            # (相手ターン中の被対象)の halt 機構が未整備 → 当面は同じ最悪札 default(random より妥当)。
            target_size = int(v) if not isinstance(v, dict) else int(v.get("size", 5))
            while len(opp.hand) > target_size:
                opp.trash.append(opp.hand.pop(_worst_hand_idx(opp.hand, opp.known_hand_card_ids)))
            state.push_log(f"  効果: 相手手札を{target_size}枚に")
        elif k == "return_self_don_to_match_opp":
            # 「相手の場のドンの枚数と同じになるように自分の場のドンをドンデッキに戻す」
            # (OP08-074 等)。 自分のドン総数 > 相手 なら 超過分を返す (active 優先で残す)。
            opp_total = opp.don_active + opp.don_rested
            my_total = me.don_active + me.don_rested
            excess = max(0, my_total - opp_total)
            ret_rested = min(excess, me.don_rested)
            me.don_rested -= ret_rested
            me.don_remaining_in_deck += ret_rested
            ret_active = excess - ret_rested
            if ret_active > 0:
                me.don_active -= ret_active
                me.don_remaining_in_deck += ret_active
            if excess > 0:
                state.push_log(f"  効果: 自ドン{excess}をドンデッキへ (相手{opp_total}枚に合わせる)")
        elif k == "swap_base_power_self_leader_chara":
            # 「自分のリーダーとキャラ1枚を選び、 元々のパワーをこのバトル中入れ替える」 (OP14-009)。
            # AI: 最高 power の自キャラと leader を入替。 turn_base_power_override 使用。
            # 2026-07-08 監査: 人間は「どのキャラと入替えるか」を選べる(target_pick modal)。
            if not me.characters:
                state.push_log("  効果: 入替対象キャラなし (不発)")
                return False
            picks_iids = v.get("_iid_picks") if isinstance(v, dict) else None
            if picks_iids is None and len(me.characters) > 1 and _maybe_request_target_pick(
                    state, list(me.characters), 1, k, (v if isinstance(v, dict) else {}), self_inplay,
                    description="元々のパワーをリーダーと入れ替えるキャラを選択"):
                return True
            if picks_iids:
                ch = next((c for c in me.characters if c.instance_id in picks_iids),
                          max(me.characters, key=lambda c: c.power))
            else:
                ch = max(me.characters, key=lambda c: c.power)
            ld_base = me.leader.turn_base_power_override if me.leader.turn_base_power_override is not None else me.leader.card.power
            ch_base = ch.turn_base_power_override if ch.turn_base_power_override is not None else ch.card.power
            me.leader.turn_base_power_override = ch_base
            ch.turn_base_power_override = ld_base
            state.push_log(f"  効果: 元々パワー入替 リーダー({ld_base}<->{ch_base}){ch.card.name}")
        elif k == "return_self_charas_then_pump_per":
            # 「自分の場のキャラを任意の枚数手札に戻してもよい。 (target)は戻したキャラ1枚につき+M」
            # (P-059)。 AI: pump target 以外の自キャラを全戻し -> target を戻し枚数xM で pump。
            spec_val = v if isinstance(v, dict) else {}
            amount = int(spec_val.get("amount", 2000))
            duration = spec_val.get("duration", "battle")
            pump_target_spec = spec_val.get("target", "self_inplay")
            pts = _resolve_target(pump_target_spec, state, me, opp, self_inplay,
                                  outer_kind="return_self_charas_then_pump_per", outer_value=pump_target_spec)
            pump_target = pts[0] if pts else None
            returned = 0
            for c in list(me.characters):
                if pump_target is not None and c.instance_id == pump_target.instance_id:
                    continue
                me.characters.remove(c)
                me.hand.append(c.card)
                if c.attached_dons > 0:
                    me.don_rested += c.attached_dons
                returned += 1
            if pump_target is not None and returned > 0:
                execute_effect({"power_pump": {"target": pump_target_spec,
                                               "amount": amount * returned, "duration": duration}},
                               state, me, opp, self_inplay)
            state.push_log(f"  効果: 自キャラ{returned}枚戻し -> +{amount*returned}")
        elif k == "give_attribute":
            # 「(target)は、 このターン中、 属性(X)を得る」 (OP15-093)。 granted_attributes に追加。
            spec_val = v if isinstance(v, dict) else {}
            attr = spec_val.get("attribute", "")
            target_spec = spec_val.get("target", "self")
            for t in _resolve_target(target_spec, state, me, opp, self_inplay,
                                     outer_kind="give_attribute", outer_value=target_spec):
                if attr:
                    t.granted_attributes.add(attr)
            state.push_log(f"  効果: 属性({attr}) 付与")
        elif k == "grant_turn_battle_ko_save_discard":
            # 「自分のキャラすべては、 このターン中、 バトルでKOされる場合、 代わりに手札1捨て」 (EB02-030)。
            # ⚠ 「自分のキャラすべて」 は **発動時点で場にいるキャラ** のスナップショット。
            #   公式 cardqa_eb_02: 発動後に登場したキャラは対象外なので、 player 単位 turn フラグ
            #   ではなく 現在の各キャラに per-InPlay フラグを付与する (後から登場する InPlay には
            #   付かない = 救済されない)。
            n = 0
            for ch in me.characters:
                ch.battle_ko_save_discard_until_turn_end = True
                n += 1
            state.push_log(f"  効果: このターン中 自キャラ{n}体 バトルKO 代替(手札1捨て)")
        elif k == "opp_may_return_active_don_else_debuff":
            # OP15-059: 「相手は自身のアクティブのドン1枚をドンデッキに戻してもよい。 そうしなかった
            # 場合、 (target) を このターン中 -N」。 opp の意思決定を モデル化: 攻撃資源(ドン)より
            # 攻撃力保持を優先し、 アクティブドンがあれば戻して -N を回避、 無ければ (=攻撃に全ドン
            # 投入で払えない) -N を受ける。 = opp の最適近似 (人間 opp も攻撃を守るため通常返す)。
            # どちらに転んでも opp は損 (ドン or パワー) = 二択ジレンマを忠実に表現。
            spec = v if isinstance(v, dict) else {}
            amount = int(spec.get("amount", -2000))
            target_spec = spec.get("target", "one_opponent_inplay_any")
            if opp.don_active >= 1:
                opp.don_active -= 1
                opp.don_remaining_in_deck = getattr(opp, "don_remaining_in_deck", 0) + 1
                state.push_log("  効果: 相手がアクティブドン1枚をドンデッキに戻した (-2000 回避)")
            else:
                execute_effect(
                    {"power_pump": {"target": target_spec, "amount": amount, "duration": "turn"}},
                    state, me, opp, self_inplay)
        elif k == "force_opp_draw":
            # 「相手はカード N 枚を引く」 (OP07-090 等)。 相手にドローを強制 (= デッキ切れは敗北要因)。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            drawn = opp.draw(n)
            state.push_log(f"  効果: 相手が{len(drawn)}枚ドロー")
        elif k == "set_all_life_face_down":
            # 「自分のライフすべてを裏向きにする」 (EB03-051/OP08-075 等)。 face-up 枚数 0 化。
            me.face_up_life_count = 0
            state.push_log("  効果: 自ライフすべてを裏向き")
        elif k == "flip_life_face_up_effect":
            # 「自分のライフの上から N 枚を表向きにする」 (= cost でなく効果としての表向き化)。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            me.face_up_life_count = min(me.face_up_life_count + n, len(me.life))
            state.push_log(f"  効果: 自ライフ上{n}枚を表向き")
        elif k == "trash_all_face_up_life":
            # 「自分のライフの表向きのカードすべてをトラッシュに置く」 (ST13-002)。 count-only モデル:
            # 表向き札は top に置かれる (search life_face_up / chara_to_self_life face_up) ので、
            # 上から face_up_life_count 枚をトラッシュへ。
            n = min(me.face_up_life_count, len(me.life))
            for _ in range(n):
                if me.life:
                    me.trash.append(me.life.pop(0))
            me.face_up_life_count = 0
            if n:
                state.push_log(f"  効果: 表向きライフ {n} 枚をトラッシュ")
        elif k == "schedule_self_return_to_deck_bottom_at_battle_end":
            # 「その後、 このバトル終了時、 このキャラを持ち主のデッキの下に置く」 (OP02-064)。
            # self_inplay に flag を立て、 バトル終了 flush で me.deck 下へ。
            if self_inplay is not None:
                self_inplay.return_to_deck_bottom_at_battle_end = True
                state.push_log(f"  効果: {self_inplay.card.name} を バトル終了時デッキ下に予約")
        elif k == "schedule_self_trash_at_turn_end":
            # 「その後、 このターン終了時、 このキャラをトラッシュに置く」 自己犠牲 (OP03-005 サッチ)。
            # self_inplay に flag を立て、 turn-end flush で me.trash へ (= 当ターンは場に残り
            # 強化を活かせる)。 即 trash_self (cost) で書くと登場/起動直後に消える bug だった。
            if self_inplay is not None:
                self_inplay.trash_at_self_turn_end = True
                state.push_log(f"  効果: {self_inplay.card.name} を ターン終了時トラッシュ予約")
        elif k == "schedule_at_self_turn_end":
            # 「このターン終了時に〜」 delayed effect (= 自ターン終了で発動)。
            # OP15-025 クロ等。 me.scheduled_at_self_turn_end に append → END phase で flush。
            spec_val = v if isinstance(v, dict) else {}
            if not hasattr(me, "scheduled_at_self_turn_end"):
                me.scheduled_at_self_turn_end = []
            me.scheduled_at_self_turn_end.append(spec_val)
            state.push_log(f"  効果: 自ターン終了時に発動を予約")
        elif k == "static_swords_attack_chara":
            # 公式 静的: 「自分の特徴《SWORD》を持つキャラは、 登場したターンにキャラへアタックできる」
            # OP11-001 コビー リーダー等。 evaluate_static_effects で対応するため
            # ここでは on_attached_don n=0 経由で呼ばれた時に SWORD キャラに 速攻:キャラ flag を立てる。
            # 観戦コメント由来の修正: push_log は削除 (= evaluate_static_effects は
            # 毎 _recompute_static で再評価される。 都度 log するとスナップショット数 爆増 +
            # 観戦 log が冗長。 granted_keywords は カード hover で見えるので冗長表示不要)。
            for ip in me.characters:
                if "SWORD" in ip.card.features:
                    ip.granted_keywords.add("速攻：キャラ")
        elif k == "keep_opp_rested_chara_next_refresh":
            # 「相手の (filter) レストのキャラ N 枚は、 次の相手のリフレッシュフェイズで
            # アクティブにならない」 (OP15-038 等)。 該当キャラに stay_rested_next_refresh フラグ。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "one_opponent_character_any")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="keep_opp_rested_chara_next_refresh", outer_value=target_spec)
            for t in targets:
                if t.rested:
                    t.stay_rested_next_refresh = True
            state.push_log(
                f"  効果: 相手レストキャラ stay_rested → {[t.card.name for t in targets]}"
            )
        elif k == "keep_opp_rested_chara_with_don_ge_next_refresh":
            # 「相手のドン!! が N 枚以上付与されているレストのキャラ M 枚までは、
            # 次の相手のリフレッシュフェイズでアクティブにならない」 (OP15-025 等)。
            # spec: {"don_ge": 3, "limit": 1}
            spec_val = v if isinstance(v, dict) else {}
            don_ge = int(spec_val.get("don_ge", 1))
            limit = int(spec_val.get("limit", 1))
            iid_picks = spec_val.get("_iid_picks")
            # cost_le/cost_ge フィルタ (= OP14-035「相手のレストのコスト4以下」)。 未指定は無制限。
            _cle = spec_val.get("cost_le")
            _cge = spec_val.get("cost_ge")

            def _cost_ok(c):
                cc = int(getattr(c.card, "cost", 0) or 0)
                return (_cle is None or cc <= int(_cle)) and (_cge is None or cc >= int(_cge))
            cands = [c for c in opp.characters
                     if c.rested and c.attached_dons >= don_ge and _cost_ok(c)]
            if iid_picks is not None:
                chosen = [c for c in cands if c.instance_id in iid_picks][:limit]
            elif len(cands) > limit and _maybe_request_target_pick(
                state, cands, limit, "keep_opp_rested_chara_with_don_ge_next_refresh",
                v, self_inplay,
                description=f"相手 ドン≥{don_ge} 付与 レストキャラ {limit} 枚 まで 選択",
            ):
                return False
            else:
                cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
                chosen = cands[:limit]
            for t in chosen:
                t.stay_rested_next_refresh = True
            state.push_log(
                f"  効果: 相手 ドン{don_ge}+付与レストキャラ stay_rested → "
                f"{[t.card.name for t in chosen]}"
            )
        elif k == "transfer_attached_don_to_feature":
            # 「自分の付与されているドン!! N 枚までを、 自分の特徴 X を持つキャラ 1 枚に
            # 付与する」 (EB02-009 アンナ等)。
            # spec: {"feature": "麦わらの一味", "count": 1}
            # 人間 acting で 移動 元 / 移動 先 両方 複数 候補 なら modal で 選ばせる。
            spec_val = v if isinstance(v, dict) else {}
            feature = spec_val.get("feature", "")
            count = int(spec_val.get("count", 1))
            source_iid_picks = spec_val.get("_source_iid_picks")
            target_iid_picks = spec_val.get("_iid_picks")
            # 取り出し元: leader と キャラ から attached_dons > 0
            sources = [
                ip for ip in [me.leader, *me.characters]
                if ip.attached_dons > 0
            ]
            if not sources:
                return False
            # 移動先: feature 一致 self chara
            targets = [
                c for c in me.characters if feature in c.card.features
            ]
            if not targets:
                return False
            # source modal (= 人間 + 候補 > 1)。 source_iid_picks は 再実行 path。
            if source_iid_picks is not None:
                source = next(
                    (s for s in sources if s.instance_id in source_iid_picks), None,
                )
                if source is None:
                    return False
            elif len(sources) > 1 and _maybe_request_target_pick(
                state, sources, 1, "transfer_attached_don_to_feature_source",
                v, self_inplay,
                description=f"付与ドン 移動 元 (ドン 付与済) を 選択",
            ):
                return False
            else:
                sources.sort(key=lambda ip: ip.power)
                source = sources[0]
            # 移動先 modal (= 人間 + 候補 > 1)
            if target_iid_picks is not None:
                target = next(
                    (c for c in targets if c.instance_id in target_iid_picks), None,
                )
                if target is None:
                    return False
            elif len(targets) > 1 and _maybe_request_target_pick(
                state, targets, 1, "transfer_attached_don_to_feature",
                v, self_inplay,
                description=f"付与ドン 移動先 (特徴《{feature}》) を 選択",
            ):
                return False
            else:
                targets.sort(key=lambda ip: -ip.power)
                target = targets[0]
            take = min(count, source.attached_dons)
            source.attached_dons -= take
            target.attached_dons += take
            state.push_log(
                f"  効果: 付与ドン移動 {source.card.name}-{take} → {target.card.name}+{take}"
            )
        elif k == "reveal_opp_hand_and_if_event_mill_life":
            # 「相手の手札 1 枚を選び、 公開する。 公開したカードがイベントの場合、
            # 相手のライフ N 枚までを、 持ち主のデッキの下に置く」 (OP01-063 等)。
            # spec: {"mill_life": 1}
            spec_val = v if isinstance(v, dict) else {}
            mill_n = int(spec_val.get("mill_life", 1))
            if not opp.hand:
                state.push_log("  効果: 相手手札なし (不発)")
                return False
            # AI 簡易: ランダム 1 枚 公開 (= 公式は「自分が選ぶ」 だが対戦時は隠匿)
            idx = state.rng.randrange(len(opp.hand))
            revealed = opp.hand[idx]
            state.push_log(f"  効果: 相手手札公開 → {revealed.name} ({revealed.category.value})")
            from .core import Category as _Cat
            if revealed.category == _Cat.EVENT:
                # ライフ N 枚を デッキ下 に
                actually_milled = 0
                for _ in range(mill_n):
                    if not opp.life:
                        break
                    opp.deck.append(opp.life.pop(0))
                    actually_milled += 1
                state.push_log(
                    f"  効果: 公開カード EVENT → 相手ライフ {actually_milled} 枚 デッキ下へ"
                )
            else:
                state.push_log("  効果: 公開カード非EVENT (ライフ操作不発)")
        elif k == "keep_opp_rested_inplay_next_refresh":
            # 「相手のレストのリーダーとキャラ N 枚は、 次の相手のリフレッシュフェイズで
            # アクティブにならない」 OP07-059 フォクシー等。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target_rest", "one_opp_chara_or_leader")
            limit = int(spec_val.get("limit", 1))
            iid_picks = spec_val.get("_iid_picks")
            # target_rest は「one_opp_chara_or_leader」 想定。 シンプル: opp.leader + chara から rested 1 枚
            cands = []
            if opp.leader.rested:
                cands.append(opp.leader)
            for c in opp.characters:
                if c.rested:
                    cands.append(c)
            if not cands:
                return False
            if iid_picks is not None:
                chosen = [c for c in cands if c.instance_id in iid_picks][:limit]
            elif len(cands) > limit and _maybe_request_target_pick(
                state, cands, limit, "keep_opp_rested_inplay_next_refresh",
                v, self_inplay,
                description=f"相手 レスト リーダー or キャラ {limit} 枚 まで 選択",
            ):
                return False
            else:
                cands.sort(key=_threat_key)  # 脅威度優先 + power tie-break
                chosen = cands[:limit]
            for c in chosen:
                c.stay_rested_next_refresh = True
            state.push_log(f"  効果: stay_rested → {[c.card.name for c in chosen]}")
        elif k == "to_hand_self_trigger":
            # 公式: 「このカードを手札に加える」 (ST09-002 雨月天ぷら等の trigger 内)。
            # state にフラグを立て、 game.py の AttackLeader/Character 処理が trash の代わりに hand に置く。
            state.last_trigger_kept_in_hand = True
            state.push_log(f"  効果: このカードを手札に加える (trigger keep)")
        elif k == "set_ko_immune_timed":
            # 公式: 「(target) は、 次の相手のターン終了時まで、 (バトル/効果) で KO されない」
            # spec: {"target": ..., "duration": "next_opp_turn_end", "scope": "battle"|"effect"|"any"}
            # 既存の prevent_ko (turn) と give_ko_immune_through_opp_turn の汎用版。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "self")
            duration = spec_val.get("duration", "next_opp_turn_end")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_ko_immune_timed", outer_value=target_spec)
            for t in targets:
                if duration == "next_opp_turn_end":
                    t.ko_immune_through_opp_turn = True
                else:
                    t.ko_immune_until_turn_end = True
            state.push_log(
                f"  効果: KO耐性 ({duration}) → {[t.card.name for t in targets]}"
            )
        elif k == "disable_blocker":
            # OP12-051 ヴェルゴ等。 「相手の(filter)キャラ X 枚 まで は、 このターン中、
            # 【ブロッカー】 を 発動 できない」。 spec: {"target": ..., "duration": "turn"}
            spec_val = v if isinstance(v, dict) else {"target": v}
            target_spec = spec_val.get("target", "one_opponent_character_any")
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="disable_blocker", outer_value=v,
            )
            for t in targets:
                t.blocker_disabled_until_turn_end = True
            state.push_log(f"  効果: ブロッカー無効 → {[t.card.name for t in targets]}")
        elif k == "hand_or_trash_to_self_life":
            # ST13-003 ペル等。 「自分の手札か トラッシュ の (filter) chara N 枚 まで を、
            # 自分のライフ の 上 に 表向き で 加える」。 spec: {"filter": ..., "count": N, "if": {...}}
            spec_val = v if isinstance(v, dict) else {}
            if_block = spec_val.get("if", {})
            if if_block and not eval_condition(if_block, state, me, self_inplay):
                continue
            filt = spec_val.get("filter", {})
            count = int(spec_val.get("count", 1))
            # from_zone: "both" (既定、 手札優先→trash) | "trash" (= トラッシュのみ、 OP16-108 シリュウ)。
            from_zone = spec_val.get("from_zone", "both")
            # face_up: True で 「表向きで加える」 (= face_up_life_count を加算)。 既定 False で
            # 従来挙動 (= 裏向き、 既存カードの behavior を変えない)。
            face_up = bool(spec_val.get("face_up", False))
            # 手札 + trash の マッチ する card を 集める
            hand_cands = ([] if from_zone == "trash"
                          else [(i, c) for i, c in enumerate(me.hand) if _matches_filter(c, filt)])
            trash_cands = [(i, c) for i, c in enumerate(me.trash) if _matches_filter(c, filt)]
            n_added = 0
            # 簡略: 手札 先 → trash 後 で count 分 ライフ 上 に 加える
            for idx, c in hand_cands[:count]:
                me.life.insert(0, c)
                n_added += 1
            if n_added < count:
                need = count - n_added
                for idx, c in trash_cands[:need]:
                    me.life.insert(0, c)
                    n_added += 1
            # 元 zone から 削除 (逆順 で pop)
            for idx, c in sorted(hand_cands[:count], key=lambda x: -x[0]):
                if idx < len(me.hand):
                    me.hand.pop(idx)
            for idx, c in sorted(trash_cands[:max(0, count - len(hand_cands[:count]))],
                                  key=lambda x: -x[0]):
                if idx < len(me.trash):
                    me.trash.pop(idx)
            if face_up and n_added:
                # 表向きで加えた分だけ face_up_life_count を加算 (= ライフ上に積んだ枚数)。
                me.face_up_life_count = min(me.face_up_life_count + n_added, len(me.life))
            state.push_log(f"  効果: 手札/trash から chara {n_added} 枚 をライフへ"
                           + (" (表向き)" if face_up else ""))
        elif k == "set_battle_ko_immune":
            # OP06-096 サンジ等。 「自分の (target) は、 このターン中、 バトル で KO されない」。
            # spec: {"target": ..., "duration": "turn"|"static"}
            spec_val = v if isinstance(v, dict) else {"target": v}
            target_spec = spec_val.get("target", "self")
            duration = spec_val.get("duration", "turn")
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="set_battle_ko_immune", outer_value=v,
            )
            for t in targets:
                if duration == "static":
                    t.battle_ko_immune_static = True
                elif duration in ("next_self_turn_start", "next_opp_turn_end"):
                    # 「次の自分のターン開始時まで」 = 相手ターンを跨ぐ battle 耐性 (OP06-030)。
                    t.battle_ko_immune_through_opp_turn = True
                else:
                    t.battle_ko_immune_until_turn_end = True
            state.push_log(
                f"  効果: バトル KO 耐性 ({duration}) → {[t.card.name for t in targets]}"
            )
        elif k == "search_from_trash":
            # OP06-071 等。 「自分の トラッシュ の (filter) カード N 枚 まで を、 手札 に 加える」。
            # spec: {"filter": ..., "count": N, "to": "hand"}
            # 2026-05-31 拡張: 人間 acting + 候補 > count なら 選択 modal halt
            #   (= 公式 「N 枚 まで」 = プレイヤー 任意 選択 規定)。
            spec_val = v if isinstance(v, dict) else {}
            filt = _resolve_dynamic_filter(spec_val.get("filter", {}), state, me, opp)
            count = int(spec_val.get("count", 1))
            cands = [(i, c) for i, c in enumerate(me.trash) if _matches_filter(c, filt)]
            picks_idx = spec_val.get("_picked_trash_idxs")
            if picks_idx is None and _should_human_pick(state) and len(cands) > count:
                state.pending_choice = {
                    "kind": "search_from_trash_pick",
                    "primitive_kind": "search_from_trash",
                    "primitive_value": v,
                    "candidates": [
                        {
                            "trash_idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "cost": int(c.cost) if c.cost is not None else 0,
                            "power": int(c.power) if c.power is not None else 0,
                        }
                        for i, c in cands
                    ],
                    "limit": count,
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: トラッシュ サーチ 候補 {len(cands)} 枚 "
                    f"→ 人間 選択 待ち (= {count} 枚 まで 手札 へ)"
                )
                return True
            if picks_idx is not None:
                picks_idx_list = sorted(set(int(i) for i in picks_idx if 0 <= int(i) < len(me.trash)), reverse=True)
                added_names = []
                for i in picks_idx_list[:count]:
                    c = me.trash.pop(i)
                    me.add_to_hand_publicly(c)
                    added_names.append(c.name)
                state.push_log(f"  効果: trash から {len(added_names)} 枚 手札へ (人間 選択)")
                continue
            picks = cands[:count]
            added_names = []
            for idx, c in sorted(picks, key=lambda x: -x[0]):
                if idx < len(me.trash):
                    me.trash.pop(idx)
                    me.add_to_hand_publicly(c)
                    added_names.append(c.name)
            state.push_log(f"  効果: trash から {len(added_names)} 枚 手札へ → {added_names}")
        elif k == "disable_opp_on_play_through_opp_turn":
            # OP09-081 ティーチ: 「次の相手のターン終了時 まで、 相手の【登場時】効果 は 無効になる」。
            # 自陣 me ターン 中 に opp の フラグ を 立てる → opp が キャラ play する on_play で 効果 skip。
            # me の 次 ターン 開始 時 (= 相手 ターン 終了 後 の REFRESH) で reset。
            opp.opp_on_play_disabled_through_opp_turn = True
            state.push_log(f"  効果: 次相手 end まで 相手 on_play 効果 無効")
        elif k == "set_ko_per_turn_immune":
            # 公式: 「このキャラは ターン に N 回、 相手の効果で KO されない」 (OP10-118 等)。
            # spec: int N | {"target": ..., "count": N}
            # 自ターン 開始 (REFRESH) で remaining が max に reset される。
            spec_val = v if isinstance(v, dict) else {"target": "self", "count": int(v)}
            target_spec = spec_val.get("target", "self")
            n = int(spec_val.get("count", 1))
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="set_ko_per_turn_immune", outer_value=v,
            )
            for t in targets:
                t.ko_per_turn_immune_max = max(t.ko_per_turn_immune_max, n)
                # 直ちに remaining を 補充 (= 登場 直後 から 有効)
                if t.ko_per_turn_immune_remaining < n:
                    t.ko_per_turn_immune_remaining = n
            state.push_log(
                f"  効果: ターン{n}回 KO 耐性 → {[t.card.name for t in targets]}"
            )
        elif k == "rest_self_cards_filtered":
            # 公式: 「自分の (filter) カード N 枚をレストにできる」 (cost 用簡略 primitive)。
            # spec: {"count": 2, "filter": {...}}
            # 人間 acting + 候補 > N なら modal で 選ばせる。
            spec_val = v if isinstance(v, dict) else {"count": int(v)}
            count = int(spec_val.get("count", 1))
            filt = spec_val.get("filter", {})
            iid_picks = spec_val.get("_iid_picks")
            cands = [
                ip for ip in [me.leader, *me.characters, *me.stages]
                if not ip.rested and _matches_filter_ip(ip, filt)
            ]
            if len(cands) < count:
                state.push_log(f"  効果: レスト不能 (active 不足)")
                return False
            if iid_picks is not None:
                chosen = [ip for ip in cands if ip.instance_id in iid_picks][:count]
            else:
                if len(cands) > count and _maybe_request_target_pick(
                    state, cands, count, "rest_self_cards_filtered", v, self_inplay,
                    description=f"自カード から {count} 枚 を レスト",
                ):
                    return False
                cands.sort(key=lambda ip: ip.power)
                chosen = cands[:count]
            for ip in chosen:
                ip.rested = True
            state.push_log(
                f"  効果: 自カード {count}枚レスト → {[ip.card.name for ip in chosen]}"
            )
        elif k == "chara_to_opp_life":
            # 公式: 「相手のキャラ1枚までを、 相手のライフの上か下に表向きで置く」 EB01-053 等。
            # 場のキャラを取り除き、 持ち主 (= opp) のライフへ。
            # 「置く：相手は手札1枚を捨てる」 の後段は **実際に置いた場合のみ** 実行する
            # (OP09-101 クザン、 cardqa: 「ライフに置かない事はできますか→はい。 その場合、
            #  相手は手札1枚を捨てることはありません。」)。 → "then" サブ効果は placed>0 で発火。
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "one_opponent_character_any")
            then_specs = (v or {}).get("then", []) if isinstance(v, dict) else []
            # resolve_pending_choice 再実行時 の _iid_picks を target_spec へ 伝播
            if isinstance(v, dict) and "_iid_picks" in v and not (
                isinstance(target_spec, dict) and "_iid_picks" in target_spec
            ):
                target_spec = {"_iid_picks": v["_iid_picks"]}
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="chara_to_opp_life", outer_value=v,
            )
            if not targets:
                return False
            placed = 0
            for t in targets:
                if t in opp.characters:
                    opp.characters.remove(t)
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                        t.attached_dons = 0
                    opp.life.insert(0, t.card)
                    state.push_log(f"  効果: 相手キャラ {t.card.name} → 相手ライフ上")
                    placed += 1
            if placed and then_specs:
                for es in then_specs:
                    execute_effect(es, state, me, opp, self_inplay)
        elif k == "return_opp_don":
            # 相手は自身の場のドン N 枚をドンデッキに戻す。 active 優先、 不足は rested から。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            removed = 0
            take_a = min(n, opp.don_active)
            opp.don_active -= take_a
            opp.don_remaining_in_deck += take_a
            removed += take_a
            if removed < n:
                take_r = min(n - removed, opp.don_rested)
                opp.don_rested -= take_r
                opp.don_remaining_in_deck += take_r
                removed += take_r
            state.push_log(f"  効果: 相手ドン {removed} 枚をドンデッキへ戻す")
        elif k == "opp_hand_to_deck_bottom":
            # 相手は自身の手札 N 枚を選び デッキの下に置く。 = 相手が選ぶ → 相手=AI は最悪札を手放す
            # (良い札を残す)。 相手=人間は本来選ばせるべきだが 非 actor halt 未整備 → 最悪札 default。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            moved = 0
            for _ in range(n):
                if not opp.hand:
                    break
                opp.deck.append(opp.hand.pop(_worst_hand_idx(opp.hand, opp.known_hand_card_ids)))
                moved += 1
            state.push_log(f"  効果: 相手手札 {moved} 枚をデッキ下へ")
        elif k == "self_hand_to_deck_bottom":
            # 公式: 「自分の手札 N 枚を 好きな順番で デッキの上か下 に置く」 = プレイヤー が 選ぶ。
            # 2026-06-12: 人間 acting + 候補 > N で modal halt → 人間 が pick。
            #   (旧バグ: コスト最高 を auto 選択 → finisher 等 を 誤って 埋める。 ナミュ OP08-050
            #    で 自分の cost9 ハンコック 2 枚 を デッキ底 へ 葬る ケース を 検出。)
            # AI / 候補 <= N / 残り補完 は ヒューリスティック (コスト最高 = 死にカード) を 維持。
            # spec: int | {"amount": N, "to": "bottom"|"top"} ("top" = デッキの上に置く)
            spec = v if isinstance(v, dict) else {"amount": int(v)}
            n = int(spec.get("amount", 1))
            to = spec.get("to", "bottom")
            picks_idx = None
            if isinstance(v, dict) and "_picked_hand_idxs" in v:
                picks_idx = list(v["_picked_hand_idxs"])
            if picks_idx is None and _should_human_pick(state) and len(me.hand) > n and n > 0:
                state.pending_choice = {
                    "kind": "self_hand_to_deck_pick",
                    "primitive_value": dict(spec),
                    "to": to,
                    "candidates": [
                        {
                            "hand_idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "cost": int(c.cost) if c.cost is not None else 0,
                            "power": int(c.power) if c.power is not None else 0,
                        }
                        for i, c in enumerate(me.hand)
                    ],
                    "limit": n,
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: 自手札 {n} 枚をデッキ{'上' if to=='top' else '下'}へ "
                    f"→ 人間 選択 待ち (候補 {len(me.hand)} 枚)"
                )
                return True
            moved = 0
            if picks_idx is not None:
                # 人間が選んだ hand index を 降順 で pop → 指定 zone へ。
                for hi in sorted({int(i) for i in picks_idx if 0 <= int(i) < len(me.hand)},
                                 reverse=True)[:n]:
                    card = me.hand.pop(hi)
                    if to == "top":
                        me.deck.insert(0, card)
                    else:
                        me.deck.append(card)
                    moved += 1
            while moved < n and me.hand:
                # AI / 人間が N 未満しか選ばなかった残り: コスト最高 (= 死にカード) を移動
                idx = max(range(len(me.hand)), key=lambda i: me.hand[i].cost)
                card = me.hand.pop(idx)
                if to == "top":
                    me.deck.insert(0, card)
                else:
                    me.deck.append(card)
                moved += 1
            state.push_log(f"  効果: 自手札 {moved} 枚をデッキ{'上' if to=='top' else '下'}へ")
        elif k == "give_attack_active_chara":
            # 「相手のアクティブのキャラにもアタックできる」 = "アクティブアタック可" キーワード付与。
            # spec: target ("self" / "self_leader" / "self_inplay" など)、 duration
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "self")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="give_attack_active_chara", outer_value=target_spec)
            for t in targets:
                t.granted_keywords.add("アクティブアタック可")
            state.push_log(
                f"  効果: アクティブアタック可付与 → {[t.card.name for t in targets]}"
            )
        elif k == "to_opp_life":
            # 「相手のキャラ 1 枚までを、 持ち主のライフの上か下に表向きで加える」 系。
            # 対象キャラを場から取り除き (KO ではない)、 持ち主 (= opp) のライフに加える。
            # spec: target_spec ("one_opponent_character_cost_le_N" など) 文字列
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "one_opponent_character_any")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="to_opp_life", outer_value=target_spec)
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect:
                        state.push_log(f"  保護効果: {t.card.name} は離れない")
                        continue
                    opp.characters.remove(t)
                    # 付与ドンはレストでコストエリアに戻る (6-5-5-4)
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    # ライフに加える (= KO ではないので【KO時】 不発動)
                    opp.life.append(t.card)
                    state.push_log(f"  効果: {t.card.name} を持ち主ライフへ")
        elif k == "ko_all_others":
            # 「このキャラ以外のキャラすべてを KO する」 (OP01-094 カイドウ 等)。
            # 自他両陣営のキャラから self_inplay を除いて、 通常 KO 経路 (protect / immune /
            # replace_ko / on_ko 系トリガー) を通して KO する。
            # spec: True または辞書 (今は引数なし)。
            ko_targets: list[tuple[Player, InPlay]] = []
            for ip in list(me.characters):
                if ip is self_inplay:
                    continue
                ko_targets.append((me, ip))
            for ip in list(opp.characters):
                ko_targets.append((opp, ip))
            _kao_any = False
            for owner, t in ko_targets:
                # 自分のキャラ KO 経路 (= 自陣)
                if owner is me:
                    if t.ko_per_turn_immune_remaining > 0:
                        t.ko_per_turn_immune_remaining -= 1
                        state.push_log(f"  KO 耐性 (per-turn 残{t.ko_per_turn_immune_remaining+1}→{t.ko_per_turn_immune_remaining}): {t.card.name}")
                        continue
                    if t.ko_immune_until_turn_end or t.static_ko_immune or t.ko_immune_through_opp_turn:
                        state.push_log(f"  KO 耐性: {t.card.name}")
                        continue
                    if state.effects_overlay and try_replace_ko(
                        state, me, opp, t, state.effects_overlay, by_opp_effect=False
                    ):
                        continue
                    if t in me.characters:
                        me.characters.remove(t)
                        me.trash.append(t.card)
                        if t.attached_dons > 0:
                            me.don_rested += t.attached_dons
                        state.push_log(f"  効果: KO {t.card.name} (自陣)")
                        _kao_any = True
                        if state.effects_overlay:
                            # me 側 victim、 me 側 effect → by_opp_effect=False (= 自爆)
                            trigger_on_ko(state, me, opp, t.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                            trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
                else:
                    # 相手キャラ KO 経路
                    if t.protect_from_opp_effect:
                        state.push_log(f"  保護効果: {t.card.name}")
                        continue
                    if t.ko_per_turn_immune_remaining > 0:
                        t.ko_per_turn_immune_remaining -= 1
                        state.push_log(f"  KO 耐性 (per-turn 残{t.ko_per_turn_immune_remaining+1}→{t.ko_per_turn_immune_remaining}): {t.card.name}")
                        continue
                    if t.ko_immune_until_turn_end or t.static_ko_immune or t.ko_immune_through_opp_turn:
                        state.push_log(f"  KO 耐性: {t.card.name}")
                        continue
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay, by_opp_effect=True
                    ):
                        continue
                    if t in opp.characters:
                        opp.characters.remove(t)
                        opp.trash.append(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: KO {t.card.name} (相手)")
                        _kao_any = True
                        if state.effects_overlay:
                            # opp 側 victim、 me 側 effect → victim から 見れば by_opp_effect=True
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                            trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                            trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            if _kao_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "ko_multi":
            # マルチターゲット KO。 v はターゲット仕様のリスト。
            # 例: [{"target": "one_opponent_character_cost_le_2"},
            #      {"target": "one_opponent_character_cost_le_1"}]
            # 各 spec を順に resolve → KO。 同じキャラを 2 度 KO しないよう dedup。
            if not isinstance(v, list):
                continue
            already_kod = set()
            _kom_any = False
            for spec in v:
                if isinstance(spec, str):
                    target_spec = spec
                elif isinstance(spec, dict) and ("type" in spec or "filter" in spec):
                    # dict 形式 {"type": "...filtered", "filter": {...}} を そのまま渡す
                    # (= OP03-025 クリーク「相手レストのコスト4以下」 等。 spec.get("target") しか
                    #  見ないと type/filter が無視され one_opponent_character_any に誤 fallback していた)。
                    target_spec = spec
                else:
                    target_spec = (spec or {}).get("target", "one_opponent_character_any")
                targets = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="ko", outer_value=target_spec,
                )
                if state.pending_choice is not None:
                    return True
                for t in targets:
                    if id(t) in already_kod:
                        continue
                    if t in opp.characters:
                        if t.protect_from_opp_effect:
                            state.push_log(f"  保護効果: {t.card.name}")
                            continue
                        if t.ko_per_turn_immune_remaining > 0:
                            t.ko_per_turn_immune_remaining -= 1
                            state.push_log(f"  KO 耐性 (per-turn 残→{t.ko_per_turn_immune_remaining}): {t.card.name}")
                            continue
                        if t.ko_immune_until_turn_end or t.static_ko_immune or t.ko_immune_through_opp_turn:
                            state.push_log(f"  KO 耐性: {t.card.name}")
                            continue
                        if state.effects_overlay and try_replace_ko(
                            state, opp, me, t, state.effects_overlay, by_opp_effect=True
                        ):
                            already_kod.add(id(t))
                            continue
                        opp.characters.remove(t)
                        opp.trash.append(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: KO {t.card.name}")
                        already_kod.add(id(t))
                        _kom_any = True
                        if state.effects_overlay:
                            # opp 側 victim、 me 側 effect → by_opp_effect=True
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                            trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                            trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            if _kom_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "ko_total_power_le":
            # 「相手のキャラ N 枚までを、 パワーの合計が X 以下になるようにKOする」
            # (OP05-007 サボ / OP09-018 失せろ 等 5枚)。 旧 ko_multi [any,any] は合計
            # 制約を落とす過剰近似だったため専用 primitive 化。
            # spec: {"max_count": 2, "total_power_le": 4000}
            # auto: KO 可能な相手キャラの中で、 現在 power 合計 <= cap の組合せのうち
            #   除去 power 最大 (tie: 枚数多) を選ぶ (= 相手の最も価値あるキャラを最大除去)。
            #   単独 power>cap のキャラは KO 不可 (= 合計制約が大型キャラを守る)。
            spec = v if isinstance(v, dict) else {}
            max_count = int(spec.get("max_count", 2))
            cap = int(spec.get("total_power_le", 4000))

            def _koable(c: InPlay) -> bool:
                return not (
                    c.protect_from_opp_effect
                    or c.static_ko_immune
                    or c.ko_immune_until_turn_end
                    or c.ko_immune_through_opp_turn
                    or c.ko_per_turn_immune_remaining > 0
                )

            pool = [c for c in opp.characters if _koable(c)]
            best: list = []
            best_key = (-1, -1)  # (除去 power 合計, 枚数)
            for r in range(1, max_count + 1):
                for combo in itertools.combinations(pool, r):
                    s = sum(c.power for c in combo)
                    if s <= cap:
                        key = (s, len(combo))
                        if key > best_key:
                            best_key = key
                            best = list(combo)
            _kom_any = False
            for t in best:
                if t not in opp.characters:
                    continue
                if state.effects_overlay and try_replace_ko(
                    state, opp, me, t, state.effects_overlay, by_opp_effect=True
                ):
                    continue
                opp.characters.remove(t)
                opp.trash.append(t.card)
                if t.attached_dons > 0:
                    opp.don_rested += t.attached_dons
                state.push_log(f"  効果: KO {t.card.name} (合計power<={cap})")
                _kom_any = True
                if state.effects_overlay:
                    trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True, victim_attached_don=t.attached_dons, victim_effect_negated=_ip_effect_negated(t))
                    trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                    trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            if _kom_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "return_to_hand_multi":
            # マルチターゲット bounce (手札戻し)。
            if not isinstance(v, list):
                continue
            already_returned = set()
            _rhm_any = False
            for spec in v:
                target_spec = spec if isinstance(spec, str) else (spec or {}).get("target", "one_opponent_character_any")
                targets = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="return_to_hand", outer_value=target_spec,
                )
                if state.pending_choice is not None:
                    return True
                for t in targets:
                    if id(t) in already_returned:
                        continue
                    if t in opp.characters:
                        if t.protect_from_opp_effect or t.static_ko_immune:
                            state.push_log(f"  保護: {t.card.name}")
                            continue
                        if state.effects_overlay and try_replace_ko(
                            state, opp, me, t, state.effects_overlay,
                            by_opp_effect=True, leave_kind="return_to_hand",
                        ):
                            already_returned.add(id(t))
                            continue
                        opp.characters.remove(t)
                        # Phase 7I: 場 → 手札 は公開経路
                        opp.add_to_hand_publicly(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: {t.card.name} を持ち主の手札へ")
                        already_returned.add(id(t))
                        _rhm_any = True
                    elif t in me.characters:
                        # 自陣キャラの bounce (= 「自分の〜すべてを、持ち主の手札に戻す」 ST26-001 等)。
                        # 単体 return_to_hand と同じく 持ち主 (= me) の手札へ (自手札は非公開経路)。
                        me.characters.remove(t)
                        me.hand.append(t.card)
                        if t.attached_dons > 0:
                            me.don_rested += t.attached_dons
                        state.push_log(f"  効果: 自キャラを手札に戻す {t.card.name}")
                        already_returned.add(id(t))
                        _rhm_any = True
            if _rhm_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
                trigger_on_opp_chara_returned_to_hand_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "return_to_deck_bottom_multi":
            # マルチターゲット 「持ち主のデッキの下に置く」。
            if not isinstance(v, list):
                continue
            already = set()
            _rdm_any = False
            for spec in v:
                target_spec = spec if isinstance(spec, str) else (spec or {}).get("target", "one_opponent_character_any")
                targets = _resolve_target(
                    target_spec, state, me, opp, self_inplay,
                    outer_kind="return_to_deck_bottom", outer_value=target_spec,
                )
                if state.pending_choice is not None:
                    return True
                for t in targets:
                    if id(t) in already:
                        continue
                    if t in opp.characters:
                        if t.protect_from_opp_effect or t.static_ko_immune:
                            continue
                        if state.effects_overlay and try_replace_ko(
                            state, opp, me, t, state.effects_overlay,
                            by_opp_effect=True, leave_kind="return_to_deck_bottom",
                        ):
                            already.add(id(t))
                            continue
                        opp.characters.remove(t)
                        opp.deck.append(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: {t.card.name} を持ち主のデッキ下へ")
                        already.add(id(t))
                        _rdm_any = True
            if _rdm_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "hand_to_self_life":
            # 「自分の手札から [filter] カード N 枚までを、 ライフの上に裏向きで加える」。
            # spec: {"filter": {feature/cost_le/...}, "count": 1}
            # 人間 acting + 候補 > count なら modal で 選ばせる (= 既存 play_from_hand_pick と
            # 同じ pattern、 destination="life" で UI 区別)。
            spec = v if isinstance(v, dict) else {"filter": {}, "count": int(v) if isinstance(v, int) else 1}
            filt = spec.get("filter", {})
            count = int(spec.get("count", 1))
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補抽出
            candidates: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.hand) if _matches_filter(c, filt)
            ]
            if picks_idx is None and _should_human_pick(state) and len(candidates) > count:
                cand_list = [
                    {
                        "hand_idx": i,
                        "card_id": c.card_id,
                        "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    }
                    for i, c in candidates
                ]
                state.pending_choice = {
                    "kind": "hand_to_life_pick",
                    "primitive_value": v,
                    "candidates": cand_list,
                    "limit": count,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: 手札 → 自ライフ 候補 {len(candidates)} 枚 → 人間 選択 待ち (= {count} 枚 まで)"
                )
                return True
            # picks 解決 path: 指定 idx を 先に 落とす
            if picks_idx is not None:
                chosen_indexes = sorted(
                    [i for i in picks_idx if 0 <= i < len(me.hand)],
                    reverse=True,
                )
                moved = 0
                for i in chosen_indexes:
                    if moved >= count:
                        break
                    card = me.hand.pop(i)
                    me.life.append(card)
                    moved += 1
                    state.push_log(f"  効果: {card.name} を自ライフへ")
            else:
                # AI / 候補 <= count: 既存 挙動 (= 先頭 から filter 一致 を 移動)
                moved = 0
                new_hand = []
                for card in me.hand:
                    if moved < count and _matches_filter(card, filt):
                        me.life.append(card)
                        moved += 1
                        state.push_log(f"  効果: {card.name} を自ライフへ")
                    else:
                        new_hand.append(card)
                me.hand[:] = new_hand
        elif k == "negate_effect":
            # 相手のキャラ / リーダー 1 枚 を このターン中、 効果無効化 (簡略実装)。
            # 「効果を発動しなくなる」 → granted_keywords に "効果無効" を追加。
            # 実際の効果発動を抑制するのは effects.py 全体の trigger_* 関数の追加判定が必要だが、
            # 簡略では 「fire 直前に negate キーワードを check」 する形にする。
            # 現状: 統計用ラベルとして付与のみ (= 機能制限あり、 将来拡張)。
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "one_opponent_inplay_any")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="negate_effect", outer_value=target_spec)
            for t in targets:
                t.granted_keywords.add("効果無効")
            # soshite (= 「その後、 そのキャラの〜」) 用に直近 negate 対象を記録。
            # 0 対象なら None で clear する (= 前回の対象が残ると opp_just_negated_* が
            # 別カードに当たる)。
            state.last_negated_iid = targets[0].instance_id if targets else None
            state.push_log(f"  効果: 効果無効付与 → {[t.card.name for t in targets]} (近似)")
        elif k == "other_self_charas_to_deck_bottom":
            # このキャラ以外の自分のキャラすべてをデッキ下へ。
            _osd_any = False
            for ip in list(me.characters):
                if ip is self_inplay:
                    continue
                me.characters.remove(ip)
                if ip.attached_dons > 0:
                    me.don_rested += ip.attached_dons
                me.deck.append(ip.card)
                state.push_log(f"  効果: {ip.card.name} を自デッキ下へ")
                _osd_any = True
            if _osd_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "other_self_charas_to_trash":
            _ost_any = False
            for ip in list(me.characters):
                if ip is self_inplay:
                    continue
                me.characters.remove(ip)
                if ip.attached_dons > 0:
                    me.don_rested += ip.attached_dons
                me.trash.append(ip.card)
                state.push_log(f"  効果: {ip.card.name} を trash へ")
                _ost_any = True
                if state.effects_overlay:
                    # me 側 victim、 me 側 effect → by_opp_effect=False (= 自分の効果による自陣KO)
                    trigger_on_ko(state, me, opp, ip.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=ip.attached_dons, victim_effect_negated=_ip_effect_negated(ip))
                    # 自KO なので on_self_chara_ko (= me 側) を発火
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
            if _ost_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "extra_turn":
            # 「このターンの後に自分のターンを追加で得る」。
            # 簡略実装: state.extra_turn_pending を True に。 advance_phase の END 時に
            # turn_player_idx を変えないことで実現。
            state.extra_turn_pending = True
            state.push_log(f"  効果: このターンの後 ターン追加 (extra_turn フラグ)")
        elif k == "return_self_to_hand":
            # このキャラを持ち主の手札に戻す。
            if self_inplay is not None and self_inplay in me.characters:
                me.characters.remove(self_inplay)
                if self_inplay.attached_dons > 0:
                    me.don_rested += self_inplay.attached_dons
                me.hand.append(self_inplay.card)
                state.push_log(f"  効果: {self_inplay.card.name} を自手札に戻す")
        elif k == "give_ko_immune_through_opp_turn":
            # 「自分の特徴X を持つキャラすべては、 次の相手ターン終了時まで、 効果で KO されない」(OP09-033)
            # spec: {"filter": {...}}
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {})
            for ip in me.characters:
                if _matches_filter_ip(ip, filt):
                    ip.ko_immune_through_opp_turn = True
            state.push_log(
                f"  効果: KO耐性 (next_opp_turn_end) → filter={filt}"
            )
        elif k == "set_cannot_attack_target_cost_le":
            # 「相手の元々のコスト N 以下のキャラへアタックできない」 (OP12-020 リーダー等)
            # spec: {"target": "self_leader", "truly_original_cost_le": 7}
            # ⚠ 公式は 「元々のコスト」 = 印刷コスト。 消費側 (game.py の _can_attack_target) は
            #   `tgt.card.cost` (= 印刷値) と比べるので、 このキーは印刷値専用。
            #   素の 「コスト N 以下」 版のカードが出たら **消費側を base_cost に切り替える**
            #   分岐が要る (現状そのカードは存在しない = tests/test_effect_interactions.py で固定)。
            spec_val = v if isinstance(v, dict) else {"truly_original_cost_le": int(v)}
            target_spec = spec_val.get("target", "self_leader")
            cost_le = int(spec_val.get("truly_original_cost_le", 0))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_cannot_attack_target_cost_le", outer_value=target_spec)
            for t in targets:
                t.cannot_attack_target_cost_le_until_turn_end = cost_le
            state.push_log(
                f"  効果: コスト{cost_le}以下のキャラへアタック禁止 → {[t.card.name for t in targets]}"
            )
        elif k == "win_game":
            # 効果による勝利 (OP09-118 速攻ルフィ等)。 即座に declare_winner。
            me_idx = state.players.index(me)
            state.declare_winner(me_idx, "効果による勝利")
            state.push_log(f"  効果: {me.name} がゲームに勝利")
        elif k == "return_self_to_trash":
            # このキャラをトラッシュに置く (ジェルマ66コスト等)。
            if self_inplay is not None and self_inplay in me.characters:
                me.characters.remove(self_inplay)
                if self_inplay.attached_dons > 0:
                    me.don_rested += self_inplay.attached_dons
                me.trash.append(self_inplay.card)
                state.push_log(f"  効果: {self_inplay.card.name} をトラッシュへ")
        elif k == "play_from_hand_or_trash":
            # 手札 か トラッシュ から filter 一致のキャラ 1 枚 まで を 登場 (= ジェルマ66系)。
            # spec: {"filter": {...}, "limit": 1, "rested": false}
            # 公式: 「自分の手札 か トラッシュ から ~ 登場 させる」 = player が source + card を 選ぶ。
            # 2026-05-31 拡張: filter cost_le_dynamic 静的化 + 人間 acting で modal halt。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = _resolve_dynamic_filter(spec.get("filter", {}), state, me, opp)
            limit = int(spec.get("limit", 1))
            rested_flag = bool(spec.get("rested", False))
            # filter.category が STAGE なら ステージ として 登場 (= OP16-102 ハチノス)。
            # 既定 CHARACTER。 ステージ登場時は MAX 超過分を トラッシュへ (3-8-5-1)。
            _tcat_str = filt.get("category", "CHARACTER")
            try:
                target_cat = Category[_tcat_str] if isinstance(_tcat_str, str) else Category.CHARACTER
            except KeyError:
                target_cat = Category.CHARACTER

            def _place_pfhot(ip: InPlay) -> None:
                if target_cat == Category.STAGE:
                    while len(me.stages) >= Player.MAX_STAGES:
                        old = me.stages.pop()
                        me.trash.append(old.card)
                        if old.attached_dons > 0:
                            me.don_rested += old.attached_dons
                    me.stages.append(ip)
                else:
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
                    me.characters.append(ip)

            picks: Optional[list[dict]] = None
            if isinstance(v, dict) and "_picks" in v:
                picks = list(v["_picks"])
            # 全候補 抽出 (= 手札 + トラッシュ 横断)
            hand_cands: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.hand)
                if c.category == target_cat and _matches_filter(c, filt)
                and not _no_play_from_hand_via_effect(c, state.effects_overlay)
            ]
            trash_cands: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.trash)
                if c.category == target_cat and _matches_filter(c, filt)
            ]
            total_cands = len(hand_cands) + len(trash_cands)
            # 人間 acting + 候補 > limit + picks 未指定 → modal halt
            if picks is None and _should_human_pick(state) and total_cands > limit:
                cand_payload = []
                for i, c in hand_cands:
                    cand_payload.append({
                        "source": "hand", "idx": i,
                        "card_id": c.card_id, "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    })
                for i, c in trash_cands:
                    cand_payload.append({
                        "source": "trash", "idx": i,
                        "card_id": c.card_id, "name": c.name,
                        "cost": int(c.cost) if c.cost is not None else 0,
                        "power": int(c.power) if c.power is not None else 0,
                    })
                state.pending_choice = {
                    "kind": "play_from_hand_or_trash_pick",
                    "primitive_value": v,
                    "candidates": cand_payload,
                    "limit": limit,
                    "rested": rested_flag,
                    "filter_desc": _describe_filter_jp(filt),
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                    # actor 文脈を保存 (= 解決時に turn_player でなく この actor の hand/trash を使う。
                    # source_iid は on_ko 等で 場外/None になり 当てにならない、 2026-06-05)。
                    "_actor_idx": state.players.index(me),
                }
                state.push_log(
                    f"  効果: 手札 か トラッシュ から 登場 候補 {total_cands} 枚 "
                    f"→ 人間 選択 待ち (= {limit} 枚 まで)"
                )
                return True
            # picks 解決 path (= 人間 modal で 選 ば れ た)。
            # picks は [{"source": "hand"|"trash", "idx": N}, ...] 形式。
            if picks is not None:
                if not picks:
                    state.push_log("  効果: 手札 か トラッシュ から 登場 0 枚 選択 (= skip)")
                    return False
                # 後ろ から 取り出し で index ずれ 防止 (= hand と trash で 独立)
                hand_idxs = sorted(
                    [p["idx"] for p in picks if p.get("source") == "hand"],
                    reverse=True,
                )
                trash_idxs = sorted(
                    [p["idx"] for p in picks if p.get("source") == "trash"],
                    reverse=True,
                )
                played = 0
                for i in hand_idxs[:limit - played]:
                    if not (0 <= i < len(me.hand)):
                        continue
                    # 防御: 解決時に hand[i] が **キャラ かつ filter 一致** か再検証してから登場。
                    # idx/actor の desync で EVENT 等を掴むと「キャラエリアに非CHARACTER」 になる
                    # ため (= AI 経路 (下) は元々 category/filter を見ている。 これと整合)。
                    if not (me.hand[i].category == target_cat
                            and _matches_filter(me.hand[i], filt)):
                        continue
                    if _no_play_from_hand_via_effect(me.hand[i], state.effects_overlay):
                        continue   # OP12-036: 効果で登場できない
                    card = me.hand.pop(i)
                    ip = InPlay.of(card, rested=rested_flag, sickness=True)
                    _place_pfhot(ip)
                    played += 1
                    state.push_log(f"  効果: 手札から登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                for i in trash_idxs[:limit - played]:
                    if not (0 <= i < len(me.trash)):
                        continue
                    if not (me.trash[i].category == target_cat
                            and _matches_filter(me.trash[i], filt)):
                        continue
                    card = me.trash.pop(i)
                    ip = InPlay.of(card, rested=rested_flag, sickness=True)
                    _place_pfhot(ip)
                    played += 1
                    state.push_log(f"  効果: トラッシュから登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                continue
            # AI / 候補 <= limit: 旧 「手札 優先 → トラッシュ」 自動 pick
            found = 0
            new_hand = []
            for card in me.hand:
                if (
                    found < limit
                    and card.category == target_cat
                    and _matches_filter(card, filt)
                    and not _no_play_from_hand_via_effect(card, state.effects_overlay)
                ):
                    ip = InPlay.of(card, rested=rested_flag, sickness=True)
                    _place_pfhot(ip)
                    found += 1
                    state.push_log(f"  効果: 手札から登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_hand.append(card)
            me.hand[:] = new_hand
            if found < limit:
                # トラッシュから残り
                new_trash = []
                for card in me.trash:
                    if (
                        found < limit
                        and card.category == target_cat
                        and _matches_filter(card, filt)
                    ):
                        ip = InPlay.of(card, rested=rested_flag, sickness=True)
                        _place_pfhot(ip)
                        found += 1
                        state.push_log(f"  効果: トラッシュから登場 → {card.name}")
                        if state.effects_overlay:
                            trigger_on_play(state, me, opp, ip, state.effects_overlay)
                    else:
                        new_trash.append(card)
                me.trash[:] = new_trash
            if found == 0:
                state.push_log(f"  効果: play_from_hand_or_trash 該当なし")
        elif k == "life_top_or_bottom_to_hand":
            # 公式: 「ライフの上か下から N 枚を手札に加える」
            # spec: {"owner": "self"|"opp", "count": 1, "place": "top"|"bottom"|"choice"}
            spec_val = v if isinstance(v, dict) else {"count": int(v)}
            owner = spec_val.get("owner", "self")
            count = int(spec_val.get("count", 1))
            place = spec_val.get("place", "choice")
            target_pl = me if owner == "self" else opp
            if (
                owner == "self"
                and getattr(me, "prevent_self_life_to_hand_until_turn_end", False)
            ):
                state.push_log(f"  効果: 自ライフ上下→手札 禁止 (OP02-023 効果中)")
                return False
            if not target_pl.life:
                return False
            moved = 0
            for _ in range(count):
                if not target_pl.life:
                    break
                # AI 簡易: choice なら下 (= 表向きカードを手札に加える挙動を持つ
                # トリガー有りのライフを下に残すことを優先) 。
                # 実用上は上下どちらでも 1 枚減るので勝率影響小。
                if place == "bottom":
                    card = target_pl.life.pop(-1)
                else:
                    card = target_pl.life.pop(0)
                me.hand.append(card)
                moved += 1
            state.push_log(f"  効果: {owner}ライフ上/下{moved}枚を手札へ")
        elif k == "scry_life":
            # 公式: 「ライフの上から N 枚までを見て、 ライフの上か下に置く」
            # spec: {"owner": "self"|"opp"|"self_or_opp", "depth": 1}
            spec_val = v if isinstance(v, dict) else {"depth": int(v)}
            owner = spec_val.get("owner", "self")
            depth = int(spec_val.get("depth", 1))
            # owner が誰のライフを見るか。 self_or_opp (= カタクリ等) は「相手の上ライフがトリガー/
            # 高カウンターなら相手を見て下に埋める(妨害)、 さもなくば自ライフを最適化」= 見の見えざる領域。
            # ⚠ 相手ライフを見て埋める判断は AI のみ (人間 actor は自ライフ modal を優先し agency 保持)。
            def _life_help(card):  # そのカードを引いた側をどれだけ助けるか
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)

            def _is_good(card):  # 引いた側にとって有用 (= トリガー or 高カウンター)
                h = _life_help(card)
                return h[0] == 1 or h[1] >= 2000

            human = _should_human_pick(state)
            if owner == "opp":
                target_pl = opp
            elif owner == "self":
                target_pl = me
            else:  # self_or_opp
                if (not human) and opp.life and _is_good(opp.life[0]):
                    target_pl = opp   # AI: 相手の上ライフが強い → 妨害しに行く
                else:
                    target_pl = me
            if not target_pl.life:
                return False
            is_self = target_pl is me
            depth = min(depth, len(target_pl.life))
            seen = target_pl.life[:depth]
            # 人間 操作中 + 自ライフ + depth>=2 は user に並び替えを委ねる (相手ライフ scry は AI 演算)。
            if is_self and human and depth >= 2:
                state.pending_choice = {
                    "kind": "scry_life_reorder",
                    "owner": "self",
                    "depth": depth,
                    "cards": [
                        {
                            "card_id": c.card_id,
                            "name": c.name,
                            "trigger": bool(getattr(c, "trigger", None)),
                            "counter": int(getattr(c, "counter", 0) or 0),
                            "power": int(getattr(c, "power", 0) or 0),
                        }
                        for c in seen
                    ],
                    "description": f"自分のライフ上{depth}枚を 並び替え",
                }
                state.push_log(
                    f"  効果: scry_life {depth} 枚 並び替え 選択 待ち"
                )
                return True
            # 公式「上か下に置く」を top/bottom 二択で実行 (= depth1 の sort no-op バグ修正)。
            #   自ライフ: 有用札(トリガー/カウンター)は【上】に残し被弾時に活かす、 不要札は【下】へ。
            #   相手ライフ: 有用札は【下】に埋めダメージ時に引かせない(妨害)、 不要札は【上】(雑魚を引かせる)。
            rest = target_pl.life[depth:]
            top_grp, bot_grp = [], []
            for c in seen:
                keep_top = _is_good(c) if is_self else (not _is_good(c))
                (top_grp if keep_top else bot_grp).append(c)
            target_pl.life = top_grp + rest + bot_grp
            owner_label = "自" if is_self else "相手"
            state.push_log(
                f"  効果: {owner_label}ライフ上{depth}枚を確認 (上{len(top_grp)}/下{len(bot_grp)})"
            )
        elif k == "scry_deck_reorder":
            # 公式: 「自分のデッキの上から N 枚を見て、 好きな順番に並び替え、 デッキの上か下に置く」
            # spec: {"depth": N}
            # OP06-059 ホワイトスネーク等。 人間 actor なら 並び替え + 上下 を choice modal、
            # AI なら デフォルト 「価値順 (= 強カード を 上 に)」 で 上 に 置く。
            spec_val = v if isinstance(v, dict) else {"depth": int(v)}
            depth = int(spec_val.get("depth", 1))
            if not me.deck:
                return False
            depth = min(depth, len(me.deck))
            seen = me.deck[:depth]
            if _should_human_pick(state) and depth >= 1:
                state.pending_choice = {
                    "kind": "scry_deck_reorder",
                    "depth": depth,
                    "cards": [
                        {
                            "card_id": c.card_id,
                            "name": c.name,
                            "trigger": bool(getattr(c, "trigger", None)),
                            "counter": int(getattr(c, "counter", 0) or 0),
                            "power": int(getattr(c, "power", 0) or 0),
                        }
                        for c in seen
                    ],
                    "description": f"自デッキ上{depth}枚 並び替え + 上or下",
                }
                state.push_log(
                    f"  効果: scry_deck_reorder {depth} 枚 並び替え 選択 待ち"
                )
                return True
            # AI: 簡易ヒューリスティック (= トリガー有 / counter 大 を 上 に → 早く 引く)
            def _deck_value(card):
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)
            seen.sort(key=_deck_value, reverse=True)
            me.deck = seen + me.deck[depth:]
            state.push_log(f"  効果: 自デッキ上{depth}枚 並び替え (= 上配置)")
        elif k == "view_life_top_choose_position":
            # 公式: 「自分か相手のライフの上から N 枚までを見て、 ライフの上か下に置く」
            # spec: {"owner": "self"|"opp"|"either", "depth": N}
            # ST20-003 シャーロット・ブリュレ等。 owner=either なら 人間 が 選ぶ。
            spec_val = v if isinstance(v, dict) else {"depth": int(v)}
            owner = spec_val.get("owner", "self")
            depth = int(spec_val.get("depth", 1))
            if _should_human_pick(state):
                state.pending_choice = {
                    "kind": "view_life_top_choose_position",
                    "owner": owner,
                    "depth": depth,
                    "self_life_count": len(me.life),
                    "opp_life_count": len(opp.life),
                    "description": f"ライフ上{depth}を見て 上or下",
                }
                state.push_log(
                    f"  効果: view_life_top_choose_position owner={owner} depth={depth} 選択 待ち"
                )
                return True
            # AI: owner="self" 自ライフ 価値高い を 上、 owner="opp" 相手ライフ 価値低い を 上。
            # owner="either" は 自分 を 優先。
            target_pl = me if owner in ("self", "either") else opp
            if not target_pl.life:
                return False
            d = min(depth, len(target_pl.life))
            seen = target_pl.life[:d]
            rest = target_pl.life[d:]
            def _life_value(card):
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)
            # AI: 自ライフ で 価値高 を 上、 相手ライフ で 価値低 を 上
            if target_pl is me:
                seen.sort(key=_life_value, reverse=True)
            else:
                seen.sort(key=_life_value)
            target_pl.life = seen + rest
            state.push_log(
                f"  効果: ライフ上{d}枚 整列 ({'自' if target_pl is me else '相手'})"
            )
        elif k == "optional_discard_hand_for_battle_buff":
            # 公式: 「自分の手札から任意の枚数 (filter) を捨ててもよい。 捨てたカード1枚につき、
            # (target) はこのバトル中、 パワー+N」 OP15-002 ルーシー / OP03-001 エース等。
            # spec: {"filter": {"category_in": ["EVENT","STAGE"]}, "amount_per_discard": 1000,
            #        "target": "self_leader", "max": 3 (AI 上限、 省略時 3)}
            # ⚠ 「捨ててもよい」 = 任意 (0 枚 可)。 人間 acting なら どの/何枚 を 捨てるか modal で
            # 選ばせる (= 攻撃 pump / 防御 survival を 人間 が 制御。 攻撃時/相手アタック時 双方)。
            # AI は 従来通り 簡易 max まで 自動 (= matrix/test 不変)。 2026-06-09 human-gate 追加。
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {"category_in": ["EVENT", "STAGE"]})
            amount_per = int(spec_val.get("amount_per_discard", 1000))
            target_spec = spec_val.get("target", "self_leader")
            max_discard = int(spec_val.get("max", 3))
            discardable = [(i, c) for i, c in enumerate(me.hand) if _matches_filter(c, filt)]
            picks_idx = None
            if isinstance(spec_val, dict) and "_picked_hand_idxs" in spec_val:
                picks_idx = list(spec_val["_picked_hand_idxs"])
            # 人間 acting + 候補あり + 未解決 → どのイベント/ステージを捨てるか modal (0=見送り可)
            if picks_idx is None and _should_human_pick(state) and len(discardable) > 0:
                state.pending_choice = {
                    "kind": "optional_discard_buff_pick",
                    "primitive_value": dict(spec_val),
                    "candidates": [
                        {
                            "hand_idx": i,
                            "card_id": c.card_id,
                            "name": c.name,
                            "cost": int(c.cost) if c.cost is not None else 0,
                            "power": int(c.power) if c.power is not None else 0,
                            "counter": int(c.counter) if c.counter else 0,
                        }
                        for i, c in discardable
                    ],
                    "limit": len(discardable),
                    "amount_per_discard": amount_per,
                    "source_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(
                    f"  効果: イベント/ステージ を 捨てて +{amount_per}/枚 → 人間 選択 待ち "
                    f"(候補 {len(discardable)} 枚、 0 枚 = 見送り)"
                )
                return True
            discarded = []
            if picks_idx is not None:
                # 人間 modal の 選択 (= 0 枚 も 可)。 hand index 降順 で pop。
                idxs = sorted(
                    set(int(i) for i in picks_idx if 0 <= int(i) < len(me.hand)),
                    reverse=True,
                )
                for hi in idxs:
                    discarded.append(me.hand.pop(hi))
                    me.trash.append(discarded[-1])
            else:
                # AI 簡易: 最大 max_discard 枚 (= デフォルト 3 枚)。
                # battle 中の発動なので「+3000」 (= 3 枚捨て) で大半の攻防を凌げる想定。
                discard_count = min(len(discardable), max_discard)
                for _, c in discardable[:discard_count]:
                    me.hand.remove(c)
                    me.trash.append(c)
                    discarded.append(c)
            if not discarded:
                return False  # 0 枚 = 見送り (buff なし)
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="optional_discard_hand_for_battle_buff", outer_value=target_spec)
            buff = amount_per * len(discarded)
            for t in targets:
                t.battle_buff += buff
            state.push_log(
                f"  効果: {len(discarded)}枚捨て (filter={filt}) → battle_buff +{buff}"
            )
            if state.effects_overlay:
                trigger_on_self_hand_discarded(
                    state, me, opp, self_inplay, len(discarded), state.effects_overlay
                )
        elif k == "mill_self_life_until_n":
            # 公式: 「自分のライフが N 枚になるようにライフの上からトラッシュに置く」
            # EB01-060 我が神なり 「ライフを 1 枚になるようにトラッシュ」 等。
            # spec: int N | dict {"target_count": 1}
            spec_val = v if isinstance(v, dict) else {"target_count": int(v) if isinstance(v, int) else 1}
            target_count = int(spec_val.get("target_count", 1))
            milled = 0
            while len(me.life) > target_count:
                card = me.life.pop(0)
                me.trash.append(card)
                milled += 1
            state.push_log(f"  効果: ライフ→トラッシュ {milled}枚 (ライフ={target_count}枚まで削減)")
        elif k == "scry_all_life_one_to_deck":
            # 公式: 「自分のライフすべてを見て、 1枚を自分のデッキの上に置き、 ライフを好きな順番で置く」
            # ST13-016 ヤマト 等。 spec: True | {} (引数なし) or {"to": "top"|"bottom"} 既定 top。
            if not me.life:
                return False
            spec_val = v if isinstance(v, dict) else {}
            to_place = spec_val.get("to", "top")
            # 人間: 並べ替え modal(1枚目がデッキへ)を本人が選択。 AI は価値最大をデッキへ+残りソート。
            if _should_human_pick(state) and len(me.life) >= 2:
                state.pending_choice = {
                    "kind": "scry_life_reorder", "owner": "self", "depth": len(me.life),
                    "one_to_deck": to_place,
                    "cards": [{"card_id": c.card_id, "name": c.name,
                               "trigger": bool(getattr(c, "trigger", None)),
                               "counter": int(getattr(c, "counter", 0) or 0),
                               "power": int(getattr(c, "power", 0) or 0)} for c in me.life],
                    "description": f"ライフ全{len(me.life)}枚を並び替え(1枚目をデッキの{'下' if to_place=='bottom' else '上'}へ)",
                }
                state.push_log(f"  効果: ライフ→デッキ + 並び替え 選択 待ち")
                return True
            def _life_value(card):
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)
            sorted_life = sorted(me.life, key=_life_value, reverse=True)
            # 価値最大のカードをデッキトップへ (= 次ターンに引いて即活用)。
            # 残りライフはトリガー/カウンター大を上に積む (= ライフトリガー発動を早める)。
            to_deck = sorted_life[0]
            rest = sorted_life[1:]
            rest.sort(key=_life_value, reverse=True)
            me.life = rest
            if to_place == "bottom":
                me.deck.append(to_deck)
                state.push_log(f"  効果: ライフ→デッキ下: {to_deck.name} + ライフ {len(rest)} 枚並べ替え")
            else:
                me.deck.insert(0, to_deck)
                state.push_log(f"  効果: ライフ→デッキ上: {to_deck.name} + ライフ {len(rest)} 枚並べ替え")
        elif k == "scry_all_life_reorder":
            # 公式: 「自分のライフすべてを見て、 好きな順番で置く」
            # ST13-012 マキノ 後文 等。 spec: True | {} (引数なし)。 人間なら並べ替えを本人が選択。
            if not me.life:
                return False
            if _should_human_pick(state) and len(me.life) >= 2:
                state.pending_choice = {
                    "kind": "scry_life_reorder", "owner": "self", "depth": len(me.life),
                    "cards": [{"card_id": c.card_id, "name": c.name,
                               "trigger": bool(getattr(c, "trigger", None)),
                               "counter": int(getattr(c, "counter", 0) or 0),
                               "power": int(getattr(c, "power", 0) or 0)} for c in me.life],
                    "description": f"自分のライフ全{len(me.life)}枚を並び替え",
                }
                state.push_log(f"  効果: ライフ {len(me.life)} 枚 並び替え 選択 待ち")
                return True
            def _life_value(card):
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)
            me.life.sort(key=_life_value, reverse=True)
            state.push_log(f"  効果: ライフ {len(me.life)} 枚を並べ替え (トリガー/カウンター大優先)")
        elif k == "chara_to_self_life":
            # 公式: 「自分のキャラ1枚までを、 持ち主のライフの上か下に表向きで加える」
            # OP06-107 モモの助 等。 spec: {"target": <target_spec>, "place": "top"|"bottom"|"choice"}
            # 場のキャラを取り除いてライフへ移動 (KO ではないので KO 時トリガーは発火しない)。
            spec_val = v if isinstance(v, dict) else {"target": v}
            target_spec = spec_val.get("target", "one_self_character_any")
            place = spec_val.get("place", "choice")
            # resolve_pending_choice 再実行時 の _iid_picks を target_spec へ 伝播
            if "_iid_picks" in spec_val and not (
                isinstance(target_spec, dict) and "_iid_picks" in target_spec
            ):
                target_spec = {"_iid_picks": spec_val["_iid_picks"]}
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="chara_to_self_life", outer_value=v,
            )
            if not targets:
                return False
            _ctl_any = False
            for t in targets:
                if t in me.characters:
                    me.characters.remove(t)
                    # 付与されたドンはコストエリアへ戻す (= 場を離れる扱い)
                    if t.attached_dons > 0:
                        me.don_active += t.attached_dons
                        t.attached_dons = 0
                    _ctl_any = True
                # 持ち主 (= me) のライフへ。 AI 簡易: top に置く (= 早く回収 / 早くトリガー発動)。
                if place == "bottom":
                    me.life.append(t.card)
                else:
                    me.life.insert(0, t.card)
                # face_up: 表向きで加える (ST13-001 等)。 count-only モデルで表向き枚数 +1。
                if spec_val.get("face_up"):
                    me.face_up_life_count = min(me.face_up_life_count + 1, len(me.life))
            state.push_log(f"  効果: キャラ→自ライフ ({place}): {[t.card.name for t in targets]}")
            if _ctl_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "prevent_blocker_for_attacker":
            # 公式: 「指定キャラ/リーダーがアタックする場合、 相手は【ブロッカー】を発動できない」
            # spec: {"target": <target_spec>} | str (target_spec)
            # target_spec で辞書 {"type": "one_self_chara_or_leader_filtered",
            #                    "filter": {"power_ge": 6000, "feature": "..."}} もサポート。
            target_spec = v if not isinstance(v, dict) or "target" not in v else v.get("target")
            # 全 type を _resolve_target 経由で 統一処理。 旧 custom 分岐 (= one_self_chara_or_leader_filtered
            # 直接 sort + [:1]) は 人間 acting 時 modal バイパス bug の 原因 だった → 削除。
            # _resolve_target は outer_kind 指定 で 人間 acting + cand > 1 で modal 化 する。
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="prevent_blocker_for_attacker", outer_value=target_spec,
            )
            for t in targets:
                t.attacker_prevents_blocker_until_turn_end = True
            state.push_log(
                f"  効果: ブロッカー発動禁止 (attacker) → {[t.card.name for t in targets]}"
            )
        elif k == "prevent_blocker_for_attacker_power_le":
            # 「(アタッカー) のアタック中、 相手はパワーN以下のキャラの【ブロッカー】を発動できない」
            # (OP01-120/OP03-002 等)。 spec: {"amount": N, "target": <attacker、 既定 self>}。
            spec_val = v if isinstance(v, dict) else {"amount": int(v)}
            amount = int(spec_val.get("amount", 0))
            target_spec = spec_val.get("target", "self")
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="prevent_blocker_for_attacker_power_le", outer_value=target_spec,
            )
            for t in targets:
                t.attacker_prevents_blocker_power_le = amount
            state.push_log(
                f"  効果: パワー{amount}以下ブロッカー発動禁止 (attacker) → {[t.card.name for t in targets]}"
            )
        elif k == "disable_effect":
            # 公式: 「相手の X 1 枚を、 (このターン中 | 次の相手のターン終了時まで)、 効果を無効にする」
            # spec: {"target": <target_spec>, "duration": "turn"|"next_opp_turn_end",
            #        "also_cannot_attack": false}
            spec_val = v if isinstance(v, dict) else {"target": v}
            target_spec = spec_val.get("target", "one_opponent_inplay_any")
            duration = spec_val.get("duration", "turn")
            also_cannot_attack = bool(spec_val.get("also_cannot_attack", False))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="disable_effect", outer_value=target_spec)
            if not targets:
                return False
            for t in targets:
                if duration == "next_opp_turn_end":
                    t.effect_disabled_through_opp_turn = True
                    if also_cannot_attack:
                        t.cannot_attack_through_opp_turn = True
                else:
                    # duration="turn" → 既存 granted_keywords + cannot_attack_until_turn_end
                    t.granted_keywords.add("効果無効")
                    if also_cannot_attack:
                        t.cannot_attack_until_turn_end = True
            state.push_log(
                f"  効果: 効果無効 ({duration}) → {[t.card.name for t in targets]}"
                + (" + アタック不可" if also_cannot_attack else "")
            )
        elif k == "optional_cost_then":
            # 公式: 「X することができる：Y」 = optional cost を払って Y を発動。
            # spec: {"cost": [<primitive>...], "effect": [<primitive>...]}
            # AI 簡易: cost / effect 両方が払える状態なら発動する。
            spec_val = v if isinstance(v, dict) else {}
            cost_specs = spec_val.get("cost", [])
            effect_specs = spec_val.get("effect", [])
            # payability check (= cost が払える前提条件)
            can_pay = True
            for cs in cost_specs:
                if "life_top_or_bottom_to_hand" in cs or "life_to_hand" in cs:
                    if not me.life:
                        can_pay = False
                        break
                elif "mill_self_life_to_trash" in cs:
                    # R4: 「自分のライフの上か下から N 枚をトラッシュに置くことができる」 cost。
                    # 公式: ST13-005 / 等。 ライフが N 枚以上必要 (= 効果ライフ削りなのでトリガー判定なし)。
                    n_spec = cs["mill_self_life_to_trash"]
                    n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
                    if len(me.life) < n:
                        can_pay = False
                        break
                elif "trash_self_hand_random" in cs:
                    # 公式「手札N枚を捨てることができる」 → 手札が N 枚以上 必要 (= N=2 なら1枚では払えない)。
                    thr_spec = cs["trash_self_hand_random"]
                    thr_n = int(thr_spec) if not isinstance(thr_spec, dict) else int(thr_spec.get("count", thr_spec.get("amount", 1)))
                    if len(me.hand) < thr_n:
                        can_pay = False
                        break
                elif "pay_don" in cs:
                    n = int(cs.get("pay_don", 0))
                    if _pay_don_capacity(state, me) < n:   # 人間は付与ドンも返却可(2026-07-08)
                        can_pay = False
                        break
                elif "chara_to_self_life" in cs:
                    # ST13-001: 「自分の (filter) キャラ1枚をライフに表向きで加える」 cost。
                    _cl = cs["chara_to_self_life"]
                    _cl_tgt = _cl.get("target", {}) if isinstance(_cl, dict) else {}
                    _cl_filt = _cl_tgt.get("filter", {}) if isinstance(_cl_tgt, dict) else {}
                    if not any(_matches_filter_ip(c, _cl_filt) for c in me.characters):
                        can_pay = False
                        break
                elif "rest_self_don" in cs:
                    n = int(cs.get("rest_self_don", 0))
                    if me.don_active < n:
                        can_pay = False
                        break
                elif "return_self_to_hand" in cs:
                    if self_inplay is None or self_inplay not in me.characters:
                        can_pay = False
                        break
                elif "return_self_to_trash" in cs:
                    if self_inplay is None or self_inplay not in me.characters:
                        can_pay = False
                        break
                elif "return_to_hand" in cs and cs.get("return_to_hand") == "other_self_chara":
                    # 「このキャラ以外の自分のキャラ1枚を持ち主の手札に戻す」 cost
                    # (ジョズ OP08-047 等)。 self 以外の自キャラが居なければ払えない
                    # (= 払えないと : 以降の効果も不発、 2026-06-10)。
                    if not any(c is not self_inplay for c in me.characters):
                        can_pay = False
                        break
                elif "return_self_to_deck_bottom" in cs:
                    # 「このカードを持ち主のデッキの下に置く」 cost (OP10-026/027 キャラ /
                    # EB01-030 ステージ)。 self_inplay が場 (chara/stage) にいる必要。
                    if self_inplay is None or (
                        self_inplay not in me.characters and self_inplay not in me.stages):
                        can_pay = False
                        break
                elif "return_self_don_to_deck" in cs:
                    # 公式 「ドン!! -N (自分の場のドンを N 枚ドンデッキに戻すことができる)」
                    # optional cost として支払可。 場のドン (active+rested) が N 枚以上必要。
                    n_spec = cs["return_self_don_to_deck"]
                    n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
                    if (me.don_active + me.don_rested) < n:
                        can_pay = False
                        break
                elif "power_pump" in cs:
                    # 公式 「自分のアクティブのリーダーを、 このターン中、 パワー-N することができる：効果」
                    # 自リーダー弱体化を optional cost として扱う (EB03-006 ナミ系)。
                    # target がアクティブの場合 OK (rested 中は当然 OK だが効果意味は薄い)。
                    pp = cs["power_pump"]
                    tgt = pp.get("target", "self") if isinstance(pp, dict) else "self"
                    if tgt in ("self_leader", "self"):
                        # self はアタッカー (self_inplay)、 self_leader は me.leader。
                        # cost としてのアタックリーダー弱体は当然リーダー必要 → always present。
                        pass
                    # 弱体 (amount<0) の場合は実態あるか確認
                    amt = int(pp.get("amount", 0)) if isinstance(pp, dict) else 0
                    if amt < 0 and not me.characters and tgt == "self":
                        # self target で chara が無く self_inplay も無い場合 不可
                        if self_inplay is None:
                            can_pay = False
                            break
                elif "rest_self" in cs:
                    # 自身 (self_inplay) を rest する cost。 アクティブが必要。
                    if self_inplay is None or self_inplay.rested:
                        can_pay = False
                        break
                elif "rest_self_target_name" in cs or "rest_self_target" in cs:
                    # 自場の name 一致 アクティブが必要。
                    spec_n = cs.get("rest_self_target_name") or cs.get("rest_self_target")
                    target_name = (
                        spec_n.get("name", "") if isinstance(spec_n, dict)
                        else str(spec_n)
                    )
                    cands = [
                        ip for ip in (list(me.characters) + list(me.stages))
                        if (ip.card.name == target_name and not ip.rested)
                    ]
                    if not cands:
                        can_pay = False
                        break
                elif "trash_self_named_hand_or_field" in cs:
                    # 名前指定 trash cost (OP06-033 方舟ノア)。 手札か場に該当 name が無ければ払えない。
                    _nm = cs["trash_self_named_hand_or_field"]
                    _nm = _nm.get("name") if isinstance(_nm, dict) else str(_nm)
                    if not any(s.card.name == _nm for s in me.stages) and \
                            not any(c.name == _nm for c in me.hand):
                        can_pay = False
                        break
                elif "discard_hand" in cs:
                    # 任意 discard cost (= 「自分の手札 N 枚を捨てることができる：」、 例 P-151 スモーカー)。
                    # 手札が N 枚以上必要。 filter なしの単純枚数指定。
                    n = int(cs.get("discard_hand", 0))
                    if len(me.hand) < n:
                        can_pay = False
                        break
                elif "discard_hand_with_filter" in cs:
                    # filter 付き discard cost。 手札に filter 一致が count 以上必要。
                    df_spec = cs["discard_hand_with_filter"]
                    if "filter" in df_spec:
                        d_filt = df_spec.get("filter", {})
                    else:
                        d_filt = {k: v for k, v in df_spec.items() if k != "count"}
                    d_count = int(df_spec.get("count", 1))
                    matching = [c for c in me.hand if _matches_filter(c, d_filt)]
                    if len(matching) < d_count:
                        can_pay = False
                        break
                elif "reveal_hand_with_filter" in cs:
                    # R4: 「自分の手札から特徴X を持つカード N 枚を公開することができる」 cost。
                    # 手札に filter 一致が count 以上必要 (実消費なし)。
                    # 影響カード: OP12-003 / OP12-009 / OP12-015 / OP08-040 等 23+ 枚。
                    rf_spec = cs["reveal_hand_with_filter"]
                    if "filter" in rf_spec:
                        r_filt = rf_spec.get("filter", {})
                    else:
                        r_filt = {k: v for k, v in rf_spec.items() if k != "count"}
                    r_count = int(rf_spec.get("count", 1))
                    matching = [c for c in me.hand if _matches_filter(c, r_filt)]
                    if len(matching) < r_count:
                        can_pay = False
                        break
                elif "rest_self_cards" in cs or "rest_self_cards_filtered" in cs:
                    # 公式 「自分の(特徴X)カード N 枚をレストにできる：効果」。
                    # ⚠ 2026-08-05 まで payability handler が **無く**、 レストにできる自カードが
                    #   0 でも効果が発火していた (実測: OP14-036 トリガーが自カード0で相手をレスト)。
                    #   公式 (cardqa_st_06) は 「コストは一部だけ払うことができない」。
                    _rc = cs.get("rest_self_cards", cs.get("rest_self_cards_filtered"))
                    _rc_n = int(_rc.get("count", 1)) if isinstance(_rc, dict) else int(_rc)
                    _rc_filt = _rc.get("filter", {}) if isinstance(_rc, dict) else {}
                    _rc_pool = [
                        ip for ip in ([me.leader] + list(me.characters))
                        if ip is not None and not ip.rested
                        and not getattr(ip, "cannot_be_rested_buff", False)
                        and not getattr(ip, "static_cannot_be_rested", False)
                        and _matches_filter_ip(ip, _rc_filt)
                    ]
                    if len(_rc_pool) < _rc_n:
                        can_pay = False
                        break
                elif "mill_self_top" in cs:
                    # 「自分のデッキの上から N 枚をトラッシュに置くことができる：効果」。
                    _ms = cs["mill_self_top"]
                    _ms_n = int(_ms.get("amount", _ms.get("count", 1))) if isinstance(_ms, dict) else int(_ms)
                    if len(me.deck) < _ms_n:
                        can_pay = False
                        break
                elif "hand_to_deck_bottom" in cs:
                    # 「自分の手札 N 枚を好きな順番でデッキの下に置くことができる：効果」 (OP09-060)。
                    _hb = cs["hand_to_deck_bottom"]
                    _hb_n = int(_hb.get("count", _hb.get("amount", 1))) if isinstance(_hb, dict) else int(_hb)
                    if len(me.hand) < _hb_n:
                        can_pay = False
                        break
                elif "play_from_hand_named_set" in cs:
                    # 「自分の手札から『X』1枚を、登場できる：効果」 (OP05-111 ホトリ)。
                    # ⚠ 手札に該当カードが無ければ払えない (実測: 無くても効果が発火していた)。
                    _pn = cs["play_from_hand_named_set"]
                    _pn_names = _pn.get("names", []) if isinstance(_pn, dict) else [str(_pn)]
                    _pn_n = int(_pn.get("count", 1)) if isinstance(_pn, dict) else 1
                    _pn_hits = [c for c in me.hand if c.name in _pn_names]
                    if len(_pn_hits) < _pn_n:
                        can_pay = False
                        break
                elif "return_attached_don_to_cost_rested" in cs:
                    # 「このキャラの付与ドン‼を…コストエリアにレストで戻すことができる：効果」 (ST28-004)。
                    _ra = cs["return_attached_don_to_cost_rested"]
                    _ra_n = int(_ra.get("count", _ra.get("amount", 1))) if isinstance(_ra, dict) else int(_ra)
                    if self_inplay is None or self_inplay.attached_dons < _ra_n:
                        can_pay = False
                        break
                elif "rest_own_card" in cs:
                    # 公式 「自分のカード1枚をレストにできる：効果」 (OP14-036 等)。
                    # ⚠ 2026-08-05 まで optional_cost_then に この cost handler が **無く**、
                    #   payability も 支払いも 素通り = **コストがタダになっていた**
                    #   (Rust だけ払うので effect_smoke_parity が MISMATCH で検出した)。
                    # 対象は自分の場のカード (leader/character/stage) = アクティブが count 枚以上必要。
                    # ⚠ 「レストにできない」 は レストを要するコストも払えなくする (公式、 2026-08-04)。
                    _ro = cs["rest_own_card"]
                    _ro_n = int(_ro.get("count", 1)) if isinstance(_ro, dict) else int(_ro)
                    _ro_filt = _ro.get("filter", {}) if isinstance(_ro, dict) else {}
                    _ro_pool = [
                        ip for ip in ([me.leader] + list(me.characters) + list(me.stages))
                        if ip is not None and not ip.rested
                        and not getattr(ip, "cannot_be_rested_buff", False)
                        and not getattr(ip, "static_cannot_be_rested", False)
                        and _matches_filter_ip(ip, _ro_filt)
                    ]
                    if len(_ro_pool) < _ro_n:
                        can_pay = False
                        break
                elif "stage_to_deck_bottom" in cs:
                    # 公式 「(自分の)ステージ1枚を持ち主のデッキの下に置くことができる：効果」 用 cost。
                    # spec: {"stage_to_deck_bottom": {"cost_eq": N, "count": 1, "side": "either"}}
                    # もしくは {"stage_to_deck_bottom": 1} (= cost 制約なし、 count=1、 自分のみ)
                    #
                    # ⚠ **コスト節も 公式は 「自分の」/「相手の」/(修飾なし) を書き分ける** (2026-08-05):
                    #     自分のみ  OP05-104 コニス 「**自分の**ステージ1枚をデッキの下に置くことができる：」
                    #     相手のみ  OP15-003 アルビダ 「**相手の**キャラ1枚に相手のレストのドン‼1枚を付与できる：」
                    #     両陣営    OP06-102/111/114 「コスト1のステージ1枚を持ち主のデッキの下に置くことができる：」
                    #   「相手の」 を明示するコストが実在する (= 41 件) ので、 修飾なしを自陣限定に
                    #   すると **選択肢が丸ごと消える**。 side: "either" (既定 "self") で書き分ける。
                    #   ⚠ 「持ち主の」 は根拠にならない (OP12-080 バラティエは自分のステージにも使う)。
                    sb_spec = cs["stage_to_deck_bottom"]
                    if isinstance(sb_spec, dict):
                        sb_count = int(sb_spec.get("count", 1))
                        sb_side = str(sb_spec.get("side", "self"))
                        sb_filt = {k: v for k, v in sb_spec.items()
                                   if k not in ("count", "side")}
                    else:
                        sb_count = int(sb_spec)
                        sb_side = "self"
                        sb_filt = {}
                    sb_pool = list(me.stages) + (
                        list(opp.stages) if sb_side == "either" else []
                    )
                    matching = [s for s in sb_pool if _matches_filter_ip(s, sb_filt)]
                    if len(matching) < sb_count:
                        can_pay = False
                        break
                elif "return_self_chara_to_deck_bottom" in cs:
                    # 公式 「自分のキャラ1枚を持ち主のデッキの下に置くことができる：効果」 用 cost。
                    # spec: {"return_self_chara_to_deck_bottom": {"count": 1, "filter": {...}}} もしくは
                    # spec: {"return_self_chara_to_deck_bottom": 1}
                    rb_spec = cs["return_self_chara_to_deck_bottom"]
                    if isinstance(rb_spec, dict):
                        rb_count = int(rb_spec.get("count", 1))
                        rb_filt = rb_spec.get("filter", {})
                    else:
                        rb_count = int(rb_spec)
                        rb_filt = {}
                    matching = [c for c in me.characters if _matches_filter_ip(c, rb_filt)]
                    # 公式 「**このキャラ以外**の自分のキャラ1枚を…できる」 (OP05-056 等)。
                    # 発動元を除外しないと、 他に自キャラが居ない盤面でも払えてしまう。
                    if (isinstance(rb_spec, dict) and rb_spec.get("except_self")
                            and self_inplay is not None):
                        matching = [c for c in matching
                                    if c.instance_id != self_inplay.instance_id]
                    if len(matching) < rb_count:
                        can_pay = False
                        break
                elif "self_hand_to_deck_bottom" in cs:
                    # 公式 「自分の手札N枚をデッキの下に置くことができる：効果」 用 cost
                    # (OP01-011 ゴードン等)。 手札が N 枚未満なら払えない。
                    # ⚠ 発動元自身が手札から場に出た後の判定なので、 「このカードが最後の1枚」
                    #   だった場合 手札 0 = 払えない (cardqa_op_01「自分の手札が他にない場合、
                    #   このキャラを登場できますか？」→ 登場はできるが 効果は起きない)。
                    _hd = cs["self_hand_to_deck_bottom"]
                    _hn = int(_hd.get("amount", _hd.get("count", 1))) if isinstance(_hd, dict) else int(_hd)
                    if len(me.hand) < _hn:
                        can_pay = False
                elif "return_to_deck_bottom" in cs:
                    # 公式 「コスト4以下のキャラ1枚を、持ち主のデッキの下に置くことができる：効果」
                    # (OP04-055 疫災弾)。 **対象が 1 枚も居なければコストを払えない**。
                    # 一次情報 (cardqa_st_06): 「「：」以前に表記されている指示はすべて "発動コスト"
                    # であり、 "発動コスト" はその一部のみを支払うことはできません。 また "発動コスト"
                    # の一部あるいは全部が支払えない場合、 その効果を発動することができません。」
                    # 実測 (2026-08-05 是正前): コスト4以下キャラが不在でも 氷鬼 を捨てて
                    # トラッシュから登場できていた = 部分支払い = 公式違反。
                    # ⚠ outer_kind を渡さない (= 人間 modal を立てずに候補数だけ見る)。
                    if not _resolve_target(
                        cs["return_to_deck_bottom"], state, me, opp, self_inplay
                    ):
                        can_pay = False
                elif "return_self_chara_to_hand" in cs:
                    # 公式 「自分のキャラ1枚を持ち主の手札に戻すことができる：効果」 用 cost。
                    # OP01-047 トラファルガー・ロー 等。
                    # spec: {"return_self_chara_to_hand": {"count": 1, "filter": {...}}}
                    # or short form: {"return_self_chara_to_hand": 1}
                    rh_spec = cs["return_self_chara_to_hand"]
                    if isinstance(rh_spec, dict):
                        rh_count = int(rh_spec.get("count", 1))
                        rh_filt = rh_spec.get("filter", {})
                    else:
                        rh_count = int(rh_spec)
                        rh_filt = {}
                    matching = [c for c in me.characters if _matches_filter_ip(c, rh_filt)]
                    if len(matching) < rh_count:
                        can_pay = False
                        break
                elif "ko_self_chara" in cs:
                    # 公式 「自分のキャラ N 枚を (KO/トラッシュに置く) ことができる：効果」 用 cost。
                    # OP05-087 ハクバ (このキャラ以外) / EB04-048 ルッチ 等。
                    # spec: {"ko_self_chara": {"count": 1, "filter": {...}, "exclude_self": true}}
                    #   or short: {"ko_self_chara": 1}
                    kc_spec = cs["ko_self_chara"]
                    if isinstance(kc_spec, dict):
                        kc_count = int(kc_spec.get("count", 1))
                        kc_filt = kc_spec.get("filter", {})
                        kc_excl = bool(kc_spec.get("exclude_self", False))
                    else:
                        kc_count = int(kc_spec)
                        kc_filt = {}
                        kc_excl = False
                    matching = [
                        c for c in me.characters
                        if _matches_filter_ip(c, kc_filt)
                        and not (kc_excl and self_inplay is not None
                                 and c.instance_id == self_inplay.instance_id)
                    ]
                    if len(matching) < kc_count:
                        can_pay = False
                        break
                elif "trash_to_deck" in cs:
                    # 公式 「自分のトラッシュから filter 一致のカード N 枚を好きな順番でデッキの下/上に置く
                    # ことができる：効果」 用 cost。 OP11-119 コビー 等。
                    # spec: {"trash_to_deck": {"limit": 2, "filter": {...}, "to": "bottom"}}
                    t_spec = cs["trash_to_deck"]
                    if isinstance(t_spec, dict):
                        t_limit = int(t_spec.get("limit", 1))
                        t_filt = t_spec.get("filter", {})
                    else:
                        t_limit = int(t_spec)
                        t_filt = {}
                    matching = [c for c in me.trash if _matches_filter(c, t_filt)]
                    if len(matching) < t_limit:
                        can_pay = False
                        break
                elif "rest_self_leader_or_stage_filtered" in cs:
                    # 公式 「自分の特徴X を持つ、 リーダーかステージ N 枚を、 レストにできる：効果」
                    # (OP10-044/081/083/087/088/091/095 ドレスローザ 等)。 leader+stages から
                    # filter 一致の アクティブ を count 枚 rest 可能か。
                    rl_spec = cs["rest_self_leader_or_stage_filtered"]
                    rl_n = int(rl_spec.get("count", 1)) if isinstance(rl_spec, dict) else int(rl_spec)
                    rl_filt = rl_spec.get("filter", {}) if isinstance(rl_spec, dict) else {}
                    pool = ([me.leader] if me.leader is not None else []) + list(me.stages)
                    avail = [ip for ip in pool if not ip.rested and _matches_filter_ip(ip, rl_filt)]
                    if len(avail) < rl_n:
                        can_pay = False
                        break
                elif "rest_self_leader_filtered_or_don" in cs:
                    # 公式「自分の、属性X を持つリーダーかドン!!1枚を、レストにできる：効果」
                    # (ST32-001 錦えもん等)。 filter 一致のアクティブ leader OR アクティブ DON があれば払える (OR-cost)。
                    rd_spec = cs["rest_self_leader_filtered_or_don"]
                    rd_filt = rd_spec.get("filter", {}) if isinstance(rd_spec, dict) else {}
                    leader_ok = (me.leader is not None and not me.leader.rested
                                 and _matches_filter_ip(me.leader, rd_filt))
                    if not leader_ok and me.don_active < 1:
                        can_pay = False
                        break
                elif "rest_self_chara_filtered" in cs:
                    # 公式 「自分の特徴X / コストN以上 の キャラ M 枚を レストにできる：効果」
                    # (OP03-021/OP03-036/OP07-036 等)。 アクティブの自キャラから filter 一致 を count 枚。
                    rc_spec = cs["rest_self_chara_filtered"]
                    rc_n = int(rc_spec.get("count", 1)) if isinstance(rc_spec, dict) else int(rc_spec)
                    rc_filt = rc_spec.get("filter", {}) if isinstance(rc_spec, dict) else {}
                    avail = [c for c in me.characters if not c.rested and _matches_filter_ip(c, rc_filt)]
                    if len(avail) < rc_n:
                        can_pay = False
                        break
                elif "flip_life_face_up" in cs:
                    # 「自分のライフの上から1枚を表向きにできる：」 cost。 裏向き (= 通常) の
                    # ライフが 1 枚以上 必要 (= 表向き枚数 < ライフ総数)。 しらほし系。
                    fu = min(me.face_up_life_count, len(me.life))
                    if len(me.life) - fu < 1:
                        can_pay = False
                        break
                elif "flip_life_face_down" in cs:
                    # 「自分のライフの上から1枚を裏向きにできる：」 cost。 表向きの
                    # ライフが 1 枚以上 必要 (= leader 等で表向きにした分を消費)。
                    if min(me.face_up_life_count, len(me.life)) < 1:
                        can_pay = False
                        break
                elif "attach_opp_don_to_opp_chara" in cs:
                    # 「相手のキャラ1枚に相手の(レストの/コストエリアの)ドンN枚を付与できる：」 cost
                    # (OP15-003/017/023 等)。 相手にドンと付与先キャラが必要。
                    ad_spec = cs["attach_opp_don_to_opp_chara"]
                    ad_n = int(ad_spec.get("count", 1)) if isinstance(ad_spec, dict) else int(ad_spec)
                    ad_cost_area = isinstance(ad_spec, dict) and ad_spec.get("from_cost_area")
                    avail_don = opp.don_rested + (opp.don_active if ad_cost_area else 0)
                    if not opp.characters or avail_don < ad_n:
                        can_pay = False
                        break
                elif "attach_active_don_to_named_chara" in cs:
                    # 「自分の「<name>」1枚にアクティブのドンN枚を付与できる：」 cost
                    # (EB04-009/OP12-016/019 レイリー等)。 該当 name のキャラ + アクティブドン必要。
                    aa_spec = cs["attach_active_don_to_named_chara"]
                    aa_name = aa_spec.get("name", "") if isinstance(aa_spec, dict) else str(aa_spec)
                    aa_n = int(aa_spec.get("count", 1)) if isinstance(aa_spec, dict) else 1
                    if me.don_active < aa_n or not any(c.card.name == aa_name for c in me.characters):
                        can_pay = False
                        break
            # effect が空回りするケースも skip (= 価値なし)
            # ⚠ 判定は **コスト支払い前** の盤面で行うので、 コスト自身が手札を増やす型
            #   (= 「自分のライフの上から1枚を手札に加えることができる：自分の手札1枚までを、
            #     ライフの上に加える」 OP08-117 トリガー) では 「手札が空 = 空回り」 が成立しない。
            #   支払い後は手札が 1 枚あるので効果は実際に働く。 コスト種別を見て guard を外す。
            _cost_fills_hand = any(
                ("life_to_hand" in cs or "life_top_or_bottom_to_hand" in cs)
                for cs in cost_specs
            )
            should_fire = can_pay
            if should_fire and not _cost_fills_hand:
                for es in effect_specs:
                    if "hand_to_self_life" in es and not me.hand:
                        should_fire = False
                        break
            if not should_fire:
                state.push_log(f"  効果: optional_cost_then 不発 (cost不能 or 効果空)")
                return False
            # 人間 操作 中 は 任意コスト (= 公式「〜できる：」) の pay/skip を 本人 に 委ねる。
            # _cost_confirmed (= resolve_pending_choice 経由 の 再実行) は bypass。
            # AI 操作 (= _should_human_pick False) は 従来通り 自動 fire (= matrix/test 不変)。
            if not spec_val.get("_cost_confirmed") and _should_human_pick(state):
                src_name = self_inplay.card.name if self_inplay is not None else "効果"
                state.pending_choice = {
                    "kind": "optional_cost_confirm",
                    "spec": spec_val,
                    "self_inplay_iid": (
                        self_inplay.instance_id if self_inplay is not None else None
                    ),
                    "source_name": src_name,
                    "prompt": f"{src_name}: 任意コストを払って効果を発動しますか？",
                }
                return False
            for _ci, cs in enumerate(cost_specs):
                # 一部 cost は execute_effect の通常パスでは正しく動かない:
                #   - rest_self_target_name / rest_self_target はそのキャラを rest にする
                #     primitive が存在しないので、 ここで直接処理する。
                if "rest_self_target_name" in cs or "rest_self_target" in cs:
                    spec_n = cs.get("rest_self_target_name") or cs.get("rest_self_target")
                    target_name = (
                        spec_n.get("name", "") if isinstance(spec_n, dict)
                        else str(spec_n)
                    )
                    for ip in (list(me.characters) + list(me.stages)):
                        if ip.card.name == target_name and not ip.rested:
                            ip.rested = True
                            state.push_log(f"  効果コスト: 自レスト {ip.card.name}")
                            break
                    continue
                if "rest_self_leader_or_stage_filtered" in cs:
                    rl_spec = cs["rest_self_leader_or_stage_filtered"]
                    rl_n = int(rl_spec.get("count", 1)) if isinstance(rl_spec, dict) else int(rl_spec)
                    rl_filt = rl_spec.get("filter", {}) if isinstance(rl_spec, dict) else {}
                    pool = ([me.leader] if me.leader is not None else []) + list(me.stages)
                    avail = [ip for ip in pool if not ip.rested and _matches_filter_ip(ip, rl_filt)]
                    # AI 簡易: ステージ優先で rest (= リーダーは攻撃に使いたい)。
                    avail.sort(key=lambda ip: 0 if ip in me.stages else 1)
                    for ip in avail[:rl_n]:
                        ip.rested = True
                        state.push_log(f"  効果コスト: 自レスト {ip.card.name}")
                    continue
                if "rest_self_leader_filtered_or_don" in cs:
                    rd_spec = cs["rest_self_leader_filtered_or_don"]
                    rd_filt = rd_spec.get("filter", {}) if isinstance(rd_spec, dict) else {}
                    # AI 簡易: DON を優先 rest (= リーダーは攻撃に使いたい)。 DON 無ければ leader を rest。
                    if me.don_active >= 1:
                        me.don_active -= 1
                        me.don_rested += 1
                        state.push_log("  効果コスト: ドン!!1枚をレスト")
                    elif me.leader is not None and not me.leader.rested and _matches_filter_ip(me.leader, rd_filt):
                        me.leader.rested = True
                        state.push_log(f"  効果コスト: リーダー {me.leader.card.name} をレスト")
                    continue
                if "rest_self_chara_filtered" in cs:
                    rc_spec = cs["rest_self_chara_filtered"]
                    rc_n = int(rc_spec.get("count", 1)) if isinstance(rc_spec, dict) else int(rc_spec)
                    rc_filt = rc_spec.get("filter", {}) if isinstance(rc_spec, dict) else {}
                    avail = [c for c in me.characters if not c.rested and _matches_filter_ip(c, rc_filt)]
                    avail.sort(key=lambda c: c.power)  # AI 簡易: power 低い順
                    for ip in avail[:rc_n]:
                        ip.rested = True
                        state.push_log(f"  効果コスト: 自レスト {ip.card.name}")
                    continue
                if "chara_to_self_life" in cs:
                    # ST13-001: cost として自キャラをライフに表向きで加える (execute_effect 経由)。
                    execute_effect({"chara_to_self_life": cs["chara_to_self_life"]},
                                   state, me, opp, self_inplay)
                    continue
                if "flip_life_face_up" in cs:
                    me.face_up_life_count = min(me.face_up_life_count + 1, len(me.life))
                    state.push_log("  効果コスト: ライフ上1枚を表向き")
                    continue
                if "flip_life_face_down" in cs:
                    me.face_up_life_count = max(0, min(me.face_up_life_count, len(me.life)) - 1)
                    state.push_log("  効果コスト: ライフ上1枚を裏向き")
                    continue
                if "attach_opp_don_to_opp_chara" in cs:
                    ad_spec = cs["attach_opp_don_to_opp_chara"]
                    ad_n = int(ad_spec.get("count", 1)) if isinstance(ad_spec, dict) else int(ad_spec)
                    ad_cost_area = isinstance(ad_spec, dict) and ad_spec.get("from_cost_area")
                    # AI 簡易: 相手の最高 power キャラに付与 (= tempo 妨害だが downside)。
                    tgt = max(opp.characters, key=lambda c: c.power)
                    take = min(ad_n, opp.don_rested)
                    opp.don_rested -= take
                    if ad_cost_area and take < ad_n:
                        more = min(ad_n - take, opp.don_active)
                        opp.don_active -= more
                        take += more
                    tgt.attached_dons += take
                    state.push_log(f"  効果コスト: 相手ドン{take}を相手キャラ{tgt.card.name}に付与")
                    continue
                if "attach_active_don_to_named_chara" in cs:
                    aa_spec = cs["attach_active_don_to_named_chara"]
                    aa_name = aa_spec.get("name", "") if isinstance(aa_spec, dict) else str(aa_spec)
                    aa_n = int(aa_spec.get("count", 1)) if isinstance(aa_spec, dict) else 1
                    for c in me.characters:
                        if c.card.name == aa_name:
                            give = min(aa_n, me.don_active)
                            me.don_active -= give
                            c.attached_dons += give
                            state.push_log(f"  効果コスト: アクティブドン{give}を{aa_name}に付与")
                            break
                    continue
                if cs.get("rest_self") is True:
                    # rest_self: True 形式 (= self_inplay = ステージ/キャラ を rest)。
                    # 旧ガード not isinstance(..,(dict,int,str)) は bool が int 部分型のため
                    # True を誤除外し no-op だった (= 既存8枚含む rest_self cost 不発の pre-existing bug)。
                    if self_inplay is not None and not self_inplay.rested:
                        self_inplay.rested = True
                        state.push_log(f"  効果コスト: 自身レスト {self_inplay.card.name}")
                    continue
                if "return_self_to_deck_bottom" in cs:
                    # 「このカードを持ち主のデッキの下に置く」 cost。 self_inplay を chara/stage
                    # から取り除き me.deck 末尾へ。 付与ドンはレストでコストエリアへ。
                    if self_inplay is not None:
                        pool = me.characters if self_inplay in me.characters else (
                            me.stages if self_inplay in me.stages else None)
                        if pool is not None:
                            pool.remove(self_inplay)
                            me.deck.append(self_inplay.card)
                            if self_inplay.attached_dons > 0:
                                me.don_rested += self_inplay.attached_dons
                                self_inplay.attached_dons = 0
                            state.push_log(f"  効果コスト: {self_inplay.card.name} を デッキ下へ")
                    continue
                if "discard_hand" in cs:
                    # 任意 discard cost (= 「自分の手札 N 枚を捨てることができる：」、 例 P-151 スモーカー)。
                    # 人間 acting + 候補 > N なら どの手札を捨てるか 選ばせる (= _continuation で
                    # 残 cost + effect を継続)。 AI は _worst_hand_idx (= 温存価値の低い札) を捨てる。
                    n = int(cs.get("discard_hand", 0))
                    if n > 0:
                        if _should_human_pick(state) and len(me.hand) > n:
                            _oidx = state.players.index(me)
                            _sid = self_inplay.instance_id if self_inplay is not None else None
                            state.pending_choice = {
                                "kind": "self_hand_discard_pick",
                                "discard_only": True,
                                "candidates": [
                                    {"hand_idx": hi, "card_id": c.card_id, "name": c.name,
                                     "cost": int(c.cost) if c.cost is not None else 0,
                                     "power": int(c.power) if c.power is not None else 0}
                                    for hi, c in enumerate(me.hand)
                                ],
                                "limit": n,
                                "source_iid": _sid,
                                "_continuation": {
                                    "do": list(cost_specs[_ci + 1:]) + list(effect_specs),
                                    "owner_idx": _oidx,
                                    "source_iid": _sid,
                                },
                            }
                            state.push_log(
                                f"  効果コスト: 自手札 {n} 枚 捨て → 人間 選択 待ち(候補 {len(me.hand)})"
                            )
                            return False
                        # AI / 候補 <= N: 温存価値の低い札から N 枚捨てる。
                        for _ in range(min(n, len(me.hand))):
                            c = me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids))
                            me.trash.append(c)
                            state.push_log(f"  効果コスト: 手札捨て → {c.name}")
                    continue
                if "discard_hand_with_filter" in cs:
                    df_spec = cs["discard_hand_with_filter"]
                    if "filter" in df_spec:
                        d_filt = df_spec.get("filter", {})
                    else:
                        d_filt = {k: v for k, v in df_spec.items() if k != "count"}
                    d_count = int(df_spec.get("count", 1))
                    # 人間操作 中 + これが最後の cost spec (= 後続 cost なし → continuation が
                    # effect のみ) + 実際に選択の余地 (= 該当候補 > 捨て枚数) の時は、 どの該当
                    # カードを捨てるか を 本人 に 選ばせる (= counter_discard_pick + _continuation)。
                    # claudevsAI coby g5 で EB03-041 孔雀 の discard が 先頭一致 auto だった gap。
                    # 後続 cost ありの稀な 2 entry (OP04-055/OP02-048) と AI 操作 は 従来の auto。
                    if _should_human_pick(state) and _ci == len(cost_specs) - 1:
                        _matching = [
                            (hi, c) for hi, c in enumerate(me.hand)
                            if _matches_filter(c, d_filt)
                        ]
                        if len(_matching) > d_count:
                            _oidx = state.players.index(me)
                            _sid = (
                                self_inplay.instance_id if self_inplay is not None else None
                            )
                            state.pending_choice = {
                                "kind": "counter_discard_pick",
                                "when_key": "cost",
                                "card_id": (
                                    self_inplay.card.card_id
                                    if self_inplay is not None else ""
                                ),
                                "owner_idx": _oidx,
                                "source_iid": _sid,
                                "effect_idx": -1,  # enqueue 抑止 (effect は _continuation で実行)
                                "discard_n": d_count,
                                "cost": {"discard_hand_with_filter": df_spec},
                                "candidates": [
                                    {"hand_idx": hi, "card_id": c.card_id, "name": c.name,
                                     "cost": int(c.cost) if c.cost is not None else 0,
                                     "power": int(c.power) if c.power is not None else 0}
                                    for hi, c in _matching
                                ],
                                "limit": d_count,
                                "_continuation": {
                                    "do": list(effect_specs),
                                    "owner_idx": _oidx,
                                    "source_iid": _sid,
                                },
                            }
                            state.push_log(
                                "  効果コスト: 捨てる 該当手札 を 選択 待ち (人間)"
                            )
                            return False
                    discarded = 0
                    new_hand = []
                    _disc_names = []
                    for c in me.hand:
                        if discarded < d_count and _matches_filter(c, d_filt):
                            me.trash.append(c)
                            discarded += 1
                            _disc_names.append(c.name)
                            state.push_log(f"  効果コスト: 手札捨て (filter) → {c.name}")
                        else:
                            new_hand.append(c)
                    me.hand = new_hand
                    # EB02-039: 「捨てたカードと同名」 参照用に記録。
                    state.last_discarded_names = _disc_names
                    continue
                if "reveal_hand_with_filter" in cs:
                    # R4: 「自分の手札から特徴X を持つカード N 枚を公開することができる」 cost。
                    # 実消費なし (公開のみ)。 payability で確認済なのでログのみ。
                    rf_spec = cs["reveal_hand_with_filter"]
                    if "filter" in rf_spec:
                        r_filt = rf_spec.get("filter", {})
                    else:
                        r_filt = {k: v for k, v in rf_spec.items() if k != "count"}
                    r_count = int(rf_spec.get("count", 1))
                    revealed: list[str] = []
                    for c in me.hand:
                        if len(revealed) < r_count and _matches_filter(c, r_filt):
                            revealed.append(c.name)
                    state.push_log(f"  効果コスト: 手札公開 (実消費なし) → {revealed}")
                    continue
                if "rest_own_card" in cs:
                    # 公式 「自分のカード1枚をレストにできる：効果」 の支払い。
                    # AI 順 = **非リーダー優先 + power 昇順** (= リーダー/高power を温存、
                    # 起動メインコスト側 (effects.py の rest_own_card) と同順。 Rust も同順)。
                    _ro = cs["rest_own_card"]
                    _ro_n = int(_ro.get("count", 1)) if isinstance(_ro, dict) else int(_ro)
                    _ro_filt = _ro.get("filter", {}) if isinstance(_ro, dict) else {}
                    _ro_pool = [
                        ip for ip in ([me.leader] + list(me.characters) + list(me.stages))
                        if ip is not None and not ip.rested
                        and not getattr(ip, "cannot_be_rested_buff", False)
                        and not getattr(ip, "static_cannot_be_rested", False)
                        and _matches_filter_ip(ip, _ro_filt)
                    ]
                    _ro_pool.sort(key=lambda ip: (0 if ip is not me.leader else 1, ip.power))
                    for ip in _ro_pool[:_ro_n]:
                        ip.rested = True
                        state.push_log(f"  効果コスト: 自レスト {ip.card.name}")
                    continue
                if "stage_to_deck_bottom" in cs:
                    # 公式: ステージ N 枚を **持ち主の** デッキの下へ (= 相手のステージなら相手のデッキ)。
                    # AI 簡易: 該当する filter 一致の最初の N 枚 (= 任意選択は最古順) を取り出す。
                    #   side="either" のときは **相手側を先に** 見る (= 両陣営 spec の既定選好、
                    #   _either_pick_one と同順)。 コストで相手の場を削れるなら常にそちらが得。
                    sb_spec = cs["stage_to_deck_bottom"]
                    if isinstance(sb_spec, dict):
                        sb_count = int(sb_spec.get("count", 1))
                        sb_side = str(sb_spec.get("side", "self"))
                        sb_filt = {k: v for k, v in sb_spec.items()
                                   if k not in ("count", "side")}
                    else:
                        sb_count = int(sb_spec)
                        sb_side = "self"
                        sb_filt = {}
                    sb_owners = (
                        [(opp, "相手")] if sb_side == "either" else []
                    ) + [(me, "自")]
                    moved = 0
                    for _owner, _label in sb_owners:
                        if moved >= sb_count:
                            break
                        new_stages = []
                        for s in _owner.stages:
                            if moved < sb_count and _matches_filter_ip(s, sb_filt):
                                _owner.deck.append(s.card)
                                moved += 1
                                state.push_log(
                                    f"  効果コスト: {_label}ステージ → デッキ下 ({s.card.name})"
                                )
                                # 付与ドンは公式 6-5-5-4 同様にレストでコストエリアへ戻す。
                                if s.attached_dons > 0:
                                    _owner.don_rested += s.attached_dons
                            else:
                                new_stages.append(s)
                        _owner.stages = new_stages
                    continue
                if "return_self_chara_to_hand" in cs:
                    # 公式: 自キャラ N 枚を持ち主 (= me) の手札へ。
                    rh_spec = cs["return_self_chara_to_hand"]
                    if isinstance(rh_spec, dict):
                        rh_count = int(rh_spec.get("count", 1))
                        rh_filt = rh_spec.get("filter", {})
                    else:
                        rh_count = int(rh_spec)
                        rh_filt = {}
                    # AI 簡易: power 低い順に取り出す。
                    cands = [c for c in me.characters if _matches_filter_ip(c, rh_filt)]
                    cands.sort(key=lambda c: c.power)
                    if _maybe_pick_self_chara_cost(state, me, self_inplay, cands, rh_count, "hand",
                                                   list(cost_specs[_ci + 1:]) + list(effect_specs)):
                        return True
                    moved = 0
                    targets_to_move = set()
                    for c in cands:
                        if moved < rh_count:
                            targets_to_move.add(c.instance_id)
                            moved += 1
                    new_chars = []
                    for c in me.characters:
                        if c.instance_id in targets_to_move:
                            me.hand.append(c.card)
                            state.push_log(
                                f"  効果コスト: 自キャラ → 手札 ({c.card.name})"
                            )
                            if c.attached_dons > 0:
                                me.don_rested += c.attached_dons
                        else:
                            new_chars.append(c)
                    me.characters = new_chars
                    continue
                if "return_self_chara_to_deck_bottom" in cs:
                    # 公式: 自キャラ N 枚を持ち主 (= me) のデッキの下へ。
                    rb_spec = cs["return_self_chara_to_deck_bottom"]
                    if isinstance(rb_spec, dict):
                        rb_count = int(rb_spec.get("count", 1))
                        rb_filt = rb_spec.get("filter", {})
                    else:
                        rb_count = int(rb_spec)
                        rb_filt = {}
                    # AI 簡易: filter 一致の中から power 低い順 (= 最も惜しくないキャラ) を取り出す。
                    cands = [c for c in me.characters if _matches_filter_ip(c, rb_filt)]
                    if (isinstance(rb_spec, dict) and rb_spec.get("except_self")
                            and self_inplay is not None):
                        cands = [c for c in cands
                                 if c.instance_id != self_inplay.instance_id]
                    cands.sort(key=lambda c: c.power)
                    if _maybe_pick_self_chara_cost(state, me, self_inplay, cands, rb_count, "deck_bottom",
                                                   list(cost_specs[_ci + 1:]) + list(effect_specs)):
                        return True
                    moved = 0
                    targets_to_move = set()
                    for c in cands:
                        if moved < rb_count:
                            targets_to_move.add(c.instance_id)
                            moved += 1
                    new_chars = []
                    for c in me.characters:
                        if c.instance_id in targets_to_move:
                            me.deck.append(c.card)
                            state.push_log(
                                f"  効果コスト: 自キャラ → デッキ下 ({c.card.name})"
                            )
                            if c.attached_dons > 0:
                                me.don_rested += c.attached_dons
                        else:
                            new_chars.append(c)
                    me.characters = new_chars
                    continue
                if "ko_self_chara" in cs:
                    # 公式: 自分のキャラ N 枚を KO (= トラッシュへ)。 OP05-087 / EB04-048。
                    kc_spec = cs["ko_self_chara"]
                    if isinstance(kc_spec, dict):
                        kc_count = int(kc_spec.get("count", 1))
                        kc_filt = kc_spec.get("filter", {})
                        kc_excl = bool(kc_spec.get("exclude_self", False))
                    else:
                        kc_count = int(kc_spec)
                        kc_filt = {}
                        kc_excl = False
                    cands = [
                        c for c in me.characters
                        if _matches_filter_ip(c, kc_filt)
                        and not (kc_excl and self_inplay is not None
                                 and c.instance_id == self_inplay.instance_id)
                    ]
                    cands.sort(key=lambda c: c.power)  # AI 簡易: power 低い順を犠牲
                    if _maybe_pick_self_chara_cost(state, me, self_inplay, cands, kc_count, "ko",
                                                   list(cost_specs[_ci + 1:]) + list(effect_specs)):
                        return True  # 人間選択待ち(continuation で残りコスト+効果)
                    to_ko = {c.instance_id for c in cands[:kc_count]}
                    new_chars = []
                    for c in me.characters:
                        if c.instance_id in to_ko:
                            me.trash.append(c.card)
                            state.push_log(f"  効果コスト: 自キャラKO → {c.card.name}")
                            if c.attached_dons > 0:
                                me.don_rested += c.attached_dons
                        else:
                            new_chars.append(c)
                    me.characters = new_chars
                    continue
                execute_effect(cs, state, me, opp, self_inplay)
                # 人間操作で cost が target pick (return_to_hand other_self_chara 等) を
                # 要求し pending_choice を立てた場合、 ここで halt しないと直後の effect 実行が
                # pending_choice を上書きし cost が踏み倒される (= ジョズ OP08-047 で「自キャラを
                # 戻さずに相手キャラを戻す」 不正発火、 2026-06-10 発見)。 残り cost + effect を
                # continuation に退避 → resolve_pending_choice が cost 解決後に継続実行。
                if state.pending_choice is not None:
                    if "_continuation" not in state.pending_choice:
                        state.pending_choice["_continuation"] = {
                            "do": list(cost_specs[_ci + 1:]) + list(effect_specs),
                            "owner_idx": state.players.index(me),
                            "source_iid": (
                                self_inplay.instance_id if self_inplay is not None else None
                            ),
                        }
                    return False
            for _ei, es in enumerate(effect_specs):
                execute_effect(es, state, me, opp, self_inplay)
                # effect 側も同様に halt-aware (= 複数 effect で先頭が pick を要求した時に
                # 後続が上書きするのを防ぐ。 run_do_array と同じ pattern)。
                if state.pending_choice is not None:
                    if "_continuation" not in state.pending_choice:
                        state.pending_choice["_continuation"] = {
                            "do": list(effect_specs[_ei + 1:]),
                            "owner_idx": state.players.index(me),
                            "source_iid": (
                                self_inplay.instance_id if self_inplay is not None else None
                            ),
                        }
                    return False
            state.push_log(f"  効果: optional_cost_then 発動")
        elif k == "choice":
            # 公式: 「A するか B する」 (= A or B の選択)。
            # spec: {"options": [[<do_spec>...], [<do_spec>...]],
            #        "heuristic": "life_count" | None}
            # AI 簡易: heuristic="life_count" のとき
            #   自ライフ ≤ 1 → option=1 を優先 (= ライフ追加系を選ぶ想定)
            #   自ライフ ≥ 3 → option=0 を優先 (= ライフから手札への変換)
            #   それ以外 → option=0 (公式テキスト先頭)
            spec_val = v if isinstance(v, dict) else {"options": v}
            options = spec_val.get("options", [])
            if not options:
                return True

            def _norm_choice_opt(opt):
                inner = opt.get("do", opt) if isinstance(opt, dict) else opt
                return inner if isinstance(inner, list) else [inner]

            # 人間: 「AするかBする」を modal で選択(option_pick 再利用)。 AI: heuristic 自動。
            if len(options) >= 2 and _should_human_pick(state):
                norm = [_norm_choice_opt(o) for o in options]
                state.pending_choice = {
                    "kind": "option_pick",
                    "optional": False,
                    "options": [{"idx": i, "label": _describe_do_list(d)} for i, d in enumerate(norm)],
                    "_full_options": [{"do": d, "label": _describe_do_list(d)} for d in norm],
                    "_self_inplay_iid": self_inplay.instance_id if self_inplay else None,
                }
                state.push_log(f"  効果: choice 選択 待ち ({len(options)}択)")
                return True
            heuristic = spec_val.get("heuristic", "life_count")
            idx = 0
            if heuristic == "life_count" and len(options) >= 2:
                if len(me.life) <= 1:
                    idx = 1
                elif len(me.life) >= 3:
                    idx = 0
                else:
                    idx = 0
            chosen = options[idx]
            # chosen は do リスト or {"do": [...]} のどちらか許容
            inner = chosen.get("do", chosen) if isinstance(chosen, dict) else chosen
            if not isinstance(inner, list):
                inner = [inner]
            for sub_spec in inner:
                execute_effect(sub_spec, state, me, opp, self_inplay)
            state.push_log(f"  効果: choice (option={idx}/{len(options)})")
        elif k == "replace_ko_complex":
            # 既存 replace_ko (when="replace_ko" の do 配列内 primitive) を条件分岐対応に拡張。
            # 「リーダーが特徴X なら~、 それ以外なら~」 等の分岐を 1 effect 内で表現する。
            # spec: {"branches": [{"if": {...}, "do": [<primitive>...]}, ...]}
            # 上から順に if を評価し、 最初に True になった branch の do を実行 (排他)。
            # どの branch も成立せず、 default branch (= if 空 / 未指定) も無い場合は False を返す
            # (= 公式 4-10 「場合」 前文不実行)。
            spec_val = v if isinstance(v, dict) else {"branches": v if isinstance(v, list) else []}
            branches = spec_val.get("branches", [])
            chosen_branch = None
            for br in branches:
                cond = br.get("if", {}) if isinstance(br, dict) else {}
                if eval_condition(cond, state, me, self_inplay):
                    chosen_branch = br
                    break
            if chosen_branch is None:
                state.push_log(f"  効果: replace_ko_complex 該当 branch なし (不発)")
                return False
            do_spec = chosen_branch.get("do", []) if isinstance(chosen_branch, dict) else []
            for sub in do_spec:
                execute_effect(sub, state, me, opp, self_inplay)
            state.push_log(f"  効果: replace_ko_complex branch 実行")
        else:
            # 未対応はスキップ
            pass


def run_do_array(
    do_list: list[dict],
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay] = None,
) -> None:
    """do 配列を順次実行。公式 4-10 に従い「場合」前文不実行 → 後文不実行を扱う。

    do 配列の要素は通常 1 プリミティブ {"draw": 1} 等。
    新形式でチェーン制御を入れる場合: {"draw": 1, "_chain": "if_prev_succeeded"}
    のように予約キーを併置する。
    - `_chain: "if_prev_succeeded"` (= 「場合」): 前文が失敗していたらスキップ
    - `_chain: "always"` (= 「その後」/省略): 前文の成否に関わらず実行
    """
    prev_succeeded = True
    for i, spec in enumerate(do_list):
        chain = spec.get("_chain", "always")
        if chain == "if_prev_succeeded" and not prev_succeeded:
            continue
        # _chain は execute_effect には渡さない (純粋なプリミティブ part のみ)
        clean_spec = {k: v for k, v in spec.items() if k != "_chain"}
        result = execute_effect(clean_spec, state, me, opp, self_inplay)
        # 人間 interactive choice 待ち が 立った 場合 は 後続 を 止める。
        # 残り do を _continuation に退避 → resolve_pending_choice が選択解決後に継続実行。
        # (= search_top_n + trash_self_hand 等、 1 do-list 内に複数 interactive primitive が
        #    並ぶカード (OP13-086 シャルリア宮 等) で、 後続が pending_choice を上書きして
        #    前段の modal/効果を喪失する人間UXバグを防ぐ)。
        if state.pending_choice is not None:
            if "_continuation" not in state.pending_choice:
                state.pending_choice["_continuation"] = {
                    "do": list(do_list[i + 1:]),
                    "owner_idx": state.players.index(me),
                    "source_iid": self_inplay.instance_id if self_inplay is not None else None,
                }
            return
        # execute_effect は基本 True 返却 (現状)。将来各プリミティブで失敗判定するなら更新
        prev_succeeded = result if result is not None else True


def _run_continuation(state: GameState, cont: dict) -> None:
    """run_do_array が halt 時に保存した _continuation (残り do-items) を実行。

    owner_idx / source_iid から me/opp/self_inplay を復元し、 残り do を run_do_array で
    順次実行 (途中で再び pending_choice が立てば run_do_array が再度 continuation 保存)。"""
    do_items = cont.get("do") or []
    if not do_items:
        return
    owner_idx = int(cont.get("owner_idx", state.turn_player_idx))
    me = state.players[owner_idx]
    opp = state.players[1 - owner_idx]
    si = None
    sid = cont.get("source_iid")
    if sid is not None:
        for ip in [me.leader, *me.characters, *me.stages,
                   opp.leader, *opp.characters, *opp.stages]:
            if ip.instance_id == sid:
                si = ip
                break
    run_do_array(do_items, state, me, opp, si)


def resolve_pending_choice(state: GameState, picks: list[int]) -> None:
    """人間 選択 を 反映 して pending_choice を 解消 (wrapper)。

    解決後、 元の choice に _continuation (= 同 do-list の残り primitive、 run_do_array が
    halt 時に保存) があれば実行する。 chained choice (= 解決で新たな pending_choice が
    立つ) 時は continuation を引き継ぐ。"""
    choice = state.pending_choice
    if choice is None:
        return
    cont = choice.get("_continuation")
    _resolve_pending_choice_inner(state, picks)
    # 召喚等で場が変わった可能性 → 常在効果を再計算する。 apply_action は finally で
    # _recompute_static するが、 人間 modal 解決 (= play_from_trash 等) はその境界の外で
    # 起きるため、 召喚キャラの静的能力 (条件付き速攻・KO耐性等) が反映されない。
    # 例: OP13-080 イーザンバロン (自trash7+で速攻) を OP13-082 で召喚 → 再計算しないと
    # is_rush_now=False のままで「速攻なのに攻撃できない」 (2026-06-04 修正)。
    from .game import _recompute_static
    if state.pending_choice is not None:
        # 解決で新たな pending_choice が連鎖 → continuation を引き継ぐ
        if cont is not None and "_continuation" not in state.pending_choice:
            state.pending_choice["_continuation"] = cont
        _recompute_static(state)
        return
    if cont is not None:
        _run_continuation(state, cont)
    # continuation 実行 で 新たな pending_choice が 立った 場合 は その pick 待ち (= drain しない)。
    # 立っていなければ、 queue に 残った event (= resolve_triggers が pending_choice で halt し
    # 残した 別 enqueue の counter/trigger、 例: 温度の opp -2000) を 再 drain する。
    # resolve_triggers は state.resolving guard 付き で 再入 安全。
    if state.pending_choice is None and state.event_queue:
        resolve_triggers(state)
    _recompute_static(state)


def _resolve_pending_choice_inner(state: GameState, picks: list[int]) -> None:
    """人間 選択 を 反映 して pending_choice を 解消。

    picks の 意味 は choice.kind 別:
    - "search_top_n": 公開された seen[] の中で 選んだ idx の list (= 0-based)
    - "target_pick": candidates[] の中で 選んだ idx の list
    """
    choice = state.pending_choice
    if choice is None:
        return
    kind = choice.get("kind")
    me = state.players[state.turn_player_idx]
    opp = state.opponent
    # ⚠ actor 文脈の中央復元: modal を **非ターンプレイヤー** のトリガー (= on_ko 等で 自キャラが
    # KO された owner、 counter/trigger 等) で 立てた 場合、 me=turn_player のままだと 別プレイヤーの
    # zone を 操作してしまう (= 召喚系で「相手の hand から登場」 → EVENT を掴み キャラエリア汚染)。
    # raise 時に保存した _actor_idx で me/opp を復元する (= source_iid は on_ko で 場外/None になり
    # 当てにならない。 forced_human_actor_idx は event 解決中のみ で modal 解決時には消えている)。
    # _actor_idx を 持たない kind は 従来通り turn_player (= 影響なし)。 2026-06-05。
    _aidx = choice.get("_actor_idx")
    if isinstance(_aidx, int) and 0 <= _aidx < len(state.players):
        me = state.players[_aidx]
        opp = state.players[1 - _aidx]

    if kind == "search_top_n_bottom_reorder":
        # picks: 残り remaining cards を ど の 順 で deck 底 に 戻 す か の index list。
        # 2026-05-31 追加: ohtsuki さん 要望 「人 間 が 並 び 順 を 指 定 で きる」。
        # state.search_top_n_pending_remaining に 退 避 した CardDef list を 順 序 通 り に
        # deck.extend する。
        remaining = getattr(state, "search_top_n_pending_remaining", None) or []
        n = len(remaining)
        # picks を remaining の 過不足 ない permutation に 正 規 化 する。
        # ⚠ UI (= ScryDeckReorderModal 流用) は 並び順 の 後 ろ に 「上/下」 位置フラグ を
        #   1 要素 付加 して 送る が、 search_top_n は 常 に デッキ底 固定 な の で フラグ は 無視。
        #   フラグ値 (0/1) は 並び順 idx と 衝突 し う る ので、 重複 idx を 除去 +
        #   未指定 idx を 元順序 で 補完 → 必ず n 枚 ちょうど (= カード 複製/欠落 を 防ぐ)。
        #   空 picks or 全 不正 idx は 元順序 fallback (= 旧 動作 相当)。
        seen_idx: set[int] = set()
        ordered_idx: list[int] = []
        for i in picks:
            if isinstance(i, int) and 0 <= i < n and i not in seen_idx:
                ordered_idx.append(i)
                seen_idx.add(i)
        for i in range(n):
            if i not in seen_idx:
                ordered_idx.append(i)
        ordered = [remaining[i] for i in ordered_idx]
        me.deck.extend(ordered)
        state.search_top_n_pending_remaining = None
        state.pending_choice = None
        state.push_log(
            f"  効果: search_top_n 残り{len(ordered)}枚 → デッキ底 (人 間 指 定 順)"
        )
        return

    if kind == "field_full_select_trash":
        # 場 5 体 差替 え 人 間 選 択 (= 公 式 3-7-6-1)。 picks[0] = candidates index。
        # 既 場 に は 新 chara が append 済 で 6 体 状 態。 picked chara を trash → 5 体 に。
        candidates = choice.get("candidates", [])
        owner_idx = choice.get("owner_idx", state.turn_player_idx)
        owner = state.players[owner_idx]
        pick_idx = picks[0] if picks else 0
        if not (0 <= pick_idx < len(candidates)):
            pick_idx = 0
        sacrifice_iid = candidates[pick_idx]["iid"]
        sacrifice = next(
            (c for c in owner.characters if c.instance_id == sacrifice_iid),
            None,
        )
        state.pending_choice = None
        if sacrifice is None:
            state.push_log(
                f"  差替 (3-7-6-1) skip: target iid={sacrifice_iid} 不 在"
            )
            return
        owner.characters.remove(sacrifice)
        owner.trash.append(sacrifice.card)
        if sacrifice.attached_dons > 0:
            owner.don_rested += sacrifice.attached_dons
        state.push_log(
            f"  差替 (3-7-6-1): {sacrifice.card.name} をトラッシュへ "
            f"(KO ではないため【KO時】不発動)"
        )
        return

    if kind == "target_pick":
        # target_pick: choices[i] → 該当 iid を 抜き出し、 _iid_picks を 渡して 再実行
        # ⚠ limit で cap + 重複除去 する (= 人間が上限超/重複を送っても防御。 各 target
        #   primitive (ko/return/rest/pump 等) は _iid_picks 全件に適用するため、 ここで
        #   絞らないと「KO1体」 効果で複数 KO できてしまう。 2026-06-04 修正)。
        candidates = choice.get("candidates", [])
        limit = int(choice.get("limit", 1) or 1)
        seen_pi: set[int] = set()
        uniq_picks: list[int] = []
        for i in picks:
            if 0 <= i < len(candidates) and i not in seen_pi:
                seen_pi.add(i)
                uniq_picks.append(i)
        picked_iids = [candidates[i]["iid"] for i in uniq_picks[:limit]]
        primitive_kind = choice.get("primitive_kind", "")
        primitive_value = choice.get("primitive_value") or {}
        self_inplay_iid = choice.get("self_inplay_iid")
        # self_inplay を 復元
        self_inplay = None
        if self_inplay_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == self_inplay_iid:
                    self_inplay = ip
                    break
        # 再実行: target_spec に _iid_picks を 追加 (= 任意 spec 形式 を カバー)。
        # primitive 側 の target 抽出 が ① v を 直接 target_spec とする / ② v.get("target") から
        # 取る、 の 2 系統 あるため、 top-level と "target" subfield の 両方に _iid_picks を 入れて
        # どちら の 読み方 でも bypass が 効く ように する。
        # (= ② 系 (return_to_deck_bottom 等) で string spec 再実行 時 に v.get("target") が default に
        #    戻り target を 再解決 → 無限 target_pick 再表示 する 人間UXバグ の 修正)
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
            new_spec["_iid_picks"] = picked_iids
            base_t = new_spec["target"] if isinstance(new_spec.get("target"), dict) else {}
            new_spec["target"] = {**base_t, "_iid_picks": picked_iids}
        else:
            # 文字列 spec (例: "one_opponent_character_any") → dict 化 して bypass
            new_spec = {"_iid_picks": picked_iids, "target": {"_iid_picks": picked_iids}}
        state.pending_choice = None  # 先 に クリア (= 再実行 中 に 別 choice 立てる 可能性 防ぐ)
        state.push_log(f"  効果: 人間選択 → {primitive_kind} 対象 {len(picked_iids)} 枚")
        execute_effect({primitive_kind: new_spec}, state, me, opp, self_inplay)
        return

    if kind == "optional_cost_confirm":
        # 任意コスト (= 公式「〜できる：」) の pay/skip 人間選択。 picks[0]==1 → pay。
        # pay → 同 spec を _cost_confirmed 付き で 再実行 (= gate bypass、 cost+effect 実行。
        # effect 内 の target pick 等 は さらに pending_choice を 連鎖 で 立てる)。
        spec = dict(choice.get("spec") or {})
        self_inplay_iid = choice.get("self_inplay_iid")
        self_inplay = None
        if self_inplay_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == self_inplay_iid:
                    self_inplay = ip
                    break
        state.pending_choice = None
        if not (picks and picks[0] == 1):
            state.push_log(f"  効果: 任意コスト 見送り ({choice.get('source_name', '')})")
            return
        spec["_cost_confirmed"] = True
        # ⭐ pay_don コストで「場のドン」(area active/rested + 各キャラ/リーダーの付与ドン)の返却元を
        # 人間に選ばせる (2026-07-08、 ohtsuki 指摘: 付与ドンも返却可)。
        pd_n = 0
        for cs in (spec.get("cost") or []):
            if isinstance(cs, dict) and "pay_don" in cs:
                pd_n = int(cs.get("pay_don", 0) or 0)
                break
        sources = _don_return_sources(me)
        total_avail = sum(s["avail"] for s in sources)
        if pd_n > 0 and len(sources) >= 2 and pd_n < total_avail and not spec.get("_don_split_done"):
            state.pending_choice = {
                "kind": "don_return_pick", "spec": spec,
                "self_inplay_iid": self_inplay_iid, "pay_don": pd_n,
                "sources": sources, "source_name": choice.get("source_name", ""),
                "prompt": f"ドン-{pd_n}: 戻すドンを {pd_n}枚 選んでください。",
            }
            return
        execute_effect({"optional_cost_then": spec}, state, me, opp, self_inplay)
        return

    if kind == "don_return_pick":
        # 人間が pay_don コストで返却元を選択。 picks = source index のリスト(1 ドンにつき 1 index、 長さ pay_don)。
        # 不足分は area 優先で補完。 割当を state._don_return_alloc にして再実行 → pay_don が消費。
        spec = dict(choice.get("spec") or {})
        self_inplay_iid = choice.get("self_inplay_iid")
        self_inplay = None
        if self_inplay_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages, *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == self_inplay_iid:
                    self_inplay = ip; break
        sources = choice.get("sources", [])
        pd_n = int(choice.get("pay_don", 0))
        alloc = {"active": 0, "rested": 0, "attached": {}}
        avail = {i: int(s["avail"]) for i, s in enumerate(sources)}

        def _add_src(i):
            key = sources[i]["key"]
            if key == "active":
                alloc["active"] += 1
            elif key == "rested":
                alloc["rested"] += 1
            else:
                alloc["attached"][key] = alloc["attached"].get(key, 0) + 1
            avail[i] -= 1

        used = 0
        for i in (picks or []):
            if used >= pd_n:
                break
            if isinstance(i, int) and 0 <= i < len(sources) and avail.get(i, 0) > 0:
                _add_src(i); used += 1
        if used < pd_n:  # 不足は avail のある source から順に補完(area 優先 = sources 先頭順)
            for i in range(len(sources)):
                while used < pd_n and avail.get(i, 0) > 0:
                    _add_src(i); used += 1
        state.pending_choice = None
        state._don_return_alloc = alloc
        spec["_don_split_done"] = True
        state.push_log(f"  効果: ドン返却割当 = {alloc}")
        execute_effect({"optional_cost_then": spec}, state, me, opp, self_inplay)
        return

    if kind == "self_chara_cost_pick":
        # コストで犠牲にする自キャラを人間が選択(ko/hand/deck_bottom)。 picks = candidates idx list。
        # 残りコスト+効果は _continuation で解決後に自動実行(resolve_pending_choice 上位)。
        cands = choice.get("candidates", [])
        action = choice.get("action", "ko")
        limit = int(choice.get("limit", 1))
        picks_iids = {cands[i]["iid"] for i in (picks or []) if 0 <= i < len(cands)}
        state.pending_choice = None
        moved = 0
        for c in list(me.characters):
            if moved >= limit:
                break
            if c.instance_id in picks_iids:
                me.characters.remove(c)
                if c.attached_dons > 0:
                    me.don_rested += c.attached_dons
                if action == "ko":
                    me.trash.append(c.card)
                elif action == "hand":
                    me.hand.append(c.card)
                elif action == "deck_bottom":
                    me.deck.append(c.card)
                state.push_log(f"  効果コスト: 自キャラ {action} → {c.card.name}")
                moved += 1
        return

    if kind == "give_keyword_choice":
        # カタリーナ・デボン等「ダブルアタックかバニッシュかブロッカーを得る」の3択を人間が選択。
        # picks[0] = keywords の index。 _chosen_keyword 付きで give_keyword を再実行。
        kws = choice.get("keywords", [])
        spec = choice.get("spec")
        self_inplay_iid = choice.get("self_inplay_iid")
        self_inplay = None
        if self_inplay_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages, *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == self_inplay_iid:
                    self_inplay = ip
                    break
        idx = int(picks[0]) if (picks and picks[0] is not None) else 0
        chosen = kws[idx] if (0 <= idx < len(kws)) else (kws[0] if kws else "速攻")
        state.pending_choice = None
        new_spec = {**(spec if isinstance(spec, dict) else {}), "_chosen_keyword": chosen}
        execute_effect({"give_keyword": new_spec}, state, me, opp, self_inplay)
        return

    if kind == "play_from_trash_or_life_pick":
        # ゲッコー・モリア OP14-104【登場時】「ライフの上に表向きで加えるか登場させる」 の
        # 行き先 選択 (human)。 picks[0] = actions[] の index (= 候補 × {登場/ライフ})。
        # picks 空 / 範囲外 = skip (= 0 枚、 「~まで」 なので合法)。
        actions = choice.get("actions", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        state.pending_choice = None
        if not picks or picks[0] < 0 or picks[0] >= len(actions):
            state.push_log("  効果: モリア 登場/ライフ → 0 枚 選択 (= skip)")
            return
        act = actions[picks[0]]
        ti = int(act.get("trash_idx", -1))
        if not (0 <= ti < len(me.trash)):
            state.push_log("  効果: モリア 行き先 選択: trash idx 不正 → skip")
            return
        if act.get("dest") == "life":
            card = me.trash.pop(ti)
            me.life.insert(0, card)  # 「ライフの上」 = top
            me.face_up_life_count = min(
                getattr(me, "face_up_life_count", 0) + 1, len(me.life)
            )
            state.push_log(f"  効果: {card.name} をライフの上に表向きで加えた (= モリア)")
        else:
            # 登場: 既存 play_from_trash の picks 解決 path を 再利用 (or_to_life は外す)
            new_spec = dict(primitive_value) if isinstance(primitive_value, dict) else {}
            new_spec["_picks_idx"] = [ti]
            new_spec.pop("or_to_life", None)
            execute_effect({"play_from_trash": new_spec}, state, me, opp, self_inplay)
        return

    if kind == "game_start_stage_pick":
        # ゲーム開始時「デッキから特徴Xのステージ1枚まで登場」の人間選択 (= イム)。
        # picks: candidates[] の index (0 or 1)。
        # ⚠ 空 picks (= モーダル未対応の古いフロント / 汎用 skip) では「登場させない」でなく
        #   最良 (= 最高コスト) を自動登場させる。 理由: 無 stage は旧挙動 (全員自動登場) からの
        #   regression + イムは開始 stage をほぼ常に出したい。 backend/frontend の別々デプロイの
        #   タイミング差 (= 新 pending_choice が古いフロントに届く窓) でも stage を失わない。
        candidates = choice.get("candidates", [])
        pidx = int(choice.get("_player_idx", state.turn_player_idx))
        p = state.players[pidx]
        state.pending_choice = None
        valid = [i for i in picks if 0 <= i < len(candidates)]
        if valid:
            deck_idx = int(candidates[valid[0]]["deck_idx"])
        elif candidates:
            # 空 picks → 最高コストを自動登場 (= 無 stage 回避)
            best = max(candidates, key=lambda c: int(c.get("cost", 0)))
            deck_idx = int(best["deck_idx"])
            state.push_log(f"  game_start: {p.name} ステージ自動選択 (skip → 最良)")
        else:
            return
        if not (0 <= deck_idx < len(p.deck)):
            return
        card = p.deck.pop(deck_idx)
        ip = InPlay.of(card, rested=False, sickness=False)
        p.stages.append(ip)
        p.shuffle_deck(state.rng)  # search 後はデッキシャッフル (公式)
        state.push_log(
            f"  game_start: {p.name} ({p.leader.card.name}) → ステージ登場: {card.name}"
        )
        return

    if kind in ("play_from_trash_pick", "summon_from_deck_pick"):
        # picks: candidates[] の index list → trash_idx / deck_idx へ。 空 = skip。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        if kind == "play_from_trash_pick":
            zone_idxs = [int(candidates[i]["trash_idx"]) for i in valid_picks]
            target_primitive = "play_from_trash"
            zone_label = "トラッシュ"
        else:
            zone_idxs = [int(candidates[i]["deck_idx"]) for i in valid_picks]
            target_primitive = "summon_from_deck"
            zone_label = "デッキ"
        state.pending_choice = None
        if not zone_idxs:
            state.push_log(f"  効果: {target_primitive} 0 枚 選択 (= skip)")
            return
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {}
        new_spec["_picks_idx"] = zone_idxs
        state.push_log(
            f"  効果: 人間選択 → {zone_label} から 登場 {len(zone_idxs)} 枚"
        )
        execute_effect({target_primitive: new_spec}, state, me, opp, self_inplay)
        return

    if kind == "self_hand_discard_pick":
        # trash_self_hand_random 人間 pick: picks = candidates idx list。
        # candidates[i]["hand_idx"] = me.hand 内 の 実 index。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        hand_idxs = [int(candidates[i]["hand_idx"]) for i in valid_picks]
        state.pending_choice = None
        if not hand_idxs:
            # 公式 「N 枚 捨てる」 は 強制 (= 拒否 不可)、 ただし 「~枚 まで」 なら 0 OK。
            # ここ で 0 を 許す と 「~枚 捨てる」 強制 でも スキップ できて しまう。
            # しかし limit=N で N 枚 強制 か N 枚 まで か は overlay spec で 区別 不可能。
            # 安全 策: AI fallback で 既 完了 した の と 同 結 果 を 出す ため、
            # 候補 数 が limit 以上 ある なら 残り は random で 補完 する。
            limit = int(choice.get("limit", 1))
            for _ in range(limit):
                if not me.hand:
                    break
                me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
            state.push_log(f"  効果: 自手札 {limit} 枚 トラッシュ (= 人間 skip 後 最悪札 fallback)")
            return
        # discard_only: 既に draw 等が済んでいる系(draw_per_self_chara_then_discard / self_hand_to_size)
        # は primitive を再実行せず、 選んだ手札を捨てるだけ(= 再 draw を防ぐ)。
        if choice.get("discard_only"):
            for hi in sorted(set(hand_idxs), reverse=True)[: int(choice.get("limit", len(hand_idxs)))]:
                if 0 <= hi < len(me.hand):
                    me.trash.append(me.hand.pop(hi))
            state.push_log(f"  効果: 人間選択 → 自手札 {len(hand_idxs)} 枚 トラッシュ")
            return
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {"amount": int(choice.get("limit", 1))}
        new_spec["_picked_hand_idxs"] = hand_idxs
        prim = choice.get("primitive_kind", "trash_self_hand_random")
        state.push_log(f"  効果: 人間選択 → 自手札 {len(hand_idxs)} 枚 トラッシュ")
        execute_effect({prim: new_spec}, state, me, opp, self_inplay)
        return

    if kind == "self_hand_to_deck_pick":
        # self_hand_to_deck_bottom 人間 pick: picks = candidates idx list。
        # candidates[i]["hand_idx"] = me.hand 内 の 実 index。空 list なら
        # 残量 を ヒューリスティック で 補完 (= 公式 「N 枚 置く」 は 強制)。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        hand_idxs = [int(candidates[i]["hand_idx"]) for i in valid_picks]
        state.pending_choice = None
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {"amount": int(choice.get("limit", 1))}
        new_spec["_picked_hand_idxs"] = hand_idxs
        state.push_log(f"  効果: 人間選択 → 自手札 {len(hand_idxs)} 枚 デッキへ")
        execute_effect({"self_hand_to_deck_bottom": new_spec}, state, me, opp, self_inplay)
        return

    if kind == "optional_discard_buff_pick":
        # optional_discard_hand_for_battle_buff 人間 pick (= OP15-002 ルーシー /
        # OP03-001 エース 等)。 picks = candidates idx list (= 0 始まり)。
        # 空 list = 見送り (= 0 枚 捨て、 pump なし。 「捨ててもよい」 = 任意)。
        # me/opp は冒頭で _actor_idx により actor 復元済 (= 相手アタック時 の 防御側 pump でも
        # 正しく human defender の 手札 から 捨て、 buff は human leader に 載る)。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        hand_idxs = [int(candidates[i]["hand_idx"]) for i in valid_picks]
        state.pending_choice = None
        new_spec = dict(primitive_value) if isinstance(primitive_value, dict) else {}
        new_spec["_picked_hand_idxs"] = hand_idxs  # 空 = 見送り
        if hand_idxs:
            state.push_log(
                f"  効果: 人間選択 → イベント/ステージ {len(hand_idxs)} 枚 捨て pump"
            )
        else:
            state.push_log("  効果: 人間選択 → 捨てず (pump 見送り)")
        execute_effect(
            {"optional_discard_hand_for_battle_buff": new_spec}, state, me, opp, self_inplay
        )
        return

    if kind == "search_pick":
        # search (= deck 全 サーチ) 人間 選択。 picks: candidates index list。
        # candidates[i]["idx"] = me.deck の 元 index。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        deck_idxs = [int(candidates[i]["idx"]) for i in valid_picks]
        state.pending_choice = None
        if not deck_idxs:
            state.push_log("  効果: サーチ 0 枚 選択 (= skip)")
            # サーチ は スキップ でも シャッフル する (= 公式: 「探した」 の 行為 で
            # デッキ シャッフル 必要)
            state.rng.shuffle(me.deck)
            me.known_bottom_card_ids.clear()
            me.known_top_card_ids.clear()
            return
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {}
        new_spec["_picked_deck_idxs"] = deck_idxs
        state.push_log(f"  効果: 人間選択 → サーチ {len(deck_idxs)} 枚")
        execute_effect({"search": new_spec}, state, me, opp, None)
        return

    if kind == "search_from_trash_pick":
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        trash_idxs = [int(candidates[i]["trash_idx"]) for i in valid_picks]
        state.pending_choice = None
        if not trash_idxs:
            state.push_log("  効果: トラッシュ サーチ 0 枚 選択 (= skip)")
            return
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {}
        new_spec["_picked_trash_idxs"] = trash_idxs
        state.push_log(f"  効果: 人間選択 → トラッシュ サーチ {len(trash_idxs)} 枚")
        execute_effect({"search_from_trash": new_spec}, state, me, opp, self_inplay)
        return

    if kind == "play_from_hand_or_trash_pick":
        # picks: candidates[] の index list。 candidate に source + idx が ある
        # ので spec.{_picks: [{source, idx}, ...]} の 形 で 再実行 する。
        # me/opp は冒頭で _actor_idx により actor 復元済 (= off-turn トリガーでも 正しい
        # プレイヤーの hand/trash を操作)。 picks 実行パスも category/filter を再検証する。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        picked_payload = [
            {"source": candidates[i]["source"], "idx": int(candidates[i]["idx"])}
            for i in valid_picks
        ]
        state.pending_choice = None
        if not picked_payload:
            state.push_log("  効果: 手札 か トラッシュ から 登場 0 枚 選択 (= skip)")
            return
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {}
        new_spec["_picks"] = picked_payload
        state.push_log(
            f"  効果: 人間選択 → 手札/トラッシュ から 登場 {len(picked_payload)} 枚"
        )
        execute_effect({"play_from_hand_or_trash": new_spec}, state, me, opp, self_inplay)
        return

    if kind in ("play_from_hand_pick", "hand_to_life_pick", "play_event_from_hand_pick",
                "reveal_hand_play_split_pick"):
        # 手札 から 候補 を 選ばせる 系統 (= play_from_hand / hand_to_self_life /
        # play_event_from_hand / reveal_hand_play_split)。 共通の picks → hand_idx 抽出 + spec 再実行 path。
        candidates = choice.get("candidates", [])
        primitive_value = choice.get("primitive_value") or {}
        source_iid = choice.get("source_iid")
        # self_inplay 復元
        self_inplay = None
        if source_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == source_iid:
                    self_inplay = ip
                    break
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        # candidates[i]["hand_idx"] → 実 hand idx
        hand_idxs = [int(candidates[i]["hand_idx"]) for i in valid_picks]
        state.pending_choice = None
        kind_to_primitive = {
            "play_from_hand_pick": "play_from_hand",
            "hand_to_life_pick": "hand_to_self_life",
            "play_event_from_hand_pick": "play_event_from_hand",
            "reveal_hand_play_split_pick": "reveal_hand_play_split",
        }
        target_primitive = kind_to_primitive[kind]
        if not hand_idxs:
            state.push_log(f"  効果: {target_primitive} 0 枚 選択 (= skip)")
            return
        # spec に _picks_idx 注入 して 再実行 (= 既 解決 path)
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
        else:
            new_spec = {}
        new_spec["_picks_idx"] = hand_idxs
        state.push_log(
            f"  効果: 人間選択 → {target_primitive} {len(hand_idxs)} 枚"
        )
        execute_effect({target_primitive: new_spec}, state, me, opp, self_inplay)
        return

    if kind == "life_taken_choice":
        from .game import resume_pending_attack_hit
        use_trigger = bool(picks and picks[0] == 1)
        state.pending_choice = None
        resume_pending_attack_hit(state, use_trigger)
        return

    if kind == "replace_ko_optional":
        # ヴェルゴ 等 「もよい」 系 replace_ko / replace_leave の 人間 選択。
        # picks[0] = 1 → 「使う」 (= cost 払って do 実行、 KO/離脱 canceled)
        # picks[0] = 0 / picks=[] → 「使わない」 (= victim を 通常 KO/離脱)
        use_replace = bool(picks and picks[0] == 1)
        victim_iid = choice.get("victim_iid")
        holder_iid = choice.get("holder_iid")
        owner_idx = int(choice.get("owner_idx", 0))
        when_key = str(choice.get("when") or "replace_ko")
        do_spec = choice.get("do_spec", []) or []
        cost_specs = choice.get("cost_specs", []) or []
        leave_kind = str(choice.get("leave_kind") or "ko")
        state.pending_choice = None
        owner = state.players[owner_idx]
        # holder / victim を iid で 復元
        all_inplay = [owner.leader, *owner.characters, *owner.stages]
        holder = next((ip for ip in all_inplay if ip.instance_id == holder_iid), None)
        victim = next((ip for ip in all_inplay if ip.instance_id == victim_iid), None)
        if victim is None:
            state.push_log(f"  replace_ko_optional resume: victim 既に 不在 → skip")
            return
        if use_replace and holder is not None:
            # cost 払う + do 実行 → KO は cancel された (= victim 場 に 残る)
            holder_cid = holder.card.card_id
            if cost_specs:
                _pay_replace_cost(state, owner, cost_specs, holder_cid, holder)
            state.push_log(
                f"  離脱置換 ({when_key}): {victim.card.name} → {holder.card.name} の効果で代替"
            )
            prev_replace_victim = getattr(state, "last_replace_victim", None)
            state.last_replace_victim = victim
            try:
                opp_player = state.players[1 - owner_idx]
                for prim in do_spec:
                    execute_effect(prim, state, owner, opp_player, holder)
            finally:
                state.last_replace_victim = prev_replace_victim
            return
        # 「使わない」 → 通常 KO/離脱 を 実施 + 同 victim を declined set に
        if not hasattr(state, "_replace_ko_declined_iids"):
            state._replace_ko_declined_iids = set()
        state._replace_ko_declined_iids.add(victim.instance_id)
        state.push_log(f"  離脱置換 ({when_key}) 不使用 → {victim.card.name} を 通常 KO/離脱")
        # KO 系 のみ inline で 実施 (= return_to_hand/deck は 元 caller が 処理)
        # leave_kind に 応じて zone を 移動
        opp_player = state.players[1 - owner_idx]
        if victim in owner.characters:
            owner.characters.remove(victim)
        elif victim is owner.leader:
            # leader は 通常 trash されない (= ゲーム 終了 でない 限り)。 ここで は no-op
            return
        if leave_kind == "ko":
            owner.trash.append(victim.card)
            if victim.attached_dons > 0:
                owner.don_rested += victim.attached_dons
            state.push_log(f"  効果: KO {victim.card.name} (= replace 不使用 経路)")
            if state.effects_overlay:
                trigger_on_ko(state, owner, opp_player, victim.card,
                              state.effects_overlay, by_opp_effect=bool(choice.get("by_opp_effect")),
                              victim_attached_don=victim.attached_dons, victim_effect_negated=_ip_effect_negated(victim))
                trigger_on_opp_chara_ko(state, opp_player, owner, state.effects_overlay)
                trigger_on_self_chara_ko(state, owner, opp_player, state.effects_overlay)
        elif leave_kind == "return_to_hand":
            owner.add_to_hand_publicly(victim.card)
            if victim.attached_dons > 0:
                owner.don_rested += victim.attached_dons
        elif leave_kind == "return_to_deck_bottom":
            owner.deck.append(victim.card)
            if victim.attached_dons > 0:
                owner.don_rested += victim.attached_dons
        elif leave_kind == "chara_to_trash":
            # 非 KO のトラッシュ送り (= 「トラッシュに置く」)。 zone は trash だが
            # KO ではないので 【KO時】 トリガーは 発動しない (leave トリガーは 呼出元で発火)。
            owner.trash.append(victim.card)
            if victim.attached_dons > 0:
                owner.don_rested += victim.attached_dons
        return

    if kind == "on_opp_attack_optional":
        # picks[0] = 1 → 使う、 0 → skip
        # on_opp_attack 効果 source は 「defender」 = 1 - turn_player_idx 側
        use_eff = bool(picks and picks[0] == 1)
        when_key = str(choice.get("when_key") or "opp_attack")
        eff_idx = int(choice.get("effect_idx", -1))
        source_iid = choice.get("source_iid")
        pay_don = int(choice.get("pay_don", 0))
        discard_n = int(choice.get("discard_hand", 0))
        state.pending_choice = None
        # defender = 1 - turn_player (= 攻撃 受け 側、 効果 の 自分 側)
        defender_idx = 1 - state.turn_player_idx
        defender = state.players[defender_idx]
        if not use_eff or eff_idx < 0:
            state.push_log(f"  opp_attack 効果 不使用 (skip)")
            return
        source = None
        for ip in [defender.leader, *defender.characters, *defender.stages]:
            if ip.instance_id == source_iid:
                source = ip
                break
        if source is None:
            return
        # 支払い (= discard は random、 ユーザ 選択 modal は 将来 拡張)
        rest_don = int(choice.get("rest_self_don", 0))
        if pay_don > 0:
            from_active = min(defender.don_active, pay_don)
            defender.don_active -= from_active
            defender.don_rested += from_active
        if rest_don > 0:
            defender.don_active -= rest_don
            defender.don_rested += rest_don
        if discard_n > 0:
            # 防御側の手札 discard もその所有者が選ぶ → 最悪札から(AI の value 判断を random で薄めない)。
            for _ in range(min(discard_n, len(defender.hand))):
                defender.trash.append(defender.hand.pop(_worst_hand_idx(defender.hand, defender.known_hand_card_ids)))
        bundle = state.effects_overlay.get(source.card.card_id) if state.effects_overlay else None
        eff = bundle.effects[eff_idx] if (bundle and 0 <= eff_idx < len(bundle.effects)) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        if cost.get("once_per_turn"):
            source.mark_attack_once_used(eff_idx)
        enqueue_event(
            state,
            when=when_key,
            owner_idx=defender_idx,
            source_card_id=source.card.card_id,
            source_iid=source.instance_id,
            payload={"effect_indexes": [eff_idx]},
        )
        prev_forced = getattr(state, "forced_human_actor_idx", None)
        state.forced_human_actor_idx = defender_idx
        try:
            _maybe_resolve(state)
        finally:
            state.forced_human_actor_idx = prev_forced
        return

    if kind == "end_of_turn_optional":
        # picks = available[] の index の list (= 発動 を 選んだ もの だけ)。
        # picks=[] なら 全 skip。 picks=[0,2] なら 0 番目 と 2 番目 を 順に 発動。
        available = choice.get("available", []) or []
        state.pending_choice = None
        # 重複排除 + range guard
        seen = set()
        ordered_picks: list[int] = []
        for i in picks:
            if isinstance(i, int) and 0 <= i < len(available) and i not in seen:
                seen.add(i)
                ordered_picks.append(i)
        # 支払い + enqueue 順 は user pick 順 を 尊重 (= 公式 8-1-3 同陣営内 順序 任意)
        for i in ordered_picks:
            item = available[i]
            owner_idx = int(item["owner_idx"])
            owner = state.players[owner_idx]
            opp_for_pay = state.players[1 - owner_idx]
            source = None
            for ip in [owner.leader, *owner.characters, *owner.stages]:
                if ip.instance_id == item["source_iid"]:
                    source = ip
                    break
            if source is None:
                # 場 から 消えた (= 直前 の effect で trash 等) → skip
                state.push_log(
                    f"  ターン終了 任意効果: {item.get('card_name','?')} は 既に 場 に いない (skip)"
                )
                continue
            bundle = state.effects_overlay.get(source.card.card_id) if state.effects_overlay else None
            if bundle is None:
                continue
            eff_idx = int(item["effect_idx"])
            eff = bundle.effects[eff_idx] if 0 <= eff_idx < len(bundle.effects) else None
            if eff is None:
                continue
            cost = eff.get("cost") or {}
            # 再 verify (= 場 状況 変化 で 払えなくなった ケース ガード)
            if not _can_pay_end_of_turn_cost(state, owner, source, cost):
                state.push_log(
                    f"  ターン終了 任意効果: {source.card.name} cost 払えず skip"
                )
                continue
            state.push_log(f"ターン終了任意: {source.card.name}")
            _pay_end_of_turn_cost(state, owner, opp_for_pay, source, cost, eff_idx)
            enqueue_event(
                state,
                when=str(item.get("when_key", "end_of_turn")),
                owner_idx=owner_idx,
                source_card_id=item["card_id"],
                source_iid=item["source_iid"],
                payload={"effect_indexes": [eff_idx]},
            )
        # skip された ものは log だけ
        skipped_n = len(available) - len(ordered_picks)
        if skipped_n > 0:
            state.push_log(
                f"  ターン終了 任意効果: {skipped_n}件 skip"
            )
        # forced_human_actor で human owner の target_pick が 立つよう に
        prev_forced = getattr(state, "forced_human_actor_idx", None)
        if state.human_player_idx is not None:
            state.forced_human_actor_idx = state.human_player_idx
        try:
            _maybe_resolve(state)
        finally:
            state.forced_human_actor_idx = prev_forced
        if state.pending_choice is not None:
            # nested target_pick 等 → user 解決 待ち、 advance_phase は 後段 で 自然 再開
            return
        # END phase の 後半 (= reset_turn_buff + turn flip + REFRESH→MAIN) を 駆動
        from .game import advance_phase, play_until_main
        # advance_phase Phase.END handler は _end_of_turn_done フラグ で trigger 再発 を skip
        advance_phase(state)
        if state.pending_choice is not None or state.game_over:
            return
        play_until_main(state)
        return

    if kind == "counter_discard_pick":
        # event cost 「自分の手札 N 枚 捨てる：効果」 で 人間 が 捨てる カード を 選んだ ところ。
        # 適用 when: counter / on_play / on_ko / on_block / main / trigger / on_*_X
        # picks=[] (= skip) なら 効果 不発 (= 公式 4-10 cost 払えず)。
        candidates = choice.get("candidates", []) or []
        discard_n = int(choice.get("discard_n", 1))
        cost = choice.get("cost") or {}
        when_key = str(choice.get("when_key", "counter"))
        card_id = choice.get("card_id", "")
        owner_idx = int(choice.get("owner_idx", state.turn_player_idx))
        source_iid = choice.get("source_iid")
        eff_idx = int(choice.get("effect_idx", -1))
        owner = state.players[owner_idx]
        opp_for_pay = state.players[1 - owner_idx]
        valid_picks = [i for i in picks if isinstance(i, int) and 0 <= i < len(candidates)]
        hand_idxs = sorted(
            list({int(candidates[i]["hand_idx"]) for i in valid_picks}),
            reverse=True,
        )
        state.pending_choice = None
        if len(hand_idxs) < discard_n:
            state.push_log(
                f"  {when_key} コスト 不払い (= {len(hand_idxs)}/{discard_n} 選択) → 効果 skip"
            )
            return
        for i in hand_idxs[:discard_n]:
            owner.trash.append(owner.hand.pop(i))
        state.push_log(f"  {when_key} コスト: 手札 {discard_n} 枚 捨て (人間 選択)")
        if state.effects_overlay:
            trigger_on_self_hand_discarded(
                state, owner, opp_for_pay, None, discard_n, state.effects_overlay
            )
        # discard_hand / discard_hand_with_filter は ここで 人間選択分を 捨て済 → 残コストから除外
        # (= 除外しないと _pay_counter_cost で二重に捨てる。 2026-06-04 修正)。
        remaining_cost = {k: v for k, v in cost.items()
                          if k not in ("discard_hand", "discard_hand_with_filter")}
        if remaining_cost:
            _pay_counter_cost(state, owner, opp_for_pay, None, remaining_cost)
        if eff_idx >= 0:
            enqueue_event(
                state,
                when=when_key,
                owner_idx=owner_idx,
                source_card_id=card_id,
                source_iid=source_iid,
                payload={"effect_indexes": [eff_idx]},
            )
            prev_forced = getattr(state, "forced_human_actor_idx", None)
            state.forced_human_actor_idx = owner_idx if owner_idx == state.human_player_idx else -1
            try:
                _maybe_resolve(state)
            finally:
                state.forced_human_actor_idx = prev_forced
        return

    if kind == "on_attack_optional":
        # picks[0] = 1 → 使う、 0 → skip
        use_eff = bool(picks and picks[0] == 1)
        eff_idx = int(choice.get("effect_idx", -1))
        attacker_iid = choice.get("_attacker_iid")
        pay_don = int(choice.get("pay_don", 0))
        state.pending_choice = None
        if not use_eff or eff_idx < 0:
            state.push_log(f"  on_attack 効果 不使用 (skip)")
            # skip した effect は このバトル中 再提示しない (= 無限ループ防止)。
            # ヴェルゴ OP14-061 等 cost 繰り返し型 (once_per_turn 無し) で、 skip しても
            # _maybe_fire_on_attack_optional が再提示して抜けられない bug の修正。
            # _reset_battle_buffs (game.py) で バトル終了時に クリア。
            for ip in [*me.characters, me.leader, *me.stages]:
                if ip.instance_id == attacker_iid:
                    skipped = set(getattr(ip, "_on_attack_opt_skipped", ()))
                    skipped.add(eff_idx)
                    ip._on_attack_opt_skipped = skipped
                    break
            return
        attacker = None
        for ip in [*me.characters, me.leader, *me.stages]:
            if ip.instance_id == attacker_iid:
                attacker = ip
                break
        if attacker is None:
            return
        # 支払い + enqueue
        bundle = state.effects_overlay.get(attacker.card.card_id) if state.effects_overlay else None
        if bundle is None:
            return
        eff = bundle.effects[eff_idx] if 0 <= eff_idx < len(bundle.effects) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        # 全 cost キーを _pay_counter_cost に委譲 (= 旧実装は pay_don のみ inline で、
        #   discard_hand/rest_self_don を踏み倒していた。 2026-06-04 修正)。
        me_idx = state.players.index(me)
        real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
        if real_cost:
            _pay_counter_cost(state, me, state.players[1 - me_idx], attacker, real_cost)
        if cost.get("once_per_turn"):
            attacker.mark_attack_once_used(eff_idx)
        # 【アタック時】 効果は 1 アタックにつき 1 回 (= トリガーは攻撃ごとに 1 度 fire)。
        # once_per_turn の無い cost 繰り返し型 (ヴェルゴ OP14-061 ドン-1 で -2000 等) でも、
        # 発動後は このバトル中 再提示しない (= 多重発動 bug の修正: redirect 再解決 や
        # use 後の再 enqueue で同一攻撃中に -2000 が複数回乗り、 2026-06-08 claude_play で
        # ドフラ/カタクリ が過剰に弱体化した)。 _on_attack_opt_skipped は _reset_battle_buffs で クリア。
        _skipped = set(getattr(attacker, "_on_attack_opt_skipped", ()))
        _skipped.add(eff_idx)
        attacker._on_attack_opt_skipped = _skipped
        enqueue_event(
            state,
            when="on_attack",
            owner_idx=me_idx,
            source_card_id=attacker.card.card_id,
            source_iid=attacker.instance_id,
            payload={"effect_indexes": [eff_idx]},
        )
        # forced_human_actor で user pick 維持
        prev_forced = getattr(state, "forced_human_actor_idx", None)
        state.forced_human_actor_idx = me_idx
        try:
            _maybe_resolve(state)
        finally:
            state.forced_human_actor_idx = prev_forced
        return

    if kind == "option_pick":
        # picks[0] が -1 なら skip (= optional 効果 不発)、 それ以外は options の idx
        full_options = choice.get("_full_options", []) or []
        self_inplay_iid = choice.get("_self_inplay_iid")
        self_inplay = None
        if self_inplay_iid is not None:
            for ip in [*me.characters, me.leader, *me.stages,
                       *opp.characters, opp.leader, *opp.stages]:
                if ip.instance_id == self_inplay_iid:
                    self_inplay = ip
                    break
        state.pending_choice = None
        if not picks:
            return
        chosen_idx = picks[0]
        if chosen_idx < 0 or chosen_idx >= len(full_options):
            # skip (= optional 効果 を 発動 しない)
            state.push_log(f"  効果: choice_effect 不発 (= user skip)")
            return
        chosen_opt = full_options[chosen_idx]
        chosen_do = chosen_opt.get("do", []) if isinstance(chosen_opt, dict) else []
        state.push_log(
            f"  効果: 人間選択 → choice_effect option {chosen_idx} ({chosen_opt.get('label','?')})"
        )
        # option の do-list は run_do_array で実行する。 途中の primitive が human modal で
        # pause した場合、 run_do_array は残りを _continuation に退避 → 解決後に継続実行する。
        # 旧 手動ループは pause 時に残りを捨てており、 OP15-054 誰にも渡さねェ の
        # 「draw 2 → discard 1 (human pick で pause) → コスト4以下登場」 で 最後の「登場」が
        # 脱落していた (= 2026-06-09 赤青ルーシー campaign で発覚)。
        run_do_array(chosen_do, state, me, opp, self_inplay)
        return

    if kind == "scry_life_reorder":
        # picks: 元 idx の 並び 替え 順 (例: [2,0,1,3,4])
        depth = int(choice.get("depth", 1))
        owner = choice.get("owner", "self")
        target_pl = me if owner == "self" else opp
        if not target_pl.life:
            state.pending_choice = None
            return
        actual_depth = min(depth, len(target_pl.life))
        seen = target_pl.life[:actual_depth]
        rest = target_pl.life[actual_depth:]
        # picks 妥当性: 0..actual_depth-1 を 順序 列挙
        valid = [i for i in picks if 0 <= i < actual_depth]
        # 重複 除去 (= 最初 のみ 保持)
        seen_set = set()
        ordered = []
        for i in valid:
            if i not in seen_set:
                ordered.append(i)
                seen_set.add(i)
        # 不足 は 元 順序 で 補完
        for i in range(actual_depth):
            if i not in seen_set:
                ordered.append(i)
        new_seen = [seen[i] for i in ordered]
        target_pl.life = new_seen + rest
        # scry_all_life_one_to_deck: 並べ替えた1枚目をデッキへ(top/bottom)、 残りをライフに。
        one_to_deck = choice.get("one_to_deck")
        if one_to_deck and target_pl.life:
            top = target_pl.life.pop(0)
            if one_to_deck == "bottom":
                target_pl.deck.append(top)
            else:
                target_pl.deck.insert(0, top)
            state.push_log(f"  効果: 人間選択 → {top.name} をデッキの{'下' if one_to_deck=='bottom' else '上'}へ")
        state.push_log(
            f"  効果: 人間選択 → 自ライフ 並び替え {ordered}"
        )
        state.pending_choice = None
        return

    if kind == "scry_deck_reorder":
        # picks 構造: [...idx_order..., position] (= depth+1 の長さ、 最後 が 0=top / 1=bottom)
        # 簡略: 最後 の 1 要素 を position と 解釈、 残り を 並び 順 idx と 解釈。
        # AI / 簡略 では position 省略 (= 上)
        depth = int(choice.get("depth", 1))
        if not me.deck:
            state.pending_choice = None
            return
        actual_depth = min(depth, len(me.deck))
        seen = me.deck[:actual_depth]
        rest = me.deck[actual_depth:]
        # 最後 の picks 要素 を 位置 と 解釈 (= 0/1)。 picks に depth+1 要素 ない なら 上 default。
        if len(picks) == actual_depth + 1:
            position = picks[-1]
            order_picks = picks[:-1]
        else:
            position = 0  # 上 default
            order_picks = picks
        valid = [i for i in order_picks if 0 <= i < actual_depth]
        seen_set = set()
        ordered = []
        for i in valid:
            if i not in seen_set:
                ordered.append(i)
                seen_set.add(i)
        for i in range(actual_depth):
            if i not in seen_set:
                ordered.append(i)
        new_seen = [seen[i] for i in ordered]
        if position == 1:
            # 下 配置 (= 並び順 維持 で デッキ 底 に。 先頭 が 一番 上 に なる ので reverse 風)
            me.deck = rest + new_seen
        else:
            me.deck = new_seen + rest
        pos_label = "下" if position == 1 else "上"
        state.push_log(
            f"  効果: 人間選択 → 自デッキ上{actual_depth}枚 並び替え + {pos_label} 配置"
        )
        state.pending_choice = None
        return

    if kind == "view_life_top_choose_position":
        # picks 構造: [owner_pick, position]
        #   owner_pick: 0=self、 1=opp (= 「自分か相手」 owner=either の 場合)
        #   position: 0=top 元に戻す、 1=bottom 底へ
        # owner="self" / "opp" 固定 の 場合 owner_pick 不要 → picks=[position]
        owner = choice.get("owner", "self")
        depth = int(choice.get("depth", 1))
        if owner == "either":
            owner_pick = picks[0] if picks else 0
            position = picks[1] if len(picks) >= 2 else 0
            target_pl = me if owner_pick == 0 else opp
        else:
            position = picks[0] if picks else 0
            target_pl = me if owner == "self" else opp
        if not target_pl.life:
            state.pending_choice = None
            return
        d = min(depth, len(target_pl.life))
        seen = target_pl.life[:d]
        rest = target_pl.life[d:]
        if position == 1:
            target_pl.life = rest + seen
            pos_label = "下"
        else:
            target_pl.life = seen + rest
            pos_label = "上"
        owner_label = "自" if target_pl is me else "相手"
        state.push_log(
            f"  効果: 人間選択 → {owner_label}ライフ上{d}枚 {pos_label} 配置"
        )
        state.pending_choice = None
        return

    if kind == "reveal_top_play_confirm":
        # picks[0] が 1 なら 登場、 0 なら skip (= デッキ底/トップへ)
        revealed = choice.get("_revealed_card")
        rested_flag = bool(choice.get("rested", False))
        rest_remain = choice.get("rest_remain", "bottom")
        do_play = bool(picks and picks[0] == 1)
        state.pending_choice = None
        if revealed is None:
            return
        if do_play:
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
            ip = InPlay.of(revealed, rested=rested_flag, sickness=True)
            me.characters.append(ip)
            state.push_log(f"  効果: 人間選択 → 登場 {revealed.name}")
            if state.effects_overlay:
                trigger_on_play(state, me, opp, ip, state.effects_overlay)
        else:
            if rest_remain == "top":
                me.deck.insert(0, revealed)
            else:
                me.deck.append(revealed)
            state.push_log(
                f"  効果: 人間選択 → {revealed.name} を デッキ{('上' if rest_remain == 'top' else '底')}へ"
            )
        return

    if kind == "activate_main_discard_pick":
        # picks: 人 間 が 選 ん だ hand index list (= 通 常 1 個、 limit 個 ま で)。
        # 2026-05-30 追加 (= イム OP13-079 起動 メイン bug 修 復)。 fire_activate_main に
        # cost_picks={"discard_idxs": [...]} 付 き で 再 呼 出 し て random discard を 上 書 き。
        candidates = choice.get("candidates", [])
        source_iid = choice.get("source_iid")
        effect_index = choice.get("effect_index")
        limit = int(choice.get("limit", 1))
        prior_picks = dict(choice.get("prior_picks") or {})
        valid_picks = [i for i in picks if 0 <= i < len(candidates)][:limit]
        if not valid_picks:
            state.pending_choice = None
            state.push_log("  起動メインコスト: 手札 捨て 選択 なし → 中止")
            return
        # picks (= candidates index) → hand_idx へ
        discard_idxs = [int(candidates[i]["hand_idx"]) for i in valid_picks]
        prior_picks["discard_idxs"] = discard_idxs
        # source inplay 復元
        inplay = None
        for ip in [*me.characters, me.leader, *me.stages]:
            if ip.instance_id == source_iid:
                inplay = ip
                break
        # trash_self/self_ko を cost に含む起動メイン (= EB03-062 等 7 枚) では、 初回 pass で
        # 既に source が場を離れトラッシュに移っている → source_iid で場を引けない。 その場合は
        # トラッシュの CardDef から ghost InPlay を再構成し、 discard cost 適用 + do 継続する。
        # これを怠ると discard も do も丸ごと unfire し、 自身 trash だけ済んで効果ゼロになる
        # (= 2026-06-11 corazon mirror campaign 中に発見、 人間 discard pick の resume bug)。
        if inplay is None:
            scid = choice.get("source_card_id")
            if scid:
                ghost_card = next(
                    (c for c in reversed(me.trash)
                     if getattr(c, "card_id", None) == scid),
                    None,
                )
                if ghost_card is not None:
                    inplay = InPlay.of(ghost_card)
                    inplay.instance_id = source_iid
        if inplay is None or effect_index is None:
            state.pending_choice = None
            return
        bundle = state.effects_overlay.get(inplay.card.card_id) if state.effects_overlay else None
        if bundle is None or effect_index >= len(bundle.effects):
            state.pending_choice = None
            return
        eff = bundle.effects[effect_index]
        state.pending_choice = None
        fire_activate_main(state, me, opp, inplay, eff, cost_picks=prior_picks)
        return

    if kind == "activate_main_cost_pick":
        # picks: candidates[] の index list (= 通常 1 個)。 空 = skip 不可 (= cost 必須)。
        candidates = choice.get("candidates", [])
        cost_kind = choice.get("cost_kind", "")
        source_iid = choice.get("source_iid")
        effect_index = choice.get("effect_index")
        prior_picks = dict(choice.get("prior_picks") or {})
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        if not valid_picks:
            # 0 件 選択 (= 人間 が skip 試みた): cost 払い 不能 で activate_main 全体 中止
            state.pending_choice = None
            state.push_log(f"  起動メインコスト: {cost_kind} 選択 なし → 中止")
            return
        picked_cand = candidates[valid_picks[0]]
        # cost_picks に inject (= prior に 重ねる)
        if cost_kind == "ko_self_with_filter":
            prior_picks["ko_iid"] = int(picked_cand["iid"])
        elif cost_kind == "rest_self_target_name":
            prior_picks["rest_iid"] = int(picked_cand["iid"])
        elif cost_kind == "rest_own_card":
            prior_picks["rest_own_iids"] = [int(candidates[i]["iid"]) for i in valid_picks]
        elif cost_kind == "trash_filtered_chara":
            # OP13-079 イム leader の choice cost (= 「天竜人キャラ か 手札1枚」 統合 modal)。
            # 候補は キャラ axis と 手札 axis が 混在しうる。 axis フィールドで 振り分ける
            # (= 手札候補は 擬似 iid 負値 + hand_idx 持ち、 キャラ候補は 実 iid)。
            if picked_cand.get("axis") == "hand":
                prior_picks["discard_idxs"] = [int(picked_cand["hand_idx"])]
            else:
                prior_picks["choice_cost_chara_iid"] = int(picked_cand["iid"])
        # source inplay 復元
        inplay = None
        for ip in [*me.characters, me.leader, *me.stages]:
            if ip.instance_id == source_iid:
                inplay = ip
                break
        if inplay is None or effect_index is None:
            state.pending_choice = None
            return
        bundle = state.effects_overlay.get(inplay.card.card_id) if state.effects_overlay else None
        if bundle is None or effect_index >= len(bundle.effects):
            state.pending_choice = None
            return
        eff = bundle.effects[effect_index]
        state.pending_choice = None
        # cost_picks 付き で fire_activate_main 再呼出 (= header 二重 push しない、 cost 適用 再開)
        fire_activate_main(state, me, opp, inplay, eff, cost_picks=prior_picks)
        return

    if kind != "search_top_n":
        # 未知 kind は クリア のみ
        state.pending_choice = None
        return
    depth = int(choice.get("depth", 5))
    destination = choice.get("destination", "hand")
    rest_remain = choice.get("rest_remain", "bottom")
    rested_flag = bool(choice.get("rested", False))
    limit = int(choice.get("limit", 1))
    filt = choice.get("filter", {}) or {}
    seen = me.deck[:depth]
    me.deck = me.deck[depth:]
    # ⚠ 公式: 手札に加えられるのは filter に合致するカードのみ (= 「コストN以上の特徴Xを
    #   1枚まで」)。 範囲内 idx でも _matches_filter を満たさなければ無効 (= 人間が非該当
    #   カードを掴むのを防ぐ)。 AI/auto 経路 (上の search_top_n primitive) は元から filter を
    #   チェック済で、 人間経路だけ未チェックだった不整合を解消。 重複 idx も除去 + limit cap。
    #   2026-06-11 (bonney mirror campaign 中に発見: 戦桃丸=エッグヘッド/海軍 を 麦わら/アラ
    #   バスタ サーチで手札に加えられた)。
    valid_picks: list[int] = []
    seen_i: set[int] = set()
    for i in picks:
        if len(valid_picks) >= limit:
            break
        if 0 <= i < len(seen) and i not in seen_i and _matches_filter(seen[i], filt):
            seen_i.add(i)
            valid_picks.append(i)
    picked = [seen[i] for i in valid_picks]
    remaining = [c for i, c in enumerate(seen) if i not in seen_i]
    for c in picked:
        if destination == "play":
            if c.category != Category.CHARACTER:
                me.hand.append(c)
                continue
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state, owner_idx=state.players.index(me))
            ip = InPlay.of(c, rested=rested_flag, sickness=True)
            me.characters.append(ip)
            state.push_log(f"  効果: 人間選択 → 登場 {c.name}")
            if state.effects_overlay:
                trigger_on_play(state, me, state.opponent, ip, state.effects_overlay)
        elif destination == "life":
            # 「ライフの上に加える」 (= OP16-119 ティーチ)。 裏向き (life 既定)。
            me.life.insert(0, c)
            state.push_log(f"  効果: 人間選択 → ライフ上に加える ({len(me.life)} 枚)")
        elif destination == "trash":
            # 「〜枚をトラッシュに置く」 (= OP03-083 コルギー等)。 picked を直接 trash へ。
            me.trash.append(c)
            state.push_log(f"  効果: 人間選択 → トラッシュ")
        else:  # hand
            me.hand.append(c)
            # 隠 ぺい 情 報 保 護 (= card name は 自 player のみ 知 る)
            state.push_log(f"  効果: 人間選択 → 手札")
    # 残 り 処 理: trash は 一 括 / bottom は 人 間 + 2 枚 以 上 で reorder modal
    if rest_remain == "trash":
        me.trash.extend(remaining)
        state.push_log(
            f"  効果: search_top_n 残り{len(remaining)}枚 → トラッシュ"
        )
        state.pending_choice = None
        return
    # bottom 戻し: 人 間 + 2 枚 以上 残 れば reorder modal halt、 1 枚 以下 なら 即 deck 底
    if remaining and len(remaining) >= 2 and _should_human_pick(state):
        state.pending_choice = {
            "kind": "search_top_n_bottom_reorder",
            "candidates": [
                {
                    "card_id": c.card_id,
                    "name": c.name,
                    "cost": int(getattr(c, "cost", 0) or 0),
                    "power": int(getattr(c, "power", 0) or 0),
                    "counter": int(getattr(c, "counter", 0) or 0),
                    "trigger": bool(getattr(c, "trigger", None)),
                }
                for c in remaining
            ],
            # 元 cards を 順 序 で 引 け る よ う card_id list で 保 持
            "_card_ids_in_order": [c.card_id for c in remaining],
            # remaining 自 体 を 直 接 持 つ (= reorder で 該当 idx 順 に deck.extend)
        }
        # remaining は state に も 退 避 (= JSON 化 不可 な ら 別 storage)
        state.search_top_n_pending_remaining = remaining
        state.push_log(
            f"  効果: search_top_n 残り{len(remaining)}枚 → デッキ底 戻 す 順 を 人 間 選 択 待 ち"
        )
        return
    # AI / 1 枚 以 下: 即 deck 底 (= 旧 動 作 維 持、 AI は 並 び 順 へ の こ だ わ り 少)
    me.deck.extend(remaining)
    state.pending_choice = None


def _resolve_dynamic_filter(
    filt: dict[str, Any],
    state: GameState,
    me: Player,
    opp: Player,
) -> dict[str, Any]:
    """filter dict の 動的 fields (= 値が ゲーム状態 に 依存) を 静的 値 に 解決。

    対応 key (= 公式テキスト で 動的 cost cap 等 を 表現する 効果 用):
    - `cost_le_dynamic`: "sum_both_life_count" → cost_le = len(me.life) + len(opp.life)
      (= ST29-013 ロブ・ルッチ: 「お互いのライフの合計枚数以下のコスト」)
    - 将来 他 source (= "self_don_active" 等) を 追加可能。 unknown source は no-op。

    呼び元 で 解決後 の filter を _matches_filter に 渡すと 静的 cost_le として 動く。
    元 filt は 変更しない (= shallow copy で 返却)。
    """
    if not isinstance(filt, dict) or not filt:
        return filt
    if ("cost_le_dynamic" not in filt and "or" not in filt
            and "name_in_last_discarded" not in filt):
        return filt
    out = dict(filt)
    if out.pop("name_in_last_discarded", None):
        # EB02-039: 「捨てたカードと同名」 = 直前に cost で捨てたカード名 で絞る。
        out["name_in"] = list(getattr(state, "last_discarded_names", []) or [])
    src = out.pop("cost_le_dynamic", None)
    if src == "sum_both_life_count":
        out["cost_le"] = len(me.life) + len(opp.life)
    elif src == "self_don_total":
        # OP13-099 虚の玉座 等。 公式: 「自分の場のドン!!の枚数以下のコストを持つ ~ カードカード」
        # = active + rested + attached (= 場 上 の 自陣 ドン 全 体)。 attached は
        # 各 InPlay の attached_dons の 合計 で 算出。
        attached_total = sum(
            getattr(ip, "attached_dons", 0)
            for ip in [me.leader, *me.characters, *me.stages]
            if ip is not None
        )
        out["cost_le"] = me.don_active + me.don_rested + attached_total
    elif src == "self_don_active":
        # 「自分のアクティブのドン!!の枚数以下のコスト」 想定 (= 派生)
        out["cost_le"] = me.don_active
    elif src == "opp_life_count":
        # OP05-102 ゲダツ: 「相手のライフの枚数以下のコストを持つ相手のキャラ」
        out["cost_le"] = len(opp.life)
    elif src == "self_life_count":
        # OP08-102 シャーロット・オペラ: 「自分のライフの枚数以下のコストを持つ相手のキャラ」
        out["cost_le"] = len(me.life)
    elif src is not None:
        # 未知 source は 防御的 に 大値 (= 制限 ない と 同義) で 通す
        out["cost_le"] = 99
    if "or" in out and isinstance(out["or"], list):
        out["or"] = [_resolve_dynamic_filter(sub, state, me, opp) for sub in out["or"]]
    return out


def _card_has_no_effect(card: CardDef, state: GameState) -> bool:
    """「元々の効果のないキャラ」 判定 = overlay に効果 entry が無い (= [] or 未登録)。
    one_self_chara_no_effect target と同一基準 (= バニラ)。 filter no_effect:true 用。"""
    overlay_map = state.effects_overlay or {}
    bundle = overlay_map.get(card.card_id)
    return bundle is None or len(getattr(bundle, "effects", [])) == 0


def _no_play_from_hand_via_effect(card: CardDef, overlay) -> bool:
    """「手札のこのカードは効果で登場できない」 (OP12-036 ゾロ)。 overlay の
    `_no_play_via_effect: true` marker で判定 → play_from_hand 系が候補から除外する。"""
    if not overlay:
        return False
    bundle = overlay.get(card.card_id)
    if bundle is None:
        return False
    return any(isinstance(e, dict) and e.get("_no_play_via_effect")
               for e in getattr(bundle, "effects", []))


_ALT_NAMES_CACHE: dict[str, list[str]] | None = None


def _alt_names_map() -> dict[str, list[str]]:
    """`db/card_alt_names.json` (= 「ルール上、このカードはカード名を「X」としても扱う」) を読む。

    公式ルール: 該当カードは **自身の名前に加えて** 別名でも参照される (OP03-122_r1 そげキング =
    「ウソップ」 / EB04-038 = 「トラファルガー・ロー」+「ドンキホーテ・ロシナンテ」 等 16 枚)。
    名前一致の filter / target spec / サーチ がこれを見ないと該当カードを取りこぼす。
    ⚠ 「カード名の異なるキャラ」 の **種類数え** では別名を数えない (公式 Q&A、 EB04-038 は 1 種類)。
    """
    global _ALT_NAMES_CACHE
    if _ALT_NAMES_CACHE is None:
        import json as _json
        from pathlib import Path as _Path

        try:
            _p = _Path(__file__).resolve().parents[1] / "db" / "card_alt_names.json"
            _ALT_NAMES_CACHE = dict(
                _json.loads(_p.read_text(encoding="utf-8")).get("alt_names") or {}
            )
        except Exception:
            _ALT_NAMES_CACHE = {}
    return _ALT_NAMES_CACHE


def card_names(card: CardDef) -> list[str]:
    """このカードが「そのカード名として扱われる」名前すべて (本来の名前 + 別名)。"""
    alt = _alt_names_map().get(getattr(card, "card_id", ""), [])
    return [card.name, *alt] if alt else [card.name]


_NORM_NAME_CACHE: dict[str, str] = {}


def _norm_name(s: str) -> str:
    """normalize_card_name のメモ化。 名前一致は AI 探索の最内周で数百万回呼ばれる。"""
    v = _NORM_NAME_CACHE.get(s)
    if v is None:
        v = normalize_card_name(s)
        _NORM_NAME_CACHE[s] = v
    return v


def name_matches(card: CardDef, target: str) -> bool:
    """カード名一致 (別名ルール込み、 表記ゆれは normalize_card_name で吸収)。

    ⚠ **ホットパス** (`_matches_filter` / target 解決 → AI 探索の最内周)。 素朴に card_names()
    のリストを作って毎回 normalize すると 20x 遅くなり、 テスト全体が分単位で悪化する
    (2026-08-03 実測)。 完全一致の高速パス + 正規化メモ化で回避する。
    """
    name = card.name
    if name == target:  # 最頻ケース: そのまま一致
        return True
    t = _norm_name(target)
    if _norm_name(name) == t:  # 表記ゆれ (全角Ｄ 等)
        return True
    alt = _alt_names_map().get(card.card_id)
    if not alt:
        return False
    for a in alt:
        if _norm_name(a) == t:
            return True
    return False


def _matches_filter_ip(ip: Any, filt: dict[str, Any]) -> bool:
    """**場に出ている InPlay** に対する filter 判定 (= コストは公式どおり現在値で見る)。

    ⭐ 公式は 素の 「コスト/パワー」 と 「**元々の**コスト/パワー」 を書き分ける。
      - コスト (ルール 1-3-6-2 + cardqa_op_02): 素の 「コストN以下」 = **効果修正後の現在コスト**
      - パワー (cardqa): 「元々のパワーが6000以下のキャラが効果で7000以上となっている場合、
        この【メイン】効果でKOできますか？」 → 「**いいえ**。 現在のパワーが6000以下のキャラを
        KOできます」 = 素の 「パワーN以下」 も **現在パワー** (ドン付与/バフ込み)
      `_matches_filter` は `CardDef` しか受け取らないので **印刷値固定** で、 場のキャラに
      対して使うと 「コスト/パワーを動かしてから除去する」 実在ラインが機能しない。

    ここで plain な `cost_le/ge/eq` / `cost` を `InPlay.base_cost` (= cost_minus 反映)、
    `power_le/ge/eq` を `InPlay.power` (= ドン付与/バフ込み) で判定し、
    残りは従来どおり `_matches_filter(ip.card, ...)` に委譲する。
    「元々の〜」 は `truly_original_{cost,power}_*` (印刷値) なので委譲側でそのまま正しい。

    ⚠ 手札/デッキ/トラッシュのカードには使わない (= そこでは修正が乗らず印刷値=現在値)。
    """
    if not filt:
        return True
    # OR 結合 (or / or_clauses) の各サブ filter も **InPlay = 現在値** で判定する。
    # ⚠ ここを CardDef 版 (`_matches_filter`) に丸投げすると、 OR の中に入れ子になった
    #   cost/power だけ印刷値で判定され、 素の 「コストN」 裁定が 「OR の外なら現在値・
    #   中なら印刷値」 と経路依存で食い違う (= 一部だけ実装、 最も見つけにくい形)。
    #   実例: P-084 バギー 「コスト3と4のキャラすべてはアタックできない」 の overlay は
    #   `{"or_clauses": [{"cost_eq": 3}, {"cost_eq": 4}]}`。 公式 (cardqa) は
    #   「元々のコスト3か4で、 他の効果で現在のコストが2以下や5以上になっているキャラは
    #    アタックできますか？」→ 「はい。 現在のコストが3か4であるキャラのアタックが
    #    宣言できなくなる効果です」 = **現在コスト** 判定。 印刷値で見ると違反する。
    #   Python/Rust とも同じ overlay を読むので差分検証では原理的に沈黙するクラス。
    if "or" in filt or "or_clauses" in filt:
        for or_key in ("or", "or_clauses"):
            subs = filt.get(or_key)
            if subs is not None and not any(_matches_filter_ip(ip, sub) for sub in subs):
                return False
        rest_or = {k: v for k, v in filt.items() if k not in ("or", "or_clauses")}
        if not rest_or:
            return True
        return _matches_filter_ip(ip, rest_or)
    plain = ("cost_le", "cost_ge", "cost_eq", "cost",
             "power_le", "power_ge", "power_eq")
    if not any(k in filt for k in plain):
        return _matches_filter(ip.card, filt)
    cur, pw = ip.base_cost, ip.power
    if "cost_le" in filt and cur > int(filt["cost_le"]):
        return False
    if "cost_ge" in filt and cur < int(filt["cost_ge"]):
        return False
    if "cost_eq" in filt and cur != int(filt["cost_eq"]):
        return False
    if "cost" in filt and cur != int(filt["cost"]):
        return False
    if "power_le" in filt and pw > int(filt["power_le"]):
        return False
    if "power_ge" in filt and pw < int(filt["power_ge"]):
        return False
    if "power_eq" in filt and pw != int(filt["power_eq"]):
        return False
    rest = {k: v for k, v in filt.items() if k not in plain}
    return _matches_filter(ip.card, rest)


def _matches_filter_hand(
    card: CardDef, filt: dict[str, Any], in_hand_cost_minus: int
) -> bool:
    """**手札のカード** に対する filter 判定。 素の 「コストN以下/以上/ぴったり」 は
    手札での **現在コスト** (= 印刷コスト − in_hand_cost_minus) で判定する。

    公式 (cardqa_st_23, ST23-001 ウタ 「手札のこのカードは、 自分のパワー10000以上の
    キャラがいる場合、 コスト-4」): 「自分のパワー10000以上のキャラがいるときに、 この
    キャラをコスト2として、 『OP01-047 ロー』 の効果 (= 手札からコスト3以下のキャラを登場)
    で登場させることはできますか？」 → **「はい、 できます」**。
    = 「コストN以下」 の登場 filter は 手札での現在コスト (= 印字コストに手札コスト修正を
    反映した値) で判定する。 `_matches_filter` (= 印字コスト固定) だと ウタ (印字6) は
    cost_le:3 で弾かれ 公式違反になる。

    `_matches_filter_ip` (= 盤面 InPlay の現在コスト判定) の手札版。 「元々のコスト」 =
    `truly_original_cost_*` は 印字コスト固定なので 委譲側 (`_matches_filter`) でそのまま正しい。
    in_hand_cost_minus<=0 (= 手札コスト修正を持たない大多数のカード) では `_matches_filter`
    と完全一致 = 挙動不変。
    """
    if in_hand_cost_minus <= 0 or not filt:
        return _matches_filter(card, filt)
    eff = max(0, card.cost - in_hand_cost_minus)
    # OR 節も現在コストで判定 (経路依存を避ける、 _matches_filter_ip と同型)
    if "or" in filt or "or_clauses" in filt:
        for or_key in ("or", "or_clauses"):
            subs = filt.get(or_key)
            if subs is not None and not any(
                _matches_filter_hand(card, sub, in_hand_cost_minus) for sub in subs
            ):
                return False
        rest_or = {k: v for k, v in filt.items() if k not in ("or", "or_clauses")}
        if not rest_or:
            return True
        return _matches_filter_hand(card, rest_or, in_hand_cost_minus)
    plain = ("cost_le", "cost_ge", "cost_eq", "cost")
    if not any(k in filt for k in plain):
        return _matches_filter(card, filt)
    if "cost_le" in filt and eff > int(filt["cost_le"]):
        return False
    if "cost_ge" in filt and eff < int(filt["cost_ge"]):
        return False
    if "cost_eq" in filt and eff != int(filt["cost_eq"]):
        return False
    if "cost" in filt and eff != int(filt["cost"]):
        return False
    rest = {k: v for k, v in filt.items() if k not in plain}
    return _matches_filter(card, rest)


def _matches_filter(card: CardDef, filt: dict[str, Any]) -> bool:
    if not filt:
        return True
    # OR 結合: filt["or"] = [sub_filter_1, sub_filter_2, ...]
    # いずれかに マッチ すれば 全体 True (= 短絡)
    if "or" in filt:
        subs = filt["or"]
        if not any(_matches_filter(card, sub) for sub in subs):
            return False
    # category は大文字 ("CHARACTER"/"EVENT"/"STAGE"/"LEADER") が正規。 overlay 側で小文字
    # ("character") を書くと従来は silent no-op (= 全不マッチ) で効果不発になっていた。
    # 大小無視で比較し、 誤記による不発を防ぐ (= 値は4種で大小違いの誤マッチは起きない)。
    if "category" in filt and card.category.value != str(filt["category"]).upper():
        return False
    if "category_in" in filt:
        cats = filt["category_in"]
        if isinstance(cats, str):
            cats = [cats]
        if card.category.value not in [str(c).upper() for c in cats]:
            return False
    if "cost_le" in filt and card.cost > int(filt["cost_le"]):
        return False
    if "cost_ge" in filt and card.cost < int(filt["cost_ge"]):
        return False
    if "cost_eq" in filt and card.cost != int(filt["cost_eq"]):
        return False
    # 厳密 "cost": N (= cost_eq エイリアス、 公式「コストN の…」)。 これを未処理だと
    # コスト制限が silently 無視され **任意コストにマッチ** する (= OP14-084「cost1 のB・W登場」
    # が cost7 も登場可能、 P-081/OP13-098/OP14-088 等。 2026-06-05 lockstep diff が検出)。
    if "cost" in filt and card.cost != int(filt["cost"]):
        return False
    # original_cost_eq: 元々(印刷)コスト = N。 CardDef.cost = 印刷値なので cost_eq と同義の
    # エイリアス。 未処理で silently 無視されていた (= 2026-06-05 filter キー監査で検出)。
    if "original_cost_eq" in filt and card.cost != int(filt["original_cost_eq"]):
        return False
    # ⭐ truly_original_cost_le/ge/eq = 公式 「**元々の**コストN以下/以上」 (2026-08-04 追加)。
    #   公式は 「コスト」 (= 効果修正後の現在値) と 「元々のコスト」 (= 印刷値) を明確に区別する:
    #     - cardqa_eb_03「元々のコストが4以上で、他の効果によって現在のコストが3以下になっている
    #       キャラを (元々のコスト3以下として) デッキの下に置けますか？」→「いいえ、できません」
    #     - cardqa_op_02「本来のコストが8以上のキャラが、他の効果で7コスト以下になった場合、
    #       (コスト7以下として) コスト-1することができますか？」→「はい、できます」
    #   CardDef は印刷値しか持たないので、 このキーは常に card.cost で判定する (= 正しい)。
    if "truly_original_cost_le" in filt and card.cost > int(filt["truly_original_cost_le"]):
        return False
    if "truly_original_cost_ge" in filt and card.cost < int(filt["truly_original_cost_ge"]):
        return False
    if "truly_original_cost_eq" in filt and card.cost != int(filt["truly_original_cost_eq"]):
        return False
    if "power_le" in filt and card.power > int(filt["power_le"]):
        return False
    if "power_ge" in filt and card.power < int(filt["power_ge"]):
        return False
    if "power_eq" in filt and card.power != int(filt["power_eq"]):
        return False
    # 「元々のパワー N 以下/以上/ぴったり」 (公式 4-9): _matches_filter は CardDef を
    # 受けるため card.power = 印刷値 = 元々のパワー。 power_le 等と同義だが、 overlay 側で
    # 公式テキスト 「元々のパワー」 を明示するための エイリアス (= 現在値 current_power_* と区別)。
    if "truly_original_power_le" in filt and card.power > int(filt["truly_original_power_le"]):
        return False
    if "truly_original_power_ge" in filt and card.power < int(filt["truly_original_power_ge"]):
        return False
    if "truly_original_power_eq" in filt and card.power != int(filt["truly_original_power_eq"]):
        return False
    if "feature" in filt and filt["feature"] not in card.features:
        return False
    if "feature_contains" in filt:
        # 部分一致: card.features の中に文字列 v を含む特徴があるか (= 公式『X』を含む特徴)
        if not any(filt["feature_contains"] in f for f in card.features):
            return False
    if "feature_in" in filt:
        # 特徴 OR (例: 「特徴《魚人族》か《人魚族》」)。
        feats = filt["feature_in"]
        if isinstance(feats, str):
            feats = [feats]
        if not any(f in card.features for f in feats):
            return False
    if "color" in filt and filt["color"] not in card.color:
        return False
    if "exclude_name" in filt and name_matches(card, filt["exclude_name"]):
        return False
    # name_exclude: exclude_name の variant 表記 (= overlay に両表記が混在)。 未処理だと
    # 名前除外が silently 無視される (= 2026-06-05 filter キー監査で検出)。
    if "name_exclude" in filt and name_matches(card, filt["name_exclude"]):
        return False
    # exclude_card_id: 特定 card_id を除外 (= ST22-002「自身以外の白ひげ海賊団」 等)。 未処理だと
    # 除外が無効で **そのカード自身も対象** になる (= 14 箇所、 2026-06-05 filter キー監査で検出)。
    if "exclude_card_id" in filt and card.card_id == filt["exclude_card_id"]:
        return False
    # card_id: 特定 card_id のみに限定。 未処理だと card_id 制限が無視され任意カードにマッチ。
    if "card_id" in filt and card.card_id != filt["card_id"]:
        return False
    if "has_trigger" in filt and filt["has_trigger"]:
        if not (card.trigger and card.trigger.startswith("【トリガー】")):
            return False
    if "trigger" in filt and isinstance(filt["trigger"], bool) and filt["trigger"]:
        # 公式 「【トリガー】を持つカード」 用 alias。
        # cards.json の trigger フィールドが空でなければ「トリガー持ち」。
        # 通常 trigger 文字列は 「【トリガー】…」 で始まるが、 既存 has_trigger との互換のため
        # 「【トリガー】」 prefix or 非空文字列のいずれでも True 扱い (公式テキスト忠実)。
        if not card.trigger:
            return False
    if "feature_or_name" in filt:
        # feature OR name のいずれかにマッチ
        spec = filt["feature_or_name"]
        feat = spec.get("feature")
        name = spec.get("name")
        if not ((feat and feat in card.features) or (name and name_matches(card, name))):
            return False
    if "name" in filt and not name_matches(card, filt["name"]):
        return False
    if "name_in" in filt:
        names = filt["name_in"]
        if isinstance(names, str):
            names = [names]
        if not any(name_matches(card, _n) for _n in names):
            return False
    if "attribute" in filt and str(filt["attribute"]) not in (card.attribute or ""):
        # 公式「属性(X)を持つカード」 = X が card の属性 (「斬/打」 等 複数可) に含まれれば真。
        # 完全一致 (!=) は 多属性カード (ロー&ベポ「斬/打」/ キッド&キラー「斬/特」 等) を
        # 取りこぼすバグ。 engine 他箇所 (leader_attribute / opp_attacker_attribute) と同じ
        # substring `in` 方式に統一。
        return False
    if "or_clauses" in filt:
        # OR 結合: 各サブ filter のいずれかが True なら通る (= 残りのキーと AND)
        if not any(_matches_filter(card, sub) for sub in filt["or_clauses"]):
            return False
    return True


# --------------------------------------------------------------------------- #
# トリガー発火
# --------------------------------------------------------------------------- #
def trigger_on_play(
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """キャラ登場時のトリガーを enqueue。 resolve は呼び出し元 (apply_action 末尾) で実施。

    on_play 効果が存在しないカードでも enqueue 自体は no-op コスト (= bundle 不在ですぐ return)。
    enqueue 後の auto-resolve はネスト時 (= 既に resolving 中) に no-op になる。

    また、 相手側の場には「相手がキャラを登場させた時」 (on_opp_chara_played) を発火。
    OP04-024 シュガー 等 (公式 7-1-1-7)。
    """
    me_idx = state.players.index(me)
    # payload-aware context: 自分の場の効果 (= OP02-026 サンジ等) が played カードを参照可
    state.last_self_chara_played_card = self_inplay.card
    # 登場した InPlay 自身を指す context (= OP16-079 ヤマト「そのキャラ」 target / トラッシュ起源 gate)。
    state.last_self_chara_played_iid = self_inplay.instance_id
    state.last_self_chara_played_from_trash = bool(getattr(self_inplay, "played_from_trash", False))
    # 自陣営: 登場したカード自身の on_play
    bundle = effects_overlay.get(self_inplay.card.card_id)
    has_self_on_play = bundle is not None and any(e.get("when") == "on_play" for e in bundle.effects)
    # OP09-081 effect: me が play する on_play は opp の flag で 無効化
    if me.opp_on_play_disabled_through_opp_turn:
        state.push_log(f"  on_play 効果 無効 (OP09-081 相手効果): {self_inplay.card.name}")
        has_self_on_play = False
    if has_self_on_play:
        enqueue_event(
            state,
            when="on_play",
            owner_idx=me_idx,
            source_card_id=self_inplay.card.card_id,
            source_iid=self_inplay.instance_id,
        )
    # 自陣営: 「自分のキャラが登場した時」 (= on_self_chara_played) を自分の場の全カードに発火
    if self_inplay.card.category == Category.CHARACTER:
        _enqueue_field_when(state, me, "on_self_chara_played", effects_overlay)
    # 相手陣営: 「相手がキャラを登場させた時」 を相手の場の全カードに対し発火
    # (キャラのみ。 ステージ/イベントは on_opp_chara_played の対象外)
    if self_inplay.card.category == Category.CHARACTER:
        # payload-aware 条件用 context (OP12-081 コアラ用)
        state.last_opp_chara_played_card = self_inplay.card
        _enqueue_field_when(state, opp, "on_opp_chara_played", effects_overlay)
    _maybe_resolve(state)
    state.last_opp_chara_played_card = None


def fire_self_life_to_hand(state: GameState, me: Player) -> None:
    """自己効果で自分のライフが手札に加わった時に on_self_life_to_hand を発火。

    damage 経路 (trigger_on_opp_life_taken の defender 側) と対称。OP08-098 カルガラ
    リーダーの then_life_to_hand / life_to_hand primitive 等、 自分の効果で自ライフを
    手札へ移した時の発火点。 OP05-107 スペーシー中尉 / OP12-099 カルガラ /
    OP11-041 ナミ の『自分のターン中 ライフが (離れて) 手札に加わった時』系トリガーが
    これで発火する (= これらは self-effect 経路では従来 silently dead だった)。
    """
    overlay = getattr(state, "effects_overlay", None)
    if not overlay:
        return
    _enqueue_field_when(state, me, "on_self_life_to_hand", overlay)
    _maybe_resolve(state)


def _fire_opp_life_left_by_effect(
    state: GameState, me: Player, opp: Player, n: int, dest: str
) -> None:
    """**効果で** 相手のライフが離れた時のトリガー発火 (2026-08-05 是正)。

    公式 (`cardqa_op_08`, OP08-105 ボニー): 「相手のライフが相手の効果によって手札やトラッシュに
    移動した時、 この【自分のターン中】効果でカード2枚を引き手札1枚を捨てることはできますか？」
    → **「はい、できます。」**
    = 「相手のライフが離れた時」 は **離れ方を問わない**。 アタックダメージ経路だけに配線して
    いると、 効果によるライフ除去で発火せず公式違反になる。

    ⚠ **ライフカードの【トリガー】は発動しない** (公式 10-1-5 = 効果でのライフ移動)。
      ここで発火するのは **場のキャラ/リーダーの when トリガー** だけ。
    ⚠ `on_self_life_taken` (= 「ダメージを受けた時」) は **戦闘ダメージ専用** なので
      ここでは発火しない (`trigger_on_opp_life_taken` の docstring 参照)。

    dest: "hand" / "trash" / "other" (= デッキ等。 owner 側トリガーは無し)
    """
    if n <= 0 or not state.effects_overlay:
        return
    _enqueue_field_when(state, me, "on_opp_life_taken", state.effects_overlay)
    if dest == "hand":
        _enqueue_field_when(state, opp, "on_self_life_to_hand", state.effects_overlay)
    elif dest == "trash":
        _enqueue_field_when(state, opp, "on_self_life_to_trash", state.effects_overlay)
    _maybe_resolve(state)


def trigger_on_opp_life_taken(
    state: GameState,
    attacker: Player,
    defender: Player,
    went_to_hand: bool,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """ライフ移動時の 2 系トリガーを発火 (公式 10-1-5 直後)。

    - attacker 側: 「相手のライフが離れた時」 (on_opp_life_taken)
    - defender 側: went_to_hand=True なら 「自分のライフが手札に加わった時」 (on_self_life_to_hand)
                    went_to_hand=False なら 「自分のライフがトラッシュに置かれた時」
                    (on_self_life_to_trash) — トリガー発動 or バニッシュで離脱した時
    - defender 側: 「ダメージを受けた時」 (on_self_life_taken) — 戦闘ダメージで
                    ライフが離れた時 (= OP13-002 等)。 自己効果の life_to_hand とは
                    区別し、 戦闘ダメージ経路 でのみ発火する。

    OP08-105 ジュエリー・ボニー (attacker 側) / OP05-107 スペーシー中尉 (defender 側) 等。
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, attacker, "on_opp_life_taken", effects_overlay)
    if went_to_hand:
        _enqueue_field_when(state, defender, "on_self_life_to_hand", effects_overlay)
    else:
        _enqueue_field_when(state, defender, "on_self_life_to_trash", effects_overlay)
    _enqueue_field_when(state, defender, "on_self_life_taken", effects_overlay)
    _maybe_resolve(state)


def evaluate_static_effects(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """`on_attached_don N` 系の常在効果を再評価し、各 InPlay の static_buff を更新する。

    両陣営の static_buff を一旦 0 にリセットしてから、ターンプレイヤー側を先、
    非ターンプレイヤー側を後の順で発火 (公式 1-3-4, 6-6-1-1-2)。
    leader / characters / stages すべてを走査対象にする (ステージ永続効果対応)。
    state.effects_overlay に変更があった場合や、ドン付与・キャラ登場・KO 後に呼ぶ。
    """
    # ⚠ 表向きライフ枚数の正規化 (2026-08-04)。 face_up_life_count は **増やす側も読む側も**
    #   `min(..., len(life))` で clamp していたが、 **ライフが減る時に減らしていなかった**。
    #   ライフ 1 (表向き 1) → ダメージで 0 になっても 1 のまま残り、 後で put_top_to_life 等で
    #   ライフが増えると **新しく置いた裏向きのライフを表向きと誤認** する潜在バグだった。
    #   読み出しが clamp されているため挙動には出にくいが、 値は canonical state (digest 対象) の
    #   一部なので 「壊れた状態」 そのもの。 Rust 側の保存則チェック (INV-face-up-life) が検出した
    #   = 差分検証では見えない (両エンジンが同じ間違いをしていた) クラス。
    #   静的再計算は両エンジンが同じ場所で回すので、 ここで正規化すれば bit 一致も保たれる。
    for _p in state.players:
        _fu = int(getattr(_p, "face_up_life_count", 0) or 0)
        _clamped = max(0, min(_fu, len(_p.life)))
        if _clamped != _fu:
            _p.face_up_life_count = _clamped
    if not effects_overlay:
        return

    # 全 InPlay の静的フラグをリセット
    for player in state.players:
        player.hand_counter_boost = None   # 手札 counter 静的ブースト (OP16-118) も毎回再評価
        for ip in [player.leader, *player.characters, *player.stages]:
            ip.static_buff = 0
            ip.static_ko_immune = False
            ip.static_ko_immune_from_source_power_le = -1
            ip.static_ko_immune_from_non_attribute = ""
            ip.base_power_override = None
            ip.base_cost_override = None
            ip.attack_taunt = False
            ip.cannot_attack_static = False
            ip.protect_from_opp_effect = False
            ip.static_cannot_be_rested = False
            ip.ko_immune_battle_attributes_in.clear()
            ip.ko_immune_battle_attributes_not_in.clear()
            ip.battle_ko_immune_static = False
            ip.battle_ko_immune_vs_leader = False
            ip.battle_pump_vs_attribute = {}
            # static-granted keywords は毎回再計算 (= 条件外れたら消える)
            ip.static_granted_keywords.clear()
        # 静的 filter 付き cost reduction も毎回再構築
        player.play_cost_reductions_filtered = []

    # ターンプレイヤー側を先に処理 (公式 1-3-4)
    turn_idx = state.turn_player_idx
    order = [turn_idx, 1 - turn_idx]
    for me_idx in order:
        me = state.players[me_idx]
        opp = state.players[1 - me_idx]
        # leader + characters + stages すべての常在効果を走査
        candidates: list[InPlay] = (
            [me.leader] + list(me.characters) + list(me.stages)
        )
        for inplay in candidates:
            bundle = effects_overlay.get(inplay.card.card_id)
            if bundle is None:
                continue
            # 「効果が無効」 のキャラは静的効果も適用しない (= OP14-056 自身negateで
            # cannot_attack static 解除 / 一般に negate されたキャラの常在も無効化)。
            if "効果無効" in inplay.granted_keywords:
                continue
            for eff in bundle.effects:
                if eff.get("when") != "on_attached_don":
                    continue
                n_required = int(eff.get("n", 1))
                if inplay.attached_dons < n_required:
                    continue
                if not eval_all_conditions(eff, state, me, inplay):
                    continue
                for primitive in eff.get("do", []):
                    # 常在内の power_pump は static として扱う (duration を強制上書き)
                    if "power_pump" in primitive:
                        pp = dict(primitive["power_pump"])
                        pp["duration"] = "static"
                        primitive = {"power_pump": pp}
                    # 常在内の set_ko_immune は static_ko_immune を立てる
                    # spec: 文字列 (= 単一 target_spec) or dict (= filter target)
                    if "set_ko_immune" in primitive:
                        target_spec = primitive["set_ko_immune"]
                        if not isinstance(target_spec, (str, dict)):
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_ko_immune = True
                        continue
                    # 常在内の set_battle_ko_immune_vs_leader は vs-leader battle 耐性。
                    if "set_battle_pump_vs_attribute" in primitive:
                        spec = primitive["set_battle_pump_vs_attribute"]
                        attr = spec.get("attribute", "")
                        amount = int(spec.get("amount", 0))
                        target_spec = spec.get("target", "self")
                        for t in _resolve_target(target_spec, state, me, opp, inplay):
                            if attr:
                                t.battle_pump_vs_attribute[attr] = amount
                        continue
                    if "set_battle_ko_immune_vs_leader" in primitive:
                        sv = primitive["set_battle_ko_immune_vs_leader"]
                        target_spec = sv.get("target", "self") if isinstance(sv, dict) else "self"
                        if not isinstance(target_spec, (str, dict)):
                            target_spec = "self"
                        for t in _resolve_target(target_spec, state, me, opp, inplay):
                            t.battle_ko_immune_vs_leader = True
                        continue
                    # 常在内の set_battle_ko_immune は battle_ko_immune_static を立てる
                    # (= 「バトルでKOされない」 限定。 set_ko_immune の static_ko_immune は
                    #  効果KO も止めるので過剰。 OP03-079 / ST09-004 等の battle-only 用)。
                    if "set_battle_ko_immune" in primitive:
                        sb = primitive["set_battle_ko_immune"]
                        target_spec = sb.get("target", "self") if isinstance(sb, dict) else sb
                        if not isinstance(target_spec, (str, dict)):
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.battle_ko_immune_static = True
                        continue
                    # 常在内の set_ko_immune_from_source_power_le
                    # spec: {"target": "self", "threshold": 5000}
                    # OP14-003 「相手の元々のパワーN以下のキャラの効果でKOされない」
                    if "set_ko_immune_from_non_attribute" in primitive:
                        spec = primitive["set_ko_immune_from_non_attribute"]
                        attr = spec.get("attribute", "") if isinstance(spec, dict) else str(spec)
                        target_spec = spec.get("target", "self") if isinstance(spec, dict) else "self"
                        for t in _resolve_target(target_spec, state, me, opp, inplay):
                            t.static_ko_immune_from_non_attribute = attr
                        continue
                    if "set_ko_immune_from_source_power_le" in primitive:
                        spec = primitive["set_ko_immune_from_source_power_le"]
                        if not isinstance(spec, dict):
                            spec = {}
                        target_spec = spec.get("target", "self")
                        threshold = int(spec.get("threshold", 0))
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_ko_immune_from_source_power_le = threshold
                        continue
                    # 「元々のパワーを X にする」: base_power_override
                    if "set_base_power" in primitive:
                        spec = primitive["set_base_power"]
                        target_spec = spec.get("target", "self")
                        amount = int(spec.get("amount", 0))
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.base_power_override = amount
                        continue
                    # 「相手はこのキャラ以外にアタックできない」 (taunt)
                    if "set_attack_taunt" in primitive:
                        target_spec = primitive["set_attack_taunt"] if isinstance(primitive["set_attack_taunt"], str) else "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.attack_taunt = True
                        continue
                    # 「相手はキャラの『X』以外にアタックできない」 (= name フィルタ付き taunt)
                    # OP01-051 ユースタス・キッド系。 場の me.characters のうち name 一致を
                    # attack_taunt=True に。 0 体なら制約なし (= 自然な動作)。
                    if "cannot_attack_target_except" in primitive:
                        spec = primitive["cannot_attack_target_except"]
                        target_name = spec.get("name", "") if isinstance(spec, dict) else str(spec)
                        for t in me.characters:
                            if t.card.name == target_name:
                                t.attack_taunt = True
                        continue
                    # 「このカードはアタックできない」常在 (OP11-022 緑黄しらほし リーダー)
                    if "set_cannot_attack_static" in primitive:
                        target_spec = primitive["set_cannot_attack_static"] if isinstance(primitive["set_cannot_attack_static"], str) else "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.cannot_attack_static = True
                        continue
                    if "set_deck_out_wins" in primitive:
                        me.deck_out_wins = True
                        continue
                    if "set_cannot_attack_filtered_static" in primitive:
                        spec = primitive["set_cannot_attack_filtered_static"]
                        filt = spec.get("filter", {})
                        scope = spec.get("scope", "both")
                        pools = []
                        if scope in ("self", "both"):
                            pools += list(me.characters)
                        if scope in ("opp", "both"):
                            pools += list(opp.characters)
                        for t in pools:
                            if _matches_filter_ip(t, filt):
                                t.cannot_attack_static = True
                        continue
                    if "set_effect_negate_filtered_static" in primitive:
                        spec = primitive["set_effect_negate_filtered_static"]
                        excl = spec.get("exclude_filter", {})
                        for t in list(me.characters):
                            if not _matches_filter_ip(t, excl):
                                t.static_granted_keywords.add("効果無効")
                        continue
                    # 「相手キャラは自分の効果で離れない」常在 (OP14-079 黒クロコ)
                    # opponent の全キャラに protect_from_opp_effect=True をセット
                    if "set_opp_protect_static" in primitive:
                        for t in opp.characters:
                            t.protect_from_opp_effect = True
                        continue
                    # 「自身は相手の効果で場を離れない」常在 (OP02-027 / P-104 等)
                    # spec: True | {"target": "self" | "all_self_..."}
                    if "set_protect_from_opp_effect_static" in primitive:
                        spec = primitive["set_protect_from_opp_effect_static"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                        else:
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.protect_from_opp_effect = True
                        continue
                    # 「対象は相手の効果でレストにされない」常在 (OP12-021 いっぽんマツ 等)。
                    # rest 限定の免疫 = static_cannot_be_rested (KO/離脱は防がない = 公式通り)。
                    if "set_cannot_be_rested_static" in primitive:
                        spec = primitive["set_cannot_be_rested_static"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                        else:
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_cannot_be_rested = True
                        continue
                    # 「属性 X を持つカードとのバトルで KO されない」 (P-052 ミホーク等)
                    # spec: {"target": "self", "attributes": ["斬"], "negate": false}
                    #   negate=True なら 「属性 X を持たない」 限定 (P-025 スモーカー)
                    if "set_ko_immune_battle_only" in primitive:
                        # 「バトルで KO されない」 (= 効果 KO は通る) 静的効果。
                        # OP10-104 / OP10-035 等。 spec: True | {"target": ...}
                        spec = primitive["set_ko_immune_battle_only"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                        else:
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.battle_ko_immune_static = True
                        continue
                    if "set_immune_attribute_in_battle" in primitive:
                        spec = primitive["set_immune_attribute_in_battle"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                            attrs = spec.get("attributes", [])
                            if isinstance(attrs, str):
                                attrs = [attrs]
                            negate = bool(spec.get("negate", False))
                        else:
                            target_spec, attrs, negate = "self", [str(spec)], False
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            if negate:
                                t.ko_immune_battle_attributes_not_in.update(attrs)
                            else:
                                t.ko_immune_battle_attributes_in.update(attrs)
                        continue
                    # filter 付き cost reduction static (OP05-097 天竜人 等)
                    if "reduce_play_cost_filtered_static" in primitive:
                        spec = primitive["reduce_play_cost_filtered_static"]
                        me.play_cost_reductions_filtered.append({
                            "filter": spec.get("filter", {}),
                            "amount": int(spec.get("amount", 1)),
                        })
                        continue
                    # give_keyword / give_rush は static_granted_keywords へ
                    # (= ドンが外れれば消える挙動を保証する)
                    if "give_keyword" in primitive:
                        spec = primitive["give_keyword"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                            keyword = spec.get("keyword", "速攻")
                        else:
                            target_spec, keyword = "self", "速攻"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_granted_keywords.add(keyword)
                        continue
                    if "give_rush" in primitive:
                        target_spec = primitive["give_rush"] if isinstance(primitive["give_rush"], str) else "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_granted_keywords.add("速攻")
                        continue
                    # 「元々のコストを X にする / +N する」: base_cost_override
                    if "set_base_cost" in primitive:
                        spec = primitive["set_base_cost"]
                        target_spec = spec.get("target", "self")
                        # absolute (= "amount") か delta (= "delta")
                        if "amount" in spec:
                            amount = int(spec["amount"])
                            targets = _resolve_target(target_spec, state, me, opp, inplay)
                            for t in targets:
                                t.base_cost_override = amount
                        elif "delta" in spec:
                            delta = int(spec["delta"])
                            targets = _resolve_target(target_spec, state, me, opp, inplay)
                            for t in targets:
                                cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                                t.base_cost_override = max(0, cur + delta)
                        elif "delta_per" in spec:
                            # スケーリング delta (= 「トラッシュ4枚につきコスト+1」 ST27-004)。
                            dp = spec["delta_per"]
                            src = dp.get("source", "")
                            divisor = max(1, int(dp.get("divisor", 1)))
                            mult = int(dp.get("multiplier", 1))
                            src_val = len(me.trash) if src == "self_trash_count" else 0
                            delta = (src_val // divisor) * mult
                            targets = _resolve_target(target_spec, state, me, opp, inplay)
                            for t in targets:
                                cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                                t.base_cost_override = max(0, cur + delta)
                        continue
                    # filter 付きの 場のキャラ コスト変更 静的効果 (OP10-042 ウソップ系)
                    # 公式 「自分のコスト2以上の特徴《ドレスローザ》を持つキャラすべてを、 コスト+1」 等。
                    # spec: {"filter": {"feature": "ドレスローザ", "cost_ge": 2}, "delta": 1,
                    #        "scope": "self" | "opp" (省略時 = "self")}
                    if "set_hand_counter_boost" in primitive:
                        # OP16-118 ポートガス: 自分の手札の該当カード (filter) の counter を静的に +amount。
                        # 実適用は _spend_counters (= 防御で counter を切る時) が me.hand_counter_boost を読む。
                        me.hand_counter_boost = dict(primitive["set_hand_counter_boost"])
                        continue
                    if "set_base_cost_filtered_static" in primitive:
                        spec = primitive["set_base_cost_filtered_static"]
                        filt = spec.get("filter", {})
                        scope = spec.get("scope", "self")
                        targets_pool = me.characters if scope == "self" else opp.characters
                        if "delta" in spec:
                            delta = int(spec["delta"])
                            for t in targets_pool:
                                if not _matches_filter_ip(t, filt):
                                    continue
                                cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                                t.base_cost_override = max(0, cur + delta)
                        elif "amount" in spec:
                            amount = int(spec["amount"])
                            for t in targets_pool:
                                if not _matches_filter_ip(t, filt):
                                    continue
                                t.base_cost_override = amount
                        continue
                    # ⚠ 静的効果 (on_attached_don) の評価は **連続評価でプレイヤー決定でない** ので
                    # human-pick modal を出してはいけない。 出すと「modal → 解決 → 静的再評価 →
                    # modal …」 の無限ループになる (= ST01-013 ゾロ on_attached_don power_pump
                    # {self_inplay} が target_pick modal を反復、 2026-06-05 合成デッキ fuzz 検出)。
                    # forced_human_actor_idx=-1 で AI モード強制 (= _should_human_pick False、 modal 抑止)。
                    # ⚠ さらに 進行中の pending_choice (= 別効果の human-pick 待ち、 例: ドール
                    # 登場時 任意 discard) を 一時退避して None にする。 これが 無いと power_pump 等の
                    # primitive が 「state.pending_choice is not None → halt」 ガードで 早期 return し、
                    # 直前に reset した static_buff を 再加算せず → 静的チーム buff (孔雀 EB03-041
                    # 「相手ターン中 全体+2000」 等) が pending choice 中だけ 0 に消える (= 2026-06-11
                    # コビーミラー campaign で 検出、 -6000 が buff 剥がれた値を KO する重大バグ)。
                    # 静的評価は deterministic (modal 無し) なので 新規 pending は生まれない。
                    _prev_forced = getattr(state, "forced_human_actor_idx", None)
                    _prev_pending = state.pending_choice
                    state.forced_human_actor_idx = -1
                    state.pending_choice = None
                    try:
                        execute_effect(primitive, state, me, opp, inplay)
                    finally:
                        state.forced_human_actor_idx = _prev_forced
                        state.pending_choice = _prev_pending


def _enqueue_field_when(
    state: GameState,
    owner: Player,
    when: str,
    effects_overlay: dict[str, CardEffectBundle],
    only_iids: Optional[set[int]] = None,
) -> None:
    """owner の場 (leader + characters + stages) のうち、 指定 when を持つ全ての InPlay を enqueue。
    複数効果がある場合でもイベントは「カード単位」で 1 つ (= _execute_event が when 一致を全実行)。
    ⚠ 2026-07-24 修正: 従来 stages を除外しており、 ステージの field-when トリガー
    (on_self_chara_ko / on_self_chara_leave_by_opp_effect 等、 OP09-080 サニー号) が発火しなかった。

    only_iids: 指定時、 その instance_id 集合に含まれる InPlay のみ enqueue する。
      = 「発火の起点となる事象の **前** に場に居たカードだけ反応させる」 スナップショット用。
      OP13-106 コニー: 自身の【トリガー】(このカードを登場させる) で登場した時、 その同じ
      【トリガー】発動を自身の【相手のターン中】(【トリガー】発動時ブロッカー) で拾わない
      (公式 cardqa_op_13: 「いいえ、できません。この効果は、このキャラが場にある間に
      【トリガー】効果を発動した際に発動できる効果です」)。
    """
    candidates: list[InPlay] = [owner.leader] + list(owner.characters) + list(owner.stages)
    owner_idx = state.players.index(owner)
    for ip in candidates:
        if only_iids is not None and ip.instance_id not in only_iids:
            continue
        bundle = effects_overlay.get(ip.card.card_id)
        if bundle is None:
            continue
        if not any(e.get("when") == when for e in bundle.effects):
            continue
        enqueue_event(
            state,
            when=when,
            owner_idx=owner_idx,
            source_card_id=ip.card.card_id,
            source_iid=ip.instance_id,
        )


def trigger_turn_start(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """ターン開始時の自動効果を enqueue (公式 6-2-1-1-2)。

    順序保証:
    - ターン側「自分のターン開始時」 を 全件 enqueue (= owner_idx=turn_player_idx)
    - 非ターン側「相手のターン開始時」 を 全件 enqueue (= owner_idx=非ターン側)
    キューはアクティブプレイヤー優先で取り出されるので、 自然に「ターン側 → 非ターン側」 順になる。
    """
    if not effects_overlay:
        return
    me = state.turn_player
    opp = state.opponent
    _enqueue_field_when(state, me, "on_turn_start", effects_overlay)
    _enqueue_field_when(state, opp, "opp_turn_start", effects_overlay)
    _maybe_resolve(state)


def _end_of_turn_cost_is_real(cost: dict) -> bool:
    """end_of_turn の cost dict が user-optional payment を伴うか判定。

    once_per_turn のみ なら 「ターン1回ガード」 = 強制 効果 (= 払う もの 無し)。
    trash_self / return_self_to_hand / discard_hand / pay_don / rest_self_don /
    return_self_chara_to_hand 等 を 1 つ でも 含む なら user-optional。
    """
    if not isinstance(cost, dict):
        return False
    real_cost_keys = {
        "trash_self",
        "return_self_to_hand",
        "return_self_chara_to_hand",
        "discard_hand",
        "discard_hand_with_filter",
        "pay_don",
        "rest_self_don",
        "ko_self_with_filter",
        "rest_self",
    }
    return any(k in cost for k in real_cost_keys)


def _can_pay_end_of_turn_cost(
    state: GameState,
    owner: Player,
    source: InPlay,
    cost: dict,
) -> bool:
    """end_of_turn cost が支払い可能か判定 (= modal 候補に出すか の前提)。"""
    if not isinstance(cost, dict):
        return True
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0 and (owner.don_active + owner.don_rested) < pay_don:
        return False
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0 and owner.don_active < rest_don:
        return False
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0 and len(owner.hand) < discard_n:
        return False
    if cost.get("return_self_to_hand") and source not in owner.characters and source not in owner.stages:
        return False
    if cost.get("trash_self") and source not in owner.characters and source not in owner.stages:
        return False
    # return_self_chara_to_hand: filter 該当 候補 必須
    rsc = cost.get("return_self_chara_to_hand")
    if rsc:
        if isinstance(rsc, dict):
            filt = rsc.get("filter", {})
            need = int(rsc.get("count", 1))
        else:
            filt, need = {}, 1
        from_chara = list(owner.characters)
        candidates = [c for c in from_chara if _matches_filter_ip(c, filt)]
        if len(candidates) < need:
            return False
    # ko_self_with_filter
    ksf = cost.get("ko_self_with_filter")
    if ksf:
        if not any(_matches_filter_ip(c, ksf) for c in owner.characters):
            return False
    return True


def _pay_end_of_turn_cost(
    state: GameState,
    owner: Player,
    opp: Player,
    source: InPlay,
    cost: dict,
    eff_idx: int,
    eff: Optional[dict] = None,
) -> None:
    """end_of_turn cost を 実際 に 支払う (= activate_main の fire_activate_main 風)。

    log は 「ターン終了コスト: ...」 prefix で push。 source は trash/return された 場合
    場 から 取り除かれている (= 後続 enqueue で source_iid 探索 が None になる が、
    explicit effect_indexes payload 経由 で 効果 は 発火 する)。
    """
    me = owner
    # trash_self
    if cost.get("trash_self"):
        if source in me.characters:
            me.characters.remove(source)
            me.trash.append(source.card)
            if source.attached_dons > 0:
                me.don_rested += source.attached_dons
                source.attached_dons = 0
            state.push_log(f"  ターン終了コスト: 自トラッシュ {source.card.name}")
        elif source in me.stages:
            me.stages.remove(source)
            me.trash.append(source.card)
            if source.attached_dons > 0:
                me.don_rested += source.attached_dons
                source.attached_dons = 0
            state.push_log(f"  ターン終了コスト: 自ステージトラッシュ {source.card.name}")
    # return_self_to_hand
    if cost.get("return_self_to_hand") and source in me.characters:
        me.characters.remove(source)
        me.hand.append(source.card)
        if source.attached_dons > 0:
            me.don_rested += source.attached_dons
            source.attached_dons = 0
        state.push_log(f"  ターン終了コスト: 自 → 手札 {source.card.name}")
    # pay_don
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0:
        taken = min(pay_don, me.don_active)
        me.don_active -= taken
        me.don_remaining_in_deck += taken
        rest_more = min(pay_don - taken, me.don_rested)
        me.don_rested -= rest_more
        me.don_remaining_in_deck += rest_more
        state.push_log(f"  ターン終了コスト: ドン-{pay_don}")
        if (taken + rest_more) > 0 and state.effects_overlay:
            trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay, count=taken + rest_more)
    # rest_self_don
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0:
        actual = min(rest_don, me.don_active)
        me.don_active -= actual
        me.don_rested += actual
        state.push_log(f"  ターン終了コスト: アクティブドン {actual} レスト")
    # rest_self
    if cost.get("rest_self") and not source.rested:
        source.rested = True
        state.push_log(f"  ターン終了コスト: 自レスト {source.card.name}")
    # discard_hand: 自手札はプレイヤーが選ぶ → AI は最悪札から(random で value を薄めない)。
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0:
        for _ in range(min(discard_n, len(me.hand))):
            me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
        state.push_log(f"  ターン終了コスト: 手札{discard_n}捨て")
    # return_self_chara_to_hand: filter 該当 chara を N 枚 手札 戻し
    rsc = cost.get("return_self_chara_to_hand")
    if rsc:
        if isinstance(rsc, dict):
            filt = rsc.get("filter", {})
            need = int(rsc.get("count", 1))
        else:
            filt, need = {}, 1
        returned = 0
        for c in list(me.characters):
            if returned >= need:
                break
            if not _matches_filter_ip(c, filt):
                continue
            me.characters.remove(c)
            me.hand.append(c.card)
            if c.attached_dons > 0:
                me.don_rested += c.attached_dons
                c.attached_dons = 0
            state.push_log(f"  ターン終了コスト: {c.card.name} を手札へ")
            returned += 1
    # ko_self_with_filter
    ksf = cost.get("ko_self_with_filter")
    if ksf:
        for c in list(me.characters):
            if _matches_filter_ip(c, ksf):
                me.characters.remove(c)
                me.trash.append(c.card)
                if c.attached_dons > 0:
                    me.don_rested += c.attached_dons
                state.push_log(f"  ターン終了コスト: 自KO {c.card.name}")
                if state.effects_overlay:
                    trigger_on_ko(state, me, opp, c.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=c.attached_dons, victim_effect_negated=_ip_effect_negated(c))
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
                break
    # once_per_turn フラグ
    if cost.get("once_per_turn"):
        setattr(source, f"_end_of_turn_used_{eff_idx}", True)
        # canonical mirror (= digest に載せて Rust から追跡可能にする、 2026-08-02)。
        # 判定は上の動的属性のまま = Python の挙動は不変。 when は呼出側の when_key と一致。
        source.mark_event_once(str((eff or {}).get("when") or "end_of_turn"), eff_idx)


def _ai_should_fire_end_of_turn_cost(
    state: GameState,
    owner: Player,
    source: InPlay,
    eff: dict,
) -> bool:
    """AI が cost-bearing end_of_turn 効果 を 自発的 に 発動するか の EV heuristic。

    2026-05-23 強化: 効果別 benefit / cost を 数値化、 闕的状況補正 (= life/hand) で 判定。
    旧 雑 ロジック (= do_keys & beneficial で 即 True、 trash_self は 弱キャラ のみ) を
    EV 比較 に 置換。
    """
    cost = eff.get("cost") or {}
    do_list = eff.get("do") or []
    do_keys: set = set()
    for prim in do_list:
        if isinstance(prim, dict):
            do_keys.update(prim.keys())

    # cost 価値 数値化 (= EV 比較 用)
    cost_value = 0
    pay_don = int(cost.get("pay_don", 0))
    rest_don = int(cost.get("rest_self_don", 0))
    discard_n = int(cost.get("discard_hand", 0))
    cost_value += pay_don * 800 + rest_don * 400 + discard_n * 1500
    if cost.get("trash_self"):
        # source の 価値 = cost*1000 + power
        card = source.card
        cost_value += int(card.cost or 0) * 1000 + int(card.power or 0) // 2
    if cost.get("return_self_to_hand"):
        # 手札 戻し は 再 プレイ 可能 だが 一旦 場 を 失う
        card = source.card
        cost_value += int(card.cost or 0) * 500 + int(card.power or 0) // 4
    if cost.get("rest_self") and not source.rested:
        cost_value += 600

    # benefit 数値化
    benefit = 0
    if do_keys & {"draw"}:
        benefit += 1500  # 1 枚ドロー
    if do_keys & {"search", "search_top_n"}:
        benefit += 2000  # サーチ ドローより 強い
    if do_keys & {"add_don"}:
        benefit += 1000
    if do_keys & {"untap_don"}:
        # active 化 = 来ターンの 行動余地
        opp_active = state.players[1 - state.players.index(owner)].don_active
        benefit += 800 + opp_active * 50  # 相手 ターン リソース余裕 多いほど 価値高
    if do_keys & {"ko", "ko_multi"}:
        # 相手キャラ KO: コスト * 1000 を 仮定 平均 3
        benefit += 3000
    if do_keys & {"return_to_hand", "return_to_hand_multi"}:
        benefit += 2500
    if do_keys & {"power_pump"}:
        # end_of_turn の power_pump は 通常 「相手 ターン中 持続」 で 守備強化
        benefit += 1500
    if do_keys & {"give_keyword"}:
        benefit += 2000

    # 闕的状況補正
    life = len(owner.life)
    hand = len(owner.hand)
    if life <= 1:
        benefit += 1000  # 守り強化系の価値 アップ
    if hand <= 2:
        # 手札少 で discard_hand 系 cost は 致命的
        if discard_n > 0:
            cost_value += 2000
        # draw 系 は 命綱
        if do_keys & {"draw", "search"}:
            benefit += 1500

    # trash_self: source の 価値 が 効果 を 下回る なら fire しない
    if cost.get("trash_self"):
        card = source.card
        # 弱キャラ (= cost≤3 + power≤4000) は trash 推奨
        if int(card.cost or 0) <= 3 and int(card.power or 0) <= 4000:
            cost_value -= 1500  # 価値補正 で fire しやすく
    return benefit > cost_value


def trigger_end_of_turn(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """エンドフェイズの自動効果を enqueue (公式 6-6-1-1)。
    順序: ターン側【自分のターン終了時】→ 非ターン側【相手のターン終了時】。

    cost 付き optional 効果 (= 「このキャラをトラッシュに置くことができる：〜」 等) は:
    - 効果 owner が human: pending_choice "end_of_turn_optional" を 立てて user 選択 待ち
      (= forced 効果 は 通常通り enqueue、 cost optional のみ defer)
    - 効果 owner が AI: 簡易 heuristic で 即 決定 → 支払い + enqueue
    """
    if not effects_overlay:
        return
    me = state.turn_player
    opp = state.opponent
    me_idx = state.players.index(me)
    opp_idx = 1 - me_idx

    # === このターン終了時の delayed 処理 (= turn player 視点) ===
    # 1. schedule_at_self_turn_end で予約された効果を flush (= OP15-025 クロ。 従来 append のみで
    #    一度も実行されない dead 状態だった bug 修復)。
    scheduled = list(getattr(me, "scheduled_at_self_turn_end", None) or [])
    if scheduled:
        me.scheduled_at_self_turn_end = []
        for spec in scheduled:
            for prim in (spec.get("do", []) if isinstance(spec, dict) else []):
                execute_effect(prim, state, me, opp, None)
    # 2. 一時登場キャラ を 持ち主のデッキの下へ戻す (= OP11-092 ヘルメッポ)。
    for ip in [c for c in list(me.characters)
               if getattr(c, "return_to_deck_bottom_at_turn_end", False)]:
        me.characters.remove(ip)
        me.deck.append(ip.card)
        if ip.attached_dons > 0:
            me.don_rested += ip.attached_dons
            ip.attached_dons = 0
        state.push_log(f"  ターン終了時: {ip.card.name} を デッキの下に置く")
    # 2b. 「このターン終了時、このキャラをトラッシュ」 自己犠牲 (= OP03-005 サッチ)。
    for ip in [c for c in list(me.characters)
               if getattr(c, "trash_at_self_turn_end", False)]:
        me.characters.remove(ip)
        me.trash.append(ip.card)
        if ip.attached_dons > 0:
            me.don_rested += ip.attached_dons
            ip.attached_dons = 0
        state.push_log(f"  ターン終了時: {ip.card.name} を トラッシュに置く")

    human_optionals: list[dict] = []

    for player, when_key, player_idx in [
        (me, "end_of_turn", me_idx),
        (opp, "opp_end_of_turn", opp_idx),
    ]:
        is_human = (
            state.human_player_idx is not None
            and player_idx == state.human_player_idx
        )
        for source in [player.leader, *player.characters, *player.stages]:
            bundle = effects_overlay.get(source.card.card_id)
            if bundle is None:
                continue
            forced_idxs: list[int] = []
            for idx, eff in enumerate(bundle.effects):
                if eff.get("when") != when_key:
                    continue
                cost = eff.get("cost") or {}
                # once_per_turn 既使用 は skip (= cost 経由 / top-level 両方)
                per_turn_key = f"_end_of_turn_used_{idx}"
                if cost.get("once_per_turn") and getattr(source, per_turn_key, False):
                    continue
                if not _end_of_turn_cost_is_real(cost):
                    # 強制 効果 (= cost なし / once_per_turn のみ): 常 enqueue
                    forced_idxs.append(idx)
                    continue
                # cost-bearing optional
                if not eval_all_conditions(eff, state, player, source):
                    continue
                if not _can_pay_end_of_turn_cost(state, player, source, cost):
                    continue
                if is_human:
                    human_optionals.append({
                        "owner_idx": player_idx,
                        "when_key": when_key,
                        "source_iid": source.instance_id,
                        "card_id": source.card.card_id,
                        "card_name": source.card.name,
                        "effect_idx": idx,
                        "effect_text": eff.get("_text", ""),
                        "pay_don": int(cost.get("pay_don", 0)),
                        "rest_self_don": int(cost.get("rest_self_don", 0)),
                        "discard_hand": int(cost.get("discard_hand", 0)),
                        "trash_self": bool(cost.get("trash_self")),
                        "return_self_to_hand": bool(cost.get("return_self_to_hand")),
                        "return_self_chara_to_hand": bool(cost.get("return_self_chara_to_hand")),
                        "rest_self": bool(cost.get("rest_self")),
                        "ko_self_with_filter": bool(cost.get("ko_self_with_filter")),
                    })
                else:
                    # AI: heuristic で 即決
                    if _ai_should_fire_end_of_turn_cost(state, player, source, eff):
                        opp_for_pay = state.players[1 - player_idx]
                        _pay_end_of_turn_cost(state, player, opp_for_pay, source, cost, idx, eff)
                        forced_idxs.append(idx)
            if forced_idxs:
                enqueue_event(
                    state,
                    when=when_key,
                    owner_idx=player_idx,
                    source_card_id=source.card.card_id,
                    source_iid=source.instance_id,
                    payload={"effect_indexes": sorted(set(forced_idxs))},
                )

    if human_optionals:
        # 強制 効果 を 先 に drain → その 後 で 任意効果 modal を 立てる
        # (= 強制 effect が 場 を 動かす と modal の 表示内容 が ズレる ため)。
        # 但し forced 解決 中 に target_pick が 立つ 可能性 あり → 立ったら 待ち、
        # resolve_pending_choice の 再 entry で end_of_turn_optional を セット する。
        state._pending_end_of_turn_optional = human_optionals
        _maybe_resolve(state)
        _maybe_prompt_end_of_turn_optional(state)
        return

    _maybe_resolve(state)


def _maybe_prompt_end_of_turn_optional(state: GameState) -> None:
    """forced 効果 が 完全 に 解決 され、 nested choice も ない なら end_of_turn_optional を 立てる。

    target_pick / option_pick 等 が pending なら 何もしない (= それらの resolve 後 に
    再呼び出し される)。
    """
    if state.pending_choice is not None:
        return
    pending = getattr(state, "_pending_end_of_turn_optional", None)
    if not pending:
        return
    state.pending_choice = {
        "kind": "end_of_turn_optional",
        "available": list(pending),
        "description": "ターン終了時の任意効果",
    }
    state._pending_end_of_turn_optional = []
    state.push_log(
        f"  効果: ターン終了時 任意効果 {len(pending)}件 選択 待ち"
    )


def _ai_should_fire_opp_attack_cost(
    state: GameState,
    me: Player,
    source_inplay: InPlay,
    eff: dict,
    attacker: Optional[InPlay] = None,
    defended_target: Optional[InPlay] = None,
) -> bool:
    """AI defender が cost 付き opp_attack 効果 を 発動 すべきか の EV 判定。

    旧挙動 は cost 払えれば 必ず fire していて、 「不利交換 (= 発動 しても 攻撃 通る + don 損)」
    を 見抜けなかった。 簡易 EV モデル で benefit > cost なら fire 推奨。

    考慮:
    - cost 価値: pay_don=800/枚、 rest_don=400/枚、 discard_hand=1500/枚
    - benefit 推定: ko/return → attacker.cost * 1000、 power_pump → 2000、
      give_keyword (= ブロッカー等) → 2500、 draw/search → 1500、
      prevent_ko → life 残量 で 5000/3000/1500
    - ライフ少 (= life ≤ 1) bonus: +2000 (= 守備積極化)
    - 攻撃 確実失敗 (= attacker_power < me.target_power - 2000) なら skip
      (= 不要 発動 防止)

    """
    cost = eff.get("cost") or {}
    do_list = eff.get("do") or []

    pay_don = int(cost.get("pay_don", 0))
    rest_don = int(cost.get("rest_self_don", 0))
    discard_n = int(cost.get("discard_hand", 0))
    cost_value = pay_don * 800 + rest_don * 400 + discard_n * 1500

    do_keys: set = set()
    for prim in do_list:
        if isinstance(prim, dict):
            do_keys.update(prim.keys())

    # ⭐ 過剰防御防止 (ohtsuki 報告 idx25「リーダー効果だけでカウンター値足りてる」= AI が
    #   不要な時も手札を捨てて -2000 防御): 効果が「このバトル中の power 増減」だけ (= 恒久
    #   価値なし、 純粋にこのバトルの防御用) で、 防御対象が効果なしでも この攻撃を耐える
    #   (defended_power > attacker_power、 counter 前でも生存) なら発動不要 → skip (手札等を温存)。
    #   defended_target を渡された時のみ (= game.py の attack step)。 それ以外は従来 heuristic。
    if (attacker is not None and defended_target is not None
            and do_keys == {"power_pump"}
            and not os.environ.get("ONEPIECE_NO_OVERDEFENSE_SKIP")):  # A/B 用 opt-out
        _all_battle = all(
            isinstance(p.get("power_pump"), dict)
            and p["power_pump"].get("duration") == "battle"
            for p in do_list if "power_pump" in p
        )
        if _all_battle and int(defended_target.power or 0) > int(attacker.power or 0):
            return False

    benefit = 0
    if do_keys & {"ko", "ko_multi", "return_to_hand", "return_to_hand_multi"}:
        atk_cost = int(attacker.card.cost) if attacker and attacker.card.cost else 3
        benefit += atk_cost * 1000
    if do_keys & {"power_pump"}:
        benefit += 2000
    if do_keys & {"give_keyword", "give_rush"}:
        benefit += 2500
    if do_keys & {"draw", "search", "search_top_n"}:
        benefit += 1500
    if do_keys & {"prevent_ko", "set_ko_immune", "set_ko_immune_timed", "set_ko_immune_battle_only"}:
        life = len(me.life)
        benefit += 5000 if life <= 1 else 3000 if life <= 2 else 1500
    if do_keys & {"add_don", "attach_don", "attach_active_don"}:
        benefit += 1000
    if do_keys & {"redirect_attack"}:
        # アタック対象変更 (= ST36-005 キッド 等): リーダー/弱キャラへの攻撃を、 パワーの高い
        # 自キャラ (= 攻撃を耐える or 交換で得) に受け流す 防御価値。 leader への攻撃を逸らすと
        # ライフ/リーサルを守れるので、 ライフ残量が少ないほど価値が高い。
        life = len(me.life)
        benefit += 4000 if life <= 1 else 3000 if life <= 2 else 2000

    # 攻撃 確実失敗 推定 (= 発動 不要)
    if attacker is not None:
        atk_power = int(attacker.power or 0)
        # defender が source_inplay 自身 と 仮定 して、 atk < src_power なら fire 不要
        src_power = int(source_inplay.power or 0)
        if src_power > 0 and atk_power + 2000 < src_power:
            return False

    # ライフ補正
    life = len(me.life)
    if life <= 1:
        benefit += 2000

    return benefit > cost_value


def _enqueue_opp_attack_with_cost(
    state: GameState,
    me: Player,
    when_key: str,
    effects_overlay: dict[str, CardEffectBundle],
    attacker: Optional[InPlay] = None,
    defended_target: Optional[InPlay] = None,
) -> None:
    """【相手のアタック時】 系 を 処理。
    人間 defender + cost 持ち: pending_choice "on_opp_attack_optional" で user 確認。
    AI defender + cost 持ち: 即時 支払 + 発火 (= 旧挙動 互換)。
    cost 無し: 全 cases で auto-fire。
    1 card = 1 event で enqueue (= 重複 fire 防止)。
    """
    me_idx = state.players.index(me)
    is_human_actor = (
        state.human_player_idx is not None
        and me_idx == state.human_player_idx
    )

    # 新しい battle (= 新 attacker) なら 防御側の costless opp_attack gate
    # (_opp_attack_opt_skipped) を クリアする。 同 battle (= pause 跨ぎの re-fire) では保持
    # = loop protection。 battle key = (turn_number, attacker.instance_id) は pickle 安定な
    # ので claude_play の 1コマンド1プロセス でも「同 battle か新 battle か」を正しく判別でき、
    # _reset_battle_buffs (= マルチプロセス pause 経路で取りこぼす) や id() マーカーに依存せず
    # gate を正しく リセットできる。 マルチ攻撃ターンで 2 発目以降の防御 pump modal が gate
    # 残留で抑止される 2026-06-09 赤青ルーシー campaign のバグ修正。
    if attacker is not None:
        battle_key = (state.turn_number, attacker.instance_id)
        if getattr(state, "_opp_attack_gate_battle_key", None) != battle_key:
            for ip in [me.leader, *me.characters, *me.stages]:
                if getattr(ip, "_opp_attack_opt_skipped", None):
                    ip._opp_attack_opt_skipped = set()
            state._opp_attack_gate_battle_key = battle_key

    pending_costed_human: list[tuple[InPlay, int, dict]] = []

    for source_inplay in [me.leader, *me.characters, *me.stages]:
        bundle = effects_overlay.get(source_inplay.card.card_id)
        if bundle is None:
            continue
        eff_indexes_to_fire: list[int] = []
        has_any_matching = False
        for idx, eff in enumerate(bundle.effects):
            if eff.get("when") != when_key:
                continue
            has_any_matching = True
            cost = eff.get("cost") or {}
            if not cost:
                # cost 無し: 1 アタック (= battle) 1 回 gate して enqueue。
                # 人間 modal (= optional_discard_hand_for_battle_buff 等) で pause→resume
                # する際、 claude_play は 1 コマンド =1 プロセス で session を再ロードするため、
                # _opp_attack_pre_fired_id (= id(attacker)) マーカーが プロセス跨ぎで 不一致 →
                # trigger_on_opp_attack が再呼出され costless 効果 が 再 enqueue → modal 無限
                # ループ。 on_attack 側 (_on_attack_opt_skipped) と 同型の instance 属性 gate
                # (= pickle 安定) で 1 battle 1 回に固定。 _reset_battle_buffs (battle 終了)
                # でクリア → 次の攻撃 (別 battle) では 再び fire。 AI vs AI は 攻撃毎に 1 回
                # 発火で 不変 (= matrix 影響なし)。 2026-06-09。
                _skipped = getattr(source_inplay, "_opp_attack_opt_skipped", None)
                if _skipped is None:
                    _skipped = set()
                if idx in _skipped:
                    continue
                _skipped.add(idx)
                source_inplay._opp_attack_opt_skipped = _skipped
                eff_indexes_to_fire.append(idx)
                continue
            if not eval_all_conditions(eff, state, me, source_inplay):
                continue
            if cost.get("once_per_turn") and idx in source_inplay.attack_once_used:
                continue
            pay_don = int(cost.get("pay_don", 0))
            rest_don = int(cost.get("rest_self_don", 0))
            discard_n = int(cost.get("discard_hand", 0))
            # 全 cost キーで支払い可能か判定 (= pay_don/rest_self_don/discard_hand だけでなく
            # discard_hand_with_filter/rest_self/trash_self 等も)。 払えない効果は提示しない
            # (= apply_human_use_opp_attack_effect / AI 即時支払の _can_pay と整合、 ValueError 防止)。
            real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
            if real_cost and not _can_pay_counter_cost(state, me, source_inplay, real_cost):
                continue
            if is_human_actor:
                # 人間 defender → pending_choice 候補 へ
                pending_costed_human.append((source_inplay, idx, eff))
                continue
            # AI: EV 判定 → 発動 価値 低い なら skip (= 旧 「常 fire」 から 改善)
            if not _ai_should_fire_opp_attack_cost(
                    state, me, source_inplay, eff, attacker, defended_target):
                continue
            # AI: 即時 支払 + fire。 全 cost キーを _pay_counter_cost に委譲して漏れなく支払う
            # (= 旧実装は pay_don/rest_self_don/discard_hand のみ inline で、 rest_self/trash_self/
            #   discard_hand_with_filter 等を踏み倒していた。 discard/don の派生トリガも未発火だった。
            #   2026-06-04 修正)。
            real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
            opp_pl = state.players[1 - me_idx]
            if real_cost and not _can_pay_counter_cost(state, me, source_inplay, real_cost):
                continue  # 払えないなら発動しない (公式 4-10)
            if real_cost:
                _pay_counter_cost(state, me, opp_pl, source_inplay, real_cost)
            if cost.get("once_per_turn"):
                source_inplay.mark_attack_once_used(idx)
            eff_indexes_to_fire.append(idx)
        if not has_any_matching:
            continue
        if eff_indexes_to_fire:
            enqueue_event(
                state,
                when=when_key,
                owner_idx=me_idx,
                source_card_id=source_inplay.card.card_id,
                source_iid=source_inplay.instance_id,
                payload={"effect_indexes": sorted(set(eff_indexes_to_fire))},
            )

    if is_human_actor and pending_costed_human:
        # 人間 defender: click-based UI で 発動 する ため state 経由 で defense pending
        # payload に 「使える 効果 list」 を 露出。 (= auto-popup しない)。
        # HumanAI.choose_defense が payload を 構築 する 際 に 読む。
        available = []
        for src, eff_idx, eff in pending_costed_human:
            cost = eff.get("cost") or {}
            available.append({
                "source_iid": src.instance_id,
                "card_id": src.card.card_id,
                "card_name": src.card.name,
                "effect_idx": eff_idx,
                "effect_text": eff.get("_text", ""),
                "when_key": when_key,
                "pay_don": int(cost.get("pay_don", 0)),
                "rest_self_don": int(cost.get("rest_self_don", 0)),
                "discard_hand": int(cost.get("discard_hand", 0)),
                # source 系コストも露出 (= UI で「自レスト/自トラッシュ」 等を表示できるよう)。
                "rest_self": bool(cost.get("rest_self")),
                "trash_self": bool(cost.get("trash_self")),
                "discard_hand_with_filter": bool(cost.get("discard_hand_with_filter")),
            })
        # 既存 list と 統合 (= opp_attack / on_leader / on_chara 各 when_key から 追加)
        if not hasattr(state, "_available_opp_attack_effects"):
            state._available_opp_attack_effects = []
        state._available_opp_attack_effects.extend(available)


def trigger_on_opp_attack(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
    defended_target: Optional[InPlay] = None,
) -> None:
    """【相手のアタック時】(opp_attack) を enqueue (10-2-16-1)。
    me = アタックを受けているプレイヤー (= 効果の「自分」側)。
    opp = アタックしているプレイヤー。 defended_target = 攻撃されている自カード (leader/chara)。
    cost 持ち effect は 人間 defender に optional 確認 modal を 立てる。
    """
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(
        state, me, "opp_attack", effects_overlay,
        attacker=attacker, defended_target=defended_target,
    )
    _maybe_resolve(state)


def trigger_on_opp_attack_on_leader(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
    defended_target: Optional[InPlay] = None,
) -> None:
    """【相手のアタック時】 (defender=自リーダー 限定) (opp_attack_on_leader)。
    OP03-001 ポートガス・D・エース等。
    AttackLeader 時のみ発火 (= opp_attack と並行)。 me = defender 側。"""
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(
        state, me, "opp_attack_on_leader", effects_overlay,
        attacker=attacker, defended_target=defended_target,
    )
    _maybe_resolve(state)


def trigger_on_opp_attack_on_chara(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
    defended_target: Optional[InPlay] = None,
) -> None:
    """【相手のアタック時】 (defender=自キャラ 限定) (opp_attack_on_chara)。
    AttackCharacter 時のみ発火 (= opp_attack と並行)。 me = defender 側。"""
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(
        state, me, "opp_attack_on_chara", effects_overlay,
        attacker=attacker, defended_target=defended_target,
    )
    _maybe_resolve(state)


def trigger_on_opp_chara_ko(
    state: GameState,
    me: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「相手のキャラが KO された時」 (on_opp_chara_ko)。 KO した側 (me) の場の効果を発火。
    OP03-076 / EB04-044 等。 trigger_on_ko の後に呼ぶ。"""
    if not effects_overlay:
        return
    _enqueue_field_when(state, me, "on_opp_chara_ko", effects_overlay)
    _maybe_resolve(state)


def trigger_on_self_battle_ko(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「このキャラのバトルによって相手のキャラをKOした時」 (on_self_battle_ko)。
    me = attacker 所有者、 attacker = バトルで KO した アタッカー本人。 バトル KO の解決直後、
    attacker 本人の効果だけを self-scope で発火する (on_opp_chara_ko の全体発火と異なり、
    「このキャラのバトルによって」 を満たす)。 OPTCG では ブロッカー/防御側が アタッカーを KO
    することは無い (= バトル KO は常に アタッカー由来) ので attacker 限定で正しい。
    OP04-086 チンジャオ (2 ドロー 2 捨て) / OP02-094 イスカ (アクティブ化) 等。
    【ドン!!×N】 gate は eff の if/conditions に self_inplay_attached_dons_ge を置く。
    """
    if not effects_overlay:
        return
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    for idx, eff in enumerate(bundle.effects):
        if eff.get("when") != "on_self_battle_ko":
            continue
        if not eval_all_conditions(eff, state, me, attacker):
            continue
        cost = eff.get("cost", {})
        if cost.get("once_per_turn"):
            key = f"_self_battle_ko_{attacker.instance_id}"
            if key in me.once_per_turn_used:
                continue
            me.once_per_turn_used.add(key)
            # canonical mirror (Rust 同期用、 判定は once_per_turn_used のまま = 挙動不変)。
            attacker.mark_event_once("on_self_battle_ko", idx)
        for prim in eff.get("do", []):
            execute_effect(prim, state, me, opp, attacker)
    _maybe_resolve(state)


def trigger_on_self_rested(
    state: GameState,
    me: Player,
    opp: Player,
    rested_ip: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「このキャラがレストになった時」 (on_self_rested)。 me = rested_ip 所有者。
    OP14-027 シャンクス等。 rest primitive 内 / AttackLeader/AttackCharacter 後で発火。
    """
    if not effects_overlay:
        return
    bundle = effects_overlay.get(rested_ip.card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "on_self_rested":
            continue
        if not eval_all_conditions(eff, state, me, rested_ip):
            continue
        cost = eff.get("cost", {})
        if cost.get("once_per_turn"):
            key = f"_self_rested_{rested_ip.instance_id}"
            if key in me.once_per_turn_used:
                continue
            me.once_per_turn_used.add(key)
        for prim in eff.get("do", []):
            execute_effect(prim, state, me, opp, rested_ip)


def trigger_on_self_draw_non_draw_phase(
    state: GameState,
    me: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「自分がドローフェイズ以外でカードを引いた時」 (on_self_draw_non_draw_phase)。 OP05-053。
    me = 引いた player。 場の各キャラの on_self_draw_non_draw_phase を発火。"""
    if not effects_overlay:
        return
    for ip in list(me.characters):
        bundle = effects_overlay.get(ip.card.card_id)
        if bundle is None:
            continue
        for idx, eff in enumerate(bundle.effects):
            if eff.get("when") != "on_self_draw_non_draw_phase":
                continue
            if not eval_all_conditions(eff, state, me, ip):
                continue
            cost = eff.get("cost", {})
            if cost.get("once_per_turn"):
                key = f"_self_draw_nondp_{ip.instance_id}"
                if key in me.once_per_turn_used:
                    continue
                me.once_per_turn_used.add(key)
                # canonical mirror (Rust 同期用、 判定は上の once_per_turn_used のまま = 挙動不変)。
                ip.mark_event_once("on_self_draw_non_draw_phase", idx)
            for prim in eff.get("do", []):
                execute_effect(prim, state, me, opp, ip)


def trigger_on_self_don_attached(
    state: GameState,
    me: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「このリーダーか自分のキャラにドンが付与された時」 (on_self_don_attached)。 OP02-002。
    me = ドン付与した player。 場の各キャラ/リーダーの on_self_don_attached を発火。"""
    if not effects_overlay:
        return
    for ip in [me.leader, *list(me.characters)]:
        bundle = effects_overlay.get(ip.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "on_self_don_attached":
                continue
            if not eval_all_conditions(eff, state, me, ip):
                continue
            for prim in eff.get("do", []):
                execute_effect(prim, state, me, opp, ip)


def trigger_on_self_battled(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「このキャラが相手のキャラとバトルした(バトル終了時)」 (on_self_battled)。
    me = attacker 所有者。 ST02-010 (自身アクティブ化) 等。 char vs char バトル後に発火。
    """
    if not effects_overlay:
        return
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    for idx, eff in enumerate(bundle.effects):
        if eff.get("when") != "on_self_battled":
            continue
        if not eval_all_conditions(eff, state, me, attacker):
            continue
        cost = eff.get("cost", {})
        if cost.get("once_per_turn"):
            key = f"_self_battled_{attacker.instance_id}"
            if key in me.once_per_turn_used:
                continue
            me.once_per_turn_used.add(key)
            # canonical mirror (Rust 同期用、 判定は once_per_turn_used のまま = 挙動不変)。
            attacker.mark_event_once("on_self_battled", idx)
        for prim in eff.get("do", []):
            execute_effect(prim, state, me, opp, attacker)


def trigger_on_self_hand_discarded(
    state: GameState,
    me: Player,
    opp: Player,
    source_inplay: Optional[InPlay],
    discard_count: int,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「自分の手札からカードが捨てられた時」 (on_self_hand_discarded)。
    OP12-040 クザン 等。 actor (= 効果発動者) 視点で発火。
    source_inplay = 効果 source カード (= 「特徴《海軍》を持つカード」 判定用)。
    discard_count = 捨てた枚数 (= draw 枚数の動的 N)。
    """
    if discard_count <= 0:
        return
    # このターン中に効果で手札が捨てられた持続フラグ (= ST33-004 コスト-3 条件、 _reset_turn_buff でクリア)。
    me.hand_discarded_by_effect_this_turn = True
    if not effects_overlay:
        return
    state.last_discard_source_inplay = source_inplay
    state.last_discard_count = discard_count
    _enqueue_field_when(state, me, "on_self_hand_discarded", effects_overlay)
    _maybe_resolve(state)
    state.last_discard_source_inplay = None
    state.last_discard_count = 0


def trigger_on_self_chara_leave_by_self_effect(
    state: GameState,
    actor: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「キャラが自分の効果で場を離れた時」 (on_self_chara_leave_by_self_effect)。
    actor = 効果発動者 (= me)。 KO / return_to_hand / return_to_deck_bottom 等で発火。
    OP07-038 ボア・ハンコック 等。 victim 視点ではなく effect 発動者視点。

    呼び出し箇所: 効果 primitive で実際に 1 体以上が場を離れた直後 (= victim が居る場合のみ)。
    """
    if not effects_overlay:
        return
    _enqueue_field_when(
        state, actor, "on_self_chara_leave_by_self_effect", effects_overlay
    )
    _maybe_resolve(state)


def trigger_on_opp_chara_returned_to_hand_by_self_effect(
    state: GameState,
    actor: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「相手のキャラが自分の効果で持ち主の手札に戻った時」
    (on_opp_chara_returned_to_hand_by_self_effect)。
    actor = 効果発動者 (= me)。 return_to_hand / return_to_hand_multi 等 で 相手の キャラ
    が 手札 に 戻った 直後 に actor の 場 で 発火。
    EB02-023 クロコダイル 等。 trigger_on_self_chara_leave_by_self_effect と 同時 に 呼ぶ
    (= 同じ primitive の 後 で 別軸 観点 の trigger)。
    """
    if not effects_overlay:
        return
    _enqueue_field_when(
        state, actor, "on_opp_chara_returned_to_hand_by_self_effect", effects_overlay
    )
    _maybe_resolve(state)


def trigger_on_self_chara_ko(
    state: GameState,
    victim_owner: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
    victim_card: Optional[CardDef] = None,
) -> None:
    """「自分の(特徴X を持つ)キャラが KO された時」 (on_self_chara_ko)。
    KO された側 (= victim_owner) の場の効果を発火。 OP10-042 ウソップ系等で利用。

    on_opp_chara_ko (KO した側の発火) と対称: on_self_chara_ko は KO された側の発火。
    条件付きフィルタ (例: 「特徴X を持つキャラが KO された場合」) は overlay 側の if で
    記述するので、 トリガー自体は無条件発火 (フィルタは eval_condition で判定)。
    trigger_on_ko / trigger_on_opp_chara_ko と並行して呼ぶ。

    victim_card: KO された victim カード (= 「元々のパワー X 以上」 等 payload-aware 条件で利用)。
    state.last_chara_ko_victim_card に一時保存され、 eval_condition の victim_* 条件で読まれる。"""
    if not effects_overlay:
        return
    # victim_card 未指定時は直前の trigger_on_ko が設定した context を保持する。
    # (= None で clobber すると victim_truly_original_power_ge / victim_feature_in 等が
    #  常に空振りし、 OP13-002 エース / OP14-041 ハンコック 等の「元々パワーN以上のキャラが
    #  KO された時」 効果が effect-KO / battle-KO の双方で発火しなくなる engine bug を防ぐ)
    if victim_card is not None:
        state.last_chara_ko_victim_card = victim_card
    _enqueue_field_when(state, victim_owner, "on_self_chara_ko", effects_overlay)
    _maybe_resolve(state)
    state.last_chara_ko_victim_card = None


def trigger_on_self_chara_leave_by_opp_effect(
    state: GameState,
    victim_owner: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
    victim_card: Optional[CardDef] = None,
) -> None:
    """「自分の(特徴X を持つ)キャラが相手の効果で場を離れた時」 (on_self_chara_leave_by_opp_effect)。
    KO 以外の離脱経路 (return_to_hand / return_to_deck_bottom 等、 相手効果による bounce/deck 戻し)
    から発火。 KO は on_self_chara_ko が別に発火するので、 OP09-080 サニー号 等は両 when を持つ。
    victim_owner = 離れた側 (= 効果を持つ側)、 victim_card は victim_feature_in 条件で読まれる。"""
    if not effects_overlay:
        return
    if victim_card is not None:
        state.last_chara_ko_victim_card = victim_card
    _enqueue_field_when(state, victim_owner, "on_self_chara_leave_by_opp_effect", effects_overlay)
    _maybe_resolve(state)
    state.last_chara_ko_victim_card = None


def trigger_opp_event_or_trigger_fired(
    state: GameState,
    opp_player: Player,
    actor_player: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「相手がイベントか【トリガー】を発動した時」 (opp_event_or_trigger_fired)。
    opp_player = 効果保有側 (= イベント/トリガーを「相手として」見る側)。
    actor_player = イベントを発動 / トリガーを発火した側 (= opp_player から見た相手)。
    OP11-102 ケイミー 等。

    呼び出し箇所:
      - trigger_main_event 内 (= EVENT を発動した側の opp 側で発火)
      - trigger_lifecard_trigger 内 (= TRIGGER 発動した defender 側の opp 側で発火)
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, opp_player, "opp_event_or_trigger_fired", effects_overlay)
    _maybe_resolve(state)


def trigger_opp_event_played(
    state: GameState,
    opp_player: Player,
    actor_player: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「相手がイベントを発動した時」 (opp_event_played)。 opp_event_or_trigger_fired との違いは
    **ライフの【トリガー】発動では発火しない** こと。

    公式 (cardqa_op_11 = OP11-012 フランキー / OP06-044 ギオン / OP01-004 ウソップ 等):
      「自分のターン中に、 相手がイベントの【トリガー】効果を発動した時、 このキャラの効果を
        発動できますか？」 → 「いいえ、 できません」。
      = 「相手がイベントを発動した時」 は 相手が **イベントカードを発動** した時のみ (手札/カウンター)
        であり、 ライフに置かれたイベントの【トリガー】キーワードを発動しても発火しない。

    したがって呼び出しは event-play 経路 (trigger_main_event / trigger_counter_event) のみ。
    ライフ【トリガー】経路 (trigger_lifecard_trigger) は opp_event_or_trigger_fired だけを撃つ
    (= OP11-102 ケイミー のように 「イベントか【トリガー】」 と書かれたカードだけが反応する)。
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, opp_player, "opp_event_played", effects_overlay)
    _maybe_resolve(state)


def trigger_self_event_played(
    state: GameState,
    actor_player: Player,
    opp_player: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「自分がイベントを発動した時」 (on_self_event_played)。
    actor_player = イベントを発動した側 (= 効果保有側)。
    OP04-053 ページワン (【ドン!!×1】【ターン1回】自分がイベントを発動した時、 ...) 等。

    呼び出し箇所:
      - trigger_main_event 内 (= EVENT を発動した側の自身の場で発火)
      - trigger_counter_event 内 (= カウンターイベント発動側でも公式 8-1-2 上は同じ「発動」)
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, actor_player, "on_self_event_played", effects_overlay)
    _maybe_resolve(state)


def trigger_on_self_don_returned_to_deck(
    state: GameState,
    owner: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
    count: int = 1,
) -> None:
    """「自分の場のドンがドンデッキに戻された時」 (on_self_don_returned_to_deck)。
    OP06-042 / OP06-076 / OP04-058 / OP12-040 等が登録する場の効果を発火。
    pay_don / return_self_don_to_deck 等の直後に呼ぶ。"""
    if not effects_overlay:
        return
    state.last_returned_don_count = int(count)
    _enqueue_field_when(state, owner, "on_self_don_returned_to_deck", effects_overlay)
    _maybe_resolve(state)


def trigger_on_opp_blocker_use(
    state: GameState,
    me: Player,
    opp: Player,
    blocker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """「相手が【ブロッカー】を発動した時」 (on_opp_blocker_use)。 アタッカー側 (= me) の場の
    効果を発火 (OP09-118 速攻ルフィ等)。"""
    if not effects_overlay:
        return
    _enqueue_field_when(state, me, "on_opp_blocker_use", effects_overlay)
    _maybe_resolve(state)


def trigger_on_block(
    state: GameState,
    me: Player,
    opp: Player,
    blocker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【ブロック時】(on_block) を enqueue (10-2-15-1)。

    me = ブロッカーを発動した側 (アタックを受けている側)。
    """
    if not effects_overlay:
        return
    bundle = effects_overlay.get(blocker.card.card_id)
    if bundle is None:
        return
    if not any(e.get("when") == "on_block" for e in bundle.effects):
        return
    me_idx = state.players.index(me)
    enqueue_event(
        state,
        when="on_block",
        owner_idx=me_idx,
        source_card_id=blocker.card.card_id,
        source_iid=blocker.instance_id,
    )
    _maybe_resolve(state)


def try_replace_ko(
    state: GameState,
    owner: Player,
    opp: Player,
    victim: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
    by_opp_effect: bool,
    leave_kind: str = "ko",
) -> bool:
    """場を離れる直前の置換効果 (when="replace_ko" / "replace_leave") を試行。
    1 つでも発動・成功すれば True を返し、本来の離脱をキャンセルさせる。

    overlay 例:
      "OP15-003": [{"when": "replace_ko",
                    "if": {"target": "self"},
                    "do": [{"trash_self_hand_random": 1}]}]
      "OP15-003_p1": [{"when": "replace_ko",
                    "if": {"target": "self"},
                    "cost": [{"discard_hand_with_filter":
                              {"filter": {"category": "CHARACTER", "power_le": 6000}, "count": 1}}]}]
      "OP12-027": [{"when": "replace_ko",
                    "if": {"target": "other_self_chara",
                           "target_attribute": "斬",
                           "target_cost_le": 5,
                           "by_opp_effect": true},
                    "do": [{"rest": "self"}]}]
      "OP12-053": [{"when": "replace_leave",
                    "if": {"target": "self", "by_opp_effect": true},
                    "cost": [{"discard_hand_with_filter":
                              {"filter": {}, "count": 1}}]}]

    leave_kind: "ko" | "return_to_hand" | "return_to_deck_bottom"
      - "ko" のみ replace_ko に該当 (= 既存挙動)
      - replace_leave (= 「場を離れる場合」) は KO 含む全離脱種別で発火
    """
    if not effects_overlay:
        return False
    # victim 所有者の場 (リーダー + キャラ + ステージ) を走査
    candidates: list[InPlay] = (
        [owner.leader] + list(owner.characters) + list(owner.stages)
    )
    for inplay in candidates:
        # 再入防止: この holder の置換 do が実行中なら、 その do が誘発した離脱で
        # 同じ holder の replace_leave を再発火させない (= 無限ループ防止)。
        # 例: OP15-052 レオ の replace_leave do が return_to_deck_bottom で自キャラを戻す →
        # その離脱が再び レオ の replace_leave を誘発 → 無限ループ (2026-06-05 aggressive fuzz 検出)。
        if inplay.instance_id in getattr(state, "_replace_leave_active_holders", ()):
            continue
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            when = eff.get("when")
            # replace_ko は KO 限定、 replace_leave は KO + return_to_hand + return_to_deck_bottom
            if when == "replace_ko":
                if leave_kind != "ko":
                    continue
            elif when == "replace_leave":
                # 公式 「場を離れる場合」 はあらゆる離脱種別に該当
                pass
            else:
                continue
            if not _replace_ko_match(eff.get("if", {}), inplay, victim, by_opp_effect):
                continue
            # 通常の eval_condition (leader_feature 等) も適用
            extra_cond = {
                k: v for k, v in eff.get("if", {}).items()
                if k not in ("target", "target_attribute", "target_cost_le",
                             "target_cost_ge",
                             "target_truly_original_cost_le",
                             "target_truly_original_cost_ge",
                             "target_power_le", "target_power_ge",
                             "target_truly_original_power_le",
                             "target_truly_original_power_ge",
                             "target_truly_original_power_eq",
                             "target_feature", "target_feature_contains",
                             "target_color", "target_name_exclude",
                             "target_name", "target_rested",
                             "by_opp_effect", "by_battle")
            }
            if extra_cond and not eval_condition(extra_cond, state, owner, inplay):
                continue
            # optional gate (= 公式 「〜してもよい」 / 「〜することができる」)。
            # owner が human の 場合 は pending_choice modal を 立てて 人間 判断 を 待つ。
            # 既 declined (= 同 victim を 「使わない」 と 答えた) なら 再 prompt しない。
            if eff.get("optional", False):
                owner_idx = state.players.index(owner)
                if (
                    state.human_player_idx is not None
                    and owner_idx == state.human_player_idx
                    and state.pending_choice is None
                ):
                    declined = getattr(state, "_replace_ko_declined_iids", set())
                    if victim.instance_id in declined:
                        # 同 victim を 既 skip 選択 済 → 通常 KO 続行
                        continue
                    # cost 払える か 事前 check (= 払えないなら そもそも 選択 modal 出さない)
                    cost_specs_pre = eff.get("cost", [])
                    holder_card_id_pre = inplay.card.card_id
                    if cost_specs_pre and not _can_pay_replace_cost(
                        state, owner, cost_specs_pre, holder_card_id_pre, inplay
                    ):
                        continue
                    # do_spec / cost_specs を シリアライズ して pending_choice に 退避
                    state.pending_choice = {
                        "kind": "replace_ko_optional",
                        "victim_iid": victim.instance_id,
                        "victim_name": victim.card.name,
                        "holder_iid": inplay.instance_id,
                        "holder_name": inplay.card.name,
                        "owner_idx": owner_idx,
                        "when": when,
                        "do_spec": eff.get("do", []),
                        "cost_specs": cost_specs_pre,
                        "leave_kind": leave_kind,
                        "by_opp_effect": by_opp_effect,
                    }
                    state.push_log(
                        f"  離脱置換 確認 待ち: {inplay.card.name} の 効果 で "
                        f"{victim.card.name} の {leave_kind} を 代替 する?"
                    )
                    # halt — caller 側 で pending_choice 検出 → KO は skip (= 再開 時 解決)
                    return True
            # cost フィールド対応 (任意): cost が払えない場合は置換不可。
            # spec: {"cost": [<primitive>...]} を payability check で消費する。
            cost_specs = eff.get("cost", [])
            holder_card_id = inplay.card.card_id
            if cost_specs:
                if not _can_pay_replace_cost(state, owner, cost_specs, holder_card_id, inplay):
                    continue
                _pay_replace_cost(state, owner, cost_specs, holder_card_id, inplay)
            state.push_log(
                f"  離脱置換 ({when}): {victim.card.name} → {inplay.card.name} の効果で代替"
            )
            # victim target spec ("victim") のため state に 一時保存。
            # OP05-001 等 「代わりに victim 自身に power -1000」 系で利用。
            prev_replace_victim = getattr(state, "last_replace_victim", None)
            state.last_replace_victim = victim
            # この holder を「置換 do 実行中」 にマーク (= do が誘発した離脱で 自己再発火しない)。
            active = set(getattr(state, "_replace_leave_active_holders", set()))
            active.add(inplay.instance_id)
            state._replace_leave_active_holders = active
            # ⭐ 置換 do の actor は holder の owner。 owner が human ならその人が target_pick、
            # AI なら human modal を出さない (= forced=-1)。 これをしないと「相手 (AI) の置換の
            # target_pick が自分 (human) に出て、 human 視点で解決され ownership が反転 →
            # 自陣 return が opp return (by_opp_effect=True) になり 置換が自己再誘発 → 無限ループ」
            # (OP15-052 レオ、 2026-06-05 aggressive fuzz 検出)。
            owner_idx = state.players.index(owner)
            prev_forced = getattr(state, "forced_human_actor_idx", None)
            state.forced_human_actor_idx = (
                owner_idx if owner_idx == state.human_player_idx else -1
            )
            try:
                for primitive in eff.get("do", []):
                    execute_effect(primitive, state, owner, opp, inplay)
            finally:
                state.last_replace_victim = prev_replace_victim
                state.forced_human_actor_idx = prev_forced
                cur = set(getattr(state, "_replace_leave_active_holders", set()))
                cur.discard(inplay.instance_id)
                state._replace_leave_active_holders = cur
            return True
    return False


def try_replace_rest(
    state: GameState,
    victim_owner: Player,
    actor: Player,
    victim: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
    by_opp_chara_effect: bool,
) -> bool:
    """rest 効果が victim にかかる前の置換効果 (when="replace_rest") を試行。
    1 つでも発動・成功すれば True を返し、本来の rest をキャンセルさせる。

    PRB02-006 ロロノア・ゾロ:
      「【相手のターン中】このキャラが相手のキャラの効果でレストになる場合、
       代わりに自分の他のキャラ1枚をレストにできる」

    overlay 例:
      "PRB02-006": [{"when": "replace_rest",
                     "if": {"target": "self", "by_opp_chara_effect": true, "opp_turn": true},
                     "do": [{"rest": "other_self_chara"}]}]

    target_clause: "self" のみサポート (= victim 自身が overlay 保有者)。
    by_opp_chara_effect: True なら 「相手のキャラの効果で」 限定。
    """
    if not effects_overlay:
        return False
    bundle = effects_overlay.get(victim.card.card_id)
    if bundle is None:
        return False
    for eff in bundle.effects:
        if eff.get("when") != "replace_rest":
            continue
        if_spec = eff.get("if", {})
        target_clause = if_spec.get("target", "self")
        if target_clause != "self":
            continue
        if if_spec.get("by_opp_chara_effect") and not by_opp_chara_effect:
            continue
        # 残り eval_condition (opp_turn / self_turn / leader_feature 等)
        extra_cond = {
            k: v for k, v in if_spec.items()
            if k not in ("target", "by_opp_chara_effect", "by_opp_effect")
        }
        if extra_cond and not eval_condition(extra_cond, state, victim_owner, victim):
            continue
        cost_specs = eff.get("cost", [])
        holder_card_id = victim.card.card_id
        if cost_specs:
            if not _can_pay_replace_cost(state, victim_owner, cost_specs, holder_card_id, victim):
                continue
            _pay_replace_cost(state, victim_owner, cost_specs, holder_card_id, victim)
        state.push_log(f"  レスト置換: {victim.card.name} の効果で発動")
        # 置換 do の actor は victim_owner (= レスト される側の持ち主)。 victim_owner が human
        # ならその人が target_pick、 AI なら human modal を出さない (= forced=-1)。 これをしないと
        # replace_rest の do (= other_self_chara を rest) の選択が turn_player (= 相手) 文脈で出て
        # victim_owner が選べない (= replace_leave 無限ループと同類の actor 文脈バグ、 2026-06-05)。
        owner_idx = state.players.index(victim_owner)
        prev_forced = getattr(state, "forced_human_actor_idx", None)
        state.forced_human_actor_idx = (
            owner_idx if owner_idx == state.human_player_idx else -1
        )
        try:
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, victim_owner, actor, victim)
        finally:
            state.forced_human_actor_idx = prev_forced
        return True
    return False


def _can_pay_replace_cost(
    state: GameState, me: Player, cost_specs: list[dict], holder_card_id: str | None = None,
    holder_inplay: "InPlay | None" = None,
) -> bool:
    """replace_ko / replace_leave の cost 配列が払えるかチェック。 R3 拡張。

    holder_card_id を 渡すと once_per_turn の 使用 済み 判定 が 効く (= 既に 同一 ターン に
    発動済 なら 払えない 扱い)。 holder_inplay は trash_self (= 自身をトラッシュへ) 用。
    """
    for cs in cost_specs:
        if "trash_self" in cs:
            # 「代わりにこのキャラをトラッシュに置き」 (OP08-045 サッチ 等)。
            # holder (= 効果保有キャラ) を場からトラッシュへ移す = holder が場に在れば常に払える。
            if not bool(cs["trash_self"]):
                continue
            if holder_inplay is None or holder_inplay not in me.characters:
                return False
        elif "discard_hand_with_filter" in cs:
            df_spec = cs["discard_hand_with_filter"]
            if "filter" in df_spec:
                d_filt = df_spec.get("filter", {})
            else:
                d_filt = {k: v for k, v in df_spec.items() if k != "count"}
            d_count = int(df_spec.get("count", 1))
            matching = [c for c in me.hand if _matches_filter(c, d_filt)]
            if len(matching) < d_count:
                return False
        elif "trash_self_hand_random" in cs:
            n = int(cs["trash_self_hand_random"])
            if len(me.hand) < n:
                return False
        elif "discard_hand" in cs:
            # 単純 「手札 N 枚捨てる」 (count に整数)
            n = int(cs["discard_hand"])
            if len(me.hand) < n:
                return False
        elif "rest_self_leader_or_stage_filtered" in cs:
            # 「代わりに自分のリーダーかステージ1枚をレストにできる」 (OP04-082/OP11-110)。
            # リーダー (アクティブ) か filter 一致ステージ が rest 可能か。
            rl_spec = cs["rest_self_leader_or_stage_filtered"]
            rl_filt = rl_spec.get("filter", {}) if isinstance(rl_spec, dict) else {}
            pool = ([me.leader] if me.leader is not None else []) + list(me.stages)
            if not any(not ip.rested and _matches_filter_ip(ip, rl_filt) for ip in pool):
                return False
        elif "return_self_don_to_deck" in cs:
            # 「代わりに自分の場のドン1枚をドンデッキに戻す」 (EB04-031)。 場にドン必要。
            n = int(cs["return_self_don_to_deck"]) if not isinstance(cs["return_self_don_to_deck"], dict) else 1
            if (me.don_active + me.don_rested) < n:
                return False
        elif "rest_self_cards" in cs:
            # 「代わりに自分のカード N 枚をレストにできる」 (OP16-033 モーリー 等)。
            # 自リーダー/キャラの アクティブ が N 枚以上 あれば 払える。
            rs_spec = cs["rest_self_cards"]
            n = int(rs_spec.get("count", 1)) if isinstance(rs_spec, dict) else int(rs_spec)
            actives = [me.leader] + list(me.characters)
            actives = [ip for ip in actives if ip is not None and not ip.rested]
            if len(actives) < n:
                return False
        elif "mill_self_life_to_trash" in cs:
            # 「代わりに自分のライフの上か下から N 枚をトラッシュに置く」 (ST09-010 エース 等)。
            # 置換の代償がライフ 1 枚のトラッシュ送りなので、 ライフが N 枚未満なら置換不能。
            n_spec = cs["mill_self_life_to_trash"]
            n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
            if len(me.life) < n:
                return False
        elif "rest_self_don" in cs:
            # 「代わりに自分の(アクティブの)ドン‼ N 枚をレストにできる」 (P-111 ロビン /
            # OP10-074 ピーカ)。 公式: 場にアクティブのドンが無い/足りない場合は この置換を
            # 行えない (= 通常どおり場を離れる)。 cardqa_ (P-111): 「自分の場にアクティブの
            # ドン!!がない場合、…ドン1枚をレストにできますか？」→「いいえ、できません。」
            # レストにできるのはアクティブのドンなので、 アクティブが N 枚未満なら置換不能。
            n_spec = cs["rest_self_don"]
            n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
            if me.don_active < n:
                return False
        elif "once_per_turn" in cs:
            # 【ターン1回】 — 同一ターン内 同一 holder の 同一 replace 発動 を 1 回 に 制限。
            # holder_card_id があれば per-card per-turn フラグ で 管理。
            if not bool(cs["once_per_turn"]):
                continue
            if holder_card_id is not None:
                key = f"replace_opt::{holder_card_id}"
                if key in me.once_per_turn_used:
                    return False
        else:
            # 未対応 cost は支払不能扱い (= 公式 4-10 解釈不能→False)
            return False
    return True


def _pay_replace_cost(
    state: GameState, me: Player, cost_specs: list[dict], holder_card_id: str | None = None,
    holder_inplay: "InPlay | None" = None,
) -> None:
    """replace_ko / replace_leave の cost 配列を実行 (消費)。"""
    for cs in cost_specs:
        if "once_per_turn" in cs and bool(cs["once_per_turn"]):
            # 【ターン1回】 使用済みフラグ (+ canonical 並行記録で Rust bit-match)
            if holder_card_id is not None:
                me.once_per_turn_used.add(f"replace_opt::{holder_card_id}")
                if holder_card_id not in me.replace_opt_used_cards:
                    me.replace_opt_used_cards.append(holder_card_id)
                    me.replace_opt_used_cards.sort()
            continue
        if "mill_self_life_to_trash" in cs:
            # 「代わりに自分のライフの上か下から N 枚をトラッシュに置く」 (ST09-010 エース 等)。
            # ライフ移動なのでライフトリガーは発動しない (= 効果でのライフ移動 10-1-5)。
            n_spec = cs["mill_self_life_to_trash"]
            n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
            for _ in range(n):
                if not me.life:
                    break
                me.trash.append(me.life.pop(0))
            state.push_log(f"  離脱置換コスト: 自ライフ {n} 枚をトラッシュへ")
            continue
        if "rest_self_don" in cs:
            # 「代わりに自分の(アクティブの)ドン‼ N 枚をレストにできる」 (P-111 / OP10-074)。
            # アクティブドン N 枚をレストへ (= execute_effect の rest_self_don と同 semantics)。
            n_spec = cs["rest_self_don"]
            n = int(n_spec) if not isinstance(n_spec, dict) else int(n_spec.get("amount", 1))
            actual = min(me.don_active, n)
            me.don_active -= actual
            me.don_rested += actual
            state.push_log(f"  離脱置換コスト: 自アクティブドン {actual} 枚をレストへ")
            continue
        if "trash_self" in cs:
            # 「代わりにこのキャラをトラッシュに置き」 — holder を場からトラッシュへ移動。
            if not bool(cs["trash_self"]):
                continue
            if holder_inplay is not None and holder_inplay in me.characters:
                me.characters.remove(holder_inplay)
                me.trash.append(holder_inplay.card)
                if holder_inplay.attached_dons > 0:
                    me.don_rested += holder_inplay.attached_dons
                state.push_log(f"  離脱置換: {holder_inplay.card.name} をトラッシュへ")
            continue
        if "discard_hand_with_filter" in cs:
            df_spec = cs["discard_hand_with_filter"]
            if "filter" in df_spec:
                d_filt = df_spec.get("filter", {})
            else:
                d_filt = {k: v for k, v in df_spec.items() if k != "count"}
            d_count = int(df_spec.get("count", 1))
            discarded = 0
            new_hand = []
            for c in me.hand:
                if discarded < d_count and _matches_filter(c, d_filt):
                    me.trash.append(c)
                    discarded += 1
                    state.push_log(f"  離脱置換コスト: 手札捨て (filter) → {c.name}")
                else:
                    new_hand.append(c)
            me.hand = new_hand
        elif "trash_self_hand_random" in cs:
            n = int(cs["trash_self_hand_random"])
            for _ in range(n):
                if not me.hand:
                    break
                # 自手札の discard はプレイヤーが選ぶ(公式)。 AI は最悪札から(random で value を薄めない)。
                me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
                state.push_log(f"  離脱置換コスト: 手札ランダム1枚捨て")
        elif "discard_hand" in cs:
            n = int(cs["discard_hand"])
            for _ in range(n):
                if not me.hand:
                    break
                # AI 簡易: power 低 → cost 低い順に捨てる (最も惜しくない)
                me.hand.sort(key=lambda c: (c.power, c.cost))
                me.trash.append(me.hand.pop(0))
                state.push_log(f"  離脱置換コスト: 手札 1 枚捨て")
        elif "rest_self_leader_or_stage_filtered" in cs:
            rl_spec = cs["rest_self_leader_or_stage_filtered"]
            rl_filt = rl_spec.get("filter", {}) if isinstance(rl_spec, dict) else {}
            pool = list(me.stages) + ([me.leader] if me.leader is not None else [])
            for ip in pool:  # ステージ優先で rest (リーダー温存)
                if not ip.rested and _matches_filter_ip(ip, rl_filt):
                    ip.rested = True
                    state.push_log(f"  離脱置換コスト: 自レスト {ip.card.name}")
                    break
        elif "return_self_don_to_deck" in cs:
            n = int(cs["return_self_don_to_deck"]) if not isinstance(cs["return_self_don_to_deck"], dict) else 1
            taken = min(n, me.don_active)
            me.don_active -= taken
            me.don_remaining_in_deck += taken
            if taken < n:
                more = min(n - taken, me.don_rested)
                me.don_rested -= more
                me.don_remaining_in_deck += more
            state.push_log(f"  離脱置換コスト: ドン{n}をドンデッキへ")
        elif "rest_self_cards" in cs:
            # 「代わりに自分のカード N 枚をレストにできる」 (OP16-033 モーリー 等)。
            # AI 簡易: アクティブの power 低い順に N 枚レスト (primitive と同方針)。
            rs_spec = cs["rest_self_cards"]
            n = int(rs_spec.get("count", 1)) if isinstance(rs_spec, dict) else int(rs_spec)
            actives = [me.leader] + list(me.characters)
            actives = [ip for ip in actives if ip is not None and not ip.rested]
            actives.sort(key=lambda ip: ip.power)
            for ip in actives[:n]:
                ip.rested = True
                state.push_log(f"  離脱置換コスト: 自カードレスト {ip.card.name}")


def _replace_ko_match(
    cond: dict, holder: InPlay, victim: InPlay, by_opp_effect: bool
) -> bool:
    """replace_ko の対象条件を判定。"""
    target = cond.get("target", "self")

    # by_opp_effect 条件 (cond で True を要求した時、効果由来でなければ不適用)
    requires_opp_effect = bool(cond.get("by_opp_effect", False))
    if requires_opp_effect and not by_opp_effect:
        return False
    # by_battle 条件 (cond で True を要求した時、 バトル由来でなければ不適用 = 効果KO除外)
    requires_battle = bool(cond.get("by_battle", False))
    if requires_battle and by_opp_effect:
        return False

    if target == "self":
        # holder 自身が victim
        if holder is not victim:
            return False
    elif target == "other_self_chara":
        # holder と異なる、同陣営のキャラ
        if holder is victim:
            return False
    elif target == "any_self_chara":
        # 自陣のキャラ全て (holder 自身も含む)
        pass
    else:
        return False

    # フィルタ: target_attribute / target_cost_le / target_power_le / target_feature
    if "target_attribute" in cond:
        # 「属性(X)を持つ」 = substring 一致 (多属性「斬/打」対応、 完全一致は取りこぼしバグ)
        if str(cond["target_attribute"]) not in (victim.card.attribute or ""):
            return False
    # ⭐ 公式 4-9 が定義するのは 「**元々の**」 の意味 (= カードに表記された数値) だけで、
    #   素の 「コスト/パワー N 以下」 を印刷値にする根拠ではない。 素の表記は現在値
    #   (cardqa: 「元々のパワーが6000以下のキャラが効果で7000以上となっている場合…KOできますか？」
    #    → 「いいえ。**現在のパワー**が6000以下のキャラをKOできます」)。
    #   よって置換条件も `target_*` = 現在値 / `target_truly_original_*` = 印刷値 に分ける。
    if "target_cost_le" in cond:
        if victim.base_cost > int(cond["target_cost_le"]):
            return False
    if "target_cost_ge" in cond:
        if victim.base_cost < int(cond["target_cost_ge"]):
            return False
    if "target_truly_original_cost_le" in cond:
        if victim.card.cost > int(cond["target_truly_original_cost_le"]):
            return False
    if "target_truly_original_cost_ge" in cond:
        if victim.card.cost < int(cond["target_truly_original_cost_ge"]):
            return False
    if "target_power_le" in cond:
        if victim.power > int(cond["target_power_le"]):
            return False
    if "target_power_ge" in cond:
        if victim.power < int(cond["target_power_ge"]):
            return False
    if "target_truly_original_power_le" in cond:
        # 公式 4-9: 「元々のパワー X 以下」は永続効果で変更されない CardDef オリジナル値で判定
        if victim.truly_original_power > int(cond["target_truly_original_power_le"]):
            return False
    if "target_truly_original_power_ge" in cond:
        if victim.truly_original_power < int(cond["target_truly_original_power_ge"]):
            return False
    if "target_truly_original_power_eq" in cond:
        if victim.truly_original_power != int(cond["target_truly_original_power_eq"]):
            return False
    if "target_feature" in cond:
        if cond["target_feature"] not in victim.card.features:
            return False
    if "target_feature_contains" in cond:
        # 部分一致 (= 公式「『X』を含む特徴」)
        feat = cond["target_feature_contains"]
        if not any(feat in f for f in victim.card.features):
            return False
    if "target_color" in cond:
        if cond["target_color"] not in victim.card.color:
            return False
    if "target_name_exclude" in cond:
        excl = cond["target_name_exclude"]
        if isinstance(excl, str):
            excl = [excl]
        if victim.card.name in excl:
            return False
    if "target_name" in cond:
        # 特定 カード名 限定 (= OP09-012 「自分のキャラの「ボンク・パンチ」 が KO される場合」 等)
        name = cond["target_name"]
        if isinstance(name, str):
            if victim.card.name != name:
                return False
        elif isinstance(name, list):
            if victim.card.name not in name:
                return False
    if "target_rested" in cond:
        # victim が レスト 状態 か (= 公式 「自分のレストのキャラが KO される場合」)
        if bool(cond["target_rested"]) != victim.rested:
            return False
    return True


def trigger_on_ko(
    state: GameState,
    owner: Player,
    opp: Player,
    ko_card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
    by_opp_effect: bool = False,
    victim_attached_don: int = 0,
    victim_effect_negated: bool = False,
) -> None:
    """【KO時】を enqueue。 ko_card は既にトラッシュへ (10-2-17-2)。
    source_iid=None: 場から既に消えているので、 _execute_event 内では self_inplay=None で実行。

    副作用: state.last_chara_ko_victim_card = ko_card を一時設定 (= 後続の
    trigger_on_self_chara_ko / trigger_on_opp_chara_ko で payload-aware 条件用に使われる)。

    by_opp_effect: True = 相手の効果由来 KO、 False = バトル / 自分の効果 / cost KO。
        eval_condition で `by_opp_effect` / `by_battle` 条件と突合される。
    victim_attached_don: KO された キャラに付与されていたドン枚数。 【ドン‼×N】【KO時】 の
        self_attached_don_ge 条件で 足し戻す (= source 不在で常に False になるのを防ぐ)。
    """
    # payload-aware 条件用 context を先に設定 (= trigger_on_self_chara_ko より先に呼ばれる場合に備える)
    state.last_chara_ko_victim_card = ko_card
    # このターン中の owner キャラ KO 数を加算 (= OP16-100 opp_chara_ko_this_turn 条件用)。
    # trigger_on_ko は全 KO 経路 (battle/効果/cost) の共通フックなので、 overlay 有無に依らず
    # bundle 早期 return より前で加算する (= vanilla キャラ KO も数える)。
    owner.chara_ko_taken_this_turn = int(getattr(owner, "chara_ko_taken_this_turn", 0) or 0) + 1
    # 公式 Q&A (cardqa_op_09 / op_10): 「効果を無効にされたキャラがKOされた場合、 そのキャラの
    # 持つ【KO時】効果は発動できますか？」 → 「いいえ、 できません」。
    # ⚠ on_ko は source が既に場外 (self_inplay=None) なので _execute_event の 効果無効 gate を
    #   通らない。 KO 直前の無効化状態を呼び出し側から渡してもらう (2026-08-04 実装)。
    #   chara_ko_taken_this_turn の加算は 「KO された」 事実なので gate より前に行う。
    if victim_effect_negated:
        state.push_log(f"  効果無効: {ko_card.name} の【KO時】 は発動されない")
        return
    bundle = effects_overlay.get(ko_card.card_id)
    if bundle is None:
        return
    if not any(e.get("when") == "on_ko" for e in bundle.effects):
        return
    owner_idx = state.players.index(owner)
    # KO時の付与ドンを退避 (= self_attached_don_ge が self_inplay=None で読む)。 cascade 安全に save/restore。
    prev_vdon = getattr(state, "_on_ko_victim_attached_don", 0)
    state._on_ko_victim_attached_don = int(victim_attached_don or 0)
    try:
        enqueue_event(
            state,
            when="on_ko",
            owner_idx=owner_idx,
            source_card_id=ko_card.card_id,
            source_iid=None,
            payload={"by_opp_effect": bool(by_opp_effect)},
        )
        _maybe_resolve(state)
    finally:
        state._on_ko_victim_attached_don = prev_vdon


def trigger_on_life_zero(
    state: GameState,
    owner: Player,
    opp: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """ライフが 0 になった瞬間のトリガー。 リーダーの when="on_life_zero" を発火。
    OP05-098 紫エネル等の「ライフが0枚になった時」効果用。
    """
    if not effects_overlay:
        return
    leader = owner.leader
    bundle = effects_overlay.get(leader.card.card_id)
    if bundle is None:
        return
    if not any(e.get("when") == "on_life_zero" for e in bundle.effects):
        return
    owner_idx = state.players.index(owner)
    enqueue_event(
        state,
        when="on_life_zero",
        owner_idx=owner_idx,
        source_card_id=leader.card.card_id,
        source_iid=leader.instance_id,
    )
    _maybe_resolve(state)


def trigger_lifecard_trigger(
    state: GameState,
    defender: Player,
    attacker_player: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
    auto_fire: bool = True,
) -> bool:
    """ライフカードの【トリガー】を enqueue。 発動した場合 True (カードはトラッシュへ)、
    発動しなかった (or 発動できなかった) 場合 False (カードは手札へ)。

    公式 10-1-5: プレイヤーは発動するか選べる。 auto_fire は呼び出し側で判定済み。
    fire するなら enqueue + 即時 resolve (= life ヒット 1 回ごとに resolve、 Q36 に従う)。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return False
    trigger_effects = [e for e in bundle.effects if e.get("when") == "trigger"]
    if not trigger_effects:
        return False
    if not auto_fire:
        return False
    # 発動可能な効果が 1 つでもあるか (= 発動成立判定)
    fireable_exists = any(
        eval_all_conditions(e, state, defender, None) for e in trigger_effects
    )
    if not fireable_exists:
        return False
    state.push_log(f"  TRIGGER: {card.name}")
    defender_idx = state.players.index(defender)
    # 【トリガー】解決 (play_self 等) の **前** に場に居た自軍カードを snapshot する。
    # OP13-106 コニー: 【トリガー】で自身を登場させた場合、 その同じ【トリガー】発動を
    # 自身の【相手のターン中】(on_self_trigger_fired) で拾ってはならない (= 公式 いいえ)。
    # 登場は trigger 解決中に起きるので、 snapshot 後の新 iid は除外される。
    pre_trigger_field_iids = {
        ip.instance_id
        for ip in ([defender.leader] + list(defender.characters) + list(defender.stages))
    }
    enqueue_event(
        state,
        when="trigger",
        owner_idx=defender_idx,
        source_card_id=card.card_id,
        source_iid=None,
    )
    # 公式 (OP06-044 ギオン系): 【トリガー】効果は それに反応する opp_event_or_trigger_fired
    # reactive より **先** に解決する。 counter 経路と同じ理由 (turn 優先で reactive が
    # 先取りされる) で、 トリガー効果を先に drain してから reactive を積む。
    _maybe_resolve(state)
    # 「相手がイベントか【トリガー】を発動した時」 (OP11-102 ケイミー 等)
    # defender = トリガー発火側 → attacker_player 側を opp として発火させる。
    trigger_opp_event_or_trigger_fired(
        state, attacker_player, defender, effects_overlay,
    )
    # 「自分の【トリガー】が発動した時」 (OP13-106 コニー 等)。
    # defender = トリガー発火側 (= 自分視点)。 defender の 場 で when="on_self_trigger_fired"
    # を 持つ カード を enqueue。 ⚠ この【トリガー】自身が登場させたカード (= snapshot 後の
    # 新 iid) は除外する (公式: 登場元の【トリガー】発動では自身の反応は発動しない)。
    _enqueue_field_when(
        state, defender, "on_self_trigger_fired", effects_overlay,
        only_iids=pre_trigger_field_iids,
    )
    _maybe_resolve(state)
    return True


def should_fire_trigger(
    state: GameState,
    defender: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> bool:
    """ヒューリスティックで「トリガーを発動すべきか」を判定 (公式 10-1-5 任意性)。

    判定方針:
    - カードに【トリガー】効果が無ければ False (発動できないので手札へ)
    - 発動効果のうち eval_condition を満たすものが 1 つもなければ False
    - 「発動して相手キャラを除去できる」/「自分の場を強化できる」など、有利になる場合のみ True
      (簡易判定: トリガー効果が ko/return_to_hand/draw/power_pump 系を含むなら True)
    - そうでない (= power_pump 自身のみ等で 状況によっては不要) は False (= 手札に保持)

    現実装はシンプルに「該当効果があれば True」を返すが、defender の状況に応じて
    保持優先 (= 手札を増やす) を選ぶ余地は残す。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return False
    trigger_effects = [e for e in bundle.effects if e.get("when") == "trigger"]
    if not trigger_effects:
        return False
    # 条件を満たす発動可能な効果が 1 つでもあるか
    for eff in trigger_effects:
        if not eval_all_conditions(eff, state, defender, None):
            continue
        # ヒューリスティック: 強力な効果 (除去/ドロー/ライフ復元/登場) が含まれるなら発動。
        # play_self / play_from_trash / play_from_hand 等の「登場」 系も盤面を増やす有利効果
        # (= OP16-105 モリア / 111 サンダーソニア / 113 マリーゴールド の トリガー登場)。
        for prim in eff.get("do", []):
            if any(k in prim for k in (
                "ko", "return_to_hand", "draw", "life_to_hand", "rest", "ko_self",
                "play_self", "play_from_trash", "play_multi_from_trash", "play_from_hand",
                "fire_self_effect",
            )):
                return True
        # power_pump のみの効果は保留 (ライフが増える方が有利な場合あり)
    # 強力な効果が無ければ手札に保持を選ぶ (= False)
    return False


def trigger_main_event(
    state: GameState,
    me: Player,
    opp: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【メイン】イベントを enqueue。 コストは呼び出し側で支払い済み。"""
    bundle = effects_overlay.get(card.card_id)
    has_main = bundle is not None and any(e.get("when") == "main" for e in bundle.effects)
    if has_main:
        me_idx = state.players.index(me)
        enqueue_event(
            state,
            when="main",
            owner_idx=me_idx,
            source_card_id=card.card_id,
            source_iid=None,
        )
        # 公式 (OP06-044 ギオン系): イベントの効果は それに反応する opp_event_or_trigger_fired
        # reactive より **先** に解決する。 counter 経路と同じ理由 (turn 優先で reactive が
        # 先取りされる) で、 main 効果を先に drain してから reactive を積む。
        _maybe_resolve(state)
    # イベント発動そのもの (= bundle 有無に関わらず) で相手側の反応を発火。
    # ① 「相手がイベントを発動した時」 (OP11-012 フランキー 等、 event-play 経路のみ)。
    trigger_opp_event_played(state, opp, me, effects_overlay)
    # ② 「相手がイベントか【トリガー】を発動した時」 (OP11-102 ケイミー 等)。
    trigger_opp_event_or_trigger_fired(state, opp, me, effects_overlay)
    # 同イベント発動で自分側の on_self_event_played を発火。
    # 公式 「自分がイベントを発動した時」 (OP04-053 ページワン 等)。
    trigger_self_event_played(state, me, opp, effects_overlay)
    _maybe_resolve(state)


def trigger_counter_event(
    state: GameState,
    me: Player,
    opp: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【カウンター】イベントを enqueue (7-1-3-1-2)。 me=防御側。 コスト既払い。"""
    bundle = effects_overlay.get(card.card_id)
    has_counter = bundle is not None and any(e.get("when") == "counter" for e in bundle.effects)
    me_idx = state.players.index(me)
    if has_counter:
        enqueue_event(
            state,
            when="counter",
            owner_idx=me_idx,
            source_card_id=card.card_id,
            source_iid=None,
        )
        # 公式 (cardqa_op_06 / OP06-044 ギオン): 「相手が使用したイベントの【カウンター】効果を
        # 処理した後、 この【自分のターン中】効果で相手が自身の手札1枚をデッキの下に置きます」。
        # = カウンター効果は それに反応する opp_event_or_trigger_fired reactive より **先** に
        # 解決する。 _pop_next_event は turn_player 側イベントを優先するため、 counter (=防御側=
        # 非turn) と reactive (=攻撃側=turn) を同時にキューへ積むと reactive が先に pop され順序が逆転
        # していた。 counter を先に drain してから reactive を積む。
        _maybe_resolve(state)
    # カウンターイベント発動も event-play 経路 = 「相手がイベントを発動した時」 を撃つ。
    trigger_opp_event_played(state, opp, me, effects_overlay)
    trigger_opp_event_or_trigger_fired(state, opp, me, effects_overlay)
    trigger_self_event_played(state, me, opp, effects_overlay)
    # 防御中 (= AI ターン中) でも defender が human なら user pick を 有効化 する 為、
    # forced_human_actor_idx を 一時的 に set。 _maybe_resolve 完了 で clear。
    prev_forced = getattr(state, "forced_human_actor_idx", None)
    state.forced_human_actor_idx = me_idx
    try:
        _maybe_resolve(state)
    finally:
        state.forced_human_actor_idx = prev_forced


def trigger_on_attack(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【アタック時】を enqueue。 effect の `cost` (once_per_turn / pay_don) は
    enqueue タイミングで同期に支払う (= 失敗ならスキップ、 成功なら effect_indexes payload に記録)。

    cost を支払って enqueue した index のみ _execute_event で発火。
    cost 無しの effect は通常通り when="on_attack" の全件発火 (effect_indexes 未指定)。

    人間 actor の cost 持ち effect は pending_choice "on_attack_optional" で user 確認、
    「使わない」 で skip (= DON 消費なし)。
    """
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    me_idx = state.players.index(me)
    is_human_actor = (
        state.human_player_idx is not None
        and me_idx == state.human_player_idx
    )
    paid_indexes: list[int] = []
    has_costless = False
    pending_cost_effects: list[tuple[int, dict]] = []
    for idx, eff in enumerate(bundle.effects):
        if eff.get("when") != "on_attack":
            continue
        cost = eff.get("cost") or {}
        if not cost:
            has_costless = True
            continue
        if not eval_all_conditions(eff, state, me, attacker):
            continue
        # skip 済み (= user が このバトルで 不使用 を 選んだ) effect は 再提示しない
        # (= cost 繰り返し型の skip-loop 防止、 _reset_battle_buffs でクリア)。
        if idx in getattr(attacker, "_on_attack_opt_skipped", ()):
            continue
        if cost.get("once_per_turn") and idx in attacker.attack_once_used:
            continue
        # cost 全体の feasibility (= pay_don だけでなく discard_hand/rest_self_don 等も)。
        real_cost = {k: v for k, v in cost.items() if k != "once_per_turn"}
        if real_cost and not _can_pay_counter_cost(state, me, attacker, real_cost):
            continue
        # 人間 actor: user 確認 が必要 → 一旦 pending に
        if is_human_actor:
            pending_cost_effects.append((idx, eff))
            continue
        # AI: 即時 支払 + 発動。 全 cost キーを _pay_counter_cost に委譲
        # (= 旧実装は pay_don のみ inline で discard_hand/rest_self_don を踏み倒していた。
        #   OP14-080 等で「手札3枚捨てずにライフ追加」 を audit_cost_payment.py が発見、 2026-06-04 修正)。
        if real_cost:
            _pay_counter_cost(state, me, opp, attacker, real_cost)
        if cost.get("once_per_turn"):
            attacker.mark_attack_once_used(idx)
        # 1 アタック 1 回 (上の human 側と同理由): 発動後は このバトル中 再 fire しない。
        # redirect 再解決で trigger_on_attack が再呼出されても多重発動しないよう battle scope で gate。
        _skipped_ai = set(getattr(attacker, "_on_attack_opt_skipped", ()))
        _skipped_ai.add(idx)
        attacker._on_attack_opt_skipped = _skipped_ai
        paid_indexes.append(idx)
    # 人間 actor + cost 持ち effect → user 確認 modal を 立てる (= 1 effect ずつ)
    if is_human_actor and pending_cost_effects:
        idx0, eff0 = pending_cost_effects[0]
        cost0 = eff0.get("cost") or {}
        state.pending_choice = {
            "kind": "on_attack_optional",
            "card_id": attacker.card.card_id,
            "card_name": attacker.card.name,
            "effect_idx": idx0,
            "effect_text": eff0.get("_text", ""),
            "pay_don": int(cost0.get("pay_don", 0)),
            "_attacker_iid": attacker.instance_id,
        }
        state.push_log(
            f"  on_attack 効果 確認 待ち: {attacker.card.name} (eff #{idx0})"
        )
        return
    if has_costless:
        # cost 無し効果 → 通常 enqueue (effect_indexes 未指定 = when 一致全件)
        # cost 持ちの effect_indexes 経路と分けるため、 別イベントとして 2 件積むのが安全
        # ただし has_costless と paid_indexes を 1 イベントで両立させる方が AI 順序選択上自然。
        # → effect_indexes に paid_indexes + costless idx を全部入れて単一イベントにする。
        # 1 アタック 1 回: cost 無し on_attack も _on_attack_opt_skipped で gate する。
        # (= 人間 actor の target_pick 等で attack が再処理され trigger_on_attack が
        #  再呼出されても -2000 等が多重発動 (無限 prompt ループ) しない。 ナス寿郎
        #  OP13-080【アタック時】相手キャラ-2000 で発覚、 _reset_battle_buffs でクリア。
        #  cost 持ち経路と同じ gate を costless にも適用)。
        _cl_skipped = set(getattr(attacker, "_on_attack_opt_skipped", ()))
        for idx, eff in enumerate(bundle.effects):
            if (eff.get("when") == "on_attack" and not eff.get("cost")
                    and idx not in _cl_skipped):
                paid_indexes.append(idx)
                _cl_skipped.add(idx)
        attacker._on_attack_opt_skipped = _cl_skipped
        paid_indexes = sorted(set(paid_indexes))
    if not paid_indexes:
        return
    enqueue_event(
        state,
        when="on_attack",
        owner_idx=me_idx,
        source_card_id=attacker.card.card_id,
        source_iid=attacker.instance_id,
        payload={"effect_indexes": paid_indexes},
    )
    _maybe_resolve(state)


def _can_pay_activate_cost(
    state: GameState, me: Player, inplay: InPlay, cost: dict
) -> bool:
    """activate_main の cost を支払えるか判定 (実際の支払いは fire_activate_main で行う)。

    対応コスト:
    - rest_self: bool          self がアクティブである必要
    - pay_don: int             場のドン (active+rested) が N 枚以上必要
    - discard_hand: int        手札 N 枚以上必要
    - ko_self_with_filter: dict 自場に該当キャラ 1 枚以上必要 (例: {feature: "B・W"})
    - once_per_turn: bool      _act_used が False
    """
    if cost.get("rest_self"):
        # 公式 (3 弾で繰り返し): 「レストにできない」 は **レストにすることが必要な行動**
        # (アタック /【ブロッカー】発動 / レストを要するコストの支払い) をできなくする。
        # レスト済 だけでなく 「レストにできない」 状態でも払えない (2026-08-04 是正)。
        if inplay.rested or inplay.cannot_be_rested_buff or inplay.static_cannot_be_rested:
            return False
    if cost.get("trash_self"):
        # 自身が場 (chara or stage) にいる必要
        if inplay not in me.characters and inplay not in me.stages:
            return False
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0 and _pay_don_capacity(state, me) < pay_don:
        return False
    rest_self_don = int(cost.get("rest_self_don", 0))
    if rest_self_don > 0 and me.don_active < rest_self_don:
        return False
    # trash_to_deck N (= トラッシュ N 枚をデッキに戻す、 例 OP05-082): トラッシュ不足なら払えない。
    ttd_n = int(cost.get("trash_to_deck", 0) or 0)
    if ttd_n > 0 and len(me.trash) < ttd_n:
        return False
    if cost.get("return_self_to_hand"):
        # self を 手札に 戻す cost: self が 場 (chara) に いる + 手札 余裕 (= 10 枚未満)
        if inplay not in me.characters:
            return False
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0 and len(me.hand) < discard_n:
        return False
    # filter 付き discard cost (= 「自分の手札から特徴X を持つカード N 枚を捨てることができる」)
    # spec: {"discard_hand_with_filter": {"filter": {"feature": "百獣海賊団"}, "count": 1}}
    #   or 旧簡略形 {"discard_hand_with_filter": {"feature": "...", "count": N}}
    discard_filter_spec = cost.get("discard_hand_with_filter")
    if discard_filter_spec:
        if "filter" in discard_filter_spec:
            d_filt = discard_filter_spec.get("filter", {})
        else:
            # 旧簡略形を filter dict に変換
            d_filt = {k: v for k, v in discard_filter_spec.items() if k != "count"}
        d_count = int(discard_filter_spec.get("count", 1))
        matching = [c for c in me.hand if _matches_filter(c, d_filt)]
        if len(matching) < d_count:
            return False
    # R4: reveal_hand_with_filter cost (= 公開のみ、 実消費なし)
    # 公式: 「自分の手札から特徴X を持つカード N 枚を公開することができる：効果」 (OP14-105, OP12-003 等)
    # spec: {"reveal_hand_with_filter": {"filter": {...}, "count": N}}
    #   or {"reveal_hand_with_filter": {"feature_in": [...], "count": N}}
    reveal_filter_spec = cost.get("reveal_hand_with_filter")
    if reveal_filter_spec:
        if "filter" in reveal_filter_spec:
            r_filt = reveal_filter_spec.get("filter", {})
        else:
            r_filt = {k: v for k, v in reveal_filter_spec.items() if k != "count"}
        r_count = int(reveal_filter_spec.get("count", 1))
        matching = [c for c in me.hand if _matches_filter(c, r_filt)]
        if len(matching) < r_count:
            return False
    ko_filter = cost.get("ko_self_with_filter")
    if ko_filter:
        # filter 一致の自キャラが少なくとも 1 枚必要
        candidates = [c for c in me.characters if _matches_filter_ip(c, ko_filter)]
        if not candidates:
            return False
    rest_filter_name = cost.get("rest_self_target_name") or cost.get("rest_self_target")
    if rest_filter_name:
        # 自分の場のキャラ/ステージで name 一致 + アクティブが 1 枚以上必要。
        # spec の形式: "ハチノス" (= name) または {"name": "X"}
        target_name = (
            rest_filter_name.get("name", "") if isinstance(rest_filter_name, dict)
            else str(rest_filter_name)
        )
        cands = [
            ip for ip in (list(me.characters) + list(me.stages))
            if (ip.card.name == target_name and not ip.rested)
        ]
        if not cands:
            return False
    # rest_own_card: 「自分のカード1枚をレストにできる」 (= OP14-020 緑ミホーク leader)。
    #   対象は自分の場のカード (leader/character/stage) 任意 = アクティブが count 枚以上必要。
    rest_own = cost.get("rest_own_card")
    if rest_own is not None:
        _ro_n = int(rest_own.get("count", 1)) if isinstance(rest_own, dict) else int(rest_own)
        _ro_filt = rest_own.get("filter", {}) if isinstance(rest_own, dict) else {}
        _ro_pool = [
            ip for ip in ([me.leader] + list(me.characters) + list(me.stages))
            if ip is not None and not ip.rested and _matches_filter_ip(ip, _ro_filt)
        ]
        if len(_ro_pool) < _ro_n:
            return False
    # 選択コスト: 「特徴X を持つキャラ か 手札1枚をトラッシュ」 (= OP13-079 イム leader)。
    # spec: {"discard_hand_or_trash_filtered_chara": {"filter": {"feature": "天竜人"}, "n": 1}}
    # 払える条件: 手札 ≥ 1 OR filter 一致の自キャラ ≥ 1 (= どちらか一方で足りる)。
    choice_cost = cost.get("discard_hand_or_trash_filtered_chara")
    if choice_cost:
        n = int(choice_cost.get("n", 1))
        c_filt = choice_cost.get("filter", {})
        chara_cands = [c for c in me.characters if _matches_filter_ip(c, c_filt)]
        if len(me.hand) < n and len(chara_cands) < n:
            return False
    # ⚠ 公式: 【ターン1回】 の **無い** 起動メインは コストを払える限り何度でも起動できる。
    #   以前は `cost.get("once_per_turn", True)` と **既定 True** にして一律 1 回に制限して
    #   いた (無限ループ回避の意図的近似)。 これは公式と違ううえ、 **overlay の実装漏れを
    #   隠していた** (EB04-016 トリ / OP10-030 スモーカー の自己ロック 「その後、 このターン中、
    #   キャラの効果でドン‼をアクティブにできない」 が未実装なのに気付けなかった)。
    #   → 既定を False にして公式準拠にする (2026-08-04)。
    #   無限ループは **公式ルール側が防いでいる**: 起動メイン 197 枚のうち 180 枚は
    #   自己制限的コスト (自身レスト/トラッシュ)、 11 枚は資源消費、 残る 2 枚 (上記) は
    #   自己ロックで 2 回目が no-op になる。 その 2 枚は list_activate_main_effects 側で
    #   「効果が無意味になったら列挙しない」 ガードを掛ける (= 探索のループ防止であって
    #   ルール上の制限ではない)。
    if cost.get("once_per_turn", False) and getattr(inplay, "_act_used", False):
        return False
    return True


def estimate_attacker_self_buff(
    state: GameState,
    attacker: InPlay,
    effects_overlay: dict[str, "CardEffectBundle"],
) -> int:
    """attacker が `when:"on_attack"` 効果で自身 / 自リーダーに与える正の power_pump 合計。

    defender が counter を切る量を決めるとき、 attacker のリアクティブ強化を予測するのに使う。
    例: attacker.power=6000、 attacker.on_attack で「self_leader +1000」あり → 実質 7000 攻撃。
        defender は gap=2000 (vs base 5000 leader) で counter を切る必要がある。
    target = "self" / "self_leader" / "self_inplay" の正の amount を集計。
    eval_condition で `if` 句が True のもののみ。 DON コスト等は最大 (発動可) と仮定。
    """
    if not effects_overlay:
        return 0
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return 0
    total = 0
    me = state.turn_player  # attacker の所有者 = ターンプレイヤー
    for eff in bundle.effects:
        if eff.get("when") != "on_attack":
            continue
        if not eval_all_conditions(eff, state, me, attacker):
            continue
        for prim in eff.get("do", []):
            pp = prim.get("power_pump")
            if not pp:
                continue
            target = pp.get("target", "self")
            amount = int(pp.get("amount", 0))
            # self / self_leader / self_inplay : attacker 自身またはターン側リーダーが強化される
            if target in ("self", "self_leader", "self_inplay") and amount > 0:
                total += amount
    return total


def estimate_opp_attack_buff_to_leader(
    state: GameState,
    opp: Player,
    effects_overlay: dict[str, "CardEffectBundle"],
) -> int:
    """opp 側が「相手のアタック時」に自リーダーへ加算する power_pump 合計を見積もる。

    AI がリーダー攻撃の viable 判定をするとき、 trigger_on_opp_attack で発火しうる
    防御 buff を予測してフィルタするのに使う。最大予想値 (= 条件成立時の上限) を返す。

    集計対象: opp.leader / opp.characters / opp.stages の overlay の when:"opp_attack" 効果
      do 配列中の power_pump で target が self_leader / self (= self_inplay = leader 自身)
      かつ amount > 0 のもの (defensive 強化)
    eval_condition で `if` 句 が True のもののみ。
    DON コストや opp_hand 条件等は default で「最大」(常に発動可能) と仮定。
    """
    if not effects_overlay:
        return 0
    total = 0
    candidates: list[InPlay] = [opp.leader, *opp.characters, *opp.stages]
    for inplay in candidates:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "opp_attack":
                continue
            # if 句 を opp 視点で評価 (opp 側 leader_feature 等)
            if not eval_all_conditions(eff, state, opp, inplay):
                continue
            for prim in eff.get("do", []):
                pp = prim.get("power_pump")
                if pp:
                    target = pp.get("target", "self")
                    amount = int(pp.get("amount", 0))
                    # opp 視点の self_leader / self → opp.leader 自身が強化される
                    if target in ("self_leader", "self") and amount > 0:
                        total += amount
                    continue
                # 可変 DON-rest 防御 pump (= OP13-001 赤緑ルフィ leader 等):
                # 「自ドンを任意枚 rest → 1 枚毎に leader/麦わら を +amount_per_rest」。
                # power_pump と違い amount が固定でないため別途集計しないと AI が
                # est_def を 過小評価し pump-leader へ boost 空振り する (= campaign #2)。
                # 防御で rest 可能な枚数 = min(opp.don_active, max)。 if 句 (attached_don_ge /
                # don_active_le 等) は上の eval_all_conditions で既に検証済 = pump online 時のみ来る。
                rb = prim.get("rest_self_don_for_battle_buff_per_don")
                if rb:
                    target = rb.get("target", "self_leader")
                    if target not in ("self_leader", "self"):
                        continue
                    amount_per = int(rb.get("amount_per_rest", 0))
                    max_n = int(rb.get("max", 5))
                    restable = min(opp.don_active, max_n)
                    if amount_per > 0 and restable > 0:
                        total += amount_per * restable
    return total


def estimate_opp_life_trigger_attacker_ko_risk(
    state: GameState,
    opp: Player,
    attacker_power: int,
    effects_overlay: dict[str, "CardEffectBundle"],
) -> float:
    """opp 側のライフから出る可能性のあるトリガー (= 「雷迎」 系) で
    自陣 attacker が KO されるリスクを期待損失で見積もる。

    AI 簡易: opp.deck + opp.life から「【トリガー】を持つ」 カードのうち、
    効果が attacker を KO しうるもの (= ko / ko_multi primitive を含み、
    target が attacker のパワーを KO 可能) の枚数 / 残デッキ枚数 を確率とし、
    attacker のコスト相当を期待損失とする。

    完全な確率モデルではなく、 「ライフが残ってる + 相手デッキに KO トリガーが多い」
    場合に attacker のリスクを認識させるための簡易シグナル。

    Returns: 期待損失 (= cost × 確率 × 1000)。 単位は AI スコア (= W_FIELD_POWER 基準)。
    """
    if not effects_overlay or not opp.life:
        return 0.0
    # opp の見えない手札 / デッキ全体から「KOトリガー候補」 を数える
    # 簡略: opp.deck + opp.life (= まだ手札に来てないカード) で評価
    pool = list(opp.deck) + list(opp.life)
    if not pool:
        return 0.0
    ko_trigger_count = 0
    for card in pool:
        if not card.trigger or "【トリガー】" not in (card.trigger or ""):
            continue
        bundle = effects_overlay.get(card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "trigger":
                continue
            for prim in eff.get("do", []):
                if "ko" in prim or "ko_multi" in prim:
                    ko_trigger_count += 1
                    break
            else:
                continue
            break
    if ko_trigger_count == 0:
        return 0.0
    # 確率 = ライフ取られた時に KO トリガーが出る期待 (= ライフから引かれるカード = pool 中の任意 1 枚)
    # 既にライフに有るのは pool 中だが、 ライフは固定 (= デッキシャッフル前提なので両者を pool として扱う)
    prob = ko_trigger_count / len(pool)
    # 期待損失 = attacker_power × 確率 (= attacker が KO されたら power 喪失)
    return attacker_power * prob


def list_activate_main_effects(
    state: GameState,
    me: Player,
    effects_overlay: dict[str, CardEffectBundle],
) -> list[tuple[InPlay, EffectSpec]]:
    """場のキャラ・リーダーのうち、起動メイン効果を持つ&使える組み合わせを返す。

    安全策: 公式ルール上、起動メイン効果はターン1回が一般的。
    overlay の cost に once_per_turn が明示されていない場合でも、
    once_per_turn=True として扱う (無限ループ回避)。
    """
    out: list[tuple[InPlay, EffectSpec]] = []
    # ⚠ ステージ (= me.stages) も 起動メイン を 持つ (= OP13-099 虚の玉座 等 41 枚)。
    #   旧実装は leader + characters のみ 走査していて、 ステージの activate_main が
    #   一切 legal_actions に出ず 「機能しない」 バグ だった (2026-07-17 修正)。
    candidates: list[InPlay] = [me.leader] + list(me.characters) + list(me.stages)
    for inplay in candidates:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "activate_main":
                continue
            cost = eff.get("cost", {})
            if not _can_pay_activate_cost(state, me, inplay, cost):
                continue
            # if 条件 (例: 場にコスト5+キャラいる、leader_feature 等) も評価
            if not eval_all_conditions(eff, state, me, inplay):
                continue
            # 発動元が 「効果無効」 なら _execute_event の gate で必ず抑止される (= 実行しても
            # 何も起きない)。 列挙しても無意味な手を AI に選ばせ続けるだけなので落とす。
            # ⚠ ルール上の制限ではなく 「確実に no-op と分かる手を出さない」 だけ。
            #   OP06-083 オーズ は自分で自分を無効化するので 2 回目以降がこれに当たる
            #   (once_per_turn 既定 True の近似を外して初めて露出、 2026-08-04)。
            if ("効果無効" in inplay.granted_keywords
                    or "効果無効" in getattr(inplay, "static_granted_keywords", set())
                    or getattr(inplay, "effect_disabled_through_opp_turn", False)):
                continue
            # ⚠ 探索のループ防止 (ルール上の制限ではない)。
            #   【ターン1回】 の無い起動メインは公式上何度でも起動できるが、 効果が
            #   **状態を一切変えない** 状態になったものを出し続けると beam/plan_search が
            #   同じ手を無限に選べてしまう。 現状 該当するのは 「ドン‼をアクティブにする」 +
            #   自己ロック (EB04-016 トリ / OP10-030 スモーカー) だけで、 ロック後の再起動は
            #   完全な no-op になる。 no-op と分かっているものは列挙しない。
            #   (2026-08-04: once_per_turn 既定 True の近似を撤去した際に導入)
            if _activate_main_is_noop(state, me, inplay, eff):
                continue
            # ⚠ コストが `do` の optional_cost_then 側に書かれている overlay が多数ある
            #   (EB02-009 サウザンド・サニー号 「このステージをレストにできる：…」 等)。
            #   _can_pay_activate_cost は top-level `cost` しか見ないので、 レスト済でも
            #   起動可能に見えてしまい AI が延々と再起動していた (once_per_turn 既定 True の
            #   近似がフタをしていた、 2026-08-04 発覚。 実測で全 action の 6 割を 1 枚が占めた)。
            #   公式は 「このステージをレストにできる」 = レスト済なら払えない。
            if not _optional_cost_payable_in_do(state, me, inplay, eff):
                continue
            out.append((inplay, eff))
    return out


def _optional_cost_payable_in_do(
    state: GameState, me: Player, inplay: InPlay, eff: EffectSpec
) -> bool:
    """`do` の optional_cost_then に書かれたコストが払えるか (起動メインの列挙用)。

    overlay は 「X することができる：Y」 を top-level `cost` ではなく do 内の
    optional_cost_then で表すことが多い。 列挙時にこれを見ないと 「払えないのに legal」 に
    なる。 ⚠ 判定できるものだけ見る (未知コストは True = 従来通り列挙する)。
    """
    for prim in (eff.get("do") or []):
        if not isinstance(prim, dict) or "optional_cost_then" not in prim:
            continue
        for cs in (prim["optional_cost_then"].get("cost") or []):
            if not isinstance(cs, dict):
                continue
            # 自身をレスト/トラッシュ/手札戻し = 自身の状態で判定できる
            if cs.get("rest_self") and inplay.rested:
                return False
            if cs.get("rest") == "self" and inplay.rested:
                return False
            if cs.get("rest_self_don"):
                if me.don_active < int(cs["rest_self_don"]):
                    return False
            if cs.get("pay_don"):
                if (me.don_active + me.don_rested) < int(cs["pay_don"]):
                    return False
            if cs.get("discard_hand"):
                if len(me.hand) < int(cs["discard_hand"]):
                    return False
            # 資源が尽きたら払えない型 (判定が単純で確実なものだけ)
            if cs.get("trash_self_hand_random"):
                if len(me.hand) < int(cs["trash_self_hand_random"]):
                    return False
            if cs.get("self_hand_to_deck_bottom") or cs.get("hand_to_deck_bottom"):
                v = cs.get("self_hand_to_deck_bottom") or cs.get("hand_to_deck_bottom")
                n = int(v.get("amount", 1)) if isinstance(v, dict) else int(v)
                if len(me.hand) < n:
                    return False
            if cs.get("trash_to_deck"):
                v = cs["trash_to_deck"]
                n = int(v.get("limit", v.get("count", 1))) if isinstance(v, dict) else int(v)
                if len(me.trash) < n:
                    return False
            if cs.get("life_to_hand") or cs.get("life_top_or_bottom_to_hand"):
                v = cs.get("life_to_hand") or cs.get("life_top_or_bottom_to_hand")
                n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
                if len(me.life) < n:
                    return False
            if cs.get("mill_self_life_to_trash"):
                v = cs["mill_self_life_to_trash"]
                n = int(v.get("amount", 1)) if isinstance(v, dict) else int(v)
                if len(me.life) < n:
                    return False
            if cs.get("flip_life_face_up") and not me.life:
                return False
            if cs.get("flip_life_face_down") and not me.life:
                return False
            if cs.get("return_self_to_deck_bottom") or cs.get("return_self_to_trash"):
                # 自身が場に居る必要 (= 既に場外なら払えない)
                if inplay not in me.characters and inplay not in me.stages:
                    return False
            if cs.get("return_self_don_to_deck"):
                if (me.don_active + me.don_rested) < int(cs["return_self_don_to_deck"]):
                    return False
    return True


def _activate_main_is_noop(
    state: GameState, me: Player, inplay: InPlay, eff: EffectSpec
) -> bool:
    """起動メインが 「実行しても状態が変わらない」 と静的に分かるか (探索のループ防止用)。

    ⚠ ここに条件を足すのは 「no-op であることが確実」 な場合だけ。 迷ったら False (= 列挙する)。
    公式ルール上は起動できるので、 列挙しないのは あくまで探索が同じ手を繰り返さないため。
    """
    do = eff.get("do") or []
    if not do:
        return True
    # 「ドン‼をアクティブにする」 が自己ロック済 → untap_don も block も no-op
    if (getattr(me, "block_chara_effect_untap_don_until_turn_end", False)
            and inplay.card.category == Category.CHARACTER
            and all(
                (isinstance(p, dict)
                 and set(p) <= {"untap_don", "block_chara_effect_untap_don_turn"})
                for p in do
            )):
        return True
    return False


def _find_effect_index(state: GameState, inplay: InPlay, eff: EffectSpec) -> Optional[int]:
    """overlay bundle 内 で eff が 何 番目 か 返す。 activate_main_cost_pick の
    resume 時 に effect 再 lookup する 為 の helper。"""
    if not state.effects_overlay:
        return None
    bundle = state.effects_overlay.get(inplay.card.card_id)
    if bundle is None:
        return None
    for i, e in enumerate(bundle.effects):
        if e is eff:
            return i
    return None


def fire_activate_main(
    state: GameState,
    me: Player,
    opp: Player,
    inplay: InPlay,
    eff: EffectSpec,
    cost_picks: Optional[dict[str, int]] = None,
) -> None:
    """起動メインの発火。 コストは同期支払い、 効果は enqueue (= effect_indexes payload 経由)。

    一度コストを払ったら効果実行は再評価せず必ず行う (= eval_condition は skip 可能)。
    実装上は _execute_event 側で if 句を再評価しているが、 起動メインの if 句は通常
    cost 判定とほぼ重複なので問題なし。

    log 順: 「起動メイン: X」 (header) → 「起動メインコスト: ...」 (cost) → 「効果: ...」 (effect)。
    cost を先に書くと、 人間が観戦時に「何の起動メインを発動した結果これを払ったのか」 が
    分からないため、 header を先に push する。

    cost_picks: resume 時 (= activate_main_cost_pick modal 解決後) に 渡される
        picks dict。 key: "ko_iid" / "rest_iid"。 None なら 初回 呼出 (= header push する)。
        人間 acting + 候補 > 1 の cost (= ko_self_with_filter / rest_self_target_name)
        で modal halt → 解決後 cost_picks 付き で 再呼出 する。
    """
    is_resume = cost_picks is not None
    if cost_picks is None:
        cost_picks = {}
    if not is_resume:
        state.push_log(f"起動メイン: {inplay.card.name}")
    cost = eff.get("cost", {})
    # resume 時 (= 既に cost 一部 払い済) は 既 paid cost を スキップ し て
    # 「未払い pick-needing cost + enqueue effect」 のみ 実行 する。
    # rest_self / trash_self / pay_don / rest_self_don / return_self_to_hand /
    # discard_hand / discard_hand_with_filter / reveal_hand_with_filter は 全 自動 適用 で、
    # 初回 呼出 で 既 完了 → resume 時 スキップ。
    if not is_resume:
        # rest_self: log push 漏れ で 「コスト と 状態 変化 の 順序 逆」 と 見える bug 修正
        # (= U2 観戦コメント T1 由来)。 push_log し ない と state.rested が 「起動メイン: X」
        # snap 後 silent に true 化 する ので、 観戦者 は cost 払い タイミング を 見失う。
        if cost.get("rest_self"):
            inplay.rested = True
            state.push_log(f"  起動メインコスト: 自レスト {inplay.card.name}")
        # trash_self: 起動コストとしてこのキャラ自身をトラッシュに置く
        # 公式: 「このキャラをトラッシュに置くことができる」 = 自KO 同等の扱い
        # (= 場から取り除き、 持ち主のトラッシュへ、 付与ドンはレストでコストエリアへ)
        if cost.get("trash_self"):
            if inplay in me.characters:
                me.characters.remove(inplay)
                me.trash.append(inplay.card)
                if inplay.attached_dons > 0:
                    me.don_rested += inplay.attached_dons
                    inplay.attached_dons = 0
                state.push_log(f"  起動メインコスト: 自トラッシュ {inplay.card.name}")
            elif inplay in me.stages:
                me.stages.remove(inplay)
                me.trash.append(inplay.card)
                if inplay.attached_dons > 0:
                    me.don_rested += inplay.attached_dons
                    inplay.attached_dons = 0
                state.push_log(f"  起動メインコスト: 自ステージトラッシュ {inplay.card.name}")
        # pay_don N: 場のドンを N 枚ドンデッキに戻す (active 優先)
        pay_don = int(cost.get("pay_don", 0))
        if pay_don > 0:
            taken = min(pay_don, me.don_active)
            me.don_active -= taken
            me.don_remaining_in_deck += taken
            rest_more = min(pay_don - taken, me.don_rested)
            me.don_rested -= rest_more
            me.don_remaining_in_deck += rest_more
            state.push_log(f"  起動メインコスト: ドン-{pay_don}")
            if (taken + rest_more) > 0 and state.effects_overlay:
                trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay, count=taken + rest_more)
        # rest_self_don N: アクティブドン N 枚を rested に
        rest_self_don = int(cost.get("rest_self_don", 0))
        if rest_self_don > 0:
            actual = min(rest_self_don, me.don_active)
            me.don_active -= actual
            me.don_rested += actual
            state.push_log(f"  起動メインコスト: アクティブドン {actual} レスト")
        # trash_to_deck N: トラッシュ上から N 枚をデッキ下へ (= 起動コスト、 例 OP05-082。
        # 旧実装は未払いで trash_to_deck 分の cost を踏み倒していた、 2026-06-04 修正)
        ttd_act = int(cost.get("trash_to_deck", 0) or 0)
        if ttd_act > 0:
            moved = min(ttd_act, len(me.trash))
            for _ in range(moved):
                me.deck.append(me.trash.pop(0))
            if moved:
                state.push_log(f"  起動メインコスト: トラッシュ {moved} 枚をデッキ下に")
        # return_self_to_hand: self を 場 から 手札 に 戻す
        if cost.get("return_self_to_hand") and inplay in me.characters:
            me.characters.remove(inplay)
            me.hand.append(inplay.card)
            if inplay.attached_dons > 0:
                me.don_rested += inplay.attached_dons
                inplay.attached_dons = 0
            state.push_log(f"  起動メインコスト: 自 → 手札 {inplay.card.name}")
        # filter 付き discard cost (= 「自分の手札から特徴X を持つカード N 枚を捨てる」)
        discard_filter_spec = cost.get("discard_hand_with_filter")
        if discard_filter_spec:
            if "filter" in discard_filter_spec:
                d_filt = discard_filter_spec.get("filter", {})
            else:
                d_filt = {k: v for k, v in discard_filter_spec.items() if k != "count"}
            d_count = int(discard_filter_spec.get("count", 1))
            discarded = 0
            new_hand = []
            for c in me.hand:
                if discarded < d_count and _matches_filter(c, d_filt):
                    me.trash.append(c)
                    discarded += 1
                    state.push_log(f"  起動メインコスト: 手札捨て (filter) → {c.name}")
                else:
                    new_hand.append(c)
            me.hand = new_hand
        # R4: reveal_hand_with_filter (公開のみ、 実消費なし)。
        # 公式: 「自分の手札から特徴X を持つカード N 枚を公開することができる：効果」 (OP14-105 等)。
        # payability で hand に N 枚以上あることは確認済。 ここでは公開ログのみ。
        reveal_filter_spec = cost.get("reveal_hand_with_filter")
        if reveal_filter_spec:
            if "filter" in reveal_filter_spec:
                r_filt = reveal_filter_spec.get("filter", {})
            else:
                r_filt = {k: v for k, v in reveal_filter_spec.items() if k != "count"}
            r_count = int(reveal_filter_spec.get("count", 1))
            revealed = []
            for c in me.hand:
                if len(revealed) < r_count and _matches_filter(c, r_filt):
                    revealed.append(c.name)
            state.push_log(f"  起動メインコスト: 手札公開 (実消費なし) → {revealed}")
    # discard_hand N: 手札 N 枚 捨 て。 人 間 acting なら modal で 選 ば せ る、
    # AI / その他 は random (= 簡 略)。
    # 2026-05-30 fix: if not is_resume の 外 で 処 理 し て resume 時 (= cost_picks に
    # discard_idxs あり) も pick 適 用 を 動 か す (= イム OP13-079 起動 メイン 真因 修 復)。
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0 and me.hand:
        actual_n = min(discard_n, len(me.hand))
        # resume 経 由 (= cost_picks に discard_idxs あり) なら そ ち ら 使 う
        picked_idxs = cost_picks.get("discard_idxs") if isinstance(cost_picks, dict) else None
        if picked_idxs is not None:
            # 人 間 modal で 選 ば れ た hand index を 使 う、 降 順 で pop (= index ずれ 防止)
            idxs = sorted(set(int(i) for i in picked_idxs if 0 <= int(i) < len(me.hand)),
                          reverse=True)
            for hi in idxs[:actual_n]:
                me.trash.append(me.hand.pop(hi))
                state.push_log(f"  起動メインコスト: 手札1捨て (人間選択)")
        elif not is_resume and _should_human_pick(state):
            # 初 回 + 人 間 picking 必要 = pending_choice で halt
            eff_idx = _find_effect_index(state, inplay, eff)
            cand_list = [
                {
                    "hand_idx": i,
                    "card_id": c.card_id,
                    "name": c.name,
                    "cost": int(c.cost) if c.cost is not None else 0,
                    "power": int(c.power) if c.power is not None else 0,
                }
                for i, c in enumerate(me.hand)
            ]
            state.pending_choice = {
                "kind": "activate_main_discard_pick",
                "source_iid": inplay.instance_id,
                # source_card_id: trash_self/self_ko を併用する cost (= EB03-062 等) では
                # この時点で既に source が場を離れトラッシュにある。 resume 時に
                # source_iid で場を引けないため card_id を持ち回し ghost 再構成する。
                "source_card_id": inplay.card.card_id,
                "effect_index": eff_idx,
                "candidates": cand_list,
                "limit": actual_n,
                "prior_picks": dict(cost_picks) if cost_picks else {},
            }
            state.push_log(
                f"  起動メインコスト: 手札 {actual_n} 枚 捨 て る 対 象 を 選 択 待 ち"
            )
            return
        elif not is_resume:
            # AI / pending 不要: 最悪札から捨てる(random だと beam の value 評価が薄まる)。
            for _ in range(actual_n):
                if not me.hand:
                    break
                me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
                state.push_log(f"  起動メインコスト: 手札1捨て")
        # is_resume + picked_idxs なし は 既 払 い 済 と み な し no-op (= 想 定 外 だ が safe)
    # discard_hand_or_trash_filtered_chara: 「特徴X キャラ か 手札1枚 を トラッシュ」 選択コスト
    # (= OP13-079 イム leader)。 人間 acting + 両方の選択肢あり → modal halt。
    # AI / 片方のみ → heuristic (= 手札優先、 手札空なら 該当キャラ trash)。
    choice_cost = cost.get("discard_hand_or_trash_filtered_chara")
    if choice_cost:
        n = int(choice_cost.get("n", 1))
        c_filt = choice_cost.get("filter", {})
        chara_cands = [c for c in me.characters if _matches_filter_ip(c, c_filt)]
        # resume key: discard_idxs (= 既存 activate_main_discard_pick modal 由来、 手札 axis) /
        #             choice_cost_chara_iid (= activate_main_cost_pick modal 由来、 キャラ axis)。
        # 既存 2 modal を 再利用するため 新 UI component 不要。
        if isinstance(cost_picks, dict) and "discard_idxs" in cost_picks:
            idxs = sorted(set(int(i) for i in cost_picks["discard_idxs"]
                              if 0 <= int(i) < len(me.hand)), reverse=True)
            for hi in idxs[:n]:
                me.trash.append(me.hand.pop(hi))
                state.push_log(f"  起動メインコスト: 手札1捨て (人間選択)")
        elif isinstance(cost_picks, dict) and "choice_cost_chara_iid" in cost_picks:
            tgt = next((c for c in chara_cands
                        if c.instance_id == cost_picks["choice_cost_chara_iid"]), None)
            if tgt is not None:
                me.characters.remove(tgt)
                me.trash.append(tgt.card)
                if tgt.attached_dons > 0:
                    me.don_rested += tgt.attached_dons
                    tgt.attached_dons = 0
                state.push_log(f"  起動メインコスト: 天竜人キャラtrash {tgt.card.name}")
        elif not is_resume and _should_human_pick(state) and (len(me.hand) >= n or chara_cands):
            # 公式: 「天竜人キャラ か 手札1枚 を トラッシュ」 の 2 択。 手札候補 と 盤面天竜人
            # キャラ候補を 1 つの activate_main_cost_pick modal に 統合 して 人間に 両方 選ばせる
            # (= 旧 実装は 手札あると キャラ axis を 出さず 自動化していた bug、 2026-06-01 修正)。
            # 候補形式: キャラ = iid 持ち / 手札 = hand_idx 持ち (擬似 iid に 負値を 振り key 衝突回避)。
            # TargetPickModal は card_id で 画像表示 + iid/power/rested を 使うのみ なので 混在可。
            eff_idx = _find_effect_index(state, inplay, eff)
            cands_mixed = []
            for c in chara_cands:
                cands_mixed.append({
                    "iid": c.instance_id, "card_id": c.card.card_id, "name": c.card.name,
                    "cost": int(c.card.cost) if c.card.cost is not None else 0,
                    "power": int(c.power), "rested": bool(c.rested),
                    "attached_dons": int(c.attached_dons), "owner": "self", "is_leader": False,
                    "axis": "chara",
                })
            for i, c in enumerate(me.hand):
                cands_mixed.append({
                    "iid": -(i + 1),  # 擬似 iid (= key 衝突回避、 resolve では hand_idx を 使う)
                    "hand_idx": i, "card_id": c.card_id, "name": c.name,
                    "cost": int(c.cost) if c.cost is not None else 0,
                    "power": int(c.power) if c.power is not None else 0,
                    "rested": False, "attached_dons": 0, "owner": "self", "is_leader": False,
                    "axis": "hand",
                })
            state.pending_choice = {
                "kind": "activate_main_cost_pick",
                "cost_kind": "trash_filtered_chara",
                "source_iid": inplay.instance_id,
                "effect_index": eff_idx,
                "candidates": cands_mixed,
                "prior_picks": dict(cost_picks),
                "limit": n,
                "primitive_kind": "trash_filtered_chara",
                "description": "起動メインコスト: トラッシュする 天竜人キャラ か 手札 を 選択",
            }
            state.push_log(
                f"  起動メインコスト: 天竜人キャラ {len(chara_cands)} + 手札 {len(me.hand)} "
                f"→ 人間 選択 待ち (trash)"
            )
            return
        elif not is_resume:
            # AI / 片方のみ: 手札優先 (= mill deck で手札discardが支配的)、 手札空なら キャラtrash
            if len(me.hand) >= n:
                for _ in range(n):
                    if not me.hand:
                        break
                    me.trash.append(me.hand.pop(_worst_hand_idx(me.hand, me.known_hand_card_ids)))
                    state.push_log(f"  起動メインコスト: 手札1捨て")
            elif chara_cands:
                chara_cands.sort(key=lambda c: c.power)
                for tgt in chara_cands[:n]:
                    me.characters.remove(tgt)
                    me.trash.append(tgt.card)
                    if tgt.attached_dons > 0:
                        me.don_rested += tgt.attached_dons
                        tgt.attached_dons = 0
                    state.push_log(f"  起動メインコスト: 天竜人キャラtrash {tgt.card.name}")
    # ko_self_with_filter: 自場の該当キャラ1枚KO
    # 人間 acting + 候補 > 1 + pick 未指定 → modal halt + activate_main_cost_pick で resume。
    ko_filter = cost.get("ko_self_with_filter")
    if ko_filter is not None:
        candidates = [c for c in me.characters if _matches_filter_ip(c, ko_filter)]
        if candidates:
            target = None
            if "ko_iid" in cost_picks:
                target = next(
                    (c for c in candidates if c.instance_id == cost_picks["ko_iid"]),
                    None,
                )
            elif len(candidates) > 1 and _should_human_pick(state):
                eff_idx = _find_effect_index(state, inplay, eff)
                if eff_idx is not None:
                    state.pending_choice = {
                        "kind": "activate_main_cost_pick",
                        "cost_kind": "ko_self_with_filter",
                        "source_iid": inplay.instance_id,
                        "effect_index": eff_idx,
                        "candidates": [
                            {
                                "iid": c.instance_id,
                                "card_id": c.card.card_id,
                                "name": c.card.name,
                                "cost": int(c.card.cost) if c.card.cost is not None else 0,
                                "power": int(c.power),
                                "rested": bool(c.rested),
                                "attached_dons": int(c.attached_dons),
                                "owner": "self",
                                "is_leader": False,
                            }
                            for c in candidates
                        ],
                        "prior_picks": dict(cost_picks),
                        "limit": 1,
                        "primitive_kind": "ko_self_with_filter",
                        "description": "起動メインコスト: 自KO 対象 を 選択",
                    }
                    state.push_log(
                        f"  起動メインコスト 候補 {len(candidates)} 枚 → 人間 選択 待ち (= 自KO)"
                    )
                    return
            if target is None:
                target = candidates[0]
            me.characters.remove(target)
            me.trash.append(target.card)
            if target.attached_dons > 0:
                me.don_rested += target.attached_dons
            state.push_log(f"  起動メインコスト: 自KO {target.card.name}")
            if state.effects_overlay:
                # me 側 victim、 me 側 cost (= 自爆 cost) → by_opp_effect=False
                trigger_on_ko(state, me, opp, target.card, state.effects_overlay, by_opp_effect=False, victim_attached_don=target.attached_dons, victim_effect_negated=_ip_effect_negated(target))
                # 自KO なので on_self_chara_ko (= me 側) を発火
                trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
    # rest_self_target_name: 自場の name 一致キャラ/ステージを 1 枚 rest
    # 公式: 「自分の『ハチノス』1枚をレストにできる：効果」 (ST27-001 アバロ・ピサロ等)
    # 人間 acting + 候補 > 1 + pick 未指定 → modal halt (= ko と 同じ pattern)。
    rest_filter_name = cost.get("rest_self_target_name") or cost.get("rest_self_target")
    if rest_filter_name:
        target_name = (
            rest_filter_name.get("name", "") if isinstance(rest_filter_name, dict)
            else str(rest_filter_name)
        )
        rest_candidates = [
            ip for ip in (list(me.characters) + list(me.stages))
            if ip.card.name == target_name and not ip.rested
        ]
        if rest_candidates:
            target_ip = None
            if "rest_iid" in cost_picks:
                target_ip = next(
                    (ip for ip in rest_candidates if ip.instance_id == cost_picks["rest_iid"]),
                    None,
                )
            elif len(rest_candidates) > 1 and _should_human_pick(state):
                eff_idx = _find_effect_index(state, inplay, eff)
                if eff_idx is not None:
                    state.pending_choice = {
                        "kind": "activate_main_cost_pick",
                        "cost_kind": "rest_self_target_name",
                        "source_iid": inplay.instance_id,
                        "effect_index": eff_idx,
                        "candidates": [
                            {
                                "iid": ip.instance_id,
                                "card_id": ip.card.card_id,
                                "name": ip.card.name,
                                "cost": int(ip.card.cost) if ip.card.cost is not None else 0,
                                "power": int(ip.power),
                                "rested": bool(ip.rested),
                                "attached_dons": int(ip.attached_dons),
                                "owner": "self",
                                "is_leader": False,
                            }
                            for ip in rest_candidates
                        ],
                        "prior_picks": dict(cost_picks),
                        "limit": 1,
                        "primitive_kind": "rest_self_target_name",
                        "description": f"起動メインコスト: 自レスト 対象 「{target_name}」 を 選択",
                    }
                    state.push_log(
                        f"  起動メインコスト 候補 {len(rest_candidates)} 枚 → 人間 選択 待ち (= 自レスト)"
                    )
                    return
            if target_ip is None:
                target_ip = rest_candidates[0]
            target_ip.rested = True
            state.push_log(f"  起動メインコスト: 自レスト {target_ip.card.name}")
    # rest_own_card: 「自分のカード1枚をレストにできる」= 場の任意カード(leader/char/stage)を選択。
    #   人間 acting + 候補 > count + pick 未指定 → modal halt。 AI は 非リーダー + power 低い順で自動
    #   (= 攻撃に使いたいリーダー/高power キャラを温存)。 OP14-020 緑ミホーク leader。
    rest_own = cost.get("rest_own_card")
    if rest_own is not None:
        ro_n = int(rest_own.get("count", 1)) if isinstance(rest_own, dict) else int(rest_own)
        ro_filt = rest_own.get("filter", {}) if isinstance(rest_own, dict) else {}
        ro_pool = [
            ip for ip in ([me.leader] + list(me.characters) + list(me.stages))
            if ip is not None and not ip.rested and _matches_filter_ip(ip, ro_filt)
        ]
        if ro_pool:
            chosen = []
            if "rest_own_iids" in cost_picks:
                _want = set(cost_picks["rest_own_iids"])
                chosen = [ip for ip in ro_pool if ip.instance_id in _want][:ro_n]
            elif len(ro_pool) > ro_n and _should_human_pick(state):
                eff_idx = _find_effect_index(state, inplay, eff)
                if eff_idx is not None:
                    state.pending_choice = {
                        "kind": "activate_main_cost_pick",
                        "cost_kind": "rest_own_card",
                        "source_iid": inplay.instance_id,
                        "effect_index": eff_idx,
                        "candidates": [
                            {
                                "iid": ip.instance_id,
                                "card_id": ip.card.card_id,
                                "name": ip.card.name,
                                "cost": int(ip.card.cost) if ip.card.cost is not None else 0,
                                "power": int(ip.power),
                                "rested": bool(ip.rested),
                                "attached_dons": int(ip.attached_dons),
                                "owner": "self",
                                "is_leader": ip is me.leader,
                            }
                            for ip in ro_pool
                        ],
                        "prior_picks": dict(cost_picks),
                        "limit": ro_n,
                        "primitive_kind": "rest_own_card",
                        "description": "起動メインコスト: レストにする自分のカードを選択",
                    }
                    state.push_log(
                        f"  起動メインコスト 候補 {len(ro_pool)} 枚 → 人間 選択 待ち (= 自レスト任意)"
                    )
                    return
            if not chosen:
                ro_pool.sort(key=lambda ip: (0 if ip is not me.leader else 1, ip.power))
                chosen = ro_pool[:ro_n]
            for ip in chosen:
                ip.rested = True
                state.push_log(f"  起動メインコスト: 自レスト {ip.card.name}")
    # once_per_turn フラグ (明示指定時のみ。 既定 True の近似は 2026-08-04 に撤去)
    if cost.get("once_per_turn", False):
        setattr(inplay, "_act_used", True)
    # effect 本体は enqueue (= 集中ドレインで実行)。 bundle 内 effect index を解決して payload に。
    # （header の push_log は関数冒頭で実施済み = cost 支払い前に観戦者へ何の起動メインか示す）
    bundle = state.effects_overlay.get(inplay.card.card_id) if state.effects_overlay else None
    if bundle is None:
        return
    eff_idx = None
    for i, e in enumerate(bundle.effects):
        if e is eff:
            eff_idx = i
            break
    if eff_idx is None:
        return
    me_idx = state.players.index(me)
    enqueue_event(
        state,
        when="activate_main",
        owner_idx=me_idx,
        source_card_id=inplay.card.card_id,
        source_iid=inplay.instance_id,
        payload={"effect_indexes": [eff_idx]},
    )
    _maybe_resolve(state)
