//! ルールエンジン (Rust)。 engine/game.py apply_action のミラー (Phase R2)。
//!
//! action は canonical エンコード (instance_id でなく zone 位置で対象参照 = 状態と同じ iid 非依存規約)。
//! 各 action type を game.py と bit 一致するよう移植し、 差分ハーネスで検証する。
//! ⚠ 効果トリガー (trigger_on_*) と _recompute_static は R3 (effects) で移植。 現状は効果が絡まない
//! action / vanilla 盤面でのみ Python と一致する (差分テストがその境界を明示)。

use crate::state::GameState;
use serde_json::Value;

fn geti(a: &Value, k: &str, default: i64) -> i64 {
    a.get(k).and_then(|v| v.as_i64()).unwrap_or(default)
}

/// action を state に適用 (副作用)。 未実装 action type は Err (差分テストで境界が判る)。
pub fn apply_action(state: &mut GameState, action: &Value) -> Result<(), String> {
    let t = action.get("t").and_then(|v| v.as_str()).ok_or("action に t が無い")?;
    let me = state.turn_player_idx;
    match t {
        // DON!! をリーダーに付与 (game.py:1418)。 n = min(要求, active don)。
        "AttachDonToLeader" => {
            let p = &mut state.players[me];
            let n = (geti(action, "n", 0) as i32).min(p.don_active);
            p.don_active -= n;
            p.leader.attached_dons += n;
            p.dons_used_count += n;
            Ok(())
        }
        // DON!! をキャラに付与 (game.py:1429)。 対象は character 位置 (target_idx)。
        "AttachDonToCharacter" => {
            let idx = geti(action, "target_idx", -1);
            let p = &mut state.players[me];
            if idx < 0 || idx as usize >= p.characters.len() {
                return Err(format!("target_idx 範囲外: {idx}"));
            }
            let n = (geti(action, "n", 0) as i32).min(p.don_active);
            p.don_active -= n;
            p.characters[idx as usize].attached_dons += n;
            p.dons_used_count += n;
            Ok(())
        }
        other => Err(format!("R2 未実装 action: {other}")),
    }
}
