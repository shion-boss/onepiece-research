# LLM overlay 監査素材: cardrush_1453

カード数: 18

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP14-020
- name=ジュラキュール・ミホーク / category=LEADER / power=5000 / counter=- / attribute=斬 / color=緑 / features=王下七武海

### 公式テキスト
> 相手のリーダーが属性(斬)を持つ場合、このリーダーのパワー+1000。【起動メイン】【ターン1回】自分のカード1枚をレストにできる：コスト5以上のキャラがいる場合、自分のドン‼3枚までを、アクティブにする。その後、自分は、このターン中、キャラカードを登場できない。

### 現行 overlay
```json
[
  {
    "_text": "緑ミホーク 常在: 相手リーダー属性 斬 → 自リーダー +1000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "opp_leader_attribute": "斬"
    },
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 1000,
          "duration": "static"
        }
      }
    ]
  },
  {
    "_text": "緑ミホーク 起動メイン: 自レスト + コスト5+キャラいる時のみ → ドン3活性化 + 登場禁止",
    "when": "activate_main",
    "if": {
      "self_chara_feature_count_ge": {
        "feature": "斬",
        "count": 1
      }
    },
    "cost": {
      "rest_self": true,
      "once_per_turn": true
    },
    "do": [
      {
        "untap_don": 3
      },
      {
        "block_chara_play": true
      }
    ]
  }
]
```

## OP12-034
- name=ペローナ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=特 / color=緑 / features=シッケアール王国/スリラーバーク海賊団

### 公式テキスト
> 【登場時】自分のリーダーが属性(斬)を持つ場合、自分のデッキの上から5枚を見て、属性(斬)を持つカードか緑のイベント1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP12-034 on_play: 自分のリーダーが属性(斬)を持つ場合、自分のデッキの上から5枚を見て、属性(斬)を持つカードか緑のイベント1枚までを公開し、手札に加える。その後、残りを好きな順",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "or_clauses": [
              {
                "attribute": "斬"
              },
              {
                "category": "EVENT",
                "color": "緑"
              }
            ]
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ],
    "if": {
      "self_leader_attribute": "斬"
    }
  }
]
```

## ST02-007
- name=ジュエリー・ボニー / category=CHARACTER / cost=1 / power=1000 / counter=1000 / attribute=特 / color=緑 / features=超新星/ボニー海賊団

### 公式テキスト
> 【起動メイン】①(コストエリアのドン!!を指定の数レストにできる)，このキャラをレストにできる：自分のデッキの上から5枚を見て、特徴《超新星》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "ボニー cost1 (緑) 【起動メイン】(コスト1+rest_self) 超新星サーチ",
    "when": "activate_main",
    "cost": {
      "rest_self": true,
      "once_per_turn": true
    },
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "category": "CHARACTER",
            "feature": "超新星"
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

## ST24-002
- name=キッド＆キラー / category=CHARACTER / cost=2 / power=2000 / counter=1000 / attribute=斬/特 / color=緑 / features=超新星/キッド海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、特徴《超新星》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。【相手のアタック時】このキャラをトラッシュに置くことができる：自分のドン!!1枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "キッド&キラー (緑 cost2) 【登場時】超新星サーチ +【相手アタック時】(self trash) ドン1活性化",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "category": "CHARACTER",
            "feature": "超新星"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
        }
      }
    ]
  },
  {
    "_text": "ST24-002 opp_attack: このキャラをトラッシュに置くことができる：自分のドン!!1枚までを、アクティブにする。",
    "when": "opp_attack",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "return_self_to_trash": true
            }
          ],
          "effect": [
            {
              "untap_don": 1
            }
          ]
        }
      }
    ],
    "cost": {
      "trash_self": true
    }
  }
]
```

## EB01-015
- name=スクラッチメン・アプー / category=CHARACTER / cost=1 / power=1000 / counter=2000 / attribute=特 / color=緑 / features=超新星/オンエア海賊団

### 公式テキスト
> 【登場時】相手のコスト2以下のキャラ1枚までを、レストにする。

### 現行 overlay
```json
[
  {
    "_text": "スクラッチメン・アプー 登場時: 相手コスト2以下キャラ1枚レスト",
    "when": "on_play",
    "do": [
      {
        "rest": "one_opponent_character_cost_le_2"
      }
    ]
  }
]
```

## OP07-026
- name=ジュエリー・ボニー / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=緑 / features=超新星/ボニー海賊団

### 公式テキスト
> 【登場時】相手の、レストのキャラかドン‼1枚までは、次の相手のリフレッシュフェイズでアクティブにならない。

### 現行 overlay
```json
[
  {
    "_text": "ジュエリー・ボニー 登場時: 相手レストキャラ1枚は次リフレッシュでアクティブ化されない",
    "when": "on_play",
    "do": [
      {
        "stay_rested_next_refresh": {
          "type": "one_opponent_character_filtered",
          "filter": {
            "rested": true
          }
        }
      }
    ]
  }
]
```

## OP14-033
- name=ペローナ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=緑 / features=シッケアール王国/スリラーバーク海賊団

### 公式テキスト
> 【登場時】相手のコスト5以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【KO時】自分のカード1枚をレストにできる：自分の手札からコスト5以下の緑のキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-033 on_play: 相手のコスト5以下のキャラ2枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。",
    "when": "on_play",
    "do": [
      {
        "set_cannot_rest": {
          "target": "one_opponent_character_cost_le_5cost",
          "count": 2
        }
      },
      {
        "set_cannot_rest": {
          "target": "one_opponent_character_cost_le_5cost",
          "count": 2
        }
      }
    ]
  },
  {
    "_text": "OP14-033 on_ko: 自分のカード1枚をレストにできる：自分の手札からコスト5以下の緑のキャラカード1枚までを、登場させる。",
    "when": "on_ko",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "rest_self_cards": 1
            }
          ],
          "effect": [
            {
              "play_from_hand": {
                "filter": {
                  "category": "CHARACTER",
                  "cost_le": 5,
                  "color": "緑"
                },
                "limit": 1
              }
            }
          ]
        }
      }
    ]
  }
]
```

## OP10-030
- name=スモーカー / category=CHARACTER / cost=5 / power=7000 / counter=- / attribute=斬 / color=緑 / features=パンクハザード/海軍

### 公式テキスト
> 【バニッシュ】(このカードがダメージを与えた場合、トリガーは発動せずそのカードはトラッシュに置かれる)【起動メイン】自分のドン‼1枚までを、アクティブにする。その後、自分はこのターン中、キャラの効果でドン‼をアクティブにできない。

### 現行 overlay
```json
[
  {
    "_text": "スモーカー 起動メイン: ドン1アクティブ化",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "untap_don": 1
      }
    ]
  }
]
```

## OP12-118
- name=ジュエリー・ボニー / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=緑 / features=超新星/ボニー海賊団

### 公式テキスト
> 【ブロッカー】【登場時】自分のレストのカードが8枚以上ある場合、カード2枚を引き、自分の手札1枚を捨てる。その後、自分のドン‼1枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP12-118 on_play: 自分のレストのカードが8枚以上ある場合、カード2枚を引き、自分の手札1枚を捨てる。その後、自分のドン‼1枚までを、アクティブにする。",
    "when": "on_play",
    "do": [
      {
        "trash_self_hand_random": 1
      },
      {
        "untap_don": 1
      }
    ],
    "cost": {
      "discard_hand": 1
    }
  }
]
```

## OP13-031
- name=トラファルガー・ロー / category=CHARACTER / cost=6 / power=6000 / counter=- / attribute=斬 / color=緑 / features=FILM/超新星/ハートの海賊団

### 公式テキスト
> 自分のライフが1枚以下の場合、このキャラは【ブロッカー】を得る。【登場時】自分のキャラ1枚を持ち主の手札に戻すことができる：自分の手札からコスト5以下のキャラカード1枚までを、レストで登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-031 常在: 自分のライフが1枚以下の場合、このキャラは【ブロッカー】を得る",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_life_le": 1
    },
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
    "_text": "OP13-031 on_play: 自分のキャラ1枚を持ち主の手札に戻すことができる：自分の手札からコスト5以下のキャラカード1枚までを、レストで登場させる。",
    "when": "on_play",
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "cost_le": 5
          },
          "limit": 1
        }
      },
      {
        "return_to_hand": {
          "type": "one_self_chara_filtered",
          "filter": {
            "cost_le": 5
          }
        }
      }
    ]
  }
]
```

## OP14-119
- name=ジュラキュール・ミホーク / category=CHARACTER / cost=9 / power=10000 / counter=- / attribute=斬 / color=緑 / features=王下七武海

### 公式テキスト
> 【自分のターン中】このキャラがレストになった時、相手のコスト9以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、レストにできない。【相手のアタック時】【ターン1回】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP14-119 opp_attack: 【ターン1回】自分の手札1枚を捨てることができる：自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。",
    "when": "opp_attack",
    "do": [
      {
        "trash_self_hand_random": 1
      },
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 2000,
          "duration": "battle"
        }
      },
      {
        "set_cannot_rest": {
          "target": "one_opponent_character_cost_le_9",
          "count": 1,
          "duration": "next_opp_turn_end"
        }
      }
    ],
    "cost": {
      "once_per_turn": true,
      "discard_hand": 1
    },
    "conditions": [
      {
        "self_turn": true
      }
    ]
  }
]
```

## ST24-004
- name=ロー＆ベポ / category=CHARACTER / cost=10 / power=11000 / counter=- / attribute=斬/打 / color=緑 / features=ミンク族/超新星/ハートの海賊団

### 公式テキスト
> 【登場時】相手のキャラ1枚までを、レストにし、そのキャラは次の相手のリフレッシュフェイズでアクティブにならない。その後、相手のレストのキャラが2枚以上いる場合、自分のリーダーを、次の相手のエンドフェイズ終了時まで、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "ロー&ベポ (緑 cost10) 【登場時】相手キャラレスト + 自リーダー +2000",
    "when": "on_play",
    "do": [
      {
        "rest": "one_opponent_character_any"
      },
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "next_opp_turn_end"
        }
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

## OP12-037
- name=鬼気 九刀流 阿修羅 抜剣 亡者戯 / category=EVENT / cost=1 / power=- / counter=- / color=緑 / features=麦わらの一味

### 公式テキスト
> 【メイン】自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。【カウンター】自分のリーダーを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "OP12-037 main: 自分のドン‼3枚をレストにできる：相手の、キャラかドン‼合計2枚までを、レストにする。",
    "when": "main",
    "do": [
      {
        "rest": "one_opp_chara_or_don"
      },
      {
        "rest": "one_opp_chara_or_don"
      },
      {
        "rest": "one_opp_chara_or_don"
      },
      {
        "rest_opp_don": 1
      }
    ],
    "cost": {
      "rest_self_don": 3
    }
  },
  {
    "_text": "OP12-037 counter: 自分のリーダーを、このバトル中、パワー+3000。",
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

## OP06-038
- name=一大・三千・大千・世界 / category=EVENT / cost=1 / power=- / counter=- / color=緑 / features=麦わらの一味/ドレスローザ
- **trigger**: 【トリガー】相手のレストのコスト3以下のキャラ1枚までを、KOする。

### 公式テキスト
> 【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、自分のレストのカードが8枚以上ある場合、そのカードを、このバトル中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP06-038 counter: 自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、自分のレストのカードが8枚以上ある場合、そのカードを、このバトル中、パワー+2000。",
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
    "_text": "OP06-038 trigger: 相手のレストのコスト3以下のキャラ1枚までを、KOする。",
    "when": "trigger",
    "do": [
      {
        "ko": "one_opponent_rested_character_cost_le_3cost"
      }
    ]
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

## OP14-039
- name=棺船 / category=STAGE / cost=1 / power=- / counter=- / color=緑 / features=東の海/王下七武海

### 公式テキスト
> 【登場時】自分のリーダーが「ジュラキュール・ミホーク」の場合、カード1枚を引く。【自分のターン終了時】自分のリーダーが「ジュラキュール・ミホーク」の場合、自分のドン‼1枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP14-039 棺船 登場時: ミホークリーダーで 1ドロー",
    "when": "on_play",
    "if": {
      "leader_name": "ジュラキュール・ミホーク"
    },
    "do": [
      {
        "draw": 1
      }
    ]
  },
  {
    "_text": "OP14-039 棺船 自ターン終了時: ミホークリーダーで ドン1アクティブ",
    "when": "end_of_turn",
    "if": {
      "leader_name": "ジュラキュール・ミホーク"
    },
    "do": [
      {
        "untap_don": 1
      }
    ]
  }
]
```
