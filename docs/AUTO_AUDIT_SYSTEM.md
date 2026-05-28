# 徹底改善 system: AI vs AI log + 公式 text から 自動 bug 検出 + 修正

> **2026-05-28 着手** — ohtsuki さん 「ゲームとして、 ルールが守られていて、 カードが正しく
> 機能しないと成立しない。 徹底的に改善する仕組みが必要」 への 構造解。
>
> 人間 目視 監査 を 廃して、 4-layer 自動 detector + 自動修正 loop で **全カード × 全ルール ×
> 全 game log** を 機械的 に audit する 基盤。

## 背景 (= なぜ 必要 か)

2026-05-28 の 人間 vs AI 対戦 で 以下 2 件 の bug が 人間 目視 で 発見 された:

| Bug | 種別 | 検出 経路 |
|---|---|---|
| set_cannot_rest 中 attack 不可 のはずが 飛ぶ | engine 漏れ | 人間 目視 |
| 自陣 optional replace_ko 自動発火 | overlay 不備 | 人間 目視 |

これらは **人間 vs AI で たまたま** 発見 された もの。 4848 game の AI vs AI 学習 中 にも
同等 (= 同じ仕組み 由来) の bug が 隠れている 可能性 が ある が 顕在化 する 機会 が 無い。
**新カード/新メタ追加 + 一般公開** を 視野 に 入れる と、 「目視 でしか 取れない」 状態 は
工数 scale しない = **将来性 0**。

## 設計 原則

1. **観測 可能 invariant**: 内部 実装 (= engine code) でなく **公式 text と 観測 状態** から 規則 を 書く。
   engine の bug を engine 自身 で test しても 同じ思考 漏れ で 取れない。
2. **coverage 数値化**: per-card 健全性 / per-primitive invariant 充足率 / per-rule 違反率 を
   dashboard 化、 改善 度合 を 可視化。
3. **CI 自動化**: commit 毎 (= 秒単位) Layer 1、 nightly Layer 2、 weekly Layer 3、 continuous Layer 4。
   人間 が 「audit を 走らせる」 という 意志決定 を 不要 に。
4. **regression 不可避 化**: 一度 catch した bug は assertion 化 されて 永久 に regression 検出。
5. **新カード 自動 carry-over**: 新弾 追加 → 静的 lint 自動 / runtime property 自動 / cardqa
   自動 ingest (= 半自動)、 既存 frame に 無 痛 で 乗る。

## 4-layer 構成

```
                ┌─────────────────────┐
                │ db/cards.json       │  ← 公式 text (一次情報)
                │ db/card_effects.json│  ← engine 解釈 (overlay)
                │ db/faq/cardqa_*.json│  ← 公式 Q&A (2500+)
                │ db/rules/*.pdf      │  ← 公式 ルール
                └────────┬────────────┘
                         │
       ┌─────────────────┼─────────────────────┐
       │                 │                     │
       ↓                 ↓                     ↓
┌─────────────┐  ┌──────────────────┐  ┌─────────────────┐
│ Layer 1     │  │ Layer 2          │  │ Layer 3         │
│ 静的 lint   │  │ runtime checker  │  │ cardqa oracle   │
│             │  │                  │  │                 │
│ overlay vs  │  │ effect_event log │  │ Q&A → assertion │
│ text 不一致 │  │ + invariant      │  │ 公式 裁定 ↔ 実装 │
└──────┬──────┘  └────────┬─────────┘  └────────┬────────┘
       │                  │                     │
       └──────────────────┼─────────────────────┘
                          ↓
              ┌─────────────────────┐
              │ db/violations/      │  ← 構造化 issue
              │   <ts>_<cid>.json   │
              └──────────┬──────────┘
                         ↓
              ┌─────────────────────┐
              │ Layer 4             │
              │ 自動 修正 loop      │
              │                     │
              │ claude sub-agent    │
              │  → 修正案 patch     │
              │  → pytest gate      │
              │  → auto-merge or    │
              │    human review     │
              └─────────────────────┘
```

## Layer 1: 静的 lint (= Phase 1、 1-2 日)

**Input**: `db/cards.json` + `db/card_effects.json`
**Output**: `db/static_audit_report.json` + `.md`
**実装**: `scripts/audit_overlay_static.py`

### 検出 pattern

| pattern | text 言葉 | overlay 期待 | catch する bug 例 |
|---|---|---|---|
| optional 漏れ | もよい / ことができる | `optional: true` | **Bug 2 系** (= OP14-061 ヴェルゴ) |
| 一回 制限 漏れ | ターン1回 | `once_per_turn: true` | once_per_turn 抜け |
| 自他 反転 | 相手の | target spec が `self_*` 禁止 | 自陣 誤適用 |
| 数 上限 漏れ | までを (= 上限) | `count: N` 必須 | 無制限 適用 |
| 条件 漏れ | 自分のリーダーが特徴《X》を持つ | `leader_feature: X` | 条件 無視 |
| trigger when 漏れ | 【XX時】 | `when: on_xx` 必須 | trigger 不発 |
| 範囲 ズレ | コスト N 以下 | `target_cost_le: N` | 範囲 超 適用 |
| duration ズレ | ターン中 / 次相手 end まで | `duration: turn` or `next_opp_turn_end` | 持続 違反 |

### 既知 該当 件数 (= 着手 前 概算)

- もよい/ことができる + replace_ko 漏れ: 43 件 (= task #25 で確認 済)
- ターン1回 + once_per_turn 漏れ: 推定 数十 件
- 【XX時】 + when 漏れ: 推定 数件
- その他: 数百 件 規模 ?

**初回 run で コミット されている bug の 大量 顕在化 を 期待**。

## Layer 2: runtime property checker (= Phase 2、 2-3 日)

**Input**: AI vs AI game log + effect_event log (NEW)
**Output**: `db/runtime_violations.json`
**実装**:
- `engine/effects.py` で effect_event 記録 hook 追加
- `scripts/audit_runtime_invariants.py` で 既存 4848 game corpus を replay → 違反 list

### effect_event log schema

```jsonc
{
  "ts": "T10 P1",
  "card_id": "OP14-069",
  "primitive": "set_cannot_rest",
  "target_iids": [12, 13, 14],
  "before": {
    "12": {"rested": true, "cannot_be_rested_buff": false},
    ...
  },
  "after": {
    "12": {"rested": true, "cannot_be_rested_buff": true},
    ...
  },
  "cost_paid": {"pay_don": 3},
  "source_iid": 5
}
```

### invariant (= 226 primitive 別 post + cross-cutting)

#### per-primitive post-condition (= 一部例)

```yaml
ko:
  post:
    - "target removed from owner.field"
    - "target.card in owner.trash"
    - "owner.don_rested += sum(target.attached_dons)"

draw:
  post:
    - "me.hand_count += min(N, len(me.deck))"
    - "me.deck_count -= min(N, len(me.deck))"

power_pump (duration=turn):
  post:
    - "target.power == before.power + amount"
    - "after turn end: target.power == before.power"

set_cannot_rest:
  post:
    - "target.cannot_be_rested_buff == True"
    - "target.cannot_be_rested_applier_idx == me_idx"

attach_don:
  post:
    - "me.don_active -= count"
    - "target.attached_dons += count"
```

#### cross-cutting invariant (= 最 高 leverage、 Bug 1 catch)

```yaml
cannot_be_rested:
  observable:
    - "for any action A: if chara X had cannot_be_rested_buff=True AND rested=False
       before A, then X.rested == False after A"
  catches:
    - Bug 1 (= attack で rest 化、 違反)
    - 同種 の rest 効果 漏れ 全般

ko_immune:
  observable:
    - "for any action A: if chara X had ko_immune=True before A,
       then X still in owner.field after A"

once_per_turn:
  observable:
    - "for any (card_id, effect_idx): count fires per turn ≤ 1"

dont_exceed_10_don:
  observable:
    - "for any player P at any state: P.don_active + P.don_rested ≤ 10"

life_in_range:
  observable:
    - "for any player P at any state: 0 ≤ len(P.life) ≤ 5"

hand_nonneg:
  observable:
    - "for any player P at any state: len(P.hand) ≥ 0"
```

### existing 4848 game corpus 活用

学習 round 1-4 の log は **既存 資産**。 新規 試合 不要 で 即 audit 走れる。
**期待**: Bug 1 と 同類 の 観測 違反 が 数百 件 顕在化。

## Layer 3: cardqa oracle (= Phase 3、 5-10 日)

**Input**: `db/faq/cardqa_*.json` (2500+ entries)
**Output**: `db/oracle_assertions.json` + per-card test cases

### 段階的 構築

1. **2500 件 tag 付け** (= 自動): 各 Q&A の Q/A を NLP regex で tag 化
   - tag 例: `optional`, `timing`, `target_range`, `cost_paid_even_if_fail`, `priority`
   - 出力: `db/cardqa_tagged.json`
2. **priority 100 cards 手動 assertion 化**: 学習 fire 多 + meta deck 採用 上位 cards
   - 1 card 平均 5-15 分 = 100 cards × 10 分 = ~17 時間
3. **残 cards LLM 補助**: claude code sub-agent に Q&A 一括 投入 → assertion 提案 → 人間 review
4. **継続 ingest**: 公式 Q&A 月次 更新 で 自動 tag → 新規 assertion 候補 浮上

### assertion DSL 例

```yaml
- card_id: OP14-061
  q: "ヴェルゴの効果は使わないこともできますか?"
  a: "はい、任意効果です。"
  derived:
    - overlay_field: "replace_ko[*].optional"
      expected: true
  catches: Bug 2

- card_id: OP14-069
  q: "次の相手のエンドフェイズ終了時までレストにできないキャラは、攻撃できますか?"
  a: "いいえ、攻撃はレストになる行動なのでできません。"
  derived:
    - runtime_invariant: "cannot_be_rested_buff → not in legal attackers"
  catches: Bug 1 (= confirms invariant Phase 2 で書ける)
```

## Layer 4: 自動 修正 loop (= Phase 4、 3-5 日)

**Input**: Layer 1-3 の violations
**Output**: PR / direct commit

### flow

```
violation 検出
   ↓
db/auto_issues/<ts>_<cid>_<layer>.json 出力
   {
     "card_id": "OP14-061",
     "layer": "static_lint",
     "violation": "missing optional flag",
     "evidence": {
       "official_text_excerpt": "戻すことができる",
       "overlay_current": {"optional": null}
     },
     "suggested_fix": {
       "file": "db/card_effects.json",
       "patch": "OP14-061 replace_ko entry に optional: true 追加"
     },
     "risk_tier": "low"  // low: data-only / mid: 1 primitive / high: cross-cutting
   }
   ↓
cron / GitHub Actions hook
   ↓
claude code sub-agent (= TaskCreate("fix audit issue #X"))
   - 入力: issue file + 関連 source
   - 出力: branch + commit + PR
   - pytest gate: 必須 pass
   ↓
risk_tier 別 ハンドリング:
  - low (= overlay flag 追加 等): auto-merge if pytest pass
  - mid (= 単一 primitive 修正): human 1 click approval
  - high (= cross-cutting / engine 改造): human review queue (= 通常 PR)
```

### 安全 装置

- **dry-run mode**: 初期 数 週間 は auto-merge OFF、 全 PR を human review。 false-positive
  pattern を 蓄積 して exclusion list 充実 後 に auto-merge 解禁。
- **rollback**: violation 「修正」 後 に 別 violation が 増えたら 自動 revert。
- **rate limit**: 1 日 N 件 まで (= AI 暴走 防止)。

## coverage dashboard (= /audit page)

### per-card 健全性

各 4518 card に 以下 metric:

| 軸 | 内容 |
|---|---|
| static lint | Layer 1 pass / fail count |
| runtime fire | 4848 game corpus で fire 回数 |
| cardqa coverage | 該当 Q&A 件数 / 内 assertion 化 済 |
| invariant 違反 | 当該 card に紐づく runtime violations |

→ 信号: ✅ (全 pass) / ⚠ (lint warn) / ❌ (違反 あり)

### per-primitive 健全性

各 226 primitive:

| 軸 | 内容 |
|---|---|
| post-condition | 宣言 済 / 未宣言 |
| cross-cutting | 関連 invariant 数 |
| 違反 件数 | 4848 game で 検出 |
| usage count | 全 overlay 中 使用 回数 |

### game integrity

| 軸 | 内容 |
|---|---|
| rule violations / 100 games | 直近 学習 round の 違反率 |
| 履歴 trend | round-over-round 改善 推移 |

## CI 統合

| event | layer | runtime |
|---|---|---|
| commit push | Layer 1 (= 静的 lint) | < 10 秒 |
| nightly cron | Layer 2 (= 直近 24h game corpus replay) | 5-15 分 |
| weekly cron | Layer 3 (= cardqa parse 拡張) | 30-60 分 |
| continuous | Layer 4 (= auto-issue 消化) | 1 件 / 数 分 |

## 既存 仕組 と の 関係

| 既存 | 拡張 |
|---|---|
| `RuleReferee` | Layer 2 cross-cutting invariant に 取り込み |
| `scripts/audit_overlay_vs_faq.py` (= sev≥3 = 0 達成 済) | Layer 1 静的 lint の 一部 として 統合 |
| `scripts/verify_overlay_vs_cardqa.py` | Layer 3 cardqa oracle の prototype |
| `scripts/smoke_test_card_effects.py` | Layer 2 effect_event 蓄積 を 兼ねる |
| `tests/*.py` 既存 799 件 | Layer 2/3 で 自動生成 された tests を 追加 |

## 工数 + 期待 効果

| Phase | 工数 | 期待 効果 |
|---|---|---|
| 設計 docs (= 本ファイル) | 1 日 | (= 完了) |
| Phase 1 静的 lint | 1-2 日 | Bug 2 系 + 既知 43 件 + 推定 数百 件 一気 catch |
| Phase 2 runtime checker | 2-3 日 | Bug 1 系 + 観測 違反 数十 件 catch |
| Phase 3 cardqa oracle (100 件 priority) | 5-10 日 | 公式 裁定 由来 の 細かい 漏れ 検出 |
| Phase 4 自動修正 (= dry-run 期間 含む) | 3-5 日 | 人間 review 工数 大幅 削減 |
| dashboard + CI 統合 | 2-3 日 | 改善 度合 可視化 + 自動化 完了 |
| **合計** | **2-3 週間** | **将来性 確保** |

## 次 着手 (= 即 開始)

1. **task #28 (= 本 設計 docs)** → commit
2. **task #29 (= Phase 1 静的 lint)** → `scripts/audit_overlay_static.py` 構築 → 4518 card 全部 run → 違反 list 確認 + 修正
3. その後 task #30 (= Phase 2 runtime checker)

並列 で task #25 (= 残 43 cards optional mark) は Phase 1 静的 lint の 出力 で **自動 抽出** されて 同時 解消 する 見込み = 統合。
