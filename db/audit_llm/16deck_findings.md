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
| tcgportal_bonney | EB04-001 | ✅ | 2 | 2 | 0 |
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

## ★ 完了総括 (16/16 deck、 2026-05-31、 main 49c9cb7、 full suite green)

- **全 16 deck inline 監査 完了**。 修復 entry 約 **130**、 発見 bug 約 **80 種**。
- **deck 別 bug 密度の差大**: クロコダイル/ミホーク/ルーシー/エース = 7-12 件 (重症)、
  ハンコック/ボニー = 0-2 件 (健全)。 overlay の質はカード/弾でばらつく。
- **主要 bug 類型 (確定)**: (1) action/対象/destination 誤実装 (ko_all/return_to_hand/trash↔deck/bounce↔KO)
  (2) cost 欠落で無償化 (3) 条件gate 過剰/欠落 (4) phantom 重複効果 (二重発火)
  (5) 「登場させる」 等の節 まるごと欠落 (leader/大型カード多発)
  (6) dead trigger (on_self_life_lost / _chain・_condition 等 engine 未対応 key で 一度も発火せず)
  (7) 二重コスト (return_self spelling 16件 DB-wide 含む)
- **真正度の実測 = overlay 真 ~85-90%**。 構造検出器 pass でも 1 deck 平均 5-6 件の忠実性 bug。
  「公式100%整合」 (CLAUDE.md) は surface integrity の意味。

## 残タスク (= 新 primitive/condition 要、 別session で集約実装)

- all_opp_power_le_0 KO target / reveal-life-pump (OP15-119) / クロコダイル cost-0 architecture
  (base_cost vs card.cost) / cost0・8+ condition (OP14-090/094/120) / OP08-098 動的cost登場 /
  OP15-002 cost3+event条件 / OP06-063 / OP13-007 / OP15-102 等。 各 deck commit + 本 doc に記録。

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

## ★ 横展開 (全4,518枚 DB-wide、 2026-05-31、 main b37567f)

inline 監査で確定した bug 類型のうち programmatic 検出可能なものを engine-validity 検出器で
全DB走査・一掃 (= 全カードを読まずに systematic instance を捕捉):

- **dead-when 13 entry**: `on_turn_end`→`end_of_turn` (5)、 `leader_passive`→`on_attached_don` n=0 (8)。
  engine が dispatch しない when で 一度も発火していなかった。
- **未handled condition key 21 entry (spelling)**: silently-ignored で gate が効いていなかった。
  `self_hand_le`→`self_hand_count_le` / `opp_hand_ge`→`opp_hand_count_ge` /
  `opp_don_ge`→`opp_don_count_ge` / `leader_attribute`→`self_leader_attribute` /
  `target_base_power_le/ge`→`target_power_le/ge` (= 本監査で自分が入れた regression も是正。
  replace matcher は target_power_le で既に truly_original_power=元々パワー を見る)。
- **_chain/_condition 3 entry**: engine 無効キーの自作 conditional → `replace_ko_complex` に是正。 DB全体 0。
- **eval_condition に condition 10種 実装**: self_hand_eq / self_not_rested / self_rested_chara_count_ge /
  self_don_rested_ge / self_leader_power_le / self_leader_attached_don_ge / self_life_plus_hand_le /
  total_life_le / self_all_chara_feature / either_player_don_total_eq_10。 ~20 カードの gate が実効化。

→ 全DB full suite green。 構造検出可能な type 6/7 を全枚で掃討。

## 横展開 残 (= context-heavy condition、 KO-sequence/iid plumbing 要)

- **victim_iid_eq_self (15 card)**: on_self_chara_ko の「KOされたのがこのキャラ自身か」 scope。
  trigger_on_self_chara_ko の victim 場残存タイミング確認 + victim iid 保存 が必要。 over-fire/不発 いずれか。
- returned_don_count_ge (4) / target_truly_original_power_eq (2) / opp_attacker_attribute (1):
  各 trigger の payload context 保存が必要。
- + 16deck findings の deck固有 primitive (all_opp_power_le_0 / reveal-life-pump / cost0・8+ 等)。
