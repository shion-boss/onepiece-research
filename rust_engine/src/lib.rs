//! OPTCG Rust エンジン — PyO3 バインディング (2026-07-29 scaffold)。
//!
//! 目的: self-play の高速ミラー。 engine/*.py を正 (reference) とし、 差分ハーネス
//! (scripts/engine_diff_trace.py + engine/state_snapshot.py) で「同一 seed/action → 同一 canonical
//! digest」を保証しながら段階移植する。
//!
//! ロードマップ (docs/rust_engine_plan.md):
//!   Phase R0 [済]: 差分ハーネス (Python 側 canonical/digest/決定論確認) + scaffold
//!   Phase R1: 状態モデル完全 port (state.rs 全 field) + cards.json/deck ロード + setup_game
//!   Phase R2: ルール (game.py: legal_actions/apply_action/turn 進行/戦闘) 差分テスト通過
//!   Phase R3: DSL インタプリタ (effects.py 312 primitive) を common 順に移植、 全カード差分テスト
//!   Phase R4: AI (beam/value) 移植 → self-play を Rust 内で完結 (30-100x)

use pyo3::prelude::*;

mod state;

/// バージョン情報 (パイプライン疎通確認用)。
#[pyfunction]
fn version() -> String {
    format!("optcg_engine {} (scaffold R0)", env!("CARGO_PKG_VERSION"))
}

/// 状態モデルが構築できることの疎通デモ (空ゲーム状態の phase 名を返す)。
/// 本実装 (setup_game/apply_action/state_digest) は Phase R1+ で追加。
#[pyfunction]
fn scaffold_selftest() -> PyResult<String> {
    use state::*;
    let leader = InPlay {
        card: CardDef {
            card_id: "TEST-000".into(),
            name: "テスト".into(),
            category: Category::Leader,
            color: vec!["赤".into()],
            cost: 0,
            life: 5,
            power: 5000,
            counter: 0,
            attribute: "".into(),
            block_icon: 0,
            features: vec![],
            trigger: "".into(),
        },
        rested: false,
        attached_dons: 0,
        summoning_sickness: false,
        static_buff: 0,
        turn_buff: 0,
        battle_buff: 0,
        next_turn_buff: 0,
    };
    let p = Player {
        name: "P0".into(),
        leader,
        deck: vec![],
        hand: vec![],
        characters: vec![],
        stages: vec![],
        trash: vec![],
        life: vec![],
        don_active: 0,
        don_rested: 0,
        don_remaining_in_deck: 10,
    };
    let gs = GameState {
        players: vec![p],
        turn_player_idx: 0,
        turn_number: 1,
        phase: Phase::Main,
        winner: None,
        game_over: false,
    };
    // canonical JSON (Python state_snapshot と同規約) で疎通確認
    serde_json::to_string(&gs).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}

#[pymodule]
fn optcg_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(scaffold_selftest, m)?)?;
    Ok(())
}
