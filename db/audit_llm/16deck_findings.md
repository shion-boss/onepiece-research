# 16-deck pool inline LLM 監査 findings

各デッキの公式テキスト ↔ overlay を 1 枚ずつ Claude Code が読み、 構造検出器では拾えない
忠実性 bug を記録。 [[project_card_effect_100_plan_kickoff]] 順3。 fix は branch `audit/16deck-inline-llm`。

**重要な発見**: 構造検出器は「新規 systematic bug 無し」 と判定したが、 inline 読解では
**1 デッキあたり平均 ~6-8 件**の忠実性 bug が見つかる (= surface pass・true fail の典型)。
overlay は二重コスト掃討後も 個別カードの解釈精度に多数の誤りを抱えている。

## 進捗

| deck | leader | 監査 | 発見 | 修復 | 残 |
|---|---|---|---|---|---|
| cardrush_1392 イム | OP13-079 | ✅(prototype) | 二重コスト等 | 済 | 0 |
| cardrush_1342 ドフラ | OP14-060 | ✅ | 1 | 1 | 0 |
| cardrush_1385 クロコダイル | OP14-079 | ✅ | 7 | 4 | 3 |
| cardrush_1399 ルーシー | OP15-002 | ✅ | 8 | 5 | 3 |
| cardrush_1456 エース | OP13-002 | ✅ | 8 | 3 | 4 |
| cardrush_1439 ナミ | OP11-041 | ✅ | 6 | 6 | 0 |
| cardrush_1453 ミホーク | OP14-020 | ✅ | 12 | 6 | 6 |
| cardrush_1454 エネル | OP15-058 | ✅ | 6 | 5 | 1 |
| cardrush_1455 空島ルフィ | OP15-098 | ✅ | 7 | 4 | 3 |
| tcgportal_bonney | EB04-001 | ⬜ | | | |
| tcgportal_calgara | OP08-098 | ✅ | 5 | 3 | 2 |
| tcgportal_coby | OP11-001 | ✅ | 4 | 4 | 0 |
| tcgportal_corazon | OP12-061 | ✅ | 5 | 3 | 2 |
| tcgportal_hancock | OP14-041 | ✅ | 1 | 0 | 1 |
| tcgportal_op11_luffy | OP11-040 | ✅ | 6 | 3 | 3 |
| tcgportal_op13_luffy | OP13-001 | ✅ | 6 | 4 | 2 |

## 修復済 (commit 済)

**ドフラ**: OP14-069 過剰 top-level if 削除。
**クロコダイル**: OP14-079 (ko_all→cost_minus-10 SEVERE) / OP14-083 (二重trash hoist) /
  OP05-094 (main keep_opp_rested + trigger draw2) / OP05-082 (cost是正 + discard 2→1)。
**ルーシー**: OP15-006 (trash_event_count) / OP10-060 (return_to_deck_bottom) /
  OP15-052 (replace_leave + base_power) / OP05-019 (-4000 any化 + ko gate) /
  OP15-020 (順序是正 + discard2 gate)。

## 残 (= 新 primitive/condition or 複雑 mechanic、 別途実装)

- **クロコダイル current-cost 整合**: cost_le target が `c.card.cost` (raw) を使用、 base_cost
  (cost_minus 反映) と不整合。 クロコダイルの cost-0 操作 synergy が機能しない深い問題。
  影響: 「コスト0か8以上」 系全般 (OP14-090/094/120)。 要: cost-target の base_cost 化 audit。
- **OP14-094 / OP14-120 / OP14-090**: 「コスト0か8以上のキャラがいる場合」 condition 未実装 +
  OP14-120 self-resummon-from-trash primitive 未実装 + OP14-090 条件付き速攻:キャラ static。
- **OP15-002 ルーシー leader**: 「このターン cost3+イベント発動」 condition 未実装 (= draw が無条件化)。
  + アタック時の「任意枚discard→+1000×N」 可変pump が固定+1000に簡略。
- **OP15-056 メラメラ**: give_keyword ダブルアタック の duration:turn + leader「ルーシー」 condition。
- **OP15-057 ドレスローザ王国**: opp_attack の cost (rest stage + event/stage discard) 欠落。

## 追加 systematic 修復 (= inline 監査が起点で DB-wide 波及)

- **return_self 二重コスト 16 entry**: trash_self/rest_self + optional_cost_then の
  `return_self_to_trash`/`return_self_to_hand` 二重 (= 旧 double-cost fix の REAL set が
  これら spelling を漏らしていた)。 ST22-002 で発覚 → DB-wide で 16 件 hoist。 guard も更新。

## 中間総括 (6/16 deck = イム+ドフラ+クロコダイル+ルーシー+エース+ナミ)

- 発見 bug 約 30 件 + 二重コスト系統 32 件 (110+16)、 修復 entry 約 60。
- **overlay 真正度 体感 ~85-90%** (= 構造検出器 pass でも 1 deck 6-8 件の忠実性 bug)。
  主要 bug 類型: (a) 効果の action/対象/数値/destination 誤り (ko_all/return_to_hand 等)、
  (b) cost 欠落で効果無償化、 (c) 条件の過剰/欠落 gate、 (d) phantom 重複効果、 (e) 二重コスト。
- 主要 deck (= meta 上位) を優先的に潰す価値が高い。 cascade (A→AI) への寄与大。

## 方針
clear bug (= 既存 primitive で安全) は即修復+commit。 新 primitive/condition 要は本 doc に集約し、
共通 primitive をまとめて実装 → 該当カード一括修復。 残 10 deck (ミホーク/エネル/空島ルフィ +
tcgportal 6 + コビー) の監査を継続。
