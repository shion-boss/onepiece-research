"""ターン切替時の所有者フラグ更新タイミングの回帰テスト。

回帰 (2026-07-17、 ohtsuki 報告): 防御時にリーダーのパワー数字が「前の攻撃の値を引きずる」。
原因 = advance_phase の END→REFRESH で turn_player_idx を反転した後、 is_owners_turn の更新
(_recompute_static) を末尾まで遅らせていたため、 その間の resolve_triggers が push_log →
snapshot を記録すると、 前ターンのプレイヤーの leader/キャラの is_owners_turn が True のまま =
DON+1000 が乗ったパワーが相手ターンの snapshot に焼き込まれていた (公式 6-5-5 違反の表示)。
修正: 反転直後に _update_ownership_flags を呼ぶ。
"""
from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.game import advance_phase, _recompute_static


def _repo():
    return CardRepository.from_json("db/cards.json")


def test_don_buff_drops_immediately_at_turn_flip():
    """DON5 を付けた P0 リーダー (自ターン中 power=10000) が、 END→REFRESH のターン反転
    直後に is_owners_turn=False + power=base(5000) になる (= DON 分が相手ターンに残らない)。"""
    repo = _repo()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.leader.attached_dons = 5
    p0.deck = [repo.get("OP01-013")] * 20
    p1.deck = [repo.get("OP01-013")] * 20
    state = GameState(players=[p0, p1])
    state.turn_player_idx = 0
    state.phase = Phase.END
    _recompute_static(state)
    base = p0.leader.base_power
    assert p0.leader.power == base + 5000, "自ターン中は DON5 で +5000"

    advance_phase(state)  # END → REFRESH (turn flip)

    assert state.turn_player_idx == 1, "ターンが P1 に移った"
    assert p0.leader.is_owners_turn is False, "反転直後に P0 leader の所有者ターンフラグが False"
    assert p0.leader.power == base, (
        f"相手ターン中は DON 分が乗らない (公式 6-5-5): {p0.leader.power} != {base}"
    )


def test_no_stale_don_snapshot_in_transition_gap():
    """record_snapshots 下でターン反転をまたいでも、 turn=P1 の snapshot に P0 leader の
    DON 乗りパワー (stale) が焼き込まれない。"""
    repo = _repo()
    p0 = Player(name="P0", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p0.leader.attached_dons = 5
    p0.deck = [repo.get("OP01-013")] * 20
    p1.deck = [repo.get("OP01-013")] * 20
    state = GameState(players=[p0, p1])
    state.turn_player_idx = 0
    state.phase = Phase.END
    state.record_snapshots = True
    _recompute_static(state)

    n0 = len(state.snapshots)
    advance_phase(state)

    boosted = p0.leader.base_power + 5000
    for snap in state.snapshots[n0:]:
        if snap.get("turn_player_idx") == 1:
            ld = snap["players"][0]["leader"]
            assert ld["power"] < boosted, (
                f"相手ターン(P1)の snapshot に P0 leader の DON乗り {ld['power']} が残っている"
            )
