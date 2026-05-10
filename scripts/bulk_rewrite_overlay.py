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


# 効果セクション抽出: 【XXX】 で区切る
def split_by_trigger(text: str) -> list[tuple[str, str]]:
    """テキストを 【トリガー】 単位に分割し、 [(when, body), ...] を返す。
    when にマップできない trigger 名はスキップ。 同じ trigger 名が複数出るとリストに追加。"""
    out: list[tuple[str, str]] = []
    matches = list(re.finditer(r"【(.+?)】", text))
    if not matches:
        return out
    for i, m in enumerate(matches):
        kw = m.group(1)
        when = TRIGGER_MAP.get(kw)
        if when is None:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        out.append((when, body))
    return out


# --- コスト抽出 ---
COST_TURN_ONCE = re.compile(r"【ターン1回】")
COST_PAY_DON = re.compile(r"ドン[‼!]{1,2}\s*[-－ー]\s*([0-9０-９]+)")
COST_DISCARD = re.compile(r"自分の手札\s*([0-9０-９]+)\s*枚を捨てる")
COST_REST_SELF = re.compile(r"このキャラをレストにする")
COST_TRASH_SELF = re.compile(r"このキャラをトラッシュに置く")
COST_KO_SELF_FEATURE = re.compile(r"自分の特徴《([^》]+)》を持つキャラ\s*1\s*枚をKOする")


def extract_cost(body: str) -> dict:
    cost: dict = {}
    if COST_TURN_ONCE.search(body):
        cost["once_per_turn"] = True
    m = COST_PAY_DON.search(body)
    if m:
        cost["pay_don"] = to_int(m.group(1))
    m = COST_DISCARD.search(body)
    if m:
        cost["discard_hand"] = to_int(m.group(1))
    if COST_REST_SELF.search(body):
        cost["rest_self"] = True
    if COST_TRASH_SELF.search(body):
        cost["trash_self"] = True
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
IF_DON_GE = re.compile(r"自分の(?:場の)?ドン[‼!]{1,2}が\s*([0-9０-９]+)\s*枚以上(?:ある場合)?")
IF_DON_LE = re.compile(r"自分の(?:場の)?ドン[‼!]{1,2}が\s*([0-9０-９]+)\s*枚以下(?:の場合)?")
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
    if m := IF_SELF_LIFE_LE.search(body):
        cond["self_life_le"] = to_int(m.group(1))
    if m := IF_SELF_LIFE_GE.search(body):
        cond["self_life_ge"] = to_int(m.group(1))
    if m := IF_OPP_LIFE_LE.search(body):
        cond["opp_life_le"] = to_int(m.group(1))
    if m := IF_OPP_LIFE_GE.search(body):
        cond["opp_life_ge"] = to_int(m.group(1))
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
ADD_DON_RE = re.compile(r"ドン[‼!]{1,2}\s*デッキからドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブ")
ADD_RESTED_DON_RE = re.compile(r"ドン[‼!]{1,2}\s*デッキからドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*レスト")
UNTAP_DON_RE = re.compile(r"自分のドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブにする")

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
KO_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KOする")
KO_OPP_POWER_RE = re.compile(r"相手のパワー\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KOする")
KO_OPP_RESTED_RE = re.compile(r"相手のレストのキャラ\s*1\s*枚(?:まで)?を、?\s*KOする")
RETURN_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻す")
RETURN_OPP_DECK_BOTTOM_RE = re.compile(r"(?:相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下の)?キャラ\s*1\s*枚(?:まで)?を、?\s*持ち主のデッキの下に置く")
REST_OPP_COST_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*レストにする")
REST_OPP_RESTED_COST_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?は、?\s*次の相手のリフレッシュフェイズでアクティブにならない")
STAY_RESTED_OPP_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ.*?次の相手のリフレッシュフェイズでアクティブにならない")
STAY_RESTED_OPP_ANY_RE = re.compile(r"相手のレストのキャラ\s*1\s*枚(?:まで)?は、?\s*次の相手のリフレッシュフェイズでアクティブにならない")
CANNOT_ATTACK_OPP_RE = re.compile(r"相手の(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?は、?.*?アタックできない")
CANNOT_ATTACK_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?は、?.*?アタックできない")
KO_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*KOする")
RETURN_OPP_ANY_RE = re.compile(r"相手のキャラ\s*1\s*枚(?:まで)?を、?\s*持ち主の手札に戻す")
REST_OPP_ANY_RE = re.compile(r"相手の(?:アクティブの)?キャラ\s*1\s*枚(?:まで)?を、?\s*レストにする")

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
ATTACH_DON_LEADER_RE = re.compile(r"自分のリーダー(?:にレストの|に)?\s*ドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで|ずつまで)?を、?\s*(?:レストで)?\s*付与する")
ATTACH_DON_INPLAY_RE = re.compile(r"自分のリーダーかキャラ\s*1\s*枚に(?:レストの|アクティブの)?\s*ドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*付与する")
ATTACH_DON_CHARA_RE = re.compile(r"自分のキャラ\s*1\s*枚に(?:レストの|アクティブの)?\s*ドン[‼!]{1,2}\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*付与する")
# 自分のリーダー/キャラを場のドン!! N 枚で 「アクティブにする」 系統
UNTAP_DON_LEADER_RE = re.compile(r"自分のリーダーを、?\s*アクティブにする")
# 「相手のリーダーかキャラ」 を pump
POWER_PUMP_OPP_LEADER_OR_CHARA_NEG_RE = re.compile(r"相手のリーダーかキャラ\s*1\s*枚(?:まで)?を、?\s*このターン中、\s*パワー\s*\-\s*([0-9０-９]+)")
# 相手のレストのキャラ KO
KO_OPP_RESTED_COST_RE = re.compile(r"相手のレストの(?:元々の)?コスト\s*([0-9０-９]+)\s*以下のキャラ\s*1\s*枚(?:まで)?を、?\s*KOする")
# ライフを表向きにする
REVEAL_SELF_LIFE_RE = re.compile(r"自分のライフの上から\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*表向きにする")
# 自分の元々のコスト/パワー X 以下の自キャラを untap
UNTAP_SELF_FILTERED_RE = re.compile(r"自分(?:の(?:特徴《[^》]+》を持つ|元々のコスト\s*([0-9０-９]+)\s*以下の|パワー\s*([0-9０-９]+)\s*以下の))?キャラ\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*アクティブにする")
# 「自分のキャラ N 枚をレストにできる：」 (= rest_self_cards N コスト)
COST_REST_SELF_CHARAS_RE = re.compile(r"自分のキャラ\s*([0-9０-９]+)\s*枚を(?:レストにできる|レストにする)")
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
RETURN_SELF_TO_HAND_RE = re.compile(r"このキャラを持ち主の手札に戻す")
# 自分のトラッシュからカード N 枚 (filter) を手札に
TRASH_TO_HAND_RE = re.compile(r"自分のトラッシュから(?:特徴《([^》]+)》を持つ)?カード\s*([0-9０-９]+)\s*枚(?:まで)?を、?\s*手札に加える")


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
        m_multi = re.search(r"相手の(?:キャラ|リーダーかキャラ)\s*[2-9]\s*枚まで.*?KOする", body)
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


def build_overlay_for_card(card: dict) -> list[dict]:
    """1 カードの overlay を構築。 解析できない部分は _unimplemented stub で残す。"""
    text = (card.get("text") or "").strip()
    trigger_text = (card.get("trigger") or "").strip()
    cid = card.get("card_id", "")

    entries: list[dict] = []

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
            prims = extract_primitives(body)
            if not prims:
                prims = [{"_unimplemented": body}]
            entries.append({
                "_text": f"{cid} trigger: {body[:80]}",
                "when": "trigger",
                "do": prims,
            })

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
