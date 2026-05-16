# -*- coding: utf-8 -*-
"""GameState → flat vector encoder (= NN 入力用)。

Plan Step 3: NN evaluator の input (= ~150 dim) を生成。
内訳:
- 既存 78 dim eval features (= compute_breakdown 経由、 重み 0 ガード前の生 diff)
- leader id one-hot (= 16 種、 deck pool 内)
- archetype one-hot (= 4 種: aggro/midrange/control/trash)
- board encode: 自陣 5 + 相手陣 5 キャラの (power_norm, cost_norm, attached_dons_norm, rested) = 40
- resource: self/opp の life / hand / don / trash count (= 8)
- phase one-hot (= 5) + turn_number_normalized (= 1)

= 計 ~152 dim、 NN MLP の入力に concat。
"""

from __future__ import annotations

from typing import Optional

from .core import GameState, Player, Phase

# deck pool 内の leader id 一覧 (= one-hot 用、 16 種)
# 実 leader id は deck.json の leader_id から取得、 ここではよく使う 16 種を hardcode
KNOWN_LEADER_IDS = [
    "OP14-079",   # 緑紫ドフラ (1342)
    "OP09-XXX",   # クロコ (1385) ※実 id 確認要
    "OP13-079",   # 黒イム (1392)
    "OP07-XXX",   # ルーシー (1399) ※実 id 確認要
    "OP06-XXX",   # 黒ナミ (1439)
    "OP02-XXX",   # 緑ミホーク (1453)
    "OP07-077",   # 紫エネル (1454)
    "OP05-XXX",   # 赤ルフィ (1455)
    "OP03-XXX",   # 赤エース (1456)
    "OP08-001",   # ボニー
    "OP02-002",   # カルガラ
    "OP10-XXX",   # 黒コビー
    "OP06-001",   # 紫コラソン
    "OP07-XXX",   # ハンコック
    "OP11-XXX",   # OP11 ルフィ
    "OP13-XXX",   # OP13 ルフィ
]
LEADER_ID_TO_IDX = {lid: i for i, lid in enumerate(KNOWN_LEADER_IDS)}

# archetype one-hot (= 4 種 + unknown)
ARCHETYPE_TO_IDX = {
    "アグロ": 0, "aggro": 0,
    "ミッドレンジ": 1, "midrange": 1,
    "コントロール": 2, "control": 2,
    "ランプ": 3, "trash": 3, "黒トラッシュ": 3,
}
N_ARCHETYPES = 4


def _encode_player_board(player: Player, max_chara: int = 5) -> list[float]:
    """player.characters を (power_norm, cost_norm, attached_dons_norm, rested) × max_chara で encode。
    max_chara より少なければ 0 padding。
    """
    out: list[float] = []
    for i in range(max_chara):
        if i < len(player.characters):
            c = player.characters[i]
            power_norm = (c.power or 0) / 10000.0  # 0-1 範囲
            cost_norm = (c.card.cost or 0) / 10.0  # 0-1 範囲
            attached_dons_norm = c.attached_dons / 10.0
            rested = 1.0 if c.rested else 0.0
            out.extend([power_norm, cost_norm, attached_dons_norm, rested])
        else:
            out.extend([0.0, 0.0, 0.0, 0.0])
    return out


def _encode_archetype(archetype: str) -> list[float]:
    """archetype one-hot (= 4 dim)。 unknown は all 0。"""
    out = [0.0] * N_ARCHETYPES
    idx = ARCHETYPE_TO_IDX.get(archetype, -1)
    if 0 <= idx < N_ARCHETYPES:
        out[idx] = 1.0
    return out


def _encode_leader_id(leader_id: str) -> list[float]:
    """leader id one-hot (= 16 dim)。 unknown は all 0。"""
    out = [0.0] * len(KNOWN_LEADER_IDS)
    idx = LEADER_ID_TO_IDX.get(leader_id, -1)
    if 0 <= idx < len(KNOWN_LEADER_IDS):
        out[idx] = 1.0
    return out


def _encode_phase(phase: Phase) -> list[float]:
    """phase one-hot (= 5 dim: REFRESH/DRAW/DON/MAIN/END)。"""
    out = [0.0] * 5
    name_to_idx = {"REFRESH": 0, "DRAW": 1, "DON": 2, "MAIN": 3, "END": 4}
    pname = phase.name if hasattr(phase, "name") else str(phase)
    idx = name_to_idx.get(pname, -1)
    if 0 <= idx < 5:
        out[idx] = 1.0
    return out


# 関数 13 (= 2026-05-16 採用案 C): opp.hand 関連 eval feature の mask 対象キー
# compute_breakdown の dim 名で opp 視点を識別。 これらの値は mask_opp_hand=True 時に 0 化される。
OPP_HAND_MASK_KEYS: set[str] = {
    "opp_hand_threat_estimate",
    "opp_known_finisher_count",
    "opp_hand_threat",
    # 既存 compute_breakdown には他にも opp 状態依存 dim あるが、
    # 「opp.hand の中身」 を直接覗くものに限定 (= opp 場 / トラッシュ / DON は公開情報)
}


def encode_state(
    state: GameState,
    me_idx: int,
    mask_opp_hand: bool = False,
) -> list[float]:
    """state を flat vector に encode (= NN 入力用、 関数 13 拡張)。

    Args:
        state: GameState
        me_idx: 自プレイヤー idx
        mask_opp_hand: True なら opp.hand 関連 dim を 0 化 (= partial info 推論用)。
                       False (default) なら oracle 推論用 (= opp.hand 直読)。

    出力: list[float] (= 172 dim、 値は -1〜+1 想定)。
    """
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    # 1) 既存 eval features (= compute_breakdown 経由、 78 dim 想定)
    from .eval import compute_breakdown
    try:
        bd = compute_breakdown(state, me_idx)
        eval_features_with_keys = [(k, float(v["diff"])) for k, v in bd.items()]
        # mask_opp_hand=True なら opp.hand 関連 dim を 0 化
        if mask_opp_hand:
            eval_features_with_keys = [
                (k, 0.0 if k in OPP_HAND_MASK_KEYS else v)
                for k, v in eval_features_with_keys
            ]
        # 正規化 (= tanh で -1〜+1 に)
        import math
        eval_features = [math.tanh(x / 1000.0) for _, x in eval_features_with_keys]
    except Exception:
        eval_features = [0.0] * 78

    # 2) leader id one-hot (= self + opp 各 16 dim)
    self_leader = _encode_leader_id(me.leader.card.card_id)
    opp_leader = _encode_leader_id(opp.leader.card.card_id)

    # 3) archetype one-hot
    archetypes = getattr(state, "archetypes", ["", ""])
    self_arche = _encode_archetype(archetypes[me_idx] if me_idx < len(archetypes) else "")
    opp_arche = _encode_archetype(archetypes[1 - me_idx] if (1 - me_idx) < len(archetypes) else "")

    # 4) board encode (= self + opp 各 20 dim、 board は公開なので mask 不要)
    self_board = _encode_player_board(me)
    opp_board = _encode_player_board(opp)

    # 5) resource (= self + opp の life/hand/don/trash 各 4 = 8 dim、 normalize)
    #    hand_size は公開、 中身は mask されているので OK
    resource = [
        len(me.life) / 5.0,
        len(opp.life) / 5.0,
        len(me.hand) / 10.0,
        len(opp.hand) / 10.0,
        me.total_don / 10.0,
        opp.total_don / 10.0,
        len(me.trash) / 30.0,
        len(opp.trash) / 30.0,
    ]

    # 6) phase + turn
    phase_oh = _encode_phase(state.phase)
    turn_norm = [state.turn_number / 15.0]

    return eval_features + self_leader + opp_leader + self_arche + opp_arche + self_board + opp_board + resource + phase_oh + turn_norm


def encode_state_with_hand(
    state: GameState,
    opp_idx: int,
    candidate_hand: list,
) -> list[float]:
    """関数 14 (= 2026-05-16): opp の仮定 hand を含む encoder。 Opp action model 学習用。

    入力:
        state: GameState
        opp_idx: opp プレイヤー idx (= 「opp 視点」 で encode)
        candidate_hand: list[CardDef]、 opp が持つと仮定する hand カード list

    出力:
        list[float] (~200 dim):
        - 172 dim: encode_state(opp_idx 視点、 mask_opp_hand=False) (= opp 視点での state encoding)
        - ~30 dim: candidate_hand の集約 encoding (= cost ヒストグラム + counter / power sum 等)

    用途: Opponent action model NN の入力 (= Logic-11 action_likelihood の NN path で使用)。
    """
    # opp 視点の state encoding (= opp_idx を me_idx に置換)
    state_part = encode_state(state, me_idx=opp_idx, mask_opp_hand=False)

    # candidate_hand の集約 encoding (~30 dim)
    hand_enc: list[float] = []

    # cost ヒストグラム (= 0-10 の 11 bins)
    cost_hist = [0.0] * 11
    for card in candidate_hand:
        c = min(max(int(getattr(card, "cost", 0)), 0), 10)
        cost_hist[c] += 1.0
    cost_hist = [x / max(len(candidate_hand), 1) for x in cost_hist]  # 正規化
    hand_enc.extend(cost_hist)

    # category 集計 (= 3 dim: chara / event / stage)
    n_chara = sum(1 for c in candidate_hand
                  if hasattr(c, "category") and "CHARACTER" in str(c.category))
    n_event = sum(1 for c in candidate_hand
                  if hasattr(c, "category") and "EVENT" in str(c.category))
    n_stage = sum(1 for c in candidate_hand
                  if hasattr(c, "category") and "STAGE" in str(c.category))
    hand_total = max(len(candidate_hand), 1)
    hand_enc.extend([n_chara / hand_total, n_event / hand_total, n_stage / hand_total])

    # counter / power 集計 (= 4 dim: 合計 / 平均 / max / nonzero ratio)
    counters = [int(getattr(c, "counter", 0)) for c in candidate_hand]
    powers = [int(getattr(c, "power", 0)) for c in candidate_hand]
    counter_sum = sum(counters)
    counter_max = max(counters) if counters else 0
    counter_nonzero = sum(1 for x in counters if x > 0)
    power_sum = sum(powers)
    hand_enc.extend([
        counter_sum / 30000.0,  # 0-1 範囲想定
        counter_max / 10000.0,
        counter_nonzero / hand_total,
        power_sum / 100000.0,
    ])

    # blocker 数 (= 1 dim)
    n_blocker = sum(1 for c in candidate_hand if getattr(c, "is_blocker", False))
    hand_enc.append(n_blocker / hand_total)

    # 計 11 + 3 + 4 + 1 = 19 dim、 末尾 zero pad で 30 dim に
    while len(hand_enc) < 30:
        hand_enc.append(0.0)
    hand_enc = hand_enc[:30]

    return state_part + hand_enc


def encoded_dim() -> int:
    """encode_state の出力次元数を返す (= NN input dim)。"""
    return 78 + 16 + 16 + 4 + 4 + 20 + 20 + 8 + 5 + 1   # = 172


def encoded_dim_with_hand() -> int:
    """encode_state_with_hand の出力次元数 (= 172 + 30 = 202)。"""
    return encoded_dim() + 30
