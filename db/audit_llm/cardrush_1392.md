# LLM overlay 監査素材: cardrush_1392

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP13-079
- name=イム / category=LEADER / power=5000 / counter=- / attribute=？ / color=黒 / features=？

### 公式テキスト
> ルール上、自分はコスト2以上のイベントをデッキに入れることができず、ゲーム開始時、自分のデッキから特徴《聖地マリージョア》を持つステージカード1枚までを、登場させる。【起動メイン】【ターン1回】自分の、特徴《天竜人》を持つキャラか、手札1枚をトラッシュに置くことができる：カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "黒イム ゲーム開始時: 自デッキから 特徴《聖地マリージョア》 を持つ ステージカード 1 枚 を 登場 (= 残りデッキ シャッフル)",
    "when": "game_start",
    "do": [
      {
        "summon_stage_from_deck_with_feature": "聖地マリージョア"
      }
    ]
  },
  {
    "_text": "黒イム 起動メイン: 手札1捨て → 1ドロー (天竜人選択肢は手札捨てに集約)",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true,
      "discard_hand": 1
    },
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP13-091
- name=マーカス・マーズ聖 / category=CHARACTER / cost=6 / power=5000 / counter=1000 / attribute=特 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 自分のトラッシュが7枚以上ある場合、このキャラは相手の効果で場を離れず、【ブロッカー】を得る。【登場時】自分の手札1枚を捨てることができる：相手の元々のコスト5以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "OP13-091 マーズ 常在: 自trash7+で 相手効果不滅 + ブロッカー",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 7
    },
    "do": [
      {
        "set_ko_immune": "self"
      },
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー"
        }
      }
    ]
  },
  {
    "_text": "OP13-091 マーズ 登場時: 1捨てコストで 相手元々cost5以下キャラ1 KO",
    "when": "on_play",
    "cost": {
      "discard_hand": 1
    },
    "do": [
      {
        "ko": "one_opponent_character_cost_le_5"
      }
    ]
  }
]
```

## OP13-080
- name=イーザンバロン・V・ナス寿郎聖 / category=CHARACTER / cost=6 / power=5000 / counter=1000 / attribute=斬 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 自分のトラッシュが7枚以上ある場合、このキャラは相手の効果で場を離れず、【速攻】を得る。【アタック時】自分のトラッシュが10枚以上ある場合、相手のキャラ1枚までを、このターン中、パワー-2000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-080 イーザンバロン 常在: 自trash7+で 相手効果不滅 + 速攻",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 7
    },
    "do": [
      {
        "set_ko_immune": "self"
      },
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      }
    ]
  },
  {
    "_text": "OP13-080 イーザンバロン アタック時: 自trash10+で 相手キャラ1 -2000 turn",
    "when": "on_attack",
    "if": {
      "self_trash_count_ge": 10
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

## OP13-083
- name=ジェイガルシア・サターン聖 / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=特 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 自分のトラッシュが7枚以上ある場合、このキャラは相手の効果で場を離れない。【登場時】自分のデッキの上から5枚を見て、特徴《五老星》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-083 サターン聖 常在: 自trash7+で 相手効果で場を離れない",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 7
    },
    "do": [
      {
        "set_ko_immune": "self"
      }
    ]
  },
  {
    "_text": "OP13-083 登場時: デッキ上5を見て 五老星1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "五老星"
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

## OP13-084
- name=シェパード・十・ピーター聖 / category=CHARACTER / cost=7 / power=5000 / counter=2000 / attribute=特 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 自分のトラッシュが7枚以上ある場合、このキャラは相手の効果で場を離れない。【自分のターン中】自分のトラッシュが10枚以上ある場合、自分の特徴《五老星》を持つキャラすべての元々のパワーを7000にする。

### 現行 overlay
```json
[
  {
    "_text": "OP13-084 シェパード 常在: 自trash7+で相手の効果で場を離れない (= 公式: 自分のターン中 限定 ではない、 相手 ターン中 も 不滅)",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "set_ko_immune": "self"
      }
    ],
    "conditions": [
      {
        "self_trash_count_ge": 7
      }
    ]
  },
  {
    "_text": "OP13-084 シェパード 自ターン中 + trash10+ で 自 五老星 全 元 々 power 7000",
    "when": "on_attached_don",
    "n": 0,
    "conditions": [
      {
        "self_trash_count_ge": 10
      },
      {
        "self_turn": true
      }
    ],
    "do": [
      {
        "set_base_power": {
          "target": {
            "type": "all_self_chara_filtered",
            "filter": {
              "feature": "五老星"
            }
          },
          "amount": 7000
        }
      }
    ]
  }
]
```

## OP13-089
- name=トップマン・ウォーキュリー聖 / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=特 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 自分のトラッシュが7枚以上ある場合、このキャラは相手の効果で場を離れず、【ブロッカー】を得る。【KO時】カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-089 ウォーキュリー 常在: 自trash7+で 相手効果不滅 + ブロッカー",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 7
    },
    "do": [
      {
        "set_ko_immune": "self"
      },
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー"
        }
      }
    ]
  },
  {
    "_text": "OP13-089 ウォーキュリー KO時: 1ドロー",
    "when": "on_ko",
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP13-082
- name=五老星 / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=斬/特 / color=黒 / features=天竜人/五老星

### 公式テキスト
> 【起動メイン】自分のリーダーが「イム」の場合、自分のドン‼1枚をレストにし、自分の手札1枚を捨てることができる：自分のキャラすべてをトラッシュに置き、自分のトラッシュからパワー5000のカード名の異なる特徴《五老星》を持つキャラカード5枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-082 五老星 起動メイン: リーダー「イム」の場合、 ドン1レスト + 手札1捨て を コスト として、 自分のキャラすべてをトラッシュに置き、 自分のトラッシュからパワー5000のカード名の異なる特徴《五老星》を持つキャラカード5枚まで を登場させる",
    "when": "activate_main",
    "do": [
      {
        "trash_all_self_chara": true
      },
      {
        "play_from_trash": {
          "filter": {
            "feature": "五老星",
            "power_eq": 5000,
            "category": "CHARACTER"
          },
          "limit": 5,
          "unique_name": true
        }
      }
    ],
    "cost": {
      "discard_hand": 1,
      "rest_self_don": 1
    },
    "if": {
      "leader_name": "イム"
    }
  }
]
```

## OP13-086
- name=シャルリア宮 / category=CHARACTER / cost=1 / power=- / counter=1000 / attribute=射 / color=黒 / features=天竜人

### 公式テキスト
> 【登場時】自分のデッキの上から3枚を見て、「シャルリア宮」以外の特徴《天竜人》を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシュに置き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-086 シャルリア宮 登場時: デッキ上3を見て 天竜人 (除く自身) 1を手札に加える、 その後 残りをトラッシュに置き 手札1捨て (= 公式: 残りはトラッシュ、 デッキ底ではない)",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "天竜人",
            "exclude_card_id": "OP13-086"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
        }
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP13-092
- name=ミョスガルド聖 / category=CHARACTER / cost=2 / power=- / counter=2000 / attribute=知 / color=黒 / features=天竜人

### 公式テキスト
> 【登場時】自分のライフが3枚以下の場合、自分のトラッシュからコスト1の特徴《聖地マリージョア》を持つステージカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-092 on_play: 自分のライフが3枚以下の場合、自分のトラッシュからコスト1の特徴《聖地マリージョア》を持つステージカード1枚までを、登場させる。",
    "when": "on_play",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "category": "STAGE",
            "cost_eq": 1,
            "feature": "聖地マリージョア"
          },
          "limit": 1
        }
      }
    ],
    "if": {
      "self_life_le": 3
    }
  }
]
```

## PRB02-014
- name=サボ / category=CHARACTER / cost=6 / power=6000 / counter=2000 / attribute=特 / color=黒 / features=ドレスローザ/革命軍

### 公式テキスト
> 手札のこのカードは、自分のトラッシュが15枚以上ある場合、コスト-3。【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)

### 現行 overlay
```json
[
  {
    "_text": "PRB02-014 サボ 手札時 コスト-3: 自trash15+",
    "when": "in_hand",
    "if": {
      "self_trash_count_ge": 15
    },
    "do": [
      {
        "in_hand_cost_minus": 3
      }
    ]
  }
]
```

## OP13-096
- name=“五老星”ここに!!! / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=天竜人/五老星
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】自分のデッキの上から3枚を見て、「”五老星“ここに!!!」以外の特徴《天竜人》を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシュに置く。

### 現行 overlay
```json
[
  {
    "_text": "OP13-096 メイン: デッキ上3を見て 天竜人 (除く自身) 1を手札 残trash",
    "when": "main",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "天竜人",
            "exclude_card_id": "OP13-096"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
        }
      }
    ]
  }
]
```

## OP13-098
- name=元々…ないではないか… / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=天竜人/五老星

### 公式テキスト
> 【メイン】自分のドン‼1枚をレストにできる：自分のリーダーが「イム」の場合、相手のコスト7のステージ1枚までを、KOする。【カウンター】自分のリーダーが「イム」の場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。

### 現行 overlay
```json
[
  {
    "_text": "OP13-098 メイン: ドン-1, イムリーダーで 相手cost7ステージ1KO",
    "when": "main",
    "cost": {
      "rest_self_don": 1
    },
    "if": {
      "leader_name": "イム"
    },
    "do": [
      {
        "ko_opp_stage": {
          "cost": 7,
          "limit": 1
        }
      }
    ]
  },
  {
    "_text": "OP13-098 カウンター: イムリーダーで 自リーダー/キャラ1 +4000 battle",
    "when": "counter",
    "if": {
      "leader_name": "イム"
    },
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 4000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

## OP14-096
- name=浸食輪廻 / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=王下七武海/B・W

### 公式テキスト
> 【メイン】自分のドン‼2枚をレストにできる：相手のコスト5以下のキャラ1枚までを、このターン中、効果を無効にする。【カウンター】自分のトラッシュが10枚以上ある場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。

### 現行 overlay
```json
[
  {
    "_text": "OP14-096 main: 自分のドン‼2枚をレストにできる：相手のコスト5以下のキャラ1枚までを、このターン中、効果を無効にする。",
    "when": "main",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "rest_self_don": 2
            }
          ],
          "effect": [
            {
              "disable_effect": {
                "target": "one_opponent_character_cost_le_5cost",
                "duration": "turn"
              }
            }
          ]
        }
      }
    ],
    "cost": {
      "rest_self_don": 2
    }
  },
  {
    "_text": "OP14-096 counter: 自分のトラッシュが10枚以上ある場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 4000,
          "duration": "battle"
        }
      }
    ],
    "if": {
      "self_trash_count_ge": 10
    }
  }
]
```

## OP05-097
- name=聖地マリージョア / category=STAGE / cost=1 / power=- / counter=- / color=黒 / features=聖地マリージョア

### 公式テキスト
> 【自分のターン中】自分が手札から登場させるコスト2以上の特徴《天竜人》を持つキャラカードの支払うコストは1少なくなる。

### 現行 overlay
```json
[
  {
    "_text": "OP05-097 on_attached_don (パターン未一致): 【自分のターン中】自分が手札から登場させるコスト2以上の特徴《天竜人》を持つキャラカードの支払うコストは1少なくなる。",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "reduce_play_cost_filtered_static": {
          "filter": {
            "category": "CHARACTER",
            "cost_ge": 2,
            "feature": "天竜人"
          },
          "amount": 1
        }
      }
    ],
    "conditions": [
      {
        "self_turn": true
      }
    ]
  }
]
```

## OP13-099
- name=虚の玉座 / category=STAGE / cost=7 / power=- / counter=- / color=黒 / features=聖地マリージョア

### 公式テキスト
> 【自分のターン中】自分のトラッシュが19枚以上ある場合、自分のリーダーを、パワー+1000。【起動メイン】このカードと自分のドン‼3枚をレストにできる：自分の手札から自分の場のドン‼の枚数以下のコストを持つ黒の特徴《五老星》を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "虚の玉座 static: トラッシュ19枚以上で leader +1000",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 1000,
          "duration": "static"
        }
      }
    ],
    "conditions": [
      {
        "self_trash_count_ge": 19
      },
      {
        "self_turn": true
      }
    ]
  },
  {
    "_text": "OP13-099 虚の玉座 起動メイン: このカード+ドン3 rest を コスト として、 自分の手札から 場のドン!!枚数以下のコストを持つ 黒 の 特徴《五老星》 を 持つキャラ 1 枚 まで を 登場 (= 公式: 手札から、 トラッシュ ではない)",
    "when": "activate_main",
    "cost": {
      "rest_self": true,
      "once_per_turn": true,
      "rest_self_don": 3
    },
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "feature": "五老星",
            "category": "CHARACTER",
            "color": "黒",
            "cost_le_dynamic": "self_don_total"
          },
          "limit": 1
        }
      }
    ]
  }
]
```
