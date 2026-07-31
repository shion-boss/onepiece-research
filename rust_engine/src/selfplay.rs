//! Rust ネイティブ self-play: **方策 (policy) + 探索 (search) + 訓練データ生成 (trajectory)** (2026-07-31)。
//!
//! 狙い = self-play 学習ループ (Expert Iteration / policy 蒸留) を単一 PC で回すための高速自己対戦。
//! state を Rust 所有のまま `clone()` して先読み → JSON 往復無し。 ゲームロジック本体 (setup /
//! legal_actions / apply_action / advance_phase) は差分検証済 (MISMATCH=0) の Python 準拠実装を再利用 =
//! 「中で起きるゲーム処理」は Python と一致保証、 方策/探索/評価の heuristic だけが新規。
//!
//! データフライホイール:
//!   ① self_play が **軌跡 (各手番の特徴 + to_move + 結末ラベル)** を吐く  ← このファイル
//!   ② Python が (特徴, 勝敗) で value を学習 → 重みを出力
//!   ③ その重みを `weights` として渡し直すと value が学習 value になる → 方策が強くなる → ①へ (反復)
//!
//! value:
//!   - weights=None → `board_eval` (heuristic: ライフ/手札/盤面/ドン)
//!   - weights=Some(w) → `features` の線形結合 → logistic = P(me 勝ち) 推定 (学習 value、 Rust で完結)

use serde_json::{json, Value};
use crate::state::{GameState, Phase, Player};
use crate::effects::legal_actions;
use crate::rules::{apply_action, advance_phase};

const N_FEATURES: usize = 16; // features() の次元 (bias 含む)。 value 重みもこの長さ。

fn bpow(p: &Player) -> f64 {
    p.characters.iter().map(|c| c.power() as f64).sum()
}
fn rested_frac(p: &Player) -> f64 {
    if p.characters.is_empty() {
        return 0.0;
    }
    p.characters.iter().filter(|c| c.rested).count() as f64 / p.characters.len() as f64
}

/// 学習用特徴ベクトル (me 視点、 次元 = N_FEATURES、 末尾 bias=1)。 順序固定 = value 学習と適用で共有。
/// 正規化は概ね [-1,1]〜[0,2] に収める (線形/logistic value が扱いやすいスケール)。
pub fn features(st: &GameState, me: usize) -> Vec<f64> {
    let opp = 1 - me;
    let m = &st.players[me];
    let o = &st.players[opp];
    let ml = m.life.len() as f64;
    let ol = o.life.len() as f64;
    let mh = m.hand.len() as f64;
    let oh = o.hand.len() as f64;
    let mc = m.characters.len() as f64;
    let oc = o.characters.len() as f64;
    vec![
        (ml - ol) / 5.0,                                    // ライフ差
        ml / 5.0,                                           // 自ライフ
        ol / 5.0,                                           // 相手ライフ
        (mh - oh) / 5.0,                                    // 手札差
        mh / 7.0,                                           // 自手札
        oh / 7.0,                                           // 相手手札
        (bpow(m) - bpow(o)) / 10000.0,                      // 盤面パワー差
        (mc - oc) / 5.0,                                    // 盤面数差
        mc / 5.0,                                           // 自盤面数
        oc / 5.0,                                           // 相手盤面数
        m.don_active as f64 / 10.0,                         // 使用可能ドン
        st.turn_number as f64 / 20.0,                       // ターン進行
        (m.leader.power() as f64 - o.leader.power() as f64) / 10000.0, // リーダーパワー差
        rested_frac(m),                                     // 自レスト率
        rested_frac(o),                                     // 相手レスト率
        1.0,                                                // bias
    ]
}

/// value: weights 無 → heuristic、 有 → features の線形結合を logistic で [0,1] (=P(me 勝ち))。
/// 終局は勝ち=1e6 / 負け=-1e6 / 引分 0 (heuristic)、 学習 value でも勝敗は 1/0 に振れるので順序整合。
pub fn eval_with(st: &GameState, me: usize, weights: Option<&[f64]>) -> f64 {
    if st.game_over {
        return match st.winner {
            Some(w) if w == me => 1e6,
            Some(_) => -1e6,
            None => 0.0,
        };
    }
    match weights {
        Some(w) if w.len() == N_FEATURES => {
            let f = features(st, me);
            let z: f64 = f.iter().zip(w).map(|(a, b)| a * b).sum();
            // logistic → [0,1]。 heuristic と混在させない (探索中 weights は固定) ので絶対スケールは任意。
            1.0e6 / (1.0 + (-z).exp())
        }
        _ => board_eval(st, me),
    }
}

/// heuristic 盤面評価 (me 視点、 大きいほど有利)。 weights 未学習時のフォールバック。
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
    let mut s = 0.0;
    s += 2000.0 * (m.life.len() as f64 - o.life.len() as f64);
    s += 1500.0 * (m.hand.len() as f64 - o.hand.len() as f64);
    s += 1.0 * (bpow(m) - bpow(o));
    s += 1000.0 * (m.characters.len() as f64 - o.characters.len() as f64);
    s += 300.0 * (m.don_active as f64);
    s
}

/// 1-ply greedy 方策。 weights で value を切替。
pub fn greedy_action(st: &GameState, weights: Option<&[f64]>) -> Value {
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
        let sc = eval_with(&c, me, weights);
        if sc > best_score {
            best_score = sc;
            best = a.clone();
        }
    }
    best
}

/// 探索 (beam): この手番の行動列を beam 幅で先読みし、 最善系列の最初の1手を返す。 weights で value 切替。
pub fn beam_action(st: &GameState, weights: Option<&[f64]>, beam_width: usize, max_depth: usize) -> Value {
    let me = st.turn_player_idx;
    struct Node {
        st: GameState,
        first: Option<Value>,
        score: f64,
    }
    let mut beam: Vec<Node> = vec![Node {
        st: st.clone(),
        first: None,
        score: eval_with(st, me, weights),
    }];
    let mut best_leaf: Option<(Value, f64)> = None;
    let consider = |first: &Option<Value>, sc: f64, best: &mut Option<(Value, f64)>| {
        if let Some(f) = first {
            if best.as_ref().map_or(true, |(_, b)| sc > *b) {
                *best = Some((f.clone(), sc));
            }
        }
    };
    for _ in 0..max_depth {
        let mut next: Vec<Node> = vec![];
        for node in &beam {
            if node.st.game_over || node.st.turn_player_idx != me || node.st.phase != Phase::Main {
                consider(&node.first, eval_with(&node.st, me, weights), &mut best_leaf);
                continue;
            }
            for a in &legal_actions(&node.st) {
                let mut c = node.st.clone();
                if apply_action(&mut c, a).is_err() {
                    continue;
                }
                let first = node.first.clone().or_else(|| Some(a.clone()));
                let sc = eval_with(&c, me, weights);
                let is_leaf = a["t"] == json!("EndPhase") || c.game_over || c.turn_player_idx != me;
                if is_leaf {
                    consider(&first, sc, &mut best_leaf);
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
    for node in &beam {
        consider(&node.first, eval_with(&node.st, me, weights), &mut best_leaf);
    }
    best_leaf.map(|(a, _)| a).unwrap_or(json!({"t": "EndPhase"}))
}

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

/// self-play 1 試合。 collect_traj=true で各手番の (features, to_move) を記録し、 決着後に結末ラベル
/// (y = to_move が勝ったか: 1.0 勝 / 0.0 負 / 0.5 引分) を付けて trajectory を返す。
/// 返り値 = {winner, turns, game_over, steps, trajectory?: [{f:[..], p:usize, y:f64}]}。
#[allow(clippy::too_many_arguments)]
pub fn play_game(
    d1: &Value,
    d2: &Value,
    rng_state: &[u64],
    first_player: usize,
    mode: &str,
    w0: Option<&[f64]>, // player 0 の value 重み (None=heuristic)
    w1: Option<&[f64]>, // player 1 の value 重み。 data-gen は w0=w1、 A/B eval は別々
    beam_width: usize,
    max_depth: usize,
    max_turns: i32,
    collect_traj: bool,
) -> Result<Value, String> {
    let mut st = crate::setup::setup_pre_mulligan(d1, d2, rng_state, first_player)?;
    advance_to_main(&mut st)?;
    let mut steps: i64 = 0;
    // (features, to_move) を貯める。 label は決着後に付ける。
    let mut traj: Vec<(Vec<f64>, usize)> = vec![];
    while !st.game_over && st.turn_number <= max_turns {
        let me = st.turn_player_idx;
        if collect_traj {
            traj.push((features(&st, me), me));
        }
        let weights = if me == 0 { w0 } else { w1 };
        let action = match mode {
            "beam" => beam_action(&st, weights, beam_width, max_depth),
            _ => greedy_action(&st, weights),
        };
        apply_action(&mut st, &action)?;
        steps += 1;
        if steps > 200_000 {
            break;
        }
    }
    let mut out = json!({
        "winner": st.winner,
        "turns": st.turn_number,
        "game_over": st.game_over,
        "steps": steps,
    });
    if collect_traj {
        let rows: Vec<Value> = traj
            .into_iter()
            .map(|(f, p)| {
                let y = match st.winner {
                    Some(w) if w == p => 1.0,
                    Some(_) => 0.0,
                    None => 0.5,
                };
                json!({"f": f, "p": p, "y": y})
            })
            .collect();
        out["trajectory"] = json!(rows);
    }
    Ok(out)
}
