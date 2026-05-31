# LLM overlay 監査素材: cardrush_1455

カード数: 15

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP15-098
- name=モンキー・Ｄ・ルフィ / category=LEADER / power=5000 / counter=- / attribute=打 / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 自分の元々のパワー6000以上の特徴《空島》を持つキャラが相手によって場を離れる場合、代わりに自分のライフの上から1枚を手札に加えることができる。

### 現行 overlay
```json
[
  {
    "_text": "空島ルフィ replace_ko: 空島P6000+ が相手効果で離れる時、代わりにライフ手札",
    "when": "replace_ko",
    "if": {
      "target": "any_self_chara",
      "target_feature": "空島",
      "target_power_ge": 6000,
      "by_opp_effect": true
    },
    "do": [
      {
        "life_to_hand": 1
      }
    ],
    "optional": true
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

## EB03-056
- name=ベロ・ベティ / category=CHARACTER / cost=4 / power=3000 / counter=2000 / attribute=特 / color=黄 / features=革命軍

### 公式テキスト
> 【登場時】自分のライフの上から1枚を表向きにできる：相手の元々のコスト3以下のキャラ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "EB03-056 on_play: 自分のライフの上から1枚を表向きにできる：相手の元々のコスト3以下のキャラ1枚までを、KOする。",
    "when": "on_play",
    "do": [
      {
        "ko": "one_opponent_character_cost_le_3cost"
      }
    ]
  }
]
```

## OP15-102
- name=ガン・フォール / category=CHARACTER / cost=4 / power=4000 / counter=2000 / attribute=斬 / color=黄 / features=空島

### 公式テキスト
> 手札のこのカードは、自分のパワー7000以上の特徴《空島》を持つキャラがいる場合、コスト-3。【登場時】相手のライフの枚数以下のコストを持つ相手のキャラ1枚までを、レストにする。

### 現行 overlay
```json
[
  {
    "_text": "OP15-102 on_play: 相手のライフの枚数以下のコストを持つ相手のキャラ1枚までを、レストにする。",
    "when": "on_play",
    "do": [
      {
        "rest": "one_opponent_character_any"
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

## OP15-109
- name=ニコ・ロビン / category=CHARACTER / cost=7 / power=7000 / counter=1000 / attribute=打 / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 【登場時】自分のライフの上から1枚を手札に加えることができる：自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のデッキの上から1枚までを、ライフの上に加える。その後、自分の手札からコスト5以下の特徴《空島》を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP15-109 on_play: 自分のライフの上から1枚を手札に加えることができる：自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のデッキの上から1枚までを、ライフの上に加える。その後、",
    "when": "on_play",
    "do": [
      {
        "life_to_hand": 1
      },
      {
        "put_top_to_life": 1
      },
      {
        "play_from_hand": {
          "filter": {
            "cost_le": 5,
            "feature": "空島"
          },
          "limit": 1
        }
      }
    ],
    "if": {
      "leader_feature": "麦わらの一味"
    }
  }
]
```

## EB02-052
- name=エネル / category=CHARACTER / cost=10 / power=11000 / counter=- / attribute=特 / color=黄 / features=空島

### 公式テキスト
> 自分のリーダーが特徴《空島》を持つ場合、このキャラは【速攻】を得る。【アタック時】自分の手札1枚を捨てることができる：自分のライフが1枚以下の場合、自分のデッキの上から1枚までを、ライフの上に加える。その後、このキャラは、このターン中、パワー+1000。

### 現行 overlay
```json
[
  {
    "_text": "EB02-052 エネル 常在: 自リーダー空島で self に【速攻】",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "leader_feature": "空島"
    },
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
    "_text": "EB02-052 エネル アタック時: 1捨てで 自ライフ1以下なら デッキ上1をライフ追加 + self +1000 turn",
    "when": "on_attack",
    "cost": {
      "discard_hand": 1
    },
    "if": {
      "self_life_le": 1
    },
    "do": [
      {
        "put_top_to_life": 1
      },
      {
        "power_pump": {
          "target": "self",
          "amount": 1000,
          "duration": "turn"
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

## OP15-116
- name=ゴムゴムの黄金回転弾 / category=EVENT / cost=1 / power=- / counter=- / color=黄 / features=空島/麦わらの一味

### 公式テキスト
> 【メイン】自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のライフの上から1枚をトラッシュに置く。その後、自分のデッキの上から1枚までを、ライフの上に加え、自分の手札1枚を捨てる。【カウンター】自分のリーダーを、このバトル中、パワー+4000。

### 現行 overlay
```json
[
  {
    "_text": "OP15-116 メイン: 麦わらリーダーで 自ライフ1をトラッシュ + デッキ上1をライフ + 1捨て",
    "when": "main",
    "if": {
      "leader_feature": "麦わらの一味"
    },
    "do": [
      {
        "mill_self_life_to_trash": 1
      },
      {
        "put_top_to_life": 1
      },
      {
        "trash_self_hand_random": 1
      }
    ]
  },
  {
    "_text": "OP15-116 カウンター: 自リーダー +4000 battle",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_leader",
          "amount": 4000,
          "duration": "battle"
        }
      }
    ]
  }
]
```

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
