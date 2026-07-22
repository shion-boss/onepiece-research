# pros02 の知見を対戦用 AI に活用する設計

> 2026-07-22。 ohtsuki 指示「どうしたら pros02 の知見を対戦用 AI に活用できるか検討し、自律的に試行錯誤せよ」。
> 本書は方針（何が効き何が効かないか）と実装パイプラインを定義する。実験ログは末尾に追記。

## 前提: この会話で確定した「効く形 / 効かない形」

pros02 = プロの知見（デッキ解説 237 + 進行記事 68 + 週間環境等、計 383 記事、`db/note_pros02/`）。
これを AI に流す方法は、これまでの検証で明確に分かれた:

- **❌ 効かない: 静的に value へ足す / blanket 蒸留**
  - v14（自盤面の駒種ラベルを value feature 化）= 冗長で null（EBV2 bench で v2 と区別不能）。
  - blanket 蒸留（顔攻撃 bonus 等を一律加点）= compose 崩壊で −6pt（[[project_rollout_teacher_loop]]）。
  - 静的ヒント全般 = 手を変えない（Δ0 実証、[[project_note_pros02_ingestion]]）。
  - 理由: 探索が既に効果を実行して結果を見ている & 配備 value は「平均的な相手」を学習済 → 知見が冗長。

- **✅ 効く形1: カードID キーの「補正ルール」を判断フックに注入**（本命・即実装可）
  - 効果が **盤面ヒューリスティックの意味を反転させる所だけ** を、value でなく決定フックで補正。
  - 例（実装済）: 黄エネル OP05-098 は 0→1 回復 → `opp_life=0` は near-win でない → `lethal_estimate`
    に回復分の壁を加算（vsエネル 0.231→0.168）。検証は mirror 勝率でなく **正確性/挙動**。
  - 冗長でなく **誤りを正す** ので効く。v6（board×matchup interaction）と同型。

- **✅ 効く形2: Claude 教師の採点カリキュラム**（フロンティア・[[project_rollout_teacher_loop]]）
  - 曖昧な位置取り判断（大半のプロ知見）はコード規則にできない → Claude が「プロならこう指す」で
    配備手を採点 → 誤りパターンを検出 → regress-proof residual で配備。pros02 = 採点の教師データ。

## パイプライン（mine → 分類 → 配線 or 教師）

```
pros02 記事 ──mine──> 知見候補 ──分類──┬─ hard rule（カードID・検証可能）──> card_knowledge + 判断フック ──正確性で検証──> 配備
                                      └─ fuzzy 判断（位置取り・大半）─────> Claude 教師の採点規則（rollout loop）
```

**分類基準（hard rule か）**: (a) 特定カード/リーダーに紐づく、(b) 素朴な heuristic の誤りを正す、
(c) 客観的に検証できる（局面で挙動が変わる/lethal 見積が変わる）。3 つ揃えば hard、そうでなければ教師。

## 知見の型 → 配線するフック（hard rule 用）

| fact_type | 素朴 heuristic の誤り | 配線フック（engine） | 検証 |
|---|---|---|---|
| recovery / effective_life | opp_life=0 = near-win | `eval.lethal_estimate`（回復分を壁に加算）※実装済 | vsそのLで lethal 見積が下がる |
| board_wipe / over_extend | 大きい盤面 = 良い | 展開の value 割引（opp が全体除去持ち×自 field 過多 の interaction）or play 抑制 | 過剰展開局面で盤面拡張の相対価値が下がる |
| ko_immune | 除去で消せる前提 | 除去 target 価値（免疫キャラへの KO を過大評価しない） | 免疫キャラを KO 対象に選ばない |
| negate | 自効果が通る前提 | 自キー効果の期待値割引（該当相手時） | — |
| key_threat | 全キャラ等価 | 除去 target 優先（pro 指定のキーカードを優先除去） | 指定カードを優先 KO |
| counter_timing | 札は即使う | 守備札の温存（該当相手の想定圧まで hold） | — |

## card_knowledge のスキーマ拡張（mine 結果の受け皿）

`engine/card_knowledge.py` の `PROS_FACTS[leader_id]` を matchup 知見の器にする:
```
PROS_FACTS["OP05-098"] = {
  "name","archetype","effective_life","lethal_rule","vs_advice","source",   # 既存(エネル)
  # 追加候補:
  "board_wipe": {"card_id","note","source"},        # over-extend 抑制
  "key_threats": [{"card_id","note","source"}],      # 優先除去
  "ko_immune_pieces": [...], "negate": [...],
}
```
機械導出 caveat（recovers_at_zero / ko_immune / negates / protects / board_wipe）は overlay から自動、
PROS_FACTS は記事から抽出した明示知見（source 明記必須、公式テキスト忠実主義と同じく出典を持つ）。

## 検証規律（重要）

- hard rule は **正確性で検証**（挙動が正しく変わるか）。mirror 勝率では測れない（[[feedback_evaluation_axis]]）。
- 配備 matrix への影響を必ず確認（該当リーダーが 16 プールに居るか）。居ないなら影響ゼロで安全。
- fuzzy を無理に hard rule 化しない（blanket 罠 = [[project_rollout_teacher_loop]] の教訓）。検出規律を守る。

## 実験ログ

- **2026-07-22**: 黄エネル回復 → lethal_estimate 補正（commit dd40e11）。第一 hard rule、verified。
- **2026-07-22**: 3 並列エージェントで meta 22 リーダーの pros02 記事を mine → **カードID検証済み 91 facts**
  を `db/pros02_matchup_facts.json` に統合。 `engine/card_knowledge.py` に accessor 追加
  (`matchup_facts_for` / `format_matchup_facts_for_teacher`)。

  **mine で確定した『どう活用するか』の答え**（fact_type を全リーダー集計した結論）:
  - 圧倒的多数が **`effective_life / recovery`**（「相手の実効ライフは厚い、削るな、7000+で確実に割れ、
    回復デッキとレースするな」）= ほぼ全 meta デッキ。 → **配備 value の `opp_life=0=near-win` は
    メタ全体で系統的に誤り**（Enel で直したのと同型）。
  - **だが meta の「実効ライフ厚い」は belief/確率的**（回復札を引く/大型を出せれば）で、Enel(黄)の
    機構的保証と違う → **リーダー別に lethal 割引をハードコードすると blanket 罠**（[[project_rollout_teacher_loop]]
    の -6pt 教訓）。
  - ko_immune/negate/KO-ペナルティ(ハンコック KO=ライフ焼き/7ロビン EB03-055 on_ko)は overlay で機構化
    済 = **探索が既に処理**（engine が on_ko/耐性を実行 → beam が結果を見る）。 hard rule 不要。
  - **∴ pros02 の価値の ~95% は belief/戦略判断 = hard rule でなく Claude 教師の採点 context に流す**
    （`format_matchup_facts_for_teacher`）。 hard rule 化できるのは機構的な数件のみ（回復リーダー=Enel、
    実装済）。 = 「40 ルールを書く」の逆で blanket 罠を避ける正しい形。

  **次の具体アクション**: (1) 教師ループ([[project_rollout_teacher_loop]])の採点 prompt に
  `format_matchup_facts_for_teacher(opp_leader)` を注入 → 配備 self-play を pros 定石で採点 → 逸脱を
  regress-proof residual 化。 (2) key_threat の latent 拘束(9ミホーク/8クロコ/4ペローナ)を value が
  過小評価する件は multi-turn 探索の宿題。
