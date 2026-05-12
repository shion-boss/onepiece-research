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
        # それ以外 (on_attack/on_block 等) は途中で KO されたので発火中止
        if self_inplay is None and evt.when not in (
            "on_ko", "main", "counter", "trigger"
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
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, self_inplay)
    finally:
        state.current_source_card_id = prev_src_cid


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
        elif k == "played_chara_truly_original_cost_ge":
            # 直近の opp_chara_played カードの 「元々のコスト」 が N 以上 (OP12-081 コアラ)
            pc = getattr(state, "last_opp_chara_played_card", None)
            if pc is None or int(getattr(pc, "cost", 0) or 0) < int(v):
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
        elif k == "self_hand_count_le":
            if len(me.hand) > int(v):
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
def _resolve_target(
    target_spec: Any,
    state: GameState,
    me: Player,
    opp: Player,
    self_inplay: Optional[InPlay],
) -> list[InPlay]:
    """target 指定文字列または辞書から対象 InPlay リストを返す。"""
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
            # 自リーダー / キャラから filter にマッチする 1 枚 (パワー高い順)
            filt = target_spec.get("filter", {})
            cands = [ip for ip in [me.leader, *me.characters]
                     if _matches_filter(ip.card, filt)]
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "one_self_chara_filtered":
            # 自キャラのみから filter にマッチする 1 枚 (パワー高い順)
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.characters
                     if _matches_filter(ip.card, filt)]
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "all_self_chara_filtered":
            # 自キャラ全員 (filter マッチ)。 limit 指定で上限あり (= 「N 枚まで」)。
            filt = target_spec.get("filter", {})
            cands = [ip for ip in me.characters if _matches_filter(ip.card, filt)]
            limit = target_spec.get("limit")
            if limit is not None:
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
            # 追加条件: attached_don_ge, rested
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
                # 現在パワー条件 (= InPlay.power; "現在のパワー" 用)
                if "current_power_le" in filt and ip.power > int(filt["current_power_le"]):
                    continue
                cands.append(ip)
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
        if t == "one_opponent_inplay_filtered":
            # 相手リーダー or キャラ から filter にマッチする 1 枚
            filt = target_spec.get("filter", {})
            cands = [opp.leader, *opp.characters]
            cands = [ip for ip in cands if _matches_filter(ip.card, filt)]
            cands.sort(key=lambda ip: -ip.power)
            return cands[:1]
    if target_spec in (None, "self") and self_inplay is not None:
        return [self_inplay]
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
    # 候補を power 高い順にソートして「最も脅威となるキャラ」を狙う簡略化
    if target_spec == "one_opponent_character_le_5000":
        cands = sorted(
            [c for c in opp.characters if c.power <= 5000],
            key=lambda c: -c.power,
        )
        return cands[:1]
    if target_spec == "one_opponent_character_le_4000":
        cands = sorted(
            [c for c in opp.characters if c.power <= 4000],
            key=lambda c: -c.power,
        )
        return cands[:1]
    if target_spec == "one_opponent_character_any":
        cands = sorted(opp.characters, key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_opp_chara_blocker":
        # 相手の【ブロッカー】 を持つキャラ 1 枚 (power 高い順)。 ST30-012 ルフィ等。
        cands = [c for c in opp.characters if c.is_blocker_now]
        cands.sort(key=lambda ip: -ip.power)
        return cands[:1]
    if target_spec == "one_opponent_inplay_any":
        # リーダー or キャラ 1 枚 (= 「相手のリーダーかキャラ 1 枚まで」)。
        # 脅威優先: パワー高いキャラ → なければリーダー
        cands = sorted(opp.characters, key=lambda c: -c.power)
        if cands:
            return cands[:1]
        return [opp.leader]
    if target_spec == "one_self_character_filtered":
        # spec が辞書じゃないと filter は外から渡せないので、 caller 側でラップ済みを期待。
        # 単独で来た場合は全自キャラから最強を返す (= フォールバック)
        cands = sorted(me.characters, key=lambda c: -c.power)
        return cands[:1]
    if target_spec == "one_opponent_rested_character_le_5000":
        cands = sorted(
            [c for c in opp.characters if c.rested and c.power <= 5000],
            key=lambda c: -c.power,
        )
        return cands[:1]
    if target_spec == "all_self_characters":
        return list(me.characters)
    if target_spec == "all_self_team":
        return [me.leader] + list(me.characters)
    if target_spec == "one_self_team_any":
        # 自分のリーダー or キャラ 1 枚 (power 高い順)。
        # 公式: 「自分のリーダーかキャラ1枚まで」 用。 OP11-119 コビー 等。
        cands = sorted([me.leader] + list(me.characters), key=lambda ip: -ip.power)
        return cands[:1]

    # --- パラメトリック target (regex マッチ) ---
    if isinstance(target_spec, str):
        # one_opponent_character_cost_le_N (1 体、最高パワー)
        m = re.match(r"one_opponent_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.card.cost <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # any_opponent_character_cost_le_N (全員)
        m = re.match(r"any_opponent_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if c.card.cost <= n]

        # one_opponent_rested_character_cost_le_N (レスト + コスト N 以下、1 体)
        m = re.match(r"one_opponent_rested_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.rested and c.card.cost <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_opponent_character_power_le_N (パワー N 以下、1 体)
        m = re.match(r"one_opponent_character_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.power <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_opponent_character_power_eq_N (パワー N ぴったり、 1 体)。
        # 公式「元々のパワー N」 用 (= CardDef.power で判定)。
        m = re.match(r"one_opponent_character_power_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.card.power == n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_opponent_character_attached_don_ge_N (= 相手のドン N 枚以上付与キャラ、 1 体)
        # OP15-001 等
        m = re.match(r"one_opponent_character_attached_don_ge_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.attached_dons >= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_self_character_cost_le_N (= 自分のキャラ コスト N 以下、 1 体, power 最大)
        m = re.match(r"one_self_character_cost_le_(\d+)(?:cost)?$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in me.characters if c.card.cost <= n],
                key=lambda c: -c.power,
            )
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

            cands = sorted(
                [
                    c for c in me.characters
                    if c.card.cost <= n and not _has_on_play(c.card)
                ],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_opponent_rested_character_power_le_N (レスト + パワー N 以下)
        m = re.match(r"one_opponent_rested_character_power_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.rested and c.power <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_opponent_character_cost_eq_N / cost_0 等 (= ぴったり N コスト)
        m = re.match(r"one_opponent_character_cost_(?:eq_)?(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.card.cost == n],
                key=lambda c: -c.power,
            )
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
            cands = sorted(
                [c for c in me.characters if c.card.cost <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # one_self_character_cost_eq_N (= 自分の cost N ぴったりキャラ 1 枚)
        m = re.match(r"one_self_character_cost_eq_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in me.characters if c.card.cost == n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # any_opp_inplay_n_N (= 相手のリーダーかキャラ 合計 N 枚まで)
        # 脅威優先: パワー高いキャラ N 体 (キャラが N 未満なら リーダーも追加)
        m = re.match(r"any_opp_inplay_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(opp.characters, key=lambda c: -c.power)
            # キャラ N 体未満なら リーダーで補う (= 全ての可能対象を返す)
            if len(cands) < n:
                cands = list(cands) + [opp.leader]
            return cands[:n]

        # any_opp_rested_chara_n_N (= 相手のレストのキャラ N 体まで)
        m = re.match(r"any_opp_rested_chara_n_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.rested],
                key=lambda c: -c.power,
            )
            return cands[:n]

        # one_self_character_named_X (名前一致セレクタ。 X は 「エネル」 等)
        m = re.match(r"one_self_character_named_(.+)$", target_spec)
        if m:
            target_name = m.group(1)
            cands = [c for c in me.characters if c.card.name == target_name]
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
            cands = sorted(
                [c for c in me.characters if feat in c.card.features],
                key=lambda c: -c.power,
            )
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
            cands = sorted(
                [c for c in opp.characters if c.card.cost <= n],
                key=lambda c: -c.power,
            )
            if cands:
                return cands[:1]
            return [opp.leader]

        # one_self_character_any (= 自分の任意 1 体、 パワー高い順)
        if target_spec == "one_self_character_any":
            cands = sorted(me.characters, key=lambda c: -c.power)
            return cands[:1]

        # other_self_chara (= self 以外の自キャラ 1 体)
        if target_spec == "other_self_chara":
            cands = [c for c in me.characters if c is not self_inplay]
            return cands[:1]

        # self_inplay_choice (= 自リーダーまたはキャラ 1 体、 リーダー優先)
        if target_spec == "self_inplay_choice":
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
            targets = _resolve_target(v, state, me, opp, self_inplay)
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
                        trigger_on_ko(state, opp, me, t.card, state.effects_overlay)
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
                elif src == "self_chara_feature_count":
                    feat = amount_per.get("feature", "")
                    src_val = sum(1 for c in me.characters if feat in c.card.features)
                elif src == "opp_don_total":
                    src_val = opp.don_active + opp.don_rested + opp.leader.attached_dons + sum(c.attached_dons for c in opp.characters)
                amount += (src_val // divisor) * mult

            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                # AI 優先順位: 相手アクティブキャラ (最も脅威) > opp.don_active > opp.don_rested (= 無意味だが順序保持)。
                active_charas = [c for c in opp.characters if not c.rested and not c.cannot_be_rested_buff]
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
            targets = _resolve_target(v, state, me, opp, self_inplay)
            actually_rested = []
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
                was_rested = t.rested
                t.rested = True
                actually_rested.append(t)
                # 「このキャラがレストになった時」 trigger (OP14-027 シャンクス等)
                if not was_rested and state.effects_overlay and v_owner is not None:
                    trigger_on_self_rested(state, v_owner, v_actor, t, state.effects_overlay)
            state.push_log(f"  効果: レスト → {[t.card.name for t in actually_rested]}")
        elif k == "rest_self_cards":
            # 自分のリーダー/キャラから N 枚をレスト。 AI 簡易: アクティブの中から power 低い順。
            n = int(v) if not isinstance(v, dict) else int(v.get("count", 1))
            actives = [me.leader] + list(me.characters)
            actives = [ip for ip in actives if not ip.rested]
            actives.sort(key=lambda ip: ip.power)
            for ip in actives[:n]:
                ip.rested = True
            state.push_log(f"  効果: 自カード{n}枚レスト → {[ip.card.name for ip in actives[:n]]}")
        elif k == "return_to_hand":
            targets = _resolve_target(v, state, me, opp, self_inplay)
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
                    opp.hand.append(t.card)
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
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
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
            spec = v if isinstance(v, dict) else {}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            sickness = bool(spec.get("sickness", True))
            found = 0
            picked: list[CardDef] = []
            remaining: list[CardDef] = []
            for c in me.deck:
                if (
                    found < limit
                    and c.category == Category.CHARACTER
                    and _matches_filter(c, filt)
                ):
                    # 公式 3-7-6-1: 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る
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
            # サーチ後はシャッフル (公式 8-7-3-3)
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
            me.hand.extend(picked)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            from_cands = _resolve_target(from_target, state, me, opp, self_inplay)
            if not from_cands:
                state.push_log("  効果: power-copy 対象なし (不発)")
                return False
            source_ip = from_cands[0]
            to_cands = _resolve_target(to_target, state, me, opp, self_inplay)
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
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            unique_name = bool(spec.get("unique_name", False))
            found = 0
            seen_names: set[str] = set()
            new_trash = []
            for card in me.trash:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    if unique_name and card.name in seen_names:
                        # name 重複: 登場させずトラッシュに残す
                        new_trash.append(card)
                        continue
                    # 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る (3-7-6-1)
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
            # 「自分の手札からキャラ1枚を 0 コストで登場」(緑紫ルフィ起動メイン等)。
            # spec: {"filter": {"feature": "...", "cost_le": N}, "limit": 1, "rested": bool}
            # 通常の PlayCharacter と異なり、 コスト無視 (= 効果代替の登場)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            found = 0
            new_hand = []
            for card in me.hand:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    # 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る (3-7-6-1)
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    found += 1
                    label = "レストで" if rested else ""
                    state.push_log(f"  効果: 手札から{label}登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_hand.append(card)
            me.hand[:] = new_hand
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            for t in targets:
                t.ko_immune_until_turn_end = True
            state.push_log(f"  効果: KO 耐性 → {[t.card.name for t in targets]}")
        elif k == "set_cannot_attack":
            # ターン終了時までアタック不可。target = "one_opponent_character_*" 等
            target_spec = v if isinstance(v, str) else "one_opponent_character_any"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            for t in targets:
                t.cannot_attack_until_turn_end = True
            state.push_log(f"  効果: アタック不可 → {[t.card.name for t in targets]}")
        elif k == "stay_rested_next_refresh":
            # 「次の (相手の) リフレッシュフェイズでアクティブにならない」
            # target = "one_opponent_character_*" など。多くは rest 効果と組み合わせる
            target_spec = v if isinstance(v, str) else "one_opponent_character_any"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            for t in targets:
                t.stay_rested_next_refresh = True
            state.push_log(f"  効果: 次リフレッシュ非アクティブ → {[t.card.name for t in targets]}")
        elif k == "cost_minus":
            # 「相手キャラ1枚のコスト-N」(ターン中)。base_cost 判定に反映される。
            # spec: {"target": "one_opponent_character_any", "amount": 10}
            spec = v if isinstance(v, dict) else {"target": "one_opponent_character_any", "amount": int(v)}
            target_spec = spec.get("target", "one_opponent_character_any")
            amount = int(spec.get("amount", 1))
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            for t in targets:
                t.cost_minus_until_turn_end += amount
            state.push_log(f"  効果: コスト-{amount} → {[t.card.name for t in targets]}")
        elif k == "redirect_attack":
            # OP14-060 紫ドフラミンゴ用「アタック対象変更」。
            # opp_attack トリガー内でセット → AttackLeader/Char 処理が対象を変更。
            # spec: "self_leader" または特定キャラ iid (簡略: self_leader 固定)
            target_spec = v if isinstance(v, str) else "self_leader"
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
        elif k == "keep_opp_rested_don_next_refresh":
            # 「相手のレストのドン!! N 枚までは、 次の相手のリフレッシュでアクティブにならない」
            # OP10-033 ナミ 等。 spec: int N | dict {"amount": N}
            n_spec = int(v) if not isinstance(v, dict) else int(v.get("amount", 1))
            actually = min(n_spec, opp.don_rested)
            opp.next_refresh_kept_rested_don += actually
            state.push_log(f"  効果: 相手レストドン {actually} 枚 次リフレッシュで起きない")
        elif k == "set_cannot_rest":
            # 「対象は、 次の (相手) ターン終了時まで、 レストにできない」 (OP14-033 等)。
            # rest プリミティブで cannot_be_rested_buff のあるキャラはスキップされる。
            # 適用時 applier_idx と applied_turn を記録し、 _reset_turn_buff でクリア。
            target_spec = v if isinstance(v, str) else (v or {}).get("target", "all_self_characters")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                            trigger_on_ko(state, me, opp, t.card, state.effects_overlay)
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
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay)
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
                targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay)
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
                targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                        opp.hand.append(t.card)
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
                targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            spec = v if isinstance(v, dict) else {"filter": {}, "count": int(v) if isinstance(v, int) else 1}
            filt = spec.get("filter", {})
            count = int(spec.get("count", 1))
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                    trigger_on_ko(state, me, opp, ip.card, state.effects_overlay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            seen = target_pl.life[:depth]
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
                targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
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
        # execute_effect は基本 True 返却 (現状)。将来各プリミティブで失敗判定するなら更新
        prev_succeeded = result if result is not None else True


def _matches_filter(card: CardDef, filt: dict[str, Any]) -> bool:
    if not filt:
        return True
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
            ip.base_power_override = None
            ip.base_cost_override = None
            ip.attack_taunt = False
            ip.cannot_attack_static = False
            ip.protect_from_opp_effect = False
            ip.ko_immune_battle_attributes_in.clear()
            ip.ko_immune_battle_attributes_not_in.clear()
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
                    if "set_ko_immune" in primitive:
                        target_spec = primitive["set_ko_immune"] if isinstance(primitive["set_ko_immune"], str) else "self"
                        targets = _resolve_target(target_spec, state, me, opp, inplay)
                        for t in targets:
                            t.static_ko_immune = True
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
                    # 「属性 X を持つカードとのバトルで KO されない」 (P-052 ミホーク等)
                    # spec: {"target": "self", "attributes": ["斬"], "negate": false}
                    #   negate=True なら 「属性 X を持たない」 限定 (P-025 スモーカー)
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


def trigger_end_of_turn(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """エンドフェイズの自動効果を enqueue (公式 6-6-1-1)。
    順序: ターン側【自分のターン終了時】→ 非ターン側【相手のターン終了時】。
    """
    if not effects_overlay:
        return
    me = state.turn_player
    opp = state.opponent
    _enqueue_field_when(state, me, "end_of_turn", effects_overlay)
    _enqueue_field_when(state, opp, "opp_end_of_turn", effects_overlay)
    _maybe_resolve(state)


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
    """
    if not effects_overlay:
        return
    _enqueue_field_when(state, me, "opp_attack", effects_overlay)
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
    _enqueue_field_when(state, me, "opp_attack_on_leader", effects_overlay)
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
    _enqueue_field_when(state, me, "opp_attack_on_chara", effects_overlay)
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
                             "target_feature", "target_color",
                             "target_name_exclude", "by_opp_effect")
            }
            if extra_cond and not eval_condition(extra_cond, state, owner, inplay):
                continue
            # cost フィールド対応 (任意): cost が払えない場合は置換不可。
            # spec: {"cost": [<primitive>...]} を payability check で消費する。
            cost_specs = eff.get("cost", [])
            if cost_specs:
                if not _can_pay_replace_cost(state, owner, cost_specs):
                    continue
                _pay_replace_cost(state, owner, cost_specs)
            state.push_log(
                f"  離脱置換 ({when}): {victim.card.name} → {inplay.card.name} の効果で代替"
            )
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, owner, opp, inplay)
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
        if cost_specs:
            if not _can_pay_replace_cost(state, victim_owner, cost_specs):
                continue
            _pay_replace_cost(state, victim_owner, cost_specs)
        state.push_log(f"  レスト置換: {victim.card.name} の効果で発動")
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, victim_owner, actor, victim)
        return True
    return False


def _can_pay_replace_cost(
    state: GameState, me: Player, cost_specs: list[dict]
) -> bool:
    """replace_ko / replace_leave の cost 配列が払えるかチェック。 R3 拡張。"""
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
        else:
            # 未対応 cost は支払不能扱い (= 公式 4-10 解釈不能→False)
            return False
    return True


def _pay_replace_cost(
    state: GameState, me: Player, cost_specs: list[dict]
) -> None:
    """replace_ko / replace_leave の cost 配列を実行 (消費)。"""
    for cs in cost_specs:
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
    if "target_color" in cond:
        if cond["target_color"] not in victim.card.color:
            return False
    if "target_name_exclude" in cond:
        excl = cond["target_name_exclude"]
        if isinstance(excl, str):
            excl = [excl]
        if victim.card.name in excl:
            return False
    return True


def trigger_on_ko(
    state: GameState,
    owner: Player,
    opp: Player,
    ko_card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【KO時】を enqueue。 ko_card は既にトラッシュへ (10-2-17-2)。
    source_iid=None: 場から既に消えているので、 _execute_event 内では self_inplay=None で実行。

    副作用: state.last_chara_ko_victim_card = ko_card を一時設定 (= 後続の
    trigger_on_self_chara_ko / trigger_on_opp_chara_ko で payload-aware 条件用に使われる)。
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
    if has_counter:
        me_idx = state.players.index(me)
        enqueue_event(
            state,
            when="counter",
            owner_idx=me_idx,
            source_card_id=card.card_id,
            source_iid=None,
        )
    # カウンターイベントも 「イベント発動」 に該当 → 相手側の opp_event_or_trigger_fired 発火。
    trigger_opp_event_or_trigger_fired(state, opp, me, effects_overlay)
    # カウンターイベント発動側でも on_self_event_played を発火 (公式 8-1-2: 発動者基準)。
    trigger_self_event_played(state, me, opp, effects_overlay)
    _maybe_resolve(state)


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
    """
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    paid_indexes: list[int] = []
    has_costless = False
    for idx, eff in enumerate(bundle.effects):
        if eff.get("when") != "on_attack":
            continue
        cost = eff.get("cost") or {}
        if not cost:
            has_costless = True
            continue
        if not eval_all_conditions(eff, state, me, attacker):
            continue
        # once_per_turn 判定
        per_turn_key = f"_on_attack_used_{idx}"
        if cost.get("once_per_turn") and getattr(attacker, per_turn_key, False):
            continue
        pay_don = int(cost.get("pay_don", 0))
        if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
            continue
        # 支払い (active 優先で rested へ)
        if pay_don > 0:
            from_active = min(me.don_active, pay_don)
            me.don_active -= from_active
            me.don_rested += from_active
        if cost.get("once_per_turn"):
            setattr(attacker, per_turn_key, True)
        paid_indexes.append(idx)
    me_idx = state.players.index(me)
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
    """
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
                trigger_on_ko(state, me, opp, target.card, state.effects_overlay)
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
    state.push_log(f"  起動メイン: {inplay.card.name}")
    # effect 本体は enqueue (= 集中ドレインで実行)。 bundle 内 effect index を解決して payload に。
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
