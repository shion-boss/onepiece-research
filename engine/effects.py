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
) -> None:
    """単一の効果(`do` 配列の1要素)を実行。"""
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
        elif k == "ko":
            targets = _resolve_target(v, state, me, opp, self_inplay)
            for t in targets:
                if t in opp.characters:
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
                    if not me.can_play_character():
                        new_trash.append(card)
                        continue
                    ip = InPlay.of(card, rested=False, sickness=True)
                    me.characters.append(ip)
                    found += 1
                    state.push_log(f"  効果: トラッシュから登場 → {card.name}")
                    if state.effects_overlay:
                        trigger_on_play(state, me, opp, ip, state.effects_overlay)
                else:
                    new_trash.append(card)
            me.trash[:] = new_trash
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
                             "target_power_le", "target_feature", "by_opp_effect")
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
        # 「元々のパワー X 以下」相当 (override 反映済の base_power)
        if victim.base_power > int(cond["target_power_le"]):
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
    auto_fire=True (デフォルト) は「効果がある場合は常に発動」。
    """
    bundle = effects_overlay.get(card.card_id)
    if bundle is None:
        return False
    trigger_effects = [e for e in bundle.effects if e.get("when") == "trigger"]
    if not trigger_effects:
        return False
    if not auto_fire:
        return False
    state.push_log(f"  TRIGGER: {card.name}")
    # defender が「自分」、attacker_player が「相手」になる
    for eff in trigger_effects:
        if not eval_condition(eff.get("if", {}), state, defender, None):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, defender, attacker_player, None)
    return True


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
    bundle = effects_overlay.get(attacker.card.card_id)
    if bundle is None:
        return
    for eff in bundle.effects:
        if eff.get("when") != "on_attack":
            continue
        if not eval_condition(eff.get("if", {}), state, me, attacker):
            continue
        for primitive in eff.get("do", []):
            execute_effect(primitive, state, me, opp, attacker)


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
            if cost.get("rest_self") and inplay.rested:
                continue
            # cost.once_per_turn が False と明示されていない限り、ターン 1 回扱い
            once_per_turn = cost.get("once_per_turn", True)
            if once_per_turn and getattr(inplay, "_act_used", False):
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
    if cost.get("rest_self"):
        inplay.rested = True
    # cost.once_per_turn が False と明示されていない限り、ターン 1 回扱い
    if cost.get("once_per_turn", True):
        setattr(inplay, "_act_used", True)
    state.push_log(f"  起動メイン: {inplay.card.name}")
    for primitive in eff.get("do", []):
        execute_effect(primitive, state, me, opp, inplay)
