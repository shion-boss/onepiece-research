# -*- coding: utf-8 -*-
"""
LLM (Claude Opus) で overlay を公式テキストから再生成する。

目的:
    `db/card_effects.json` 内に大量に残る 「自動 fallback」 「簡略化」 effect を
    公式テキストの正確な解釈に置換する。

戦略:
    1. 対象判定: 各 effect の `_text` に simplified marker (fallback/簡略/auto/省略/近似)
       が含まれるか、 `_meta.regen_skip` で除外指定されていないカード
    2. プロンプト: DSL 仕様 + 公式テキストを与え、 JSON で effect 配列を出力させる
    3. claude -p --output-format json --json-schema で構造化出力
    4. JSON 検証 → overlay に上書き保存
    5. 進捗を `db/regen_progress.json` に逐次記録、 中断後再開可

呼出:
    .venv/bin/python scripts/regenerate_overlay_with_llm.py --limit 5     # テスト 5 件
    .venv/bin/python scripts/regenerate_overlay_with_llm.py --batch 50    # 50 件で 1 セッション
    .venv/bin/python scripts/regenerate_overlay_with_llm.py --resume      # 中断箇所から再開
    .venv/bin/python scripts/regenerate_overlay_with_llm.py --card-id OP14-080  # 特定 1 枚

注意:
    - claude CLI を呼ぶため、 ユーザーが Claude Code を購読している必要あり
    - 1 カードあたり 30〜90 秒程度を想定。 2,500 枚なら数時間〜数日
    - 各カードでネットワーク要求するため、 中断/再開の設計を重視
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
PROGRESS_JSON = ROOT / "db" / "regen_progress.json"
ARCHIVE_JSON = ROOT / "db" / "card_effects.archive_simplified.json"

SIMPLIFIED_MARKERS = ("fallback", "簡略", "auto", "省略", "近似", "自動抽出")


# ----------------------------------------------------------------------------- #
# DSL 仕様 (LLM プロンプトの SYSTEM 部に渡す参照)
# ----------------------------------------------------------------------------- #
DSL_SPEC = """\
You are an expert at converting ONE PIECE TCG card text into the project's effect overlay DSL.

Output strict JSON of the shape: {"effects": [<effect_obj>, ...]}.

Each effect_obj:
  - _text (string): one-line summary of what this entry represents (Japanese ok)
  - when (string, required): one of:
      "on_play"               登場時
      "on_attack"             アタック時
      "on_block"              ブロック時
      "opp_attack"            相手のアタック時
      "on_ko"                 KO時
      "activate_main"         起動メイン
      "end_of_turn"           自分のターン終了時
      "opp_end_of_turn"       相手のターン終了時
      "on_turn_start"         自分のターン開始時
      "opp_turn_start"        相手のターン開始時
      "trigger"               【トリガー】 ライフ起動効果
      "main"                  メインフェイズ用イベントカード本体効果
      "on_attached_don"       【ドン!!×N】 常在条件
      "replace_ko"            「KOされる代わりに〜」 置換効果
  - n (int, optional): on_attached_don のみ。 ドン枚数閾値 (例: ドン!!×2 → n=2)
  - cost (object, optional): activate_main / on_attack で使う。 fields:
      once_per_turn (bool)
      pay_don (int)        コストエリアのドンを N 枚レストにする
      discard_hand (int)   手札 N 枚捨て
      ko_self_with_filter  {feature: "..."} 形の自場 1 枚 KO コスト
      rest_self (bool)     自身レスト
  - if (object, optional): 条件節
      leader_feature (string|list)
      leader_color (string)
      always (bool)
      self_life_le / self_life_ge / opp_life_le / opp_life_ge (int)
      self_field_count_ge / self_field_count_le (int)
      self_trash_count_ge (int)
      self_don_ge / self_don_active_ge (int)
      self_chara_feature_count_ge ({feature, count})
      self_turn / opp_turn (bool)
  - do (list, required): primitives. Each is an object with one key:
      {"draw": N}                                  N 枚引く
      {"trash_self_hand_random": N}                 自手札ランダム N 枚捨て
      {"trash_opp_hand_random": N}                  相手手札ランダム N 枚捨て
      {"ko": "<target>"}                           対象を KO
      {"return_to_hand": "<target>"}               対象を持ち主の手札に
      {"rest": "<target>"}                         対象をレスト
      {"untap": "<target>"}                        対象をアクティブ化
      {"power_pump": {"target","amount","duration"}} パワー +N
        target: "self" / "self_leader" / "self_inplay" / "all_self_characters" /
                "any_opponent_character_le_5000" / "one_opponent_character_le_5000" 等
        amount: int
        duration: "turn" / "battle" / "static"
      {"attach_don": {"target","count"}}           ドン N 付与
      {"add_don": N}                               ドンデッキからアクティブで N 追加
      {"untap_don": N}                              レストドン N をアクティブ化
      {"give_keyword": {"target","keyword"}}       キーワード付与 (ブロッカー/速攻/ダブルアタック/バニッシュ/ブロック不可)
      {"give_rush": "<target>"}                    速攻付与 (= give_keyword の特化)
      {"search": {"filter":{...},"limit":N}}        デッキサーチ
      {"summon_from_deck": {"filter":{...},"limit":N,"rested":bool}}
      {"play_from_trash": {"filter":{...},"limit":N}}
      {"play_from_hand": {"filter":{...},"limit":N}}
      {"play_event_from_hand": {"filter":{...}}}
      {"life_to_hand": N}                           ライフ N をトラッシュではなく手札へ
      {"put_top_to_life": N}                        デッキ上 N をライフへ
      {"mill": N}                                    デッキ上 N をトラッシュへ
      {"set_cannot_attack": "<target>"}            ターン中アタック不可
      {"stay_rested_next_refresh": "<target>"}     次リフレッシュで非アクティブ化
      {"prevent_ko": "<target>"}                   ターン中 KO 耐性
      {"set_ko_immune": "<target>"}                 静的 KO 耐性 (on_attached_don 内のみ)
      {"reduce_play_cost": N}                      自次プレイのコスト軽減
      {"cost_minus": {"target","amount"}}          相手のコスト -N (ターン中)
      {"set_base_power": {"target","amount"}}      元々のパワー上書き (on_attached_don)
      {"set_base_cost": {"target","amount"|"delta":N}}
      {"set_attack_taunt": "<target>"}             相手はこのキャラ以外攻撃不可
      {"replace_ko": {...}}                          KO 代替の置換効果
      {"redirect_attack": "<target>"}              アタック対象変更 (opp_attack 内)
      {"block_chara_play": true}                   このターン中キャラ登場禁止 (自分側)

ターゲットセレクタ (target_spec) の代表値:
  "self"                         このカード自身 (発動者)
  "self_leader"                  自リーダー
  "self_inplay"                  発動者と同じ in-play (= self とほぼ同義)
  "all_self_characters"          自場のキャラ全員
  "all_self_team"                自リーダー + 自場キャラ全員
  "one_opponent_character_le_5000" 相手キャラ 1 枚 (パワー高い順に 1 体、 制限なし)
  "one_opponent_character_le_2000" / le_3000 / le_4000 / le_5000 / le_6000 等
    パワー上限付きの単体対象 (= 「コスト N 以下のキャラ 1 枚」 もこれで近似可)
  "any_opponent_character_le_5000" 相手キャラ 全体 (= 「コスト N 以下のキャラ全員」)

Rules for output:
1. NEVER simplify or drop conditions. If the official text says "ライフ3以下なら 〜", include `if: {self_life_le: 3}`.
2. If the text has multiple trigger blocks (e.g. 【登場時】 と 【KO時】), output multiple effect objects.
3. Use the exact Japanese names (「麦わらの一味」 etc.) for features/leaders.
4. If a primitive doesn't exist for an effect, output `{"_unimplemented": "<text>"}` as the
   primitive in `do` (= leave for human to extend the DSL). Do NOT invent primitive names.
5. Keep `_text` short (≤ 100 chars). Summarize in Japanese.
6. If the card has 0 effects (vanilla), output {"effects": []}.
7. 【ブロッカー】【ダブルアタック】 等のキーワードは CardDef に静的に持つので overlay には書かない。
   ただし 「【ドン!!×N】 ブロッカー」 のような条件付きはoverlayに書く。

Example output for 「【登場時】 カード1枚を引く。【KO時】 自分のライフ1枚を手札に加える」:
{"effects": [
  {"_text": "登場時 1ドロー", "when": "on_play", "do": [{"draw": 1}]},
  {"_text": "KO時 ライフ1枚を手札に", "when": "on_ko", "do": [{"life_to_hand": 1}]}
]}
"""


JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "effects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "_text": {"type": "string"},
                    "when": {"type": "string"},
                    "n": {"type": "integer"},
                    "cost": {"type": "object"},
                    "if": {"type": "object"},
                    "do": {"type": "array"},
                },
                "required": ["when", "do"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["effects"],
    "additionalProperties": True,
}


# ----------------------------------------------------------------------------- #
# 対象カード判定
# ----------------------------------------------------------------------------- #
def is_simplified_effect(eff: dict) -> bool:
    """1 つの effect が simplified marker を持つか?"""
    text = eff.get("_text", "") or ""
    return any(m in text for m in SIMPLIFIED_MARKERS)


def needs_regen(card: dict, current_effects: list[dict]) -> bool:
    """このカードを再生成すべきか? 公式テキストあり、 かつ既存 effect が 0 件 or simplified を含む場合。"""
    text = (card.get("text") or "").strip()
    if not text or text == "-":
        return False
    if not current_effects:
        # 効果なしの実装抜けがある可能性 (テキストはあるが overlay 0 件)
        return True
    return any(is_simplified_effect(e) for e in current_effects)


# ----------------------------------------------------------------------------- #
# Claude CLI 呼出
# ----------------------------------------------------------------------------- #
def call_claude(card_id: str, name: str, category: str, text: str) -> dict | None:
    """claude -p で 1 カードの DSL を生成。 失敗時 None。"""
    prompt = (
        f"Card ID: {card_id}\n"
        f"Name: {name}\n"
        f"Category: {category}\n"
        f"Official Text:\n{text}\n\n"
        f"Output the effect overlay JSON now."
    )
    schema_str = json.dumps(JSON_SCHEMA, ensure_ascii=False)
    # --system-prompt で minimal な system prompt に置換し、 余計な context を排除する。
    # (--bare は OAuth を切るので使わない。 --tools "" は -- separator が必要)
    try:
        result = subprocess.run(
            [
                "claude",
                "--output-format", "json",
                "--json-schema", schema_str,
                "--system-prompt", DSL_SPEC,
                "--model", "opus",
                "--no-session-persistence",
                "--disable-slash-commands",
                "-p", prompt,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(f"  [{card_id}] タイムアウト", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"  [{card_id}] CLI エラー rc={result.returncode}: {result.stderr[:200]}", file=sys.stderr)
        return None
    # claude -p の json 出力は { "type":"result", "result": "<text>", ... }
    # --json-schema 指定時は result に検証済 JSON 文字列が入る
    try:
        wrapper = json.loads(result.stdout)
        result_text = wrapper.get("result", "")
        if isinstance(result_text, dict):
            return result_text
        return json.loads(result_text)
    except (json.JSONDecodeError, AttributeError) as e:
        # 末尾の説明文が混じることがあるため抽出
        m = re.search(r'\{[\s\S]*"effects"[\s\S]*\}', result.stdout)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        print(f"  [{card_id}] JSON parse 失敗: {e}", file=sys.stderr)
        return None


def validate_effects(effects: list[dict]) -> tuple[bool, str]:
    """生成された effects 配列の形式チェック。 不正なら (False, 理由)。"""
    valid_when = {
        "on_play", "on_attack", "on_block", "opp_attack", "on_ko",
        "activate_main", "end_of_turn", "opp_end_of_turn",
        "on_turn_start", "opp_turn_start", "trigger", "main",
        "on_attached_don", "replace_ko",
    }
    for i, e in enumerate(effects):
        if not isinstance(e, dict):
            return False, f"entry {i}: not a dict"
        if "when" not in e or "do" not in e:
            return False, f"entry {i}: missing when/do"
        if e["when"] not in valid_when:
            return False, f"entry {i}: invalid when={e['when']}"
        if not isinstance(e["do"], list):
            return False, f"entry {i}: do is not a list"
    return True, ""


# ----------------------------------------------------------------------------- #
# メイン処理
# ----------------------------------------------------------------------------- #
def load_progress() -> dict:
    if PROGRESS_JSON.exists():
        return json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
    return {"completed": [], "failed": [], "started_at": None}


def save_progress(progress: dict) -> None:
    PROGRESS_JSON.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def archive_simplified(overlay: dict, card_id: str) -> None:
    """元の effect を archive に保存して上書きを安全に。"""
    archive = {}
    if ARCHIVE_JSON.exists():
        archive = json.loads(ARCHIVE_JSON.read_text(encoding="utf-8"))
    archive[card_id] = overlay.get(card_id, [])
    ARCHIVE_JSON.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="N カードで打ち切り (テスト用)")
    ap.add_argument("--batch", type=int, default=None,
                    help="このセッションで処理する件数")
    ap.add_argument("--resume", action="store_true",
                    help="進捗を読み込んで未処理のみ実行")
    ap.add_argument("--card-id", type=str, default=None,
                    help="特定 1 枚のみ再生成 (デバッグ用)")
    ap.add_argument("--dry-run", action="store_true",
                    help="LLM を呼ぶが overlay 書き込みはしない")
    args = ap.parse_args()

    cards = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))
    by_id = {c["card_id"]: c for c in cards}

    progress = load_progress() if args.resume else {"completed": [], "failed": []}
    completed_set = set(progress.get("completed", []))
    failed_set = set(progress.get("failed", []))

    # 対象抽出
    if args.card_id:
        targets = [args.card_id]
    else:
        targets = []
        for cid, card in by_id.items():
            current = overlay.get(cid, [])
            if not isinstance(current, list):
                continue
            if needs_regen(card, current):
                if args.resume and cid in completed_set:
                    continue
                targets.append(cid)
        targets.sort()

    if args.limit:
        targets = targets[: args.limit]
    if args.batch:
        targets = targets[: args.batch]

    print(f"再生成対象: {len(targets)} カード")
    if not targets:
        return

    if not progress.get("started_at"):
        progress["started_at"] = datetime.now(timezone.utc).isoformat()

    for i, cid in enumerate(targets):
        card = by_id.get(cid)
        if card is None:
            continue
        text = (card.get("text") or "").strip()
        print(f"[{i+1}/{len(targets)}] {cid} {card['name']} ({card['category']}) ...")
        t0 = time.time()
        result = call_claude(cid, card["name"], card["category"], text)
        elapsed = time.time() - t0
        if result is None:
            print(f"   失敗 ({elapsed:.1f}s)")
            failed_set.add(cid)
            progress["failed"] = sorted(failed_set)
            save_progress(progress)
            continue

        effects = result.get("effects", [])
        ok, reason = validate_effects(effects)
        if not ok:
            print(f"   検証失敗: {reason}")
            failed_set.add(cid)
            progress["failed"] = sorted(failed_set)
            save_progress(progress)
            continue

        if not args.dry_run:
            archive_simplified(overlay, cid)
            overlay[cid] = effects
            OVERLAY_JSON.write_text(
                json.dumps(overlay, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        completed_set.add(cid)
        progress["completed"] = sorted(completed_set)
        save_progress(progress)
        print(f"   ✓ {len(effects)} effect ({elapsed:.1f}s)")

    print(f"\n=== サマリ ===")
    print(f"  完了: {len(completed_set)}")
    print(f"  失敗: {len(failed_set)}")


if __name__ == "__main__":
    main()
