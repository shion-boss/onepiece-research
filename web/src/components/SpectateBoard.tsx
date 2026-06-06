"use client";

// AI vs AI 観戦の盤面。 人間vsAI (HumanMatchPlay) と **同じ盤面コンポーネント** (PlayerMat /
// HandRow / StatBadge / OpponentInfoPanel / LogSidebar) を read-only で composeし、 見た目を完全に
// 揃える (= 2026-06-06、 ohtsuki「人間vsAIと同じ見た目に」)。 replay snapshot は StateSnapshot[] で
// players は PlayerSnapshot なので そのまま渡せる。 操作系 props は no-op / 空。
import { useEffect, useRef, useState } from "react";
import type { StateSnapshot } from "@/lib/types";
import {
  PlayerMat,
  HandRow,
  StatBadge,
  OpponentInfoPanel,
  LogSidebar,
} from "./HumanMatchPlay";

const NOOP = () => {};
const EMPTY_ACTIONS = new Map<number, never[]>();

export function SpectateBoard({
  snapshots,
  deckTopName,
  deckBottomName,
  winner,
}: {
  snapshots: StateSnapshot[];
  deckTopName?: string;
  deckBottomName?: string;
  /** winner_idx (= players index)。 表示用。 */
  winner?: number | null;
}) {
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const total = snapshots.length;
  const clampedIdx = Math.min(idx, Math.max(0, total - 1));
  const snap = snapshots[clampedIdx];

  // 自動再生 (= playing 中、 speed に応じて次フレームへ)。
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
  // log は StateSnapshot.log (= string) を 現フレームまで集約して string[] に。
  const log = snapshots
    .slice(0, clampedIdx + 1)
    .flatMap((s) => ((s.log as unknown as string) || "").split("\n"))
    .filter((l) => l && l.trim().length > 0);

  const atEnd = clampedIdx >= total - 1;

  return (
    <div
      className="relative flex h-[85vh] min-h-[560px] w-full flex-col gap-2 overflow-hidden rounded-lg p-2"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, #6b4423 0%, #3d2817 100%)",
      }}
    >
      {/* 再生コントロール (= 観戦は read-only なので step/play のみ) */}
      <div className="z-30 flex shrink-0 flex-wrap items-center gap-2 rounded-lg border border-amber-400/50 bg-zinc-900/80 px-3 py-1.5 text-sm shadow-lg backdrop-blur">
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setIdx(0);
          }}
          className="rounded px-2 py-0.5 font-bold text-amber-200 hover:bg-amber-900/60"
        >
          最初
        </button>
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setIdx((i) => Math.max(0, i - 1));
          }}
          className="rounded px-2 py-0.5 font-bold text-amber-200 hover:bg-amber-900/60"
        >
          前
        </button>
        <button
          type="button"
          onClick={() => {
            if (atEnd) {
              setIdx(0);
              setPlaying(true);
            } else {
              setPlaying((p) => !p);
            }
          }}
          className="rounded bg-amber-500 px-3 py-0.5 font-bold text-white hover:bg-amber-400"
        >
          {playing ? "停止" : atEnd ? "最初から再生" : "再生"}
        </button>
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setIdx((i) => Math.min(total - 1, i + 1));
          }}
          className="rounded px-2 py-0.5 font-bold text-amber-200 hover:bg-amber-900/60"
        >
          次
        </button>
        <div className="ml-1 flex items-center gap-1">
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
        <span className="ml-auto rounded bg-black/40 px-2 py-0.5 text-xs font-semibold text-zinc-200">
          フレーム {clampedIdx + 1}/{total}・ターン {snap.turn}
        </span>
        {atEnd && winner != null && winner >= 0 && (
          <span className="rounded bg-emerald-700 px-2 py-0.5 text-xs font-bold text-white">
            勝者: {winner === 0 ? deckBottomName ?? "P0" : deckTopName ?? "P1"}
          </span>
        )}
      </div>

      <div className="flex min-h-0 flex-1 gap-2 overflow-hidden">
        {/* 左サイド: 相手info + log + 自分stat + 自手札 (= 人間vsAI と同構成) */}
        <div className="flex min-w-[280px] flex-1 min-h-0 flex-col gap-2">
          <OpponentInfoPanel opp={top} reveal onHover={NOOP} />
          <LogSidebar log={log} aiIdx={1} sessionId={null} />
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
                onHover={NOOP}
                onDragStart={NOOP}
                onDragEnd={NOOP}
              />
            </div>
          </div>
        </div>

        {/* 中央: 相手マット + 自分マット (= PlayerMat read-only) */}
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
            onHover={NOOP}
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
            onHover={NOOP}
            onTrashClick={NOOP}
          />
        </div>
      </div>
    </div>
  );
}
