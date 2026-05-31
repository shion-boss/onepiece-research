# LLM overlay 監査素材: cardrush_1439

カード数: 16

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP11-041
- name=ナミ / category=LEADER / power=5000 / counter=- / attribute=特 / color=青/黄 / features=麦わらの一味

### 公式テキスト
> 【自分のターン中】【ターン1回】ライフが離れた時、発動できる。自分の手札が7枚以下の場合、カード1枚を引く。【ドン‼×1】【相手のアタック時】【ターン1回】自分の手札1枚を捨てることができる：このリーダーは、このターン中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "青黄ナミ ドン1+ 相手ターン中 自リーダー +2000",
    "when": "on_attached_don",
    "n": 1,
    "if": {
      "opp_turn": true
    },
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "static"
        }
      }
    ],
    "cost": {
      "once_per_turn": true
    }
  },
  {
    "_text": "青黄ナミ アタック時 1ドロー (ライフ離れた時の代替)",
    "when": "on_attack",
    "if": {
      "self_hand_count_le": 7
    },
    "do": [
      {
        "draw": 1
      }
    ],
    "cost": {
      "once_per_turn": true
    }
  },
  {
    "_text": "【自分のターン中】【ターン1回】ライフが離れた時、自分の手札が7枚以下の場合、カード1枚を引く",
    "when": "on_self_life_taken",
    "if": {
      "self_turn": true,
      "self_hand_le": 7
    },
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "draw": 1
      }
    ]
  },
  {
    "_text": "OP11-041 ナミ 相手アタック時 [DON×1 + ターン1回 + 手札1捨て]: 自リーダー +2000",
    "when": "opp_attack",
    "if": {
      "self_attached_don_ge": 1
    },
    "cost": {
      "once_per_turn": true,
      "discard_hand": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 2000,
          "duration": "battle"
        }
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

## PRB02-008
- name=マルコ / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=特 / color=青 / features=ワノ国/元白ひげ海賊団

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【KO時】カード2枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "マルコ (青ブロッカー) KO時 2ドロー",
    "when": "on_ko",
    "do": [
      {
        "draw": 2
      }
    ]
  }
]
```

## OP11-106
- name=ゼウス / category=CHARACTER / cost=2 / power=2000 / counter=2000 / attribute=特 / color=黄 / features=ホーミーズ/ビッグ・マム海賊団

### 公式テキスト
> 【登場時】自分のライフの上か下から1枚を手札に加えることができる：相手のコスト5以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "ゼウス (黄) 【登場時】コスト5以下キャラKO",
    "when": "on_play",
    "do": [
      {
        "ko": "one_opponent_character_cost_le_5"
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

## OP14-110
- name=ドクトル・ホグバック / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=知 / color=黄 / features=スリラーバーク海賊団
- **trigger**: 【トリガー】自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、レストで登場させる。

### 公式テキスト
> 【KO時】自分のトラッシュから「ドクトル・ホグバック」以外のコスト4以下の【トリガー】を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-110 ホグバック KO時: trashから cost4以下 トリガー持ちキャラ (除く自身) 1を登場",
    "when": "on_ko",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "category": "CHARACTER",
            "cost_le": 4,
            "has_trigger": true,
            "exclude_name": "ドクトル・ホグバック"
          },
          "limit": 1
        }
      }
    ]
  },
  {
    "_text": "trigger: trash から cost4以下 スリラーバーク海賊団 キャラ 1 rested 登場",
    "when": "trigger",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "category": "CHARACTER",
            "cost_le": 4,
            "feature": "スリラーバーク海賊団"
          },
          "limit": 1,
          "rested": true
        }
      }
    ]
  }
]
```

## OP14-111
- name=ペローナ / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=特 / color=黄 / features=スリラーバーク海賊団
- **trigger**: 【トリガー】自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、レストで登場させる。

### 公式テキスト
> 【登場時】/【KO時】相手のコスト6以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。

### 現行 overlay
```json
[
  {
    "_text": "OP14-111 on_play: 相手のコスト6以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。",
    "when": "on_play",
    "do": [
      {
        "set_cannot_attack": {
          "target": "one_opponent_character_cost_le_6cost",
          "duration": "next_opp_turn_end"
        }
      }
    ]
  },
  {
    "_text": "OP14-111 on_ko: 相手のコスト6以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。",
    "when": "on_ko",
    "do": [
      {
        "set_cannot_attack": {
          "target": "one_opponent_character_cost_le_6cost",
          "duration": "next_opp_turn_end"
        }
      }
    ]
  },
  {
    "_text": "OP14-111 trigger: 自分のトラッシュからコスト4以下の特徴《スリラーバーク海賊団》を持つキャラカード1枚までを、レストで登場させる。",
    "when": "trigger",
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "cost_le": 4,
            "feature": "スリラーバーク海賊団"
          },
          "limit": 1,
          "rested": true
        }
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

## OP15-047
- name=サンジ / category=CHARACTER / cost=3 / power=4000 / counter=1000 / attribute=打 / color=青 / features=ドレスローザ/麦わらの一味

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】自分のキャラ1枚までは、このターン中、【ブロック不可】を得る。(このカードはブロックされない)

### 現行 overlay
```json
[
  {
    "_text": "OP15-047 サンジ 登場時: 自キャラ1 ブロック不可 turn",
    "when": "on_play",
    "do": [
      {
        "give_keyword": {
          "target": "one_self_character_any",
          "keyword": "ブロック不可"
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

## EB03-055
- name=ニコ・ロビン / category=CHARACTER / cost=7 / power=8000 / counter=- / attribute=打 / color=黄 / features=麦わらの一味

### 公式テキスト
> 【登場時】自分のライフの上から1枚をトラッシュに置くことができる：自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のデッキの上から2枚までを、ライフの上に加える。【相手のターン中】【KO時】相手に1ダメージを与えてもよい。

### 現行 overlay
```json
[
  {
    "_text": "EB03-055 on_play: 自分のライフの上から1枚をトラッシュに置くことができる：自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のデッキの上から2枚までを、ライフの上に加える。【相",
    "when": "on_play",
    "do": [
      {
        "put_top_to_life": 2
      },
      {
        "mill_self_life_to_trash": 1
      }
    ],
    "conditions": [
      {
        "leader_feature": "麦わらの一味"
      },
      {
        "opp_turn": true
      }
    ],
    "if": {
      "leader_feature": "麦わらの一味"
    }
  },
  {
    "_text": "EB03-055 on_ko: 相手に1ダメージを与えてもよい。",
    "when": "on_ko",
    "do": [
      {
        "deal_opp_leader_damage": 1
      }
    ]
  },
  {
    "_text": "EB03-055 ロビン 相手ターン中 自KO時: 相手に 1 ダメージ",
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
        "mill_opp_life_to_trash": 1
      }
    ]
  }
]
```

## OP13-042
- name=エドワード・ニューゲート / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=特 / color=青 / features=四皇/白ひげ海賊団

### 公式テキスト
> 【ブロッカー】【登場時】カード2枚を引き、自分の手札1枚を捨てる。その後、自分のリーダーとキャラ1枚にレストのドン‼2枚ずつまでを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "OP13-042 白ひげ 登場時: 2ドロー + 1捨て + 自リーダーとキャラ1にレストドン2ずつ",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 1
      },
      {
        "attach_don": {
          "target": "self_leader",
          "count": 2,
          "rested": true
        }
      },
      {
        "attach_don": {
          "target": "one_self_character_any",
          "count": 2,
          "rested": true
        }
      }
    ]
  }
]
```

## OP06-104
- name=菊之丞 / category=CHARACTER / cost=4 / power=6000 / counter=- / attribute=斬 / color=黄 / features=ワノ国/赤鞘九人男
- **trigger**: 【トリガー】相手のライフが3枚以下の場合、このカードを登場させる。

### 公式テキスト
> 【KO時】相手のライフが3枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP06-104 菊之丞 KO時: 相手ライフ3以下なら デッキ上1をライフへ",
    "when": "on_ko",
    "if": {
      "opp_life_le": 3
    },
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  },
  {
    "_text": "trigger: 相手ライフ≤3 で 自身登場",
    "when": "trigger",
    "if": {
      "opp_life_le": 3
    },
    "do": [
      {
        "play_self": true
      }
    ]
  }
]
```

## OP06-059
- name=ホワイトスネーク / category=EVENT / cost=2 / power=- / counter=- / color=青 / features=海軍
- **trigger**: 【トリガー】自分のデッキの上から5枚を見て、好きな順番に並び替え、デッキの上か下に置く。

### 公式テキスト
> 【カウンター】自分のリーダーかキャラ1枚までを、このターン中、パワー+1000し、カード1枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "ホワイトスネーク カウンター: +1000 + 1ドロー",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 1000,
          "duration": "battle"
        }
      },
      {
        "draw": 1
      }
    ]
  },
  {
    "_text": "trigger: 自デッキ上5枚 並び替え (上 or 下)",
    "when": "trigger",
    "do": [
      {
        "scry_deck_reorder": {
          "depth": 5
        }
      }
    ]
  }
]
```
