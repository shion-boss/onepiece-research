---
name: onepiece-tcg-refresh
description: ONE PIECE カードゲームの公式データ一式 (カード DB / 効果オーバーレイ + engine / 公式 FAQ・cardqa / 禁止・制限リスト / ルール PDF / レギュレーション) を最新の公式状態へ総合的に更新する運用 runbook。新弾リリース時や定期更新時の唯一の入口。ユーザーが「カード情報は最新か」「新弾を入れて/追加」「最新化して」「OPxx/新セットを取り込む」「公式の更新を確認」「禁止リスト/FAQ/cardqa/レギュレーションを更新」「データをリフレッシュ」等と言ったら、個別スクリプト名を出していなくても必ずこのスキルを使う。既存スクリプト (scraper.py / check_official_updates.py / refresh_all.py / overlay パイプライン / audit 群) を正しい順序・公式テキスト忠実主義で束ねる。
last_reviewed: 2026-06-15
---

# ONE PIECE データ最新化 runbook

新しい弾が出るたび (および定期チェックで)、 5 つの公式リソースを最新化する。 **`db/cards.json` が「正」、 SQLite は派生物**、 効果は `db/card_effects.json` overlay (公式テキスト忠実主義)。

| # | 対象 | 主担当スクリプト | 重さ |
|---|---|---|---|
| 1 | 新カード (cards.json/sqlite) | `scraper/scraper.py` | 軽 (数分) |
| 2 | 効果 overlay + engine 拡張 | 手作業 + `suggest_overlay_from_cards.py` + audit 群 | **重 (新弾の本体)** |
| 3 | FAQ / cardqa | `check_official_updates.py` (自動 rescrape) | 軽 |
| 4 | 禁止/制限/禁止ペア | `check_official_updates.py` (自動 rescrape) | 軽 |
| 5 | ルール PDF / レギュレーション | `check_official_updates.py` + `engine/deck.py` validate | 軽 |
| + | 下流 (画像 / メタ / matrix) | `cache_*_images.py` / `refresh_all.py` | 重 (matrix ~80分) |

すべて `.venv/bin/python` で実行 (リポジトリルート = `/home/ohtsuki/projects/onepiece_research`)。 各ステップの完了を確認してから次へ進む。

---

## Step 0 — 何が新しいか検知する (read-only)

まず差分を把握してからスコープを決める。 ⚠ scraper は HTML を `/tmp/onepiece_html` にキャッシュするので、 **新シリーズを発見するには top ページのキャッシュを消す**。

```bash
rm -f /tmp/onepiece_html/_top.html
.venv/bin/python scraper/scraper.py --list-series        # 公式の全 series (55+ 件)
```

これを `cards.json` の収録弾と突き合わせ、 未取得の series を特定する (例: OP16 = 550116)。 確認用:

```bash
.venv/bin/python - <<'PY'
import json, re
from collections import Counter
cards = json.load(open("db/cards.json", encoding="utf-8"))
sets = Counter(re.match(r'^(OP\d+|EB\d+|ST\d+|PRB\d+|P)', c["card_id"].split("_")[0]).group(1)
               for c in cards if re.match(r'^(OP\d+|EB\d+|ST\d+|PRB\d+|P)', c["card_id"]))
print("総数", len(cards), "/ 弾", dict(sorted(sets.items())))
PY
```

FAQ / cardqa / 禁止リスト / PDF の変更検知 (ハッシュ比較。 変更があれば自動で再 scrape する):

```bash
.venv/bin/python scripts/check_official_updates.py
```

→ 出力の `[NEW]/[CHANGED]` と末尾サマリで、 どのリソースが動いたか分かる (戻り値 1 = 変更あり)。 これで **Step 3・4・5 の検知と取得が一括で走る**。

---

## Step 1 — 新カードを取り込む (cards.json / sqlite)

### ⚠⚠ 最重要の落とし穴

- **`scraper.py --series <id>` は cards.json を「そのセットだけ」 で上書きする (追記でない)**。 既存 4,500+ 枚が消える。 **必ず `--all` を使う**。
- `--all` は各 series の HTML を `/tmp/onepiece_html/<id>.html` キャッシュから読む (既存弾は再 fetch せず高速)。 新弾はキャッシュが無いので net から取得。 **既存弾のテキスト改訂 (erratum) も拾いたい場合は当該 `<id>.html` も消す**。

```bash
rm -f /tmp/onepiece_html/_top.html          # 新 series 発見のため (Step 0 で消していれば不要)
.venv/bin/python scraper/scraper.py --all   # cards.json (正) + cards.sqlite (派生) を全弾で再生成
```

完了後、 新弾が入ったか・総数が想定どおり増えたかを確認 (Step 0 の確認スクリプト再実行)。 画像は後段でまとめて (Step 6)。 `--with-images` も付けられるが時間がかかるので分離推奨。

---

## Step 2 — 効果 overlay + engine 拡張 (新弾の本体・最重要)

新カードは overlay が無いと **engine 上で効果ゼロ** (バニラ扱い)。 ここが新弾対応の中心で、 **公式テキスト忠実主義** を厳守する。 詳細な記述ルール・DSL・頻出バグ類型は **`references/overlay_authoring.md` を必ず読む**。

要点 (詳細は reference):

1. **候補の種出し (任意)**: `suggest_overlay_from_cards.py` でテキストから候補を半自動生成 → `db/card_effects.suggestions.json`。 ⚠ これは**ヒューリスティックな足場であって正ではない**。 そのまま信用しない。
2. **公式テキストから忠実に記述**: 各新カードの効果を `db/card_effects.json` に手で書く。 条件節 (ライフ X 以下 / リーダー特徴 Y 等) を省略しない。 `「fallback」「自動抽出」「簡略」「近似」 禁止`。
3. **DSL に無ければ primitive を足す**: `engine/effects.py` に新プリミティブを追加し、 `tests/test_effects.py` にテストを足す。 新トリガーが要れば engine 側も拡張 (= 「engine の更新」)。
4. **本当に表現不能な時だけ**: `{"_unimplemented": "..."}` か `_fidelity_note` で**公式テキストを残してマーク**。 空近似で誤魔化さない。
5. ルール裁定は `onepiece-tcg-rules` スキル + `db/faq/cardqa_*.json` を grep して確認。

全カード 4,518 枚は過去に `_unimplemented = 0` / audit sev≥3 = 0 を達成済み。 **新弾追加でこの基準を割らないこと** がゴール (Step 3 で機械的に担保)。

---

## Step 3 — 監査ゲート (忠実度 + 正しさを機械で担保)

新カードの overlay を書いたら、 既存の audit 群を全部 green にする (= 新弾分の漏れ・矛盾・未実装を洗い出す):

```bash
.venv/bin/python scripts/audit_overlay_vs_faq.py        # overlay vs FAQ 突合 (sev>=3 = 0 が基準)
.venv/bin/python scripts/verify_overlay_vs_cardqa.py    # cardqa 効果マーカー vs overlay (missing = 0)
.venv/bin/python scripts/audit_engine_strictness.py     # engine 厳密化 10 項目 (10/10)
.venv/bin/python scripts/smoke_test_card_effects.py     # 全カード効果を最小ステートで発火
.venv/bin/pytest                                        # 全テスト (新 primitive のテスト含む)
```

- `db/audit_acknowledged.json` は intrinsic な除外リスト (新弾で正当な intrinsic が出たら追記)。
- `db/overlay_audit.{md,json}` に結果が出る。 新弾起因の sev≥3 / `_unimplemented` をゼロに戻す。

---

## Step 4 — FAQ / cardqa / 禁止リスト (大半は自動)

`check_official_updates.py` (Step 0) が変更を検知すると **自動で再 scrape** する:

- FAQ/cardqa 変更 → `scrape_official_faq.py` を内部実行 → `db/faq/*.json` 更新。
- 禁止リスト変更 → `scrape_official_banlist.py` を内部実行 → `db/banlist/master.json` 更新。

やること:
1. `git diff db/faq/ db/banlist/master.json` で差分を確認。
2. ルール/Q&A が変わったら **`onepiece-tcg-rules` スキルの `last_checked` を更新**、 engine 仕様に影響するなら同 SKILL の §17 表も更新。
3. 個別に取り直したい時: `scripts/scrape_official_faq.py` / `scripts/scrape_official_banlist.py` / `scripts/check_rules_update.py`。

---

## Step 5 — レギュレーション確認

スタンダード合法性は `engine/deck.py` の `_check_standard_block` が判定: **`block_icon >= banlist["standard_min_block"]` (既定 2)**。 新弾の `block_icon` は scrape で入る。

1. 新禁止リストで `standard_min_block` やバン/制限/禁止ペアが変わっていないか (Step 4 の diff)。
2. 既存メタデッキ等が新禁止リストでまだ合法か検証:

```bash
.venv/bin/python - <<'PY'
import glob
from engine.deck import CardRepository, DeckList
repo = CardRepository.from_json("db/cards.json")
for p in sorted(glob.glob("decks/*.json")):
    if ".analysis." in p or ".target_v" in p:   # 分析/生成スクラッチは除外
        continue
    try:
        dl = DeckList.from_json(p, repo)      # path を直接渡す
    except Exception as e:
        print(p, "LOAD ERR", e); continue
    probs = dl.validate()                     # banlist=None で db/banlist/master.json を自動ロード
    if probs:
        print(p, probs)
PY
```

新禁止リスト下で違反になったデッキ (禁止ペア等) は `decks/_archive/` へ退避し、 代替が無いアーキタイプは matrix から除外する。

---

## Step 6 — 下流 (任意・重い。 必要に応じて)

- **画像**: 新弾分をキャッシュ。 `scripts/cache_deck_images.py` (デッキで使う分) か `scripts/cache_all_images.py` (全件、 30〜60分)。 web は `web/public/cards/` を優先し未キャッシュは公式 CDN フォールバックなので必須ではない。
- **メタデッキ更新**: 新弾は環境を変える。 `scripts/scrape_cardrush_decks.py` → `scripts/select_cardrush_representatives.py` (CLAUDE.md の「メタデッキ更新」 参照)。 取得レシピは新禁止リストで validate。
- **matrix 再計算 (重)**: メタが変わったら `scripts/compute_matchup_matrix.py --ai-mode exploitbeam --workers 8 --n-games 20` (~80分)。 ⚠ 配備 AI の手が変わる engine 変更後にも要再計算。
- **一括**: `scripts/refresh_all.py` が「公式チェック → cardrush 再 scrape → 代表選出 → matrix → 学習診断」 を束ねる。 ⚠ **`refresh_all.py` はカード scrape を含まない** (Step 1 は別途必須)。

---

## Step 7 — 検証してコミット

- 変更前に `git status`。 default ブランチ上ならまず作業ブランチを切る。
- 論理単位でコミット (例: ①カード scrape、 ②overlay+engine、 ③メタ/matrix)。 CLAUDE.md のコミット規約に従う。
- コミット前ゲート: Step 3 の audit/pytest が全 green、 `cd web && npx tsc --noEmit` (UI 触ったら)。

---

## 完了チェックリスト

- [ ] `cards.json` に新弾が入り総数が想定どおり (Step 0 確認スクリプト)
- [ ] 新カードの overlay を公式テキスト忠実に記述、 `_unimplemented` 不要分はゼロ
- [ ] audit 5 種 + pytest 全 green (sev≥3 = 0、 cardqa missing = 0、 strictness 10/10)
- [ ] FAQ/cardqa/banlist の diff 確認、 `onepiece-tcg-rules` の last_checked 更新
- [ ] レギュレーション: 新 banlist 反映、 既存デッキの合法性確認
- [ ] (必要なら) 画像 / メタデッキ / matrix 更新
- [ ] 論理単位でコミット
