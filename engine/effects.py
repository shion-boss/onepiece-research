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

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .core import CardDef, Category, GameState, InPlay, Player


# --------------------------------------------------------------------------- #
# 効果オーバーレイの読み込み
# --------------------------------------------------------------------------- #
EffectSpec = dict[str, Any]


@dataclass
class CardEffectBundle:
    """1 枚のカードに紐づく効果のリスト。"""

    card_id: str
    effects: list[EffectSpec] = field(default_factory=list)


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
        out[cid] = CardEffectBundle(card_id=cid, effects=effects)
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
        # 主要効果のみ。 on_ko 等は除外。
        if (
            self_inplay is not None
            and (
                "効果無効" in self_inplay.granted_keywords
                or self_inplay.effect_disabled_through_opp_turn
            )
            and evt.when in ("on_play", "on_attack", "activate_main", "main", "counter")
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
                if _check_and_set_once_per_turn(state, me, eff, evt.source_card_id, idx) is False:
                    continue
                for primitive in eff.get("do", []):
                    execute_effect(primitive, state, me, opp, self_inplay)
            return

        # 通常の when 一致 effects を全て発火
        for idx, eff in enumerate(bundle.effects):
            if eff.get("when") != when:
                continue
            if not eval_all_conditions(eff, state, me, self_inplay):
                continue
            # 【ターン1回】 ガード: spec.once_per_turn が True/str なら使用済みチェック
            if _check_and_set_once_per_turn(state, me, eff, evt.source_card_id, idx) is False:
                continue
            # counter event の cost (= 「自分の手札 1 枚を捨てる」 等 任意 コスト):
            # 公式 「コスト：効果」 で コスト 払えない なら 効果 不発。
            # 旧 engine は cost を 無視 して 効果 発動 (= bug、 player は コスト 払わず 効果 取得)。
            # 新: counter 専用 path で cost 支払い 検証 + 支払い。 払えなければ 効果 skip。
            # 注: 現状 modal UI 未対応 (= 人間 も auto-pay)、 将来 「counter_optional」 modal 追加 予定。
            if when == "counter":
                cost = eff.get("cost") or {}
                if cost:
                    if not _can_pay_counter_cost(state, me, self_inplay, cost):
                        state.push_log(
                            f"  counter 効果: cost 支払い不能 → skip ({evt.source_card_id})"
                        )
                        continue
                    _pay_counter_cost(state, me, opp, self_inplay, cost)
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, self_inplay)
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
    if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
        return False
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0 and me.don_active < rest_don:
        return False
    return True


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
            i = state.rng.randrange(len(me.hand))
            me.trash.append(me.hand.pop(i))
        state.push_log(f"  counter コスト: 手札 {actual} 枚 捨て")
        if actual > 0 and state.effects_overlay:
            trigger_on_self_hand_discarded(
                state, me, opp, self_inplay, actual, state.effects_overlay
            )
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0:
        from_active = min(me.don_active, pay_don)
        me.don_active -= from_active
        me.don_remaining_in_deck += from_active
        rest_more = min(pay_don - from_active, me.don_rested)
        me.don_rested -= rest_more
        me.don_remaining_in_deck += rest_more
        state.push_log(f"  counter コスト: ドン-{pay_don}")
        if (from_active + rest_more) > 0 and state.effects_overlay:
            trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay)
    rest_don = int(cost.get("rest_self_don", 0))
    if rest_don > 0:
        actual = min(rest_don, me.don_active)
        me.don_active -= actual
        me.don_rested += actual
        state.push_log(f"  counter コスト: アクティブドン {actual} レスト")


def _check_and_set_once_per_turn(
    state: GameState,
    me: Player,
    eff: EffectSpec,
    card_id: str,
    idx: int,
) -> bool:
    """effect spec の `once_per_turn` をチェックし、 未使用なら使用済みフラグを立てる。

    戻り値:
    - True: once_per_turn 指定なし、 もしくは未使用 → 発動許可
    - False: 既に使用済み → 発動拒否 (= 呼び出し元は continue でスキップ)

    once_per_turn の値:
    - True: 自動キー (= f"{card_id}:{when}:{idx}")
    - "<str>": 明示キー (= 複数 effect で同一キーを共有可)

    cost 経由の once_per_turn (= activate_main / on_attack の `cost.once_per_turn`) は
    InPlay 側のフラグで別管理されているのでここでは触れない。
    """
    opt = eff.get("once_per_turn")
    if not opt:
        return True
    if opt is True:
        key = f"{card_id}:{eff.get('when', '')}:{idx}"
    else:
        key = f"key:{opt}"
    if key in me.once_per_turn_used:
        return False
    me.once_per_turn_used.add(key)
    return True


def _maybe_resolve(state: GameState) -> None:
    """resolve_triggers をネスト呼び出ししない安全ラッパ。 trigger_* の末尾で呼ぶ。"""
    if state.resolving:
        return
    resolve_triggers(state)


# --------------------------------------------------------------------------- #
# 条件評価
# --------------------------------------------------------------------------- #
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
        elif k == "self_field_count_le":
            if len(me.characters) > int(v):
                return False
        elif k == "self_trash_count_ge":
            if len(me.trash) < int(v):
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
        elif k == "self_chara_filtered_count_ge":
            # 複合 filter (色 + 特徴 + 除外名 等) でカウント条件判定。
            # OP11-096 リッパー 「リッパー以外の自分の黒の特徴《海軍》を持つキャラがいる場合」 等。
            # spec: {"filter": {...}, "count": N, "rested_required": false}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 1))
            rested_required = bool(spec.get("rested_required", False))
            def _ip_matches(ip):
                if not _matches_filter(ip.card, filt):
                    return False
                if rested_required and not ip.rested:
                    return False
                return True
            count = sum(1 for c in me.characters if _ip_matches(c))
            if count < need:
                return False
        elif k == "opp_chara_filtered_count_ge" and opp is not None:
            # 相手場の キャラ で filter にマッチ する 数 N 以上 (= 「相手のコスト0のキャラがいる場合」 等)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            need = int(spec.get("count", 1))
            count = sum(1 for c in opp.characters if _matches_filter(c.card, filt))
            if count < need:
                return False
        elif k == "opp_chara_filtered_count_le" and opp is not None:
            # 相手場 キャラ で filter にマッチ する 数 N 以下 (= 「相手のパワー5000+のキャラが2以上いない (= ≤1)」 等)。
            # spec: {"filter": {...}, "count": N}
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            limit = int(spec.get("count", 0))
            count = sum(1 for c in opp.characters if _matches_filter(c.card, filt))
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
        elif k == "leader_multicolor":
            # 自リーダーが多色 (= color に "/" 含む) であるか
            is_multi = "/" in me.leader.card.color
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
            # リーダーのカード名一致 (例: "サンジ" / "イム" / "ルーシー")
            if me.leader.card.name != str(v):
                return False
        elif k == "leader_name_in":
            # リーダー名がリストに含まれる
            if me.leader.card.name not in (v or []):
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
    # opp target 「実害 評価」 (= AI が pick する 際 の eval 良い順)。
    # ohtsuki さん 要望 「AI も最善手 考えるよう target expansion」。
    # 排除 価値 = cost + power + blocker bonus + finisher role bonus
    def _opp_value(c) -> float:
        val = float(c.card.cost) * 1000 + float(c.power)
        if getattr(c, "is_blocker_now", False):
            val += 3000
        try:
            from . import card_role as _cr
            role = _cr.get_primary_role(c.card.card_id)
            if role == "finisher":
                val += 5000
            elif role == "blocker":
                val += 2500
            elif role == "support":
                val += 1500
        except Exception:
            pass
        return val

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
    # 辞書 spec で type-based dispatch
    if isinstance(target_spec, dict) and "type" in target_spec:
        t = target_spec["type"]
        if t == "self_chara_named":
            name = target_spec.get("name", "")
            return [ip for ip in me.characters if ip.card.name == name][:1]
        if t == "self_chara_or_leader_named":
            name = target_spec.get("name", "")
            cands = [ip for ip in [me.leader, *me.characters] if ip.card.name == name]
            return cands[:1]
        if t == "all_self_chara_named":
            name = target_spec.get("name", "")
            return [ip for ip in me.characters if ip.card.name == name]
        if t == "one_self_chara_or_leader_filtered":
            # 自リーダー / キャラから filter にマッチする 1 枚 (パワー高い順、 human は modal で選択)
            filt = target_spec.get("filter", {})
            cands = [ip for ip in [me.leader, *me.characters]
                     if _matches_filter(ip.card, filt)]
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
                     if _matches_filter(ip.card, filt)]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="自キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "all_self_chara_filtered":
            # 自キャラ全員 (filter マッチ)。 limit 指定で上限あり (= 「N 枚まで」)。
            # rested フィールド (= optional) で active/rested を 絞れる。
            # human + 候補 > limit なら modal で 選択。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.characters if _matches_filter(ip.card, filt)]
            if "rested" in target_spec:
                rested_required = bool(target_spec["rested"])
                cands = [ip for ip in cands if ip.rested == rested_required]
            limit = target_spec.get("limit")
            if iid_picks is not None and limit is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:int(limit)]
            if limit is not None:
                if outer_kind and len(cands) > int(limit) and _maybe_request_target_pick(
                    state, cands, int(limit), outer_kind, outer_value, self_inplay,
                    description=f"自キャラ から {limit} 枚 まで 選択",
                ):
                    return []
                # AI 簡易: power 高い順 (= 強いキャラ優先)
                cands.sort(key=lambda ip: -ip.power)
                return cands[:int(limit)]
            return cands
        if t == "all_self_team_filtered":
            # 自リーダー + キャラ全員 (filter マッチ)
            filt = target_spec.get("filter", {})
            return [ip for ip in [me.leader, *me.characters]
                    if _matches_filter(ip.card, filt)]
        if t == "one_opponent_character_filtered":
            # 相手キャラから filter にマッチする 1 枚 (= パワー高い順、 attached_don 等の属性条件も追加サポート)
            filt = target_spec.get("filter", {})
            attached_don_ge = int(filt.get("attached_don_ge", 0))
            rested_required = bool(filt.get("rested", False))
            cands = []
            for ip in opp.characters:
                if not _matches_filter(ip.card, filt):
                    continue
                if attached_don_ge > 0 and ip.attached_dons < attached_don_ge:
                    continue
                if rested_required and not ip.rested:
                    continue
                if "current_power_le" in filt and ip.power > int(filt["current_power_le"]):
                    continue
                cands.append(ip)
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="相手キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "all_opponent_chara_filtered":
            # 相手キャラ全員 (filter マッチ)。 limit 指定で上限あり (= 「N 枚まで」)。
            # 公式 「相手のキャラ N 枚まで」 で、 power 5000 制限がないケースに使う。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in opp.characters if _matches_filter(ip.card, filt)]
            limit = target_spec.get("limit")
            if iid_picks is not None and limit is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:int(limit)]
            if limit is not None:
                cands.sort(key=lambda ip: -_opp_value(ip))
                return cands[:int(limit)]
            return cands
        if t == "one_opponent_inplay_filtered":
            # 相手リーダー or キャラ から filter にマッチする 1 枚
            filt = target_spec.get("filter", {})
            cands = [opp.leader, *opp.characters]
            cands = [ip for ip in cands if _matches_filter(ip.card, filt)]
            if iid_picks is not None:
                return [ip for ip in cands if ip.instance_id in iid_picks][:1]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description="相手リーダー or キャラ から 1 枚 選択",
            ):
                return []
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "one_self_stage_filtered":
            # 自分のステージから filter にマッチする 1 枚 (= レスト中優先、 human は modal で選択)。
            # 公式 「自分の紫のステージ1枚までを、 アクティブにする」 (P-077 等)。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.stages if _matches_filter(ip.card, filt)]
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
    if target_spec == "opponent_leader":
        return [opp.leader]
    if target_spec == "self_leader":
        return [me.leader]
    if target_spec == "all_opponent_characters":
        return list(opp.characters)
    if target_spec == "any_opponent_character_le_5000":
        # 全員対象 (board wipe 系)。普通のカード「1枚まで」は one_* を使うこと
        return [c for c in opp.characters if c.power <= 5000]
    # --- single-target (公式テキスト「1 枚まで」相当) ---
    # 候補を power 高い順にソートして「最も脅威となるキャラ」を狙う簡略化 (AI 用)。
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
    if target_spec == "all_self_characters":
        return list(me.characters)
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
        m = re.match(r"one_opponent_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.card.cost <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (コスト≤{n})",
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
            return [c for c in opp.characters if c.card.cost <= n]

        # one_opponent_rested_character_cost_le_N (レスト + コスト N 以下、1 体)
        m = re.match(r"one_opponent_rested_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.rested and c.card.cost <= n]
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
            cands = [c for c in opp.characters if c.power <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (パワー≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_opponent_character_power_eq_N (パワー N ぴったり、 1 体)。
        # 公式「元々のパワー N」 用 (= CardDef.power で判定)。
        m = re.match(r"one_opponent_character_power_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.card.power == n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (元々のパワー={n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
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
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_self_character_cost_le_N (= 自分のキャラ コスト N 以下、 1 体, power 最大)
        m = re.match(r"one_self_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in me.characters if c.card.cost <= n]
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
                if c.card.cost <= n and not _has_on_play(c.card)
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
            cands = [c for c in opp.characters if c.rested and c.power <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手レストキャラ から 1 枚 選択 (パワー≤{n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # one_opponent_character_cost_eq_N / cost_0 等 (= ぴったり N コスト)
        m = re.match(r"one_opponent_character_cost_(?:eq_)?(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in opp.characters if c.card.cost == n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手キャラ から 1 枚 選択 (コスト={n})",
            ):
                return []
            cands.sort(key=lambda c: -c.power)
            return cands[:1]

        # all_opponent_rested_characters_le_Ncost
        m = re.match(r"all_opponent_rested_characters_le_(\d+)cost$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if c.rested and c.card.cost <= n]

        # one_self_character_le_Ncost (= 自分の cost N 以下キャラ 1 枚、 パワー高い順)
        m = re.match(r"one_self_character_le_(\d+)cost$", target_spec)
        if m:
            n = int(m.group(1))
            cands = [c for c in me.characters if c.card.cost <= n]
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
            cands = [c for c in me.characters if c.card.cost == n]
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
            cands.sort(key=lambda c: -c.power)
            return cands[:n]

        # one_self_character_named_X (名前一致セレクタ。 X は 「エネル」 等)
        m = re.match(r"one_self_character_named_(.+)$", target_spec)
        if m:
            target_name = m.group(1)
            cands = [c for c in me.characters if c.card.name == target_name]
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
            return [c for c in me.characters if c.card.name == target_name]

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
            cands = [opp.leader] + [c for c in opp.characters if c.card.cost <= n]
            if outer_kind and _maybe_request_target_pick(
                state, cands, 1, outer_kind, outer_value, self_inplay,
                description=f"相手リーダー or キャラ から 1 枚 選択 (コスト≤{n})",
            ):
                return []
            sorted_chara = sorted(
                [c for c in opp.characters if c.card.cost <= n],
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
    """
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
            # AI (= actor=opp 含む): 1 つ目 valid を 発動 (= 簡略)
            chosen_idx, chosen_opt = valid_options[0]
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
            state.push_log(f"  効果: ドロー {n} → {[c.name for c in drawn]}")
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
            state.push_log(f"  効果: 動的ドロー {n} → {[c.name for c in drawn]}")
        elif k == "trash_self_hand_random":
            n = int(v)
            actually_discarded = 0
            for _ in range(n):
                if not me.hand:
                    break
                idx = state.rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
                actually_discarded += 1
            state.push_log(f"  効果: 手札{n}枚捨て")
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
            state.push_log(f"  効果: 相手手札{n}枚捨て")
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
                        trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True)
                        # 「相手のキャラが KO された時」 (= 自分の効果で KO した側)
                        trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                        # 「自分のキャラが KO された時」 (= KO された側の場効果)
                        trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            if _ko_any and state.effects_overlay:
                # 「キャラが自分の効果で場を離れた時」 (OP07-038 ハンコック等)
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
                elif src == "self_trash_count":
                    src_val = len(me.trash)
                elif src == "self_trash_event_count":
                    src_val = sum(1 for c in me.trash if c.category == Category.EVENT)
                elif src == "self_trash_chara_count":
                    src_val = sum(1 for c in me.trash if c.category == Category.CHARACTER)
                elif src == "self_chara_feature_count":
                    feat = amount_per.get("feature", "")
                    src_val = sum(1 for c in me.characters if feat in c.card.features)
                elif src == "opp_don_total":
                    src_val = opp.don_active + opp.don_rested + opp.leader.attached_dons + sum(c.attached_dons for c in opp.characters)
                amount += (src_val // divisor) * mult

            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="power_pump", outer_value=v,
            )
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
            # 静的効果 (= on_attached_don) は evaluate_static_effects で
            # 毎回 リセット → 再加算されるためログ noise になる。 値は正常 (= +amount 一定)。
            if duration != "static":
                state.push_log(f"  効果: パワー{amount:+d} → {[t.card.name for t in targets]}")
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
                active_charas = [c for c in opp.characters if not c.rested and not c.cannot_be_rested_buff]
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
                # 「レストにできない」 保護 (OP14-033 等)
                if t.cannot_be_rested_buff:
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
            if _ret_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
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
                    return False
                chosen_indexes = sorted(
                    [i for i in picks_idx if 0 <= i < len(me.deck)],
                    reverse=True,
                )
                played_count = 0
                for i in chosen_indexes[:limit]:
                    card = me.deck[i]
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    me.deck.pop(i)
                    ip = InPlay.of(card, rested=rested, sickness=sickness)
                    me.characters.append(ip)
                    played_count += 1
                    state.push_log(f"  効果: デッキから登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                state.rng.shuffle(me.deck)
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
                        me.trash_weakest_chara_for_field_full(state)
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
                    if c.category != Category.CHARACTER:
                        # キャラ以外は登場できない → 手札にもどす (簡略フォールバック)
                        me.hand.append(c)
                        continue
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(c, rested=rested_flag, sickness=True)
                    me.characters.append(ip)
                    state.push_log(f"  効果: search_top_n → 登場 {c.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:  # hand
                    me.hand.append(c)
                    state.push_log(f"  効果: search_top_n → 手札 {c.name}")
            # 残り処理
            if rest_remain == "trash":
                me.trash.extend(remaining)
                state.push_log(
                    f"  効果: search_top_n 残り{len(remaining)}枚 → トラッシュ"
                )
            else:
                # bottom / top_or_bottom はどちらも底へ (AI 簡易)
                me.deck.extend(remaining)
            if not picked:
                state.push_log(f"  効果: search_top_n 該当なし")
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
            # 公開済カードを rest_remain へ
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
                    me.trash_weakest_chara_for_field_full(state)
                ip = InPlay.of(revealed, rested=rested_flag, sickness=True)
                me.characters.append(ip)
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
            filt = v.get("filter", {})
            limit = int(v.get("limit", 1))
            found = 0
            picked: list[CardDef] = []
            remaining: list[CardDef] = []
            for c in me.deck:
                if found < limit and _matches_filter(c, filt):
                    picked.append(c)
                    found += 1
                else:
                    remaining.append(c)
            me.deck = remaining
            # Phase 7I: search 経路は公開して手札に加える (opp に見える)
            for c in picked:
                me.add_to_hand_publicly(c)
            # サーチ後はシャッフル
            state.rng.shuffle(me.deck)
            state.push_log(f"  効果: サーチ → {[c.name for c in picked]}")
        elif k == "life_to_hand":
            if getattr(me, "prevent_self_life_to_hand_until_turn_end", False):
                state.push_log(f"  効果: ライフ→手札 禁止 (OP02-023 効果中)")
                return False
            n = int(v)
            for _ in range(n):
                if me.life:
                    me.hand.append(me.life.pop(0))
            state.push_log(f"  効果: ライフ{n}枚を手札へ")
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
            if isinstance(v, str) and v == "all":
                n = me.don_rested
            else:
                n = int(v)
            n = min(n, me.don_rested)
            me.don_rested -= n
            me.don_active += n
            state.push_log(f"  効果: ドン{n}枚をアクティブに")
        elif k == "pay_don":
            # ドン-N: 場のドン (active 優先, 足りなければ rested) N 枚をドンデッキに戻す。
            # コストとして使う (緑紫ルフィ 起動メイン ドン-2 等)
            n = int(v)
            taken = min(n, me.don_active)
            me.don_active -= taken
            me.don_remaining_in_deck += taken
            removed = taken
            if removed < n:
                more = min(n - removed, me.don_rested)
                me.don_rested -= more
                me.don_remaining_in_deck += more
                removed += more
            state.push_log(f"  効果: 自ドン -{removed} (ドンデッキへ)")
            if removed > 0 and state.effects_overlay:
                trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay)
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
            # 選択肢があれば AI が選ぶ。 優先順位 = ブロッカー (守備) > ダブルアタック (攻撃) > バニッシュ > 速攻
            if "keywords" in spec:
                kws = spec["keywords"]
                priority = ["ブロッカー", "ダブルアタック", "バニッシュ", "速攻", "ブロック不可"]
                chosen = next((p for p in priority if p in kws), kws[0] if kws else "速攻")
                keyword = chosen
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_base_power_timed", outer_value=target_spec)
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
            from_cands = _resolve_target(from_target, state, me, opp, self_inplay, outer_kind="set_base_power_copy", outer_value=from_target)
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
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            unique_name = bool(spec.get("unique_name", False))
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補 抽出 (= trash idx + CardDef)
            candidates: list[tuple[int, CardDef]] = [
                (i, c) for i, c in enumerate(me.trash)
                if c.category == Category.CHARACTER and _matches_filter(c, filt)
            ]
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
                for i in chosen_indexes[:limit]:
                    card = me.trash[i]
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    me.trash.pop(i)
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    played_count += 1
                    label = "レストで" if rested else ""
                    state.push_log(f"  効果: トラッシュから{label}登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                if played_count == 0:
                    return False
                continue
            # AI / 候補 <= limit: 既存 挙動 (= 先頭 から filter 一致 を 登場)
            found = 0
            seen_names: set[str] = set()
            new_trash = []
            for card in me.trash:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    if unique_name and card.name in seen_names:
                        new_trash.append(card)
                        continue
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    found += 1
                    seen_names.add(card.name)
                    label = "レストで" if rested else ""
                    state.push_log(f"  効果: トラッシュから{label}登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_trash.append(card)
            me.trash[:] = new_trash
        elif k == "play_from_hand":
            # 「自分の手札からキャラ1枚を 0 コストで登場」(緑紫ルフィ起動メイン / OP10-071 ドフラ 等)。
            # spec: {"filter": {"feature": "...", "cost_le": N}, "limit": 1, "rested": bool}
            # 通常の PlayCharacter と異なり、 コスト無視 (= 効果代替の登場)。
            # 人間 acting + 複数候補 + 0 < limit < 候補数 なら modal 選択 (= 2026-05-23 修正、
            # ohtsuki さん 指摘: OP10-071 ドフラ 登場時 で 勝手 に 選ばれる)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            # 既 解決 picks (= resolve_pending_choice 経由) の場合 は直接実行
            picks_idx: Optional[list[int]] = None
            if isinstance(v, dict) and "_picks_idx" in v:
                picks_idx = list(v["_picks_idx"])
            # 候補抽出
            candidates: list[tuple[int, CardDef]] = []
            for i, card in enumerate(me.hand):
                if card.category != Category.CHARACTER:
                    continue
                if not _matches_filter(card, filt):
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
                if picks_idx is not None:
                    chosen_indexes = sorted(
                        [i for i in picks_idx if 0 <= i < len(me.hand)],
                        reverse=True,
                    )
                else:
                    # ヒューリスティック並び: cost 降順 → power 降順 → name (安定)
                    candidates.sort(key=lambda t: (-t[1].cost, -t[1].power, t[1].name))
                    chosen = candidates[:limit]
                    chosen_indexes = sorted([i for i, _ in chosen], reverse=True)
                chosen_cards: list[CardDef] = []
                for idx in chosen_indexes:
                    chosen_cards.append(me.hand.pop(idx))
                for card in chosen_cards:
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    label = "レストで" if rested else ""
                    state.push_log(f"  効果: 手札から{label}登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
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
            # ヒューリスティック並び: cost 降順 → power 降順 → name (安定)
            candidates.sort(key=lambda t: (-t[1].cost, -t[1].power, t[1].name))
            chosen = candidates[:limit]
            chosen_indexes = sorted([i for i, _ in chosen], reverse=True)
            chosen_cards: list[CardDef] = []
            for i in chosen_indexes:
                chosen_cards.append(me.hand.pop(i))
            for card in chosen_cards:
                if not me.can_play_character():
                    me.trash_weakest_chara_for_field_full(state)
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
            spec = v if isinstance(v, dict) else {}
            name = spec.get("name", "")
            cost_ge = int(spec.get("cost_ge", 0))
            src = spec.get("cost_le_source", "opp_don_total")
            if src == "opp_don_total":
                cost_le = opp.don_active + opp.don_rested + opp.leader.attached_dons + sum(c.attached_dons for c in opp.characters)
            elif src == "self_don_total":
                cost_le = me.don_active + me.don_rested + me.leader.attached_dons + sum(c.attached_dons for c in me.characters)
            else:
                cost_le = int(spec.get("cost_le", 99))
            for i, card in enumerate(me.hand):
                if card.category != Category.CHARACTER:
                    continue
                if card.name != name:
                    continue
                if card.cost < cost_ge or card.cost > cost_le:
                    continue
                if not me.can_play_character():
                    me.trash_weakest_chara_for_field_full(state)
                ip = InPlay.of(card, rested=False, sickness=True)
                me.characters.append(ip)
                me.hand.pop(i)
                state.push_log(f"  効果: {name} を手札から登場 (動的cost_le={cost_le})")
                if state.effects_overlay:
                    trigger_on_play(state, me, opp, ip, state.effects_overlay)
                return True
            state.push_log(f"  効果: {name} 該当なし (cost_ge={cost_ge}, cost_le={cost_le})")
            return False
        elif k == "play_from_hand_named_set":
            # R4: 「自分の手札から、 N1 と N2 と N3 ... それぞれ 1 枚ずつまでを、 登場させる」 (ST13-006 等)。
            # spec: {"names": ["サボ", "ポートガス・D・エース", "モンキー・D・ルフィ"],
            #        "cost_eq": 2, "rested": false, "filter": {...}}
            # - cost_eq/cost_le 制約を filter として追加可。
            # - filter は names 制約とAND結合。
            # 各 name について 手札先頭の 1 枚を取り出し登場 (= AI 簡易: 最も若い index)。
            spec = v if isinstance(v, dict) else {"names": []}
            names = list(spec.get("names", []))
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
                        me.trash_weakest_chara_for_field_full(state)
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
            for _ in range(n):
                if not opp.life:
                    break
                taken = opp.life.pop(0)
                opp.hand.append(taken)
            state.push_log(f"  効果: 相手ライフ上 {n} 枚を相手手札へ")
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
            for _ in range(n):
                if not opp.life:
                    break
                taken = opp.life.pop(0)
                opp.trash.append(taken)
            state.push_log(f"  効果: 相手ライフ上 {n} 枚をトラッシュへ")
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
                trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay)
        elif k == "rest_self_don":
            # 自分のアクティブドン N 枚をレストにする (= 起動メイン代替コスト)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            actual = min(me.don_active, n)
            me.don_active -= actual
            me.don_rested += actual
            state.push_log(f"  効果: 自アクティブドン {actual} 枚をレストへ")
        elif k == "deal_opp_leader_damage":
            # 相手リーダーに N ダメージ (= 相手ライフ N を相手の手札 or トリガー)
            # 簡略: mill_opp_life_to_hand と等価扱い (トリガー判定省略)
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            for _ in range(n):
                if not opp.life:
                    break
                taken = opp.life.pop(0)
                opp.hand.append(taken)
            state.push_log(f"  効果: 相手リーダーに {n} ダメージ")
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
            target_spec = v if isinstance(v, str) else (v.get("target", "one_opponent_character_le_5000") if isinstance(v, dict) else "one_opponent_character_le_5000")
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
            state.push_log(
                f"  効果: trash → deck {to_pos} {len(picked)} 枚"
                f"{' (shuffle)' if shuffle_after else ''}"
            )
        elif k == "self_hand_to_size":
            # 自分の手札が N 枚になるように手札を捨てる
            target_size = int(v) if not isinstance(v, dict) else int(v.get("size", 5))
            while len(me.hand) > target_size:
                idx = state.rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
            state.push_log(f"  効果: 自手札を {target_size} 枚に")
        elif k == "block_chara_play_cost_ge":
            # このターン中、 元々のコスト N 以上のキャラを登場できない
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 7))
            me.block_chara_play_until_turn_end = True  # 簡略 (cost 区別なく ブロック)
            state.push_log(f"  効果: このターン中 cost{n}+ キャラ登場禁止")
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
        elif k == "in_hand_cost_minus":
            # 手札中の自身のカードコスト軽減 (= overlay の in_hand effect で使用)。
            # execute_effect 経由ではなく _compute_in_hand_cost_minus で別経路扱い。
            # ここでは log のみ (= placeholder)。
            state.push_log(f"  効果: in_hand_cost_minus (= 別経路で計算済)")
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
        elif k == "block_self_draw_turn":
            # このターン中、 自分の効果でカードを引くことができない
            me.block_self_draw_until_turn_end = True
            state.push_log(f"  効果: このターン中、 自効果ドロー禁止")
        elif k == "prevent_self_life_to_hand_turn":
            # 「自分は、 このターン中、 自分の効果でライフを手札に加えられない」 (OP02-023 等)。
            me.prevent_self_life_to_hand_until_turn_end = True
            state.push_log(f"  効果: このターン中、 自効果ライフ→手札 禁止")
        elif k == "prevent_ko":
            # ターン終了時まで KO 耐性付与。target = self / all_self_characters 等
            target_spec = v if isinstance(v, str) else "self"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="prevent_ko", outer_value=target_spec)
            for t in targets:
                t.ko_immune_until_turn_end = True
            state.push_log(f"  効果: KO 耐性 → {[t.card.name for t in targets]}")
        elif k == "set_cannot_attack":
            # ターン終了時までアタック不可。target = "one_opponent_character_*" 等
            target_spec = v if isinstance(v, str) else "one_opponent_character_any"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_cannot_attack", outer_value=target_spec)
            for t in targets:
                t.cannot_attack_until_turn_end = True
            state.push_log(f"  効果: アタック不可 → {[t.card.name for t in targets]}")
        elif k == "stay_rested_next_refresh":
            # 「次の (相手の) リフレッシュフェイズでアクティブにならない」
            # target = "one_opponent_character_*" など。多くは rest 効果と組み合わせる
            target_spec = v if isinstance(v, str) else "one_opponent_character_any"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="stay_rested_next_refresh", outer_value=target_spec)
            for t in targets:
                t.stay_rested_next_refresh = True
            state.push_log(f"  効果: 次リフレッシュ非アクティブ → {[t.card.name for t in targets]}")
        elif k == "cost_minus":
            # 「相手キャラ1枚のコスト-N」(ターン中)。base_cost 判定に反映される。
            # spec: {"target": "one_opponent_character_any", "amount": 10}
            spec = v if isinstance(v, dict) else {"target": "one_opponent_character_any", "amount": int(v)}
            target_spec = spec.get("target", "one_opponent_character_any")
            amount = int(spec.get("amount", 1))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="cost_minus", outer_value=target_spec)
            for t in targets:
                t.cost_minus_until_turn_end += amount
            state.push_log(f"  効果: コスト-{amount} → {[t.card.name for t in targets]}")
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
            targets = _resolve_target(
                target_spec, state, me, opp, self_inplay,
                outer_kind="attach_rested_don", outer_value=v,
            )
            if not targets:
                continue
            if per_target:
                attached_log: list[str] = []
                for t in targets:
                    give = min(n, me.don_rested)
                    if give <= 0:
                        break
                    me.don_rested -= give
                    t.attached_dons += give
                    attached_log.append(f"{t.card.name}+{give}")
                state.push_log(f"  効果: レストドン付与 (per_target) → {attached_log}")
            else:
                n = min(n, me.don_rested)
                if n <= 0:
                    continue
                target = targets[0]
                me.don_rested -= n
                target.attached_dons += n
                state.push_log(f"  効果: レストドン{n}付与 → {target.card.name}")
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
        elif k == "set_base_cost_timed":
            # 公式: 「(target) は、 次の相手のターン終了時まで、 コスト+N」 (EB02-041 メリー号等)。
            # spec: {"target": <target_spec>, "delta": 2, "duration": "next_opp_turn_end"}
            # 既存 set_base_cost (static) と異なり期間限定。 cost_override は absolute or delta。
            spec_val = v if isinstance(v, dict) else {}
            target_spec = spec_val.get("target", "self")
            duration = spec_val.get("duration", "next_opp_turn_end")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="set_base_cost_timed", outer_value=target_spec)
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
                    if c.card_id == src_cid and c.category == Category.CHARACTER:
                        found_card = zone.pop(i)
                        state.push_log(f"  効果: このカードを登場 ({zone_name} → 場)")
                        break
                if found_card:
                    break
            if not found_card:
                continue
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state)
            ip = InPlay.of(found_card, rested=False, sickness=True)
            me.characters.append(ip)
            if state.effects_overlay:
                trigger_on_play(state, me, opp, ip, state.effects_overlay)
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
            cands = [c for c in opp.characters if _matches_filter(c.card, filt)]
            if len(cands) < 2:
                state.push_log(f"  効果: swap_opp_power 該当 2 枚未満 (不発)")
                return False
            # AI 簡易: 最強 + 最弱 を選んでスワップ (= 弱体化最大化)
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
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 2))
            revealed = opp.hand[:n]
            state.push_log(f"  効果: 相手手札 {n} 枚公開 → {[c.name for c in revealed]}")
        elif k == "discard_self_to_deck_top":
            # 自分の手札 N 枚をデッキの上に置く (ST17-001 等)。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            if not me.hand:
                return False
            # AI 簡易: 弱いカードをデッキ上 (= 次ドローを犠牲)
            # 公式は任意選択だが、 シンプル: index 0 のカード (= 古い手札)
            moved = []
            for _ in range(min(n, len(me.hand))):
                c = me.hand.pop(0)
                me.deck.insert(0, c)
                moved.append(c.name)
            state.push_log(f"  効果: 自手札 {len(moved)} 枚 → デッキ上 ({moved})")
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
            cands = [c for c in opp.characters if c.rested and c.attached_dons >= don_ge]
            if iid_picks is not None:
                chosen = [c for c in cands if c.instance_id in iid_picks][:limit]
            elif len(cands) > limit and _maybe_request_target_pick(
                state, cands, limit, "keep_opp_rested_chara_with_don_ge_next_refresh",
                v, self_inplay,
                description=f"相手 ドン≥{don_ge} 付与 レストキャラ {limit} 枚 まで 選択",
            ):
                return False
            else:
                cands.sort(key=lambda c: -c.power)
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
            # 人間 acting + target 複数 候補 なら 移動先 を modal で 選ばせる。
            # source (= 付与ドン取り外し元) は 簡易: power 低い順 で 自動 (= 1 ターン内 で 影響軽微)。
            spec_val = v if isinstance(v, dict) else {}
            feature = spec_val.get("feature", "")
            count = int(spec_val.get("count", 1))
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
            # AI 簡易: source は power 低い順 (= 弱いキャラから剥がす)
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
                cands.sort(key=lambda ip: -ip.power)
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
                if not ip.rested and _matches_filter(ip.card, filt)
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
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "one_opponent_character_any")
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
            for t in targets:
                if t in opp.characters:
                    opp.characters.remove(t)
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                        t.attached_dons = 0
                    opp.life.insert(0, t.card)
                    state.push_log(f"  効果: 相手キャラ {t.card.name} → 相手ライフ上")
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
            # 相手は自身の手札 N 枚を選び (簡略: ランダム or 末尾) デッキの下に置く。
            # 現実的には AI が判断するが、 簡略でランダムを採用。
            n = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            moved = 0
            for _ in range(n):
                if not opp.hand:
                    break
                idx = state.rng.randrange(len(opp.hand))
                opp.deck.append(opp.hand.pop(idx))
                moved += 1
            state.push_log(f"  効果: 相手手札 {moved} 枚をデッキ下へ")
        elif k == "self_hand_to_deck_bottom":
            # 自分の手札 N 枚を好きな順番でデッキの下に置く。 簡略: 末尾から。
            spec = v if isinstance(v, dict) else {"amount": int(v) if not isinstance(v, dict) else 1}
            n = int(spec.get("amount", 1))
            moved = 0
            for _ in range(n):
                if not me.hand:
                    break
                # ヒューリスティック: コスト最高のカード (= 手札で死にカード) をデッキ下に
                idx = max(range(len(me.hand)), key=lambda i: me.hand[i].cost)
                me.deck.append(me.hand.pop(idx))
                moved += 1
            state.push_log(f"  効果: 自手札 {moved} 枚をデッキ下へ")
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
                            trigger_on_ko(state, me, opp, t.card, state.effects_overlay, by_opp_effect=False)
                            trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
                else:
                    # 相手キャラ KO 経路
                    if t.protect_from_opp_effect:
                        state.push_log(f"  保護効果: {t.card.name}")
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
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True)
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
                target_spec = spec if isinstance(spec, str) else (spec or {}).get("target", "one_opponent_character_any")
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
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay, by_opp_effect=True)
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
            if _rhm_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
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
                    trigger_on_ko(state, me, opp, ip.card, state.effects_overlay, by_opp_effect=False)
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
                if _matches_filter(ip.card, filt):
                    ip.ko_immune_through_opp_turn = True
            state.push_log(
                f"  効果: KO耐性 (next_opp_turn_end) → filter={filt}"
            )
        elif k == "set_cannot_attack_target_cost_le":
            # 「相手の元々のコスト N 以下のキャラへアタックできない」 (OP12-020 リーダー等)
            # spec: {"target": "self_leader", "cost_le": 7} or {"cost_le": 7} (= self_leader 既定)
            spec_val = v if isinstance(v, dict) else {"cost_le": int(v)}
            target_spec = spec_val.get("target", "self_leader")
            cost_le = int(spec_val.get("cost_le", 0))
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
            # 手札 か トラッシュ から filter 一致のキャラ 1 枚を登場 (= ジェルマ66系)。
            # spec: {"filter": {...}, "limit": 1, "rested": false}
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested_flag = bool(spec.get("rested", False))
            # 手札優先 → トラッシュ
            found = 0
            new_hand = []
            for card in me.hand:
                if (
                    found < limit
                    and card.category == Category.CHARACTER
                    and _matches_filter(card, filt)
                ):
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=rested_flag, sickness=True)
                    me.characters.append(ip)
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
                        and card.category == Category.CHARACTER
                        and _matches_filter(card, filt)
                    ):
                        if not me.can_play_character():
                            me.trash_weakest_chara_for_field_full(state)
                        ip = InPlay.of(card, rested=rested_flag, sickness=True)
                        me.characters.append(ip)
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
            # AI 簡易: owner="self_or_opp" は自ライフ優先 (= 自分のライフを最適化)
            target_pl = me if owner in ("self", "self_or_opp") else opp
            if not target_pl.life:
                return False
            depth = min(depth, len(target_pl.life))
            seen = target_pl.life[:depth]
            # 人間 操作中 + 対象 が 自ライフ なら user に 並び替え を 委ねる
            # (= 相手 ライフ の scry は AI 演算 のまま、 公開時点で 露呈 する 情報 ではない)
            if (
                target_pl is me
                and _should_human_pick(state)
                and depth >= 2
            ):
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
            rest = target_pl.life[depth:]
            # 自ライフ: 価値の高いカード(トリガー有/カウンター大/パワー大) を上に
            # 相手ライフ: 逆 (= 弱いカードを上にして引かせる)
            def _life_value(card):
                trig = 1 if getattr(card, "trigger", None) else 0
                counter = int(getattr(card, "counter", 0) or 0)
                power = int(getattr(card, "power", 0) or 0)
                return (trig, counter, power)
            if target_pl is me:
                seen.sort(key=_life_value, reverse=True)
            else:
                seen.sort(key=_life_value)
            target_pl.life = seen + rest
            owner_label = "自" if target_pl is me else "相手"
            state.push_log(f"  効果: {owner_label}ライフ上{depth}枚を整列")
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
            # (target) はこのバトル中、 パワー+N」 OP03-001 ポートガス・D・エース等。
            # spec: {"filter": {"category_in": ["EVENT","STAGE"]}, "amount_per_discard": 1000,
            #        "target": "self_leader", "max": 3 (AI 上限、 省略時 3)}
            spec_val = v if isinstance(v, dict) else {}
            filt = spec_val.get("filter", {"category_in": ["EVENT", "STAGE"]})
            amount_per = int(spec_val.get("amount_per_discard", 1000))
            target_spec = spec_val.get("target", "self_leader")
            max_discard = int(spec_val.get("max", 3))
            discardable = [c for c in me.hand if _matches_filter(c, filt)]
            # AI 簡易: 最大 max_discard 枚 (= デフォルト 3 枚)。
            # battle 中の発動なので「+3000」 (= 3 枚捨て) で大半の攻防を凌げる想定。
            discard_count = min(len(discardable), max_discard)
            if discard_count == 0:
                return False
            discarded = []
            for c in discardable[:discard_count]:
                me.hand.remove(c)
                me.trash.append(c)
                discarded.append(c)
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
            # ST13-012 マキノ 後文 等。 spec: True | {} (引数なし)。
            if not me.life:
                return False
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
            state.push_log(f"  効果: キャラ→自ライフ ({place}): {[t.card.name for t in targets]}")
            if _ctl_any and state.effects_overlay:
                trigger_on_self_chara_leave_by_self_effect(state, me, opp, state.effects_overlay)
        elif k == "prevent_blocker_for_attacker":
            # 公式: 「指定キャラ/リーダーがアタックする場合、 相手は【ブロッカー】を発動できない」
            # spec: {"target": <target_spec>} | str (target_spec)
            # target_spec で辞書 {"type": "one_self_chara_or_leader_filtered",
            #                    "filter": {"power_ge": 6000, "feature": "..."}} もサポート。
            target_spec = v if not isinstance(v, dict) or "target" not in v else v.get("target")
            if isinstance(target_spec, dict) and target_spec.get("type") == "one_self_chara_or_leader_filtered":
                filt = target_spec.get("filter", {})
                # 全自リーダー/キャラから filter にマッチする 1 枚 (= power 高い順)
                cands = [me.leader] + list(me.characters)
                cands = [ip for ip in cands if _matches_filter(ip.card, filt)]
                # power_ge は dataclass の InPlay.power (= base + buff) を参照する場合と
                # card.power の場合で意図が異なる。 公式は「現在のパワー」なので InPlay.power を見る。
                if "power_ge" in filt:
                    cands = [ip for ip in cands if ip.power >= int(filt["power_ge"])]
                cands.sort(key=lambda ip: -ip.power)
                targets = cands[:1]
            else:
                targets = _resolve_target(target_spec, state, me, opp, self_inplay, outer_kind="prevent_blocker_for_attacker", outer_value=target_spec)
            for t in targets:
                t.attacker_prevents_blocker_until_turn_end = True
            state.push_log(
                f"  効果: ブロッカー発動禁止 (attacker) → {[t.card.name for t in targets]}"
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
                    if not me.hand:
                        can_pay = False
                        break
                elif "pay_don" in cs:
                    n = int(cs.get("pay_don", 0))
                    if (me.don_active + me.don_rested) < n:
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
                elif "stage_to_deck_bottom" in cs:
                    # 公式 「自分のステージ1枚を持ち主のデッキの下に置くことができる：効果」 用 cost。
                    # spec: {"stage_to_deck_bottom": {"cost_eq": N, "count": 1}} もしくは
                    # spec: {"stage_to_deck_bottom": 1} (= cost 制約なし、 count=1)
                    sb_spec = cs["stage_to_deck_bottom"]
                    if isinstance(sb_spec, dict):
                        sb_count = int(sb_spec.get("count", 1))
                        sb_filt = {k: v for k, v in sb_spec.items() if k != "count"}
                    else:
                        sb_count = int(sb_spec)
                        sb_filt = {}
                    matching = [s for s in me.stages if _matches_filter(s.card, sb_filt)]
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
                    matching = [c for c in me.characters if _matches_filter(c.card, rb_filt)]
                    if len(matching) < rb_count:
                        can_pay = False
                        break
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
                    matching = [c for c in me.characters if _matches_filter(c.card, rh_filt)]
                    if len(matching) < rh_count:
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
            # effect が空回りするケースも skip (= 価値なし)
            should_fire = can_pay
            if should_fire:
                for es in effect_specs:
                    if "hand_to_self_life" in es and not me.hand:
                        should_fire = False
                        break
            if not should_fire:
                state.push_log(f"  効果: optional_cost_then 不発 (cost不能 or 効果空)")
                return False
            for cs in cost_specs:
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
                if "rest_self" in cs and not isinstance(cs.get("rest_self"), (dict, int, str)):
                    # rest_self: True 形式 (= self_inplay を rest)
                    if self_inplay is not None and not self_inplay.rested:
                        self_inplay.rested = True
                        state.push_log(f"  効果コスト: 自身レスト {self_inplay.card.name}")
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
                            state.push_log(f"  効果コスト: 手札捨て (filter) → {c.name}")
                        else:
                            new_hand.append(c)
                    me.hand = new_hand
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
                if "stage_to_deck_bottom" in cs:
                    # 公式: 自場のステージ N 枚を持ち主 (= me) のデッキの下へ。
                    # AI 簡易: 該当する filter 一致の最初の N 枚 (= 任意選択は最古順) を取り出す。
                    sb_spec = cs["stage_to_deck_bottom"]
                    if isinstance(sb_spec, dict):
                        sb_count = int(sb_spec.get("count", 1))
                        sb_filt = {k: v for k, v in sb_spec.items() if k != "count"}
                    else:
                        sb_count = int(sb_spec)
                        sb_filt = {}
                    moved = 0
                    new_stages = []
                    for s in me.stages:
                        if moved < sb_count and _matches_filter(s.card, sb_filt):
                            me.deck.append(s.card)
                            moved += 1
                            state.push_log(
                                f"  効果コスト: 自ステージ → デッキ下 ({s.card.name})"
                            )
                            # 付与ドンは公式 6-5-5-4 同様にレストでコストエリアへ戻す。
                            if s.attached_dons > 0:
                                me.don_rested += s.attached_dons
                        else:
                            new_stages.append(s)
                    me.stages = new_stages
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
                    cands = [c for c in me.characters if _matches_filter(c.card, rh_filt)]
                    cands.sort(key=lambda c: c.power)
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
                    cands = [c for c in me.characters if _matches_filter(c.card, rb_filt)]
                    cands.sort(key=lambda c: c.power)
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
                execute_effect(cs, state, me, opp, self_inplay)
            for es in effect_specs:
                execute_effect(es, state, me, opp, self_inplay)
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
    for spec in do_list:
        chain = spec.get("_chain", "always")
        if chain == "if_prev_succeeded" and not prev_succeeded:
            continue
        # _chain は execute_effect には渡さない (純粋なプリミティブ part のみ)
        clean_spec = {k: v for k, v in spec.items() if k != "_chain"}
        result = execute_effect(clean_spec, state, me, opp, self_inplay)
        # 人間 interactive choice 待ち が 立った 場合 は 後続 を 止める
        # (= 選択 解決 後 に 残り を 動かす 仕組み は 後段 で 別途 必要 だが、
        #    まず は halt を 保証)
        if state.pending_choice is not None:
            return
        # execute_effect は基本 True 返却 (現状)。将来各プリミティブで失敗判定するなら更新
        prev_succeeded = result if result is not None else True


def resolve_pending_choice(state: GameState, picks: list[int]) -> None:
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

    if kind == "target_pick":
        # target_pick: choices[i] → 該当 iid を 抜き出し、 _iid_picks を 渡して 再実行
        candidates = choice.get("candidates", [])
        valid_picks = [i for i in picks if 0 <= i < len(candidates)]
        picked_iids = [candidates[i]["iid"] for i in valid_picks]
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
        # 再実行: target_spec に _iid_picks を 追加 (= 任意 spec 形式 を カバー)
        if isinstance(primitive_value, dict):
            new_spec = dict(primitive_value)
            new_spec["_iid_picks"] = picked_iids
            # nested "target" dict にも injection (= power_pump 等 spec.target を 持つ primitive)
            if "target" in new_spec and isinstance(new_spec["target"], dict):
                new_spec["target"] = {
                    **new_spec["target"], "_iid_picks": picked_iids,
                }
            elif "target" in new_spec and isinstance(new_spec["target"], str):
                new_spec["target"] = {"_iid_picks": picked_iids}
        else:
            # 文字列 spec (例: "one_opponent_character_any") → dict 化 して bypass
            new_spec = {"_iid_picks": picked_iids}
        state.pending_choice = None  # 先 に クリア (= 再実行 中 に 別 choice 立てる 可能性 防ぐ)
        state.push_log(f"  効果: 人間選択 → {primitive_kind} 対象 {len(picked_iids)} 枚")
        execute_effect({primitive_kind: new_spec}, state, me, opp, self_inplay)
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

    if kind in ("play_from_hand_pick", "hand_to_life_pick", "play_event_from_hand_pick"):
        # 手札 から 候補 を 選ばせる 3 系統 (= play_from_hand / hand_to_self_life /
        # play_event_from_hand)。 共通の picks → hand_idx 抽出 + spec 再実行 path。
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
            import random as _rng
            rng = state.rng or _rng.Random()
            for _ in range(min(discard_n, len(defender.hand))):
                i = rng.randrange(len(defender.hand))
                defender.trash.append(defender.hand.pop(i))
        bundle = state.effects_overlay.get(source.card.card_id) if state.effects_overlay else None
        eff = bundle.effects[eff_idx] if (bundle and 0 <= eff_idx < len(bundle.effects)) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        if cost.get("once_per_turn"):
            setattr(source, f"_opp_attack_used_{eff_idx}", True)
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

    if kind == "on_attack_optional":
        # picks[0] = 1 → 使う、 0 → skip
        use_eff = bool(picks and picks[0] == 1)
        eff_idx = int(choice.get("effect_idx", -1))
        attacker_iid = choice.get("_attacker_iid")
        pay_don = int(choice.get("pay_don", 0))
        state.pending_choice = None
        if not use_eff or eff_idx < 0:
            state.push_log(f"  on_attack 効果 不使用 (skip)")
            return
        attacker = None
        for ip in [*me.characters, me.leader, *me.stages]:
            if ip.instance_id == attacker_iid:
                attacker = ip
                break
        if attacker is None:
            return
        # 支払い + enqueue
        if pay_don > 0:
            from_active = min(me.don_active, pay_don)
            me.don_active -= from_active
            me.don_rested += from_active
        bundle = state.effects_overlay.get(attacker.card.card_id) if state.effects_overlay else None
        if bundle is None:
            return
        eff = bundle.effects[eff_idx] if 0 <= eff_idx < len(bundle.effects) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        if cost.get("once_per_turn"):
            setattr(attacker, f"_on_attack_used_{eff_idx}", True)
        me_idx = state.players.index(me)
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
        for sub in chosen_do:
            if isinstance(sub, dict):
                execute_effect(sub, state, me, opp, self_inplay)
                if state.pending_choice is not None:
                    return
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
        state.push_log(
            f"  効果: 人間選択 → 自ライフ上{actual_depth}枚 並び替え {ordered}"
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
                me.trash_weakest_chara_for_field_full(state)
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

    if kind != "search_top_n":
        # 未知 kind は クリア のみ
        state.pending_choice = None
        return
    depth = int(choice.get("depth", 5))
    destination = choice.get("destination", "hand")
    rest_remain = choice.get("rest_remain", "bottom")
    rested_flag = bool(choice.get("rested", False))
    limit = int(choice.get("limit", 1))
    seen = me.deck[:depth]
    me.deck = me.deck[depth:]
    valid_picks = [i for i in picks if 0 <= i < len(seen)][:limit]
    picked = [seen[i] for i in valid_picks]
    remaining = [c for i, c in enumerate(seen) if i not in valid_picks]
    for c in picked:
        if destination == "play":
            if c.category != Category.CHARACTER:
                me.hand.append(c)
                continue
            if not me.can_play_character():
                me.trash_weakest_chara_for_field_full(state)
            ip = InPlay.of(c, rested=rested_flag, sickness=True)
            me.characters.append(ip)
            state.push_log(f"  効果: 人間選択 → 登場 {c.name}")
            if state.effects_overlay:
                trigger_on_play(state, me, state.opponent, ip, state.effects_overlay)
        else:  # hand
            me.hand.append(c)
            state.push_log(f"  効果: 人間選択 → 手札 {c.name}")
    if rest_remain == "trash":
        me.trash.extend(remaining)
        state.push_log(
            f"  効果: search_top_n 残り{len(remaining)}枚 → トラッシュ"
        )
    else:
        me.deck.extend(remaining)
    state.pending_choice = None


def _matches_filter(card: CardDef, filt: dict[str, Any]) -> bool:
    if not filt:
        return True
    # OR 結合: filt["or"] = [sub_filter_1, sub_filter_2, ...]
    # いずれかに マッチ すれば 全体 True (= 短絡)
    if "or" in filt:
        subs = filt["or"]
        if not any(_matches_filter(card, sub) for sub in subs):
            return False
    if "category" in filt and card.category.value != filt["category"]:
        return False
    if "category_in" in filt:
        cats = filt["category_in"]
        if isinstance(cats, str):
            cats = [cats]
        if card.category.value not in cats:
            return False
    if "cost_le" in filt and card.cost > int(filt["cost_le"]):
        return False
    if "cost_ge" in filt and card.cost < int(filt["cost_ge"]):
        return False
    if "cost_eq" in filt and card.cost != int(filt["cost_eq"]):
        return False
    if "power_le" in filt and card.power > int(filt["power_le"]):
        return False
    if "power_ge" in filt and card.power < int(filt["power_ge"]):
        return False
    if "power_eq" in filt and card.power != int(filt["power_eq"]):
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
    if "exclude_name" in filt and card.name == filt["exclude_name"]:
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
        if not ((feat and feat in card.features) or (name and card.name == name)):
            return False
    if "name" in filt and card.name != filt["name"]:
        return False
    if "name_in" in filt:
        names = filt["name_in"]
        if isinstance(names, str):
            names = [names]
        if card.name not in names:
            return False
    if "attribute" in filt and card.attribute != filt["attribute"]:
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
    # 自陣営: 登場したカード自身の on_play
    bundle = effects_overlay.get(self_inplay.card.card_id)
    has_self_on_play = bundle is not None and any(e.get("when") == "on_play" for e in bundle.effects)
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

    OP08-105 ジュエリー・ボニー (attacker 側) / OP05-107 スペーシー中尉 (defender 側) 等。
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, attacker, "on_opp_life_taken", effects_overlay)
    if went_to_hand:
        _enqueue_field_when(state, defender, "on_self_life_to_hand", effects_overlay)
    else:
        _enqueue_field_when(state, defender, "on_self_life_to_trash", effects_overlay)
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
    if not effects_overlay:
        return

    # 全 InPlay の静的フラグをリセット
    for player in state.players:
        for ip in [player.leader, *player.characters, *player.stages]:
            ip.static_buff = 0
            ip.static_ko_immune = False
            ip.static_ko_immune_from_source_power_le = -1
            ip.base_power_override = None
            ip.base_cost_override = None
            ip.attack_taunt = False
            ip.cannot_attack_static = False
            ip.protect_from_opp_effect = False
            ip.ko_immune_battle_attributes_in.clear()
            ip.ko_immune_battle_attributes_not_in.clear()
            ip.battle_ko_immune_static = False
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
                    # 常在内の set_ko_immune_from_source_power_le
                    # spec: {"target": "self", "threshold": 5000}
                    # OP14-003 「相手の元々のパワーN以下のキャラの効果でKOされない」
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
                    # 「対象は相手の効果でレストにされない」常在 (OP12-021 等)
                    # 簡略: protect_from_opp_effect で 代用 (= rest 含む opp 効果 全般 ブロック)
                    if "set_cannot_be_rested_static" in primitive:
                        spec = primitive["set_cannot_be_rested_static"]
                        if isinstance(spec, dict):
                            target_spec = spec.get("target", "self")
                        else:
                            target_spec = "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.protect_from_opp_effect = True
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
                        continue
                    # filter 付きの 場のキャラ コスト変更 静的効果 (OP10-042 ウソップ系)
                    # 公式 「自分のコスト2以上の特徴《ドレスローザ》を持つキャラすべてを、 コスト+1」 等。
                    # spec: {"filter": {"feature": "ドレスローザ", "cost_ge": 2}, "delta": 1,
                    #        "scope": "self" | "opp" (省略時 = "self")}
                    if "set_base_cost_filtered_static" in primitive:
                        spec = primitive["set_base_cost_filtered_static"]
                        filt = spec.get("filter", {})
                        scope = spec.get("scope", "self")
                        targets_pool = me.characters if scope == "self" else opp.characters
                        if "delta" in spec:
                            delta = int(spec["delta"])
                            for t in targets_pool:
                                if not _matches_filter(t.card, filt):
                                    continue
                                cur = t.base_cost_override if t.base_cost_override is not None else t.card.cost
                                t.base_cost_override = max(0, cur + delta)
                        elif "amount" in spec:
                            amount = int(spec["amount"])
                            for t in targets_pool:
                                if not _matches_filter(t.card, filt):
                                    continue
                                t.base_cost_override = amount
                        continue
                    execute_effect(primitive, state, me, opp, inplay)


def _enqueue_field_when(
    state: GameState,
    owner: Player,
    when: str,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """owner の場 (leader + characters) のうち、 指定 when を持つ全ての InPlay を enqueue。
    複数効果がある場合でもイベントは「カード単位」で 1 つ (= _execute_event が when 一致を全実行)。
    """
    candidates: list[InPlay] = [owner.leader] + list(owner.characters)
    owner_idx = state.players.index(owner)
    for ip in candidates:
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
        candidates = [c for c in from_chara if _matches_filter(c.card, filt)]
        if len(candidates) < need:
            return False
    # ko_self_with_filter
    ksf = cost.get("ko_self_with_filter")
    if ksf:
        if not any(_matches_filter(c.card, ksf) for c in owner.characters):
            return False
    return True


def _pay_end_of_turn_cost(
    state: GameState,
    owner: Player,
    opp: Player,
    source: InPlay,
    cost: dict,
    eff_idx: int,
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
            trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay)
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
    # discard_hand: random (= activate_main と 同 semantics、 modal 拡張 は 別 issue)
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0:
        import random as _rng
        rng = state.rng or _rng.Random()
        for _ in range(min(discard_n, len(me.hand))):
            i = rng.randrange(len(me.hand))
            me.trash.append(me.hand.pop(i))
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
            if not _matches_filter(c.card, filt):
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
            if _matches_filter(c.card, ksf):
                me.characters.remove(c)
                me.trash.append(c.card)
                if c.attached_dons > 0:
                    me.don_rested += c.attached_dons
                state.push_log(f"  ターン終了コスト: 自KO {c.card.name}")
                if state.effects_overlay:
                    trigger_on_ko(state, me, opp, c.card, state.effects_overlay, by_opp_effect=False)
                    trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
                break
    # once_per_turn フラグ
    if cost.get("once_per_turn"):
        setattr(source, f"_end_of_turn_used_{eff_idx}", True)


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
                        _pay_end_of_turn_cost(state, player, opp_for_pay, source, cost, idx)
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
                # cost 無し: 単純 fire
                eff_indexes_to_fire.append(idx)
                continue
            if not eval_all_conditions(eff, state, me, source_inplay):
                continue
            per_turn_key = f"_opp_attack_used_{idx}"
            if cost.get("once_per_turn") and getattr(source_inplay, per_turn_key, False):
                continue
            pay_don = int(cost.get("pay_don", 0))
            rest_don = int(cost.get("rest_self_don", 0))
            # pay_don は active + rested から、 rest_self_don は active のみから 取れる
            if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
                continue
            if rest_don > 0 and me.don_active < rest_don:
                continue
            discard_n = int(cost.get("discard_hand", 0))
            if discard_n > 0 and len(me.hand) < discard_n:
                continue
            if is_human_actor:
                # 人間 defender → pending_choice 候補 へ
                pending_costed_human.append((source_inplay, idx, eff))
                continue
            # AI: EV 判定 → 発動 価値 低い なら skip (= 旧 「常 fire」 から 改善)
            if not _ai_should_fire_opp_attack_cost(state, me, source_inplay, eff, attacker):
                continue
            # AI: 即時 支払 + fire
            # pay_don: ドン!!-N → don_active から N 枚 を don_remaining_in_deck に 戻す
            # (= fire_activate_main と 同 semantics)。
            if pay_don > 0:
                taken = min(pay_don, me.don_active)
                me.don_active -= taken
                me.don_remaining_in_deck += taken
                rest_more = min(pay_don - taken, me.don_rested)
                me.don_rested -= rest_more
                me.don_remaining_in_deck += rest_more
            if rest_don > 0:
                me.don_active -= rest_don
                me.don_rested += rest_don
            if discard_n > 0:
                import random as _rng
                rng = state.rng or _rng.Random()
                for _ in range(min(discard_n, len(me.hand))):
                    i = rng.randrange(len(me.hand))
                    me.trash.append(me.hand.pop(i))
            if cost.get("once_per_turn"):
                setattr(source_inplay, per_turn_key, True)
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
) -> None:
    """【相手のアタック時】(opp_attack) を enqueue (10-2-16-1)。
    me = アタックを受けているプレイヤー (= 効果の「自分」側)。
    opp = アタックしているプレイヤー。
    cost 持ち effect は 人間 defender に optional 確認 modal を 立てる。
    """
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(state, me, "opp_attack", effects_overlay, attacker=attacker)
    _maybe_resolve(state)


def trigger_on_opp_attack_on_leader(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【相手のアタック時】 (defender=自リーダー 限定) (opp_attack_on_leader)。
    OP03-001 ポートガス・D・エース等。
    AttackLeader 時のみ発火 (= opp_attack と並行)。 me = defender 側。"""
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(state, me, "opp_attack_on_leader", effects_overlay, attacker=attacker)
    _maybe_resolve(state)


def trigger_on_opp_attack_on_chara(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【相手のアタック時】 (defender=自キャラ 限定) (opp_attack_on_chara)。
    AttackCharacter 時のみ発火 (= opp_attack と並行)。 me = defender 側。"""
    if not effects_overlay:
        return
    _enqueue_opp_attack_with_cost(state, me, "opp_attack_on_chara", effects_overlay, attacker=attacker)
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
    if not effects_overlay or discard_count <= 0:
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
    state.last_chara_ko_victim_card = victim_card
    _enqueue_field_when(state, victim_owner, "on_self_chara_ko", effects_overlay)
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
) -> None:
    """「自分の場のドンがドンデッキに戻された時」 (on_self_don_returned_to_deck)。
    OP06-042 / OP06-076 / OP04-058 / OP12-040 等が登録する場の効果を発火。
    pay_don / return_self_don_to_deck 等の直後に呼ぶ。"""
    if not effects_overlay:
        return
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
                             "target_power_le", "target_power_ge",
                             "target_feature", "target_feature_contains",
                             "target_color", "target_name_exclude",
                             "target_name", "target_rested",
                             "by_opp_effect", "by_battle")
            }
            if extra_cond and not eval_condition(extra_cond, state, owner, inplay):
                continue
            # cost フィールド対応 (任意): cost が払えない場合は置換不可。
            # spec: {"cost": [<primitive>...]} を payability check で消費する。
            cost_specs = eff.get("cost", [])
            holder_card_id = inplay.card.card_id
            if cost_specs:
                if not _can_pay_replace_cost(state, owner, cost_specs, holder_card_id):
                    continue
                _pay_replace_cost(state, owner, cost_specs, holder_card_id)
            state.push_log(
                f"  離脱置換 ({when}): {victim.card.name} → {inplay.card.name} の効果で代替"
            )
            # victim target spec ("victim") のため state に 一時保存。
            # OP05-001 等 「代わりに victim 自身に power -1000」 系で利用。
            prev_replace_victim = getattr(state, "last_replace_victim", None)
            state.last_replace_victim = victim
            try:
                for primitive in eff.get("do", []):
                    execute_effect(primitive, state, owner, opp, inplay)
            finally:
                state.last_replace_victim = prev_replace_victim
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
            if not _can_pay_replace_cost(state, victim_owner, cost_specs, holder_card_id):
                continue
            _pay_replace_cost(state, victim_owner, cost_specs, holder_card_id)
        state.push_log(f"  レスト置換: {victim.card.name} の効果で発動")
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, victim_owner, actor, victim)
        return True
    return False


def _can_pay_replace_cost(
    state: GameState, me: Player, cost_specs: list[dict], holder_card_id: str | None = None
) -> bool:
    """replace_ko / replace_leave の cost 配列が払えるかチェック。 R3 拡張。

    holder_card_id を 渡すと once_per_turn の 使用 済み 判定 が 効く (= 既に 同一 ターン に
    発動済 なら 払えない 扱い)。
    """
    for cs in cost_specs:
        if "discard_hand_with_filter" in cs:
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
    state: GameState, me: Player, cost_specs: list[dict], holder_card_id: str | None = None
) -> None:
    """replace_ko / replace_leave の cost 配列を実行 (消費)。"""
    for cs in cost_specs:
        if "once_per_turn" in cs and bool(cs["once_per_turn"]):
            # 【ターン1回】 使用済みフラグ
            if holder_card_id is not None:
                me.once_per_turn_used.add(f"replace_opt::{holder_card_id}")
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
                idx = state.rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
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
        if cond["target_attribute"] != victim.card.attribute:
            return False
    if "target_cost_le" in cond:
        if victim.card.cost > int(cond["target_cost_le"]):
            return False
    if "target_power_le" in cond:
        # 公式 4-9: 「元々のパワー X 以下」は永続効果で変更されない CardDef オリジナル値で判定
        if victim.truly_original_power > int(cond["target_power_le"]):
            return False
    if "target_power_ge" in cond:
        # 公式 4-9: 「元々のパワー X 以上」も同様
        if victim.truly_original_power < int(cond["target_power_ge"]):
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
) -> None:
    """【KO時】を enqueue。 ko_card は既にトラッシュへ (10-2-17-2)。
    source_iid=None: 場から既に消えているので、 _execute_event 内では self_inplay=None で実行。

    副作用: state.last_chara_ko_victim_card = ko_card を一時設定 (= 後続の
    trigger_on_self_chara_ko / trigger_on_opp_chara_ko で payload-aware 条件用に使われる)。

    by_opp_effect: True = 相手の効果由来 KO、 False = バトル / 自分の効果 / cost KO。
        eval_condition で `by_opp_effect` / `by_battle` 条件と突合される。
    """
    # payload-aware 条件用 context を先に設定 (= trigger_on_self_chara_ko より先に呼ばれる場合に備える)
    state.last_chara_ko_victim_card = ko_card
    bundle = effects_overlay.get(ko_card.card_id)
    if bundle is None:
        return
    if not any(e.get("when") == "on_ko" for e in bundle.effects):
        return
    owner_idx = state.players.index(owner)
    enqueue_event(
        state,
        when="on_ko",
        owner_idx=owner_idx,
        source_card_id=ko_card.card_id,
        source_iid=None,
        payload={"by_opp_effect": bool(by_opp_effect)},
    )
    _maybe_resolve(state)


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
    enqueue_event(
        state,
        when="trigger",
        owner_idx=defender_idx,
        source_card_id=card.card_id,
        source_iid=None,
    )
    # 「相手がイベントか【トリガー】を発動した時」 (OP11-102 ケイミー 等)
    # defender = トリガー発火側 → attacker_player 側を opp として発火させる。
    trigger_opp_event_or_trigger_fired(
        state, attacker_player, defender, effects_overlay,
    )
    # 「自分の【トリガー】が発動した時」 (OP13-106 コニー 等)。
    # defender = トリガー発火側 (= 自分視点)。 defender の 場 で when="on_self_trigger_fired"
    # を 持つ カード を enqueue。
    _enqueue_field_when(state, defender, "on_self_trigger_fired", effects_overlay)
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
        # ヒューリスティック: 強力な効果 (除去/ドロー/ライフ復元) が含まれるなら発動
        for prim in eff.get("do", []):
            if any(k in prim for k in ("ko", "return_to_hand", "draw", "life_to_hand", "rest", "ko_self")):
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
    # イベント発動そのもの (= bundle 有無に関わらず) で相手側の opp_event_or_trigger_fired を発火。
    # 公式 「相手がイベントか【トリガー】を発動した時」 (OP11-102 ケイミー 等)。
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
        per_turn_key = f"_on_attack_used_{idx}"
        if cost.get("once_per_turn") and getattr(attacker, per_turn_key, False):
            continue
        pay_don = int(cost.get("pay_don", 0))
        if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
            continue
        # 人間 actor: user 確認 が必要 → 一旦 pending に
        if is_human_actor:
            pending_cost_effects.append((idx, eff))
            continue
        # AI: 即時 支払 + 発動
        if pay_don > 0:
            from_active = min(me.don_active, pay_don)
            me.don_active -= from_active
            me.don_rested += from_active
        if cost.get("once_per_turn"):
            setattr(attacker, per_turn_key, True)
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
        for idx, eff in enumerate(bundle.effects):
            if eff.get("when") == "on_attack" and not eff.get("cost"):
                paid_indexes.append(idx)
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
    if cost.get("rest_self") and inplay.rested:
        return False
    if cost.get("trash_self"):
        # 自身が場 (chara or stage) にいる必要
        if inplay not in me.characters and inplay not in me.stages:
            return False
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
        return False
    rest_self_don = int(cost.get("rest_self_don", 0))
    if rest_self_don > 0 and me.don_active < rest_self_don:
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
        candidates = [c for c in me.characters if _matches_filter(c.card, ko_filter)]
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
    once_per_turn = cost.get("once_per_turn", True)
    if once_per_turn and getattr(inplay, "_act_used", False):
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
                if not pp:
                    continue
                target = pp.get("target", "self")
                amount = int(pp.get("amount", 0))
                # opp 視点の self_leader / self → opp.leader 自身が強化される
                if target in ("self_leader", "self") and amount > 0:
                    total += amount
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
    candidates: list[InPlay] = [me.leader] + list(me.characters)
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
            out.append((inplay, eff))
    return out


def fire_activate_main(
    state: GameState,
    me: Player,
    opp: Player,
    inplay: InPlay,
    eff: EffectSpec,
) -> None:
    """起動メインの発火。 コストは同期支払い、 効果は enqueue (= effect_indexes payload 経由)。

    一度コストを払ったら効果実行は再評価せず必ず行う (= eval_condition は skip 可能)。
    実装上は _execute_event 側で if 句を再評価しているが、 起動メインの if 句は通常
    cost 判定とほぼ重複なので問題なし。

    log 順: 「起動メイン: X」 (header) → 「起動メインコスト: ...」 (cost) → 「効果: ...」 (effect)。
    cost を先に書くと、 人間が観戦時に「何の起動メインを発動した結果これを払ったのか」 が
    分からないため、 header を先に push する。
    """
    state.push_log(f"起動メイン: {inplay.card.name}")
    cost = eff.get("cost", {})
    # rest_self
    if cost.get("rest_self"):
        inplay.rested = True
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
            trigger_on_self_don_returned_to_deck(state, me, opp, state.effects_overlay)
    # rest_self_don N: アクティブドン N 枚を rested に
    rest_self_don = int(cost.get("rest_self_don", 0))
    if rest_self_don > 0:
        actual = min(rest_self_don, me.don_active)
        me.don_active -= actual
        me.don_rested += actual
        state.push_log(f"  起動メインコスト: アクティブドン {actual} レスト")
    # return_self_to_hand: self を 場 から 手札 に 戻す
    if cost.get("return_self_to_hand") and inplay in me.characters:
        me.characters.remove(inplay)
        me.hand.append(inplay.card)
        if inplay.attached_dons > 0:
            me.don_rested += inplay.attached_dons
            inplay.attached_dons = 0
        state.push_log(f"  起動メインコスト: 自 → 手札 {inplay.card.name}")
    # discard_hand N: 手札N枚ランダム捨て (簡略: 末尾から)
    discard_n = int(cost.get("discard_hand", 0))
    for _ in range(discard_n):
        if not me.hand:
            break
        idx = state.rng.randrange(len(me.hand))
        me.trash.append(me.hand.pop(idx))
        state.push_log(f"  起動メインコスト: 手札1捨て")
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
    # ko_self_with_filter: 自場の該当キャラ1枚KO
    ko_filter = cost.get("ko_self_with_filter")
    if ko_filter:
        candidates = [c for c in me.characters if _matches_filter(c.card, ko_filter)]
        if candidates:
            target = candidates[0]
            me.characters.remove(target)
            me.trash.append(target.card)
            if target.attached_dons > 0:
                me.don_rested += target.attached_dons
            state.push_log(f"  起動メインコスト: 自KO {target.card.name}")
            if state.effects_overlay:
                # me 側 victim、 me 側 cost (= 自爆 cost) → by_opp_effect=False
                trigger_on_ko(state, me, opp, target.card, state.effects_overlay, by_opp_effect=False)
                # 自KO なので on_self_chara_ko (= me 側) を発火
                trigger_on_self_chara_ko(state, me, opp, state.effects_overlay)
    # rest_self_target_name: 自場の name 一致キャラ/ステージを 1 枚 rest
    # 公式: 「自分の『ハチノス』1枚をレストにできる：効果」 (ST27-001 アバロ・ピサロ等)
    rest_filter_name = cost.get("rest_self_target_name") or cost.get("rest_self_target")
    if rest_filter_name:
        target_name = (
            rest_filter_name.get("name", "") if isinstance(rest_filter_name, dict)
            else str(rest_filter_name)
        )
        for ip in (list(me.characters) + list(me.stages)):
            if ip.card.name == target_name and not ip.rested:
                ip.rested = True
                state.push_log(f"  起動メインコスト: 自レスト {ip.card.name}")
                break
    # once_per_turn フラグ
    if cost.get("once_per_turn", True):
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
