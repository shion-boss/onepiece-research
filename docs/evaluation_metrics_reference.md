# 対戦 AI が評価に使っている指標 — 人間確認用リファレンス

> 2026-07-03。 「AI が盤面の何を見て手を選んでいるか」 を人間が監査するための一覧。
> ohtsuki 要望(「自分の手札のカード種類 / 相手の手札枚数 / サーチで中身バレした相手の特定カード」等)。
> 正は engine コード(`engine/gbm_value.py` = 学習 value、 `engine/eval.py` = board_eval)。
> ⚠ この doc は snapshot。 feature 追加時は同時に更新すること。

## 0. 評価は 2 系統ある

| 系統 | 実体 | 用途 | 何で決まるか |
|---|---|---|---|
| **学習 value (GBM)** | `engine/gbm_value.py` の `features()` + `db/value_gbm_<deck>.pkl` | **配備 ExploitBeam の葉評価**(= 実際に手を選ぶ主役) | 下記 feature ベクトル → GBM が P(win) を予測 |
| **board_eval (ヒューリスティック)** | `engine/eval.py` の重み付き指標(base ~40 + 交互作用 30 + leader 効果 5) | value 未配備 deck の degrade / 一部探索の補助 / 悪手診断 | 下記の各指標 × 手調整の重み(3層 hierarchical) |

**配備 AI(あなたが戦う相手)= 学習 value が主。** board_eval は fallback と診断が主用途。
以下、 両方の「見ている指標」 を列挙する。

---

## 1. 学習 value (GBM) が見る feature

value は **自分視点(me)と相手視点(opp)の差分 + 生値** を入力にする。 バージョンで拡張(後方互換、
配備 pkl の次元で自動判別)。 **配備 = v6(38)基準、 一部は block_residual(v11 補正)**。

### base(v1、 17列)= 盤面の量
| feature | 意味 | 情報源 |
|---|---|---|
| d_life / my_life / opp_life | ライフ差・各自ライフ | 公開 |
| d_field_count / my_field_count / opp_field_count | 場のキャラ枚数差・各自 | 公開 |
| d_field_power / my_field_power / opp_field_power | 場の総パワー差・各自 | 公開 |
| **d_hand / my_hand / opp_hand** | **手札枚数差・各自手札枚数** ← 「相手の手札の枚数」✅ | 枚数は公開 |
| d_don | 総 DON 差 | 公開 |
| d_blocker | ブロッカー数差 ⚠ v6 までは **rested を数えない**(v11 で修正) | 公開 |
| d_attached_don | 付与 DON 差 | 公開 |
| d_active_chara | アクティブ(攻撃可能)キャラ数差 | 公開 |
| turn | ターン番号 | 公開 |

### v2(+4 = 21列)= レース + 防御資源
| my_lethal / opp_lethal | 各自の lethal(致死打点)見積 | lethal_estimate |
| **my_counter / opp_counter** | **各自手札の counter 値総量**(= 防御資源) | ⚠ 下記「隠匿情報」参照 |

### v5/v6(+13/+4 = 34/38列)= 相手 leader 理解(配備基準)
- **opp_<tag> 13列**: 相手 leader の archetype tag(aggro / control / big_finisher / draw_engine /
  ramp / counter_pump / defensive_buff_low_life 等、 `leader_profiles.json`)。 = 「相手が誰か・何をする deck か」。
- **ix_* 4列(v6 の肝)**: 相手 tag × 盤面 の**交互作用**(候補手ごとに変わる selection-relevant 信号):
  ix_opp_buff_active / ix_opp_life_fed_draw / ix_opp_counter_threat / **ix_opp_finisher_armed**(相手 active DON = alpha strike の構え)。

### v11(+3 = 41列)= 防御保持の意思決定(2026-07-03、 block_residual で配備)
| **me_avail_blocker** | **unrested(実際に防御できる)ブロッカー数** ← ブロッカーで殴ると減る(v6 の穴を修正) | 公開 |
| **ix_incoming_unblocked** | max(0, 相手 active 攻撃役 − 自 avail_blocker) = 次ターン通る攻撃見込み | 公開 |
| **ix_deck_threat_exposure** | 相手デッキの速攻/aggro belief(`opp_aggro_threat.json`) / (1+avail) ← 「相手デッキに速攻がいるか」 | belief(相手 leader から推定) |

> ⚠ **未配備の scaffold**: v3(raw DON)/ v4(deck engine 密度)/ v7(balance)/ v8(相手 role)/
> v10(自 role)。 A/B で有意差なく凍結。 詳細は各 FEATURE_KEYS のコメント。

---

## 2. board_eval が見る指標(ヒューリスティック、 `eval.py`)

自(me)− 相手(opp)の差 × 重み。 主要 base 指標(`metrics` list より):

### 盤面の量
life / field_count / field_power / hand / don / blocker / attached_don / active_chara / stage_count / stage_value / trash_count

### レース・致死
lethal / next_turn_lethal(相手が次ターン refresh 後に持つ lethal)/ lethal_risk_diff / deck_finisher(山の決定力)/ life_trigger(ライフのトリガー価値)

### 手札の質(= 「自分の手札のカードの種類」に相当)
| **hand_quality** | 手札全体の役割質スコア | ← 手札の中身を role 別に評価 ✅(部分) |
| **finisher_in_hand_count** | 手札のフィニッシャー枚数 | |
| **self_counter_in_hand_total** | 手札の counter 総量 | |
| **dead_card_in_hand** | 今腐っているカード数 | |
| **removal_threat_count** | 手札の除去札数 | |
| chara_quality | 場キャラの質 | |

### 相手情報(= 「相手の手札」「中身バレ」)
| **opp_hand_threat** | 相手手札の**隠匿脅威**推定(hand_estimator、 見えない手札の危険度) | ← 相手手札の中身を belief で推定 ✅ |
| **known_finisher_count_in_hand** | 相手手札で**中身バレしたフィニッシャー数**(`known_hand_card_ids`) | ← **「サーチで中身バレした相手の特定カード」✅** |
| active_blocker_count | 相手の active ブロッカー数 | |
| opp_next_lethal | 相手の次ターン致死 | |

### テンポ / DON / 情報
don_reserve(counter-event 用リザーブ)/ tempo_lost_total(使い残し DON)/ cards_drawn_total /
cards_played_total / dons_used_total / hand_log / field_exposure / static_cost_reduction_total /
playable_cost_match / rush_count / double_attack_count / keyword_taunt_count / ko_immune_count

### ターン文脈
is_first_player / is_my_turn / turn_number_normalized

### 交互作用 30(`W_INT_*`)= 「状況の組み合わせ」
例: opp_lethal_no_counter(相手致死 × 自分カウンター無し)/ low_life_no_blocker /
have_removal_arsenal_opp_strong(除去を持ち × 相手が強い)/ ramp_finisher_combo /
opp_hidden_threat_high / exposed_finisher / aggressive_window_open 等。 = 単指標でなく
「この条件が同時に成立すると危険/好機」 を明示。

### leader 効果 flag 5(category I)
自 leader 固有効果 × state 条件(= 起動好機か)を 5 個。

---

## 3. 隠匿情報(imperfect info)の扱い

- **自分の手札 = 完全公開**(自分のものなので当然)。
- **相手の手札 = 原則隠匿**。 ただし 2 経路で部分的に見える:
  1. **`Player.known_hand_card_ids`**(`core.py:530`)= **サーチ/公開効果で中身バレした特定カード**を確定情報として記録。
     → board_eval が `opp_known_finisher_count` / hand_estimator が確定 counter として使用。 **= あなたの例、 捕捉済み**。
  2. **`hand_estimator`** = 見えない残りを **belief(相手 leader → デッキ prior)** で推定(expected_counter_total /
     probability_of_blocker_in_hand)。 known は確定、 unknown は確率で埋める。
- **相手の山札 = 隠匿**、 belief(`opponent_deck_priors.json`)で「積まれやすいカード」を推定。

---

## 4. あなたの例の捕捉状況(直接回答)

| あなたの挙げた指標 | 学習 value (GBM) | board_eval | 判定 |
|---|---|---|---|
| 自分の手札のカードの**種類** | my_hand(枚数)/ my_counter のみ = **粗い** | hand_quality / finisher / counter / dead / removal で role 別 = ✅部分 | ⚠ role 別はあるが「種類の内訳」まではない |
| 相手の**手札の枚数** | opp_hand ✅ | hand ✅ | ✅ 捕捉 |
| サーチで**中身バレした相手の特定カード** | ❌ **明示 feature 無し** | opp_known_finisher_count ✅ + hand_estimator で確定 counter | ⚠ **board_eval のみ。 学習 value に無い(gap)** |

---

## 5. 弱い / 抜けている指標(改善候補)

1. **学習 value に「中身バレした相手カード」feature が無い** ← 最有力 gap。 engine は `known_hand_card_ids` を
   持つのに value(v11)に渡していない。 = **v12 候補**: opp_known_finisher / opp_known_removal / opp_known_counter を feature 化。
2. **自分の手札の「種類の内訳」が粗い**。 value は枚数と counter 総量のみ。 role 別ヒストグラム(finisher/removal/
   ramp/draw/blocker の手札内枚数)を value feature 化する余地。
3. **相手の山札に残る脅威**(belief)は v11 の deck_threat_exposure(速攻のみ)止まり。 除去・カウンター・フィニッシャーの
   belief も threat feature 化できる(= [[project_opponent_deck_belief_model]] の value 配線)。
4. **中身バレの鮮度/経路**(いつ・どうバレたか)は未追跡。

> **これらは block_residual の枠組み(配備 value を土台に補正だけ足す)で安全に検証可能** —— 効けば残す、
> 効かねば hard floor で無害。 次の feature 実験はこの枠で。
