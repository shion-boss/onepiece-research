# LLM overlay 監査素材: tcgportal_bonney

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## EB04-001
- name=ジュエリー・ボニー / category=LEADER / power=5000 / counter=- / attribute=特 / color=赤/黄 / features=エッグヘッド/ボニー海賊団

### 公式テキスト
> 【相手のターン中】自分のライフが1枚以下の場合、このリーダーのパワー+2000。【起動メイン】【ターン1回】相手のキャラ1枚までを、このターン中、パワー-1000。その後、自分のライフが2枚以上の場合、自分のライフの上から1枚を手札に加えることができる。

### 現行 overlay
```json
[
  {
    "_text": "赤黄ボニー 常在: 相手ターン中ライフ1以下で自リーダー +2000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "opp_turn": true,
      "self_life_le": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "static"
        }
      }
    ]
  },
  {
    "_text": "赤黄ボニー 起動メイン: 相手キャラ -1000",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -1000,
          "duration": "turn"
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

## EB03-053
- name=ナミ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=黄 / features=麦わらの一味

### 公式テキスト
> 【登場時】自分のリーダーにレストのドン‼1枚までを、付与する。その後、相手のライフが3枚以上の場合、相手のライフの上から1枚までを、持ち主の手札に加える。【KO時】自分のライフの上から1枚を表向きにできる：自分の手札からパワー6000以下のキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "EB03-053 ナミ 登場時 1/2: 自リーダーに rested ドン1付与",
    "when": "on_play",
    "do": [
      {
        "attach_don": {
          "target": "self_leader",
          "count": 1,
          "rested": true
        }
      }
    ]
  },
  {
    "_text": "EB03-053 ナミ KO時: 自ライフ上1表向き(任意cost) → 自手札 power6000以下 キャラ1 登場",
    "when": "on_ko",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "peek_self_life_top": 1
            }
          ],
          "effect": [
            {
              "play_from_hand": {
                "filter": {
                  "power_le": 6000,
                  "category": "CHARACTER"
                },
                "limit": 1
              }
            }
          ]
        }
      }
    ]
  },
  {
    "_text": "EB03-053 ナミ 登場時 2/2: 相手ライフ3+ の 場合、 相手ライフ上1枚 を 相手 手札 へ",
    "when": "on_play",
    "if": {
      "opp_life_ge": 3
    },
    "do": [
      {
        "mill_opp_life_to_hand": 1
      }
    ]
  }
]
```

## EB04-058
- name=ボルサリーノ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=黄 / features=エッグヘッド/海軍

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】自分のライフが2枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "EB04-058 ボルサリーノ 登場時: 自ライフ2以下なら デッキ上1枚をライフへ",
    "when": "on_play",
    "if": {
      "self_life_le": 2
    },
    "do": [
      {
        "put_top_to_life": 1
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

## OP13-108
- name=ジュエリー・ボニー / category=CHARACTER / cost=9 / power=10000 / counter=- / attribute=特 / color=黄 / features=エッグヘッド/ボニー海賊団
- **trigger**: 【トリガー】自分のライフが1枚以下の場合、相手のコスト7以下のキャラ1枚までを、レストにする。

### 公式テキスト
> 【登場時】自分のリーダーが特徴《エッグヘッド》を持つ場合、このキャラは、このターン中、【速攻】を得る。その後、相手は自身のライフの上から1枚を、手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP13-108 ボニー 登場時: エッグヘッドリーダーで self に【速攻】turn, その後 相手ライフ1を相手手札へ",
    "when": "on_play",
    "if": {
      "leader_feature": "エッグヘッド"
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      },
      {
        "mill_opp_life_to_hand": 1
      }
    ]
  },
  {
    "_text": "trigger: 自ライフ≤1 で 相手 cost≤7 キャラ 1 レスト",
    "when": "trigger",
    "if": {
      "self_life_le": 1
    },
    "do": [
      {
        "rest": {
          "type": "one_opp_chara_filtered",
          "filter": {
            "cost_le": 7
          }
        }
      }
    ]
  }
]
```

## ST29-015
- name=温度レアァストライク!!! / category=EVENT / cost=1 / power=- / counter=- / color=黄 / features=エッグヘッド/麦わらの一味
- **trigger**: 【トリガー】カード1枚を引く。

### 公式テキスト
> 【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、自分のライフが1枚以下の場合、相手のリーダーかキャラ1枚までを、このターン中、パワー-2000。

### 現行 overlay
```json
[
  {
    "_text": "ST29-015 カウンター 1/2: 自リーダー or キャラ +2000 (無条件)",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 2000,
          "duration": "battle"
        }
      }
    ]
  },
  {
    "_text": "ST29-015 カウンター 2/2: 自ライフ1以下 で 相手 -2000 turn",
    "when": "counter",
    "if": {
      "self_life_le": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_inplay_any",
          "amount": -2000,
          "duration": "turn"
        }
      }
    ]
  },
  {
    "_text": "ST29-015 trigger: カード1枚を引く。",
    "when": "trigger",
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## EB04-061
- name=モンキー・D・ルフィ / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=打 / color=黄 / features=エッグヘッド/四皇/麦わらの一味

### 公式テキスト
> 手札のこのカードは、自分のライフが1枚以下の場合、コスト-1。【登場時】自分の手札1枚を捨てることができる：自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。その後、このキャラは、次の相手のエンドフェイズ終了時まで、【ブロッカー】を得る。

### 現行 overlay
```json
[
  {
    "_text": "EB04-061 ルフィ 手札時 コスト-1: 自ライフ1以下",
    "when": "in_hand",
    "if": {
      "self_life_le": 1
    },
    "do": [
      {
        "in_hand_cost_minus": 1
      }
    ]
  },
  {
    "_text": "EB04-061 ルフィ 登場時: 1捨てで 自リーダー +2000 + ブロッカー (next_opp_turn_end 統一)",
    "when": "on_play",
    "cost": {
      "discard_hand": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "next_opp_turn_end"
        }
      },
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー",
          "duration": "next_opp_turn_end"
        }
      }
    ]
  }
]
```

## EB04-053
- name=戦桃丸 / category=CHARACTER / cost=2 / power=1000 / counter=1000 / attribute=斬 / color=黄 / features=エッグヘッド/海軍

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【ブロック時】自分のライフが2枚以下の場合、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "EB04-053 戦桃丸 ブロック時: 自ライフ2以下なら 1ドロー",
    "when": "on_block",
    "if": {
      "self_life_le": 2
    },
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## EB04-054
- name=バーソロミュー・くま / category=CHARACTER / cost=7 / power=7000 / counter=1000 / attribute=打 / color=黄 / features=エッグヘッド/革命軍

### 公式テキスト
> 【登場時】自分のライフが2枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える。【KO時】相手のライフの上から1枚までを、持ち主の手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "EB04-054 くま 登場時: 自ライフ2以下なら デッキ上1をライフへ",
    "when": "on_play",
    "if": {
      "self_life_le": 2
    },
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  },
  {
    "_text": "EB04-054 くま KO時: 相手ライフ上1を相手手札へ",
    "when": "on_ko",
    "do": [
      {
        "mill_opp_life_to_hand": 1
      }
    ]
  }
]
```

## OP12-112
- name=ベビー５ / category=CHARACTER / cost=4 / power=5000 / counter=2000 / attribute=特 / color=黄 / features=ドンキホーテ海賊団
- **trigger**: 【トリガー】自分のリーダーが多色の場合、カード2枚を引く。

### 公式テキスト
> -

### 現行 overlay
```json
[
  {
    "_text": "OP12-112 trigger: 自分のリーダーが多色の場合、カード2枚を引く。",
    "when": "trigger",
    "do": [
      {
        "draw": 2
      }
    ],
    "if": {
      "leader_multicolor": true
    }
  }
]
```

## OP07-099
- name=ウソップ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=射 / color=黄 / features=エッグヘッド/麦わらの一味
- **trigger**: 【トリガー】自分の特徴《エッグヘッド》を持つ、リーダーかキャラ1枚までを、次の自分のターン終了時まで、パワー+2000。

### 公式テキスト
> -

### 現行 overlay
```json
[
  {
    "_text": "OP07-099 trigger: 自分の特徴《エッグヘッド》を持つ、リーダーかキャラ1枚までを、次の自分のターン終了時まで、パワー+2000。",
    "when": "trigger",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "エッグヘッド"
            }
          },
          "amount": 2000,
          "duration": "next_self_turn_end"
        }
      }
    ]
  }
]
```

## EB04-008
- name=歪んだ未来 / category=EVENT / cost=1 / power=- / counter=- / color=赤 / features=エッグヘッド/ボニー海賊団

### 公式テキスト
> 【メイン】自分のライフが2枚以下の場合、相手のキャラ1枚までを、このターン中、パワー-3000。【カウンター】自分のリーダーを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "EB04-008 メイン: 自ライフ2以下なら 相手キャラ1 -3000 turn",
    "when": "main",
    "if": {
      "self_life_le": 2
    },
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
    "_text": "EB04-008 カウンター: 自リーダー +3000 battle",
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

## OP13-012
- name=ネフェルタリ・ビビ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=知 / color=赤 / features=アラバスタ王国

### 公式テキスト
> 【登場時】自分のデッキの上から4枚を見て、コスト2以上の、特徴《アラバスタ王国》か《麦わらの一味》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-012 on_play: 自分のデッキの上から4枚を見て、コスト2以上の、特徴《アラバスタ王国》か《麦わらの一味》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデ",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "feature_in": [
              "アラバスタ王国",
              "麦わらの一味"
            ],
            "cost_ge": 2
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
