"use client";

// AI vs AI 観戦の盤面。 人間vsAI (HumanMatchPlay) と **同じ盤面部品** (PlayerMat / HandRow /
// StatBadge / OpponentInfoPanel / LogSidebar) を read-only で composeし、 全画面・3カラムで
// 見た目を揃える (= 2026-06-06、 ohtsuki 要望: 全画面 / ログにコメント / カードホバープレビュー /
// ACTION 枠 = 盤面データ+コントロールパネル)。
// 左: 相手info + log(コメント可) + 自分stat + 自手札。 中央: 相手/自分マット。
// 右: フレーム操作 + 盤面データ(board_eval/stats) + ホバープレビュー。
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

  return (
    <div
      className="fixed inset-0 z-50 flex h-[100dvh] w-full gap-2 overflow-hidden p-2"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* 左: 相手info + log(コメント可) + 自分stat + 自手札 */}
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

      {/* 中央: 相手/自分マット (= PlayerMat read-only) */}
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

      {/* 右: コントロール / 盤面データ / ホバープレビュー (= 人間vsAI の ACTION 枠の位置) */}
      <div className="flex w-[340px] shrink-0 flex-col gap-2 overflow-y-auto rounded-lg border border-amber-400/40 bg-zinc-900/85 p-3 backdrop-blur">
        {/* コントロール */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-amber-200">観戦コントロール</span>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="rounded border border-rose-400 bg-rose-700/80 px-2 py-0.5 text-xs font-bold text-white hover:bg-rose-600"
              >
                閉じる
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1">
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx(0);
              }}
              className="rounded px-2 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/60"
            >
              最初
            </button>
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setIdx((i) => Math.max(0, i - 1));
              }}
              className="rounded px-2 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/60"
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
              className="rounded px-2 py-1 text-xs font-bold text-amber-200 hover:bg-amber-900/60"
            >
              次
            </button>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-amber-200/80">速度</span>
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
            className="w-full accent-amber-500"
          />
          <div className="text-xs text-zinc-300">
            フレーム {clampedIdx + 1}/{total}・ターン {snap.turn}
            {atEnd && winner != null && winner >= 0 && (
              <span className="ml-2 rounded bg-emerald-700 px-2 py-0.5 font-bold text-white">
                勝者: {winner === 0 ? deckBottomName ?? "P0" : deckTopName ?? "P1"}
              </span>
            )}
          </div>
        </div>

        {/* 盤面データ */}
        <div className="rounded border border-zinc-700 bg-black/30 p-2 text-xs text-zinc-200">
          <div className="mb-1 font-bold text-amber-200">盤面データ</div>
          <div className="grid grid-cols-[auto_1fr_1fr] gap-x-2 gap-y-0.5">
            <span className="text-zinc-500" />
            <span className="font-semibold text-rose-300">
              {deckTopName ?? "P1"}
            </span>
            <span className="font-semibold text-emerald-300">
              {deckBottomName ?? "P0"}
            </span>
            <span className="text-zinc-500">ライフ</span>
            <span>{top.life_count}</span>
            <span>{bottom.life_count}</span>
            <span className="text-zinc-500">手札</span>
            <span>{top.hand_count}</span>
            <span>{bottom.hand_count}</span>
            <span className="text-zinc-500">DON</span>
            <span>
              {top.don_active}/{top.don_total}
            </span>
            <span>
              {bottom.don_active}/{bottom.don_total}
            </span>
            <span className="text-zinc-500">場</span>
            <span>{top.characters.length}</span>
            <span>{bottom.characters.length}</span>
            <span className="text-zinc-500">場power</span>
            <span>{fieldPower(top)}</span>
            <span>{fieldPower(bottom)}</span>
          </div>
          {typeof snap.board_eval === "number" && (
            <div className="mt-1 border-t border-zinc-700 pt-1">
              board_eval (P{snap.turn_player_idx}視点):{" "}
              <span className="font-bold text-amber-200">{snap.board_eval}</span>
            </div>
          )}
        </div>

        {/* ホバープレビュー */}
        <div className="flex min-h-[200px] flex-1 flex-col rounded border border-zinc-700 bg-black/30 p-2">
          <div className="mb-1 text-xs font-bold text-amber-200">
            カードプレビュー
          </div>
          {hovered ? (
            <div className="flex flex-col gap-1">
              <CardImage
                cardId={hovered.cardId}
                alt={hovered.cardId}
                className="w-full rounded"
              />
              {hovered.kind === "chara" && (
                <div className="text-xs text-zinc-200">
                  <div className="font-bold">{hovered.name}</div>
                  <div>
                    P {hovered.power}
                    {hovered.attached_dons > 0
                      ? ` (DON+${hovered.attached_dons})`
                      : ""}
                    {hovered.rested ? " / レスト" : ""}
                  </div>
                  {hovered.keywords.length > 0 && (
                    <div className="text-amber-200">
                      {hovered.keywords.join(" ")}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-zinc-500">
              カードにホバーすると表示
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
