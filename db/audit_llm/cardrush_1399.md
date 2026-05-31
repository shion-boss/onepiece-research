# LLM overlay 監査素材: cardrush_1399

カード数: 16

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP15-002
- name=ルーシー / category=LEADER / power=5000 / counter=- / attribute=打 / color=赤/青 / features=ドレスローザ/革命軍

### 公式テキスト
> 【アタック時】/【相手のアタック時】自分の手札からイベントかステージカードを任意の枚数捨ててもよい。捨てたカード1枚につき、このリーダーは、このバトル中、パワー+1000。【起動メイン】【ターン1回】このターン中、自分が元々のコスト3以上のイベントを発動している場合、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "赤青ルーシー アタック時: 自リーダー +1000 (1枚捨て前提)",
    "when": "on_attack",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 1000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "赤青ルーシー 相手アタック時: 自リーダー +1000 (防御用)",
    "when": "opp_attack",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 1000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "赤青ルーシー 起動メイン: 1ドロー",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP15-053
- name=レベッカ / category=CHARACTER / cost=1 / power=- / counter=1000 / attribute=知 / color=青 / features=ドレスローザ

### 公式テキスト
> 【ドン‼×1】このキャラは【ブロッカー】を得る。【登場時】自分のデッキの上から3枚を見て、特徴《ドレスローザ》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-053 レベッカ 常在: ドン×1で 自身ブロッカー",
    "when": "on_attached_don",
    "n": 1,
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー"
        }
      }
    ]
  },
  {
    "_text": "OP15-053 レベッカ 登場時: デッキ上3を見て ドレスローザ1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "ドレスローザ"
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

## OP15-052
- name=レオ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=打 / color=青 / features=トンタッタ族/ドレスローザ

### 公式テキスト
> 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに自分のキャラ1枚を持ち主のデッキの下に置くことができる。

### 現行 overlay
```json
[
  {
    "_text": "OP15-052 replace_ko: 自分の元々のパワー7000以下のキャラが相手の効果で場を離れる場合、代わりに自分のキャラ1枚を持ち主のデッキの下に置くことができる。",
    "when": "replace_ko",
    "if": {
      "target": "any_self_chara",
      "target_power_le": 7000,
      "by_opp_effect": true
    },
    "do": [
      {
        "return_to_deck_bottom": "one_self_character_any"
      }
    ],
    "optional": true
  }
]
```

## OP15-040
- name=ヴィオラ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=特 / color=青 / features=ドレスローザ/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から3枚を見て、特徴《ドレスローザ》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-040 ヴィオラ 登場時: デッキ上3を見て ドレスローザ1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "ドレスローザ"
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

## OP10-045
- name=キャベンディッシュ / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=斬 / color=青 / features=ドレスローザ/美しき海賊団

### 公式テキスト
> 【アタック時】【ターン1回】カード2枚を引き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP10-045 キャベ アタック時 (ターン1回): 2ドロー + 1捨て",
    "when": "on_attack",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP15-006
- name=キャベンディッシュ / category=CHARACTER / cost=4 / power=4000 / counter=2000 / attribute=斬 / color=赤 / features=ドレスローザ/美しき海賊団

### 公式テキスト
> 自分のトラッシュにイベントが4枚以上ある場合、このキャラのパワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "キャベンディッシュ static: トラッシュ4枚以上で +2000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 4
    },
    "do": [
      {
        "power_pump": {
          "target": "self",
          "amount": 2000,
          "duration": "static"
        }
      }
    ]
  }
]
```

## OP09-118
- name=ゴール・D・ロジャー / category=CHARACTER / cost=10 / power=13000 / counter=- / attribute=斬 / color=赤 / features=海賊王/ロジャー海賊団

### 公式テキスト
> 【速攻】(このカードは登場したターンにアタックできる)相手が【ブロッカー】を発動した時、自分か相手のライフが0枚の場合、自分はゲームに勝利する。

### 現行 overlay
```json
[
  {
    "_text": "OP09-118 on_opp_blocker_use: ライフ0 (either) で勝利",
    "when": "on_opp_blocker_use",
    "if": {
      "life_zero_either": true
    },
    "do": [
      {
        "win_game": true
      }
    ]
  }
]
```

## OP15-046
- name=サボ / category=CHARACTER / cost=7 / power=9000 / counter=- / attribute=特 / color=青 / features=ドレスローザ/革命軍

### 公式テキスト
> 【ブロッカー】【登場時】自分のリーダーが特徴《ドレスローザ》を持つ場合、自分の手札から特徴《ドレスローザ》を持つイベント1枚までを、発動する。

### 現行 overlay
```json
[
  {
    "_text": "OP15-046 サボ 登場時: ドレスローザリーダーで 手札のドレスローザ イベ1を発動",
    "when": "on_play",
    "if": {
      "leader_feature": "ドレスローザ"
    },
    "do": [
      {
        "play_event_from_hand": {
          "filter": {
            "feature": "ドレスローザ"
          }
        }
      }
    ]
  }
]
```

## OP15-020
- name=火拳 / category=EVENT / cost=7 / power=- / counter=- / color=赤 / features=ドレスローザ/革命軍

### 公式テキスト
> 【メイン】自分のリーダーを、このターン中、パワー+3000し、相手のキャラ1枚までを、次の相手のエンドフェイズ終了時まで、パワー-8000。その後、自分の手札2枚を捨ててもよい。そうした場合、相手のパワー0以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "OP15-020 main: 自分のリーダーを、このターン中、パワー+3000し、相手のキャラ1枚までを、次の相手のエンドフェイズ終了時まで、パワー-8000。その後、自分の手札2枚を捨てて",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 3000,
          "duration": "turn"
        }
      },
      {
        "ko": "one_opponent_character_power_le_0"
      },
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -8000,
          "duration": "next_opp_turn_end"
        }
      }
    ]
  }
]
```

## OP15-056
- name=“メラメラの実”はおれが食っていいか？ / category=EVENT / cost=7 / power=- / counter=- / color=青 / features=ドレスローザ/革命軍
- **trigger**: 【トリガー】カード2枚を引く。

### 公式テキスト
> 【メイン】カード2枚を引く。その後、自分のリーダー「ルーシー」は、このターン中、【ダブルアタック】を得て、パワー+3000。(このカードが与えるダメージは2になる)

### 現行 overlay
```json
[
  {
    "_text": "OP15-056 メイン: 2ドロー + 自リーダー「ルーシー」に ダブルアタック+3000 turn",
    "when": "main",
    "do": [
      {
        "draw": 2
      },
      {
        "give_keyword": {
          "target": "self_leader",
          "keyword": "ダブルアタック"
        }
      },
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 3000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "trigger: 2ドロー",
    "when": "trigger",
    "do": [
      {
        "draw": 2
      }
    ]
  }
]
```

## OP10-060
- name=バリバリの銃 / category=EVENT / cost=5 / power=- / counter=- / color=青 / features=ドレスローザ/バルトクラブ
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】相手のパワー6000以下のキャラ1枚までを、持ち主のデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "バリバリの銃 (青 cost5) メイン: 6000以下デッキ下",
    "when": "main",
    "do": [
      {
        "return_to_hand": "one_opponent_character_power_le_6000"
      }
    ]
  },
  {
    "_text": "trigger: 自身の【メイン】効果 発動",
    "when": "trigger",
    "do": [
      {
        "fire_self_main": true
      }
    ]
  }
]
```

## OP15-054
- name=誰にも渡さねェよ!“あいつ”の形見だ / category=EVENT / cost=4 / power=- / counter=- / color=青 / features=ドレスローザ/革命軍

### 公式テキスト
> 【メイン】自分のリーダーが「ルーシー」の場合、以下から1つを選ぶ。・カード2枚を引き、自分の手札1枚を捨てる。その後、自分の手札からコスト4以下の特徴《ドレスローザ》を持つキャラカード1枚までを、登場させる。・ステージ1枚までを、持ち主の手札に戻す。

### 現行 overlay
```json
[
  {
    "_text": "OP15-054 【メイン】自分のリーダーが「ルーシー」の場合、以下から1つを選ぶ。・カード2枚を引き、自分の手札1枚を捨てる。その後、自分の手札からコスト4以下の特徴《ドレスローザ》を持つキャラカード1枚までを、登場させる。・ステージ1枚までを、持ち主の手札に戻す。",
    "when": "main",
    "if": {
      "leader_name": "ルーシー"
    },
    "do": [
      {
        "choice_effect": {
          "optional": false,
          "options": [
            {
              "label": "2 ドロー + 1 捨て + 特徴ドレスローザ コスト4以下 登場",
              "do": [
                {
                  "draw": 2
                },
                {
                  "trash_self_hand_random": 1
                },
                {
                  "play_from_hand": {
                    "filter": {
                      "feature": "ドレスローザ",
                      "cost_le": 4,
                      "category": "CHARACTER"
                    }
                  }
                }
              ]
            },
            {
              "label": "ステージ 1 枚 手札戻し",
              "do": [
                {
                  "return_to_hand": {
                    "type": "any_stage_n_1"
                  }
                }
              ]
            }
          ]
        }
      }
    ]
  }
]
```

## OP15-021
- name=見てろよ!エース!!! / category=EVENT / cost=4 / power=- / counter=- / color=赤 / features=ドレスローザ/革命軍

### 公式テキスト
> 手札のこのカードは、自分のトラッシュにイベントが4枚以上ある場合、コスト-3。【メイン】/【カウンター】相手のキャラ1枚までを、このターン中、パワー-3000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-021 手札時 コスト-3: 自trashイベ4+",
    "when": "in_hand",
    "if": {
      "self_trash_event_count_ge": 4
    },
    "do": [
      {
        "in_hand_cost_minus": 3
      }
    ]
  },
  {
    "_text": "OP15-021 メイン: 相手キャラ1 -3000 turn",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -3000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "OP15-021 カウンター: 相手キャラ1 -3000 turn",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -3000,
          "duration": "turn"
        }
      }
    ]
  }
]
```

## OP05-019
- name=火拳 / category=EVENT / cost=2 / power=- / counter=- / color=赤 / features=革命軍
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】相手のキャラ1枚までを、このターン中、パワー-4000。その後、自分のライフが2枚以下の場合、相手のパワー0以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "OP05-019 main: 相手のキャラ1枚までを、このターン中、パワー-4000。その後、自分のライフが2枚以下の場合、相手のパワー0以下のキャラ1枚までを、KOする。",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_power_le_0",
          "amount": -4000,
          "duration": "turn"
        }
      },
      {
        "ko": "one_opponent_character_power_le_0"
      }
    ],
    "if": {
      "self_life_le": 2
    }
  },
  {
    "_text": "OP05-019 trigger: このカードの【メイン】効果を発動する。",
    "when": "trigger",
    "do": [
      {
        "fire_self_effect": {
          "when_kind": "main"
        }
      }
    ]
  }
]
```

## OP10-059
- name=おまえ…タチ…わ…おれ…が…み…ち…び…く…!!! / category=EVENT / cost=1 / power=- / counter=- / color=青 / features=ドレスローザ/麦わらの一味
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】自分のデッキの上から5枚を見て、特徴《ドレスローザ》を持つキャラカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP10-059 メイン: デッキ上5を見て ドレスローザキャラ1を手札 残デッキ底",
    "when": "main",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "ドレスローザ",
            "category": "CHARACTER"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  },
  {
    "_text": "trigger: 自身の【メイン】効果 発動",
    "when": "trigger",
    "do": [
      {
        "fire_self_main": true
      }
    ]
  }
]
```

## OP15-057
- name=ドレスローザ王国 / category=STAGE / cost=1 / power=- / counter=- / color=青 / features=ドレスローザ

### 公式テキスト
> 【登場時】自分のリーダーが特徴《ドレスローザ》を持つ場合、カード1枚を引く。【相手のアタック時】このステージをレストにし、自分の手札からイベントかステージカード1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-057 on_play: 自分のリーダーが特徴《ドレスローザ》を持つ場合、カード1枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 1
      }
    ],
    "if": {
      "leader_feature": "ドレスローザ"
    }
  },
  {
    "_text": "OP15-057 opp_attack: このステージをレストにし、自分の手札からイベントかステージカード1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。",
    "when": "opp_attack",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 2000,
          "duration": "battle"
        }
      }
    ]
  }
]
```
