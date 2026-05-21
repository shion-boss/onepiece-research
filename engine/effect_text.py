"""DSL → 公式テキスト風 日本語 renderer。

主目的: db/card_effects.json の DSL 実装が 公式テキスト と 整合しているか 機械的に audit する。

副目的: 人間プレイ UI / AI 判断 UI で 「この効果は何か」 を 自然な日本語で 提示する。

設計方針:
- 忠実性 最優先: DSL の 全パラメータ (= target/filter/amount/duration/condition) を 漏れなく 出す。
  公式テキストとの ズレ (= 数値・対象・条件・概念) が 一目で 見えるよう、 詳細を 省略しない。
- カバレッジ: top ~80 primitive で カード 95% 以上 を 自然な日本語化、 残りは debug schema 風 fallback。
- 構造化出力: render_effect_structured() が {trigger, conditions, cost, effect, optional} を 返す。
  human/AI 共通の 効果発動 UI で 「発動しますか?」 modal の source として 流用可能。

エクスポート:
- render_effect(entry: dict) -> str
- render_effect_structured(entry: dict) -> dict
- render_card_effects(card_id: str, entries: list) -> str  (= 全 entry を 結合)
"""
from __future__ import annotations
from typing import Any


# ---------- trigger labels ----------

WHEN_LABEL = {
    "on_play": "【登場時】",
    "activate_main": "【起動メイン】",
    "trigger": "【トリガー】",
    "on_attack": "【アタック時】",
    "main": "【メイン】",
    "on_attached_don": "【ドン!!付与時】",
    "counter": "【カウンター】",
    "on_ko": "【KO時】",
    "end_of_turn": "【ターン終了時】",
    "opp_attack": "【相手アタック時】",
    "on_block": "【ブロック時】",
    "on_self_don_returned_to_deck": "【自分のドン!!がドン!!デッキに戻った時】",
    "replace_ko": "【KO置換】",  # = 「〜の時、代わりに〜」
    "in_hand": "【手札にある時】",
    "replace_leave": "【離れる置換】",
    "on_opp_chara_ko": "【相手キャラKO時】",
    "on_opp_blocker_use": "【相手ブロッカー発動時】",
    "on_self_chara_ko": "【自キャラKO時】",
    "on_self_event_played": "【自分イベント使用時】",
    "on_turn_end": "【ターン終了時】",
    "on_self_rested": "【自分レスト時】",
    "on_self_chara_rested_by_self_effect": "【自キャラ自効果レスト時】",
    "on_self_hand_discarded": "【手札捨札時】",
    "on_opp_chara_played": "【相手キャラ登場時】",
    "on_life_zero": "【ライフ0時】",
    "opp_event_or_trigger_fired": "【相手イベント/トリガー発動時】",
    "on_self_chara_played": "【自キャラ登場時】",
    "on_self_chara_leave_by_self_effect": "【自分効果で自キャラ離脱時】",
    "on_opp_life_taken": "【相手ライフ受領時】",
    "leader_passive": "【リーダー常在】",
    "replace_rest": "【レスト置換】",
    "opp_attack_on_leader": "【リーダーへの相手アタック時】",
    "opp_attack_on_chara": "【キャラへの相手アタック時】",
    "on_self_life_taken": "【自分ライフ受領時】",
    "game_start": "【ゲーム開始時】",
    "don_phase_modifier": "【ドン!!フェイズ修飾】",
    "setup_modifier": "【セットアップ修飾】",
    "on_self_life_to_hand": "【自分ライフ→手札時】",
    "on_self_life_lost": "【自分ライフ消失時】",
}


# ---------- target ----------

TARGET_LABEL = {
    "self": "このカード",
    "self_leader": "自分のリーダー",
    "opponent_leader": "相手のリーダー",
    "self_inplay": "自分の場全体",
    "self_inplay_choice": "自分のリーダーかキャラ1枚",
    "all_self_characters": "自分のキャラ全部",
    "all_self_team": "自分のリーダーとキャラ全部",
    "all_opponent_characters": "相手のキャラ全部",
    "one_self_team_any": "自分のリーダーかキャラ1枚",
    "one_self_character_any": "自分のキャラ1枚",
    "one_opponent_character_any": "相手のキャラ1枚",
    "one_opponent_inplay_any": "相手のリーダーかキャラ1枚",
    "any_self_chara": "自分のキャラ1枚",
    "other_self_chara": "このキャラ以外の自分のキャラ1枚",
    "all_self_chara_other": "このキャラ以外の自分のキャラ全部",
    "one_self_chara_filtered": "条件を満たす自分のキャラ1枚",
    "one_self_character_filtered": "条件を満たす自分のキャラ1枚",
    "one_opponent_character_filtered": "条件を満たす相手のキャラ1枚",
    "one_opp_inplay_filtered": "条件を満たす相手のリーダーかキャラ1枚",
}


def _target_jp(target: Any) -> str:
    """target 文字列を 日本語化。 cost_le_N, le_NNNN 等の suffix を解釈。"""
    if not isinstance(target, str):
        return "?対象?"
    if target in TARGET_LABEL:
        return TARGET_LABEL[target]
    import re
    # `(one|any|all)_(opponent|self|opp)_[state_]*(chara|character|inplay|team)[_qual]?`
    m = re.match(
        r"(one|any|all)_(opponent|self|opp)((?:_(?:rested|active|inactive|blocker))*)_(chara|character|inplay|team)s?(?:_(.+))?$",
        target,
    )
    if m:
        scope, side, states, kind, qual = m.groups()
        scope_jp = {"one": "1枚", "any": "1枚", "all": "全部"}[scope]
        side_jp = {"opponent": "相手", "opp": "相手", "self": "自分"}[side]
        kind_jp = {
            "chara": "キャラ", "character": "キャラ",
            "inplay": "リーダーかキャラ", "team": "リーダーかキャラ",
        }[kind]
        state_jp = ""
        for st in (states or "").split("_"):
            if st == "rested":
                state_jp += "レストの"
            elif st == "active":
                state_jp += "アクティブの"
            elif st == "blocker":
                state_jp += "ブロッカーの"
        qual_jp = _target_qual_jp(qual or "")
        return f"{side_jp}の{state_jp}{qual_jp}{kind_jp}{scope_jp}".replace("のの", "の")
    # other_self_chara_filtered など
    m = re.match(r"other_self_chara(?:_(.+))?$", target)
    if m:
        return f"このキャラ以外の自分のキャラ" + (_target_qual_jp(m.group(1) or "") or "1枚")
    # any_opp_inplay_n_2
    m = re.match(r"any_opp_inplay_n_(\d+)$", target)
    if m:
        return f"相手のリーダーかキャラ{m.group(1)}枚"
    return f"対象({target})"


def _target_qual_jp(qual: str) -> str:
    """target の suffix を 日本語化 (= cost_le_5, named_X, filtered, rested 等)。"""
    if not qual:
        return ""
    import re
    out_parts = []
    # cost_le_N / cost_le_Ncost / cost_eq_N
    m = re.match(r"cost_le_(\d+)c?o?s?t?$", qual)
    if m:
        out_parts.append(f"コスト{m.group(1)}以下の")
    elif re.match(r"cost_eq_(\d+)$", qual):
        n = re.match(r"cost_eq_(\d+)$", qual).group(1)
        out_parts.append(f"コスト{n}の")
    elif qual.endswith("c"):  # legacy
        pass
    # le_NNNN (power threshold)
    m2 = re.match(r"le_(\d+)$", qual)
    if m2:
        out_parts.append(f"パワー{m2.group(1)}以下の")
    m3 = re.match(r"ge_(\d+)$", qual)
    if m3:
        out_parts.append(f"パワー{m3.group(1)}以上の")
    if "rested" in qual:
        out_parts.append("レスト状態の")
    if "active" in qual and "inactive" not in qual:
        out_parts.append("アクティブ状態の")
    if "blocker" in qual:
        out_parts.append("ブロッカーの")
    if "filtered" in qual and not out_parts:
        out_parts.append("条件を満たす")
    if "named" in qual:
        m4 = re.search(r"named_(.+)$", qual)
        if m4:
            out_parts.append(f"「{m4.group(1)}」 ")
    if "truly_power_le" in qual:
        m5 = re.search(r"truly_power_le_(\d+)$", qual)
        if m5:
            out_parts.append(f"元のパワー{m5.group(1)}以下の")
    return "".join(out_parts)


# ---------- filter ----------

def _filter_jp(flt: dict) -> str:
    if not isinstance(flt, dict) or not flt:
        return ""
    parts = []
    if "feature" in flt:
        f = flt["feature"]
        if isinstance(f, list):
            parts.append("特徴《" + "/".join(f) + "》")
        else:
            parts.append(f"特徴《{f}》")
    if "name" in flt:
        n = flt["name"]
        if isinstance(n, list):
            parts.append("「" + "/".join(n) + "」")
        else:
            parts.append(f"「{n}」")
    if "exclude_name" in flt:
        n = flt["exclude_name"]
        if isinstance(n, list):
            parts.append("(" + "/".join(n) + "を除く)")
        else:
            parts.append(f"({n}を除く)")
    if "exclude_card_id" in flt:
        parts.append(f"(自身を除く)")
    if "color" in flt:
        parts.append(f"色《{flt['color']}》")
    if "category" in flt:
        c = flt["category"]
        cat_jp = {"character": "キャラ", "event": "イベント", "stage": "ステージ", "leader": "リーダー"}
        if isinstance(c, list):
            parts.append("/".join(cat_jp.get(x, x) for x in c))
        else:
            parts.append(cat_jp.get(c, c))
    if "cost_le" in flt:
        parts.append(f"コスト{flt['cost_le']}以下")
    if "cost_ge" in flt:
        parts.append(f"コスト{flt['cost_ge']}以上")
    if "cost_eq" in flt:
        parts.append(f"コスト{flt['cost_eq']}")
    if "power_le" in flt:
        parts.append(f"パワー{flt['power_le']}以下")
    if "power_ge" in flt:
        parts.append(f"パワー{flt['power_ge']}以上")
    if "truly_original_power_le" in flt:
        parts.append(f"元のパワー{flt['truly_original_power_le']}以下")
    if "rested" in flt:
        parts.append("レスト状態")
    if "active" in flt:
        parts.append("アクティブ状態")
    if "blocker" in flt:
        parts.append("ブロッカー")
    if "has_keyword" in flt:
        parts.append(f"《{flt['has_keyword']}》持ち")
    if "or_clauses" in flt:
        sub = [_filter_jp(c) for c in flt["or_clauses"]]
        parts.append("(" + " または ".join(s for s in sub if s) + ")")
    return "".join(parts)


# ---------- condition (if / conditions) ----------

def _cond_jp(cond: Any) -> str:
    if not cond:
        return ""
    if isinstance(cond, list):
        joined = "かつ".join(_cond_jp(c) for c in cond if _cond_jp(c))
        return joined
    if not isinstance(cond, dict):
        return ""
    parts = []
    for k, v in cond.items():
        parts.append(_single_cond_jp(k, v))
    return "かつ".join(p for p in parts if p)


def _single_cond_jp(k: str, v: Any) -> str:
    # life
    if k == "self_life_le": return f"自分のライフが{v}以下の場合"
    if k == "self_life_ge": return f"自分のライフが{v}以上の場合"
    if k == "self_life_eq": return f"自分のライフが{v}の場合"
    if k == "opp_life_le": return f"相手のライフが{v}以下の場合"
    if k == "opp_life_ge": return f"相手のライフが{v}以上の場合"
    if k == "self_life_lt_opp": return "自分のライフが相手より少ない場合"
    # leader
    if k == "leader_feature":
        if isinstance(v, list):
            return f"自分のリーダーが特徴《{'/'.join(v)}》の場合"
        return f"自分のリーダーが特徴《{v}》の場合"
    if k == "leader_features_any":
        return f"自分のリーダーが特徴《{'/'.join(v) if isinstance(v, list) else v}》のいずれかを持つ場合"
    if k == "leader_color":
        if isinstance(v, list):
            return f"自分のリーダーが色《{'/'.join(v)}》の場合"
        return f"自分のリーダーが色《{v}》の場合"
    if k == "leader_color_multi": return "自分のリーダーが多色の場合"
    if k == "leader_multicolor": return "自分のリーダーが多色の場合"
    if k == "leader_name":
        if isinstance(v, list):
            return f"自分のリーダーが「{'/'.join(v)}」の場合"
        return f"自分のリーダーが「{v}」の場合"
    if k == "leader_name_in": return f"自分のリーダーが「{'/'.join(v)}」のいずれかの場合"
    if k == "leader_feature_contains":
        return f"自分のリーダーの特徴に「{v}」を含む場合"
    if k == "opp_leader_attribute": return f"相手リーダーの属性が《{v}》の場合"
    if k == "self_leader_attribute": return f"自分リーダーの属性が《{v}》の場合"
    if k == "opp_leader_feature": return f"相手リーダーの特徴に《{v}》を含む場合"
    # don
    if k == "self_don_ge": return f"自分のドン!!{v}枚以上の場合"
    if k == "self_don_le": return f"自分のドン!!{v}枚以下の場合"
    if k == "self_don_active_ge": return f"自分のアクティブドン!!{v}枚以上の場合"
    if k == "self_don_active_le": return f"自分のアクティブドン!!{v}枚以下の場合"
    if k == "don_count_ge": return f"ドン!!デッキ{v}枚以上の場合"
    if k == "don_count_le": return f"ドン!!デッキ{v}枚以下の場合"
    if k == "opp_don_count_ge": return f"相手ドン!!デッキ{v}枚以上の場合"
    if k == "opp_don_count_le": return f"相手ドン!!デッキ{v}枚以下の場合"
    if k == "don_diff_le": return f"ドン!!差{v}以下の場合"
    # board
    if k == "self_field_count_ge": return f"自分の場のキャラが{v}枚以上の場合"
    if k == "self_field_count_le": return f"自分の場のキャラが{v}枚以下の場合"
    if k == "self_chara_count_ge": return f"自分のキャラが{v}枚以上の場合"
    if k == "self_chara_count_le": return f"自分のキャラが{v}枚以下の場合"
    if k == "self_chara_feature_count_ge":
        if isinstance(v, dict):
            return f"自分の特徴《{v.get('feature')}》のキャラ{v.get('n', '?')}枚以上の場合"
        return f"自分の特徴キャラ{v}枚以上の場合"
    if k == "self_chara_cost_ge_count":
        if isinstance(v, dict):
            return f"自分のコスト{v.get('cost', '?')}以上のキャラ{v.get('n', '?')}枚以上の場合"
        return f"条件のキャラ{v}枚以上の場合"
    if k == "self_chara_filtered_count_ge":
        if isinstance(v, dict):
            f = _filter_jp(v.get("filter", {}))
            return f"自分の{f}キャラ{v.get('count', v.get('n', '?'))}枚以上の場合"
        return f"条件のキャラ{v}枚以上の場合"
    if k == "opp_chara_filtered_count_ge":
        if isinstance(v, dict):
            f = _filter_jp(v.get("filter", {}))
            return f"相手の{f}キャラ{v.get('count', v.get('n', '?'))}枚以上の場合"
        return f"条件の相手キャラ{v}枚以上の場合"
    if k == "opp_chara_filtered_count_le":
        if isinstance(v, dict):
            f = _filter_jp(v.get("filter", {}))
            return f"相手の{f}キャラ{v.get('count', v.get('n', '?'))}枚以下の場合"
        return f"条件の相手キャラ{v}枚以下の場合"
    if k == "self_trash_has_named_all":
        if isinstance(v, list):
            return f"自分のトラッシュに「{'」と「'.join(v)}」がある場合"
        return f"自分のトラッシュに「{v}」がある場合"
    if k == "self_chara_power_ge": return f"自分のパワー{v}以上のキャラがいる場合"
    if k == "self_inplay_power_ge": return f"自分にパワー{v}以上のキャラがいる場合"
    if k == "self_inplay_attached_dons_ge":
        if isinstance(v, dict):
            return f"自分に付与ドン!!{v.get('n', '?')}枚以上のキャラがいる場合"
        return f"付与ドン!!{v}以上の場合"
    if k == "self_chara_only_feature": return f"自分の場のキャラが全て特徴《{v}》の場合"
    if k == "self_chara_unique_name": return "自分の場のキャラ名が全て異なる場合"
    # hand / trash
    if k == "self_hand_count_le": return f"自分の手札{v}枚以下の場合"
    if k == "self_hand_count_ge": return f"自分の手札{v}枚以上の場合"
    if k == "opp_hand_count_ge": return f"相手の手札{v}枚以上の場合"
    if k == "self_trash_count_ge": return f"自分のトラッシュ{v}枚以上の場合"
    if k == "self_trash_event_count_ge": return f"自分のトラッシュにイベント{v}枚以上の場合"
    # turn
    if k == "self_turn": return "自分のターン中"
    if k == "opp_turn": return "相手のターン中"
    if k == "self_turn_number_ge": return f"ターン数{v}以上の場合"
    if k == "self_summoning_sickness": return "このキャラに召喚酔いがある場合"
    if k == "self_rested": return "このカードがレスト状態の場合"
    if k == "self_rested_cards_count_ge": return f"自分のレスト状態のカード{v}枚以上の場合"
    if k == "self_attached_don_ge": return f"このカードに付与ドン!!{v}枚以上の場合"
    if k == "self_power_ge": return f"このキャラのパワー{v}以上の場合"
    if k == "life_zero_either": return "いずれかのライフ0の場合"
    if k == "always": return ""
    # special
    if k == "self_stage_named": return f"自分の場にステージ「{v}」がある場合"
    if k == "opp_or_self_chara_cost_eq_0_exists": return "場にコスト0のキャラがいる場合"
    # battle context (counter / on_attack / opp_attack)
    if k == "victim_truly_original_power_ge": return f"対象の元パワーが{v}以上の場合"
    if k == "victim_feature_in": return f"対象が特徴《{'/'.join(v) if isinstance(v, list) else v}》の場合"
    if k == "played_chara_truly_original_cost_ge": return f"登場したキャラの元コストが{v}以上の場合"
    if k == "played_self_chara_has_no_effect": return "登場した自キャラに効果がない場合"
    if k == "actor_source_feature_contains":
        return f"アタックしたキャラが特徴《{v}》の場合"
    return f"[{k}={v}]"


# ---------- cost ----------

def _cost_jp(cost: Any) -> str:
    if not cost or not isinstance(cost, dict):
        return ""
    parts = []
    if cost.get("once_per_turn"):
        parts.append("ターン1回")
    if "discard_hand" in cost:
        v = cost["discard_hand"]
        if isinstance(v, dict):
            parts.append(f"手札を{v.get('count', 1)}枚捨てる")
        else:
            parts.append(f"手札を{v}枚捨てる" if isinstance(v, int) else "手札を1枚捨てる")
    if "pay_don" in cost:
        parts.append(f"ドン-{cost['pay_don']}")
    if "rest_self_don" in cost:
        parts.append(f"自分のアクティブドン!!{cost['rest_self_don']}枚レスト")
    if "rest_self" in cost:
        parts.append("このカードをレスト")
    if "trash_self" in cost:
        parts.append("このカードをトラッシュに置く")
    if "return_self_to_hand" in cost:
        parts.append("このカードを手札に戻す")
    if "discard_hand_with_filter" in cost:
        f = cost["discard_hand_with_filter"]
        if isinstance(f, dict):
            n = f.get("count", 1)
            flt = _filter_jp(f.get("filter", {}))
            parts.append(f"{flt}手札{n}枚を捨てる")
    if "ko_self_with_filter" in cost:
        f = cost["ko_self_with_filter"]
        if isinstance(f, dict):
            flt = _filter_jp(f.get("filter", {}))
            n = f.get("count", 1)
            parts.append(f"{flt}自キャラ{n}枚をKO")
    if "trash_to_deck" in cost:
        parts.append(f"トラッシュ{cost['trash_to_deck']}枚をデッキに")
    if "life_top_or_bottom_to_hand" in cost:
        parts.append("自分のライフの上か下を手札に")
    if "life_to_hand" in cost:
        parts.append(f"自分のライフ{cost['life_to_hand']}枚を手札に")
    return "[" + "][".join(parts) + "]" if parts else ""


# ---------- duration ----------

def _duration_jp(d: Any) -> str:
    if d == "turn":
        return "このターン中"
    if d == "next_opp_turn_end" or d == "until_next_opp_turn_end":
        return "次の相手ターン終了時まで"
    if d == "static":
        return "(常在)"
    if d == "permanent":
        return "(恒久)"
    if d == "next_turn_end":
        return "次のターン終了時まで"
    return ""


# ---------- do primitive renderers ----------

def _amount_signed(amount: Any) -> str:
    if isinstance(amount, (int, float)):
        if amount > 0:
            return f"+{amount}"
        return f"{amount}"
    return f"{amount}"


def _do_jp(d: Any) -> str:
    if not isinstance(d, dict):
        return f"{d}"
    if len(d) == 0:
        return ""
    # 一般に primitive は 1キー dict
    k = next(iter(d.keys()))
    v = d[k]
    return _do_prim_jp(k, v, d)


def _do_prim_jp(k: str, v: Any, full: dict) -> str:  # full = 親 dict
    # === draw / discard ===
    if k == "draw":
        n = v if isinstance(v, int) else v.get("amount", 1)
        return f"カード{n}枚を引く"
    if k == "draw_per_self_hand_discarded":
        return "捨てた手札の枚数分カードを引く"
    if k == "draw_per_hand_to_deck_bottom":
        return "デッキ底に戻した枚数分カードを引く"
    if k == "trash_self_hand_random":
        n = v if isinstance(v, int) else (v.get("count", v.get("amount", 1)) if isinstance(v, dict) else 1)
        return f"自分の手札からランダムに{n}枚をトラッシュ"
    if k == "trash_opp_hand_random":
        n = v if isinstance(v, int) else (v.get("count", v.get("amount", 1)) if isinstance(v, dict) else 1)
        return f"相手の手札からランダムに{n}枚をトラッシュ"
    if k == "force_opp_discard":
        n = v if isinstance(v, int) else (v.get("count", v.get("amount", 1)) if isinstance(v, dict) else 1)
        return f"相手は手札から{n}枚を選んで捨てる"
    if k == "discard_self_to_deck_top":
        return f"自分の手札{v}枚をデッキの上に"

    # === ko ===
    if k == "ko":
        return _target_jp(v) + "をKOする"
    if k == "ko_multi":
        if isinstance(v, dict):
            return _target_jp(v.get("target", "")) + f"を{v.get('count', '?')}枚までKO"
        return f"複数KO({v})"
    if k == "ko_all_others":
        return "このカード以外をKO"
    if k == "ko_opp_stage":
        return "相手のステージをKO"

    # === return ===
    if k == "return_to_hand":
        return _target_jp(v) + "を手札に戻す"
    if k == "return_to_hand_multi":
        if isinstance(v, dict):
            return _target_jp(v.get("target", "")) + f"を{v.get('count', '?')}枚まで手札に"
        return f"複数を手札に戻す"
    if k == "return_to_deck_bottom":
        return _target_jp(v) + "をデッキの下に戻す"
    if k == "return_to_deck_bottom_multi":
        if isinstance(v, dict):
            return _target_jp(v.get("target", "")) + f"を{v.get('count', '?')}枚までデッキの下に"
        return f"複数をデッキの下に戻す"
    if k == "return_self_to_hand":
        return "このカードを手札に戻す"
    if k == "return_self_to_trash":
        return "このカードをトラッシュに置く"
    if k == "return_self_to_deck_bottom_if_condition":
        return "条件を満たす場合、 このカードをデッキの下に戻す"
    if k == "chara_to_self_life":
        return _target_jp(v) + "を自分のライフの上に置く"
    if k == "chara_to_opp_life":
        return _target_jp(v) + "を相手のライフの上に置く"
    if k == "hand_to_self_life":
        return f"自分の手札{v}枚をライフの上に"

    # === power / cost mod ===
    if k == "power_pump":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", ""))
            amt = _amount_signed(v.get("amount", 0))
            dur = _duration_jp(v.get("duration"))
            mult = v.get("amount_per") or v.get("amount_per_source")
            extra = ""
            if mult:
                extra = f"({mult}ごと×{v.get('multiplier', 1)})"
            return f"{tgt}を{dur}、 パワー{amt}{extra}"
        return f"power_pump({v})"
    if k == "power_pump_per_target_attached_don":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", ""))
            amt = v.get("amount_per_don", 1000)
            return f"{tgt}を {amt}×付与ドン!!枚数 パワー+"
        return "対象を 付与ドン!!ごと +N"
    if k == "set_base_power_timed":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", ""))
            return f"{tgt}の元のパワーを{v.get('amount')}に (このターン中)"
        return f"元パワー固定({v})"
    if k == "set_base_power_copy":
        return "対象キャラの元のパワーをコピー"
    if k == "set_base_cost_timed":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", ""))
            return f"{tgt}の元コストを{v.get('amount')}に (このターン中)"
        return f"元コスト固定({v})"
    if k == "cost_minus":
        n = v if isinstance(v, int) else v.get("amount", 0) if isinstance(v, dict) else 0
        return f"コスト-{n}"
    if k == "reduce_play_cost":
        if isinstance(v, dict):
            return f"場に出す時のコスト-{v.get('amount', 0)}"
        return f"場に出す時のコスト-{v}"
    if k == "in_hand_cost_minus":
        return f"手札にある時、 コスト-{v}"

    # === don ===
    if k in ("add_don", "add_don_active"):
        return f"ドン!!{v}枚をアクティブで追加"
    if k == "add_rested_don":
        return f"ドン!!{v}枚をレストで追加"
    if k == "attach_don":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", ""))
            n = v.get("count", 1)
            rested = "レストの" if v.get("rested") else ""
            return f"{tgt}に{rested}ドン!!{n}枚までを付与"
        return f"ドン!!付与({v})"
    if k == "attach_rested_don":
        if isinstance(v, dict):
            return f"{_target_jp(v.get('target', ''))}にレストのドン!!{v.get('count', 1)}枚までを付与"
        return f"レストのドン!!付与"
    if k == "attach_active_don":
        if isinstance(v, dict):
            return f"{_target_jp(v.get('target', ''))}にアクティブのドン!!{v.get('count', 1)}枚までを付与"
        return f"アクティブのドン!!付与"
    if k == "untap_don":
        return f"自分のドン!!{v}枚をアクティブに"
    if k == "rest_self_don":
        return f"自分のアクティブドン!!{v}枚をレスト"
    if k == "rest_opp_don":
        return f"相手のドン!!{v}枚をレスト"
    if k == "return_self_don_to_deck":
        return f"自分のドン!!{v}枚をドン!!デッキに戻す"
    if k == "return_opp_don":
        return f"相手のドン!!{v}枚をドン!!デッキに戻す"
    if k == "return_attached_don_to_cost_rested":
        return f"対象の付与ドン!!{v}枚をコスト領域にレストで戻す"
    if k == "transfer_attached_don_to_feature":
        return "対象の付与ドン!!を 特徴対象に移す"
    if k == "don_minus_opp":
        return f"相手のドン!!{v}を 使用不可"
    if k == "keep_opp_rested_don_next_refresh":
        return "次のリフレッシュフェイズで 相手のドン!!をアクティブにしない"

    # === rest / untap ===
    if k == "rest":
        return _target_jp(v) + "をレストにする"
    if k == "untap":
        return _target_jp(v) + "をアクティブにする"
    if k == "untap_chara":
        return _target_jp(v) + "をアクティブにする"
    if k == "rest_self_cards":
        return f"自分の{v}枚をレスト"
    if k == "rest_self_cards_filtered":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"自分の{flt}{v.get('count', '?')}枚をレスト"
        return "条件のキャラをレスト"
    if k == "stay_rested_next_refresh":
        if isinstance(v, str):
            return f"{_target_jp(v)}は次のリフレッシュフェイズでアクティブにならない"
        return "次のリフレッシュフェイズでこのカードをアクティブにしない"
    if k == "keep_opp_rested_inplay_next_refresh":
        return "次のリフレッシュフェイズで対象をアクティブにしない"
    if k == "keep_opp_rested_chara_next_refresh":
        return "次のリフレッシュフェイズで対象キャラをアクティブにしない"
    if k == "keep_opp_rested_chara_with_don_ge_next_refresh":
        if isinstance(v, dict):
            return f"次のリフレッシュで 付与ドン!!{v.get('don_ge', '?')}以上のキャラをアクティブにしない"
        return "条件付き対象を次の refresh でアクティブにしない"

    # === life ===
    if k == "life_to_hand":
        n = v if isinstance(v, int) else v.get("amount", 1) if isinstance(v, dict) else 1
        return f"自分のライフ{n}枚を手札に加える"
    if k == "life_top_or_bottom_to_hand":
        return "自分のライフの上か下を手札に加える"
    if k == "put_top_to_life":
        return f"自分のデッキの上{v}枚をライフに置く"
    if k == "peek_self_life_top":
        return f"自分のライフの一番上を見る"
    if k == "scry_life":
        return "自分のライフを見て並び替える"
    if k == "scry_all_life_one_to_deck":
        return "自分のライフを全部見て1枚をデッキに"
    if k == "scry_all_life_reorder":
        return "自分のライフを全部見て好きな順に並び替える"
    if k == "mill_self_life_until_n":
        return f"自分のライフを{v}枚になるまでトラッシュに"
    if k == "mill_opp_life_to_hand":
        return f"相手のライフ{v}枚を相手の手札に加える"
    if k == "mill_opp_life_to_trash":
        return f"相手のライフ{v}枚をトラッシュに置く"
    if k == "mill_self_life_to_trash":
        return f"自分のライフ{v}枚をトラッシュに置く"
    if k == "to_opp_life":
        return _target_jp(v) + "を相手のライフの上に"

    # === search / play ===
    if k == "search_top_n":
        if isinstance(v, dict):
            depth = v.get("depth", "?")
            flt = _filter_jp(v.get("filter", {}))
            limit = v.get("limit", 1)
            dest = v.get("destination", "hand")
            dest_jp = {"hand": "手札", "trash": "トラッシュ", "play": "場に出す"}.get(dest, dest)
            rest_remain = v.get("rest_remain", "bottom")
            rest_jp = "残りはデッキの下" if rest_remain == "bottom" else "残りはデッキの上"
            return f"自分のデッキの上から{depth}枚を見て、 {flt}カード{limit}枚までを{dest_jp}に加え、 {rest_jp}に好きな順で置く"
        return f"search_top_n({v})"
    if k == "search":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            limit = v.get("limit", 1)
            return f"自分のデッキから{flt}カード{limit}枚を手札に加え、 デッキをシャッフル"
        return f"search({v})"
    if k == "reveal_top_then":
        return f"デッキの一番上を公開して、 条件分岐 ({v})"
    if k == "reveal_top_play":
        return "デッキの一番上を公開し、 条件を満たせば場に出す"
    if k == "reveal_opp_hand":
        return "相手の手札を見る"
    if k == "reveal_opp_hand_and_if_event_mill_life":
        return "相手の手札を見て、 イベントがあれば 相手のライフをトラッシュ"
    if k == "look_top_reorder":
        if isinstance(v, dict):
            return f"自分のデッキの上{v.get('depth', '?')}枚を見て、 好きな順で戻す"
        return f"デッキ上を並び替え"
    if k == "play_from_hand":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"自分の手札から{flt}カード{v.get('count', 1)}枚を場に出す"
        return f"手札から場に({v})"
    if k == "play_from_hand_choice":
        return "手札から条件のカードを選んで場に出す"
    if k == "play_from_hand_named_with_dynamic_cost":
        return f"手札の指定カードを場に出す ({v})"
    if k == "play_from_hand_named_set":
        return f"手札の指定カードセットから1枚を場に出す"
    if k == "play_from_hand_or_trash":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"自分の手札またはトラッシュから{flt}カードを場に出す"
        return "手札またはトラッシュから場に"
    if k == "play_from_trash":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"自分のトラッシュから{flt}カードを場に出す"
        return f"トラッシュから場に({v})"
    if k == "play_event_from_hand":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"手札から{flt}イベントを使用"
        return "手札からイベント使用"
    if k == "play_self":
        return "このカードを場に出す"
    if k == "summon_from_deck":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"自分のデッキから{flt}カードを場に出し、 デッキをシャッフル"
        return f"デッキから場に({v})"

    # === keyword grants ===
    if k == "give_keyword":
        if isinstance(v, dict):
            tgt = _target_jp(v.get("target", "self"))
            kw = v.get("keyword") or v.get("keywords")
            if isinstance(kw, list):
                kw_jp = "/".join(kw)
            else:
                kw_jp = kw
            dur = _duration_jp(v.get("duration"))
            return f"{tgt}を{dur}、 《{kw_jp}》を得る"
        return f"キーワード付与({v})"
    if k == "give_rush":
        return _target_jp(v) + "は《速攻》を得る"
    if k == "give_attack_active_chara":
        return _target_jp(v) + "は《アクティブキャラに攻撃可能》を得る"
    if k == "give_ko_immune_through_opp_turn":
        return _target_jp(v) + "は次の相手ターン終了時までKOされない"
    if k == "prevent_ko":
        return _target_jp(v) + "はKOされない"
    if k == "prevent_blocker_for_attacker":
        return "このアタックはブロックされない"
    if k == "prevent_opp_blocker_for_cost_le":
        return f"このターン、 コスト{v}以下の対象はブロックされない"
    if k == "set_ko_immune_timed":
        return _target_jp(v) + "はこのターンKOされない"
    if k == "set_cannot_attack":
        return _target_jp(v) + "はアタックできない"
    if k == "set_cannot_attack_target_cost_le":
        return f"コスト{v}以下にアタックできない"
    if k == "set_cannot_rest":
        return _target_jp(v) + "はレストにならない"
    if k == "static_swords_attack_chara":
        return "(常在) このリーダーは特徴《剣士》としてアタックできる"
    if k == "prevent_self_life_to_hand_turn":
        return "このターン、 自分のライフは手札に加えられない"

    # === schedule / replace ===
    if k == "schedule_at_opp_main_phase_start":
        return "(予約) 相手メインフェイズ開始時に発動"
    if k == "schedule_at_self_turn_end":
        return "(予約) 自ターン終了時に発動"
    if k == "optional_cost_then":
        if isinstance(v, dict):
            c = _cost_jp({"_": True, **v.get("cost", {})}) if False else _cost_jp(v.get("cost", {}))
            inner = " / ".join(_do_jp(x) for x in v.get("then", []))
            return f"任意で{c}支払い、 {inner}"
        return f"任意コスト({v})"
    if k == "optional_after_battle_mutual_ko":
        return "バトル後、 任意で 相互KO"
    if k == "optional_discard_hand_for_battle_buff":
        if isinstance(v, dict):
            return f"任意で手札を捨ててバトル中パワー+{v.get('amount', '?')}"
        return "任意で手札捨ててパワー+"

    # === misc ===
    if k == "negate_effect":
        return "効果を無効にする"
    if k == "disable_effect":
        return _target_jp(v) + "の効果を無効化"
    if k == "fire_self_effect":
        return "このカードの効果を発動"
    if k == "win_game":
        return "ゲームに勝利する"
    if k == "extra_turn":
        return "追加ターン"
    if k == "redirect_attack":
        return _target_jp(v) + "をアタック対象に変更"
    if k == "deal_opp_leader_damage":
        return f"相手のリーダーに{v}ダメージ"
    if k == "swap_opp_power":
        return "対象のパワーを交換"
    if k == "set_attack_cost_discard_hand":
        return f"アタック時、 手札{v}枚捨てる必要"
    if k == "set_don_deck_size":
        return f"ドン!!デッキ枚数を{v}に"
    if k == "shuffle_self_deck":
        return "自分のデッキをシャッフル"
    if k == "block_self_draw_turn":
        return "このターン、 ドローできない"
    if k == "block_chara_play_turn":
        return "このターン、 キャラを場に出せない"
    if k == "block_chara_play":
        return "キャラを場に出せない"
    if k == "block_chara_play_cost_ge":
        return f"コスト{v}以上のキャラを場に出せない"
    if k == "other_self_charas_to_trash":
        return "他の自キャラを全部トラッシュ"
    if k == "other_self_charas_to_deck_bottom":
        return "他の自キャラを全部デッキの下に"
    if k == "mill":
        return f"自分のデッキの上{v}枚をトラッシュに"
    if k == "mill_self_top":
        return f"自分のデッキの上{v}枚をトラッシュに"
    if k == "self_hand_to_deck_bottom":
        return f"自分の手札{v}枚をデッキの下に"
    if k == "self_hand_to_size":
        return f"自分の手札を{v}枚に調整"
    if k == "opp_hand_to_deck_bottom":
        return f"相手の手札{v}枚をデッキの下に"
    if k == "trash_to_hand":
        if isinstance(v, dict):
            flt = _filter_jp(v.get("filter", {}))
            return f"トラッシュから{flt}カード{v.get('count', 1)}枚を手札に"
        return f"トラッシュから{v}枚を手札に"
    if k == "trash_to_deck":
        if isinstance(v, dict):
            return f"トラッシュ{v.get('count', '?')}枚をデッキに"
        return f"トラッシュ{v}枚をデッキに"
    if k == "opp_trash_to_deck_bottom":
        return f"相手のトラッシュ{v}枚をデッキの下に"
    if k == "to_hand_self_trigger":
        return "このカードを手札に加える (トリガー)"
    if k == "pay_don":
        return f"ドン-{v}"
    if k == "discard_hand":
        return f"手札{v}枚を捨てる"
    if k == "trash_self":
        return "このカードをトラッシュに置く"

    if k == "replace_ko_complex":
        return f"KO時の代わりに条件処理 ({v})"
    if k == "choice":
        return f"選択効果 ({v})"

    if k == "_unimplemented":
        return f"[未実装: {v}]"

    # === fallback ===
    return f"[{k}: {_brief(v)}]"


def _brief(v: Any, maxlen: int = 60) -> str:
    import json
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    if len(s) > maxlen:
        s = s[:maxlen] + "…"
    return s


# ---------- top-level ----------

def render_effect_structured(entry: dict) -> dict:
    """単一 entry を {trigger, conditions, cost, effect, optional, raw} に分解。

    返り値:
      {
        "trigger": "【登場時】",
        "conditions": "自分のライフが2以下の場合",  # 空可
        "cost": "[ターン1回][手札を1枚捨てる]",     # 空可
        "effect": "カード2枚を引く",                 # メイン効果
        "optional": False,                            # 任意発動か
        "raw": entry,
      }
    """
    when = entry.get("when", "")
    trigger = WHEN_LABEL.get(when, f"【{when}】" if when else "")

    # conditions
    conds = entry.get("if") or entry.get("conditions") or {}
    cond_text = _cond_jp(conds)

    # cost
    cost_text = _cost_jp(entry.get("cost") or {})

    # do
    do_list = entry.get("do") or []
    if not isinstance(do_list, list):
        do_list = [do_list]
    effect_parts = [_do_jp(d) for d in do_list]
    # ばつ印的なフィルタ
    effect_parts = [p for p in effect_parts if p]
    effect_text = "、 ".join(effect_parts)

    # optional flag
    optional = bool(entry.get("optional")) or "optional_cost_then" in str(do_list)

    # on_attached_don の n 表示
    if when == "on_attached_don" and "n" in entry:
        trigger = f"【ドン!!{entry['n']}枚以上付与時】"

    return {
        "trigger": trigger,
        "conditions": cond_text,
        "cost": cost_text,
        "effect": effect_text,
        "optional": optional,
        "raw": entry,
    }


def render_effect(entry: dict) -> str:
    """単一 entry を 1行の 公式テキスト風 日本語に。"""
    s = render_effect_structured(entry)
    parts = []
    if s["trigger"]:
        parts.append(s["trigger"])
    if s["cost"]:
        parts.append(s["cost"])
    body = ""
    if s["conditions"]:
        body += s["conditions"] + "、 "
    body += s["effect"]
    if s["optional"]:
        body += " (任意)"
    parts.append(body)
    return "".join(parts)


def render_card_effects(card_id: str, entries: list) -> str:
    """カード単位で全 entry を 結合 (改行区切り)。"""
    if not isinstance(entries, list):
        return ""
    lines = [render_effect(e) for e in entries if isinstance(e, dict)]
    return "\n".join(line for line in lines if line)


if __name__ == "__main__":
    # smoke test
    import json
    overlay = json.load(open("db/card_effects.json"))
    for cid in ["OP01-016", "ST01-007", "OP11-028", "OP05-005", "OP13-075"]:
        if cid in overlay:
            print(f"--- {cid} ---")
            print(render_card_effects(cid, overlay[cid]))
            print()
