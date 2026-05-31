# LLM overlay 監査 prototype 結果 (= 真100%担保 plan 順2)

**日付**: 2026-05-31
**対象**: イム deck (cardrush_1392) 全 15 カード (= leader + 14)
**手法**: `scripts/audit_llm_extract.py` で 各カードの 公式テキスト ↔ 現行 overlay を 1 ブロック化 →
Claude Code が inline で 1 枚ずつ 忠実性監査 (= sub-agent 不要、 subscription のみ)。

## 結論: 手法は有効。 全 4,518 枚 走行を **GO 推奨**。

15 枚 monitor で **1 件の systematic bug (= DB 全体 110 entry に波及)** + 1 件の fidelity gap を発見。
過去の 4 種 audit (overlay_vs_faq / cardqa / engine_strict / DSL_JP) は すべて pass していた
カード群 = surface integrity では catch できない bug を LLM 監査が捕捉した。 [[project_card_implementation_audit]]
の「真 100% ではなかった」 仮説を 定量的に裏付け。

## 15 カード 監査結果

| カード | 判定 | 内容 |
|---|---|---|
| OP13-079 イム (leader) | **既知gap** | 起動メイン cost が 公式「天竜人キャラ か 手札 trash」 の選択 → discard のみ実装。 `_fidelity_note` 付与済 |
| OP13-091 マーズ | ✓ + 検証 | KO target「元々のコスト5以下」 = engine `c.card.cost` (printed=元々) で正しい |
| OP13-080 イーザンバロン | ✓ | 忠実 |
| OP13-083 サターン聖 | ✓ | 忠実 (search_top_n bottom 順は人間指定) |
| OP13-084 シェパード | ✓ | 昨夜修復済 (第2効果)。 `conditions` 使用も static path で honor 確認 |
| OP13-089 ウォーキュリー | ✓ | 忠実 |
| OP13-082 五老星 | ✓ | 忠実 (trash_all + play_from_trash 5×五老星power5000) |
| OP13-086 シャルリア宮 | ✓ + 検証 | discard は `trash_self_hand_random` だが human modal (self_hand_discard_pick) に routing 済、 名称のみ誤解招く |
| OP13-092 ミョスガルド | ✓ | 忠実 |
| PRB02-014 サボ | ✓ + 検証 | 無条件【ブロッカー】は engine が text から intrinsic 検出 (has_innate_keyword)、 overlay 省略は正しい |
| OP13-096 五老星ここに | ✓ | main 効果 忠実 (昨夜 誤trigger 削除済) |
| OP13-098 元々ないか | ✓ | 忠実 |
| **OP14-096 浸食輪廻** | **★bug→修復** | **二重コスト: 公式2DON→4DON rest。 systematic bug の発見起点** |
| OP05-097 聖地マリージョア | ✓ | 忠実 (静的cost-1)、 _text "パターン未一致" は stale annotation のみ |
| OP13-099 虚の玉座 | ✓ | 忠実 |

## 発見した systematic bug: optional_cost_then 二重コスト

**症状**: entry が top-level `cost` と do 内 `optional_cost_then` で 同一コストを 2 箇所請求 →
実コスト倍化。 runtime 実証: OP14-096 (main) 4DON / OP13-026 (activate_main) 2DON / OP06-118_r2 4DON。

**波及**: DB 全体 **110 entry** (= 全 when path: main/on_play/counter/activate_main/on_attack)。
DON 経済は AI の行動評価の根幹 → [[project_card_effect_100_plan_kickoff]] の cascade (A→C→D→AI) で
学習 noise として 蓄積していた可能性大。

**修復済** (commit 済): phase1 85 + phase2 25。 regression guard
(`tests/test_no_double_optional_cost.py`) で 二重コスト 0 を invariant 化。 関連 effect 是正も同時:
OP08-077 (bounce→KO2), OP07-059 (rest重複→単一), ST26-002 (cost制約追加)。 OP11-070 は
effect 未実装 (peek_opp_deck_top) を `_missing_effect` で注記。

## LLM 監査が catch した「surface pass・true fail」 の類型

1. **重複コスト** (optional_cost_then × top cost) — primitive 単位では valid、 組合せで bug
2. **誤 primitive** (OP08-077 bounce vs KO / OP12-061 rest vs return) — DSL 上は実行可能だが 公式と乖離
3. **target 超過** (OP07-059 2枚 rest vs 公式1枚) — 効果は動くが 範囲が誤り
4. **未実装の隠蔽** (OP11-070 空 effect) — entry は存在するが effect 配列が空

これらは いずれも 既存 4 audit の検査軸 (= marker有無 / FAQ突合 / strict検査 / JP表記) では検出不能。

## 全 4,518 枚 走行への推奨

- **GO**。 15 枚で 110-entry 級の systematic bug を 1 件発見した検出力は 投資に見合う。
- 手法: `audit_llm_extract.py --all --chunk 50` で 91 chunk 生成 → chunk 単位で inline 監査。
  - sub-agent (Agent tool) 並列は API 不要だが cold start コスト大。 deck 単位 (16 deck pool) を
    優先走行し、 メタ被覆カードから 潰すのが費用対効果 高。
- 期待: 真 ~95% → ~98% へ (systematic bug 類型を 全 DB で 掃討)。 真 100% は理論上不可を維持認識。

## 残タスク (本 prototype 由来)

1. OP13-079 leader: char-or-hand 複合 choice cost primitive + 人間 modal (`_fidelity_note` 参照)
2. OP11-070: peek_opp_deck_top primitive 実装 (`_missing_effect` 参照)
3. 全 4,518 枚 (or 16 deck pool 優先) で 本手法を 横展開
