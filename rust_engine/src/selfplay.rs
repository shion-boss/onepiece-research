//! Rust ネイティブ self-play: **方策 (policy) と探索 (search) を Rust 内で回す** (2026-07-31)。
//!
//! 狙い = self-play 高速化。 state を Rust 所有のまま `clone()` して先読みするので、 差分テスト用の
//! JSON 往復 (apply_action_digest) のオーバーヘッドが無い。 ゲームロジック本体 (setup / legal_actions /
//! apply_action / advance_phase) は **差分検証済 (MISMATCH=0) の Python 準拠実装をそのまま再利用**するため、
//! 「中で起きるゲーム処理」は Python と一致が保証される (方策・探索の heuristic だけが新規)。
//!
//! 構成:
//!   - `board_eval`      : 盤面 heuristic 評価 (me 視点、 Python board_eval の縮小版)。 探索の葉評価。
//!   - `greedy_action`   : 1-ply 方策 = 各合法手を試し eval 最大の手。
//!   - `beam_action`     : 探索 = 1 ターンぶんの行動列を beam 幅で先読みし、 最善の「次の1手」を返す。
//!   - `play_game`       : setup → 方策で決着まで自動対戦 (self-play 1 試合)。
//!
//! ⚠ v1 の限界 (今後の refine): **防御 (ブロッカー/カウンター) 未実装** = アタックは常に通る前提で自陣手番の
//!   方策/探索のみ最適化する。 攻撃の eval は「通った後の盤面」= greedy/beam の信号として妥当だが、
//!   防御側の最適応答は入っていない (次段で defender policy を足す)。 value も heuristic (学習 value は未接続)。

use serde_json::{json, Value};
use crate::state::{GameState, Phase, Player};
use crate::effects::legal_actions;
use crate::rules::{apply_action, advance_phase};

/// 盤面評価 (me 視点、 大きいほど me 有利)。 終局は ±1e6 (勝ち/負け)、 引き分け 0。
/// heuristic: ライフ差・手札差・盤面パワー差・盤面数差・使用可能ドン。 学習 value は未接続 (v1)。
pub fn board_eval(st: &GameState, me: usize) -> f64 {
    if st.game_over {
        return match st.winner {
            Some(w) if w == me => 1e6,
            Some(_) => -1e6,
            None => 0.0,
        };
    }
    let opp = 1 - me;
    let m = &st.players[me];
    let o = &st.players[opp];
    let life = |p: &Player| p.life.len() as f64;
    let hand = |p: &Player| p.hand.len() as f64;
    let board_pow = |p: &Player| p.characters.iter().map(|c| c.power() as f64).sum::<f64>();
    let count = |p: &Player| p.characters.len() as f64;
    let mut s = 0.0;
    s += 2000.0 * (life(m) - life(o)); // ライフ = 防御資源 (被弾すると減る)
    s += 1500.0 * (hand(m) - hand(o)); // 手札 = 選択肢/カウンター量
    s += 1.0 * (board_pow(m) - board_pow(o)); // 盤面総パワー
    s += 1000.0 * (count(m) - count(o)); // 盤面キャラ数
    s += 300.0 * (m.don_active as f64); // 手番中に使えるドン
    s
}

/// 1-ply greedy 方策: 各合法手を clone-apply して me 視点 eval 最大の手を返す。 空なら EndPhase。
pub fn greedy_action(st: &GameState) -> Value {
    let me = st.turn_player_idx;
    let acts = legal_actions(st);
    if acts.is_empty() {
        return json!({"t": "EndPhase"});
    }
    let mut best = json!({"t": "EndPhase"});
    let mut best_score = f64::NEG_INFINITY;
    for a in &acts {
        let mut c = st.clone();
        if apply_action(&mut c, a).is_err() {
            continue;
        }
        let sc = board_eval(&c, me);
        if sc > best_score {
            best_score = sc;
            best = a.clone();
        }
    }
    best
}

/// 探索 (beam search): この手番 (me のメインフェイズ) の行動列を beam 幅で先読みし、
/// 「葉 (EndPhase / 相手手番遷移 / 終局) の eval 最大」に至る系列の **最初の1手** を返す。
/// 各手番でこれを呼び直す (re-plan) 前提。 max_depth = 1 手番内の最大行動数。
pub fn beam_action(st: &GameState, beam_width: usize, max_depth: usize) -> Value {
    let me = st.turn_player_idx;
    struct Node {
        st: GameState,
        first: Option<Value>, // この手番で最初に取った手 (返却用)
        score: f64,
    }
    let mut beam: Vec<Node> = vec![Node {
        st: st.clone(),
        first: None,
        score: board_eval(st, me),
    }];
    let mut best_leaf: Option<(Value, f64)> = None;
    let mut consider_leaf = |first: &Option<Value>, sc: f64, best: &mut Option<(Value, f64)>| {
        if let Some(f) = first {
            if best.as_ref().map_or(true, |(_, b)| sc > *b) {
                *best = Some((f.clone(), sc));
            }
        }
    };

    for _ in 0..max_depth {
        let mut next: Vec<Node> = vec![];
        for node in &beam {
            // 相手手番へ移った / 終局 / メイン外 = 葉
            if node.st.game_over || node.st.turn_player_idx != me || node.st.phase != Phase::Main {
                consider_leaf(&node.first, board_eval(&node.st, me), &mut best_leaf);
                continue;
            }
            let acts = legal_actions(&node.st);
            for a in &acts {
                let mut c = node.st.clone();
                if apply_action(&mut c, a).is_err() {
                    continue;
                }
                let first = node.first.clone().or_else(|| Some(a.clone()));
                let sc = board_eval(&c, me);
                let is_leaf = a["t"] == json!("EndPhase") || c.game_over || c.turn_player_idx != me;
                if is_leaf {
                    consider_leaf(&first, sc, &mut best_leaf);
                } else {
                    next.push(Node { st: c, first, score: sc });
                }
            }
        }
        if next.is_empty() {
            break;
        }
        next.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
        next.truncate(beam_width.max(1));
        beam = next;
    }
    // beam に残った (max_depth 到達) ノードも葉候補として評価
    for node in &beam {
        consider_leaf(&node.first, board_eval(&node.st, me), &mut best_leaf);
    }
    best_leaf.map(|(a, _)| a).unwrap_or(json!({"t": "EndPhase"}))
}

/// Refresh 等の非メインフェイズから Main まで進める (play_until_main 相当)。
fn advance_to_main(st: &mut GameState) -> Result<(), String> {
    let mut guard = 0;
    while st.phase != Phase::Main && !st.game_over {
        advance_phase(st)?;
        guard += 1;
        if guard > 100 {
            return Err("advance_to_main: phase loop".into());
        }
    }
    Ok(())
}

/// self-play 1 試合: setup → (mulligan skip=keep) → 方策で決着まで自動対戦。
/// mode = "greedy" | "beam"。 max_turns 到達で draw (winner=None、 公式 floor_rule 時間切れ proxy)。
/// 返り値 = {winner: Option<usize>, turns, game_over, steps}。
pub fn play_game(
    d1: &Value,
    d2: &Value,
    rng_state: &[u64],
    first_player: usize,
    mode: &str,
    beam_width: usize,
    max_depth: usize,
    max_turns: i32,
) -> Result<Value, String> {
    let mut st = crate::setup::setup_pre_mulligan(d1, d2, rng_state, first_player)?;
    advance_to_main(&mut st)?; // mulligan は keep (skip) して Main へ
    let mut steps: i64 = 0;
    while !st.game_over && st.turn_number <= max_turns {
        let action = match mode {
            "beam" => beam_action(&st, beam_width, max_depth),
            _ => greedy_action(&st),
        };
        apply_action(&mut st, &action)?;
        steps += 1;
        if steps > 200_000 {
            break; // 安全弁 (病的長期戦)
        }
    }
    Ok(json!({
        "winner": st.winner,
        "turns": st.turn_number,
        "game_over": st.game_over,
        "steps": steps,
    }))
}
