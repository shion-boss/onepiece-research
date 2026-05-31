# LLM overlay 監査素材: tcgportal_op11_luffy

カード数: 14

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP11-040
- name=モンキー・Ｄ・ルフィ / category=LEADER / power=6000 / counter=- / attribute=打 / color=青/紫 / features=麦わらの一味

### 公式テキスト
> 自分のターン開始時、発動できる。自分の場のドン‼が8枚以上ある場合、自分のデッキの上から5枚を見て、特徴《麦わらの一味》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番に並び替え、デッキの上か下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP11-040 on_attached_don (パターン未一致): 自分のターン開始時、発動できる。自分の場のドン‼が8枚以上ある場合、自分のデッキの上から5枚を見て、特徴《麦わらの一味》を持つカード1枚までを公開し、手札に加え",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "feature": "麦わらの一味"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "top_or_bottom"
        }
      }
    ],
    "if": {
      "self_don_ge": 8
    }
  }
]
```

## OP13-043
- name=お玉 / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=特 / color=青 / features=ワノ国

### 公式テキスト
> 【登場時】自分のライフが3枚以下の場合、カード2枚を引き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP13-043 お玉 登場時: 自ライフ3以下なら 2ドロー + 1捨て",
    "when": "on_play",
    "if": {
      "self_life_le": 3
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

## EB01-061
- name=Mr.2・ボン・クレー(ベンサム) / category=CHARACTER / cost=4 / power=1000 / counter=1000 / attribute=特 / color=紫 / features=元B・W

### 公式テキスト
> 【登場時】ドン!!デッキからドン!!1枚までを、アクティブで追加する。【アタック時】相手のキャラ1枚までを選ぶ。このキャラの元々のパワーは、このターン中、選んだキャラと同じパワーになる。

### 現行 overlay
```json
[
  {
    "_text": "EB01-061 Mr.2 on_play: ドン!!デッキからドン!!1枚までを、アクティブで追加する",
    "when": "on_play",
    "do": [
      {
        "add_don": 1
      }
    ]
  },
  {
    "_text": "EB01-061 Mr.2 on_attack: 相手のキャラ1枚までを選ぶ。このキャラの元々のパワーは、このターン中、選んだキャラと同じパワーになる",
    "when": "on_attack",
    "do": [
      {
        "set_base_power_copy": {
          "from_target": "one_opponent_character_any",
          "to_target": "self",
          "duration": "turn"
        }
      }
    ]
  }
]
```

## OP11-054
- name=ナミ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=青 / features=麦わらの一味

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】自分のリーダーが多色の場合、カード3枚を引き、自分の手札2枚を好きな順番に並び替え、デッキの上か下に置く。

### 現行 overlay
```json
[
  {
    "_text": "ナミ (青黄 cost5) ブロッカー+登場時 (多色リーダー) 3ドロー2並び替え",
    "when": "on_play",
    "if": {
      "leader_color": "多色"
    },
    "do": [
      {
        "draw": 3
      }
    ]
  }
]
```

## OP06-119
- name=サンジ / category=CHARACTER / cost=9 / power=9000 / counter=- / attribute=打 / color=青 / features=麦わらの一味

### 公式テキスト
> 【登場時】自分のデッキの上から1枚を公開し、「サンジ」以外のコスト9以下のキャラ1枚までを、登場させる。その後、残りをデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP06-119 on_play: 自分のデッキの上から1枚を公開し、「サンジ」以外のコスト9以下のキャラ1枚までを、登場させる。その後、残りをデッキの下に置く。",
    "when": "on_play",
    "do": [
      {
        "reveal_top_play": {
          "filter": {
            "cost_le": 9,
            "exclude_name": "サンジ"
          },
          "rest_remain": "bottom"
        }
      }
    ]
  }
]
```

## OP09-078
- name=ゴムゴムの巨人 / category=EVENT / cost=1 / power=- / counter=- / color=紫 / features=四皇/麦わらの一味

### 公式テキスト
> 【カウンター】ドン!!-2,自分の手札1枚を捨てることができる：自分のリーダーが特徴《麦わらの一味》を持つ場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+4000。その後、カード2枚を引く。

### 現行 overlay
```json
[
  {
    "_text": "OP09-078 ゴムゴムの巨人 カウンター: ドン-2 + 1捨て → 麦わらリーダーで +4000 + 2ドロー",
    "when": "counter",
    "cost": {
      "pay_don": 2,
      "discard_hand": 1
    },
    "if": {
      "leader_feature": "麦わらの一味"
    },
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 4000,
          "duration": "battle"
        }
      },
      {
        "draw": 2
      }
    ]
  }
]
```

## OP11-080
- name=ギア2 / category=EVENT / cost=1 / power=- / counter=- / color=紫 / features=麦わらの一味

### 公式テキスト
> 【メイン】自分のドン‼2枚をレストにできる：自分のリーダーが青を含む場合、ドン‼デッキからドン‼1枚までを、レストで追加する。【カウンター】自分のリーダー1枚までを、このバトル中、パワー+3000。

### 現行 overlay
```json
[
  {
    "_text": "OP11-080 main: 自分のドン‼2枚をレストにできる：自分のリーダーが青を含む場合、ドン‼デッキからドン‼1枚までを、レストで追加する。",
    "when": "main",
    "do": [
      {
        "add_rested_don": 1
      }
    ],
    "cost": {
      "rest_self_don": 2
    }
  },
  {
    "_text": "OP11-080 counter: 自分のリーダー1枚までを、このバトル中、パワー+3000。",
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

## OP08-076
- name=しぬほど…おいしい♡ / category=EVENT / cost=3 / power=- / counter=- / color=紫 / features=四皇/ビッグ・マム海賊団
- **trigger**: 【トリガー】ドン‼デッキからドン‼1枚までを、アクティブで追加する。

### 公式テキスト
> 【メイン】ドン‼デッキからドン‼1枚までを、アクティブで追加する。その後、相手のパワー6000以上のキャラがいる場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "【メイン】ドン!!デッキからドン!!1枚を追加。その後、相手のパワー6000以上のキャラがいる場合、追加で1枚",
    "when": "main",
    "do": [
      {
        "add_don": 1
      },
      {
        "add_don": 1,
        "_chain": "if_prev_succeeded",
        "_condition": {
          "opp_chara_power_ge": 6000
        }
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

## OP05-067
- name=ゾロ十郎 / category=CHARACTER / cost=3 / power=4000 / counter=1000 / attribute=斬 / color=紫 / features=麦わらの一味

### 公式テキスト
> 【アタック時】自分のライフが3枚以下の場合、ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "OP05-067 on_attack: 自分のライフが3枚以下の場合、ドン!!デッキからドン!!1枚までを、アクティブで追加する。",
    "when": "on_attack",
    "do": [
      {
        "add_don": 1
      }
    ],
    "if": {
      "self_life_le": 3
    }
  }
]
```

## OP10-072
- name=ドンキホーテ・ロシナンテ / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=紫 / features=海軍/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】自分の手札からイベント1枚を捨てることができる：カード2枚を引く。【自分のターン終了時】自分の場のドン‼が7枚以上ある場合、自分のドン‼2枚までを、アクティブにする。

### 現行 overlay
```json
[
  {
    "_text": "OP10-072 on_play: 自分の手札からイベント1枚を捨てることができる：カード2枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      }
    ]
  },
  {
    "_text": "OP10-072 end_of_turn: 自分の場のドン‼が7枚以上ある場合、自分のドン‼2枚までを、アクティブにする。",
    "when": "end_of_turn",
    "do": [
      {
        "untap_don": 2
      }
    ],
    "if": {
      "self_don_ge": 7
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

## OP03-044
- name=カヤ / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=知 / color=青 / features=東の海

### 公式テキスト
> 【登場時】カード2枚を引き、自分の手札2枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "カヤ on_play: 2ドロー + 2捨て",
    "when": "on_play",
    "do": [
      {
        "draw": 2
      },
      {
        "trash_self_hand_random": 2
      }
    ]
  }
]
```

## OP06-063
- name=ヴィンスモーク・ソラ / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=知 / color=紫 / features=ヴィンスモーク家/ジェルマ王国

### 公式テキスト
> 【登場時】自分の手札1枚を捨てることができる：自分の場のドン !!が相手の場のドン !!の枚数以下の場合、自分のトラッシュのパワー4000以下の特徴《ヴィンスモーク家》を持つキャラカード1枚までを、手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP06-063 on_play: 自分の手札1枚を捨てることができる：自分の場のドン !!が相手の場のドン !!の枚数以下の場合、自分のトラッシュのパワー4000以下の特徴《ヴィンスモーク家》を",
    "when": "on_play",
    "do": [
      {
        "trash_self_hand_random": 1
      }
    ],
    "cost": {
      "discard_hand": 1
    }
  }
]
```
