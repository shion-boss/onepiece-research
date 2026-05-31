# LLM overlay 監査素材: tcgportal_op13_luffy

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP13-001
- name=モンキー・Ｄ・ルフィ / category=LEADER / power=5000 / counter=- / attribute=打 / color=赤/緑 / features=超新星/麦わらの一味

### 公式テキスト
> 【ドン‼×1】【相手のアタック時】自分のアクティブのドン‼が5枚以下の場合、自分のドン‼を任意の枚数レストにできる。レストにしたドン‼1枚につき、このリーダーか自分の特徴《麦わらの一味》を持つキャラ1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "【ドン!!×1】【相手のアタック時】自分のアクティブのドン‼が5枚以下の場合、自分のドン‼を任意の枚数レストにできる。レストにしたドン‼1枚につき、このリーダーか自分の特徴《麦わらの一味》を持つキャラ1枚までを、このバトル中、パワー+2000",
    "when": "opp_attack",
    "if": {
      "self_attached_don_ge": 1,
      "self_don_active_le": 5
    },
    "do": [
      {
        "rest_self_don_for_battle_buff_per_don": {
          "target": "self_leader",
          "amount_per_rest": 2000,
          "max": 5
        }
      }
    ]
  }
]
```

## EB04-002
- name=ジュエリー・ボニー / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=特 / color=赤 / features=エッグヘッド/ボニー海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から4枚を見て、「ジュエリー・ボニー」以外の特徴《エッグヘッド》か《麦わらの一味》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "ジュエリー・ボニー 登場時: デッキ上4枚見てエッグヘッド/麦わら1枚公開手札追加",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "feature_in": [
              "エッグヘッド",
              "麦わらの一味"
            ],
            "exclude_name": "ジュエリー・ボニー"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  }
]
```

## OP13-016
- name=モンキー・Ｄ・ガープ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=打 / color=赤 / features=海軍

### 公式テキスト
> 【登場時】自分のリーダーが「サボ」か「ポートガス・D・エース」か「モンキー・Ｄ・ルフィ」の場合、自分のデッキの上から4枚を見て、コスト3以上のカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-016 ガープ 登場時: サボ/エース/ルフィ リーダーで デッキ上4を見て cost3+ を1枚手札",
    "when": "on_play",
    "if": {
      "leader_name_in": [
        "サボ",
        "ポートガス・D・エース",
        "モンキー・D・ルフィ"
      ]
    },
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "cost_ge": 3
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  }
]
```

## OP14-031
- name=ナミ / category=CHARACTER / cost=4 / power=2000 / counter=1000 / attribute=特 / color=緑 / features=FILM/麦わらの一味

### 公式テキスト
> 【ブロッカー】【登場時】相手のコスト8以下のキャラ2枚までを、レストにする。その後、このターン終了時、自分のドン‼5枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP14-031 on_play: 相手のコスト8以下のキャラ2枚までを、レストにする。その後、このターン終了時、自分のドン‼5枚までを、アクティブにする。",
    "when": "on_play",
    "do": [
      {
        "untap_don": 5
      },
      {
        "rest": {
          "target": "one_opponent_character_cost_le_8",
          "count": 2
        }
      }
    ]
  }
]
```

## OP13-027
- name=サンジ / category=CHARACTER / cost=5 / power=7000 / counter=- / attribute=打 / color=緑 / features=FILM/麦わらの一味

### 公式テキスト
> 【登場時】自分のドン‼2枚までを、アクティブにする。【自分のターン終了時】自分のリーダーが特徴《FILM》か《麦わらの一味》を持つ場合、自分のドン‼1枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "サンジ (黄 cost5) 登場時: ドン2活性化",
    "when": "on_play",
    "do": [
      {
        "untap_don": 2
      }
    ]
  },
  {
    "_text": "ターン終了時 (FILM/麦わら): ドン1活性化",
    "when": "end_of_turn",
    "do": [
      {
        "untap_don": 1
      }
    ],
    "if": {
      "leader_features_any": [
        "FILM",
        "麦わらの一味"
      ]
    }
  }
]
```

## OP08-036
- name=エレクトリカルルナ / category=EVENT / cost=3 / power=- / counter=- / color=緑 / features=ミンク族
- **trigger**: 【トリガー】相手のキャラ1枚までを、レストにする。

### 公式テキスト
> 【メイン】相手のレストのコスト7以下のキャラすべては、次の相手のリフレッシュフェイズでアクティブにならない。

### 現行 overlay
```json
[
  {
    "_text": "OP08-036 エレクトリカルルナ メイン: 相手レスト cost7以下 全員 stay_rested_next_refresh",
    "when": "main",
    "do": [
      {
        "stay_rested_next_refresh": "all_opponent_rested_characters_le_7cost"
      }
    ]
  },
  {
    "_text": "OP08-036 エレクトリカルルナ トリガー: 相手キャラ1枚 rest",
    "when": "trigger",
    "do": [
      {
        "rest": {
          "type": "one_opponent_character_filtered",
          "filter": {
            "cost_le": 7,
            "rested": true
          }
        }
      }
    ]
  }
]
```

## OP05-038
- name=舞踏石 / category=EVENT / cost=2 / power=- / counter=- / color=緑 / features=ドンキホーテ海賊団
- **trigger**: 【トリガー】相手のリーダーかコスト3以下のキャラ1枚までを、レストにする。

### 公式テキスト
> 【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。その後、自分の手札1枚を捨ててもよい。そうした場合、自分のドン!!3枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP05-038 counter: 自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。その後、自分の手札1枚を捨ててもよい。そうした場合、自分のドン!!3枚までを、アクティブにする",
    "when": "counter",
    "do": [
      {
        "untap_don": 3
      },
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 4000,
          "duration": "battle"
        }
      }
    ]
  },
  {
    "_text": "OP05-038 trigger: 相手のリーダーかコスト3以下のキャラ1枚までを、レストにする。",
    "when": "trigger",
    "do": [
      {
        "rest": "one_opponent_inplay_cost_le_3"
      }
    ]
  }
]
```

## OP14-022
- name=ウソップ / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=射 / color=緑 / features=FILM/麦わらの一味

### 公式テキスト
> 【自分のターン終了時】自分のリーダーが特徴《FILM》か《麦わらの一味》を持つ場合、自分のドン‼2枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "ウソップ (緑 cost4) ターン終了時 (FILM/麦わら): ドン2活性化",
    "when": "end_of_turn",
    "do": [
      {
        "untap_don": 2
      }
    ],
    "if": {
      "leader_features_any": [
        "FILM",
        "麦わらの一味"
      ]
    }
  }
]
```

## OP13-118
- name=モンキー・Ｄ・ルフィ / category=CHARACTER / cost=6 / power=7000 / counter=- / attribute=打 / color=緑 / features=魚人島/超新星/麦わらの一味

### 公式テキスト
> 【ダブルアタック】【登場時】自分のリーダーが多色の場合、自分のドン‼4枚までを、アクティブにする。その後、自分は、このターン中、元々のコスト5以上のキャラカードを登場できない。

### 現行 overlay
```json
[
  {
    "_text": "ルフィ cost6 ダブルアタック+登場時: 多色なら ドン4活性化",
    "when": "on_play",
    "do": [
      {
        "untap_don": 4
      }
    ]
  }
]
```

## OP13-040
- name=強ェとわかってんだから… 始めから全開だ!!! / category=EVENT / cost=1 / power=- / counter=- / color=緑 / features=超新星/麦わらの一味

### 公式テキスト
> 【メイン】自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。【カウンター】自分のリーダーを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-040 main: 自分のドン‼2枚をレストにできる：相手のレストのコスト7以下のキャラ2枚までは、次の相手のリフレッシュフェイズでアクティブにならない。",
    "when": "main",
    "do": [
      {
        "stay_rested_next_refresh": "any_opp_rested_chara_cost_le_7_n_2"
      }
    ],
    "cost": {
      "rest_self_don": 2
    }
  },
  {
    "_text": "OP13-040 counter: 自分のリーダーを、このバトル中、パワー+3000。",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 3000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## EB04-007
- name=ロロノア・ゾロ / category=CHARACTER / cost=7 / power=9000 / counter=- / attribute=斬 / color=赤 / features=エッグヘッド/麦わらの一味

### 公式テキスト
> 【登場時】自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。【起動メイン】【ターン1回】相手のパワー8000以上のキャラがいる場合、このキャラは、このターン中、【速攻：キャラ】を得る。

### 現行 overlay
```json
[
  {
    "_text": "EB04-007 on_play: 自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。",
    "when": "on_play",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "next_opp_turn_end"
        }
      }
    ]
  },
  {
    "_text": "EB04-007 起動メイン: 相手power8000+ キャラ存在で 速攻 + アクティブキャラアタック可",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      },
      {
        "give_attack_active_chara": "self"
      }
    ],
    "if": {
      "opp_chara_filtered_count_ge": {
        "filter": {
          "power_ge": 8000
        },
        "count": 1
      }
    }
  }
]
```

## ST21-003
- name=サンジ / category=CHARACTER / cost=2 / power=3000 / counter=2000 / attribute=打 / color=赤 / features=麦わらの一味

### 公式テキスト
> 【登場時】自分のパワー6000以上の特徴《麦わらの一味》を持つキャラ1枚までを選ぶ。相手は、このターン中、選んだキャラがアタックする場合【ブロッカー】を発動できない。

### 現行 overlay
```json
[
  {
    "_text": "ST21-003 on_play: 自分のパワー6000以上の特徴《麦わらの一味》を持つキャラ1枚までを選ぶ。相手は、このターン中、選んだキャラがアタックする場合【ブロッカー】を発動できない。",
    "when": "on_play",
    "do": [
      {
        "prevent_blocker_for_attacker": {
          "target": {
            "type": "one_self_chara_filtered",
            "filter": {
              "category": "CHARACTER",
              "power_ge": 6000,
              "feature": "麦わらの一味"
            }
          }
        }
      }
    ]
  }
]
```

## OP15-035
- name=ラブーン / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=打 / color=緑 / features=動物

### 公式テキスト
> 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに自分のカード2枚をレストにできる。

### 現行 overlay
```json
[
  {
    "_text": "OP15-035 replace_ko: 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに自分のカード2枚をレストにできる。",
    "when": "replace_ko",
    "if": {
      "target": "any_self_chara",
      "target_power_le": 7000,
      "by_opp_effect": true
    },
    "do": [
      {
        "rest_self_cards": 2
      }
    ]
  }
]
```

## OP13-028
- name=シャンクス / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=斬 / color=緑 / features=FILM/四皇/赤髪海賊団

### 公式テキスト
> 【登場時】自分のドン‼すべてを、アクティブにする。その後、自分は、このターン中、手札からカードをプレイできない。

### 現行 overlay
```json
[
  {
    "_text": "OP13-028 on_play: 自分のドン‼すべてを、アクティブにする。その後、自分は、このターン中、手札からカードをプレイできない。",
    "when": "on_play",
    "do": [
      {
        "untap_don": "all"
      },
      {
        "block_chara_play_turn": true
      }
    ]
  }
]
```

## OP12-030
- name=ジュラキュール・ミホーク / category=CHARACTER / cost=8 / power=8000 / counter=- / attribute=斬 / color=緑 / features=シッケアール王国/王下七武海

### 公式テキスト
> 【ブロッカー】【登場時】自分のドン‼4枚までを、アクティブにする。その後、自分は、このターン中、元々のコスト7以上のキャラカードを登場できない。

### 現行 overlay
```json
[
  {
    "_text": "OP12-030 on_play: 自分のドン‼4枚までを、アクティブにする。その後、自分は、このターン中、元々のコスト7以上のキャラカードを登場できない。",
    "when": "on_play",
    "do": [
      {
        "untap_don": 4
      }
    ]
  }
]
```
