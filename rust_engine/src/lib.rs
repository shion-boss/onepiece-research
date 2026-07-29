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

/// デバッグ用: Rust が再構成した canonical JSON blob をそのまま返す (Python と文字列比較して乖離 pinpoint)。
#[pyfunction]
fn canonical_blob(dump_json: &str) -> PyResult<String> {
    let st: state::GameState = serde_json::from_str(dump_json)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize 失敗: {e}")))?;
    let v = serde_json::to_value(&st)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    serde_json::to_string(&v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn optcg_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_digest, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_blob, m)?)?;
    m.add_function(wrap_pyfunction!(apply_action_digest, m)?)?;
    Ok(())
}
