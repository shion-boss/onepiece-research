//! Rust standalone setup_game (pre-mulligan 決定的コア)。
//!
//! Python game.py:setup_game の deterministic 部 (= _make_player[deck shuffle] → _place_life_and_draw)
//! を bit-match で再現。 mulligan (AI 判定) と game_start ステージ登場 (イム等、 稀) は R4/後段に委ね、
//! ここでは do_mulligan_and_finalize=False 相当の pre-mulligan 状態を構築する (= 差分検証可能)。
//!
//! 入力 deck JSON = {leader: CardDef, main: [CardDef], don_deck_size: int}。 rng は getstate keys。

use crate::rng::PyRandom;
use crate::state::{CardDef, GameState, InPlay, Phase, Player};
use serde_json::Value;

/// deck JSON から Player を構築し、 deck を Python 同一列で shuffle (_make_player 相当)。
fn make_player(deck: &Value, name: &str, rng: &mut PyRandom) -> Result<Player, String> {
    let leader_card: CardDef = serde_json::from_value(
        deck.get("leader").cloned().ok_or("deck.leader 無し")?,
    )
    .map_err(|e| format!("leader deserialize: {e}"))?;
    let main: Vec<CardDef> = serde_json::from_value(
        deck.get("main").cloned().ok_or("deck.main 無し")?,
    )
    .map_err(|e| format!("main deserialize: {e}"))?;
    let dds = deck.get("don_deck_size").and_then(|v| v.as_i64()).unwrap_or(10) as i32;
    // InPlay.of(leader, rested=false, sickness=false)
    let leader = InPlay::of(leader_card, false);
    let mut p = Player {
        name: name.to_string(),
        leader,
        deck: main,
        don_remaining_in_deck: dds,
        // Python Player dataclass の非 0 default (Rust Default=0 と差異があるもの)。
        block_chara_play_cost_ge_threshold: -1,
        ..Default::default()
    };
    // Python: p.shuffle_deck(rng) = rng.shuffle(self.deck)。 index 置換を deck に適用。
    let n = p.deck.len();
    let perm = rng.shuffle_perm(n);
    let old = std::mem::take(&mut p.deck);
    p.deck = perm.iter().map(|&j| old[j].clone()).collect();
    Ok(p)
}

/// pre-mulligan 状態を構築 (setup_game の do_mulligan_and_finalize=False 相当、 _recompute_static 前)。
/// rng 消費順 = shuffle(deck1) → shuffle(deck2) (first_player は明示前提 = randrange(2) 消費なし)。
pub fn setup_pre_mulligan(
    deck1: &Value,
    deck2: &Value,
    rng_state: &[u64],
    first_player: usize,
) -> Result<GameState, String> {
    let mut rng = PyRandom::from_state(rng_state).ok_or("rng_state 不正 (625 要素必須)")?;
    // Python: p1=_make_player(deck1) → p2=_make_player(deck2) の順で shuffle 消費。
    let p1 = make_player(deck1, "P0", &mut rng)?;
    let p2 = make_player(deck2, "P1", &mut rng)?;
    let mut players = if first_player == 0 {
        vec![p1, p2]
    } else {
        vec![p2, p1]
    };
    // Python: 並べ替え後に index で name を再設定 (players[0]=P0, [1]=P1)。
    players[0].name = "P0".to_string();
    players[1].name = "P1".to_string();
    let mut st = GameState {
        players,
        turn_player_idx: 0,
        turn_number: 1,
        phase: Phase::Refresh,
        ..Default::default()
    };
    // _place_life_and_draw: 各 player の deck 上から leader.life 枚を life へ、 その後 5 枚 draw。
    for p in st.players.iter_mut() {
        let life_n = p.leader.card.life;
        for _ in 0..life_n {
            if !p.deck.is_empty() {
                let c = p.deck.remove(0);
                p.life.push(c);
            }
        }
    }
    for p in st.players.iter_mut() {
        // Python p.draw(5): 手札 5 枚 + cards_drawn_count += 実ドロー数 (life 配置は draw 経由でない=不加算)。
        let mut drawn = 0;
        for _ in 0..5 {
            if !p.deck.is_empty() {
                let c = p.deck.remove(0);
                p.hand.push(c);
                drawn += 1;
            }
        }
        p.cards_drawn_count += drawn;
    }
    // rng を state に載せておく (以後の rng 依存 effect 継続用)。 pre-mulligan の getstate 相当。
    st.rng = Some(rng);
    Ok(st)
}
