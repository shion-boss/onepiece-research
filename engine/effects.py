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
                if not eval_condition(eff.get("if", {}), state, me, self_inplay):
                    continue
                for primitive in eff.get("do", []):
                    execute_effect(primitive, state, me, opp, self_inplay)
            return

        # 通常の when 一致 effects を全て発火
        for eff in bundle.effects:
            if eff.get("when") != when:
                continue
            if not eval_condition(eff.get("if", {}), state, me, self_inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, self_inplay)
    finally:
        state.current_source_card_id = prev_src_cid


def _maybe_resolve(state: GameState) -> None:
    """resolve_triggers をネスト呼び出ししない安全ラッパ。 trigger_* の末尾で呼ぶ。"""
    if state.resolving:
        return
    resolve_triggers(state)


# --------------------------------------------------------------------------- #
# 条件評価
# --------------------------------------------------------------------------- #
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
            # 自キャラ全員 (filter マッチ)
            filt = target_spec.get("filter", {})
            return [ip for ip in me.characters
                    if _matches_filter(ip.card, filt)]
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
        elif k == "trash_self_hand_random":
            n = int(v)
            for _ in range(n):
                if not me.hand:
                    break
                idx = state.rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
            state.push_log(f"  効果: 手札{n}枚捨て")
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
                    if state.effects_overlay:
                        # 効果による KO も【KO時】を発動 (10-2-1-3)
                        trigger_on_ko(state, opp, me, t.card, state.effects_overlay)
                        # 「相手のキャラが KO された時」 (= 自分の効果で KO した側)
                        trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
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
                else:
                    t.turn_buff += amount
            state.push_log(f"  効果: パワー{amount:+d} → {[t.card.name for t in targets]}")
        elif k == "rest":
            targets = _resolve_target(v, state, me, opp, self_inplay)
            for t in targets:
                t.rested = True
            state.push_log(f"  効果: レスト → {[t.card.name for t in targets]}")
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
                        state, opp, me, t, state.effects_overlay, by_opp_effect=True
                    ):
                        continue
                    opp.characters.remove(t)
                    opp.hand.append(t.card)
                    # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: 手札に戻す {t.card.name}")
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
            n = int(v)
            for _ in range(n):
                if me.life:
                    me.hand.append(me.life.pop(0))
            state.push_log(f"  効果: ライフ{n}枚を手札へ")
        elif k == "add_don":
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
            # 速攻付与 (登場ターン中もアタック可)。target = self / one_self_character
            target_spec = v if isinstance(v, str) else "self"
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
            spec = v if isinstance(v, dict) else {"target": "self", "keyword": "速攻"}
            target_spec = spec.get("target", "self")
            keyword = spec.get("keyword", "速攻")
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            for t in targets:
                t.granted_keywords.add(keyword)
            state.push_log(f"  効果: {keyword} 付与 → {[t.card.name for t in targets]}")
        elif k == "play_from_trash":
            # 「自分のトラッシュからキャラ1枚を登場」
            # spec: {"filter": {"category": "CHARACTER", "feature": "...", "cost_le": N},
            #        "limit": 1, "rested": bool}
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            rested = bool(spec.get("rested", False))
            found = 0
            new_trash = []
            for card in me.trash:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    # 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る (3-7-6-1)
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=rested, sickness=True)
                    me.characters.append(ip)
                    found += 1
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
            for t in targets:
                if t in opp.characters:
                    if t.protect_from_opp_effect or t.static_ko_immune:
                        continue
                    if state.effects_overlay and try_replace_ko(
                        state, opp, me, t, state.effects_overlay, by_opp_effect=True
                    ):
                        continue
                    opp.characters.remove(t)
                    opp.deck.append(t.card)
                    if t.attached_dons > 0:
                        opp.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} を相手デッキ底へ")
                elif t in me.characters:
                    me.characters.remove(t)
                    me.deck.append(t.card)
                    if t.attached_dons > 0:
                        me.don_rested += t.attached_dons
                    state.push_log(f"  効果: {t.card.name} を自デッキ底へ")
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
            spec = v if isinstance(v, dict) else {"target": "self_leader", "count": 1}
            target_spec = spec.get("target", "self_leader")
            n = int(spec.get("count", 1))
            n = min(n, me.don_active)
            if n <= 0:
                continue
            targets = _resolve_target(target_spec, state, me, opp, self_inplay)
            if not targets:
                continue
            # 1 体目に全部付与する単純実装 (複数対象は max +N 分散)
            target = targets[0]
            me.don_active -= n
            target.attached_dons += n
            state.push_log(f"  効果: ドン{n}付与 → {target.card.name} (P={target.power})")
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
            # spec: {"depth": N, "to": "top"|"bottom"|"choice"} (choice = AI が片方選ぶ; 現実装は top)
            # 公開情報のみで決まる効果なので AI に判断させる余地は少ない。 簡略実装:
            #   to="top": 順番そのままで戻す (= no-op の安全選択)
            #   to="bottom": 上 N 枚をデッキ末尾に移動
            #   to="choice": ヒューリスティック → トリガー持ち / コスト低が手前に来るよう並び替え
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
                    if not eval_condition(eff.get("if", {}), state, me, self_inplay):
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
        elif k == "ko_multi":
            # マルチターゲット KO。 v はターゲット仕様のリスト。
            # 例: [{"target": "one_opponent_character_cost_le_2"},
            #      {"target": "one_opponent_character_cost_le_1"}]
            # 各 spec を順に resolve → KO。 同じキャラを 2 度 KO しないよう dedup。
            if not isinstance(v, list):
                continue
            already_kod = set()
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
                        if state.effects_overlay:
                            trigger_on_ko(state, opp, me, t.card, state.effects_overlay)
                            trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
        elif k == "return_to_hand_multi":
            # マルチターゲット bounce (手札戻し)。
            if not isinstance(v, list):
                continue
            already_returned = set()
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
                            state, opp, me, t, state.effects_overlay, by_opp_effect=True
                        ):
                            already_returned.add(id(t))
                            continue
                        opp.characters.remove(t)
                        opp.hand.append(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: {t.card.name} を持ち主の手札へ")
                        already_returned.add(id(t))
        elif k == "return_to_deck_bottom_multi":
            # マルチターゲット 「持ち主のデッキの下に置く」。
            if not isinstance(v, list):
                continue
            already = set()
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
                            state, opp, me, t, state.effects_overlay, by_opp_effect=True
                        ):
                            already.add(id(t))
                            continue
                        opp.characters.remove(t)
                        opp.deck.append(t.card)
                        if t.attached_dons > 0:
                            opp.don_rested += t.attached_dons
                        state.push_log(f"  効果: {t.card.name} を持ち主のデッキ下へ")
                        already.add(id(t))
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
            for ip in list(me.characters):
                if ip is self_inplay:
                    continue
                me.characters.remove(ip)
                if ip.attached_dons > 0:
                    me.don_rested += ip.attached_dons
                me.deck.append(ip.card)
                state.push_log(f"  効果: {ip.card.name} を自デッキ下へ")
        elif k == "other_self_charas_to_trash":
            for ip in list(me.characters):
                if ip is self_inplay:
                    continue
                me.characters.remove(ip)
                if ip.attached_dons > 0:
                    me.don_rested += ip.attached_dons
                me.trash.append(ip.card)
                state.push_log(f"  効果: {ip.card.name} を trash へ")
                if state.effects_overlay:
                    trigger_on_ko(state, me, opp, ip.card, state.effects_overlay)
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
    if "color" in filt and filt["color"] not in card.color:
        return False
    if "exclude_name" in filt and card.name == filt["exclude_name"]:
        return False
    if "has_trigger" in filt and filt["has_trigger"]:
        if not (card.trigger and card.trigger.startswith("【トリガー】")):
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
    """
    bundle = effects_overlay.get(self_inplay.card.card_id)
    if bundle is None:
        return
    # on_play 効果が 1 つも無いなら enqueue 自体スキップ (キュー肥大化回避)
    if not any(e.get("when") == "on_play" for e in bundle.effects):
        return
    me_idx = state.players.index(me)
    enqueue_event(
        state,
        when="on_play",
        owner_idx=me_idx,
        source_card_id=self_inplay.card.card_id,
        source_iid=self_inplay.instance_id,
    )
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
                if not eval_condition(eff.get("if", {}), state, me, inplay):
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
) -> bool:
    """KO される直前の置換効果 (when="replace_ko") を試行。
    1 つでも発動・成功すれば True を返し、本来の KO をキャンセルさせる。

    overlay 例:
      "OP15-003": [{"when": "replace_ko",
                    "if": {"target": "self"},
                    "do": [{"trash_self_hand_random": 1}]}]
      "OP12-027": [{"when": "replace_ko",
                    "if": {"target": "other_self_chara",
                           "target_attribute": "斬",
                           "target_cost_le": 5,
                           "by_opp_effect": true},
                    "do": [{"rest": "self"}]}]
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
            if eff.get("when") != "replace_ko":
                continue
            if not _replace_ko_match(eff.get("if", {}), inplay, victim, by_opp_effect):
                continue
            # 通常の eval_condition (leader_feature 等) も適用
            extra_cond = {
                k: v for k, v in eff.get("if", {}).items()
                if k not in ("target", "target_attribute", "target_cost_le",
                             "target_power_le", "target_power_ge",
                             "target_feature", "by_opp_effect")
            }
            if extra_cond and not eval_condition(extra_cond, state, owner, inplay):
                continue
            state.push_log(
                f"  KO 置換: {victim.card.name} → {inplay.card.name} の効果で代替"
            )
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, owner, opp, inplay)
            return True
    return False


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
    """
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
        eval_condition(e.get("if", {}), state, defender, None) for e in trigger_effects
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
        if not eval_condition(eff.get("if", {}), state, defender, None):
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
    if bundle is None:
        return
    if not any(e.get("when") == "main" for e in bundle.effects):
        return
    me_idx = state.players.index(me)
    enqueue_event(
        state,
        when="main",
        owner_idx=me_idx,
        source_card_id=card.card_id,
        source_iid=None,
    )
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
    if bundle is None:
        return
    if not any(e.get("when") == "counter" for e in bundle.effects):
        return
    me_idx = state.players.index(me)
    enqueue_event(
        state,
        when="counter",
        owner_idx=me_idx,
        source_card_id=card.card_id,
        source_iid=None,
    )
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
        if not eval_condition(eff.get("if", {}), state, me, attacker):
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
    pay_don = int(cost.get("pay_don", 0))
    if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
        return False
    discard_n = int(cost.get("discard_hand", 0))
    if discard_n > 0 and len(me.hand) < discard_n:
        return False
    ko_filter = cost.get("ko_self_with_filter")
    if ko_filter:
        # filter 一致の自キャラが少なくとも 1 枚必要
        candidates = [c for c in me.characters if _matches_filter(c.card, ko_filter)]
        if not candidates:
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
        if not eval_condition(eff.get("if", {}), state, me, attacker):
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
            if not eval_condition(eff.get("if", {}), state, opp, inplay):
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
            if not eval_condition(eff.get("if", {}), state, me, inplay):
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
