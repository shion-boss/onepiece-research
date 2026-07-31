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
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, mode="greedy", weights_json=None, beam_width=8, max_depth=12, max_turns=40, collect_traj=false))]
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
        &d1, &d2, &rng_state, first_player, mode, w.as_deref(), w.as_deref(),
        beam_width, max_depth, max_turns, collect_traj,
    )
    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    serde_json::to_string(&res).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// A/B eval: player0 が weights0、 player1 が weights1 の value で対戦し winner を返す (head-to-head)。
/// 学習 value (weights0) vs heuristic/旧 value (weights1=None/旧) の強さ比較用。
#[pyfunction]
#[pyo3(signature = (deck1_json, deck2_json, rng_state_json, first_player, mode="beam", weights0_json=None, weights1_json=None, beam_width=8, max_depth=12, max_turns=40))]
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
        &d1, &d2, &rng_state, first_player, mode, w0.as_deref(), w1.as_deref(),
        beam_width, max_depth, max_turns, false,
    )
    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
    serde_json::to_string(&res).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

/// 与えられた state (full_dump JSON) に対し Rust の方策/探索が選ぶ action を返す (canonical action dict JSON)。
/// mode = "greedy" | "beam"、 weights_json = 学習 value 重み (省略で heuristic)。
#[pyfunction]
#[pyo3(signature = (state_json, mode="greedy", weights_json=None, beam_width=8, max_depth=12))]
fn choose_action(
    state_json: &str,
    mode: &str,
    weights_json: Option<&str>,
    beam_width: usize,
    max_depth: usize,
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
    let action = match mode {
        "beam" => selfplay::beam_action(&st, w.as_deref(), beam_width, max_depth),
        _ => selfplay::greedy_action(&st, w.as_deref()),
    };
    serde_json::to_string(&action).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn optcg_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(self_play, m)?)?;
    m.add_function(wrap_pyfunction!(eval_ab, m)?)?;
    m.add_function(wrap_pyfunction!(choose_action, m)?)?;
    m.add_function(wrap_pyfunction!(setup_pre_mulligan_digest, m)?)?;
    m.add_function(wrap_pyfunction!(setup_pre_mulligan_blob, m)?)?;
    m.add_function(wrap_pyfunction!(apply_raw_effect_digest, m)?)?;
    m.add_function(wrap_pyfunction!(mt_getrandbits, m)?)?;
    m.add_function(wrap_pyfunction!(mt_randrange, m)?)?;
    m.add_function(wrap_pyfunction!(mt_shuffle, m)?)?;
    m.add_function(wrap_pyfunction!(load_overlay, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_digest, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_blob, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_digest, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_blob, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_digest, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_blob, m)?)?;
    m.add_function(wrap_pyfunction!(legal_actions_json, m)?)?;
    Ok(())
}
