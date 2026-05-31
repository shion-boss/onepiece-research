# LLM overlay 監査素材: cardrush_1385

カード数: 17

各カードで 公式テキスト の 全 節 が overlay に 忠実 反映 されて いるか、 公式 に ない 効果 が 混入 して いないか、 条件/対象/数値/タイミング が 正確か を 監査 する。

---

## OP14-079
- name=クロコダイル / category=LEADER / power=5000 / counter=- / attribute=特 / color=黒 / features=王下七武海/B・W

### 公式テキスト
> 相手のキャラすべては、自分の効果で場を離れない。【起動メイン】【ターン1回】自分の『B・W』を含む特徴を持つキャラ1枚をKOできる：相手のキャラ1枚までを、このターン中、コスト-10。その後、自分のデッキの上から2枚をトラッシュに置いてもよい。

### 現行 overlay
```json
[
  {
    "_text": "黒クロコダイル 常在: 相手キャラは自分の効果で離れない",
    "when": "on_attached_don",
    "n": 0,
    "do": [
      {
        "set_opp_protect_static": true
      }
    ]
  },
  {
    "_text": "黒クロコダイル 起動メイン: BWキャラKO代償 → 5000以下KO + 2ミル",
    "when": "activate_main",
    "cost": {
      "once_per_turn": true,
      "ko_self_with_filter": {
        "feature": "B・W"
      }
    },
    "do": [
      {
        "ko": "all_opponent_characters"
      },
      {
        "mill": {
          "target": "self",
          "count": 2
        }
      }
    ]
  }
]
```

## OP14-083
- name=ミス・ウェンズデー / category=CHARACTER / cost=1 / power=1000 / counter=2000 / attribute=斬 / color=黒 / features=B・W

### 公式テキスト
> 【起動メイン】このキャラをトラッシュに置くことができる：相手のコスト0のキャラ1枚までを、このターン中、パワー-3000。

### 現行 overlay
```json
[
  {
    "_text": "OP14-083 activate_main: このキャラをトラッシュに置くことができる：相手のコスト0のキャラ1枚までを、このターン中、パワー-3000。",
    "when": "activate_main",
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
              "power_pump": {
                "target": "one_opponent_character_cost_le_0cost",
                "amount": -3000,
                "duration": "turn"
              }
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

## OP14-085
- name=ミス・ゴールデンウィーク(マリアンヌ) / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=知 / color=黒 / features=B・W

### 公式テキスト
> 【KO時】カード2枚を引き、自分の手札2枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "マリアンヌ on_ko: 2ドロー + 2捨て",
    "when": "on_ko",
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

## OP14-087
- name=ミス・バレンタイン(ミキータ) / category=CHARACTER / cost=1 / power=2000 / counter=1000 / attribute=打 / color=黒 / features=B・W

### 公式テキスト
> 【登場時】自分のリーダーが『B・W』を含む特徴を持つ場合、デッキの上から4枚を見て、「ミス・バレンタイン(ミキータ)」以外の『B・W』を含む特徴を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシュに置く。

### 現行 overlay
```json
[
  {
    "_text": "OP14-087 バレンタイン 登場時: BWリーダーで デッキ上4を見て BW (除く自身) 1を手札、 残りtrash",
    "when": "on_play",
    "if": {
      "leader_features_any": [
        "B・W"
      ]
    },
    "do": [
      {
        "search_top_n": {
          "depth": 4,
          "filter": {
            "feature": "B・W",
            "exclude_card_id": "OP14-087"
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

## OP14-088
- name=ミス・メリークリスマス(ドロフィー) / category=CHARACTER / cost=1 / power=2000 / counter=2000 / attribute=斬 / color=黒 / features=B・W

### 公式テキスト
> 【KO時】自分のリーダーが『B・W』を含む特徴を持つ場合、カード1枚を引き、相手のコスト1のステージ1枚までを、KOする。

### 現行 overlay
```json
[
  {
    "_text": "OP14-088 ドロフィー KO時: BWリーダーで 1ドロー + 相手cost1ステージ1 KO",
    "when": "on_ko",
    "if": {
      "leader_features_any": [
        "B・W"
      ]
    },
    "do": [
      {
        "draw": 1
      },
      {
        "ko_opp_stage": {
          "cost": 1,
          "limit": 1
        }
      }
    ]
  }
]
```

## OP14-091
- name=Mr.2・ボン・クレー(ベンサム) / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=打 / color=黒 / features=B・W

### 公式テキスト
> 【KO時】自分の手札かトラッシュから「Mr.2・ボン・クレー(ベンサム)」以外のコスト5以下の『B・W』を含む特徴を持つキャラカード1枚までを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-091 on_ko: 自分の手札かトラッシュから「Mr.2・ボン・クレー(ベンサム)」以外のコスト5以下の『B・W』を含む特徴を持つキャラカード1枚までを、登場させる。",
    "when": "on_ko",
    "do": [
      {
        "play_from_hand_or_trash": {
          "filter": {
            "category": "CHARACTER",
            "cost_le": 5,
            "exclude_name": "Mr.2・ボン・クレー(ベンサム)",
            "feature": "B・W"
          },
          "limit": 1
        }
      }
    ]
  }
]
```

## OP14-093
- name=Mr.4(ベーブ) / category=CHARACTER / cost=4 / power=5000 / counter=1000 / attribute=打 / color=黒 / features=B・W

### 公式テキスト
> 【ブロッカー】【KO時】自分のトラッシュからコスト8以下の『B・W』を含む特徴を持つキャラカード1枚までを、手札に加える。

### 現行 overlay
```json
[
  {
    "_text": "OP14-093 on_ko: 自分のトラッシュからコスト8以下の『B・W』を含む特徴を持つキャラカード1枚までを、手札に加える。",
    "when": "on_ko",
    "do": [
      {
        "search": {
          "source": "trash",
          "filter": {
            "category": "CHARACTER",
            "feature_contains": "B・W",
            "cost_le": 8
          },
          "limit": 1,
          "destination": "hand"
        }
      }
    ]
  }
]
```

## OP14-090
- name=Mr.1(ダズ・ボーネス) / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=斬 / color=黒 / features=B・W

### 公式テキスト
> コスト0か8以上のキャラがいる場合、このキャラは登場したターンにキャラへアタックできる。【登場時】相手のコスト0のキャラ1枚までを、レストにする。

### 現行 overlay
```json
[
  {
    "_text": "OP14-090 on_play: 相手のコスト0のキャラ1枚までを、レストにする。",
    "when": "on_play",
    "do": [
      {
        "rest": "one_opponent_character_cost_le_0cost"
      }
    ]
  }
]
```

## OP14-094
- name=Mr.5(ジェム) / category=CHARACTER / cost=5 / power=6000 / counter=1000 / attribute=特 / color=黒 / features=B・W

### 公式テキスト
> 【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)【登場時】コスト0か8以上のキャラがいる場合、カード2枚を引き、自分の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-094 on_play: コスト0か8以上のキャラがいる場合、カード2枚を引き、自分の手札1枚を捨てる。",
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

## OP14-084
- name=ミス・オールサンデー / category=CHARACTER / cost=7 / power=8000 / counter=- / attribute=打 / color=黒 / features=B・W

### 公式テキスト
> 【登場時】自分のリーダーが『B・W』を含む特徴を持つ場合、自分のトラッシュから『B・W』を含む特徴を持つ、コスト4以下と1のキャラカード1枚ずつまでを、登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-084 ミスサンデー 登場時: BWリーダーで trashからBWキャラ cost4以下 と cost1 を1枚ずつ登場",
    "when": "on_play",
    "if": {
      "leader_features_any": [
        "B・W"
      ]
    },
    "do": [
      {
        "play_from_trash": {
          "filter": {
            "feature": "B・W",
            "cost_le": 4
          },
          "limit": 1
        }
      },
      {
        "play_from_trash": {
          "filter": {
            "feature": "B・W",
            "cost": 1
          },
          "limit": 1
        }
      }
    ]
  }
]
```

## OP14-120
- name=クロコダイル / category=CHARACTER / cost=8 / power=10000 / counter=- / attribute=特 / color=黒 / features=王下七武海/B・W

### 公式テキスト
> 【登場時】相手のコスト9以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。その後、相手のコスト0か8以上のキャラがいる場合、カード1枚を引く。【KO時】自分の手札1枚を捨てることができる：このキャラカードをトラッシュから登場させる。

### 現行 overlay
```json
[
  {
    "_text": "OP14-120 on_play: 相手のコスト9以下のキャラ1枚までは、次の相手のエンドフェイズ終了時まで、アタックできない。その後、相手のコスト0か8以上のキャラがいる場合、カード1枚を引く。",
    "when": "on_play",
    "do": [
      {
        "draw": 1
      },
      {
        "set_cannot_attack": {
          "target": "one_opponent_character_cost_le_9cost",
          "duration": "next_opp_turn_end"
        }
      }
    ]
  },
  {
    "_text": "OP14-120 on_ko: 自分の手札1枚を捨てることができる：このキャラカードをトラッシュから登場させる。",
    "when": "on_ko",
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

## OP05-082
- name=しらほし / category=CHARACTER / cost=1 / power=- / counter=2000 / attribute=知 / color=黒 / features=人魚族

### 公式テキスト
> 【起動メイン】このキャラをレストにし、自分のトラッシュのカード2枚を好きな順番でデッキの下に置くことができる：相手の手札が6枚以上ある場合、相手は自身の手札1枚を捨てる。

### 現行 overlay
```json
[
  {
    "_text": "OP05-082 activate_main: このキャラをレストにし、自分のトラッシュのカード2枚を好きな順番でデッキの下に置くことができる：相手の手札が6枚以上ある場合、相手は自身の手札1枚を捨てる。",
    "when": "activate_main",
    "do": [
      {
        "trash_opp_hand_random": 1
      },
      {
        "trash_opp_hand_random": 1
      }
    ],
    "if": {
      "opp_hand_count_ge": 6
    },
    "cost": {
      "rest_self": true,
      "trash_self": true
    }
  }
]
```

## OP15-092
- name=モンキー・Ｄ・ルフィ / category=CHARACTER / cost=7 / power=7000 / counter=1000 / attribute=特 / color=黒 / features=麦わらの一味

### 公式テキスト
> 自分のトラッシュの枚数によって以下の効果をそれぞれ適用する。・10枚以上ある場合、このキャラは元々のパワー9000になり、コスト+10。・20枚以上ある場合、相手のターン中、自分のリーダーを、元々のパワー7000にする。・30枚以上ある場合、このキャラのパワー+1000。

### 現行 overlay
```json
[
  {
    "_text": "ルフィ static (trash≥10): 元々のパワー9000 + 元々のコスト+10",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 10
    },
    "do": [
      {
        "set_base_power": {
          "target": "self",
          "amount": 9000
        }
      },
      {
        "set_base_cost": {
          "target": "self",
          "delta": 10
        }
      }
    ]
  },
  {
    "_text": "ルフィ static (trash≥20, 相手ターン中): 自リーダー 元々のパワー7000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 20,
      "opp_turn": true
    },
    "do": [
      {
        "set_base_power": {
          "target": "self_leader",
          "amount": 7000
        }
      }
    ]
  },
  {
    "_text": "ルフィ static (trash≥30): このキャラ +1000",
    "when": "on_attached_don",
    "n": 0,
    "if": {
      "self_trash_count_ge": 30
    },
    "do": [
      {
        "power_pump": {
          "target": "self",
          "amount": 1000,
          "duration": "static"
        }
      }
    ]
  }
]
```

## P-100
- name=マーシャル・D・ティーチ / category=CHARACTER / cost=10 / power=12000 / counter=- / attribute=特 / color=黒 / features=四皇/黒ひげ海賊団

### 公式テキスト
> 【アタック時】相手のリーダーとキャラすべてを、このターン中、効果を無効にする。

### 現行 overlay
```json
[
  {
    "_text": "P-100 on_attack: 相手のリーダーとキャラすべてを、このターン中、効果を無効にする。",
    "when": "on_attack",
    "do": [
      {
        "disable_effect": {
          "target": "opponent_leader",
          "duration": "turn"
        }
      },
      {
        "disable_effect": {
          "target": "all_opponent_characters",
          "duration": "turn"
        }
      }
    ]
  }
]
```

## OP05-094
- name=高級仕立パッチ★ワーク / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=トンタッタ族/ドレスローザ
- **trigger**: 【トリガー】カード2枚を引き、自分の手札1枚を捨てる。

### 公式テキスト
> 【メイン】相手のキャラ1枚までを、このターン中、コスト-3。その後、相手のコスト0のキャラ1枚までは、次のリフレッシュフェイズでアクティブにならない。

### 現行 overlay
```json
[
  {
    "_text": "OP05-094 main: 相手のキャラ1枚までを、このターン中、コスト-3。その後、相手のコスト0のキャラ1枚までは、次のリフレッシュフェイズでアクティブにならない。",
    "when": "main",
    "do": [
      {
        "cost_minus": {
          "target": "one_opponent_character_any",
          "amount": 3
        }
      }
    ]
  },
  {
    "_text": "OP05-094 trigger: カード2枚を引き、自分の手札1枚を捨てる。",
    "when": "trigger",
    "do": [
      {
        "trash_self_hand_random": 1
      }
    ]
  }
]
```

## OP14-099
- name=不服か？ / category=EVENT / cost=1 / power=- / counter=- / color=黒 / features=王下七武海/B・W
- **trigger**: 【トリガー】このカードの【メイン】効果を発動する。

### 公式テキスト
> 【メイン】自分のデッキの上から3枚を見て、「不服か？」以外の『B・W』を含む特徴を持つカード1枚までを公開し、手札に加える。その後、残りをトラッシュに置く。

### 現行 overlay
```json
[
  {
    "_text": "OP14-099 不服か メイン: デッキ上3を見て BW (除く自身) 1を手札 残trash",
    "when": "main",
    "do": [
      {
        "search_top_n": {
          "depth": 3,
          "filter": {
            "feature": "B・W",
            "exclude_card_id": "OP14-099"
          },
          "limit": 1,
          "destination": "hand",
          "rest_remain": "trash"
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
        "disable_effect": {
          "target": "one_opponent_character_cost_le_5cost",
          "duration": "turn"
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
