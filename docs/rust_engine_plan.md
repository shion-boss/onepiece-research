# Rust エンジン計画 — self-play 高速ミラー + 差分同期

> 2026-07-29 着手。 Python engine を正 (reference) とし、 Rust を self-play 専用の高速ミラーとして
> 両運用する。 目的 = policy 蒸留ループ (AlphaZero 型 Expert Iteration) を **この 16-core PC で
> コツコツ回せる状態**にすること。

## なぜ Rust が必須か (戦略的根拠)

このセッションで確立した事実 ([[project_rollout_beats_beam]]):

1. **rollout > beam +30pt = 成長勾配は実在**。 rollout は policy 改善オペレータ (rollout(π)>π)
   → 蒸留 → 反復で超人まで登れる梯子が実在する。
2. **蒸留は feature-value では天井** (GBM も NN も v14 で ~31-39%、 model でなく input が天井)。
   破るには生盤面 NN (学習表現) + 大量の先読みデータ = scale。
3. **律速は self-play の CPU** (rollout 教師 = 1手~1分、 1game 20-30分)。 GPU でなく CPU 並列度。
4. **Rust で engine が 30-100x** → 1 iteration が「16core で 2日」→「1-2時間」。
   = 分散 (Phase 9、 1000台) を待たずに **単一 PC でコツコツ Expert Iteration が回る**。

⇒ Rust は特定の蒸留手法の成否に関係なく、 全 self-play 研究・matrix・テストを 30-100x する
インフラ投資。 早期着手の合理性がある。

## アーキテクチャ: 両運用 (Python=正 / Rust=高速ミラー)

```
Python engine (engine/*.py)          Rust engine (rust_engine/)
━━━━━━━━━━━━━━━━━━━━━━            ━━━━━━━━━━━━━━━━━━━━━━
・カード効果 authoring/監査 (正)      ・self-play データ生成の内ループ専用
・DSL の reference 実装                ・NN 推論とバッチ連携
・API / web / 対人プレイ               ・(Phase R4 で AI も内包 → 完全 Rust ループ)
・テスト / deckbuilder / 分析
        ↘                    ↙
   card_effects.json (効果 = 共有データ、 両 engine が読む)
        ↘                    ↙
   差分ハーネス: 同一 seed/action → canonical digest 一致を assert
```

**Python は捨てない。** 対人・API は速度不要なので Python のまま。 Rust は「大量に回す self-play」だけ担う。

## 差分同期の仕組み (= 両方同じ状態を保つ機構、 R0 で構築済)

「両方同じ状態を保ち続ける」ための中核。 **これが無いと盲目移植になる。**

- `engine/state_snapshot.py`: **canonical state serializer**。 dataclass introspection で全 field 自動列挙
  (InPlay 71 field でも漏れなし)。 正準化規約:
  - `instance_id` 除外 (グローバル採番タグ = ゲーム毎/言語間で不一致、 状態の意味は card_id+flag+zone位置で決まる)
  - set→sorted / dict→key sorted / CardDef→card_id / rng・log・overlay・hook 除外
  - `state_digest()` = canonical の sha1、 `diff_canonical()` = 乖離 field の pinpoint
- `engine/core.py:reset_iid()`: instance_id カウンタを game 毎 reset → 同一 seed で同一 iid 列 = 決定論。
- `scripts/engine_diff_trace.py`: 1game 再生し各 action 後の digest 列を記録 (trace)。 **Python engine の
  決定論を確認済** (同一 seed → 全 run bit 一致 = Rust が満たすべき ground truth)。 将来 Rust engine が
  同じ seed/deck/action 列で同じ digest 列を出すか comparator で照合、 乖離時は `diff_canonical` で
  「どの field / どの primitive で分岐したか」を pinpoint。
- `rust_engine/src/state.rs`: 同じ正準化規約で serde serialize (Python と突合可能)。

## 段階移植 plan

| Phase | 内容 | 状態 |
|---|---|---|
| **R0** | 差分ハーネス (canonical/digest/決定論確認) + Rust scaffold (cargo+PyO3+maturin、 build→import→serialize 疎通) | ✅ 済 (2026-07-29) |
| **R1a** | **状態モデル完全 port (state.rs 全147field) + fidelity 実証**。 Python `full_dump` → Rust `canonical_digest` が Python `state_digest` と **15/15 状態で bit 一致** (複数 seed/マッチ/手数0-40)。 = Rust 状態表現が忠実 | ✅ 済 (2026-07-29) |
| **R1b** | cards.json/deck ロード + `setup_game` を Rust に (RNG = Python MT19937 互換 or Python から初期状態受領) | 未 |
| **R2** | ルール port (`game.py`: legal_actions/apply_action/turn 進行/戦闘/ライフ)。 action を canonical エンコード (card_id+zone位置、 iid 非依存) して両 engine で replay、 全 step digest 一致 | 🔄 着手: **AttachDon(Leader/Character)= 128/128 一致 (2026-07-29)**。 残 = EndPhase/phase進行, PlayCharacter/Event, Attack/戦闘, ActivateMain。 ⚠ 効果を伴う action は R3 (effects) と interleave |
| **R3** | DSL インタプリタ (`effects.py` 312 primitive、 13.7k 行) を **self-play 頻出順**に移植。 各 primitive 追加毎に該当カードの差分テスト。 頻出~80 primitive で 99% のゲームがカバーされる想定 → 早期に使える高速 engine | 未 (本体) |
| **R4** | AI (beam/value: plan_search/exploit_beam/gbm_value) を Rust に → self-play を Rust 内で完結 (30-100x)。 ⚠ ルールは bit 一致必須だが AI は heuristic なので近似同値で可 | 未 |

**⚠ 工数は Claude 実装ベースで実測する ([[feedback_estimation_claude_basis]]、 human-dev 見積りはノイズ)**。
実測 (2026-07-29): **R1a (状態モデル全147field port + fidelity 実証) = 1 セッション内**(core.py 読み + state.rs
翻訳 + full_dump/canonical_digest + build-test-fix 3 回)。 friction は予想通り「field 完全性 + serialization 規約
一致」で、 **全て機械的 + 差分ハーネスが自動採点** = grind。 → R2/R3 も同様に「翻訳 + 差分テスト」の grind、
借用チェッカ (mutation の所有権設計) が唯一の非機械的部分。 R3 は 312 primitive の volume だが並列化可能。

## dual-fix: クラウド エンジン修正ルーティンを両 engine 対応に

`optcg-effect-bugfix` (クラウド cron) が engine を直す時、 両方に反映する仕組み:

- **データ修正 (`card_effects.json`)**: 両 engine が同じ JSON を読む → **自動的に両対応**。 ルーティン変更不要。
  (実測: 修正の大半はこれ = OP11-046 等)
- **Python DSL primitive 修正 (`effects.py`)**: 該当 primitive が **Rust に既に移植済 (R3+)** の場合のみ Rust 側も
  要修正。 **差分テストが gate**: primitive 修正後に `engine_diff_trace` を該当カードで走らせ、 Python vs Rust の
  digest が乖離したら「Rust 側が古い」= 修正が要る、 と自動検出。
- **現状 (R0)**: Rust に primitive が無い → **dual-fix 対象はまだ存在しない**。 R3 で primitive 移植を始めた時点で
  ①差分テストを CI gate 化 ②cron に「primitive 修正後の差分チェック + Rust 乖離を `_pending_review` に escalate」を追加。
  → **R3 着手時の TODO** (それまでは全修正がデータ or Python-only で乖離不能)。

## 次アクション

1. **[gate] robustness sweep** (実行中 b7c1eucav): rollout>beam が複数マッチで robust か。 robust 確認が
   R1+ 本格投資の前提。
2. robust なら R1 (状態モデル完全 port + setup_game) に着手。 差分ハーネスで初期状態一致を積み上げる。

関連: [[project_rollout_beats_beam]] / [[project_search_route_pivot]] / [[project_leader_as_progression_unit]] (分散の受け皿) / docs/ROADMAP.md Phase 9。
