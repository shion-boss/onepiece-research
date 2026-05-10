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
        elif k == "opp_leader_attribute" and opp is not None:
            # 相手リーダーの属性 (例: "斬"、緑ミホーク "斬がある場合 +1000")
            if v != opp.leader.card.attribute:
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
        m = re.match(r"one_opponent_character_cost_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            cands = sorted(
                [c for c in opp.characters if c.card.cost <= n],
                key=lambda c: -c.power,
            )
            return cands[:1]

        # any_opponent_character_cost_le_N (全員)
        m = re.match(r"any_opponent_character_cost_le_(\d+)$", target_spec)
        if m:
            n = int(m.group(1))
            return [c for c in opp.characters if c.card.cost <= n]

        # one_opponent_rested_character_cost_le_N (レスト + コスト N 以下、1 体)
        m = re.match(r"one_opponent_rested_character_cost_le_(\d+)$", target_spec)
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
                    if t.ko_immune_until_turn_end or t.static_ko_immune:
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
                else:
                    t.turn_buff += amount
            state.push_log(f"  効果: パワー{amount:+d} → {[t.card.name for t in targets]}")
        elif k == "rest":
            targets = _resolve_target(v, state, me, opp, self_inplay)
            for t in targets:
                t.rested = True
            state.push_log(f"  効果: レスト → {[t.card.name for t in targets]}")
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
            # spec: {"filter": {"category": "CHARACTER", "feature": "...", "cost_le": N}, "limit": 1}
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            found = 0
            new_trash = []
            for card in me.trash:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    # 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る (3-7-6-1)
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=False, sickness=True)
                    me.characters.append(ip)
                    found += 1
                    state.push_log(f"  効果: トラッシュから登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_trash.append(card)
            me.trash[:] = new_trash
        elif k == "play_from_hand":
            # 「自分の手札からキャラ1枚を 0 コストで登場」(緑紫ルフィ起動メイン等)。
            # spec: {"filter": {"feature": "...", "cost_le": N}, "limit": 1}
            # 通常の PlayCharacter と異なり、 コスト無視 (= 効果代替の登場)。
            spec = v if isinstance(v, dict) else {"filter": {}, "limit": 1}
            filt = spec.get("filter", {})
            limit = int(spec.get("limit", 1))
            found = 0
            new_hand = []
            for card in me.hand:
                if found < limit and card.category == Category.CHARACTER and _matches_filter(card, filt):
                    # 5 枚埋まり時は最弱 1 枚 trash で空き枠を作る (3-7-6-1)
                    if not me.can_play_character():
                        me.trash_weakest_chara_for_field_full(state)
                    ip = InPlay.of(card, rested=False, sickness=True)
                    me.characters.append(ip)
                    found += 1
                    state.push_log(f"  効果: 手札から登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_hand.append(card)
            me.hand[:] = new_hand
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
    if "feature" in filt and filt["feature"] not in card.features:
        return False
    if "color" in filt and filt["color"] not in card.color:
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
    """キャラ登場時のトリガー処理。"""
    bundle = effects_overlay.get(self_inplay.card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "on_play":
            continue
        if not eval_condition(eff.get("if", {}), state, me, self_inplay):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, self_inplay)


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


def trigger_turn_start(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """ターン開始時の自動効果発動 (公式 6-2-1-1-2)。
    REFRESH 内で発動。順序: ターン側「自分のターン開始時」 → 非ターン側「相手のターン開始時」。
    overlay の when:"on_turn_start" / "opp_turn_start"。
    """
    if not effects_overlay:
        return

    me = state.turn_player
    opp = state.opponent

    # Step 1: ターン側 (自分のターン開始時)
    candidates = [me.leader] + list(me.characters)
    for inplay in candidates:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "on_turn_start":
                continue
            if not eval_condition(eff.get("if", {}), state, me, inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, inplay)

    # Step 2: 非ターン側 (相手のターン開始時)
    candidates_opp = [opp.leader] + list(opp.characters)
    for inplay in candidates_opp:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "opp_turn_start":
                continue
            if not eval_condition(eff.get("if", {}), state, opp, inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, opp, me, inplay)


def trigger_end_of_turn(
    state: GameState,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """エンドフェイズの自動効果発動 (公式 6-6-1-1)。

    順序:
    1. ターンプレイヤー側の【自分のターン終了時】効果
    2. 非ターンプレイヤー側の【相手のターン終了時】効果

    各カテゴリ内では複数効果あればプレイヤーが任意順 (現実装は出現順)。
    """
    if not effects_overlay:
        return

    me = state.turn_player
    opp = state.opponent

    # Step 1: ターン側の【自分のターン終了時】
    candidates = [me.leader] + list(me.characters)
    for inplay in candidates:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "end_of_turn":
                continue
            if not eval_condition(eff.get("if", {}), state, me, inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, inplay)

    # Step 2: 非ターン側の【相手のターン終了時】
    candidates_opp = [opp.leader] + list(opp.characters)
    for inplay in candidates_opp:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "opp_end_of_turn":
                continue
            if not eval_condition(eff.get("if", {}), state, opp, inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, opp, me, inplay)


def trigger_on_opp_attack(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【相手のアタック時】(opp_attack) 効果の発動 (10-2-16-1)。

    me = アタックを受けているプレイヤー。
    opp = アタックしているプレイヤー (= attacker の持ち主)。
    me 側の leader + characters のうち when:"opp_attack" を持つカードを発動。
    """
    if not effects_overlay:
        return
    candidates: list[InPlay] = [me.leader] + list(me.characters)
    for inplay in candidates:
        bundle = effects_overlay.get(inplay.card.card_id)
        if bundle is None:
            continue
        for eff in bundle.effects:
            if eff.get("when") != "opp_attack":
                continue
            if not eval_condition(eff.get("if", {}), state, me, inplay):
                continue
            for primitive in eff.get("do", []):
                execute_effect(primitive, state, me, opp, inplay)


def trigger_on_block(
    state: GameState,
    me: Player,
    opp: Player,
    blocker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【ブロック時】(on_block) 効果の発動 (10-2-15-1)。

    me = ブロッカーを発動した側 (アタックを受けている側)。
    blocker = ブロッカーとして使われた InPlay。
    """
    if not effects_overlay:
        return
    bundle = effects_overlay.get(blocker.card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "on_block":
            continue
        if not eval_condition(eff.get("if", {}), state, me, blocker):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, blocker)


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
    return True


def trigger_on_ko(
    state: GameState,
    owner: Player,
    opp: Player,
    ko_card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【KO時】効果の発動。ko_card は既にトラッシュへ移動済 (10-2-17-2 の特例)。

    owner: KO されたキャラの持ち主 (= 効果の "自分"側)
    opp: KO した側の対戦相手
    """
    bundle = effects_overlay.get(ko_card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "on_ko":
            continue
        if not eval_condition(eff.get("if", {}), state, owner, None):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, owner, opp, None)


def trigger_lifecard_trigger(
    state: GameState,
    defender: Player,
    attacker_player: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
    auto_fire: bool = True,
) -> bool:
    """ライフカードの【トリガー】効果を発動。発動した場合 True (カードはトラッシュへ)、
    発動しなかった (or 発動できなかった) 場合 False (カードは手札へ)。

    overlay 上は when:"trigger" で記述。
    公式 10-1-5: プレイヤーは発動するか選べる。
    auto_fire=True: 効果ヒューリスティックで「発動すべきなら発動」(現実装は基本発動)。
    auto_fire=False: 発動しない (= 手札に加える、保持を選ぶ)。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return False
    trigger_effects = [e for e in bundle.effects if e.get("when") == "trigger"]
    if not trigger_effects:
        return False
    if not auto_fire:
        return False
    # 発動可能な効果が存在するかを最終チェック (eval_condition で 1 つでも True)
    fireable = [e for e in trigger_effects if eval_condition(e.get("if", {}), state, defender, None)]
    if not fireable:
        return False
    state.push_log(f"  TRIGGER: {card.name}")
    for eff in fireable:
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, defender, attacker_player, None)
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
    """【メイン】イベントカード発動時の効果実行 (PlayEvent から呼ぶ)。

    overlay 上は when:"main" で記述。発動コストは PlayEvent 側で支払い済み。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "main":
            continue
        if not eval_condition(eff.get("if", {}), state, me, None):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, None)


def trigger_counter_event(
    state: GameState,
    me: Player,
    opp: Player,
    card: CardDef,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【カウンター】イベントカード発動時の効果実行 (7-1-3-1-2)。

    overlay 上は when:"counter" で記述。me=防御側 (アタックを受けている側)。
    発動コストは呼び出し側で支払い済み。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "counter":
            continue
        if not eval_condition(eff.get("if", {}), state, me, None):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, None)


def trigger_on_attack(
    state: GameState,
    me: Player,
    opp: Player,
    attacker: InPlay,
    effects_overlay: dict[str, CardEffectBundle],
) -> None:
    """【アタック時】効果。 effect の `cost` フィールドがあれば支払い処理を行う:
    - `once_per_turn`: True なら 1 ターン 1 回まで (`_on_attack_used_<idx>` で管理)
    - `pay_don N`: 場のドンを N 枚レストにする (active 優先 → rested)。 不足時は発動不可
    cost が無い場合は無条件発動 (互換維持)。
    """
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    for idx, eff in enumerate(bundle.effects):
        if eff.get("when") != "on_attack":
            continue
        if not eval_condition(eff.get("if", {}), state, me, attacker):
            continue
        cost = eff.get("cost") or {}
        # once_per_turn 判定 (effect index ごと管理。 同カードに複数 on_attack あっても独立)
        per_turn_key = f"_on_attack_used_{idx}"
        if cost.get("once_per_turn") and getattr(attacker, per_turn_key, False):
            continue
        pay_don = int(cost.get("pay_don", 0))
        if pay_don > 0 and (me.don_active + me.don_rested) < pay_don:
            continue  # ドン不足 → 発動不可
        # ドン支払い: active から優先的にレストへ
        if pay_don > 0:
            from_active = min(me.don_active, pay_don)
            me.don_active -= from_active
            me.don_rested += from_active
            remaining = pay_don - from_active
            if remaining > 0:
                # rested → ドン!!デッキへ戻す動きが厳密 (公式) だが、 簡略でレスト維持の総数からは引く
                # ただし on_attack のコストはほぼ active のみで足りるので remaining=0 想定
                pass
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, attacker)
        # once_per_turn フラグ立て
        if cost.get("once_per_turn"):
            setattr(attacker, per_turn_key, True)


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
    for primitive in eff.get("do", []):
        execute_effect(primitive, state, me, opp, inplay)
