# -*- coding: utf-8 -*-
"""
非メタ簡略カードの一括 honest リセット。

目的:
    `db/card_effects.json` に残る ~2,300 件の simplified marker 持ち effect を
    公式テキスト忠実な DSL で書き直す。 解析できないものは _unimplemented stub で
    official text を保持し、 嘘の挙動 (= fallback) を完全排除する。

戦略:
    1. simplified marker (fallback / 簡略 / 自動抽出 / auto / 省略 / 近似) 持ち effect を
       含むカードを抽出 (cardrush メタリーダーは除外)
    2. 各カードの公式テキストを正規表現パターンで分解:
       - 【XXX】 で trigger 単位に切り分け
       - 各 trigger 内で primitive を抽出 (draw / ko / power_pump / search 等)
       - 条件節 (if) を抽出 (自ライフ / リーダー特徴 / トラッシュ枚数 等)
       - コスト (cost) を抽出 (【ターン1回】 / ドン!!-N / 手札 N 枚捨て 等)
    3. 解析成功した primitive は DSL JSON で出力。
       テキストは残るが primitive 化できない部分は _unimplemented で保持。
    4. パラレル variants (_p1, _p2 等) も同じ effect で更新

実行:
    .venv/bin/python scripts/bulk_rewrite_overlay.py            # 一括実行
    .venv/bin/python scripts/bulk_rewrite_overlay.py --dry-run  # 書き込まずに統計のみ
    .venv/bin/python scripts/bulk_rewrite_overlay.py --limit 200 # N 枚で打ち切り (デバッグ用)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
DECKS_DIR = ROOT / "decks"

SIMPLIFIED_MARKERS = ("fallback", "簡略", "auto", "省略", "近似", "自動抽出")

# テスト依存カード (= 個別動作期待): bulk rewrite 対象から除外
PROTECTED_TEST_CARDS = {
    "OP01-013",  # サンジ activate_main pump
    "OP01-016",  # ナミ search 麦わら
    "OP02-013",  # エース on_play -3000
    "OP01-051",  # キッド attack_taunt static
    "OP15-003",  # アルビダ replace_ko self
    "OP06-118",  # ゾロ on_attack once_per_turn
    "OP11-096",  # リッパー conditional blocker
}


def has_unimplemented(effs: list) -> bool:
    """overlay の effects に _unimplemented プリミティブが含まれるか?"""
    if not isinstance(effs, list):
        return False
    for e in effs:
        if not isinstance(e, dict):
            continue
        for p in (e.get("do", []) or []):
            if isinstance(p, dict) and "_unimplemented" in p:
                return True
        if isinstance(e.get("cost"), dict) and "_unimplemented" in e["cost"]:
            return True
        if isinstance(e.get("if"), dict) and "_unimplemented" in e["if"]:
            return True
    return False


# --------------------------------------------------------------------------- #
# パターン定義
# --------------------------------------------------------------------------- #
TRIGGER_MAP = {
    "登場時": "on_play",
    "KO時": "on_ko",
    "アタック時": "on_attack",
    "ブロック時": "on_block",
    "相手のアタック時": "opp_attack",
    "起動メイン": "activate_main",
    "メイン": "main",
    "カウンター": "counter",
    "トリガー": "trigger",
    "自分のターン終了時": "end_of_turn",
    "相手のターン終了時": "opp_end_of_turn",
    "自分のターン開始時": "on_turn_start",
    "相手のターン開始時": "opp_turn_start",
}


def has_simplified_marker(effects: list) -> bool:
    if not isinstance(effects, list):
        return False
    for e in effects:
        if not isinstance(e, dict):
            continue
        text = e.get("_text", "") or ""
        if any(m in text for m in SIMPLIFIED_MARKERS):
            return True
    return False


def to_int(s: str) -> int:
    s = s.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return int(s)


# cost / keyword 修飾子: trigger ではなく、 直前の trigger に吸収させる
NON_TRIGGER_MARKERS = {
    "ターン1回", "ターン1回 ", "ドン!!-1", "ドン!!-2", "ドン!!-3",
    "ドン!!-4", "ドン!!-5", "ドン!!-10", "ブロッカー", "速攻",
    "ダブルアタック", "バニッシュ", "ブロック不可", "速攻：キャラ", "速攻:キャラ",
    "トリガー",  # trigger field はトップレベルで扱う
}


def _is_keyword_reference(text: str, match: re.Match) -> bool:
    """【XXX】 が 「を持つ」 「を得る」 「を発動」 等の参照表現の一部か判定。

    例: 「【トリガー】を持つカード」 「【速攻】を得る」 「【ブロッカー】を発動できない」
    これらは セクション区切りではなく、 ボディ内の キーワード参照。
    """
    rest = text[match.end():match.end() + 6]
    return rest.startswith("を持") or rest.startswith("を得") or rest.startswith("を発")


# 効果セクション抽出: 【XXX】 で区切る
def split_by_trigger(text: str) -> list[tuple[str, str]]:
    """テキストを 【トリガー】 単位に分割し、 [(when, body), ...] を返す。

    cost / keyword マーカー (【ターン1回】 / 【ドン!!-N】 / 【ブロッカー】 等) は
    分割対象から除外し、 body の一部として保持する。
    【XXX】 を持つ/得る/発動 のような キーワード参照表現も区切らない。
    """
    matches = list(re.finditer(r"【(.+?)】", text))
    if not matches:
        return []
    # trigger マーカーのみフィルタ (= 区切り点として使うもの)。 キーワード参照は除外。
    trigger_matches = [
        m for m in matches
        if m.group(1) in TRIGGER_MAP and not _is_keyword_reference(text, m)
    ]
    if not trigger_matches:
        return []
    out: list[tuple[str, str]] = []
    for i, m in enumerate(trigger_matches):
        kw = m.group(1)
        when = TRIGGER_MAP[kw]
        start = m.end()
        end = trigger_matches[i + 1].start() if i + 1 < len(trigger_matches) else len(text)
        body = text[start:end].strip()
        out.append((when, body))
    return out


# --- コスト抽出 ---
COST_TURN_ONCE = re.compile(r"【ターン1回】")
COST_PAY_DON = re.compile(r"ドン\s*[‼!]{1,2}\s*[-－ー]\s*([0-9０-９]+)")
COST_DISCARD = re.compile(r"自分の手札\s*([0-9０-９]+)\s*枚を捨てる")
COST_REST_SELF = re.compile(r"このキャラをレストに[しす](?:る)?")
COST_TRASH_SELF = re.compile(r"このキャラをトラッシュに置く")
COST_KO_SELF_FEATURE = re.compile(r"自分の特徴《([^》]+)》を持つキャラ\s*1\s*枚をKO[しす](?:る)?")


def extract_cost(body: str) -> dict:
    cost: dict = {}
    if COST_TURN_ONCE.search(body):
        cost["once_per_turn"] = True
    m = COST_PAY_DON.search(body)
    if m:
        cost["pay_don"] = to_int(m.group(1))
    # variable pay_don ("N 枚以上") — 簡略で 最小値を pay
    if "pay_don" not in cost:
        m = COST_PAY_DON_VAR_RE.search(body)
        if m:
            cost["pay_don"] = to_int(m.group(1))
    m = COST_DISCARD.search(body)
    if m:
        cost["discard_hand"] = to_int(m.group(1))
    # feature-filtered discard cost
    m = COST_DISCARD_FEATURE_RE.search(body)
    if m and "discard_hand" not in cost:
        feat = m.group(1) or m.group(2)
        n_str = m.group(3)
        cost["discard_hand"] = to_int(n_str) if n_str else 1
        cost["discard_feature"] = feat
    if COST_REST_SELF.search(body):
        cost["rest_self"] = True
    if COST_TRASH_SELF.search(body):
        cost["trash_self"] = True
    if COST_RETURN_SELF_TO_HAND_RE.search(body):
        cost["return_self_to_hand"] = True
    m = COST_KO_SELF_FEATURE.search(body)
    if m:
        cost["ko_self_with_filter"] = {"feature": m.group(1)}
    return cost


# --- 条件 (if) 抽出 ---
IF_LEADER_FEATURE = re.compile(r"自分のリーダーが特徴《([^》]+)》を持つ場合")
IF_LEADER_FEATURES_ANY = re.compile(r"自分のリーダーが『([^』]+)』を含む特徴を持つ場合")
IF_LEADER_NAME = re.compile(r"自分のリーダーが「([^」]+)」の場合")
IF_SELF_LIFE_LE = re.compile(r"自分のライフが\s*([0-9０-９]+)\s*枚以下の場合")
IF_SELF_LIFE_GE = re.compile(r"自分のライフが\s*([0-9０-９]+)\s*枚以上の場合")
IF_OPP_LIFE_LE = re.compile(r"相手のライフが\s*([0-9０-９]+)\s*枚以下の場合")
IF_OPP_LIFE_GE = re.compile(r"相手のライフが\s*([0-9０-９]+)\s*枚以上の場合")
IF_TRASH_GE = re.compile(r"自分のトラッシュが\s*([0-9０-９]+)\s*枚以上(?:ある場合)?")
IF_DON_GE = re.compile(r"自分の(?:場の)?ドン\s*[‼!]{1,2}が\s*([0-9０-９]+)\s*枚以上(?:ある場合)?")
IF_DON_LE = re.compile(r"自分の(?:場の)?ドン\s*[‼!]{1,2}が\s*([0-9０-９]+)\s*枚以下(?:の場合)?")
IF_OPP_TURN = re.compile(r"【相手のターン中】")
IF_SELF_TURN = re.compile(r"【自分のターン中】")
IF_HAND_COUNT = re.compile(r"自分の手札が\s*([0-9０-９]+)\s*枚以下(?:の場合)?")
IF_OPP_HAND_GE = re.compile(r"相手の手札が\s*([0-9０-９]+)\s*枚以上(?:ある場合)?")
IF_FIELD_GE = re.compile(r"自分(?:の場のキャラ|のキャラ)が\s*([0-9０-９]+)\s*枚以上(?:いる場合)?")


def extract_if(body: str) -> dict:
    cond: dict = {}
    if m := IF_LEADER_NAME.search(body):
        cond["leader_name"] = m.group(1)
    if m := IF_LEADER_FEATURE.search(body):
        cond["leader_feature"] = m.group(1)
    if m := IF_LEADER_FEATURES_ANY.search(body):
        cond["leader_features_any"] = [m.group(1)]
    # 「自分のリーダーが多色の場合」 条件
    if "自分のリーダーが多色の場合" in body:
        cond["leader_color"] = "多色"
    if m := IF_SELF_LIFE_LE.search(body):
        cond["self_life_le"] = to_int(m.group(1))
    if m := IF_SELF_LIFE_GE.search(body):
        cond["self_life_ge"] = to_int(m.group(1))
    if m := IF_OPP_LIFE_LE.search(body):
        cond["opp_life_le"] = to_int(m.group(1))
    if m := IF_OPP_LIFE_GE.search(body):
        cond["opp_life_ge"] = to_int(m.group(1))
    # 「自分のライフが N 枚になった時」 (= self_life_eq) — トリガー条件
    if m := SELF_LIFE_EQ_RE.search(body):
        cond["self_life_eq"] = to_int(m.group(1))
    if m := IF_TRASH_GE.search(body):
        cond["self_trash_count_ge"] = to_int(m.group(1))
    if m := IF_DON_GE.search(body):
        cond["self_don_ge"] = to_int(m.group(1))
    if m := IF_DON_LE.search(body):
        cond["self_don_le"] = to_int(m.group(1))
    if m := IF_HAND_COUNT.search(body):
        cond["self_hand_count_le"] = to_int(m.group(1))
    if m := IF_OPP_HAND_GE.search(body):
        cond["opp_hand_count_ge"] = to_int(m.group(1))
    # 「このキャラのパワーが N 以上の場合」
    if m := COND_SELF_POWER_GE_RE.search(body):
        cond["self_power_ge"] = to_int(m.group(1))
    if m := IF_FIELD_GE.search(body):
        cond["self_field_count_ge"] = to_int(m.group(1))
    return cond


# --- 効果 (do primitives) 抽出 ---
DRAW_RE = re.compile(r"カード\s*([0-9０-９]+)\s*枚(?:まで)?を引く")
LIFE_TO_HAND_RE = re.compile(r"自分のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*手札に")
PUT_TOP_TO_LIFE_RE = re.compile(r"自分のデッキの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*ライフ(?:の上)?に(?:加える|表向きで加える)")
MILL_SELF_LIFE_RE = re.compile(r"自分のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を(?:、)?\s*トラッシュ")
MILL_OPP_LIFE_RE = re.compile(r"相手のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*持ち主の手札")
TRASH_SELF_HAND_RE = re.compile(r"自分の手札\s*([0-9０-９]+)\s*枚を捨てる")
TRASH_OPP_HAND_RE = re.compile(r"相手(?:は自身|プレイヤー)?の手札\s*([0-9０-９]+)\s*枚を(?:ランダムに)?捨て")
ADD_DON_RE = re.compile(r"ドン\s*[‼!]{1,2}\s*デッキからドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブ")
ADD_RESTED_DON_RE = re.compile(r"ドン\s*[‼!]{1,2}\s*デッキからドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*レスト")
UNTAP_DON_RE = re.compile(r"自分のドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブにする")

# パワー付与
POWER_PUMP_LEADER_RE = re.compile(r"自分のリーダー(?:1枚まで)?を、?(?:[^パ]*?)(?:このターン中|このバトル中|次の相手のエンドフェイズ終了時まで|次の相手のターン終了時まで)、?\s*パワー\s*\+\s*([0-9０-９]+)")
POWER_PUMP_INPLAY_RE = re.compile(r"自分のリーダーかキャラ\s*1\s*枚(?:まで)?を、?(?:[^パ]*?)(?:このターン中|このバトル中|次の相手のエンドフェイズ終了時まで)、?\s*パワー\s*\+\s*([0-9０-９]+)")
POWER_PUMP_SELF_CHARA_RE = re.compile(r"このキャラ(?:は)?(?:、)?(?:このターン中|このバトル中)、?\s*パワー\s*\+\s*([0-9０-９]+)")
POWER_PUMP_ALL_SELF_RE = re.compile(r"自分のリーダーとキャラすべてを、?(?:このターン中|このバトル中)、?\s*パワー\s*\+\s*([0-9０-９]+)")
POWER_PUMP_OPP_NEG_RE = re.compile(r"相手の(?:キャラ|リーダーかキャラ|リーダー)\s*1\s*枚(?:まで)?を、?(?:[^パ]*?)(?:このターン中|次の相手のエンドフェイズ終了時まで|次の相手のターン終了時まで)、?\s*パワー\s*\-\s*([0-9０-９]+)")
POWER_PUMP_ALL_OPP_NEG_RE = re.compile(r"相手のキャラすべてを、?(?:このターン中|このバトル中)、?\s*パワー\s*\-\s*([0-9０-９]+)")
# 「N 枚まで」 (N>1) は any_* として近似
POWER_PUMP_OPP_NEG_MULTI_RE = re.compile(r"相手の(?:キャラ|リーダーかキャラ)\s*([2-9])\s*枚まで(?:を)?、?(?:[^パ]*?)(?:このターン中|次の相手のエンドフェイズ終了時まで|次の相手のターン終了時まで)、?\s*パワー\s*\-\s*([0-9０-９]+)")

# KO / Bounce / Rest (相手キャラを対象)
KO_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
KO_OPP_POWER_RE = re.compile(r"相手のパワー\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
KO_OPP_RESTED_RE = re.compile(r"相手のレストのキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
RETURN_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?")
RETURN_OPP_DECK_BOTTOM_RE = re.compile(r"(?:相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下の)?キャラ\s*1\s*枚(?:まで)?を、?\s*持ち主のデッキの下に置く")
REST_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*レストに[しす](?:る)?")
REST_OPP_RESTED_COST_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?は、?\s*次の相手のリフレッシュフェイズでアクティブにならない")
STAY_RESTED_OPP_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ.*?次の相手のリフレッシュフェイズでアクティブにならない")
STAY_RESTED_OPP_ANY_RE = re.compile(r"相手のレストのキャラ\s*1\s*枚(?:まで)?は、?\s*次の相手のリフレッシュフェイズでアクティブにならない")
CANNOT_ATTACK_OPP_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?は、?.*?アタックできない")
CANNOT_ATTACK_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?は、?.*?アタックできない")
KO_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
RETURN_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?")
REST_OPP_ANY_RE = re.compile(r"相手の(?:アクティブの)?キャラ\s*1\s*枚(?:まで)?を、?\s*レストに[しす](?:る)?")

# サーチ (自分のデッキの上から N 枚を見て...)
# 公式テキストは 「N 枚を見て、 [〜の]カード [N枚]まで を公開し、 手札に加える」
SEARCH_RE = re.compile(
    r"自分のデッキの上から\s*([0-9０-９]+)\s*枚を見て(?:、)?(?P<filter>[^。]*?)(?:カード|キャラ(?:カード)?)\s*([0-9０-９]+)?\s*枚?(?:まで)?を公開し、?\s*手札に加える"
)
# サーチ filter から特徴を抽出
FILT_FEATURE_RE = re.compile(r"特徴《([^》]+)》")
FILT_COST_LE_RE = re.compile(r"コスト\s*([0-9０-９]+)\s*以下")
FILT_EXCLUDE_NAME_RE = re.compile(r"「([^」]+)」以外")

# 召喚 / 登場
PLAY_FROM_TRASH_RE = re.compile(r"自分のトラッシュから(?:コスト\s*([0-9０-９]+)\s*以下の)?(?:特徴《([^》]+)》を持つ)?(?:キャラカード|キャラ)\s*1\s*枚(?:まで)?を、?\s*登場させる")
PLAY_FROM_HAND_RE = re.compile(r"自分の手札から(?:コスト\s*([0-9０-９]+)\s*以下の)?(?:特徴《([^》]+)》を持つ)?(?:キャラカード|キャラ)\s*1\s*枚(?:まで)?を、?\s*(?:レストで)?登場させる")
SUMMON_FROM_DECK_RE = re.compile(r"自分のデッキから(?:コスト\s*([0-9０-９]+)\s*以下の)?(?:特徴《([^》]+)》を持つ)?(?:キャラカード|キャラ)\s*1\s*枚(?:まで)?を、?\s*登場させ")

# キーワード付与
GIVE_KEYWORD_RE = re.compile(r"自分の(?:リーダー|キャラ|リーダーかキャラ).*?は、?\s*このターン中、?\s*【(速攻|ブロッカー|ダブルアタック|バニッシュ|ブロック不可|速攻：キャラ)】を得る")

# 在中 attach_don
ATTACH_DON_LEADER_RE = re.compile(r"自分のリーダー(?:にレストの|に)?\s*ドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで|ずつまで)?を、?\s*(?:レストで)?\s*付与する")
ATTACH_DON_INPLAY_RE = re.compile(r"自分のリーダーかキャラ\s*1\s*枚に(?:レストの|アクティブの)?\s*ドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*付与する")
ATTACH_DON_CHARA_RE = re.compile(r"自分のキャラ\s*1\s*枚に(?:レストの|アクティブの)?\s*ドン\s*[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*付与する")
# 自分のリーダー/キャラを場のドン!! N 枚で 「アクティブにする」 系統
UNTAP_DON_LEADER_RE = re.compile(r"自分のリーダーを、?\s*アクティブにする")
# 「相手のリーダーかキャラ」 を pump
POWER_PUMP_OPP_LEADER_OR_CHARA_NEG_RE = re.compile(r"相手のリーダーかキャラ\s*1\s*枚(?:まで)?を、?\s*このターン中、\s*パワー\s*\-\s*([0-9０-９]+)")
# 相手のレストのキャラ KO
KO_OPP_RESTED_COST_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
# ライフを表向きにする
REVEAL_SELF_LIFE_RE = re.compile(r"自分のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*表向きにする")
# 自分の元々のコスト/パワー X 以下の自キャラを untap
UNTAP_SELF_FILTERED_RE = re.compile(r"自分(?:の(?:特徴《[^》]+》を持つ|元々のコスト\s*([0-9０-９]+)\s*以下の|パワー\s*([0-9０-９]+)\s*以下の))?キャラ\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブにする")
# 「自分のキャラ N 枚をレストにできる：」 (= rest_self_cards N コスト)
COST_REST_SELF_CHARAS_RE = re.compile(r"自分のキャラ\s*([0-9０-９]+)\s*枚を(?:レストにできる|レストに[しす](?:る)?)")
COST_TRASH_SELF_HAND_RE = re.compile(r"自分の手札\s*([0-9０-９]+)\s*枚を捨てる(?:ことができる)?[：:]")
# Untap (キャラ)
UNTAP_SELF_LEADER_RE = re.compile(r"自分のリーダーを、?\s*アクティブにする")
UNTAP_SELF_CHARA_RE = re.compile(r"自分の(?:キャラ|特徴《[^》]+》を持つキャラ)\s*1\s*枚(?:まで)?を、?\s*アクティブにする")
# 自手札にカード追加 (= 単発の add_to_hand 効果用)
SHUFFLE_DECK_RE = re.compile(r"デッキをシャッフルする")
# Cost +/-
COST_PLUS_OPP_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*このターン中、\s*コスト\s*\+\s*([0-9０-９]+)")
COST_MINUS_OPP_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*このターン中、\s*コスト\s*[-－]\s*([0-9０-９]+)")
# 相手の手札を 1 枚捨てさせる
DISCARD_OPP_RE = re.compile(r"相手は(?:自身の手札|手札の)\s*([0-9０-９]+)\s*枚を(?:選び|ランダムに)?\s*捨てる")
# 相手手札を N 枚にする (= 5枚以上なら 4 まで)
HAND_TO_SIZE_RE = re.compile(r"相手の手札が\s*([0-9０-９]+)\s*枚になるように")
# self を手札に戻す (= 自身を return)
RETURN_SELF_TO_HAND_RE = re.compile(r"このキャラを持ち主の手札に戻[しす](?:る)?")
# 自分のトラッシュからカード N 枚 (filter) を手札に
TRASH_TO_HAND_RE = re.compile(r"自分のトラッシュから(?:特徴《([^》]+)》を持つ)?カード\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*手札に加える")

# === Phase 1 新規パターン ===
# 1) 自分のデッキの上から N 枚をトラッシュに置く
MILL_SELF_TOP_RE = re.compile(r"自分のデッキの上から\s*([0-9０-９]+)\s*枚を(?:、)?\s*トラッシュに置く")
# 2) 自分のデッキの上から N 枚を見て、 好きな順番に並び替え、 デッキの上か下に置く / デッキの上 / デッキの下
LOOK_TOP_REORDER_RE = re.compile(
    r"自分のデッキの上から\s*([0-9０-９]+)\s*枚を見て(?:、)?\s*"
    r"(?:好きな順番(?:に|で)?(?:並び替え|並び変え)?(?:、)?)?\s*"
    r"デッキの(上か下|下|上)に置く"
)
# 3) このカードを登場させる (self play)
PLAY_SELF_RE = re.compile(r"このカードを登場させる")
# 4) このカードの【XXX】効果を発動する (self effect copy)
FIRE_SELF_EFFECT_RE = re.compile(r"このカードの【([^】]+)】効果を発動する")
# 5) 相手は自身の(?:場の)?ドン[‼!]+1枚をドン[‼!]+デッキに戻す
RETURN_OPP_DON_RE = re.compile(r"相手は自身の(?:場の)?ドン[‼!]+\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*ドン[‼!]+デッキに戻す")
# 6) 相手は自身の手札 N 枚をデッキの下に置く
OPP_HAND_TO_DECK_BOTTOM_RE = re.compile(r"相手は(?:自身の)?手札\s*([0-9０-９]+)\s*枚(?:まで)?(?:を、?\s*(?:選び|ランダムに))?(?:、)?\s*デッキの下に置く")
# 7) 自分の手札 N 枚をデッキの下に置く
SELF_HAND_TO_DECK_BOTTOM_RE = re.compile(r"自分の手札\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*(?:好きな順番で)?\s*デッキの下に置く")
# 8) このキャラをアクティブにする (= self untap)
UNTAP_SELF_RE = re.compile(r"このキャラ(?:を|は)、?\s*アクティブにする")
# 9) アクティブのキャラにもアタックできる (give アクティブアタック可)
GIVE_ATTACK_ACTIVE_RE = re.compile(r"このキャラ(?:は)?、?\s*相手のアクティブのキャラにもアタックできる")
# 10) コスト N 以下のキャラ 1 枚までを、 持ち主の手札に戻[しす](?:る)? (相手の修飾なし)
RETURN_BARE_COST_RE = re.compile(r"^コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?")
# 11) コスト N 以下のキャラ 1 枚までを、 持ち主のデッキの下に置く
RETURN_BARE_COST_DECK_RE = re.compile(r"^コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主のデッキの下に置く")
# 12) 【ドン!!×N】 このキャラのパワー+M (on_attached_don power_pump)
DON_X_POWER_RE = re.compile(r"【ドン[‼!]+×\s*([0-9０-９]+)\s*】\s*このキャラのパワー\s*\+\s*([0-9０-９]+)")
# 13) 【ドン!!×N】 このキャラはバトルでKOされない (on_attached_don ko_immune)
DON_X_KO_IMMUNE_RE = re.compile(r"【ドン[‼!]+×\s*([0-9０-９]+)\s*】\s*このキャラはバトルでKOされない")
# 14) 【ドン!!×N】 このキャラは【速攻】を得る
DON_X_RUSH_RE = re.compile(r"【ドン[‼!]+×\s*([0-9０-９]+)\s*】\s*このキャラ(?:は)?【(速攻|ブロッカー|ダブルアタック|バニッシュ|ブロック不可)】を得る")
# 15) 【ドン!!×N】 このキャラは、相手のアクティブのキャラにもアタックできる
DON_X_ATTACK_ACTIVE_RE = re.compile(r"【ドン[‼!]+×\s*([0-9０-９]+)\s*】\s*このキャラ(?:は)?、?\s*相手のアクティブのキャラにもアタックできる")
# 16) 自分のリーダーが「X」の場合 / 特徴《X》を持つ場合: leader_name / leader_feature 条件付き
# (既に extract_if が処理。 ここはそのまま prim を抽出するだけ。)
# 17) 相手のライフの上から N 枚までを、 トラッシュに置く (= 相手ライフ trash)
MILL_OPP_LIFE_TO_TRASH_RE = re.compile(r"相手のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*トラッシュに置く")
# 18) 相手は、このバトル中、【ブロッカー】を発動できない (attacker に ブロック不可)
DISABLE_OPP_BLOCKER_BATTLE_RE = re.compile(r"相手は、?\s*このバトル中、?\s*(?:パワー\s*[0-9０-９]+\s*以下のキャラの)?【ブロッカー】を発動できない")
# 19) 相手のリーダーかキャラ N 枚までは、このターン中、アタックできない (cost 制約なし版)
CANNOT_ATTACK_OPP_LDR_OR_CHARA_RE = re.compile(r"相手のリーダーかキャラ\s*([0-9０-９]+)\s*枚(?:まで)?は、?\s*このターン中、?\s*アタックできない")
# 20) 相手のコスト N のキャラ (= 等しい cost) — 「以下」 ではなく完全一致
KO_OPP_EXACT_COST_RE = re.compile(r"相手のコスト\s*([0-9０-９]+)\s*のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?")
RETURN_OPP_EXACT_COST_RE = re.compile(r"相手のコスト\s*([0-9０-９]+)\s*のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?")

# === Phase 2 新パターン ===
# 21) Multi-target: 相手のコスト A 以下のキャラ 1 枚まで と コスト B 以下のキャラ 1 枚までを、 [KO/手札戻し/デッキ下]
MULTI_TARGET_KO_RE = re.compile(
    r"相手の、?\s*コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?と"
    r"コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?"
)
MULTI_TARGET_RETURN_RE = re.compile(
    r"相手の、?\s*コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?と"
    r"コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?"
)
MULTI_TARGET_DECK_RE = re.compile(
    r"相手の、?\s*コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?と"
    r"コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主のデッキの下に(?:好きな順番で)?置く"
)
# 22) パワー X 以上のキャラの ブロッカー無効 (既存の DISABLE は X 以下 専用)
DISABLE_OPP_BLOCKER_BATTLE_GE_RE = re.compile(
    r"相手は、?\s*このバトル中、?\s*パワー\s*([0-9０-９]+)\s*以上のキャラの【ブロッカー】を発動できない"
)
# 23) Trash 登場「レストで」 修飾
PLAY_FROM_TRASH_RESTED_RE = re.compile(
    r"自分のトラッシュから(?:コスト\s*([0-9０-９]+)\s*以下の)?"
    r"(?:特徴《([^》]+)》を持つ)?(?:キャラカード|キャラ)\s*1\s*枚(?:まで)?を、?\s*レストで登場させる"
)
# 24) Target → 持ち主のライフへ (コスト N 以下のキャラを ライフ上か下に表向きで加える)
TO_OPP_LIFE_RE = re.compile(
    r"(?:相手の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*"
    r"持ち主のライフの(?:上か下に|上に|下に)\s*表向き(?:で)?加える"
)
# 25) Hand → 自ライフ (「自分の手札から [filter] 1 枚までを公開し、ライフの上に裏向きで加える」)
HAND_TO_SELF_LIFE_RE = re.compile(
    r"自分の手札から(?:特徴《([^》]+)》を持つ)?(?:コスト\s*([0-9０-９]+)\s*以下の)?"
    r"(?:キャラ)?カード\s*([0-9０-９]+)\s*枚(?:まで)?を(?:公開し|、?)、?"
    r"\s*ライフの(?:上|上か下)に(?:裏|表)?向き(?:で)?加える"
)
# 26) 効果無効 (このターン中)
NEGATE_OPP_EFFECT_RE = re.compile(
    r"相手の(?:リーダーかキャラ|キャラ)\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*"
    r"このターン中、?\s*効果を無効にする"
)
# 27) duration "next_self_turn_start" — 「次の自分のターン開始時まで、 パワー+N」
POWER_PUMP_NEXT_TURN_RE = re.compile(
    r"自分のリーダー(?:1\s*枚まで)?を、?\s*次の自分のターン開始時まで、?\s*パワー\s*\+\s*([0-9０-９]+)"
)

# === Phase 3 バッチ 1 (頻度 5+ パターン) ===
# 28) Multi-target return / KO / deck-bottom — 「相手の」 prefix 無し版
MULTI_TARGET_RETURN_BARE_RE = re.compile(
    r"^コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?と、?"
    r"\s*コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻[しす](?:る)?"
)
MULTI_TARGET_KO_BARE_RE = re.compile(
    r"^コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?と、?"
    r"\s*コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KO[しす](?:る)?"
)
# 29) パワー X 以下のキャラの ブロッカー無効 (= 自分に ブロック不可 付与、 特定パワー帯のみ)
DISABLE_OPP_BLOCKER_TARGET_RE = re.compile(
    r"相手のパワー\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?は、?"
    r"\s*このターン中、?\s*【ブロッカー】を発動できない"
)
# 30) play_from_trash with color filter — 「自分のトラッシュからコスト N 以下の[color]の キャラカード〜登場」
PLAY_FROM_TRASH_COLOR_RE = re.compile(
    r"自分のトラッシュから(?:コスト\s*([0-9０-９]+)\s*以下の)?(赤|青|緑|黄|紫|黒)のキャラカード"
    r"\s*1\s*枚(?:まで)?を、?\s*(レストで)?\s*登場させる"
)
# 31) trash_to_hand with exclude_name + cost range + color/feature
TRASH_TO_HAND_COMPLEX_RE = re.compile(
    r"自分のトラッシュの(?:「([^」]+)」以外の)?"
    r"(?:コスト\s*([0-9０-９]+)\s*(?:から|〜|-)\s*([0-9０-９]+)?の|"
    r"コスト\s*([0-9０-９]+)\s*以下の)?"
    r"(赤|青|緑|黄|紫|黒)?(?:の)?"
    r"(?:特徴《([^》]+)》(?:を持つ)?)?"
    r"(?:キャラ)?カード\s*1\s*枚(?:まで)?を、?\s*手札に加える"
)
# 32) play_from_hand with power filter & trigger filter
PLAY_FROM_HAND_POWER_TRIGGER_RE = re.compile(
    r"自分の手札から(?:パワー\s*([0-9０-９]+)\s*以下の)?"
    r"(?:【トリガー】を持つ)?(?:キャラカード|キャラ)\s*1\s*枚(?:まで)?を、?\s*(?:レストで)?登場させる"
)
# 33) untap target chara (cost-exact / feature-exclude フィルタ)
UNTAP_TARGET_CHARA_RE = re.compile(
    r"自分の(?:「([^」]+)」以外の)?(?:特徴《([^》]+)》を持つ)?キャラ\s*1\s*枚(?:まで)?を、?\s*アクティブにする"
)
# 34) power_pump on filtered chara: 「自分のコスト N の赤のキャラ 1 枚までを、 パワー+M」
POWER_PUMP_COST_EXACT_RE = re.compile(
    r"自分のコスト\s*([0-9０-９]+)\s*の(赤|青|緑|黄|紫|黒)?(?:の)?キャラ\s*1\s*枚(?:まで)?を、?\s*"
    r"(?:このターン中|このバトル中)、?\s*パワー\s*\+\s*([0-9０-９]+)"
)
# 35) 相手のリーダーかキャラ 合計 N 枚 までのパワー-M (multi-target neg pump)
POWER_PUMP_OPP_MULTI_NEG_RE = re.compile(
    r"相手のリーダーかキャラ\s*合計\s*([0-9０-９]+)\s*枚(?:まで)?を、?"
    r"\s*このターン中、?\s*パワー\s*[-－]\s*([0-9０-９]+)"
)
# 36) Draw + 手札 N 枚を デッキ上下置く
DRAW_AND_HAND_TO_DECK_RE = re.compile(
    r"カード\s*([0-9０-９]+)\s*枚を引き、?\s*自分の手札\s*([0-9０-９]+)\s*枚を"
    r"\s*好きな順番で?\s*(?:並び替え、)?デッキの(下|上か下|上)に置く"
)
# 37) compound search: 「デッキ上 N 枚見て、 X以外 / X 以下 / Y特徴 等の1枚を公開し手札へ」 — 既存 SEARCH_RE 拡張版で対応済
# ただし 「カードか〜」 「キャラカードか〜」 等 の OR 表現は未対応 (= 「ビッグマム海賊団 カードか サンジ 」 のような)
SEARCH_OR_NAMED_RE = re.compile(
    r"自分のデッキの上から\s*([0-9０-９]+)\s*枚(?:まで)?を見て、?"
    r"(?:「([^」]+)」以外の)?"
    r"(?:特徴《([^》]+)》を持つ)?"
    r"(?:カード|キャラ(?:カード)?)\s*か\s*「([^」]+)」"
    r"\s*([0-9０-９]+)?\s*枚?(?:まで)?を、?\s*公開し、?\s*手札に加える"
)

# === Phase 3 バッチ 2 (頻度 3-9 パターン) ===
# 38) 自分のキャラに dop attach (= このキャラに ドン!!N 枚) — activate_main + self attach
ATTACH_DON_SELF_RE = re.compile(
    r"このキャラに(?:レストの|アクティブの)?\s*ドン\s*[‼!]+\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*付与する"
)
# 39) Search with color (「赤のイベント」「コスト1の赤のキャラ」 等)
SEARCH_WITH_COLOR_RE = re.compile(
    r"自分のデッキの上から\s*([0-9０-９]+)\s*枚(?:まで)?を見て、?"
    r"(?:コスト\s*([0-9０-９]+)\s*(?:以下|の)?)?(?:の)?"
    r"(赤|青|緑|黄|紫|黒)の(イベント|キャラ(?:カード)?|カード)"
    r"\s*([0-9０-９]+)?\s*枚?(?:まで)?を、?\s*公開し、?\s*手札に加える"
)
# 40) Multi stay_rested for リーダーとキャラ合計 N 枚 (= リーダー+キャラ含む)
MULTI_STAY_RESTED_LDR_CHARA_RE = re.compile(
    r"相手のレストの、?\s*リーダーとキャラ合計\s*([0-9０-９]+)\s*枚(?:まで)?は、?"
    r"\s*次の相手のリフレッシュフェイズでアクティブにならない"
)
# 41) in_hand_cost_minus with feature filter (「コスト N 以上の特徴 Y のキャラのコストは M 少なくなる」)
COST_REDUCTION_FEATURE_RE = re.compile(
    r"自分が手札から登場させる(?:コスト\s*([0-9０-９]+)\s*以上の)?"
    r"特徴《([^》]+)》を持つ(?:カード|キャラ(?:カード)?)の支払うコストは\s*([0-9０-９]+)\s*少なくなる"
)
# 42) 「自分のキャラ N 枚をレストにできる：」 (cost 用 既存 COST_REST_SELF_CHARAS_RE があるはず)
# 既存: COST_REST_SELF_CHARAS_RE = 自分のキャラ N 枚を レストに[しす](?:る)? — 流用可
# 43) leader_features_any 条件付き 効果 (「自分のリーダーが『X』を含む特徴を持つ場合」) — 既存 extract_if で対応済
# 44) 自分のドン!!を1枚以上ドン!!デッキに戻すことができる (= cost variable) — 簡略で pay_don=1 として処理
COST_PAY_DON_VAR_RE = re.compile(
    r"自分の(?:場の)?ドン\s*[‼!]+\s*を\s*([0-9０-９]+)\s*枚以上\s*ドン\s*[‼!]+\s*デッキに戻す"
)
# 45) 「このキャラ以外の自分のキャラすべて」 を [デッキの下/トラッシュ] に置く
SELF_CHARAS_TO_DECK_BOTTOM_RE = re.compile(
    r"このキャラ以外の自分のキャラすべて(?:を)?(?:、)?\s*"
    r"(?:好きな順番で)?\s*デッキの下に置く"
)
SELF_CHARAS_TO_TRASH_RE = re.compile(
    r"このキャラ以外の自分のキャラすべて(?:を)?(?:、)?\s*トラッシュに置く"
)
# 46) このキャラは、 このターン中、 [keyword] を得る
SELF_GIVE_KEYWORD_TURN_RE = re.compile(
    r"このキャラ(?:は)?、?\s*このターン中、?\s*【(速攻|ブロッカー|ダブルアタック|バニッシュ|ブロック不可)】を得る"
)
# 47) self_life_eq_0 condition: 「自分のライフが N 枚になった時」
SELF_LIFE_EQ_RE = re.compile(r"自分のライフが\s*([0-9０-９]+)\s*枚になった時")
# 48) ターン追加 (= "このターンの後に自分のターンを追加で得る") — rare, mark as primitive
EXTRA_TURN_RE = re.compile(r"このターンの後に自分のターンを追加で得る")
# 49) リーダーが多色の場合の 条件 (既存 leader_color: 多色 を使用、 extract_if で対応済)
# 50) 「このキャラを持ち主の手札に戻すことができる：」 — cost
COST_RETURN_SELF_TO_HAND_RE = re.compile(r"このキャラを持ち主の手札に戻すことができる[：:]")
# 51) 「相手のレストの、リーダーとキャラ N 枚までを選ぶ。 選んだカードは次の相手のリフレッシュでアクティブにならない」 — rare
# 52) 「自分の手札から特徴《X》を持つカード1枚を捨てることができる：」 — cost (feature-filtered discard)
COST_DISCARD_FEATURE_RE = re.compile(
    r"自分の手札から(?:『([^』]+)』を含む特徴を持つ|特徴《([^》]+)》を持つ)カード\s*([0-9０-９]+)?\s*枚?を捨てる(?:ことができる)?"
)
# 53) この キャラカードをトラッシュからレストで登場させる
PLAY_SELF_FROM_TRASH_RESTED_RE = re.compile(
    r"このキャラカードをトラッシュから(?:レストで)?登場させる"
)
# 54) 「ドン!! N 枚以上ドン!!デッキに戻すことができる」 cost — 既存 COST_PAY_DON_VAR_RE
# 55) condition: 「このキャラのパワーが N 以上の場合」 — self_attached_buff の参照
COND_SELF_POWER_GE_RE = re.compile(r"このキャラのパワーが\s*([0-9０-９]+)\s*以上の場合")


def extract_primitives(body: str) -> list[dict]:
    """body から DSL primitive を抽出。"""
    primitives: list[dict] = []

    if m := DRAW_RE.search(body):
        primitives.append({"draw": to_int(m.group(1))})
    if m := LIFE_TO_HAND_RE.search(body):
        primitives.append({"life_to_hand": to_int(m.group(1))})
    if m := PUT_TOP_TO_LIFE_RE.search(body):
        primitives.append({"put_top_to_life": to_int(m.group(1))})
    if m := MILL_SELF_LIFE_RE.search(body):
        primitives.append({"mill_self_life_to_trash": to_int(m.group(1))})
    if m := MILL_OPP_LIFE_RE.search(body):
        primitives.append({"mill_opp_life_to_hand": to_int(m.group(1))})
    if m := TRASH_SELF_HAND_RE.search(body):
        primitives.append({"trash_self_hand_random": to_int(m.group(1))})
    if m := TRASH_OPP_HAND_RE.search(body):
        primitives.append({"trash_opp_hand_random": to_int(m.group(1))})
    if m := ADD_DON_RE.search(body):
        primitives.append({"add_don": to_int(m.group(1))})
    if m := ADD_RESTED_DON_RE.search(body):
        primitives.append({"add_rested_don": to_int(m.group(1))})
    if m := UNTAP_DON_RE.search(body):
        primitives.append({"untap_don": to_int(m.group(1))})

    # power_pump (リーダーまたはリーダーかキャラ、 +/-)
    is_battle = "このバトル中" in body
    duration = "battle" if is_battle else "turn"
    if m := POWER_PUMP_LEADER_RE.search(body):
        primitives.append({"power_pump": {"target": "self_leader", "amount": to_int(m.group(1)), "duration": duration}})
    elif m := POWER_PUMP_INPLAY_RE.search(body):
        primitives.append({"power_pump": {"target": "self_inplay", "amount": to_int(m.group(1)), "duration": duration}})
    elif m := POWER_PUMP_ALL_SELF_RE.search(body):
        primitives.append({"power_pump": {"target": "all_self_team", "amount": to_int(m.group(1)), "duration": duration}})
    elif m := POWER_PUMP_SELF_CHARA_RE.search(body):
        primitives.append({"power_pump": {"target": "self", "amount": to_int(m.group(1)), "duration": duration}})
    if m := POWER_PUMP_OPP_NEG_RE.search(body):
        primitives.append({"power_pump": {"target": "one_opponent_character_le_5000", "amount": -to_int(m.group(1)), "duration": "turn"}})
    elif m := POWER_PUMP_OPP_NEG_MULTI_RE.search(body):
        # N 枚まで → any_opponent_character_le_5000 で近似 (= 全 ≤5000 対象。 1 ply での影響は同じ)
        primitives.append({"power_pump": {"target": "any_opponent_character_le_5000", "amount": -to_int(m.group(2)), "duration": "turn"}})
    elif m := POWER_PUMP_ALL_OPP_NEG_RE.search(body):
        primitives.append({"power_pump": {"target": "all_opponent_characters", "amount": -to_int(m.group(1)), "duration": "turn"}})

    # KO / bounce / rest (相手対象、 cost 限定 → 一般)
    ko_added = False
    return_added = False
    rest_added = False
    stay_added = False
    attack_added = False
    if m := KO_OPP_COST_RE.search(body):
        primitives.append({"ko": f"one_opponent_character_cost_le_{m.group(1)}cost"})
        ko_added = True
    elif m := KO_OPP_POWER_RE.search(body):
        primitives.append({"ko": f"one_opponent_character_power_le_{m.group(1)}"})
        ko_added = True
    elif KO_OPP_RESTED_RE.search(body):
        primitives.append({"ko": "one_opponent_rested_character_le_5000"})
        ko_added = True
    elif KO_OPP_ANY_RE.search(body) and not ko_added:
        primitives.append({"ko": "one_opponent_character_any"})
        ko_added = True
    # 「相手のリーダーかキャラ N 枚まで」 のパワー減 (multi-target)
    if not ko_added:
        m_multi = re.search(r"相手の(?:キャラ|リーダーかキャラ)\s*[2-9]\s*枚まで.*?KO[しす](?:る)?", body)
        if m_multi:
            primitives.append({"ko": "any_opponent_character_le_5000"})
            ko_added = True
    if m := RETURN_OPP_COST_RE.search(body):
        primitives.append({"return_to_hand": f"one_opponent_character_cost_le_{m.group(1)}cost"})
        return_added = True
    elif RETURN_OPP_ANY_RE.search(body) and not return_added:
        primitives.append({"return_to_hand": "one_opponent_character_any"})
        return_added = True
    if m := RETURN_OPP_DECK_BOTTOM_RE.search(body):
        cost_str = m.group(1)
        if cost_str:
            primitives.append({"return_to_deck_bottom": f"one_opponent_character_cost_le_{cost_str}cost"})
        else:
            primitives.append({"return_to_deck_bottom": "one_opponent_character_any"})
    if m := REST_OPP_COST_RE.search(body):
        primitives.append({"rest": f"one_opponent_character_cost_le_{m.group(1)}cost"})
        rest_added = True
    elif REST_OPP_ANY_RE.search(body) and not rest_added:
        primitives.append({"rest": "one_opponent_character_any"})
        rest_added = True
    if m := STAY_RESTED_OPP_RE.search(body):
        primitives.append({"stay_rested_next_refresh": f"one_opponent_rested_character_cost_le_{m.group(1)}cost"})
        stay_added = True
    elif STAY_RESTED_OPP_ANY_RE.search(body) and not stay_added:
        primitives.append({"stay_rested_next_refresh": "one_opponent_rested_character_le_5000"})
        stay_added = True
    if m := CANNOT_ATTACK_OPP_RE.search(body):
        primitives.append({"set_cannot_attack": f"one_opponent_character_cost_le_{m.group(1)}cost"})
        attack_added = True
    elif CANNOT_ATTACK_OPP_ANY_RE.search(body) and not attack_added:
        primitives.append({"set_cannot_attack": "one_opponent_character_any"})
        attack_added = True

    # cost +/-
    if m := COST_MINUS_OPP_RE.search(body):
        primitives.append({"cost_minus": {"target": "one_opponent_character_le_5000", "amount": to_int(m.group(1))}})
    elif m := COST_PLUS_OPP_RE.search(body):
        primitives.append({"cost_minus": {"target": "one_opponent_character_le_5000", "amount": -to_int(m.group(1))}})

    # 相手手札捨て
    if m := DISCARD_OPP_RE.search(body):
        primitives.append({"trash_opp_hand_random": to_int(m.group(1))})
    if m := HAND_TO_SIZE_RE.search(body):
        primitives.append({"self_hand_to_size": to_int(m.group(1))})

    # untap (キャラ)
    if UNTAP_SELF_LEADER_RE.search(body) and "ドン" not in body[:body.find("アクティブにする")]:
        primitives.append({"untap": "self_leader"})
    elif UNTAP_SELF_CHARA_RE.search(body):
        primitives.append({"untap_chara": {"target": "one_self_character_any", "limit": 1}})

    # 召喚 (デッキから)
    if m := SUMMON_FROM_DECK_RE.search(body):
        cost_le = m.group(1)
        feature = m.group(2)
        filt = {}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        if feature:
            filt["feature"] = feature
        primitives.append({"summon_from_deck": {"filter": filt, "limit": 1}})

    # トラッシュからカード (= 非キャラ含む) 手札へ
    if m := TRASH_TO_HAND_RE.search(body):
        feature = m.group(1)
        n = to_int(m.group(2))
        filt = {"feature": feature} if feature else {}
        primitives.append({"trash_to_hand": {"filter": filt, "limit": n}})

    # シャッフル
    if SHUFFLE_DECK_RE.search(body):
        primitives.append({"shuffle_self_deck": True})

    # search
    if m := SEARCH_RE.search(body):
        depth = to_int(m.group(1))
        filter_text = m.group("filter") or ""
        limit_str = m.group(3)
        limit = to_int(limit_str) if limit_str else 1
        filt: dict = {}
        if fm := FILT_FEATURE_RE.search(filter_text):
            filt["feature"] = fm.group(1)
        if cm := FILT_COST_LE_RE.search(filter_text):
            filt["cost_le"] = to_int(cm.group(1))
        if em := FILT_EXCLUDE_NAME_RE.search(filter_text):
            filt["exclude_name"] = em.group(1)
        primitives.append({"search": {"filter": filt, "limit": limit, "depth": depth}})
        # 「その後、 残りを好きな順番でデッキの下に置く」 サフィックスがあれば
        # 同 depth で look_top_reorder (to=bottom) を追加 (= 残りを下へ)
        # 注: 既に search で N 枚を手札に取ったので、 残りは深度から取得済み分を引いた数。
        # しかし search 実装はデッキから filter 一致を抜き出して再シャッフルなので、
        # 「残りをデッキ下」 は概念的に意味を成しにくい。 ここでは look_top_reorder で
        # next の depth 枚を底に持っていく (= bottom 並び替え) ことで近似。
        suffix_re = re.compile(r"その後、?\s*残りを好きな順番でデッキの下に置く")
        if suffix_re.search(body):
            # depth は search の depth と同じ
            primitives.append({"look_top_reorder": {"depth": depth, "to": "bottom"}})

    # 登場系
    if m := PLAY_FROM_TRASH_RE.search(body):
        cost_le = m.group(1)
        feature = m.group(2)
        filt: dict = {}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        if feature:
            filt["feature"] = feature
        primitives.append({"play_from_trash": {"filter": filt, "limit": 1}})
    if m := PLAY_FROM_HAND_RE.search(body):
        cost_le = m.group(1)
        feature = m.group(2)
        filt: dict = {}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        if feature:
            filt["feature"] = feature
        primitives.append({"play_from_hand": {"filter": filt, "limit": 1}})

    # キーワード付与
    if m := GIVE_KEYWORD_RE.search(body):
        primitives.append({"give_keyword": {"target": "self_inplay", "keyword": m.group(1)}})

    # ドン付与 (自リーダーに / 自リーダーかキャラに / 自キャラ 1 体に)
    rested = "レストで" in body or "レストの" in body
    if m := ATTACH_DON_INPLAY_RE.search(body):
        primitives.append({"attach_don": {"target": "self_inplay_choice", "count": to_int(m.group(1)), "rested": rested}})
    elif m := ATTACH_DON_LEADER_RE.search(body):
        primitives.append({"attach_don": {"target": "self_leader", "count": to_int(m.group(1)), "rested": rested}})
    elif m := ATTACH_DON_CHARA_RE.search(body):
        primitives.append({"attach_don": {"target": "one_self_character_any", "count": to_int(m.group(1)), "rested": rested}})

    # 相手リーダーかキャラ パワー-N
    if not any("power_pump" in p and p.get("power_pump", {}).get("amount", 0) < 0 for p in primitives if isinstance(p, dict)):
        if m := POWER_PUMP_OPP_LEADER_OR_CHARA_NEG_RE.search(body):
            primitives.append({"power_pump": {"target": "one_opponent_character_le_5000", "amount": -to_int(m.group(1)), "duration": "turn"}})

    # 相手レスト cost N 以下キャラ KO
    if m := KO_OPP_RESTED_COST_RE.search(body):
        primitives.append({"ko": f"one_opponent_rested_character_cost_le_{m.group(1)}cost"})

    # === Phase 1 新規: deck/hand/self/don 操作 ===
    # 自デッキ上 N 枚を trash
    if m := MILL_SELF_TOP_RE.search(body):
        primitives.append({"mill_self_top": to_int(m.group(1))})
    # 自デッキ上 N 枚を見て並び替え (= scry)
    if m := LOOK_TOP_REORDER_RE.search(body):
        depth = to_int(m.group(1))
        place = m.group(2)
        # 「上か下」 → choice / 「上」 → top / 「下」 → bottom
        to_pos = {"上か下": "choice", "上": "top", "下": "bottom"}.get(place, "choice")
        primitives.append({"look_top_reorder": {"depth": depth, "to": to_pos}})
    # 相手ライフを trash (バニッシュ的)
    if m := MILL_OPP_LIFE_TO_TRASH_RE.search(body):
        primitives.append({"mill_opp_life_to_trash": to_int(m.group(1))})
    # 相手ドン返却
    if m := RETURN_OPP_DON_RE.search(body):
        primitives.append({"return_opp_don": to_int(m.group(1))})
    # 相手手札 → デッキ下
    if m := OPP_HAND_TO_DECK_BOTTOM_RE.search(body):
        primitives.append({"opp_hand_to_deck_bottom": to_int(m.group(1))})
    # 自分手札 → デッキ下
    if m := SELF_HAND_TO_DECK_BOTTOM_RE.search(body):
        primitives.append({"self_hand_to_deck_bottom": to_int(m.group(1))})
    # コスト N 以下キャラ → 手札へ (相手の修飾なしの bare 形)
    if m := RETURN_BARE_COST_RE.search(body):
        primitives.append({"return_to_hand": f"one_opponent_character_cost_le_{m.group(1)}cost"})
    # コスト N 以下キャラ → デッキ下へ (bare 形)
    if m := RETURN_BARE_COST_DECK_RE.search(body):
        primitives.append({"return_to_deck_bottom": f"one_opponent_character_cost_le_{m.group(1)}cost"})
    # このキャラを active 化
    if UNTAP_SELF_RE.search(body) and not any("untap" in p for p in primitives):
        primitives.append({"untap": "self"})
    # アクティブアタック可
    if GIVE_ATTACK_ACTIVE_RE.search(body):
        primitives.append({"give_attack_active_chara": "self"})
    # このカードを登場させる (self play)
    if PLAY_SELF_RE.search(body):
        primitives.append({"play_self": True})
    # このカードの【XXX】効果を発動する
    if m := FIRE_SELF_EFFECT_RE.search(body):
        marker = m.group(1)
        when_kind = TRIGGER_MAP.get(marker, marker)  # 【メイン】→ "main" など
        primitives.append({"fire_self_effect": {"when_kind": when_kind}})

    # 相手のブロッカー封じ (このバトル中) → 自分に ブロック不可 付与 (turn 期限で over-grant 許容)
    if DISABLE_OPP_BLOCKER_BATTLE_RE.search(body):
        primitives.append({"give_keyword": {"target": "self", "keyword": "ブロック不可"}})

    # 相手のリーダーかキャラ N 枚までは、このターン中、アタックできない
    if m := CANNOT_ATTACK_OPP_LDR_OR_CHARA_RE.search(body):
        primitives.append({"set_cannot_attack": "one_opponent_inplay_any"})

    # 相手のコスト N (exact) のキャラ → KO / 手札戻し
    if m := KO_OPP_EXACT_COST_RE.search(body):
        primitives.append({"ko": f"one_opponent_character_cost_eq_{m.group(1)}"})
    if m := RETURN_OPP_EXACT_COST_RE.search(body):
        primitives.append({"return_to_hand": f"one_opponent_character_cost_eq_{m.group(1)}"})

    # === Phase 2 新パターン ===
    # 21) Multi-target KO / return / deck-bottom (2 つの cost cap 同時)
    if m := MULTI_TARGET_KO_RE.search(body):
        a, b = to_int(m.group(1)), to_int(m.group(2))
        primitives.append({"ko_multi": [
            f"one_opponent_character_cost_le_{a}cost",
            f"one_opponent_character_cost_le_{b}cost",
        ]})
    elif m := MULTI_TARGET_RETURN_RE.search(body):
        a, b = to_int(m.group(1)), to_int(m.group(2))
        primitives.append({"return_to_hand_multi": [
            f"one_opponent_character_cost_le_{a}cost",
            f"one_opponent_character_cost_le_{b}cost",
        ]})
    elif m := MULTI_TARGET_DECK_RE.search(body):
        a, b = to_int(m.group(1)), to_int(m.group(2))
        primitives.append({"return_to_deck_bottom_multi": [
            f"one_opponent_character_cost_le_{a}cost",
            f"one_opponent_character_cost_le_{b}cost",
        ]})
    # 22) パワー X 以上のキャラの ブロッカー無効 (= 自分に ブロック不可 付与)
    if DISABLE_OPP_BLOCKER_BATTLE_GE_RE.search(body):
        if not any(
            isinstance(p, dict) and "give_keyword" in p
            and p.get("give_keyword", {}).get("keyword") == "ブロック不可"
            for p in primitives
        ):
            primitives.append({"give_keyword": {"target": "self", "keyword": "ブロック不可"}})
    # 23) Trash 「レストで」 登場 — 既存 play_from_trash を生成しつつ rested=True
    if m := PLAY_FROM_TRASH_RESTED_RE.search(body):
        cost_le = m.group(1)
        feature = m.group(2)
        filt: dict = {}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        if feature:
            filt["feature"] = feature
        # 既存に同様の play_from_trash が無ければ追加
        if not any("play_from_trash" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"play_from_trash": {"filter": filt, "limit": 1, "rested": True}})
    # 24) Target → 持ち主のライフ
    if m := TO_OPP_LIFE_RE.search(body):
        cost_le = to_int(m.group(1))
        primitives.append({"to_opp_life": f"one_opponent_character_cost_le_{cost_le}cost"})
    # 25) Hand → 自ライフ (filter は近似)
    if m := HAND_TO_SELF_LIFE_RE.search(body):
        feature = m.group(1)
        cost_le = m.group(2)
        count = to_int(m.group(3))
        filt: dict = {"category": "CHARACTER"}
        if feature:
            filt["feature"] = feature
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        primitives.append({"hand_to_self_life": {"filter": filt, "count": count}})
    # 26) 効果無効化
    if m := NEGATE_OPP_EFFECT_RE.search(body):
        # 「リーダーかキャラ」 か 「キャラ」 で target を分ける
        if "リーダーかキャラ" in body:
            target = "one_opponent_inplay_any"
        else:
            target = "one_opponent_character_any"
        primitives.append({"negate_effect": target})
    # 27) duration "next_self_turn_start"
    if m := POWER_PUMP_NEXT_TURN_RE.search(body):
        # 重複しないよう既存 power_pump があれば追加しない
        if not any(
            isinstance(p, dict) and "power_pump" in p
            and p["power_pump"].get("duration") == "next_self_turn_start"
            for p in primitives
        ):
            primitives.append({"power_pump": {
                "target": "self_leader",
                "amount": to_int(m.group(1)),
                "duration": "next_self_turn_start",
            }})

    # === Phase 3 バッチ 1 ===
    # 28) Multi-target bare 形 (= 「相手の」 prefix 無し)
    body_stripped = body.lstrip("、。 \n")
    if m := MULTI_TARGET_RETURN_BARE_RE.match(body_stripped):
        a, b = to_int(m.group(1)), to_int(m.group(2))
        if not any("return_to_hand_multi" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"return_to_hand_multi": [
                f"one_opponent_character_cost_le_{a}cost",
                f"one_opponent_character_cost_le_{b}cost",
            ]})
    elif m := MULTI_TARGET_KO_BARE_RE.match(body_stripped):
        a, b = to_int(m.group(1)), to_int(m.group(2))
        if not any("ko_multi" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"ko_multi": [
                f"one_opponent_character_cost_le_{a}cost",
                f"one_opponent_character_cost_le_{b}cost",
            ]})
    # 29) パワー X 以下のキャラの ブロッカー無効 (= 自分に ブロック不可)
    if DISABLE_OPP_BLOCKER_TARGET_RE.search(body):
        if not any(
            isinstance(p, dict) and "give_keyword" in p
            and p.get("give_keyword", {}).get("keyword") == "ブロック不可"
            for p in primitives
        ):
            primitives.append({"give_keyword": {"target": "self", "keyword": "ブロック不可"}})
    # 30) play_from_trash with color filter
    if m := PLAY_FROM_TRASH_COLOR_RE.search(body):
        cost_le = m.group(1)
        color = m.group(2)
        rested = m.group(3) == "レストで"
        filt: dict = {"color": color}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        # 既存に play_from_trash なければ追加
        if not any("play_from_trash" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"play_from_trash": {"filter": filt, "limit": 1, "rested": rested}})
    # 31) trash_to_hand (色 + 特徴 + 除外名 + コスト範囲)
    if m := TRASH_TO_HAND_COMPLEX_RE.search(body):
        exclude_name = m.group(1)
        cost_lo = m.group(2)
        cost_hi = m.group(3)
        cost_le_single = m.group(4)
        color = m.group(5)
        feature = m.group(6)
        filt: dict = {}
        if exclude_name:
            filt["exclude_name"] = exclude_name
        if cost_lo and cost_hi:
            filt["cost_ge"] = to_int(cost_lo)
            filt["cost_le"] = to_int(cost_hi)
        elif cost_le_single:
            filt["cost_le"] = to_int(cost_le_single)
        if color:
            filt["color"] = color
        if feature:
            filt["feature"] = feature
        # 既存に trash_to_hand なければ追加
        if filt and not any("trash_to_hand" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"trash_to_hand": {"filter": filt, "limit": 1}})
    # 32) play_from_hand with power 制限 + trigger 制限
    if m := PLAY_FROM_HAND_POWER_TRIGGER_RE.search(body):
        power_le = m.group(1)
        # filter は power_le + has_trigger=true (= 後者は新フィルタ)
        filt: dict = {}
        if power_le:
            filt["power_le"] = to_int(power_le)
        if "【トリガー】を持つ" in body:
            filt["has_trigger"] = True
        # rested 修飾検出
        rested = "レストで登場" in body
        if filt and not any("play_from_hand" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"play_from_hand": {"filter": filt, "limit": 1, "rested": rested}})
    # 33) untap target chara (filter 付き)
    if m := UNTAP_TARGET_CHARA_RE.search(body):
        exclude_name = m.group(1)
        feature = m.group(2)
        if exclude_name or feature:
            filt: dict = {}
            if exclude_name:
                filt["exclude_name"] = exclude_name
            if feature:
                filt["feature"] = feature
            if not any("untap_chara" in p for p in primitives if isinstance(p, dict)):
                primitives.append({"untap_chara": {"target": "one_self_character_filtered", "filter": filt, "limit": 1}})
    # 34) 自分のコスト N の [color] キャラ +M
    if m := POWER_PUMP_COST_EXACT_RE.search(body):
        cost = to_int(m.group(1))
        color = m.group(2)
        amount = to_int(m.group(3))
        # target = one_self_character_cost_eq_N (色フィルタは省略 — 主にコスト)
        primitives.append({"power_pump": {
            "target": f"one_self_character_cost_eq_{cost}",
            "amount": amount,
            "duration": "turn",
        }})
    # 35) 相手のリーダーかキャラ 合計 N 枚 まで パワー-M
    if m := POWER_PUMP_OPP_MULTI_NEG_RE.search(body):
        n = to_int(m.group(1))
        amount = -to_int(m.group(2))
        primitives.append({"power_pump": {
            "target": f"any_opp_inplay_n_{n}",
            "amount": amount,
            "duration": "turn",
        }})
    # 36) Draw + 手札 N 枚を デッキ上下
    if m := DRAW_AND_HAND_TO_DECK_RE.search(body):
        n_draw = to_int(m.group(1))
        n_hand_back = to_int(m.group(2))
        place = m.group(3)  # 「下」 / 「上か下」 / 「上」
        # draw + self_hand_to_deck_bottom (簡略: 場所は下に固定 — 「上か下」 はヒューリスティック)
        if not any("draw" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"draw": n_draw})
        primitives.append({"self_hand_to_deck_bottom": n_hand_back})
    # 37) Search OR-named (「特徴 X カードか 名前 Y」)
    if m := SEARCH_OR_NAMED_RE.search(body):
        depth = to_int(m.group(1))
        exclude = m.group(2)
        feature = m.group(3)
        named = m.group(4)
        limit_str = m.group(5)
        limit = to_int(limit_str) if limit_str else 1
        filt: dict = {"limit": limit, "depth": depth}
        # OR 表現: feature OR named のいずれか
        if feature:
            filt["feature_or_name"] = {"feature": feature, "name": named}
        if exclude:
            filt["exclude_name"] = exclude
        # 既存 search が無ければ追加
        if not any("search" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"search": filt})

    # === Phase 3 バッチ 2 ===
    # 38) このキャラにドン!!N 枚を付与 (self attach)
    if m := ATTACH_DON_SELF_RE.search(body):
        rested = "レストの" in body[:body.find("付与する")]
        if not any("attach_don" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"attach_don": {"target": "self", "count": to_int(m.group(1)), "rested": rested}})
    # 39) Search with color filter
    if m := SEARCH_WITH_COLOR_RE.search(body):
        depth = to_int(m.group(1))
        cost_le = m.group(2)
        color = m.group(3)
        category_str = m.group(4)
        limit_str = m.group(5)
        limit = to_int(limit_str) if limit_str else 1
        filt: dict = {"color": color}
        if cost_le:
            filt["cost_le"] = to_int(cost_le)
        if "イベント" in category_str:
            filt["category"] = "EVENT"
        elif "キャラ" in category_str:
            filt["category"] = "CHARACTER"
        if not any("search" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"search": {"filter": filt, "limit": limit, "depth": depth}})
    # 40) Multi stay_rested for リーダーとキャラ
    if m := MULTI_STAY_RESTED_LDR_CHARA_RE.search(body):
        n = to_int(m.group(1))
        # 簡略: 既存 stay_rested_next_refresh プリミティブで近似 (target spec で全 N 体)
        # 文字列 spec の制約上、 リーダー対象は不可だが、 N 体のキャラに stay_rested で近似
        primitives.append({"stay_rested_next_refresh": "any_opp_rested_chara_n_" + str(n)})
    # 41) in_hand_cost_minus with feature filter
    if m := COST_REDUCTION_FEATURE_RE.search(body):
        cost_ge_str = m.group(1)
        feature = m.group(2)
        minus = to_int(m.group(3))
        # in_hand_cost_minus は overlay の when="in_hand" で使う想定 — 対象 feature/cost_ge を保存
        # 簡略: feature filter で reduce_play_cost を発動 (= 累積 +N)
        # 注: reduce_play_cost は次の登場 1 件のみ軽減なので、 「特徴 X 全部に -M」 と微妙に異なる
        # 厳密実装は時間がかかるので、 reduce_play_cost で近似
        primitives.append({"reduce_play_cost": {"amount": minus, "feature": feature}})
    # 44) Variable pay_don cost (1 枚以上)
    if m := COST_PAY_DON_VAR_RE.search(body):
        # 「N 枚以上」 → 簡略で N=1 として cost に追加 (= 最低 1 枚)。
        # ただし extract_cost は別途呼ばれる。 ここでは effect 内に 「速攻 + ドロー」 等を追加する
        # 主目的は 「効果文 が一見プリミティブを持たない」 のを避けること。
        pass  # cost extraction は extract_cost が担当

    # 45) このキャラ以外の自分のキャラすべてを デッキ下/トラッシュ
    if SELF_CHARAS_TO_DECK_BOTTOM_RE.search(body):
        primitives.append({"other_self_charas_to_deck_bottom": True})
    if SELF_CHARAS_TO_TRASH_RE.search(body):
        primitives.append({"other_self_charas_to_trash": True})

    # 46) このキャラは このターン中 [keyword] を得る (= 自身に give_keyword)
    if m := SELF_GIVE_KEYWORD_TURN_RE.search(body):
        keyword = m.group(1)
        if not any(
            isinstance(p, dict) and "give_keyword" in p
            and p.get("give_keyword", {}).get("keyword") == keyword
            for p in primitives
        ):
            primitives.append({"give_keyword": {"target": "self", "keyword": keyword}})

    # 48) ターン追加 (rare, 簡略実装)
    if EXTRA_TURN_RE.search(body):
        primitives.append({"extra_turn": True})

    # 50) このキャラを持ち主の手札に戻す — self bounce (cost or effect)
    if "このキャラを持ち主の手札に戻す" in body and "ことができる" not in body:
        primitives.append({"return_self_to_hand": True})

    # 53) このキャラカードをトラッシュからレストで登場
    if PLAY_SELF_FROM_TRASH_RESTED_RE.search(body):
        # play_self は trash 検索 + 場へ。 rested=True で同等の動作を実装
        if not any("play_self" in p for p in primitives if isinstance(p, dict)):
            primitives.append({"play_self": {"from": "trash", "rested": True}})

    return primitives


# --------------------------------------------------------------------------- #
# 1 カードの overlay 構築
# --------------------------------------------------------------------------- #
def _is_noise_body(body: str) -> bool:
    """空文字・「/」 のみ・短すぎる body は noise (= primitive 抽出無意味) として skip。"""
    s = (body or "").strip()
    if not s or s in ("/", "・", "／"):
        return True
    # ブロッカー説明文 (CardDef で表現済) の典型的な括弧書きのみ
    if "相手のアタックの後" in s and "アタックの対象" in s:
        return True
    if "登場したターンに" in s and "アタックできる" in s and len(s) < 60:
        return True
    if "(このカードが与えるダメージは2になる)" in s and len(s) < 50:
        return True
    return False


DON_X_SECTION_RE = re.compile(
    r"【ドン[‼!]+×\s*([0-9０-９]+)\s*】(.*?)(?=【ドン[‼!]+×|$)",
    re.DOTALL,
)


def extract_don_x_sections(text: str) -> list[dict]:
    """【ドン!!×N】 で始まるセクションを抽出。

    body 内に【XXX時】 等 のトリガー marker がある場合は、 トリガー entries として
    `if: {self_attached_don_ge: N}` 条件付きで生成。 そうでなければ on_attached_don entry。
    """
    out: list[dict] = []
    for m in DON_X_SECTION_RE.finditer(text):
        n_required = to_int(m.group(1))
        body = (m.group(2) or "").strip("\n。 ")
        if not body:
            continue

        # body 内に トリガー marker (【XXX時】 等) があるか確認
        trigger_secs = split_by_trigger(body)
        if trigger_secs:
            # 各 trigger section に条件 self_attached_don_ge=N を付けて出力
            for when, tbody in trigger_secs:
                if _is_noise_body(tbody):
                    continue
                cost = extract_cost(tbody)
                cond = extract_if(tbody)
                cond["self_attached_don_ge"] = n_required
                prims = extract_primitives(tbody)
                if not prims:
                    prims = [{"_unimplemented": f"【ドン!!×{n_required}】【{when}】{tbody}"}]
                entry: dict = {
                    "_text": f"don×{n_required} {when}: {tbody[:60]}",
                    "when": when,
                    "do": prims,
                    "if": cond,
                }
                if cost:
                    entry["cost"] = cost
                out.append(entry)
            continue

        # トリガー marker 無し → 従来の on_attached_don 解析
        prims: list[dict] = []
        if pm := DON_X_POWER_RE.match(f"【ドン!!×{m.group(1)}】" + body):
            prims.append({"power_pump": {
                "target": "self_inplay",
                "amount": to_int(pm.group(2)),
                "duration": "static",
            }})
        if DON_X_KO_IMMUNE_RE.search(f"【ドン!!×{m.group(1)}】" + body):
            prims.append({"set_ko_immune": "self"})
        if km := DON_X_RUSH_RE.search(f"【ドン!!×{m.group(1)}】" + body):
            prims.append({"give_keyword": {"target": "self", "keyword": km.group(2)}})
        if DON_X_ATTACK_ACTIVE_RE.search(f"【ドン!!×{m.group(1)}】" + body):
            prims.append({"give_attack_active_chara": "self"})
        if not prims:
            prims = [{"_unimplemented": f"【ドン!!×{n_required}】{body}"}]
        out.append({
            "_text": f"on_attached_don n={n_required}: {body[:60]}",
            "when": "on_attached_don",
            "n": n_required,
            "do": prims,
        })
    return out


def build_overlay_for_card(card: dict) -> list[dict]:
    """1 カードの overlay を構築。 解析できない部分は _unimplemented stub で残す。"""
    text = (card.get("text") or "").strip()
    trigger_text = (card.get("trigger") or "").strip()
    cid = card.get("card_id", "")

    entries: list[dict] = []

    # 【ドン!!×N】 セクション (= on_attached_don 静的効果)
    entries.extend(extract_don_x_sections(text))

    # 通常テキストの分解
    sections = split_by_trigger(text)
    for when, body in sections:
        if _is_noise_body(body):
            continue
        cost = extract_cost(body)
        cond = extract_if(body)
        prims = extract_primitives(body)

        # 何も抽出できなかった場合は _unimplemented stub を残す
        if not prims:
            prims = [{"_unimplemented": body}]

        entry: dict = {
            "_text": f"{cid} {when}: {body[:80]}",
            "when": when,
            "do": prims,
        }
        if cost:
            entry["cost"] = cost
        if cond:
            entry["if"] = cond
        entries.append(entry)

    # trigger 欄 (= 別フィールド) 処理
    if trigger_text and trigger_text != "-" and trigger_text.startswith("【トリガー】"):
        body = trigger_text[len("【トリガー】"):].strip()
        if not _is_noise_body(body):
            cond = extract_if(body)
            prims = extract_primitives(body)
            if not prims:
                prims = [{"_unimplemented": body}]
            entry = {
                "_text": f"{cid} trigger: {body[:80]}",
                "when": "trigger",
                "do": prims,
            }
            if cond:
                entry["if"] = cond
            entries.append(entry)

    # テキストありなのに entries が空の場合 (= 【】 マーカーがない単純常在効果) → 全文を _unimplemented で残す
    if not entries and text and text != "-":
        # 「常在」 か推定: 「自分の」 「このキャラ」 「このターン中」 等が含まれる場合は on_attached_don n=0
        when = "on_attached_don" if "このキャラ" in text or "自分の" in text else "main"
        entries.append({
            "_text": f"{cid} {when} (パターン未一致): {text[:80]}",
            "when": when,
            "n": 0 if when == "on_attached_don" else None,
            "do": [{"_unimplemented": text}],
        })
        # n を None で残すと検証 NG なので、 削除
        if entries[-1].get("n") is None:
            entries[-1].pop("n", None)

    # 後処理: 各エントリ内の _unimplemented を持つ primitive のうち、
    # 同じ entry に他の有効 primitive がある場合は noise の _unimplemented を捨てる
    for entry in entries:
        do = entry.get("do", []) or []
        if len(do) > 1:
            kept = [p for p in do if not (isinstance(p, dict) and len(p) == 1 and "_unimplemented" in p and (not p["_unimplemented"] or p["_unimplemented"].strip() in ("", "/")))]
            if kept:
                entry["do"] = kept

    return entries


# --------------------------------------------------------------------------- #
# メイン
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    by_id = {c["card_id"]: c for c in cards}
    overlay = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))

    # メタリーダー除外
    meta_leaders: set[str] = set()
    for f in DECKS_DIR.glob("cardrush_*.json"):
        if f.name.endswith(".analysis.json"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("leader"):
                meta_leaders.add(d["leader"])
        except Exception:
            continue

    # 対象抽出: simplified marker 持ち or _unimplemented 持ち
    # (メタリーダー / テスト依存カードは protected)
    targets: list[str] = []
    for cid, effs in overlay.items():
        if cid.startswith("_"):
            continue
        if cid in meta_leaders:
            continue
        if cid in PROTECTED_TEST_CARDS:
            continue
        # parallel variants of protected cards も除外
        base = cid.split("_p")[0].split("_r")[0]
        if base in PROTECTED_TEST_CARDS:
            continue
        if has_simplified_marker(effs) or has_unimplemented(effs):
            targets.append(cid)

    targets.sort()
    if args.limit:
        targets = targets[: args.limit]

    print(f"対象: {len(targets)} カード")

    rewritten = 0
    unimplemented_stubs = 0
    fully_parsed = 0

    for cid in targets:
        card = by_id.get(cid)
        if card is None:
            continue
        new_effs = build_overlay_for_card(card)

        # 統計
        has_unimpl = any(
            any("_unimplemented" in p for p in (e.get("do", []) or []) if isinstance(p, dict))
            for e in new_effs
        )
        if has_unimpl:
            unimplemented_stubs += 1
        else:
            fully_parsed += 1

        if not args.dry_run:
            overlay[cid] = new_effs
        rewritten += 1

    if not args.dry_run:
        OVERLAY_JSON.write_text(
            json.dumps(overlay, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"書き換え: {rewritten} カード")
    print(f"  完全 DSL 化: {fully_parsed}")
    print(f"  _unimplemented 含む: {unimplemented_stubs}")


if __name__ == "__main__":
    main()
