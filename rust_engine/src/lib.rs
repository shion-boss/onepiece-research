//! OPTCG Rust エンジン — PyO3 バインディング (Phase R0→R1)。
//!
//! Python engine を正とし、 差分ハーネス (scripts/engine_diff_trace.py + engine/state_snapshot.py) で
//! 「同一状態 → 同一 canonical digest」を保証しながら段階移植する。 docs/rust_engine_plan.md。
//!
//! R1 の fidelity テスト: Python が full_dump した状態 (全 field、 card は CardDef dict、 instance_id 除外)
//! を Rust が deserialize → canonical serialize (card→card_id, sorted key) → sha1 が Python state_digest と
//! 一致するか。 一致 = Rust の状態モデルが忠実 (全 147 field を正しく表現)。

use pyo3::prelude::*;
use sha1::{Digest, Sha1};

mod effects;
mod rng;
mod rules;
mod selfplay;
mod setup;
mod state;

/// バージョン情報。
#[pyfunction]
fn version() -> String {
    format!("optcg_engine {} (R2: ルール一部)", env!("CARGO_PKG_VERSION"))
}

/// GameState → canonical digest (Python state_snapshot.state_digest と一致する規約)。
fn digest_of(st: &state::GameState) -> Result<String, String> {
    let v = serde_json::to_value(st).map_err(|e| e.to_string())?;
    let blob = serde_json::to_string(&v).map_err(|e| e.to_string())?;
    let mut h = Sha1::new();
    h.update(blob.as_bytes());
    Ok(h.finalize().iter().map(|b| format!("{:02x}", b)).collect::<String>()[..16].to_string())
}

/// Python の full_dump(JSON) を deserialize → canonical digest を返す。
/// engine/state_snapshot.py:state_digest と bit 一致すれば状態モデルが忠実。
///
/// canonical 規約 (Python state_digest と一致):
///  - to_value でネストを serde_json::Value 化 → Map は BTreeMap = key sorted (Python sort_keys 相当)
///  - card は ser_card_id で card_id に畳む (Python CardDef→card_id 相当)
///  - BTreeSet は sorted array (Python set→sorted 相当)
///  - to_string は compact ","/":"、 UTF-8 raw (Python separators+ensure_ascii=False 相当)
#[pyfunction]
fn canonical_digest(dump_json: &str) -> PyResult<String> {
    let st: state::GameState = serde_json::from_str(dump_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize 失敗: {e}")))?;
    digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// R2 差分テスト: full_dump(state) + canonical action を受け、 Rust apply_action 後の digest を返す。
/// Python の apply_action 後 state_digest と一致すれば Rust ルールが忠実 (その action/盤面について)。
#[pyfunction]
fn apply_action_digest(state_json: &str, action_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state deserialize: {e}")))?;
    let act: serde_json::Value = serde_json::from_str(action_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("action deserialize: {e}")))?;
    rules::apply_action(&mut st, &act)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// デバッグ: Rust apply 後の canonical blob を返す (Python canonical と diff して乖離 pinpoint)。
#[pyfunction]
fn apply_action_blob(state_json: &str, action_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state deserialize: {e}")))?;
    let act: serde_json::Value = serde_json::from_str(action_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("action deserialize: {e}")))?;
    rules::apply_action(&mut st, &act)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    let v = serde_json::to_value(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// デバッグ用: Rust が再構成した canonical JSON blob をそのまま返す (Python と文字列比較して乖離 pinpoint)。
#[pyfunction]
fn canonical_blob(dump_json: &str) -> PyResult<String> {
    let st: state::GameState = serde_json::from_str(dump_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize 失敗: {e}")))?;
    let v = serde_json::to_value(&st)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// db/card_effects.json を Rust に読み込む (静的効果評価用)。
#[pyfunction]
fn load_overlay(path: &str) -> PyResult<()> {
    let s = std::fs::read_to_string(path)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("read {path}: {e}")))?;
    effects::load_overlay(&s).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    // 同ディレクトリの card_roles.json も読む (_opp_value の role bonus 用)。 無ければ無視。
    let roles_path = path.replace("card_effects.json", "card_roles.json");
    if let Ok(rs) = std::fs::read_to_string(&roles_path) {
        let _ = effects::load_roles(&rs);
    }
    // 同ディレクトリの card_alt_names.json も読む (= 「ルール上、カード名を X としても扱う」)。
    effects::load_alt_names(&path.replace("card_effects.json", "card_alt_names.json"));
    Ok(())
}

/// R3 idempotence テスト: full_dump(state) を deserialize → Rust evaluate_static_effects → digest。
/// Python は既に _recompute_static 済なので、 Rust の再評価が一致すれば静的効果が忠実 (冪等)。
#[pyfunction]
fn recompute_static_digest(state_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize: {e}")))?;
    effects::evaluate_static_effects(&mut st);
    digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

#[pyfunction]
fn recompute_static_blob(state_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize: {e}")))?;
    effects::evaluate_static_effects(&mut st);
    let v = serde_json::to_value(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// R2 差分テスト: full_dump(state) を受け、 Rust legal_actions を canonical action dict の JSON 配列で返す。
/// Python legal_actions を同 canonical encode したものと集合比較すれば合法手生成が忠実。
#[pyfunction]
fn legal_actions_json(state_json: &str) -> PyResult<String> {
    let st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize: {e}")))?;
    let acts = effects::legal_actions(&st);
    serde_json::to_string(&acts).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// MT 検証: getstate keys (625) を JSON で受け、 各 k について getrandbits(k) を返す (Python 比較用)。
#[pyfunction]
fn mt_getrandbits(keys_json: &str, ks_json: &str) -> PyResult<String> {
    let keys: Vec<u64> = serde_json::from_str(keys_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("keys: {e}")))?;
    let ks: Vec<u32> = serde_json::from_str(ks_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("ks: {e}")))?;
    let mut r = rng::PyRandom::from_state(&keys)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("bad state len"))?;
    let out: Vec<u64> = ks.iter().map(|&k| r.getrandbits(k)).collect();
    serde_json::to_string(&out).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// MT 検証: getstate keys (625) を受け、 randrange(stop) の列を返す (stops_json = [u64...])。
#[pyfunction]
fn mt_randrange(keys_json: &str, stops_json: &str) -> PyResult<String> {
    let keys: Vec<u64> = serde_json::from_str(keys_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("keys: {e}")))?;
    let stops: Vec<u64> = serde_json::from_str(stops_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("stops: {e}")))?;
    let mut r = rng::PyRandom::from_state(&keys)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("bad state len"))?;
    let out: Vec<u64> = stops.iter().map(|&s| r.randrange(s)).collect();
    serde_json::to_string(&out).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// MT 検証: getstate keys (625) を受け、 shuffle([0..n)) の並びを返す。
#[pyfunction]
fn mt_shuffle(keys_json: &str, n: usize) -> PyResult<String> {
    let keys: Vec<u64> = serde_json::from_str(keys_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("keys: {e}")))?;
    let mut r = rng::PyRandom::from_state(&keys)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("bad state len"))?;
    let out = r.shuffle_perm(n);
    serde_json::to_string(&out).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// テスト用: full_dump + 単一 effect (JSON) を受け、 execute_effect 適用後の digest を返す。
/// rng 依存 primitive (shuffle_self_deck / trash_opp_hand_random) の bit-match 検証用。
#[pyfunction]
fn apply_raw_effect_digest(state_json: &str, effect_json: &str, me_idx: usize) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state: {e}")))?;
    let eff: serde_json::Value = serde_json::from_str(effect_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("effect: {e}")))?;
    effects::apply_raw_effect(&eff, &mut st, me_idx);
    digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// standalone setup (pre-mulligan) の digest。 deck JSON = {leader, main, don_deck_size}、 rng_state keys、
/// first_player。 Python setup_game(do_mulligan_and_finalize=False) の state_digest と一致すれば忠実。
#[pyfunction]
fn setup_pre_mulligan_digest(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let st = setup::setup_pre_mulligan(&d1, &d2, &rng_state, first_player)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// setup_game(do_mulligan_and_finalize=True) 相当 = pre-mulligan + マリガン + _recompute_static。
/// blob=true で canonical blob、 false で digest を返す。 Python の setup_game と bit 一致を検証する用。
#[pyfunction]
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, blob=false))]
fn setup_full(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
    blob: bool,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let mut st = setup::setup_pre_mulligan(&d1, &d2, &rng_state, first_player)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    setup::apply_mulligan(&mut st, &d1, &d2, first_player);
    effects::evaluate_static_effects(&mut st);
    if blob {
        let v = serde_json::to_value(&st)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    } else {
        digest_of(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
    }
}

#[pyfunction]
fn setup_pre_mulligan_blob(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let st = setup::setup_pre_mulligan(&d1, &d2, &rng_state, first_player)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    let v = serde_json::to_value(&st).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// Rust ネイティブ self-play を 1 試合走らせる (方策/探索は Rust 内、 JSON 往復無し)。
/// deck{1,2}_json = setup_pre_mulligan と同じ deck Value、 rng_state_json = MT getstate (625 keys)、
/// mode = "greedy" | "beam"。 返り値 = {winner, turns, game_over, steps} の JSON。
#[pyfunction]
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, mode="greedy", weights_json=None, beam_width=8, max_depth=12, max_turns=40, collect_traj=false, rollout_plies=80))]
#[allow(clippy::too_many_arguments)]
fn self_play(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
    mode: &str,
    weights_json: Option<&str>,
    beam_width: usize,
    max_depth: usize,
    max_turns: i32,
    collect_traj: bool,
    rollout_plies: usize,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let w: Option<Vec<f64>> = match weights_json {
        Some(s) if !s.is_empty() => Some(
            serde_json::from_str(s)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("weights: {e}")))?,
        ),
        _ => None,
    };
    let res = selfplay::play_game(
        &d1, &d2, &rng_state, first_player, mode, mode, w.as_deref(), w.as_deref(),
        beam_width, max_depth, rollout_plies, max_turns, collect_traj,
    )
    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    serde_json::to_string(&res).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// A/B eval: player0 が weights0、 player1 が weights1 の value で対戦し winner を返す (head-to-head)。
/// 学習 value (weights0) vs heuristic/旧 value (weights1=None/旧) の強さ比較用。 方策は両者同一 (mode)。
#[pyfunction]
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, mode="beam", weights0_json=None, weights1_json=None, beam_width=8, max_depth=12, max_turns=40, rollout_plies=80))]
#[allow(clippy::too_many_arguments)]
fn eval_ab(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
    mode: &str,
    weights0_json: Option<&str>,
    weights1_json: Option<&str>,
    beam_width: usize,
    max_depth: usize,
    max_turns: i32,
    rollout_plies: usize,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let parse_w = |s: Option<&str>| -> PyResult<Option<Vec<f64>>> {
        match s {
            Some(x) if !x.is_empty() => Ok(Some(
                serde_json::from_str(x)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("weights: {e}")))?,
            )),
            _ => Ok(None),
        }
    };
    let w0 = parse_w(weights0_json)?;
    let w1 = parse_w(weights1_json)?;
    let res = selfplay::play_game(
        &d1, &d2, &rng_state, first_player, mode, mode, w0.as_deref(), w1.as_deref(),
        beam_width, max_depth, rollout_plies, max_turns, false,
    )
    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    serde_json::to_string(&res).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// 方策 A/B: player0 が mode0/weights0、 player1 が mode1/weights1 で対戦し winner を返す。
/// eval_ab と違い **方策 (rollout/beam/greedy) を左右で変えられる** = expert (rollout) vs beam の強さ測定用。
#[pyfunction]
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, mode0, mode1, weights0_json=None, weights1_json=None, beam_width=8, max_depth=12, max_turns=40, rollout_plies=80))]
#[allow(clippy::too_many_arguments)]
fn eval_policies(
    deck1_json: &str,
    deck2_json: &str,
    rng_state_json: &str,
    first_player: usize,
    mode0: &str,
    mode1: &str,
    weights0_json: Option<&str>,
    weights1_json: Option<&str>,
    beam_width: usize,
    max_depth: usize,
    max_turns: i32,
    rollout_plies: usize,
) -> PyResult<String> {
    let d1: serde_json::Value = serde_json::from_str(deck1_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck1: {e}")))?;
    let d2: serde_json::Value = serde_json::from_str(deck2_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deck2: {e}")))?;
    let rng_state: Vec<u64> = serde_json::from_str(rng_state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("rng_state: {e}")))?;
    let parse_w = |s: Option<&str>| -> PyResult<Option<Vec<f64>>> {
        match s {
            Some(x) if !x.is_empty() => Ok(Some(
                serde_json::from_str(x)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("weights: {e}")))?,
            )),
            _ => Ok(None),
        }
    };
    let w0 = parse_w(weights0_json)?;
    let w1 = parse_w(weights1_json)?;
    let res = selfplay::play_game(
        &d1, &d2, &rng_state, first_player, mode0, mode1, w0.as_deref(), w1.as_deref(),
        beam_width, max_depth, rollout_plies, max_turns, false,
    )
    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    serde_json::to_string(&res).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// 与えられた state (full_dump JSON) に対し Rust の方策/探索が選ぶ action を返す (canonical action dict JSON)。
/// mode = "greedy" | "beam" | "rollout"、 weights_json = 学習 value 重み (省略で heuristic)。
#[pyfunction]
#[pyo3(signature = (state_json, mode="greedy", weights_json=None, beam_width=8, max_depth=12, rollout_plies=80))]
fn choose_action(
    state_json: &str,
    mode: &str,
    weights_json: Option<&str>,
    beam_width: usize,
    max_depth: usize,
    rollout_plies: usize,
) -> PyResult<String> {
    let st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let w: Option<Vec<f64>> = match weights_json {
        Some(s) if !s.is_empty() => Some(
            serde_json::from_str(s)
                .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("weights: {e}")))?,
        ),
        _ => None,
    };
    let action = selfplay::choose_move(&st, mode, w.as_deref(), beam_width, max_depth, rollout_plies);
    serde_json::to_string(&action).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// self-play の実装カバレッジ計器を読む。 返り値 JSON:
///   defense = {attacks, blocker_available, candidate_bails, chose_block, chose_counter}
///   actions = {<action type>: {ok, bail}}  (diag=true で self-play した分のみ)
/// bail = 「Rust が解決できず方策が黙って捨てた手」 = 実装漏れの在処。
#[pyfunction]
fn coverage_stats() -> PyResult<String> {
    use std::sync::atomic::Ordering;
    let d: Vec<u64> = selfplay::DEF_STATS.iter().map(|a| a.load(Ordering::Relaxed)).collect();
    let acts: serde_json::Value = match selfplay::ACTION_STATS.lock() {
        Ok(m) => m
            .iter()
            .map(|(k, v)| (k.clone(), serde_json::json!({"ok": v[0], "bail": v[1]})))
            .collect::<serde_json::Map<_, _>>()
            .into(),
        Err(_) => serde_json::json!({}),
    };
    let reasons: serde_json::Value = match selfplay::BAIL_REASONS.lock() {
        Ok(m) => m
            .iter()
            .map(|(k, v)| (k.clone(), serde_json::json!(v)))
            .collect::<serde_json::Map<_, _>>()
            .into(),
        Err(_) => serde_json::json!({}),
    };
    let inv: serde_json::Value = match selfplay::INV_VIOLATIONS.lock() {
        Ok(m) => m.iter().map(|(k, v)| (k.clone(), serde_json::json!(v)))
            .collect::<serde_json::Map<_, _>>().into(),
        Err(_) => serde_json::json!({}),
    };
    let fired: Vec<String> = match selfplay::FIRED_CARDS.lock() {
        Ok(m) => m.iter().cloned().collect(),
        Err(_) => vec![],
    };
    let unk: serde_json::Value = match selfplay::UNKNOWN_CONDS.lock() {
        Ok(m) => m.iter().map(|(k, v)| (k.clone(), serde_json::json!(v)))
            .collect::<serde_json::Map<_, _>>().into(),
        Err(_) => serde_json::json!({}),
    };
    Ok(serde_json::json!({
        "unknown_conditions": unk,
        "invariant_violations": inv,
        "fired_cards": fired,
        "defense": {
            "attacks": d[0], "blocker_available": d[1], "candidate_bails": d[2],
            "chose_block": d[3], "chose_counter": d[4], "chose_counter_event": d[5],
        },
        "actions": acts,
        "bail_reasons": reasons,
    })
    .to_string())
}

/// 計器のリセット + 診断モード切替 (diag=true で action 種別ごとの ok/bail 計数を有効化。 わずかに遅くなる)。
#[pyfunction]
#[pyo3(signature = (diag=false))]
fn reset_coverage_stats(diag: bool) {
    use std::sync::atomic::Ordering;
    for a in selfplay::DEF_STATS.iter() {
        a.store(0, Ordering::Relaxed);
    }
    if let Ok(mut m) = selfplay::ACTION_STATS.lock() {
        m.clear();
    }
    if let Ok(mut m) = selfplay::BAIL_REASONS.lock() {
        m.clear();
    }
    if let Ok(mut m) = selfplay::INV_VIOLATIONS.lock() {
        m.clear();
    }
    if let Ok(mut m) = selfplay::UNKNOWN_CONDS.lock() {
        m.clear();
    }
    if let Ok(mut m) = selfplay::FIRED_CARDS.lock() {
        m.clear();
    }
    selfplay::DIAG_ON.store(diag, Ordering::Relaxed);
}

/// 全カード効果スモーク用: 与えられた state に対し card_id の effect_index 番目の効果を **直接発火** し、
/// 実行できたか (ok) / 降参したか (err) と保存則違反数を返す。 self-play では踏めない効果 (発火率 ~60%
/// で頭打ち) を 100% 実行させて「そもそも Rust で実行できるのか」を測るための入口。
/// src_idx: >=0 = 自場キャラ index / -2 = 自場ステージ 0 / -1 = 場に置かない (source-gone)。
#[pyfunction]
fn fire_effect_smoke(
    state_json: &str,
    card_id: &str,
    when: &str,
    effect_index: usize,
    src_idx: i64,
) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state: {e}")))?;
    let base = selfplay::inv_base(&st);
    let src = match src_idx {
        // -3 = 発動元が **自リーダー** (LEADER カードの activate_main / field-when)。
        //      これが無く LEADER が Detached になっていたため、 直接発火ハーネスが
        //      リーダー効果を丸ごと skip(no_src) していた (113 件、 2026-08-04)。
        -3 => effects::Slot::Leader,
        -2 => effects::Slot::Stage(0),
        i if i >= 0 => effects::Slot::Char(i as usize),
        _ => effects::Slot::Detached,
    };
    // 実経路 (fire_life_trigger / fire_on_ko / counter) は発火前に current_source_card_id を立てる。
    // スモークで立てないと play_self 等が「source 不明」で bail し、 未実装と誤計上される。
    st.current_source_card_id = Some(card_id.to_string());
    let r = effects::execute_one_effect(&mut st, 0, card_id, when, effect_index, src);
    st.current_source_card_id = None;
    let inv = selfplay::check_invariants(&st, &base, "smoke");
    // digest も返す: Python 側で同じ最小 state に同じ effect を発火させ bit 比較するため
    // (scripts/rust_effect_smoke_parity.py)。 self-play で踏めない counter イベント等の
    // 差分検証は この経路でしか作れない。
    let dg = digest_of(&st).unwrap_or_default();
    // 診断用に発火後 state も返す (MISMATCH の blob-diff に使う)。
    let after = serde_json::to_value(&st).unwrap_or(serde_json::Value::Null);
    let out = match r {
        Ok(()) => serde_json::json!({"ok": true, "invariant_violations": inv, "digest": dg, "after": after}),
        Err(e) => serde_json::json!({"ok": false, "err": e, "invariant_violations": inv}),
    };
    Ok(out.to_string())
}

/// ドンフェイズ修飾スモーク (don_phase_modifier / auto_attach_to_leader)。
#[pyfunction]
fn don_phase_modifier_smoke(state_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state: {e}")))?;
    let base = selfplay::inv_base(&st);
    let r = effects::apply_don_phase_modifier(&mut st, 0);
    let inv = selfplay::check_invariants(&st, &base, "don_phase_smoke");
    let out = match r {
        Ok(()) => serde_json::json!({"ok": true, "invariant_violations": inv}),
        Err(e) => serde_json::json!({"ok": false, "err": e, "invariant_violations": inv}),
    };
    Ok(out.to_string())
}

/// 静的効果スモーク: state に対し evaluate_static_effects を走らせ、 保存則違反 / panic を測る。
/// on_attached_don (= DON×N の常在) 等、 execute_one_effect では踏めない経路の網羅に使う。
#[pyfunction]
fn static_effect_smoke(state_json: &str) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state: {e}")))?;
    let base = selfplay::inv_base(&st);
    effects::evaluate_static_effects(&mut st);
    let inv = selfplay::check_invariants(&st, &base, "static_smoke");
    Ok(serde_json::json!({"ok": true, "invariant_violations": inv}).to_string())
}

/// 置換効果スモーク: victim を KO しようとして replace_ko / replace_leave / replace_rest を踏ませる。
/// ok=true かつ replaced=true なら置換が発動した。 Err は「再現不能」= 未実装の在処。
#[pyfunction]
fn replace_effect_smoke(
    state_json: &str,
    victim_owner: usize,
    victim_idx: usize,
    by_opp_effect: bool,
    leave_kind: &str,
) -> PyResult<String> {
    let mut st: state::GameState = serde_json::from_str(state_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("state: {e}")))?;
    let base = selfplay::inv_base(&st);
    let r = effects::try_replace_ko(&mut st, victim_owner, victim_idx, by_opp_effect, leave_kind);
    let inv = selfplay::check_invariants(&st, &base, "replace_smoke");
    // ⚠ digest / after を返さないと Python と bit 比較できず、 置換効果 (replace_ko /
    //   replace_leave / replace_rest) だけが **一度も差分検証されない** まま残る
    //   (2026-08-04 時点で未証明 18 枚がこれ)。 fire_effect_smoke と同じ形で返す。
    let dg = digest_of(&st).unwrap_or_default();
    let after = serde_json::to_value(&st).unwrap_or(serde_json::Value::Null);
    let out = match r {
        Ok(replaced) => serde_json::json!({
            "ok": true, "replaced": replaced, "invariant_violations": inv,
            "digest": dg, "after": after}),
        Err(e) => serde_json::json!({"ok": false, "err": e, "invariant_violations": inv}),
    };
    Ok(out.to_string())
}

#[pymodule]
fn optcg_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(self_play, m)?)?;
    m.add_function(wrap_pyfunction!(coverage_stats, m)?)?;
    m.add_function(wrap_pyfunction!(reset_coverage_stats, m)?)?;
    m.add_function(wrap_pyfunction!(eval_ab, m)?)?;
    m.add_function(wrap_pyfunction!(eval_policies, m)?)?;
    m.add_function(wrap_pyfunction!(choose_action, m)?)?;
    m.add_function(wrap_pyfunction!(setup_pre_mulligan_digest, m)?)?;
    m.add_function(wrap_pyfunction!(setup_pre_mulligan_blob, m)?)?;
    m.add_function(wrap_pyfunction!(setup_full, m)?)?;
    m.add_function(wrap_pyfunction!(fire_effect_smoke, m)?)?;
    m.add_function(wrap_pyfunction!(apply_raw_effect_digest, m)?)?;
    m.add_function(wrap_pyfunction!(mt_getrandbits, m)?)?;
    m.add_function(wrap_pyfunction!(mt_randrange, m)?)?;
    m.add_function(wrap_pyfunction!(mt_shuffle, m)?)?;
    m.add_function(wrap_pyfunction!(load_overlay, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_digest, m)?)?;
    m.add_function(wrap_pyfunction!(static_effect_smoke, m)?)?;
    m.add_function(wrap_pyfunction!(don_phase_modifier_smoke, m)?)?;
    m.add_function(wrap_pyfunction!(replace_effect_smoke, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_blob, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_digest, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_blob, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_digest, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_blob, m)?)?;
    m.add_function(wrap_pyfunction!(legal_actions_json, m)?)?;
    Ok(())
}
