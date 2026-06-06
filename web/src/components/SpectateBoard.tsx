"use client";

// AI vs AI 観戦の盤面。 人間vsAI (HumanMatchPlay) と **同じ盤面部品** (PlayerMat / HandRow /
// StatBadge / OpponentInfoPanel / LogSidebar) を read-only で composeし、 全画面・3カラムで
// 見た目を揃える (= 2026-06-06、 ohtsuki 要望)。 各カラム幅も人間vsAI と一致
// (左 min-w-280 flex-1 / 中央 w-780 / 右 w-480)。 右パネルは人間vsAI の RightPanel と同じ並び:
// [ヘッダ] → [PREVIEW (大)] → [ACTION 位置 = 観戦コントロール + 盤面データ]。
import { useEffect, useRef, useState } from "react";
import type { StateSnapshot } from "@/lib/types";
import {
  PlayerMat,
  HandRow,
  StatBadge,
  OpponentInfoPanel,
  LogSidebar,
  type HoverInfo,
} from "./HumanMatchPlay";
import { CardImage } from "./CardImage";

const NOOP = () => {};
const EMPTY_ACTIONS = new Map<number, never[]>();

// compute_breakdown (engine/eval.py) の指標キー → 日本語ラベル (全 78 指標)。 AI が手を判断する
// ときに使う盤面指標 = この内訳。 未掲載キーは生キーをそのまま表示 (= フォールバック)。
const METRIC_LABELS: Record<string, string> = {
  // 基本指標 (重み > 0、 判断を駆動)
  life: "ライフ",
  field_count: "場のキャラ数",
  field_power: "場の総パワー",
  hand: "手札枚数",
  don: "DON数",
  blocker: "ブロッカー",
  attached_don: "付与DON",
  active_chara: "アクティブキャラ",
  lethal: "リーサル(自→相)",
  next_turn_lethal: "次ターンリーサル脅威",
  deck_finisher: "山のフィニッシャー数",
  life_trigger: "ライフトリガー価値",
  chara_quality: "場のキャラ質",
  hand_quality: "手札の質",
  opp_hand_threat: "相手手札の脅威",
  // 拡張指標 (Step2-pre)
  is_first_player: "先攻",
  stage_count: "ステージ数",
  stage_value: "ステージ価値",
  trash_count: "トラッシュ枚数",
  trash_archetype_match: "トラッシュのアーキ適合",
  rush_count: "ラッシュ数",
  double_attack_count: "ダブルアタック数",
  static_cost_reduction_total: "常時コスト軽減合計",
  playable_cost_match: "出せるコスト適合",
  synergy_count: "シナジー数",
  is_my_turn: "自分のターン",
  turn_number_normalized: "ターン数(正規化)",
  dead_card_in_hand: "手札の腐りカード",
  active_blocker_count: "アクティブブロッカー数",
  removal_threat_count: "除去脅威数",
  self_counter_in_hand_total: "手札カウンター合計",
  finisher_in_hand_count: "手札フィニッシャー数",
  keyword_taunt_count: "挑発キャラ数",
  ko_immune_count: "KO耐性キャラ数",
  cards_drawn_total: "累計ドロー",
  cards_played_total: "累計プレイ",
  dons_used_total: "累計DON使用",
  tempo_lost_total: "テンポ損失合計",
  known_finisher_count_in_hand: "既知フィニッシャー(手札)",
  don_reserve: "DON温存",
  field_exposure: "場の被弾リスク",
  hand_log: "手札枚数(対数)",
  lethal_risk_diff: "リーサルリスク差",
  // 相互作用指標 (interaction)
  int_low_life_low_hand: "低ライフ×低手札",
  int_low_life_no_blocker: "低ライフ×ブロッカー無",
  int_opp_lethal_no_counter: "被リーサル×カウンター無",
  int_defensive_collapse: "守備崩壊",
  int_opp_da_pressure: "相手ダブルアタック圧",
  int_lethal_setup_ready: "リーサル準備完了",
  int_aggressive_window_open: "攻めどき",
  int_burst_threshold: "バースト閾値",
  int_removal_window: "除去好機",
  int_don_advantage_open: "DON優位",
  int_on_curve: "カーブ通り",
  int_tempo_lost_critical: "致命的テンポ損失",
  int_ramp_paying_off: "ランプ奏功",
  int_mana_starved: "マナ不足",
  int_synergy_threshold_3: "シナジー3閾値",
  int_trash_archetype_5: "トラッシュ5閾値",
  int_stage_with_synergy: "ステージ×シナジー",
  int_ramp_finisher_combo: "ランプ×フィニッシャー",
  int_opp_hidden_threat_high: "相手隠匿脅威 高",
  int_self_hand_quality_high: "自手札の質 高",
  int_opp_low_resource: "相手リソース枯渇",
  int_early_game_strong: "序盤の強さ",
  int_mid_game_pressure: "中盤の圧",
  int_late_game_solver: "終盤の解決力",
  int_ko_immune_finisher: "KO耐性フィニッシャー",
  int_blocker_with_taunt: "挑発持ちブロッカー",
};

const fmt = (n: number) =>
  Number.isInteger(n) ? `${n}` : `${Math.round(n * 10) / 10}`;

export function SpectateBoard({
  snapshots,
  deckTopName,
  deckBottomName,
  winner,
  onClose,
  replayKey,
}: {
  snapshots: StateSnapshot[];
  deckTopName?: string;
  deckBottomName?: string;
  /** winner_idx (= players index)。 表示用。 */
  winner?: number | null;
  /** 全画面を閉じて selector へ戻る。 */
  onClose?: () => void;
  /** コメントを紐づける replay 識別子 (= LogSidebar の sessionId)。 非null でコメント有効。 */
  replayKey?: string;
}) {
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
  const [hovered, setHovered] = useState<HoverInfo>(null);
  const [showData, setShowData] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const total = snapshots.length;
  const clampedIdx = Math.min(idx, Math.max(0, total - 1));
  const snap = snapshots[clampedIdx];

  useEffect(() => {
    if (!playing) return;
    if (clampedIdx >= total - 1) {
      setPlaying(false);
      return;
    }
    timerRef.current = setTimeout(() => setIdx((i) => i + 1), 900 / speed);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, clampedIdx, total, speed]);

  if (!snap) {
    return (
      <div className="p-6 text-sm text-zinc-400">観戦データがありません。</div>
    );
  }

  // perspective: players[1] = 上 (相手枠)、 players[0] = 下 (自分枠)。 観戦なので両方 reveal。
  const top = snap.players[1];
  const bottom = snap.players[0];
  const log = snapshots
    .slice(0, clampedIdx + 1)
    .flatMap((s) => ((s.log as unknown as string) || "").split("\n"))
    .filter((l) => l && l.trim().length > 0);
  const atEnd = clampedIdx >= total - 1;
  const onHover = (h: HoverInfo) => setHovered(h);
  const fieldPower = (p: typeof top) =>
    p.characters.reduce((s, c) => s + (c.power || 0), 0);

  // 盤面データ内訳 (= P0 / 手前 視点固定)。 寄与 (contribution) の大きい順に並べ、 寄与0は除外。
  const detail = snap.board_eval_detail ?? null;
  const detailRows = detail
    ? Object.entries(detail)
        .map(([k, v]) => ({ key: k, ...v }))
        .filter((r) => r.contribution !== 0 || r.diff !== 0)
        .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    : [];
  const p0Eval = detail
    ? Object.values(detail).reduce((s, m) => s + m.contribution, 0)
    : null;

  const ctrlBtn =
    "rounded px-2 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/60";

  return (
    <div
      className="fixed inset-0 z-50 flex h-[100dvh] w-full gap-2 overflow-hidden p-2"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* 左 (= 人間vsAI と同じ min-w-280 flex-1): 相手info + log(コメント可) + 自分stat + 自手札 */}
      <div className="flex min-w-[280px] flex-1 min-h-0 flex-col gap-2">
        <OpponentInfoPanel opp={top} reveal onHover={onHover} />
        <LogSidebar log={log} aiIdx={1} sessionId={replayKey ?? null} />
        <div className="shrink-0 rounded border border-emerald-400/50 bg-emerald-950/40 p-2">
          <StatBadge
            player={bottom}
            label={deckBottomName ?? "P0"}
            color="bg-emerald-700 text-white"
          />
          <div className="mt-2">
            <HandRow
              hand={bottom.hand}
              actionsByHand={EMPTY_ACTIONS}
              canAct={false}
              selectedIdx={null}
              draggingHandIdx={null}
              onClick={NOOP}
              onHover={onHover}
              onDragStart={NOOP}
              onDragEnd={NOOP}
            />
          </div>
        </div>
      </div>

      {/* 中央 (= 人間vsAI と同じ w-780): 相手/自分マット */}
      <div className="relative flex min-h-0 w-[780px] shrink-0 flex-col gap-2">
        <PlayerMat
          player={top}
          isMe={false}
          attackerIid={null}
          canSelectAsTarget={false}
          onLeaderClick={NOOP}
          onCharaClick={NOOP}
          onSelfLeaderClick={NOOP}
          onSelfCharaClick={NOOP}
          actionsByIid={EMPTY_ACTIONS}
          canAct={false}
          drag={null}
          onDropTarget={NOOP}
          onHover={onHover}
          onTrashClick={NOOP}
        />
        <div className="h-px shrink-0 bg-amber-100/30" />
        <PlayerMat
          player={bottom}
          isMe={true}
          attackerIid={null}
          canSelectAsTarget={false}
          onLeaderClick={NOOP}
          onCharaClick={NOOP}
          onSelfLeaderClick={NOOP}
          onSelfCharaClick={NOOP}
          actionsByIid={EMPTY_ACTIONS}
          canAct={false}
          drag={null}
          onDropTarget={NOOP}
          onHover={onHover}
          onTrashClick={NOOP}
        />
      </div>

      {/* 右 (= 人間vsAI と同じ w-480): [ヘッダ] → [PREVIEW 大] → [ACTION位置 = コントロール + 盤面データ] */}
      <div className="flex w-[480px] shrink-0 flex-col gap-2">
        {/* ヘッダ: turn / phase / 勝者 / 閉じる */}
        <div className="flex shrink-0 items-center gap-2 rounded bg-black/50 px-2 py-1.5 text-xs text-zinc-100">
          <span className="font-semibold">
            T{snap.turn} {snap.phase}
          </span>
          <span className="rounded bg-rose-500 px-2 py-0.5 text-xs font-bold text-white">
            観戦
          </span>
          {atEnd && winner != null && winner >= 0 && (
            <span className="rounded bg-amber-500 px-2 py-0.5 text-xs font-bold text-white">
              勝者 {winner === 0 ? deckBottomName ?? "P0" : deckTopName ?? "P1"}
            </span>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded border border-rose-400 bg-rose-700/80 px-2 py-0.5 text-xs font-bold text-white hover:bg-rose-600"
            >
              閉じる
            </button>
          )}
        </div>

        {/* PREVIEW (= 人間vsAI と同じ flex-1 大表示) */}
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden rounded bg-black/40 p-2">
          <div className="shrink-0 text-xs font-bold text-zinc-200">PREVIEW</div>
          {hovered ? (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1">
              <CardImage
                cardId={hovered.cardId}
                alt={hovered.cardId}
                className="max-h-full max-w-full rounded object-contain shadow-2xl"
              />
              {hovered.kind === "chara" && (
                <div className="shrink-0 text-center text-xs text-zinc-200">
                  <span className="font-bold">{hovered.name}</span>{" "}
                  <span>
                    P {hovered.power}
                    {hovered.attached_dons > 0
                      ? ` (DON+${hovered.attached_dons})`
                      : ""}
                    {hovered.rested ? " / レスト" : ""}
                  </span>
                  {hovered.keywords.length > 0 && (
                    <span className="ml-1 text-amber-200">
                      {hovered.keywords.join(" ")}
                    </span>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center text-xs text-zinc-400">
              カードに hover で 拡大表示
            </div>
          )}
        </div>

        {/* ACTION 位置 (= 人間vsAI のアクション枠): 観戦コントロール + 盤面データ */}
        <div className="shrink-0 rounded border border-amber-400/40 bg-zinc-900/85 p-2">
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx(0);
              }}
              className={ctrlBtn}
            >
              最初
            </button>
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx((i) => Math.max(0, i - 1));
              }}
              className={ctrlBtn}
            >
              前
            </button>
            <button
              type="button"
              onClick={() => {
                if (atEnd) {
                  setIdx(0);
                  setPlaying(true);
                } else setPlaying((p) => !p);
              }}
              className="rounded bg-amber-500 px-3 py-1 text-xs font-bold text-white hover:bg-amber-400"
            >
              {playing ? "停止" : atEnd ? "再生(最初から)" : "再生"}
            </button>
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx((i) => Math.min(total - 1, i + 1));
              }}
              className={ctrlBtn}
            >
              次
            </button>
            <span className="ml-1 text-xs text-amber-200/80">速度</span>
            {([1, 2, 4] as const).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={
                  "rounded px-1.5 py-0.5 text-xs font-bold transition " +
                  (speed === s
                    ? "bg-amber-500 text-white"
                    : "text-amber-200 hover:bg-amber-900/60")
                }
              >
                {s}x
              </button>
            ))}
            <span className="ml-auto text-xs text-zinc-300">
              {clampedIdx + 1}/{total}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, total - 1)}
            value={clampedIdx}
            onChange={(e) => {
              setPlaying(false);
              setIdx(parseInt(e.target.value, 10));
            }}
            className="mt-1 w-full accent-amber-500"
          />
          {/* 盤面データ (= クイック表示。 手前 = P0 を左列。 詳細は下のボタンでモーダル) */}
          <div className="mt-2 grid grid-cols-[auto_1fr_1fr] gap-x-2 gap-y-0.5 text-xs text-zinc-200">
            <span className="font-bold text-amber-200">盤面</span>
            <span className="font-semibold text-emerald-300">
              {deckBottomName ?? "P0"}
            </span>
            <span className="font-semibold text-rose-300">
              {deckTopName ?? "P1"}
            </span>
            <span className="text-zinc-500">ライフ</span>
            <span>{bottom.life_count}</span>
            <span>{top.life_count}</span>
            <span className="text-zinc-500">手札</span>
            <span>{bottom.hand_count}</span>
            <span>{top.hand_count}</span>
            <span className="text-zinc-500">DON</span>
            <span>
              {bottom.don_active}/{bottom.don_total}
            </span>
            <span>
              {top.don_active}/{top.don_total}
            </span>
            <span className="text-zinc-500">場/power</span>
            <span>
              {bottom.characters.length} / {fieldPower(bottom)}
            </span>
            <span>
              {top.characters.length} / {fieldPower(top)}
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2">
            {p0Eval !== null ? (
              <span className="text-xs text-zinc-300">
                eval(手前視点):{" "}
                <span
                  className={
                    "font-bold " +
                    (p0Eval >= 0 ? "text-emerald-300" : "text-rose-300")
                  }
                >
                  {p0Eval > 0 ? "+" : ""}
                  {p0Eval}
                </span>
              </span>
            ) : (
              <span />
            )}
            {detailRows.length > 0 && (
              <button
                type="button"
                onClick={() => setShowData(true)}
                className="rounded border border-amber-400/60 bg-amber-900/40 px-2 py-0.5 text-xs font-bold text-amber-100 hover:bg-amber-800/60"
              >
                盤面データ詳細
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 盤面データ詳細モーダル (= AI が手を判断する全指標、 手前 P0 視点、 寄与順) */}
      {showData && detail && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowData(false)}
        >
          <div
            className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-amber-400/50 bg-zinc-900 p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-bold text-amber-200">
                盤面データ詳細 (手前 = {deckBottomName ?? "P0"} 視点)
              </span>
              <button
                type="button"
                onClick={() => setShowData(false)}
                className="rounded border border-zinc-500 px-2 py-0.5 text-xs font-bold text-zinc-200 hover:bg-zinc-700"
              >
                閉じる
              </button>
            </div>
            <p className="mb-2 text-xs text-zinc-400">
              AI が手を判断するときに使う盤面指標 (= engine/eval.py compute_breakdown)。
              寄与 = 差 × 重み、 正 = 手前有利。 寄与の大きい順。 寄与0 (淡色) = 重み0で判断に未使用の参考値。
            </p>
            <div className="mb-2 rounded bg-black/40 px-2 py-1 text-xs text-zinc-200">
              T{snap.turn} {snap.phase}・線形eval(手前):{" "}
              <span
                className={
                  "font-bold " +
                  ((p0Eval ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300")
                }
              >
                {(p0Eval ?? 0) > 0 ? "+" : ""}
                {p0Eval}
              </span>
            </div>
            <table className="w-full text-xs text-zinc-200">
              <thead>
                <tr className="border-b border-zinc-700 text-zinc-400">
                  <th className="py-1 text-left">指標</th>
                  <th className="py-1 text-right">手前</th>
                  <th className="py-1 text-right">相手</th>
                  <th className="py-1 text-right">差</th>
                  <th className="py-1 text-right">寄与</th>
                </tr>
              </thead>
              <tbody>
                {detailRows.map((r) => (
                  <tr
                    key={r.key}
                    className={
                      "border-b border-zinc-800/60 " +
                      (r.contribution === 0 ? "opacity-50" : "")
                    }
                  >
                    <td className="py-1">{METRIC_LABELS[r.key] ?? r.key}</td>
                    <td className="py-1 text-right">{fmt(r.self)}</td>
                    <td className="py-1 text-right">{fmt(r.opp)}</td>
                    <td className="py-1 text-right">{fmt(r.diff)}</td>
                    <td
                      className={
                        "py-1 text-right font-semibold " +
                        (r.contribution > 0
                          ? "text-emerald-300"
                          : r.contribution < 0
                            ? "text-rose-300"
                            : "text-zinc-500")
                      }
                    >
                      {r.contribution > 0 ? "+" : ""}
                      {fmt(r.contribution)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
