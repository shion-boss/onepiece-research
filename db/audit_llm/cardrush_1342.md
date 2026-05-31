# LLM overlay 監査素材: cardrush_1342

カード数: 17

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP14-060
- name=ドンキホーテ・ドフラミンゴ / category=LEADER / power=5000 / counter=- / attribute=特 / color=紫 / features=王下七武海/ドンキホーテ海賊団

### 公式テキスト
> 【相手のアタック時】【ターン1回】ドン‼-1：自分のリーダーか特徴《ドンキホーテ海賊団》を持つキャラ1枚を選ぶ。選んだカードにアタックの対象を変更する。

### 現行 overlay
```json
[
  {
    "_text": "紫ドフラミンゴ 相手アタック時 [DON-1, ターン1回]: リーダー or 特徴《ドンキホーテ海賊団》 キャラ 1 枚 を 選び アタック対象 変更",
    "when": "opp_attack",
    "do": [
      {
        "redirect_attack": {
          "candidates": [
            "self_leader",
            {
              "type": "all_self_chara_filtered",
              "filter": {
                "feature": "ドンキホーテ海賊団"
              }
            }
          ]
        }
      }
    ],
    "cost": {
      "once_per_turn": true,
      "pay_don": 1
    }
  }
]
```

## OP14-069
- name=ドンキホーテ・ドフラミンゴ / category=CHARACTER / cost=10 / power=10000 / counter=- / attribute=特 / color=紫 / features=王下七武海/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】ドン‼-3：以下から1つを選ぶ。・自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、相手のコスト8以下のキャラ1枚までを、KOする。・相手のコスト7以下のキャラ3枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。

### 現行 overlay
```json
[
  {
    "_text": "OP14-069 【登場時】ドン‼-3：以下から1つを選ぶ。・自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、相手のコスト8以下のキャラ1枚までを、KOする。・相手のコスト7以下のキャラ3枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。",
    "when": "on_play",
    "cost": {
      "pay_don": 3
    },
    "do": [
      {
        "choice_effect": {
          "optional": true,
          "options": [
            {
              "label": "コスト8以下のキャラ 1 枚 KO",
              "if": {
                "leader_feature": "ドンキホーテ海賊団"
              },
              "do": [
                {
                  "ko": "one_opponent_character_cost_le_8cost"
                }
              ]
            },
            {
              "label": "コスト7以下キャラ 3 枚 まで 次相手 end まで レスト不可",
              "do": [
                {
                  "set_cannot_rest": {
                    "target": "any_opponent_character_le_7cost",
                    "count": 3,
                    "duration": "next_opp_turn_end"
                  }
                }
              ]
            }
          ]
        }
      }
    ],
    "if": {
      "leader_feature": "ドンキホーテ海賊団"
    }
  }
]
```

## OP10-071
- name=ドンキホーテ・ドフラミンゴ / category=CHARACTER / cost=8 / power=9000 / counter=- / attribute=特 / color=紫 / features=王下七武海/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】ドン‼-1：自分の手札からコスト5以下の特徴《ドンキホーテ海賊団》を持つキャラカード1枚までを、登場させる。【相手のアタック時】【ターン1回】自分のドン‼1枚をレストにできる：ドン‼デッキからドン‼1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "OP10-071 ドフラ 登場時: ドン-1 → 手札 cost5以下ドフラ海賊団キャラ登場",
    "when": "on_play",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "feature": "ドンキホーテ海賊団",
            "cost_le": 5
          },
          "limit": 1
        }
      }
    ]
  },
  {
    "_text": "OP10-071 ドフラ 相手アタック時: ドン1レスト → ドンデッキからドン1アクティブ追加 (ターン1回)",
    "when": "opp_attack",
    "cost": {
      "once_per_turn": true,
      "rest_self_don": 1
    },
    "do": [
      {
        "add_don": 1
      }
    ]
  }
]
```

## OP14-061
- name=ヴェルゴ / category=CHARACTER / cost=5 / power=7000 / counter=- / attribute=打 / color=紫 / features=パンクハザード/海軍/ドンキホーテ海賊団

### 公式テキスト
> 【ターン1回】自分の特徴《ドンキホーテ海賊団》を持つキャラが相手の効果で場を離れる場合、代わりに自分の場のドン‼1枚をドン‼デッキに戻すことができる。【アタック時】ドン‼-1：相手のキャラ1枚までを、このターン中、パワー-2000。

### 現行 overlay
```json
[
  {
    "_text": "OP14-061 ヴェルゴ 置換 (ターン1回): 自ドフラ海賊団キャラが相手効果で場離れる時、 ドン1ドンデッキへ",
    "when": "replace_leave",
    "cost": [
      {
        "once_per_turn": true
      }
    ],
    "if": {
      "target": "other_self_chara",
      "target_feature": "ドンキホーテ海賊団",
      "by_opp_effect": true
    },
    "do": [
      {
        "return_self_don_to_deck": 1
      }
    ],
    "optional": true
  },
  {
    "_text": "OP14-061 ヴェルゴ アタック時: ドン-1 → 相手キャラ1 -2000 turn",
    "when": "on_attack",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -2000,
          "duration": "turn"
        }
      }
    ]
  }
]
```

## OP14-072
- name=ベビー５ / category=CHARACTER / cost=4 / power=1000 / counter=1000 / attribute=特 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【登場時】ドン‼デッキからドン‼1枚までを、アクティブで追加する。【KO時】ドン‼-1：自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP14-072 ベビー5 登場時: ドンデッキからドン1アクティブ追加",
    "when": "on_play",
    "do": [
      {
        "add_don": 1
      }
    ]
  },
  {
    "_text": "OP14-072 ベビー5 KO時: ドン-1 → デッキ上1をライフへ",
    "when": "on_ko",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  }
]
```

## OP14-074
- name=モネ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=紫 / features=パンクハザード/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。【KO時】カード2枚を引き、自分の手札1枚を捨てる。その後、ドン‼デッキからドン‼2枚までを、レストで追加する。

### 現行 overlay
```json
[
  {
    "_text": "モネ 登場時 (ドンキホーテ): ドン+1",
    "when": "on_play",
    "if": {
      "leader_feature": "ドンキホーテ海賊団"
    },
    "do": [
      {
        "add_don": 1
      }
    ]
  },
  {
    "_text": "モネ KO時: 2ドロー + ドン2追加",
    "when": "on_ko",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      },
      {
        "add_rested_don": 2
      }
    ]
  }
]
```

## OP14-071
- name=ピーカ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=打 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【自分のターン終了時】自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "ピーカ 自ターン終了時: ドンキホーテ海賊団リーダーなら add_don 1",
    "when": "end_of_turn",
    "if": {
      "leader_feature": "ドンキホーテ海賊団"
    },
    "do": [
      {
        "add_don": 1
      }
    ]
  }
]
```

## OP10-065
- name=シュガー / category=CHARACTER / cost=1 / power=1000 / counter=1000 / attribute=特 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【起動メイン】自分のドン‼1枚をレストにし、このキャラをレストにできる：自分のデッキの上から5枚を見て、特徴《ドンキホーテ海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP10-065 シュガー 起動メイン: ドン1レスト+self レストで デッキ上5見てドフラ海賊団1手札 残デッキ底",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true,
      "rest_self": true,
      "rest_self_don": 1
    },
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "ドンキホーテ海賊団"
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

## OP14-067
- name=デリンジャー / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=打 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【KO時】ドン‼デッキからドン‼1枚までを、レストで追加し、自分のデッキの上から5枚を見て、特徴《ドンキホーテ海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP14-067 デリンジャー KO時: ドンデッキからドン1レスト追加 + デッキ上5見てドフラ海賊団1手札 残デッキ底",
    "when": "on_ko",
    "do": [
      {
        "add_rested_don": 1
      },
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "ドンキホーテ海賊団"
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

## OP14-068
- name=トレーボル / category=CHARACTER / cost=5 / power=5000 / counter=2000 / attribute=特 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【相手のターン中】【ターン1回】自分の場のドン‼がドン‼デッキに戻された時、自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、ドン‼デッキからドン‼1枚までを、レストで追加する。

### 現行 overlay
```json
[
  {
    "_text": "OP14-068 トレーボル 相手ターン中 ドンが ドンデッキに戻された時: ターン1回 ドフラリーダーで ドンデッキからドン1レスト追加",
    "when": "on_self_don_returned_to_deck",
    "cost": {
      "once_per_turn": true
    },
    "if": {
      "opp_turn": true,
      "leader_feature": "ドンキホーテ海賊団"
    },
    "do": [
      {
        "add_rested_don": 1
      }
    ]
  }
]
```

## OP15-069
- name=ノラ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=打 / color=紫 / features=動物/空島

### 公式テキスト
> 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに自分の場のドン‼1枚をドン‼デッキに戻すことができる。

### 現行 overlay
```json
[
  {
    "_text": "OP15-069 ノラ 置換: 自元々パワー7000以下キャラが相手効果で場離れる時、 ドン1ドンデッキへ戻すと代替",
    "when": "replace_leave",
    "if": {
      "target": "other_self_chara",
      "target_base_power_le": 7000,
      "by_opp_effect": true
    },
    "do": [
      {
        "return_self_don_to_deck": 1
      }
    ],
    "optional": true
  }
]
```

## ST18-001
- name=ウソ八 / category=CHARACTER / cost=3 / power=3000 / counter=2000 / attribute=射 / color=紫 / features=麦わらの一味

### 公式テキスト
> 【登場時】自分の場のドン!!が8枚以上ある場合、相手のコスト5以下のキャラ1枚までを、レストにする。

### 現行 overlay
```json
[
  {
    "_text": "ST18-001 ウソ八 登場時: 自場ドン8以上で 相手 cost5以下 1枚 rest",
    "when": "on_play",
    "if": {
      "self_don_ge": 8
    },
    "do": [
      {
        "rest": "one_opponent_character_cost_le_5"
      }
    ]
  }
]
```

## OP14-063
- name=シュガー / category=CHARACTER / cost=4 / power=1000 / counter=1000 / attribute=特 / color=紫 / features=ドンキホーテ海賊団

### 公式テキスト
> 【登場時】ドン‼デッキからドン‼1枚までを、アクティブで追加する。【KO時】相手の場のドン‼が6枚以上ある場合、自分の手札からコスト5以下の特徴《ドンキホーテ海賊団》を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "シュガー 登場時: ドン+1",
    "when": "on_play",
    "do": [
      {
        "add_don": 1
      }
    ]
  },
  {
    "_text": "KO時: ドンキホーテ5以下 trash から登場",
    "when": "on_ko",
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "category": "CHARACTER",
            "feature": "ドンキホーテ海賊団",
            "cost_le": 5
          },
          "limit": 1
        }
      }
    ],
    "if": {
      "opp_don_ge": 6
    }
  }
]
```

## OP11-067
- name=シャーロット・カタクリ / category=CHARACTER / cost=8 / power=8000 / counter=- / attribute=打 / color=紫 / features=ビッグ・マム海賊団

### 公式テキスト
> 【ブロッカー】【自分のターン終了時】自分のコスト3以上の特徴《ビッグ・マム海賊団》を持つキャラ2枚までを、アクティブにする。その後、自分のドン‼デッキからドン‼1枚までを、レストで追加する。

### 現行 overlay
```json
[
  {
    "_text": "OP11-067 end_of_turn: 自分のコスト3以上の特徴《ビッグ・マム海賊団》を持つキャラ2枚までを、アクティブにする。その後、自分のドン‼デッキからドン‼1枚までを、レストで追加する。",
    "when": "end_of_turn",
    "do": [
      {
        "untap_chara": {
          "target": {
            "type": "self_chara_filtered",
            "filter": {
              "feature": "ビッグ・マム海賊団",
              "cost_ge": 3
            }
          },
          "count": 2
        }
      },
      {
        "add_rested_don": 1
      }
    ]
  }
]
```

## OP10-079
- name=神誅殺 / category=EVENT / cost=5 / power=- / counter=- / color=紫 / features=王下七武海/ドンキホーテ海賊団
- **trigger**: 【トリガー】ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 公式テキスト
> 【メイン】相手のコスト5以下のキャラ1枚までを、KOする。その後、ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "神誅殺 メイン: 相手コスト5以下KO + ドン+1",
    "when": "main",
    "do": [
      {
        "ko": "one_opponent_character_cost_le_5"
      },
      {
        "add_don": 1
      }
    ]
  },
  {
    "_text": "trigger: ドン1 アクティブ 追加",
    "when": "trigger",
    "do": [
      {
        "add_don": 1
      }
    ]
  }
]
```

## OP13-076
- name=神避 / category=EVENT / cost=- / power=- / counter=- / color=紫 / features=海賊王/ロジャー海賊団

### 公式テキスト
> 【メイン】自分のドン‼5枚をレストにできる：自分の付与されているドン‼がある場合、相手のキャラ1枚までを、このターン中、パワー-8000。【カウンター】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-076 神避 メイン: ドン-5 + 自付与ドンあり → 相手キャラ1体 -8000 turn",
    "when": "main",
    "cost": {
      "rest_self_don": 5
    },
    "if": {
      "self_attached_don_ge": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -8000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "OP13-076 神避 カウンター: 手札1捨て → 自リーダー/キャラ +3000 battle",
    "when": "counter",
    "cost": {
      "discard_hand": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 3000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## OP10-078
- name=家族を笑う者はおれが許さん…!!! / category=EVENT / cost=1 / power=- / counter=- / color=紫 / features=王下七武海/ドンキホーテ海賊団

### 公式テキスト
> 【メイン】/【カウンター】自分のデッキの上から3枚を見て、「家族を笑う者はおれが許さん…!!!」以外の特徴《ドンキホーテ海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP10-078 メイン: デッキ上3を見て ドフラ海賊団 (除く自身) 1を手札 残デッキ底",
    "when": "main",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "ドンキホーテ海賊団",
            "exclude_card_id": "OP10-078"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  },
  {
    "_text": "OP10-078 カウンター: 同上のサーチ",
    "when": "counter",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "ドンキホーテ海賊団",
            "exclude_card_id": "OP10-078"
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
