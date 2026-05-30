"""rich state-axes for spec entries (= 2026-05-30、 axis 拡 張)。

ohtsuki さん 提 案 [[project_corpus_methodology_dead_end]] 後 続:
4 軸 (turn, opp_leader, opp_archetype, self_condition) では cell 内 で base_eval
推 し と spec 推 し が 一 致 する chicken-and-egg 罠。 9-12 軸 に 拡 張 し て cell を
細 分 化 し、 各 cell で 明 確 な 正 解 entry を 持 つ。

## 軸 (= 2026-05-30 version 1)

| 軸 | 計 算 | bucket |
|---|---|---|
| turn | state.turn_number | int (= そのまま) |
| opp_leader_id | opp.leader.card_id | str |
| opp_archetype | deck_to_archetype map | str (= control/aggro/midrange/ramp) |
| opp_life_bucket | opp.life.count | dead/lethal/low/mid/full |
| opp_hand_bucket | opp.hand.count | few/mid/many |
| opp_field_bucket | opp.characters.count | empty/some/many |
| opp_active_chara_bucket | opp active chara count | none/some/many |
| opp_threat_bucket | opp active power + don | low/mid/high |
| self_life_bucket | me.life.count | dead/lethal/low/mid/full |
| self_hand_bucket | me.hand.count | few/mid/many |
| self_field_bucket | me.characters.count | empty/some/many |
| self_don_bucket | me.don_active | tight/ok/plenty |

合 計 cells: 7 × 16 × 4 × 5 × 3 × 3 × 3 × 3 × 5 × 3 × 3 × 3 ≈ 数 万 / leader (= 実 出 現 約 ~3,000-10,000)
"""
from __future__ import annotations

from typing import Any


# ===========================================================================
# bucket 化 関 数 (= state 値 → bucket 文 字 列)
# ===========================================================================


def life_bucket(n: int) -> str:
    """ライフ 残 数 → 5 段 bucket。 dead < lethal < low < mid < full。"""
    if n <= 0:
        return "dead"
    if n == 1:
        return "lethal"
    if n <= 2:
        return "low"
    if n <= 3:
        return "mid"
    return "full"


def hand_bucket(n: int) -> str:
    """手 札 数 → 3 段 bucket。"""
    if n <= 2:
        return "few"
    if n <= 5:
        return "mid"
    return "many"


def field_bucket(n: int) -> str:
    """場 chara 数 → 3 段 bucket。"""
    if n == 0:
        return "empty"
    if n <= 2:
        return "some"
    return "many"


def active_chara_bucket(n: int) -> str:
    """active chara 数 → 3 段 bucket。"""
    if n == 0:
        return "none"
    if n <= 2:
        return "some"
    return "many"


def don_bucket(active_don: int) -> str:
    """don active 数 → 3 段 bucket。 tight (= 1-3 don)、 ok (= 4-7)、 plenty (= 8+)。"""
    if active_don <= 3:
        return "tight"
    if active_don <= 7:
        return "ok"
    return "plenty"


def threat_bucket(active_power_sum: int, active_don: int) -> str:
    """opp の 「次 turn 攻 撃 圧」 → 3 段。 active 場 power + don 余 力 で 評 価。"""
    score = active_power_sum + active_don * 1000
    if score <= 2000:
        return "low"
    if score <= 10000:
        return "mid"
    return "high"


# ===========================================================================
# state → 軸 値 (= snapshot dict から)
# ===========================================================================


def compute_axes_from_snapshot(state_features: dict, actor_idx: int, target_idx: int,
                                opp_archetype: str = "midrange") -> dict:
    """corpus dump の state_features から rich axes を 計 算。

    snapshot は engine/game_corpus.py の snapshot_player 形 式 を 想 定。

    Returns: 全 軸 値 dict (= entry filter で 使う)
    """
    players = state_features.get("players") or []
    if len(players) != 2:
        return {}
    actor = players[actor_idx]
    target = players[target_idx]

    actor_life = actor.get("life_count", 0)
    actor_hand = actor.get("hand_count", 0)
    actor_field = actor.get("field_count", 0)
    actor_don = actor.get("don_active", 0)

    target_life = target.get("life_count", 0)
    target_hand = target.get("hand_count", 0)
    target_field = target.get("field_count", 0)
    target_active_chara = target.get("field_active_count", 0)
    target_active_power = sum(
        c.get("power", 0) for c in target.get("field", []) if not c.get("rested")
    )
    target_active_don = target.get("don_active", 0)

    return {
        "turn": state_features.get("turn_number", 0),
        "opp_leader_id": (target.get("leader") or {}).get("card_id"),
        "opp_archetype": opp_archetype,
        # opp 軸
        "opp_life_bucket": life_bucket(target_life),
        "opp_hand_bucket": hand_bucket(target_hand),
        "opp_field_bucket": field_bucket(target_field),
        "opp_active_chara_bucket": active_chara_bucket(target_active_chara),
        "opp_threat_bucket": threat_bucket(target_active_power, target_active_don),
        # self 軸
        "self_life_bucket": life_bucket(actor_life),
        "self_hand_bucket": hand_bucket(actor_hand),
        "self_field_bucket": field_bucket(actor_field),
        "self_don_bucket": don_bucket(actor_don),
    }


# ===========================================================================
# state → 軸 値 (= 実 戦 中 の GameState から、 engine 側 用)
# ===========================================================================


def compute_axes_from_state(state: Any, me_idx: int,
                              opp_archetype: str = "midrange") -> dict:
    """実 戦 中 の GameState から rich axes を 計 算。

    find_matching_entries や derive_actions_for_goal で 使 う。
    """
    me = state.players[me_idx]
    opp = state.players[1 - me_idx]

    target_active_power = sum(
        c.power for c in opp.characters if not c.rested
    )

    # 旧 self_condition も 計 算 (= v1 entries との backward compat 用)
    try:
        from .target_dsl import compute_self_condition
        self_cond = compute_self_condition(state, me_idx)
    except Exception:
        self_cond = "even"

    return {
        "turn": state.turn_number,
        "opp_leader_id": opp.leader.card.card_id,
        "opp_archetype": opp_archetype,
        "self_condition": self_cond,  # = v1 軸 backward compat
        "opp_life_bucket": life_bucket(len(opp.life)),
        "opp_hand_bucket": hand_bucket(len(opp.hand)),
        "opp_field_bucket": field_bucket(len(opp.characters)),
        "opp_active_chara_bucket": active_chara_bucket(
            sum(1 for c in opp.characters if not c.rested)
        ),
        "opp_threat_bucket": threat_bucket(target_active_power, opp.don_active),
        "self_life_bucket": life_bucket(len(me.life)),
        "self_hand_bucket": hand_bucket(len(me.hand)),
        "self_field_bucket": field_bucket(len(me.characters)),
        "self_don_bucket": don_bucket(me.don_active),
    }


# ===========================================================================
# axes 比 較 (= entry の 軸 と state の 軸 が match する か)
# ===========================================================================

# entry に 書 か れ うる 軸 keys (= match 対 象)
ENTRY_AXES_KEYS = (
    "turn", "opp_leader_id", "opp_archetype",
    "opp_life_bucket", "opp_hand_bucket", "opp_field_bucket",
    "opp_active_chara_bucket", "opp_threat_bucket",
    "self_life_bucket", "self_hand_bucket", "self_field_bucket",
    "self_don_bucket",
    # 旧 軸 (= backward compat、 まだ entry に 残って る 可能 性)
    "self_condition",
)


def axes_match(entry_axes: dict, state_axes: dict,
                turn_tolerance: int = 1) -> tuple[bool, float]:
    """entry の 軸 が state の 軸 と match する か。

    Returns: (matched: bool, weight: float)
    - 全 entry 軸 (= 値 設 定 済) が state 軸 と 一 致 すれば match
    - turn は ±turn_tolerance で 部 分 一 致 (= 旧 logic 互 換)
    - turn 厳 密 一 致 = 1.0、 ±1 = 0.6、 ±2 以 上 = skip
    - 軸 値 が None なら wildcard で 常 に match
    """
    weight = 1.0

    # turn 特 別 扱 い (= 部 分 一 致 weight)
    e_turn = entry_axes.get("turn")
    s_turn = state_axes.get("turn", 0)
    if e_turn is not None:
        diff = abs(int(e_turn) - int(s_turn))
        if diff == 0:
            pass  # weight 1.0
        elif diff <= turn_tolerance:
            weight *= 0.6
        else:
            return False, 0.0

    # その他 軸 = 厳 密 一 致 か wildcard
    for key in ENTRY_AXES_KEYS:
        if key == "turn":
            continue
        e_val = entry_axes.get(key)
        if e_val is None:
            continue  # entry 側 wildcard
        s_val = state_axes.get(key)
        if s_val is None:
            continue  # state 側 で 計 算 漏れ も wildcard 扱い (= 寛容、 backward compat)
        if e_val != s_val:
            return False, 0.0

    return True, weight
