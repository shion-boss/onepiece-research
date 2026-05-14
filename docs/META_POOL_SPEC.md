# メタデッキ pool 仕様 (= 確定版)

> 2026-05-14 確定。 ROADMAP.md Phase 7 の一部として実装予定。
> 関連: [docs/ROADMAP.md](./ROADMAP.md), [CLAUDE.md](../CLAUDE.md)

## 目的

「現メタの主要 archetype vs 対戦評価」 を継続的に運用するため、 **active プール** と
**historical プール** を分離した recipe 管理を確立する。 過去 archetype も
`deck_classifier` の学習データとして残す。

### Active pool サイズ

固定 16 ではなく、 **動的サイズ** で運用:
- top N usage_pct で 上位 archetype を採用
- ただし **「同 leader 内で構築が分かれてる場合は別 variant として個別カウント」**
- 結果: 「リーダー 16 種類だが、 一部が variant 別 = pool サイズ 18-20」 という形態も許容

サイズ目安: **15-25 archetype** が現実的。
- 下限 15: メタ主要をカバー (= 使用率上位 90%+)
- 上限 25: matrix 計算コストの実用範囲 (= 25² × 20 × 2.4s = 8 時間以内)
- 超過時: usage_pct 下位から圏外化

## 確定方針 (= 2026-05-14)

| 項目 | 決定 |
|---|---|
| 更新頻度 | **月次** (= 月初自動) + **イベント trigger** (= 新弾/禁止リスト) |
| Matrix 更新粒度 | **per-cell timestamp + stale 再計算** (= 変更分のみ) |
| Archetype slug | **永続 slug** (= leader_id ベース) |
| Historical 保存期限 | **無期限** (= ML データとして全保存) |

---

## ディレクトリ構造

```
decks/
├── active/                          ← 現メタ top 16 (= matrix 対象)
│   ├── OP15-058/                    (= 紫エネル、 leader_id ベース slug)
│   │   ├── recipe.json
│   │   ├── analysis.json
│   │   └── _meta.json
│   ├── OP15-002/                    (= 赤青ルーシー)
│   ├── ... 16 dirs
│   └── _pool_index.json             ← 全 active archetype の一覧 + 使用率
│
├── historical/                      ← 圏外になった archetype の最終 recipe
│   ├── OP12-041/                    (= 青紫サンジ、 例)
│   │   ├── recipe.json              (= last_active 時の recipe を凍結保存)
│   │   ├── analysis.json
│   │   └── _meta.json
│   ├── ...
│   └── _pool_index.json
│
└── _archive/
    ├── cardrush_raw/                ← 個別レシピ (= 代表選出されなかった生 88+ 件)
    │   ├── cardrush_1273.json
    │   └── ...
    ├── recipe_history/              ← 同 archetype の歴史的 recipe バリエーション
    │   ├── OP15-058/                (= 紫エネル の歴史)
    │   │   ├── 2026-02_cardrush_1130.json
    │   │   ├── 2026-03_cardrush_1284.json
    │   │   └── 2026-05_cardrush_1454.json
    │   └── ...
    └── deprecated_meta/             ← 旧形式 meta_*.json 等
```

### Slug 規約

**archetype slug = `<leader_id>` または `<leader_id>_<variant>`**

- 単一構築: `OP15-058` (= 紫エネル の標準構築)
- 複数構築: `OP15-058_aggro` / `OP15-058_control` (= 同じリーダーで構築が分離した場合)

#### なぜ 「同じリーダーでも構築別」 で管理するか

同じリーダーカードでも、 採用カード次第で **戦略が全く別物** になるケースがある:

| 例 | 構築 A | 構築 B |
|---|---|---|
| **赤青エース** | 「速攻リーダー詰め」 アグロ型 | 「サテライト + 中型キャラ」 ミッド型 |
| **黄カルガラ** | 「ライフ回復維持」 コントロール型 | 「空島シナジー」 ミッド型 |
| **緑ミホーク** | 「超新星サーチ高速展開」 | 「ミホーク守備重視」 |

このような構築差は AI 戦略に直結する (= 別 archetype として扱わないと matchup 予測が不正確)。

### Variant の検出

#### 自動検出 (= 統計クラスタリング)

```python
def detect_variants(leader_id, recipes_in_period):
    """同 leader の recipe 群を card 採用パターンで k-means クラスタリング"""
    if len(recipes_in_period) < 4:
        return [recipes_in_period]  # サンプル不足 → 単一 variant
    
    # 各 recipe を「カード ID → 採用枚数」 のベクトル化
    vectors = [recipe_to_vector(r) for r in recipes_in_period]
    
    # silhouette score で最適クラスタ数 k を選ぶ (k=1〜3)
    best_k = optimal_k(vectors)
    if best_k == 1:
        return [recipes_in_period]  # 統計的に単一構築と判定
    
    clusters = kmeans(vectors, k=best_k)
    return clusters  # 複数 variant 検出
```

検出基準:
- 同 leader で 4+ レシピが存在
- silhouette score ≥ 0.4 で複数構築と判定
- 各 variant に 「特徴的 4 枚」 (= 採用率差最大のカード) を自動抽出 → variant 名候補

#### 手動命名 (= 人間による調整)

自動検出された variant は仮名 (`<leader_id>_v1` / `v2`) で命名。
人間が後で `_meta.json` を編集して意味のある名前に置き換え:

```json
// decks/active/OP15-058_v1/_meta.json → 編集
{
  "archetype_slug": "OP15-058_aggro",   // 「v1」 → 「aggro」 にリネーム
  "variant_label": "アグロ型 (= プリン採用)",
  "characteristic_cards": ["OP12-071", "OP15-118"],   // 特徴カード
  ...
}
```

`refresh_meta_pool.py` 実行時、 命名済 variant は維持 (= 自動上書きしない)。

#### Variant の独立性

各 variant は **完全に独立した archetype として扱う**:
- 独自の `recipe.json` / `analysis.json` / `_meta.json`
- 独自の matrix 行 / 列
- classifier の独自カテゴリ
- usage_history も variant 別に集計

### 現状データでの variant 検出見込み (= 2026-05-14 時点)

`decks/_archive/cardrush_raw/` の 88 件 + active 16 から、 5+ recipe を持つ leader:

| leader | name | recipe 数 | variant 検出見込み |
|---|---|---|---|
| OP15-058 | 紫エネル | 30 | **2-3 variants** (= プリン採用型 / 旧 cardrush 構成型 等) |
| OP11-041 | 青黄ナミ | 16 | **1-2 variants** (= 標準型 が主流の可能性) |
| OP15-098 | 空島ルフィ | 11 | **1-2 variants** |
| OP14-020 | 緑ミホーク | 10 | **1-2 variants** (= 速展開 / 守備型) |
| OP15-002 | 赤青ルーシー | 10 | **1-2 variants** |
| OP14-041 | 青黄ハンコック | 8 | **1-2 variants** |
| OP13-079 | 黒イム | 5 | 単一 (= サンプル不足) |
| OP13-002 | 赤青エース | 5 | 単一 (= サンプル不足) |

その他 8 leader はサンプル不足 (= 1-4 件) で当面単一 variant 扱い。

### 当面の運用 (= Phase 7F 実装開始時)

1. 全 16 archetype を **単一 variant でスタート** (= 既存 active 16 を leader_id slug で migration)
2. variant 検出は **Phase 7F-3 で 月次 refresh に統合**、 検出されたら自動 split
3. 自動 split された variant は仮名 `_v1` / `_v2` で運用
4. 人間が観察して「これは aggro 型」 と判定したら `_meta.json` をリネーム
5. 命名済 variant は以後 refresh 時に維持 (= 自動上書き禁止)

### 既存命名との対応

| 現状 (= cardrush_<id>) | 新 (= leader_id) | leader |
|---|---|---|
| cardrush_1454 | OP15-058 | 紫エネル |
| cardrush_1399 | OP15-002 | 赤青ルーシー |
| cardrush_1407 | OP14-041 | 青黄ハンコック |
| cardrush_1439 | OP11-041 | 青黄ナミ |
| cardrush_1455 | OP15-098 | 黄ルフィ(OP15、 cardrush 上は「空島ルフィ」) |
| cardrush_1453 | OP14-020 | 緑ミホーク |
| cardrush_1456 | OP13-002 | 赤青エース |
| cardrush_1392 | OP13-079 | 黒イム |
| cardrush_1385 | OP14-079 | 黒クロコダイル |
| cardrush_1342 | OP14-060 | 紫ドフラミンゴ |
| tcgportal_op11_luffy | OP11-040 | 青紫ルフィ |
| tcgportal_bonney | EB04-001 | 赤黄ボニー |
| tcgportal_calgara | OP08-098 | 黄カルガラ |
| tcgportal_op13_luffy | OP13-001 | 赤緑ルフィ(OP13) |
| tcgportal_coby | OP11-001 | 赤黒コビー |
| tcgportal_corazon | OP12-061 | 紫黄ロシナンテ |

### 内部参照 (= 既存 slug 互換)

実 deck JSON ファイル内では現在の `cardrush_1454` のような大会 ID も `recipe.json` の
metadata に保持 (= 出典トレーサビリティ)。

```json
// decks/active/OP15-058/recipe.json
{
  "archetype_slug": "OP15-058",
  "archetype_name_jp": "紫エネル",
  "source_recipe_id": "cardrush_1454",
  "source_url": "https://cardrush.media/onepiece/decks/1454",
  "name": "紫エネル",
  "leader": "OP15-058",
  "main": [...]
}
```

---

## Metadata schema

### `decks/active/<slug>/_meta.json`

```json
{
  "archetype_slug": "OP15-058",
  "archetype_name_jp": "紫エネル",
  "leader_id": "OP15-058",
  "leader_name": "エネル",
  "leader_color": ["紫"],
  "status": "active",
  "first_seen_at": "2026-01-15",
  "last_active_at": "2026-05-13",
  "current_recipe_source": "cardrush_1454",
  "current_recipe_date": "2026-05-11",
  "usage_history": [
    { "snapshot_date": "2026-03-01", "usage_pct": 14.2, "rank": 1, "tier": 1 },
    { "snapshot_date": "2026-04-01", "usage_pct": 13.5, "rank": 1, "tier": 1 },
    { "snapshot_date": "2026-05-01", "usage_pct": 12.7, "rank": 1, "tier": 1 }
  ],
  "recipe_evolution": [
    { "date": "2026-02-15", "source": "cardrush_1130", "key_diffs": "初期構成" },
    { "date": "2026-04-29", "source": "cardrush_1398", "key_diffs": "プリン採用" },
    { "date": "2026-05-11", "source": "cardrush_1454", "key_diffs": "神避 4 枚化" }
  ]
}
```

### `decks/historical/<slug>/_meta.json`

```json
{
  "archetype_slug": "OP12-041",
  "archetype_name_jp": "青紫サンジ",
  "leader_id": "OP12-041",
  "status": "historical",
  "first_seen_at": "2026-02-01",
  "last_active_at": "2026-04-01",      // この日以降 top 16 圏外
  "fell_out_at": "2026-05-01",         // 圏外確認日
  "current_recipe_source": "cardrush_1339",
  "current_recipe_date": "2026-04-18",  // 凍結保存された recipe の元データ日付
  "usage_history": [
    { "snapshot_date": "2026-02-01", "usage_pct": 4.5, "rank": 8, "tier": 3 },
    { "snapshot_date": "2026-03-01", "usage_pct": 3.1, "rank": 12, "tier": 4 },
    { "snapshot_date": "2026-04-01", "usage_pct": 2.0, "rank": 16, "tier": 4 },
    { "snapshot_date": "2026-05-01", "usage_pct": 1.2, "rank": 22 }   // 圏外
  ]
}
```

### `decks/active/_pool_index.json` (= 全 archetype 横断 index)

```json
{
  "snapshot_date": "2026-05-13",
  "data_source": "tcg-portal /meta-analysis",
  "data_window": "2026-02-14 to 2026-05-13",
  "tournament_count": 1040,
  "archetypes": [
    { "slug": "OP15-058", "name_jp": "紫エネル", "usage_pct": 12.7, "rank": 1, "tier": 1 },
    { "slug": "OP15-002", "name_jp": "赤青ルーシー", "usage_pct": 11.3, "rank": 2, "tier": 1 },
    ...
  ]
}
```

---

## 更新ワークフロー

### Cadence

| Trigger | 動作 |
|---|---|
| 月初 (= 自動) | フル refresh (= tcg-portal + cardrush 取得 → 全 archetype update) |
| 新弾発売 (= 手動 kick) | フル refresh + 直近 1 週間のみ重み付け |
| 禁止リスト更新 | 禁止カード使用デッキの即 archive、 新規 recipe 待ち |
| 手動 (= 任意) | `scripts/refresh_meta_pool.py --force` |

### 自動化スクリプト

#### `scripts/refresh_meta_pool.py` (新規、 orchestrator)

```python
def main(args):
    today = date.today()
    
    # ─ Step 1: 外部データ取得 ─
    tcgportal_top_n = fetch_tcgportal_meta_analysis(
        window_months=3, top_n=16
    )
    cardrush_winners = scrape_cardrush_winning_decks(
        since=today - timedelta(days=90),
    )
    
    # ─ Step 2: 各 top archetype に representative 選出 ─
    new_active = {}
    for entry in tcgportal_top_n:
        slug = entry.leader_id  # = "OP15-058" 等
        rep = select_representative(
            slug, cardrush_winners,
            fallback=lambda: synthesize_from_tcgportal(slug),
        )
        new_active[slug] = rep
    
    # ─ Step 3: status 遷移 ─
    old_active = load_pool("active")
    transitions = []
    
    # 継続中: recipe 変更があれば evolution に追記
    for slug in set(new_active) & set(old_active):
        if recipe_changed(old_active[slug], new_active[slug]):
            archive_old_recipe(slug, old_active[slug])
            update_evolution(slug, new_active[slug])
            transitions.append(("recipe_changed", slug))
        update_usage_snapshot(slug, today, tcgportal_top_n)
    
    # 圏外化: active → historical へ移動
    for slug in set(old_active) - set(new_active):
        move_active_to_historical(slug)
        update_usage_snapshot(slug, today, tcgportal_top_n)  # 圏外 rank も記録
        transitions.append(("fell_out", slug))
    
    # 新規 active 化
    for slug in set(new_active) - set(old_active):
        if slug in load_pool("historical"):
            # 復活: historical → active
            promote_historical_to_active(slug, new_active[slug])
            transitions.append(("returned", slug))
        else:
            # 完全新規
            add_new_active(slug, new_active[slug])
            transitions.append(("new", slug))
    
    # ─ Step 4: pool index 更新 + recipe_history snapshot ─
    update_pool_index(today, tcgportal_top_n)
    archive_monthly_recipes(today, new_active)
    
    # ─ Step 5: matrix 影響評価 ─
    invalidate_matrix_cells(transitions)
    
    # ─ Step 6: 変動レポート ─
    print_changelog(today, transitions)
    if args.recompute_matrix:
        recompute_stale_matrix_cells()
```

#### 既存スクリプトの改修

- `scrape_cardrush_decks.py`: 出力先を `decks/_archive/cardrush_raw/` に統一、 代表選出と切り離す
- `scrape_tcgportal_decks.py`: tier list hardcode を廃止、 動的 fetch のみ
- `select_cardrush_representatives.py`: 廃止 (= `refresh_meta_pool.py` に統合)
- `compute_matchup_matrix.py`: `decks/active/*/recipe.json` を対象に、 per-cell timestamp 対応

---

## Matrix 更新粒度

### per-cell timestamp 方式

`db/matchup_matrix.json` 拡張:

```json
{
  "version": "2.0",
  "matrix": [
    {
      "deck_a": "OP15-058",
      "deck_a_recipe_hash": "abc123...",
      "row": [
        {
          "deck_b": "OP15-002",
          "deck_b_recipe_hash": "def456...",
          "winrate": 0.65,
          "wins": 13,
          "losses": 7,
          "draws": 0,
          "avg_turns": 8.5,
          "computed_at": "2026-05-14T15:00:00Z",
          "ai_version": "PlanningAI_R71",
          "stale": false
        }
      ]
    }
  ]
}
```

各 cell に保持:
- `deck_a_recipe_hash` / `deck_b_recipe_hash`: 該当 deck recipe の hash (= 変更検知)
- `computed_at`: 算出日時
- `ai_version`: 使った AI 識別子 (= AI 改善時の invalidation 用)
- `stale`: 手動 flag (= 計算待ち or invalid)

### Invalidation rule

deck recipe 変更時:
```python
def invalidate_cells_for_deck(slug):
    """この slug が deck_a か deck_b として登場する全 cell を stale 化"""
    for row in matrix:
        if row.deck_a == slug:
            for cell in row.row:
                cell.stale = True
        else:
            for cell in row.row:
                if cell.deck_b == slug:
                    cell.stale = True
```

AI 改善時 (= ai_version 変更):
```python
def invalidate_all_for_ai_version(new_version):
    """全 cell を stale 化 (= AI 変更影響は全体に及ぶ)"""
    for row in matrix:
        for cell in row.row:
            if cell.ai_version != new_version:
                cell.stale = True
```

### Recompute strategy

```python
def recompute_stale_cells(args):
    stale_cells = find_stale_cells()
    print(f"再計算対象: {len(stale_cells)} cells")
    for cell in stale_cells:
        rep = run_matchup(
            load_deck(cell.deck_a), load_deck(cell.deck_b),
            n_games=args.n_games, seed=args.seed,
        )
        update_cell(cell, rep, ai_version=current_ai_version())
```

コスト見積もり (= 16 deck pool, 2.4s/g, n=20):
- 全 stale (= AI 変更時): 6 時間
- 1 deck recipe 変更: 30 cells (= 1 行 + 1 列) × 20 × 2.4s = **24 分**
- 月次更新で 3 deck 変更想定: ~90 cells = **72 分**

---

## Phase 7C (deck classifier) との連動

classifier 学習データ:
- **active 16**: prior 大 (= 高 usage_pct)
- **historical N**: prior 小 (= 過去 usage の decay 重み)
- **recipe_history/**: 同 archetype の変動を学習 (= 「初期版 vs 最新版」 識別)

```python
def build_classifier_prior() -> dict[str, float]:
    priors = {}
    # active: 現在の使用率
    for slug, meta in load_pool("active").items():
        priors[slug] = meta.current_usage_pct
    # historical: 過去使用率 × decay (= 経過月数で減衰)
    for slug, meta in load_pool("historical").items():
        avg_pct = average_recent_usage(meta.usage_history, months=6)
        months_since = (today - meta.last_active_at).months
        decay = 0.5 ** months_since
        priors[slug] = avg_pct * decay
    return softmax(priors)
```

---

## 実装ステップ (= Phase 7F として追加)

### Phase 7F: メタデッキ pool 再構造化 (= 1-2 週間)

1. **7F-1**: ディレクトリ構造移行 (= 0.5 日)
   - `decks/cardrush_*.json` → `decks/active/<leader_id>/recipe.json`
   - `decks/tcgportal_*.json` → 同上 (= leader_id でリネーム)
   - `decks/_archive/out_of_top16/` → `decks/historical/`

2. **7F-2**: metadata schema 適用 (= 1 日)
   - 各 archetype に `_meta.json` 生成
   - `_pool_index.json` の初期スナップショット

3. **7F-3**: `refresh_meta_pool.py` 実装 (= 2-3 日)
   - tcg-portal + cardrush 統合
   - status 遷移ロジック
   - recipe_history snapshot

4. **7F-4**: matrix per-cell timestamp 対応 (= 1-2 日)
   - `db/matchup_matrix.json` schema v2 対応
   - hash + ai_version + stale flag
   - `recompute_stale_cells.py` 新規

5. **7F-5**: 既存スクリプト改修 (= 1 日)
   - `compute_matchup_matrix.py` を `decks/active/` 対応
   - `select_cardrush_representatives.py` 廃止 → `refresh_meta_pool.py` 統合

6. **7F-6**: API / UI 対応 (= 1-2 日)
   - `/api/decks` glob を `decks/active/` に切替
   - `/meta` ページに「historical」 タブ追加 (= 過去 archetype 一覧)
   - matrix viewer に `stale` 表示

7. **7F-7**: 月次 cron 設定 + イベント trigger 文書化 (= 0.5 日)

**Phase 7F は Phase 7A〜7E と並走可能** (= ファイル構造変更は engine 動作と独立)。

実装順:
- 7F-1, 7F-2 を最初に (= structure)
- 7F-3, 7F-4 を engine 側 (7A-7E) と並走
- 7F-5, 7F-6, 7F-7 を最後に統合

---

## 移行時の注意点

### Matrix 互換性

現在の `db/matchup_matrix.json` は schema v1 (= deck_a/deck_b が cardrush slug)。
v2 (= leader_id slug + timestamp) への移行時に旧データを保持:

```bash
mv db/matchup_matrix.json db/matchup_matrix.v1.json
# 新形式で再計算
```

旧スコアの保存目的: 比較レポート (= v1 で AI baseline → v2 で AI 改善後 の対照)

### API 後方互換

`/api/decks` に新旧両対応のラベル:
```json
{
  "slug": "OP15-058",           // 新 archetype slug
  "legacy_slug": "cardrush_1454", // 旧大会 ID
  "name": "紫エネル",
  ...
}
```

旧クライアント (= ブックマーク URL) は `legacy_slug` で参照可能、 新規は `slug` 推奨。

---

## 更新条件

このドキュメントを更新する条件:

- メタデッキの top N サイズ変更 (= 16 → 20 等)
- 更新頻度 / cadence 変更
- ディレクトリ構造変更
- archetype slug 規約変更

(= 単発の archetype 入替や recipe 更新では更新不要、 ワークフローが自動で処理する)
