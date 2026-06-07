# デッキプレイ知識システム 仕様 (Deck Play Knowledge)

> 目的: **デッキの中身を確認し、 (1) デッキ内コンボの発見、 (2) 各カードの有効な使い方を学習**して
> 知識アーティファクトに保存し、 **対戦用 AI が対戦時にそれを使う**。
> ohtsuki 指示 (2026-06-07): 「カードの効果を最大限発揮し、 デッキ内コンボを把握してプレイする AI」。

## 0. 設計原則

- **固定プランを作らない**: コンボ手順を committed macro にしない (= 過去 dead-end の塊プラン路線、
  [[project_70pct_vs_greedy]])。 知識は **探索のプライア / 評価のヒント / 可視化の素材**。 最終判断は
  対戦時の探索が盤面・相手を見て下す。
- **全カード・全デッキ汎用**: calgara 専用にしない。 16 デッキ + 任意の推しキャラデッキ + 全 4,518 枚で
  成立する (= プロジェクトの「任意 deck 汎用 AI」ゴール)。 知識は **カード効果 DSL (`card_effects.json`)
  から決定論的に導出** + (任意で) 自己対戦 corpus で補正。
- **検証は手の質**: 勝率でなく実対戦ログで「効果が活きる文脈で使えているか」 を読む ([[feedback_evaluation_axis]])。

## 1. アーティファクト: `db/deck_play_knowledge_<slug>.json`

deck別に生成 (= 再生成可、 gitignore)。 構造:

```jsonc
{
  "slug": "tcgportal_calgara", "deck_name": "黄カルガラ", "main_feature": "空島",
  "summon_features": ["シャンドラの戦士"],     // 登場踏み倒しの対象 feature
  "combos": [                                    // = デッキ内コンボ (発見結果)
    {"tag": "attach_don", "to": "OP08-098", "from": ["OP15-114","EB03-053"],
     "kind": "enabler->payoff",
     "desc": "ドン付与 → リーダーの登場時summon (self_attached_don_ge:1) が発火"}
  ],
  "cards": {                                     // = 各カードの有効な使い方 (学習結果)
    "EB04-058": {
      "name": "ボルサリーノ", "cost": 5, "power": 6000, "counter": 1000,
      "roles": ["blocker", "recovery"],          // 役割分類
      "produces": ["life+"], "consumes": ["low_life"],
      "usage": [                                  // 効果ごとの発動文脈
        {"when": "on_play", "if": {"self_life_le": 2}, "do": ["put_top_to_life"],
         "value_class": "recovery", "live_when": "self_life<=2",
         "reachable": "self_life は減るので将来満たされやすい"}
      ],
      "combo": {"enables": [], "enabled_by": []},
      "timing_hint": "登場時効果は self_life<=2 でのみ発火。 高ライフは body(6000ブロッカー)のみ → 他に手がなければ可、 基本は低ライフまで温存"
    }
  }
}
```

## 2. 発見・学習パイプライン (生成: `scripts/build_deck_knowledge.py`)

### Stage A — コンボ発見 (静的、 DSL)
各カードが DSL から **produces (生む資源/条件)** と **consumes (要る資源/条件)** を抽出し、
`A.produces ∩ B.consumes` でエッジ。 資源タグ例:
- produces: `hand:<feature>` (サーチ/ドロー), `attach_don`, `don` (ramp), `life+`, `keyword`,
  `trash+`, `cost_reduction`, `board:<feature/name>`
- consumes: `attach_don`/`don`/`trash+`/`cost_reduction` (if/cost), `board:<X>`
  (`self_chara_filtered_count_ge`), `hand:<feature>` (summon 対象)
- 外的条件 (`self_life_le`/`opp_life_ge` 等) は **デッキ内で作れない = コンボでなく状況待ち**に分類。

### Stage B — 各カードの有効な使い方 (静的、 DSL)
カードごとに効果 (`when`/`if`/`do`) を解析:
- **roles**: enabler / payoff / blocker / counter / finisher / removal / searcher / ramp / recovery / pump
- **usage[]**: 効果ごとに (trigger, 条件, do の value_class, `live_when` = 発動文脈,
  `reachable` = 条件が将来満たされやすいか)
- **timing_hint**: 条件 + role から「いつ使うのが最も価値が高いか」 の言語化

### Stage C — corpus 補正 (任意、 将来)
自己対戦 corpus から ①非自明コンボ (手順→eval跳ね マイニング) ②各カードの文脈価値 Q(attrs, state)
③条件到達可能性 を学習し Stage A/B を補正 ([[feedback_corpus_methodology]])。 v1 は静的のみで動く。

## 3. 対戦 AI の利用機能 (`engine/deck_play_knowledge.py` loader + AI hook)

対戦開始時に deck_slug から知識をロードし、 **候補手のスコアリング**で使う (= 固定プランでなくプライア):

1. **タイミング bonus/defer** (= 各カードの有効な使い方):
   - `play C` 候補で C の on_play 等の `if` が **今 live** → bonus。
   - 主要 on_play 効果が **今 dead** だが `reachable` かつ温存余力あり → **defer penalty** (= ボルサリーノを
     高ライフでスルー)。 他に手がない/テンポを失うなら penalty < body 価値で出す。
2. **コンボ bonus** (= デッキ内コンボ):
   - C が「準備完了コンボ」 を前進/完成させる (= partner が場/手札に揃う) → bonus。
3. **探索の枝刈り回避** (= 仕込み手を殺さない):
   - C が enabler (combo の from 側) なら beam の中間枝刈りから保護 (= [[project_combo_aware_ai]] 施策1)。

実装は **配備 AI (SmartOpponentAI = ExploitBeam/GoalDirectedAI)** に hook ([[feedback_unified_deployed_ai]])。
A/B は pure_lookup で測る ([[feedback_eval_specs_in_pure_lookup]])。 env flag で on/off 可。

## 4. 検証
実ログ精読で複数カード型 × 複数デッキ:
- 条件カードが条件成立時に発動 (ボルサリーノ低ライフ等)
- コンボのパーツが揃った時に実行 (calgara: ドン付与+シャンドラ手札 → summon)
- 除去が対象有時、 カウンターが防御時、 ドローが手札少時

## 5. 段階
- **S0 (済)**: コンボ発見 Stage A、 全16デッキで動作 (`build_combo_graph.py`)。
- **S1**: Stage B (各カード usage) を生成に追加 → 完全アーティファクト。
- **S2**: loader + タイミング/コンボ bonus を AI に hook、 calgara で手の質検証。
- **S3**: 全16展開 + corpus 補正 (Stage C)。
