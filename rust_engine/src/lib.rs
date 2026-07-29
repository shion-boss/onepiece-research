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
mod rules;
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

#[pymodule]
fn optcg_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(load_overlay, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_digest, m)?)?;
    m.add_function(wrap_pyfunction!(recompute_static_blob, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_digest, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_blob, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_digest, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_blob, m)?)?;
    Ok(())
}
