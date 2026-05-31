# LLM overlay 監査素材: tcgportal_calgara

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP08-098
- name=カルガラ / category=LEADER / power=5000 / counter=- / attribute=斬 / color=黄 / features=ジャヤ/空島/シャンドラの戦士

### 公式テキスト
> 【ドン‼×1】【アタック時】自分の手札から自分の場のドン‼の枚数以下のコストを持ち、特徴《シャンドラの戦士》を持つキャラカード1枚までを、登場させる。登場させた場合、自分のライフの上から1枚を手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP08-098 on_attack: 自分の手札から自分の場のドン‼の枚数以下のコストを持ち、特徴《シャンドラの戦士》を持つキャラカード1枚までを、登場させる。登場させた場合、自分のライフの上から1",
    "when": "on_attack",
    "do": [
      {
        "life_to_hand": 1
      }
    ]
  }
]
```

## OP15-101
- name=カルガラ / category=CHARACTER / cost=3 / power=5000 / counter=- / attribute=斬 / color=黄 / features=ジャヤ/空島/シャンドラの戦士

### 公式テキスト
> 【登場時】自分の手札1枚を捨てることができる：自分のデッキの上から5枚を見て、「モンブラン・ノーランド」か特徴《シャンドラの戦士》を持つカード合計2枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-101 on_play: 自分の手札1枚を捨てることができる：自分のデッキの上から5枚を見て、「モンブラン・ノーランド」か特徴《シャンドラの戦士》を持つカード合計2枚までを公開し、手札に",
    "when": "on_play",
    "do": [
      {
        "trash_self_hand_random": 1
      },
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "シャンドラの戦士",
            "name": "モンブラン・ノーランド"
          },
          "limit": 2,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ],
    "cost": {
      "discard_hand": 1
    }
  }
]
```

## OP08-110
- name=ワイパー / category=CHARACTER / cost=4 / power=5000 / counter=2000 / attribute=射 / color=黄 / features=空島/シャンドラの戦士

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、「アッパーヤード」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置き、自分の手札から「アッパーヤード」1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP08-110 on_play: 自分のデッキの上から5枚を見て、「アッパーヤード」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置き、自分の手札から「アッパーヤード」1",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "name": "アッパーヤード"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      },
      {
        "play_from_hand": {
          "filter": {
            "name": "アッパーヤード"
          },
          "limit": 1
        }
      }
    ]
  }
]
```

## OP15-114
- name=ワイパー / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=射 / color=黄 / features=空島/シャンドラの戦士

### 公式テキスト
> 【登場時】自分のライフの上から1枚を表向きにできる：相手のキャラすべてを、このターン中、パワー-2000。その後、相手のパワー0以下のキャラすべてを、KOする。【起動メイン】【ターン1回】自分の特徴《空島》を持つ、リーダーかキャラ1枚にレストのドン‼1枚までを、付与する。

### 現行 overlay
```json
[
  {
    "_text": "OP15-114 on_play: 自分のライフの上から1枚を表向きにできる：相手のキャラすべてを、このターン中、パワー-2000。その後、相手のパワー0以下のキャラすべてを、KOする。",
    "when": "on_play",
    "do": [
      {
        "power_pump": {
          "target": "all_opponent_characters",
          "amount": -2000,
          "duration": "turn"
        }
      },
      {
        "ko": "one_opponent_character_power_le_0"
      }
    ]
  },
  {
    "_text": "ワイパー (黄 cost5) 起動メイン: 空島キャラにドン1付与",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true
    },
    "do": [
      {
        "attach_don": {
          "target": "self_leader",
          "count": 1
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

## OP08-109
- name=モンブラン・ノーランド / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=斬 / color=黄 / features=ジャヤ/植物学者

### 公式テキスト
> 【登場時】自分のリーダーが特徴《シャンドラの戦士》を持ち、自分のキャラの「カルガラ」がいる場合、自分のデッキの上から1枚までを、ライフの上に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP08-109 on_play: 自分のリーダーが特徴《シャンドラの戦士》を持ち、自分のキャラの「カルガラ」がいる場合、自分のデッキの上から1枚までを、ライフの上に加える。",
    "when": "on_play",
    "do": [
      {
        "put_top_to_life": 1
      }
    ]
  }
]
```

## OP12-099
- name=カルガラ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=斬 / color=黄 / features=ジャヤ/空島/シャンドラの戦士

### 公式テキスト
> 【自分のターン中】ライフが離れた時、カード1枚を引く。その後、自分は、このターン中、自分の効果でカードを引くことができない。

### 現行 overlay
```json
[
  {
    "_text": "OP12-099 カルガラ 自ターン中ライフ離れた時: 1ドロー, ターン中 自効果ドロー禁止",
    "when": "on_self_life_lost",
    "if": {
      "self_turn": true
    },
    "do": [
      {
        "draw": 1
      },
      {
        "block_self_draw_turn": true
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

## OP12-114
- name=ワイパー / category=CHARACTER / cost=6 / power=7000 / counter=2000 / attribute=射 / color=黄 / features=空島/シャンドラの戦士

### 公式テキスト
> -

### 現行 overlay
`[]` (効果なし = バニラ / ブロッカーのみ / パラレル空 でマーク済)

## OP05-117
- name=アッパーヤード / category=STAGE / cost=1 / power=- / counter=- / color=黄 / features=空島

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、特徴《空島》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP05-117 on_play: 自分のデッキの上から5枚を見て、特徴《空島》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "空島"
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

## OP15-108
- name=ナミ / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=特 / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 【登場時】自分のデッキの上から3枚を見て、特徴《空島》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP15-108 ナミ 登場時: デッキ上3を見て 空島1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "空島"
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

## OP08-115
- name=大地は敗けない!!! / category=EVENT / cost=1 / power=- / counter=- / color=黄 / features=空島/シャンドラの戦士
- **trigger**: 【トリガー】カード2枚を引き、自分の手札1枚を捨てる。

### 公式テキスト
> 【カウンター】自分のリーダーが特徴《シャンドラの戦士》を持つ場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。その後、自分の手札から「アッパーヤード」1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP08-115 counter: 自分のリーダーが特徴《シャンドラの戦士》を持つ場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+3000。その後、自分の手札から「アッパーヤード」1",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 3000,
          "duration": "battle"
        }
      }
    ],
    "if": {
      "leader_feature": "シャンドラの戦士"
    }
  },
  {
    "_text": "OP08-115 trigger: カード2枚を引き、自分の手札1枚を捨てる。",
    "when": "trigger",
    "do": [
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP08-099
- name=カルガラ / category=CHARACTER / cost=6 / power=8000 / counter=1000 / attribute=斬 / color=黄 / features=ジャヤ/空島/シャンドラの戦士

### 公式テキスト
> -

### 現行 overlay
`[]` (効果なし = バニラ / ブロッカーのみ / パラレル空 でマーク済)

## OP05-106
- name=シュラ / category=CHARACTER / cost=2 / power=2000 / counter=1000 / attribute=斬 / color=黄 / features=空島/神官
- **trigger**: 【トリガー】このカードを登場させる。

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、「シュラ」以外の特徴《空島》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP05-106 シュラ 登場時: デッキ上5を見て 空島 (除く自身) 1を手札 残デッキ底",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "空島",
            "exclude_card_id": "OP05-106"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ]
  },
  {
    "_text": "trigger: 自身登場 (play_self)",
    "when": "trigger",
    "do": [
      {
        "play_self": true
      }
    ]
  }
]
```

## OP15-119
- name=モンキー・Ｄ・ルフィ / category=CHARACTER / cost=5 / power=7000 / counter=- / attribute=打 / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 自分の場のドン‼が6枚以上ある場合、このキャラは【速攻】を得る。相手がイベントか【ブロッカー】を発動した時、自分のライフの上から1枚までを公開する。公開したカードのコスト1につき、このキャラは、このターン中、パワー+1000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-119 on_attached_don n=6: 自ドン6+で 自身に速攻 (static)",
    "when": "on_attached_don",
    "n": 6,
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "速攻"
        }
      }
    ]
  },
  {
    "_text": "OP15-119 opp_event_or_trigger_fired: 相手イベント/ブロッカー発動時 → 空島キャラ1枚にレストドン1付与 (※ ブロッカー発動は trigger 系では拾えない、 イベント or トリガー のみ)",
    "when": "opp_event_or_trigger_fired",
    "do": [
      {
        "attach_rested_don": {
          "target": {
            "type": "one_self_chara_filtered",
            "filter": {
              "feature": "空島"
            }
          },
          "count": 1
        }
      }
    ]
  }
]
```
