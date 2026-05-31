# LLM overlay 監査素材: tcgportal_hancock

カード数: 16

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP14-041
- name=ボア・ハンコック / category=LEADER / power=5000 / counter=- / attribute=特 / color=青/黄 / features=王下七武海/九蛇海賊団

### 公式テキスト
> 【相手のターン中】自分のキャラが登場した時、カード1枚を引く。【ドン‼×1】【ターン1回】自分の元々のパワー5000以上の、特徴《アマゾン・リリー》か《九蛇海賊団》を持つキャラがKOされた時、相手のライフの上から1枚までを、持ち主の手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "【相手のターン中】自分のキャラが登場した時、カード1枚を引く",
    "when": "on_self_chara_played",
    "if": {
      "opp_turn": true
    },
    "do": [
      {
        "draw": 1
      }
    ]
  },
  {
    "_text": "【ドン!!×1】【ターン1回】自分の元々のパワー5000以上の、特徴《アマゾン・リリー》か《九蛇海賊団》を持つキャラがKOされた時、相手のライフの上から1枚までを、持ち主の手札に加える。",
    "when": "on_self_chara_ko",
    "conditions": [
      {
        "self_attached_don_ge": 1
      },
      {
        "victim_truly_original_power_ge": 5000
      },
      {
        "victim_feature_in": [
          "アマゾン・リリー",
          "九蛇海賊団"
        ]
      }
    ],
    "cost": {
      "once_per_turn": true
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

## OP14-107
- name=シャクヤク / category=CHARACTER / cost=6 / power=5000 / counter=2000 / attribute=知 / color=黄 / features=アマゾン・リリー
- **trigger**: 【トリガー】自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。

### 公式テキスト
> 【登場時】相手のライフが3枚以下の場合、カード2枚を引き、自分の手札2枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-107 シャクヤク 登場時: 相手のライフが3枚以下の場合、 カード2枚を引き、 自分の手札2枚を捨てる (= 公式: 引く+捨てる は 共に 効果 do、 自ライフ 条件 は 公式 に ない)",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 2
      }
    ],
    "if": {
      "opp_life_le": 3
    }
  },
  {
    "_text": "OP14-107 trigger: 自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_self": true
      }
    ],
    "if": {
      "leader_feature": "九蛇海賊団"
    }
  }
]
```

## OP14-105
- name=ゴルゴン三姉妹 / category=CHARACTER / cost=6 / power=5000 / counter=2000 / attribute=斬/特 / color=黄 / features=王下七武海/九蛇海賊団
- **trigger**: 【トリガー】自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。

### 公式テキスト
> 【起動メイン】【ターン1回】自分の手札から特徴《アマゾン・リリー》か《九蛇海賊団》を持つカード3枚を公開することができる：自分のリーダーとキャラすべてにレストのドン‼1枚ずつまでを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "【起動メイン】【ターン1回】自分の手札から特徴《アマゾン・リリー》か《九蛇海賊団》を持つカード3枚を公開することができる：自分のリーダーとキャラすべてにレストのドン‼1枚ずつまでを、付与する。",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "reveal_hand_with_filter": {
                "feature_in": [
                  "アマゾン・リリー",
                  "九蛇海賊団"
                ],
                "count": 3
              }
            }
          ],
          "effect": [
            {
              "attach_rested_don": {
                "target": "all_self_team",
                "count": 1,
                "per_target": true
              }
            }
          ]
        }
      }
    ]
  },
  {
    "_text": "trigger: 条件 ({'leader_feature': '九蛇海賊団'}) で 自身登場",
    "when": "trigger",
    "if": {
      "leader_feature": "九蛇海賊団"
    },
    "do": [
      {
        "play_self": true
      }
    ]
  }
]
```

## OP15-113
- name=ロロノア・ゾロ / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=斬 / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 【登場時】自分の手札1枚を捨てることができる：自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP15-113 ゾロ 登場時: 自手札1捨てで デッキ上1をライフへ",
    "when": "on_play",
    "cost": {
      "discard_hand": 1
    },
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  }
]
```

## OP14-104
- name=ゲッコー・モリア / category=CHARACTER / cost=8 / power=10000 / counter=- / attribute=特 / color=黄 / features=王下七武海/スリラーバーク海賊団
- **trigger**: 【トリガー】自分のトラッシュからコスト4以下のキャラカード1枚までを、登場させる。

### 公式テキスト
> 【登場時】自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、ライフの上に表向きで加えるか登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-104 on_play: 自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、ライフの上に表向きで加えるか登場させる。",
    "when": "on_play",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "category": "CHARACTER",
            "cost_le": 4,
            "feature": "スリラーバーク海賊団"
          },
          "limit": 1
        }
      }
    ]
  },
  {
    "_text": "OP14-104 trigger: 自分のトラッシュからコスト4以下のキャラカード1枚までを、登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "cost_le": 4
          },
          "limit": 1
        }
      }
    ]
  }
]
```

## OP14-112
- name=ボア・ハンコック / category=CHARACTER / cost=9 / power=10000 / counter=- / attribute=特 / color=黄 / features=王下七武海/九蛇海賊団
- **trigger**: 【トリガー】自分の手札からパワー6000以下の【トリガー】を持つキャラカード1枚までを、登場させる。

### 公式テキスト
> 【登場時】自分のリーダーが特徴《王下七武海》を持つ場合、自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のライフの上から1枚までを、持ち主の手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP14-112 on_play: 自分のリーダーが特徴《王下七武海》を持つ場合、自分のデッキの上から1枚までを、ライフの上に加える。その後、相手のライフの上から1枚までを、持ち主の手札に加える。",
    "when": "on_play",
    "do": [
      {
        "put_top_to_life": 1
      },
      {
        "mill_opp_life_to_hand": 1
      }
    ],
    "if": {
      "leader_feature": "王下七武海"
    }
  },
  {
    "_text": "OP14-112 trigger: 自分の手札からパワー6000以下の【トリガー】を持つキャラカード1枚までを、登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_from_hand": {
          "filter": {
            "power_le": 6000,
            "has_trigger": true
          },
          "limit": 1,
          "rested": false
        }
      }
    ]
  }
]
```

## OP14-113
- name=マーガレット / category=CHARACTER / cost=3 / power=5000 / counter=- / attribute=知 / color=黄 / features=アマゾン・リリー
- **trigger**: 【トリガー】自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、特徴《アマゾン・リリー》か《九蛇海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-113 マーガレット 登場時: デッキ上 5 を 見て 《アマゾン・リリー》 か 《九蛇海賊団》 1 枚 を 手札へ、 残りを 好きな順番 でデッキ底、 その後 手札 1 捨て (= 公式: feature_in で 2 特徴 OR、 discard は 効果 do 内)",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature_in": [
              "アマゾン・リリー",
              "九蛇海賊団"
            ]
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  },
  {
    "_text": "OP14-113 trigger: 自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_self": true
      }
    ],
    "if": {
      "leader_feature": "九蛇海賊団"
    }
  }
]
```

## ST17-004
- name=ボア・ハンコック / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=特 / color=青 / features=王下七武海/九蛇海賊団

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】自分のデッキの上から3枚を見て、好きな順番に並び替え、デッキの上か下に置く。その後、自分の特徴《王下七武海》を持つ、リーダーかキャラ1枚にレストのドン‼1枚までを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "ST17-004 ハンコック 登場時: デッキ上3並び替え 上/下 + その後 自 王下七武海 リーダー/キャラ 1 に レストドン1付与",
    "when": "on_play",
    "do": [
      {
        "look_top_reorder": {
          "depth": 3,
          "to": "choice"
        }
      },
      {
        "attach_rested_don": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "王下七武海"
            }
          },
          "count": 1
        }
      }
    ]
  }
]
```

## OP06-106
- name=光月日和 / category=CHARACTER / cost=2 / power=- / counter=2000 / attribute=知 / color=黄 / features=ワノ国/光月家

### 公式テキスト
> 【登場時】自分のライフの上か下から1枚を手札に加えることができる：自分の手札1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP06-106 on_play: 自分のライフの上か下から1枚を手札に加えることができる：自分の手札1枚までを、ライフの上に加える。",
    "when": "on_play",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "life_top_or_bottom_to_hand": 1
            }
          ],
          "effect": [
            {
              "hand_to_self_life": 1
            }
          ]
        }
      }
    ]
  }
]
```

## OP08-050
- name=ナミュール / category=CHARACTER / cost=3 / power=2000 / counter=1000 / attribute=打 / color=青 / features=魚人族/白ひげ海賊団

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】カード2枚を引き、自分の手札2枚を好きな順番で並び替え、デッキの上か下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP08-050 on_play: カード2枚を引き、自分の手札2枚を好きな順番で並び替え、デッキの上か下に置く。",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "self_hand_to_deck_bottom": 2
      }
    ]
  }
]
```

## OP14-103
- name=グロリオーサ(ニョン婆) / category=CHARACTER / cost=2 / power=- / counter=1000 / attribute=知 / color=黄 / features=アマゾン・リリー
- **trigger**: 【トリガー】このカードを登場させる。

### 公式テキスト
> 【登場時】自分のライフの上か下から1枚を手札に加えることができる：自分の手札1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP14-103 on_play: 自分のライフの上か下から1枚を手札に加えることができる：自分の手札1枚までを、ライフの上に加える。",
    "when": "on_play",
    "do": [
      {
        "optional_cost_then": {
          "cost": [
            {
              "life_top_or_bottom_to_hand": 1
            }
          ],
          "effect": [
            {
              "hand_to_self_life": 1
            }
          ]
        }
      }
    ]
  },
  {
    "_text": "OP14-103 trigger: このカードを登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_self": true
      }
    ]
  }
]
```

## OP12-119
- name=バーソロミュー・くま / category=CHARACTER / cost=6 / power=7000 / counter=1000 / attribute=打 / color=黄 / features=王下七武海/革命軍

### 公式テキスト
> 【登場時】自分の手札1枚を捨てることができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、次の相手のエンドフェイズ終了時まで、コスト+2。【相手のターン中】【KO時】自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP12-119 on_play (cost: 手札1捨): 自デッキ上1枚→ライフ + 自cost+2 (= 次opp turn 終 ま で)",
    "when": "on_play",
    "do": [
      {
        "put_top_to_life": 1
      },
      {
        "cost_minus": {
          "target": "self",
          "amount": -2,
          "duration": "next_opp_turn_end"
        }
      }
    ],
    "cost": {
      "discard_hand": 1
    }
  },
  {
    "_text": "OP12-119 くま 相手ターン中 自KO時: 自デッキ上1枚→ライフ",
    "when": "on_self_chara_ko",
    "conditions": [
      {
        "opp_turn": true
      },
      {
        "victim_iid_eq_self": true
      }
    ],
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  }
]
```

## OP14-102
- name=クマシー / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=打 / color=黄 / features=スリラーバーク海賊団
- **trigger**: 【トリガー】自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、レストで登場させる。

### 公式テキスト
> -

### 現行 overlay
```json
[
  {
    "_text": "クマシー トリガー: スリラー4以下 trash から登場",
    "when": "trigger",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "category": "CHARACTER",
            "feature": "スリラーバーク海賊団",
            "cost_le": 4
          },
          "limit": 1,
          "rested": true
        }
      }
    ]
  }
]
```

## OP07-057
- name=芳香脚 / category=EVENT / cost=2 / power=- / counter=- / color=青 / features=王下七武海/九蛇海賊団
- **trigger**: 【トリガー】カード1枚を引く。

### 公式テキスト
> 【メイン】自分の特徴《王下七武海》を持つ、リーダーかキャラ1枚までを選び、このターン中、パワー+2000。その後、相手は、このターン中、選んだカードがアタックする場合【ブロッカー】を発動できない。

### 現行 overlay
```json
[
  {
    "_text": "OP07-057 main: 自分の特徴《王下七武海》を持つ、リーダーかキャラ1枚までを選び、このターン中、パワー+2000。その後、相手は、このターン中、選んだカードがアタックする場合【ブ",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "王下七武海"
            }
          },
          "amount": 2000,
          "duration": "turn"
        }
      },
      {
        "prevent_blocker_for_attacker": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "王下七武海"
            }
          }
        }
      }
    ]
  },
  {
    "_text": "OP07-057 trigger: カード1枚を引く。",
    "when": "trigger",
    "do": [
      {
        "draw": 1
      }
    ]
  }
]
```

## OP14-114
- name=ラン / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=射 / color=黄 / features=九蛇海賊団
- **trigger**: 【トリガー】自分のリーダーが特徴《九蛇海賊団》を持つ場合、このカードを登場させる。

### 公式テキスト
> 【起動メイン】【ターン1回】自分の特徴《九蛇海賊団》を持つ、リーダーかキャラ1枚にレストのドン‼1枚までを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "【起動メイン】【ターン1回】自分の特徴《九蛇海賊団》を持つ、リーダーかキャラ1枚にレストのドン‼1枚までを、付与する。",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "attach_rested_don": {
          "target": {
            "type": "one_self_chara_or_leader_filtered",
            "filter": {
              "feature": "九蛇海賊団"
            }
          },
          "count": 1
        }
      }
    ]
  },
  {
    "_text": "trigger: 条件 ({'leader_feature': '九蛇海賊団'}) で 自身登場",
    "when": "trigger",
    "if": {
      "leader_feature": "九蛇海賊団"
    },
    "do": [
      {
        "play_self": true
      }
    ]
  }
]
```
