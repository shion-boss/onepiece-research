# 効果オーバーレイ記述ガイド (Step 2 詳細)

新カードの効果を `db/card_effects.json` に **公式テキスト忠実主義** で書くための実務ガイド。 過去に全 4,518 枚で `_unimplemented = 0` / audit sev≥3 = 0 を達成した基準を、 新弾でも割らないために使う。

## 目次
1. 忠実度の鉄則
2. overlay の構造 (when / condition / do / cost)
3. DSL プリミティブの探し方・足し方
4. トリガー (when) と条件 (eval_condition) の一覧
5. 頻出バグ類型 (過去監査で繰り返し出たもの)
6. 1 枚の効果を検証する手順
7. 参照先

---

## 1. 忠実度の鉄則 (CLAUDE.md より、 厳守)

- 自動近似禁止: **「fallback」「自動抽出」「簡略」「省略」「近似」 を作らない**。
- 解釈不可な効果は `[]` (空) もしくは `{"_unimplemented": "..."}` / `_fidelity_note` で**公式テキストを残してマーク**。 空近似で誤魔化さない。
- 条件節 (ライフ X 以下、 リーダー特徴 Y、 ドン‼ N 枚以上 等) を**省略しない**。
- 既存の simplified entry を見つけたら公式テキストから**再構築**する。
- DSL に対応プリミティブが無ければ `engine/effects.py` に**新規追加**する (近似で済ませない)。
- 効果なし (バニラ / ブロッカーのみ / パラレル空) は**空配列でマーク**する (= 「未対応」 と区別)。

ゴール: 新弾追加後も `audit_overlay_vs_faq.py` sev≥3 = 0 / `verify_overlay_vs_cardqa.py` missing = 0 / `_unimplemented` は真に表現不能な分のみ。

## 2. overlay の構造

`db/card_effects.json` は `card_id → [effect, ...]` のマップ。 各 effect はおおむね:

```jsonc
{
  "when": "on_play",                 // トリガー (下記一覧)
  "condition": {"self_life_le": 2},  // 任意。 発動条件 (eval_condition のキー)
  "cost": [{"k": "discard_hand_with_filter", ...}],  // 任意。 支払いコスト (optional は別途)
  "do": [                            // 実際の効果 (DSL プリミティブの配列)
    {"k": "ko", "target": {"side": "opp", "kind": "character", "power_le": 4000}}
  ]
}
```

⚠ **既存カードを真似るのが最短で正確**。 同じトリガー/効果型の既存エントリを `card_effects.json` から grep して構造をコピーし、 数値・対象・条件だけ公式テキストに合わせる。 「元々パワー (base)」 と「パワー (current)」、 `cost` と `optional_cost_then`、 spec 形式と filter 形式で意味が逆転する箇所があるので §5 を必ず参照。

## 3. DSL プリミティブの探し方・足し方

- 実体は `engine/effects.py`。 ディスパッチは **`elif k == "..."`** の列挙 (現在 226 種)。 `grep -n 'k == "' engine/effects.py` で全プリミティブを一覧できる。
- 主要カテゴリ (CLAUDE.md の「DSL プリミティブ主要カテゴリ」 に一覧): draw/discard, KO/離脱, power, cost, don, rest, search/play, life, キーワード付与, 置換効果, KO耐性, 静的効果, コスト/遅延 ほか。
- **無ければ足す**:
  1. `engine/effects.py` の本体 (`_execute_effect_body`、 ⚠ `execute_effect` は wrapper) に `elif k == "新プリミティブ":` を追加。
  2. `tests/test_effects.py` に最小テストを追加 (発火 → 盤面変化を assert)。
  3. 既存の似たプリミティブの実装を参照して target 解決・副作用局所化 (`engine/game.py:apply_action`) の流儀に合わせる。
- 新トリガー (when) が要る場合は engine 側のトリガー発火経路も拡張する (= 「engine の更新」 の中身)。

## 4. トリガー (when) と条件 (eval_condition)

**when (主なもの)**: on_play / on_attack / activate_main / on_ko / end_of_turn / opp_end_of_turn / on_block / on_opp_attack / trigger / counter / main_event /
on_self_chara_leave_by_self_effect / on_self_rested / on_self_hand_discarded / on_self_chara_played / on_opp_chara_played / on_self_event_played /
on_opp_life_taken / on_self_life_to_hand / on_self_life_to_trash / on_self_don_returned_to_deck / on_opp_blocker_use / on_self_chara_ko / on_opp_chara_ko /
opp_attack_on_leader / opp_attack_on_chara (完全な一覧と意味は CLAUDE.md「主要トリガー」 + `engine/effects.py`)。

**condition (eval_condition の主なキー)**: leader_feature / leader_color / self_life_le|ge / opp_life_le|ge / self_hand_le|ge / opp_hand_le|ge / self_don_ge / opp_turn / self_turn / self_rested / self_trash_count_ge / victim_truly_original_power_ge / victim_feature_in / played_chara_truly_original_cost_ge / played_self_chara_has_no_effect / actor_source_feature_contains / self_chara_filtered_count_ge / don_diff_le ほか 30+ (`eval_condition` を grep)。

## 5. 頻出バグ類型 (過去監査で繰り返し出た — 新弾でも警戒)

- **二重コスト**: top-level `cost` と `optional_cost_then` の両方に discard を書くと 2 枚要求になる (公式 1 枚)。 `REAL_COST_KEYS` を経由するか片方に寄せる。
- **任意コストの人間ゲート**: `optional_cost_then` は人間プレイで pay/skip を選べる必要 (AI 不変)。
- **自己デバフ vs 相手デバフ**: 「このキャラ パワー-X」 や **コスト側の -X** を「相手を下げる」 と誤読しない (主語が『相手の』 の節だけ)。
- **元々パワー (base) vs パワー (current)**: **spec 形式と filter 形式で意味が逆転**する (spec power_le = 現在値 / filter power_le = base)。
- **category 小文字** "character" は silent no-op になりうる (engine は大小無視化済だが新規記述は正規表記で)。
- **ゾーン誤り**: 「手札から登場」 を `play_from_trash` にしない。 「手札かトラッシュから」 = `play_from_hand_or_trash`。
- **features 分割**: `core.py` で「/」 分割 → leader_feature exact が各要素にマッチ。 「X を含む特徴」 を exact で誤フラグしない。
- **欠落しやすい節**: 条件 (missing-cond)、 持続 (duration: turn / next_opp_turn_end)、 数量 (amount)。 leader カードに集中しがち。
- **リーダー要件 ≠ 対象**: 「リーダーが特徴《F》を持つ場合」 の《F》 は gate であって効果の対象ではない。

## 6. 1 枚の効果を検証する手順

1. 公式テキスト (cards.json の `text` / `trigger`) と cardqa を読む (`grep <card_id> db/faq/cardqa_*.json`)。
2. overlay を書く。
3. **実ディスパッチを introspect** して発火を確認 (wrapper でなく `_execute_effect_body` が処理する key か)。
4. 最小ステートで behavior test (発火前後の盤面差分)。 **run1 == run2 (再現性)** を確認してからコミット。
5. `smoke_test_card_effects.py` + `audit_overlay_vs_faq.py` + `verify_overlay_vs_cardqa.py` + `audit_engine_strictness.py` + `pytest` を通す。

## 7. 参照先

- ルール裁定: `onepiece-tcg-rules` スキル (`.claude/skills/onepiece-tcg-rules/SKILL.md`) + `db/rules/*.pdf`。
- カード個別 Q&A: `db/faq/cardqa_*.json` を grep。
- 既存実装の手本: `db/card_effects.json` の同型エントリ + `engine/effects.py` の同型プリミティブ。
- 監査の意味と除外: `db/audit_acknowledged.json` (intrinsic 除外) / `db/overlay_audit.{md,json}`。
