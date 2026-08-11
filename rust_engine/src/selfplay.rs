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

/// value を [0,1] に正規化 (rollout の打ち切り推定 / tie-break 用)。 終局は 1/0.5/0 に振る。
fn norm_value(st: &GameState, me: usize, weights: Option<&[f64]>) -> f64 {
    if st.game_over {
        return match st.winner {
            Some(w) if w == me => 1.0,
            Some(_) => 0.0,
            None => 0.5,
        };
    }
    let v = eval_with(st, me, weights);
    if weights.is_some() {
        (v / 1.0e6).clamp(0.0, 1.0)
    } else {
        1.0 / (1.0 + (-v / 3000.0).exp())
    }
}

// ===== 防御方策 (2026-07-31) =====
// エンジン (rules.rs) は `blocker` / `counter_card_idxs` を持つ action を Python 一致で解決できるが、
// `legal_actions` は **攻撃側の合法手しか列挙しない** (= 防御フィールドが付かない)。 そのまま self-play すると
// 防御側が常にノーガード = カウンター (デッキ総量 ~40000) と要求値が存在しない別ゲームを学習してしまう。
// → ここで防御側の応手を value で選び action に埋める。 探索 (greedy/beam/rollout) の内部 sim も同じ関数を
// 通すので、 攻撃側は 「相手は防御してくる」 前提で読む (= 無防御前提の歪んだ攻めを防ぐ)。
// 候補 = 無防御 / 手札カウンター札 / ブロッカー / カウンターイベント (+ 併用)。
// ⚠ 未対応: 【相手のアタック時】のコスト付き起動防御 (rules.rs が bail するため候補に入れられない)。

// 防御の実効カバレッジ計器。 「防御を選ばなかった (方策)」 と 「Rust が解決できず bail した (未実装)」 を
// 区別する為の大域カウンタ。 無防御への静かな回帰を検出する。 [attacks, blocker_avail, cand_bail, chose_block,
// chose_counter]。 reset/read は lib.rs の def_stats/reset_def_stats。
pub static DEF_STATS: [std::sync::atomic::AtomicU64; 6] = [
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
    std::sync::atomic::AtomicU64::new(0),
];

#[inline]
fn bump(i: usize, n: u64) {
    DEF_STATS[i].fetch_add(n, std::sync::atomic::Ordering::Relaxed);
}

/// 診断モード (既定 OFF)。 ON にすると action 種別ごとに [成功, bail] を数える。
/// 探索/方策は bail した手を黙って捨てる (`is_err() → continue`) ので、 Rust 未実装の手が多いと
/// **action 空間が静かに痩せて別ゲームを学習する**。 その痩せを可視化する計器。
pub static DIAG_ON: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
pub static ACTION_STATS: std::sync::Mutex<std::collections::BTreeMap<String, [u64; 2]>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());
/// bail の理由別内訳 ("<action種別> | <Err 文字列>" -> 回数)。 残実装の作業リストそのもの。
pub static BAIL_REASONS: std::sync::Mutex<std::collections::BTreeMap<String, u64>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());

/// 保存則違反の集計 ("<rule_id>: <詳細>" -> 回数)。 Python を **使わず** に「壊れた状態」を検出する層。
/// 差分検証 (Python 一致) は「Python の正しさが天井」だが、 保存則は言語非依存の絶対条件なので
/// Rust 固有の実装ミス (index ズレ / clone のクロス汚染 / zone 移動漏れ) を単独で捕まえられる。
pub static INV_VIOLATIONS: std::sync::Mutex<std::collections::BTreeMap<String, u64>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());
/// 未対応だった条件キーの内訳 (bail 「条件 unknown」の中身)。 実装すべき eval_condition の一覧。
pub static UNKNOWN_CONDS: std::sync::Mutex<std::collections::BTreeMap<String, u64>> =
    std::sync::Mutex::new(std::collections::BTreeMap::new());
/// 効果が一度でも実行された card_id (「デッキに入っている」≠「発火した」を区別する)。
pub static FIRED_CARDS: std::sync::Mutex<std::collections::BTreeSet<String>> =
    std::sync::Mutex::new(std::collections::BTreeSet::new());

fn note_violation(rule: &str, detail: String) {
    if let Ok(mut m) = INV_VIOLATIONS.lock() {
        *m.entry(format!("{rule}: {detail}")).or_insert(0) += 1;
    }
}

/// player の全 zone に存在するカード枚数 (leader は除く = 常に 1 枚で不変)。
pub fn zone_card_count(p: &Player) -> usize {
    p.deck.len() + p.hand.len() + p.life.len() + p.trash.len() + p.characters.len() + p.stages.len()
}

/// player のドン総数 (コストエリア active/rested + 付与 + ドンデッキ残)。 ドンは所有者を移らない。
pub fn don_total(p: &Player) -> i32 {
    p.don_active
        + p.don_rested
        + p.don_remaining_in_deck
        + p.leader.attached_dons
        + p.characters.iter().map(|c| c.attached_dons).sum::<i32>()
        + p.stages.iter().map(|c| c.attached_dons).sum::<i32>()
}

/// card_id の **順不同チェックサム** (= 集合として変化していないかを見る)。
/// ⚠ 枚数だけ見ていると 「A が消えて B が増えた」 (置換・複製) を見逃す。 和は可換なので
/// zone 間の移動では変わらず、 **card_id の入れ替わりだけを検出** する。 leader は zone_card_count
/// と揃えて除外 (場を離れないので不変)。
fn card_id_hash(s: &str) -> u64 {
    // FNV-1a (64bit)。 順不同和に使うだけなので暗号強度は不要。
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100_0000_01b3);
    }
    h
}

pub fn card_multiset_sum(p: &Player) -> u64 {
    let mut h: u64 = 0;
    for c in p.deck.iter().chain(p.hand.iter()).chain(p.life.iter()).chain(p.trash.iter()) {
        h = h.wrapping_add(card_id_hash(&c.card_id));
    }
    for ip in p.characters.iter().chain(p.stages.iter()) {
        h = h.wrapping_add(card_id_hash(&ip.card.card_id));
    }
    h
}

/// 不変条件の基準値 (カード枚数, ドン総数, card_id 順不同和) を両 player 分作る。
pub fn inv_base(st: &GameState) -> [(usize, i32, u64); 2] {
    [
        (zone_card_count(&st.players[0]), don_total(&st.players[0]), card_multiset_sum(&st.players[0])),
        (zone_card_count(&st.players[1]), don_total(&st.players[1]), card_multiset_sum(&st.players[1])),
    ]
}

/// 状態の絶対条件を検査 (Python 不要 = **独立した正しさの根拠**)。
/// base = 基準時点の (カード枚数, ドン総数, card_id 順不同和) × 2 player。
/// 検出したら INV_VIOLATIONS に積む。 戻り値 = このチェックで見つけた違反数。
pub fn check_invariants(st: &GameState, base: &[(usize, i32, u64); 2], ctx: &str) -> usize {
    let mut n = 0;
    let total_now: usize = st.players.iter().map(zone_card_count).sum();
    let total_base: usize = base[0].0 + base[1].0;
    if total_now != total_base {
        note_violation("INV-card-total", format!("{total_base} → {total_now} ({ctx})"));
        n += 1;
    }
    // ⚠ 全体の card_id 集合は不変。 player 単位だと 「相手のライフの上に置く」 (chara_to_opp_life)
    //   のような **持ち主をまたぐ移動** で正当に変わりうるので、 集合チェックは全体で見る。
    let sum_now = card_multiset_sum(&st.players[0]).wrapping_add(card_multiset_sum(&st.players[1]));
    let sum_base = base[0].2.wrapping_add(base[1].2);
    if sum_now != sum_base {
        note_violation(
            "INV-card-multiset",
            format!("card_id 集合が変化 (枚数は合っているが中身が違う) ({ctx})"),
        );
        n += 1;
    }
    if st.turn_player_idx > 1 {
        note_violation("INV-turn-player", format!("turn_player_idx={} ({ctx})", st.turn_player_idx));
        n += 1;
    }
    for (i, p) in st.players.iter().enumerate() {
        // カードは所有者を移らない = player 単位でも不変
        if zone_card_count(p) != base[i].0 {
            note_violation("INV-card-player", format!("p{i} {} → {} ({ctx})", base[i].0, zone_card_count(p)));
            n += 1;
        }
        if don_total(p) != base[i].1 {
            note_violation("INV-don-total", format!("p{i} {} → {} ({ctx})", base[i].1, don_total(p)));
            n += 1;
        }
        if p.don_active < 0 || p.don_rested < 0 || p.don_remaining_in_deck < 0 {
            note_violation("INV-don-negative", format!("p{i} a={} r={} deck={} ({ctx})", p.don_active, p.don_rested, p.don_remaining_in_deck, ctx = ctx));
            n += 1;
        }
        // 公式 1-3-2: キャラエリアは 5 枚まで / ステージは 1 枚まで
        if p.characters.len() > 5 {
            note_violation("INV-field-max5", format!("p{i} {} 体 ({ctx})", p.characters.len()));
            n += 1;
        }
        if p.stages.len() > 1 {
            note_violation("INV-stage-max1", format!("p{i} {} 枚 ({ctx})", p.stages.len()));
            n += 1;
        }
        if p.leader.card.card_id.is_empty() {
            note_violation("INV-leader-exists", format!("p{i} ({ctx})"));
            n += 1;
        }
        // ⚠ 以前は stages を見ておらず、 ステージに付与されたドンの負値を取りこぼしていた。
        if p.characters.iter().chain(p.stages.iter()).any(|c| c.attached_dons < 0)
            || p.leader.attached_dons < 0
        {
            note_violation("INV-attached-negative", format!("p{i} ({ctx})"));
            n += 1;
        }
        // ⭐ per-card 化 (2026-08-11) で 「表向き枚数 ≤ ライフ枚数」 は導出値ゆえ自明になった。
        //   代わりに **フラグ列の長さがライフと一致しているか** を保存則として見る
        //   (= 同期漏れがあれば 「表向きだったはずの札が裏向きになる」 = 黙って壊れる)。
        if p.life_face_up.len() != p.life.len() {
            note_violation(
                "INV-face-up-life",
                format!("p{i} flags={} / life={} ({ctx})", p.life_face_up.len(), p.life.len()),
            );
            n += 1;
        }
    }
    // ⚠ 「game_over なら winner が確定」 は **不変条件ではない**。 公式 floor_rule II. の
    //   時間切れ両者敗北 (= 引き分け) は winner=None のまま game_over になるのが正しい。
    //   一度書きかけたが成立しないので入れない (検査は 「必ず真」 のものだけ載せる)。
    n
}

pub fn note_fired(card_id: &str) {
    if !DIAG_ON.load(std::sync::atomic::Ordering::Relaxed) {
        return;
    }
    if let Ok(mut m) = FIRED_CARDS.lock() {
        if !m.contains(card_id) {
            m.insert(card_id.to_string());
        }
    }
}

fn diag_record(action: &Value, err: Option<&String>) {
    if !DIAG_ON.load(std::sync::atomic::Ordering::Relaxed) {
        return;
    }
    let t = action.get("t").and_then(|v| v.as_str()).unwrap_or("?").to_string();
    if let Ok(mut m) = ACTION_STATS.lock() {
        let e = m.entry(t.clone()).or_insert([0, 0]);
        e[if err.is_none() { 0 } else { 1 }] += 1;
    }
    if let Some(e) = err {
        if let Ok(mut m) = BAIL_REASONS.lock() {
            *m.entry(format!("{t} | {e}")).or_insert(0) += 1;
        }
    }
}

fn is_attack(action: &Value) -> bool {
    matches!(
        action.get("t").and_then(|v| v.as_str()),
        Some("AttackLeader") | Some("AttackCharacter")
    )
}

/// 防御側手札の counter 札 (hand_idx, counter 値) を値の大きい順に。
fn counter_cards(p: &Player) -> Vec<(usize, i32)> {
    let mut v: Vec<(usize, i32)> = p
        .hand
        .iter()
        .enumerate()
        .filter(|(_, c)| c.counter > 0)
        .map(|(i, c)| (i, c.counter))
        .collect();
    v.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    v
}

/// need 以上を満たす最小枚数の counter 集合 (大きい札から = 要求値をちょうど満たす人間の計算に近い)。
/// 届かなければ None。 need<=0 なら空集合。
fn min_counter_set(cands: &[(usize, i32)], need: i32, max_cards: usize) -> Option<Vec<i64>> {
    if need <= 0 {
        return Some(vec![]);
    }
    let mut sum = 0;
    let mut out: Vec<i64> = vec![];
    for &(i, v) in cands.iter() {
        if out.len() >= max_cards {
            break;
        }
        out.push(i as i64);
        sum += v;
        if sum >= need {
            return Some(out);
        }
    }
    None
}

/// ブロック可能なキャラ (アクティブ + ブロッカー + 無効化されていない)。
fn eligible_blockers(p: &Player) -> Vec<usize> {
    (0..p.characters.len())
        .filter(|&i| {
            let c = &p.characters[i];
            !c.rested && c.is_blocker_now() && !c.blocker_disabled_until_turn_end
        })
        .collect()
}

/// 攻撃 action に防御側の応手 (ブロッカー / カウンター) を埋め、 **解決後の state ごと** 返す。
/// 候補を安い順 (無防御 → カウンター → ブロック → ブロック+カウンター) に並べ、 防御側 value 最大を採る
/// (同点は先頭 = 資源を使わない方)。 全候補が bail したら None (呼出側が素の action にフォールバック)。
pub fn defended_move(
    st: &GameState,
    action: &Value,
    def_w: Option<&[f64]>,
) -> Option<(Value, GameState)> {
    let me = st.turn_player_idx;
    let def = 1 - me;
    let to_leader = action.get("t").and_then(|v| v.as_str()) == Some("AttackLeader");

    // shortlist 用の概算 (on_attack 前の power)。 採否は sim 後の value が決めるので概算で足りる。
    let atk_power = match action.get("attacker_kind").and_then(|v| v.as_str()) {
        Some("leader") => st.players[me].leader.power(),
        _ => {
            let i = action.get("attacker_idx").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
            st.players[me].characters.get(i).map(|c| c.power()).unwrap_or(0)
        }
    };
    let target_power = if to_leader {
        st.players[def].leader.power()
    } else {
        let ti = action.get("target_idx").and_then(|v| v.as_i64()).unwrap_or(0) as usize;
        st.players[def].characters.get(ti).map(|c| c.power()).unwrap_or(0)
    };

    let ccands = counter_cards(&st.players[def]);
    let mut blockers = eligible_blockers(&st.players[def]);
    // 失っても軽い順 (power 昇順) = 捨てブロック候補から並べる
    blockers.sort_by_key(|&i| st.players[def].characters[i].power());

    let mut cands: Vec<Value> = vec![action.clone()]; // ① 無防御
    // ② カウンターで耐える (要求値ちょうど / +1枚 = パンプ保険)
    if let Some(set) = min_counter_set(&ccands, atk_power - target_power + 1, 4) {
        if !set.is_empty() {
            let mut a = action.clone();
            a["counter_card_idxs"] = json!(set.clone());
            cands.push(a);
            if set.len() < ccands.len() {
                let mut more = set.clone();
                more.push(ccands[set.len()].0 as i64);
                let mut a2 = action.clone();
                a2["counter_card_idxs"] = json!(more);
                cands.push(a2);
            }
        }
    }
    // ③ ブロック (最大 3 体)
    for &bi in blockers.iter().take(3) {
        let mut a = action.clone();
        a["blocker"] = json!({"idx": bi});
        cands.push(a);
    }
    // ④ 一番硬いブロッカーをカウンターで守る
    if let Some(&bi) = blockers.iter().max_by_key(|&&i| st.players[def].characters[i].power()) {
        let bp = st.players[def].characters[bi].power();
        if let Some(set) = min_counter_set(&ccands, atk_power - bp + 1, 3) {
            if !set.is_empty() {
                let mut a = action.clone();
                a["blocker"] = json!({"idx": bi});
                a["counter_card_idxs"] = json!(set);
                cands.push(a);
            }
        }
    }

    // ⑤ カウンターイベント (エンジンは fire_counter_events で実装済)。 相手ターン中に残した
    //    アクティブドンで払う = 「ドンを残す」判断の受け皿。 払えない/該当なしなら候補は増えない。
    let cev: Vec<usize> = st.players[def]
        .hand
        .iter()
        .enumerate()
        .filter(|(_, c)| {
            c.category == crate::state::Category::Event
                && c.cost <= st.players[def].don_active
                && crate::effects::card_has_when(&c.card_id, "counter")
        })
        .map(|(i, _)| i)
        .collect();
    for (n, &i) in cev.iter().take(2).enumerate() {
        let mut a = action.clone();
        a["counter_event_idxs"] = json!([i as i64]);
        cands.push(a);
        // 先頭の 1 枚だけ「イベント + 手札カウンター」併用も見る (要求値に届かない分を足す)
        if n == 0 {
            if let Some(set) = min_counter_set(&ccands, atk_power - target_power + 1, 2) {
                if !set.is_empty() {
                    let mut a2 = action.clone();
                    a2["counter_event_idxs"] = json!([i as i64]);
                    a2["counter_card_idxs"] = json!(set);
                    cands.push(a2);
                }
            }
        }
    }

    bump(0, 1);
    if !blockers.is_empty() {
        bump(1, 1);
    }
    let mut best: Option<(Value, GameState, f64)> = None;
    for a in &cands {
        let mut c = st.clone();
        if let Err(e) = apply_action(&mut c, a) {
            // 防御候補が Rust 未対応で bail = 「方策が選ばなかった」ではなく「選べなかった」
            bump(2, 1);
            if DIAG_ON.load(std::sync::atomic::Ordering::Relaxed) {
                if let Ok(mut m) = BAIL_REASONS.lock() {
                    *m.entry(format!("defense | {e}")).or_insert(0) += 1;
                }
            }
            continue;
        }
        let sc = eval_with(&c, def, def_w);
        if best.as_ref().map_or(true, |(_, _, b)| sc > *b) {
            best = Some((a.clone(), c, sc));
        }
    }
    if let Some((a, _, _)) = &best {
        if a.get("blocker").map_or(false, |b| !b.is_null()) {
            bump(3, 1);
        }
        if a.get("counter_card_idxs").and_then(|v| v.as_array()).map_or(false, |x| !x.is_empty()) {
            bump(4, 1);
        }
        if a.get("counter_event_idxs").and_then(|v| v.as_array()).map_or(false, |x| !x.is_empty()) {
            bump(5, 1);
        }
    }
    best.map(|(a, s, _)| (a, s))
}

/// 1 手適用 (攻撃なら防御側の応手込み)。 返り値 = 実際に適用した action (防御フィールド入り)。
/// def_w = 防御側の value 重み。 探索内 sim では探索者の weights を渡す (= 相手も自分と同じ value で
/// 守ると仮定する self-play 標準の相手モデル)。
pub fn apply_move(
    st: &mut GameState,
    action: &Value,
    def_w: Option<&[f64]>,
) -> Result<Value, String> {
    if is_attack(action) {
        if let Some((chosen, ns)) = defended_move(st, action, def_w) {
            *st = ns;
            diag_record(action, None);
            return Ok(chosen);
        }
    }
    let r = apply_action(st, action);
    diag_record(action, r.as_ref().err());
    r?;
    Ok(action.clone())
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
        if apply_move(&mut c, a, weights).is_err() {
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
                if apply_move(&mut c, a, weights).is_err() {
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

/// start から base 方策で終局まで playout し、 me 視点の結末 (勝1/負0/分0.5) を返す。
/// max_plies 到達時 (稀) は value を [0,1] に正規化した推定で代替。 = root-rollout の 1 本の playout。
fn playout_value(start: &GameState, me: usize, weights: Option<&[f64]>,
                 policy: &str, max_plies: usize) -> f64 {
    let mut c = start.clone();
    let mut plies = 0usize;
    while !c.game_over && plies < max_plies {
        let a = match policy {
            "beam" => beam_action(&c, weights, 4, 6),
            _ => greedy_action(&c, weights),
        };
        if apply_move(&mut c, &a, weights).is_err() {
            break;
        }
        plies += 1;
    }
    if c.game_over {
        match c.winner {
            Some(w) if w == me => 1.0,
            Some(_) => 0.0,
            None => 0.5,
        }
    } else {
        // 打ち切り: eval_with を [0,1] に (weights 有→logistic*1e6 を /1e6、 無→heuristic を squash)
        let v = eval_with(&c, me, weights);
        if weights.is_some() {
            (v / 1.0e6).clamp(0.0, 1.0)
        } else {
            1.0 / (1.0 + (-v / 3000.0).exp())
        }
    }
}

/// root-rollout 方策 (= expert)。 各 legal action を適用後、 base 方策で終局まで playout した me 視点の
/// 実結末を評価値として最良 action を返す。 value を迂回して「打ち切ってみる」= 最強教師 (Python で
/// 63% vs beam 33% を実証した路線)。 rollout_policy = playout の base ("greedy" 既定 / "beam")。
/// deterministic (state の rng も固定) なので 1 action = 1 playout で確定。
pub fn rollout_action(st: &GameState, weights: Option<&[f64]>,
                      rollout_policy: &str, max_plies: usize) -> Value {
    let me = st.turn_player_idx;
    let acts = legal_actions(st);
    if acts.is_empty() {
        return json!({"t": "EndPhase"});
    }
    let mut best = acts[0].clone();
    let mut best_score = f64::NEG_INFINITY;
    for a in &acts {
        let mut c = st.clone();
        if apply_move(&mut c, a, weights).is_err() {
            continue;
        }
        // ⚠ playout の結末は {0, 0.5, 1} の粗い値 = 同点が大量に出る。 同点を「先頭優先」で解くと
        // legal_actions の先頭 = EndPhase が勝ち続け、 **1 手も打たずにターンを渡す** 病理になる
        // (実測 2026-07-31: この bug 込みで rollout vs beam = 7.5%)。 直後盤面 value を 1e-3 の
        // 重みで tie-break に足す (結末 {0,0.5,1} の順序は壊さない)。
        let sc = playout_value(&c, me, weights, rollout_policy, max_plies)
            + 1.0e-3 * norm_value(&c, me, weights);
        if sc > best_score {
            best_score = sc;
            best = a.clone();
        }
    }
    best
}

/// mode 文字列で 1 手番の action を選ぶ dispatcher。 play_game / choose_action 共通。
pub fn choose_move(st: &GameState, mode: &str, weights: Option<&[f64]>,
                   beam_width: usize, max_depth: usize, rollout_plies: usize) -> Value {
    match mode {
        "beam" => beam_action(st, weights, beam_width, max_depth),
        "rollout" => rollout_action(st, weights, "greedy", rollout_plies),
        // policy-consistent rollout (playout base = beam)。 = faithful rollout の検証用 (激重)
        "rollout_beam" => rollout_action(st, weights, "beam", rollout_plies),
        _ => greedy_action(st, weights),
    }
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
/// self-play/対戦 1 試合。 player0=mode0/w0、 player1=mode1/w1 で打つ (per-player 方策 + value)。
/// data-gen は mode0=mode1 / w0=w1、 A/B は value 差、 expert 測定は mode 差 (rollout vs beam) で使う。
#[allow(clippy::too_many_arguments)]
pub fn play_game(
    d1: &Value,
    d2: &Value,
    rng_state: &[u64],
    first_player: usize,
    mode0: &str,
    mode1: &str,
    w0: Option<&[f64]>, // player 0 の value 重み (None=heuristic)
    w1: Option<&[f64]>, // player 1 の value 重み。 data-gen は w0=w1、 A/B eval は別々
    beam_width: usize,
    max_depth: usize,
    rollout_plies: usize,
    max_turns: i32,
    collect_traj: bool,
) -> Result<Value, String> {
    let mut st = crate::setup::setup_pre_mulligan(d1, d2, rng_state, first_player)?;
    // マリガン (game.py:182)。 これが無いと初手品質の分布が実戦とズレる (= キーカード依存の
    // control 側が不当に不利)。 判定材料 (keep/prior card_ids) は deck Value 経由で受け取る。
    crate::setup::apply_mulligan(&mut st, d1, d2, first_player);
    crate::effects::evaluate_static_effects(&mut st);
    advance_to_main(&mut st)?;
    let mut steps: i64 = 0;
    // 保存則の基準 (試合開始時のカード枚数 / ドン総数)。 diag 時のみ各手後に照合する。
    let inv_base = inv_base(&st);
    let diag = DIAG_ON.load(std::sync::atomic::Ordering::Relaxed);
    let mut inv_bad: i64 = 0;
    // 防御が実際に働いているかの計器 (無防御回帰の検出用)
    let (mut n_attacks, mut n_blocks, mut n_counter_cards): (i64, i64, i64) = (0, 0, 0);
    // (features, to_move) を貯める。 label は決着後に付ける。
    let mut traj: Vec<(Vec<f64>, usize)> = vec![];
    while !st.game_over && st.turn_number <= max_turns {
        let me = st.turn_player_idx;
        if collect_traj {
            traj.push((features(&st, me), me));
        }
        let weights = if me == 0 { w0 } else { w1 };
        let mode = if me == 0 { mode0 } else { mode1 };
        let action = choose_move(&st, mode, weights, beam_width, max_depth, rollout_plies);
        // 防御は **実際の防御側の value** で決める (A/B の公平性: 各 player は自分の value で守る)。
        let def_w = if me == 0 { w1 } else { w0 };
        let applied = apply_move(&mut st, &action, def_w)?;
        if is_attack(&action) {
            n_attacks += 1;
            if applied.get("blocker").map_or(false, |b| !b.is_null()) {
                n_blocks += 1;
            }
            n_counter_cards += applied
                .get("counter_card_idxs")
                .and_then(|v| v.as_array())
                .map_or(0, |a| a.len() as i64);
        }
        steps += 1;
        if diag {
            inv_bad += check_invariants(&st, &inv_base, action["t"].as_str().unwrap_or("?")) as i64;
        }
        if steps > 200_000 {
            break;
        }
    }
    let mut out = json!({
        "winner": st.winner,
        "turns": st.turn_number,
        "game_over": st.game_over,
        "steps": steps,
        "n_attacks": n_attacks,
        "n_blocks": n_blocks,
        "n_counter_cards": n_counter_cards,
        "invariant_violations": inv_bad,
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
