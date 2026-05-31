# LLM overlay 監査素材: tcgportal_corazon

カード数: 17

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP12-061
- name=ドンキホーテ・ロシナンテ / category=LEADER / power=5000 / counter=- / attribute=特 / color=紫/黄 / features=海軍/ドンキホーテ海賊団

### 公式テキスト
> 【ターン1回】自分の「トラファルガー・ロー」がKOされる場合、代わりに自分のライフの上から1枚を手札に加えることができる。【起動メイン】【ターン1回】ドン‼-1：このターン中、次に自分が手札から登場させるコスト4以上の「トラファルガー・ロー」の支払うコストは2少なくなる。

### 現行 overlay
```json
[
  {
    "_text": "OP12-061 activate_main: 【ターン1回】ドン‼-1：このターン中、次に自分が手札から登場させるコスト4以上の「トラファルガー・ロー」の支払うコストは2少なくなる。",
    "when": "activate_main",
    "do": [
      {
        "reduce_play_cost": 2
      }
    ],
    "cost": {
      "once_per_turn": true,
      "pay_don": 1
    }
  }
]
```

## OP12-108
- name=ドンキホーテ・ロシナンテ / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=特 / color=黄 / features=海軍/ドンキホーテ海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から5枚を見て、「トラファルガー・ロー」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP12-108 on_play: 自分のデッキの上から5枚を見て、「トラファルガー・ロー」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 5,
          "filter": {
            "name": "トラファルガー・ロー"
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

## EB04-038
- name=ロシナンテ＆ロー / category=CHARACTER / cost=6 / power=8000 / counter=- / attribute=特/知 / color=紫 / features=海軍/ドンキホーテ海賊団

### 公式テキスト
> ルール上、このカードはカード名を「トラファルガー・ロー」と「ドンキホーテ・ロシナンテ」としても扱う。【ブロッカー】【登場時】自分の場のドン‼が相手の場のドン‼の枚数以下の場合、カード1枚を引く。その後、ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 現行 overlay
```json
[
  {
    "_text": "EB04-038 on_play: 自分の場のドン‼が相手の場のドン‼の枚数以下の場合、カード1枚を引く。その後、ドン!!デッキからドン!!1枚までを、アクティブで追加する。",
    "when": "on_play",
    "do": [
      {
        "draw": 1
      },
      {
        "add_don": 1
      }
    ],
    "if": {
      "don_diff_le": 0
    }
  }
]
```

## EB03-062
- name=トラファルガー・ロー / category=CHARACTER / cost=8 / power=6000 / counter=1000 / attribute=斬 / color=黄 / features=ハートの海賊団

### 公式テキスト
> 【速攻】【起動メイン】自分の手札1枚を捨て、このキャラをトラッシュに置くことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、自分の手札からコスト7以下の「トラファルガー・ロー」1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "EB03-062 activate_main: 自分の手札1枚を捨て、このキャラをトラッシュに置くことができる：自分のデッキの上から1枚までを、ライフの上に加える。その後、自分の手札からコスト7以下の「トラフ",
    "when": "activate_main",
    "do": [
      {
        "put_top_to_life": 1
      }
    ],
    "cost": {
      "trash_self": true,
      "discard_hand": 1
    }
  }
]
```

## OP12-115
- name=愛してるぜ!! / category=EVENT / cost=1 / power=- / counter=- / color=黄 / features=海軍/ドンキホーテ海賊団

### 公式テキスト
> 【カウンター】自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、自分のライフが2枚以下の場合、自分のトラッシュから「トラファルガー・ロー」1枚までを、手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP12-115 カウンター 1/2: 自リーダー or キャラ +2000 battle (無条件)",
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
    "_text": "OP12-115 カウンター 2/2: 自ライフ2以下 で トラッシュ から 「トラファルガー・ロー」 1 を 手札 へ",
    "when": "counter",
    "if": {
      "self_life_le": 2
    },
    "do": [
      {
        "search_from_trash": {
          "filter": {
            "name": "トラファルガー・ロー",
            "category": "CHARACTER"
          },
          "count": 1
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

## OP12-073
- name=トラファルガー・ロー / category=CHARACTER / cost=7 / power=8000 / counter=- / attribute=斬 / color=紫 / features=ドレスローザ/超新星/ハートの海賊団

### 公式テキスト
> 【登場時】自分の場のドン‼が相手の場のドン‼の枚数以下の場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。その後、自分の、「ドンキホーテ・ロシナンテ」と特徴《ハートの海賊団》を持つキャラすべてを、次の相手のエンドフェイズ終了時まで、パワー+1000。

### 現行 overlay
```json
[
  {
    "_text": "OP12-073 on_play: 自分の場のドン‼が相手の場のドン‼の枚数以下の場合、ドン‼デッキからドン‼1枚までを、アクティブで追加する。その後、自分の、「ドンキホーテ・ロシナンテ」と特徴《",
    "when": "on_play",
    "do": [
      {
        "add_don": 1
      },
      {
        "power_pump": {
          "target": {
            "type": "all_self_chara_filtered",
            "filter": {
              "or": [
                {
                  "name": "ドンキホーテ・ロシナンテ"
                },
                {
                  "feature": "ハートの海賊団"
                }
              ]
            }
          },
          "amount": 1000,
          "duration": "next_opp_turn_end"
        }
      }
    ],
    "if": {
      "don_diff_le": 0
    }
  }
]
```

## OP09-069
- name=トラファルガー・ロー / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=斬 / color=紫 / features=ハートの海賊団

### 公式テキスト
> 【登場時】自分のデッキの上から4枚を見て、コスト2以上の、特徴《麦わらの一味》か《ハートの海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置く。

### 現行 overlay
```json
[
  {
    "_text": "OP09-069 on_play: 自分のデッキの上から4枚を見て、コスト2以上の、特徴《麦わらの一味》か《ハートの海賊団》を持つカード1枚までを公開し、手札に加える。その後、残りを好きな順番でデ",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "feature_in": [
              "麦わらの一味",
              "ハートの海賊団"
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

## OP05-077
- name=ガンマナイフ / category=EVENT / cost=2 / power=- / counter=- / color=紫 / features=ハートの海賊団
- **trigger**: 【トリガー】ドン!!デッキからドン!!1枚までを、アクティブで追加する。

### 公式テキスト
> 【メイン】ドン!!-1(自分の場のドン!!を指定の数ドン!!デッキに戻すことができる)：相手のキャラ1枚までを、このターン中、パワー-5000。

### 現行 overlay
```json
[
  {
    "_text": "OP05-077 ガンマナイフ メイン: ドン-1 → 相手キャラ1 -5000 turn",
    "when": "main",
    "cost": {
      "pay_don": 1
    },
    "do": [
      {
        "power_pump": {
          "target": "one_opponent_character_any",
          "amount": -5000,
          "duration": "turn"
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

## OP14-078
- name=弾糸 / category=EVENT / cost=2 / power=- / counter=- / color=紫 / features=王下七武海/ドンキホーテ海賊団

### 公式テキスト
> 【カウンター】ドン‼-1：自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、そのカードを、このターン中、パワー+2000。

### 現行 overlay
```json
[
  {
    "_text": "OP14-078 counter: ドン‼-1：自分のリーダーが特徴《ドンキホーテ海賊団》を持つ場合、自分のリーダーかキャラ1枚までを、このバトル中、パワー+2000。その後、そのカードを、このタ",
    "when": "counter",
    "do": [
      {
        "power_pump": {
          "target": "self_inplay",
          "amount": 2000,
          "duration": "battle"
        }
      }
    ],
    "cost": {
      "pay_don": 1
    },
    "if": {
      "leader_feature": "ドンキホーテ海賊団"
    }
  }
]
```

## OP12-077
- name=“お前の影響で出る音は全て消えるの術”だ / category=EVENT / cost=2 / power=- / counter=- / color=紫 / features=ハートの海賊団
- **trigger**: 【トリガー】カード1枚を引く。

### 公式テキスト
> 【メイン】自分の「トラファルガー・ロー」1枚までを選び、このターン中、パワー+2000。その後、相手は、このターン中、選んだカードがアタックする場合【ブロッカー】を発動できない。

### 現行 overlay
```json
[
  {
    "_text": "OP12-077 main: 自分の「トラファルガー・ロー」1枚までを選び、このターン中、パワー+2000。その後、相手は、このターン中、選んだカードがアタックする場合【ブロッカー】を発動で",
    "when": "main",
    "do": [
      {
        "power_pump": {
          "target": {
            "type": "one_self_chara_filtered",
            "filter": {
              "name": "トラファルガー・ロー"
            }
          },
          "amount": 2000,
          "duration": "turn"
        }
      },
      {
        "prevent_blocker_for_attacker": {
          "target": {
            "type": "one_self_chara_filtered",
            "filter": {
              "name": "トラファルガー・ロー"
            }
          }
        }
      }
    ]
  },
  {
    "_text": "OP12-077 trigger: カード1枚を引く。",
    "when": "trigger",
    "do": [
      {
        "draw": 1
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

## EB04-056
- name=パシフィスタ / category=CHARACTER / cost=1 / power=1000 / counter=2000 / attribute=特 / color=黄 / features=生物兵器/エッグヘッド/海軍

### 公式テキスト
> 自分の「ジュエリー・ボニー」がいて、自分のライフが0枚の場合、このキャラは【ブロッカー】を得る。(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)

### 現行 overlay
```json
[
  {
    "_text": "EB04-056 パシフィスタ 常在: 自分の「ジュエリー・ボニー」がいて、自分のライフが0枚の場合、このキャラは【ブロッカー】を得る",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_chara_filtered_count_ge": {
        "filter": {
          "name": "ジュエリー・ボニー"
        },
        "count": 1
      },
      "self_life_le": 0
    },
    "do": [
      {
        "give_keyword": {
          "target": "self",
          "keyword": "ブロッカー"
        }
      }
    ]
  }
]
```

## EB02-032
- name=アイスバーグ / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=知 / color=紫 / features=W7/GC

### 公式テキスト
> 【登場時】自分の場のドン‼が3枚以上ある場合、自分のデッキの上から7枚を見て、「ガレーラカンパニー」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に置き、自分の手札から「ガレーラカンパニー」1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "EB02-032 on_play: 自分の場のドン‼が3枚以上ある場合、自分のデッキの上から7枚を見て、「ガレーラカンパニー」1枚までを公開し、手札に加える。その後、残りを好きな順番でデッキの下に",
    "when": "on_play",
    "do": [
      {
        "search_top_n": {
          "depth": 7,
          "filter": {
            "name": "ガレーラカンパニー"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "bottom"
        }
      }
    ],
    "if": {
      "self_don_ge": 3
    }
  }
]
```
