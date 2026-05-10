"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { computeBoardEval, evalLabel } from "@/lib/boardEval";
import type { StateSnapshot } from "@/lib/types";

/**
 * 盤面評価の時系列グラフ。
 *
 * 全 snapshot の `normalized` (-1.0 〜 +1.0) を線グラフでプロット。
 * 0 線で互角、 上が self 有利、 下が self 劣勢。
 * - ターン境界 (各ターンの最初の snapshot) を薄い縦線で表示
 * - 現在位置 (currentIdx) を強調縦線で表示
 * - 線上の点クリックで onJump(idx) を呼び該当 snapshot へジャンプ
 */
export function BoardEvalChart({
  snapshots,
  selfIdx,
  oppIdx,
  currentIdx,
  onJump,
}: {
  snapshots: StateSnapshot[];
  selfIdx: 0 | 1;
  oppIdx: 0 | 1;
  currentIdx: number;
  onJump?: (idx: number) => void;
}) {
  // データ計算 (snapshots / selfIdx / oppIdx に依存)
  const data = useMemo(
    () =>
      snapshots.map((snap, i) => {
        const ev = computeBoardEval(snap, selfIdx, oppIdx);
        return {
          idx: i,
          turn: snap.turn,
          normalized: ev.normalized,
          diff: ev.diff,
        };
      }),
    [snapshots, selfIdx, oppIdx],
  );

  // ターン境界 (各ターン開始 index)
  const turnBoundaries = useMemo(() => {
    const out: number[] = [];
    let lastTurn = -1;
    for (let i = 0; i < snapshots.length; i++) {
      if (snapshots[i].turn !== lastTurn) {
        out.push(i);
        lastTurn = snapshots[i].turn;
      }
    }
    return out;
  }, [snapshots]);

  const cur = data[currentIdx];
  const curLabel = cur ? evalLabel(cur.normalized) : "";

  return (
    <div className="rounded border border-white/10 bg-white/5 p-2 text-zinc-100">
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="text-zinc-300">
          盤面評価の推移 (X = snapshot index, Y = 有利度 -1〜+1)
        </span>
        {cur && (
          <span className="font-mono text-zinc-200">
            T{cur.turn} #{cur.idx}: {cur.normalized >= 0 ? "+" : ""}
            {cur.normalized.toFixed(2)} ({curLabel})
          </span>
        )}
      </div>
      <div style={{ width: "100%", height: 200 }}>
        <ResponsiveContainer>
          <LineChart
            data={data}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            onClick={(e) => {
              if (!onJump) return;
              // recharts の click は activeTooltipIndex で点 index を返す
              const idx = (e as { activeTooltipIndex?: number })
                ?.activeTooltipIndex;
              if (typeof idx === "number") onJump(idx);
            }}
          >
            <CartesianGrid stroke="#ffffff20" strokeDasharray="3 3" />
            <XAxis
              dataKey="idx"
              tick={{ fontSize: 10, fill: "#d4d4d8" }}
              tickFormatter={(v) => `#${v}`}
              stroke="#ffffff40"
            />
            <YAxis
              domain={[-1, 1]}
              tick={{ fontSize: 10, fill: "#d4d4d8" }}
              tickFormatter={(v) => v.toFixed(1)}
              ticks={[-1, -0.5, 0, 0.5, 1]}
              stroke="#ffffff40"
            />
            <Tooltip
              contentStyle={{
                fontSize: "11px",
                background: "rgba(0,0,0,0.85)",
                border: "1px solid #ffffff20",
                color: "#fafafa",
              }}
              labelFormatter={(idx) =>
                `#${idx} (T${data[idx as number]?.turn ?? "?"})`
              }
              formatter={(v) => {
                const num = typeof v === "number" ? v : Number(v);
                return [Number.isFinite(num) ? num.toFixed(2) : String(v), "normalized"];
              }}
            />
            {/* 0 ライン (= 互角) */}
            <ReferenceLine y={0} stroke="#a1a1aa" strokeWidth={1} />
            {/* ターン境界 */}
            {turnBoundaries.map((b) => (
              <ReferenceLine
                key={`tb-${b}`}
                x={b}
                stroke="#ffffff30"
                strokeDasharray="2 2"
              />
            ))}
            {/* 現在位置 */}
            <ReferenceLine x={currentIdx} stroke="#f87171" strokeWidth={2} />
            <Line
              type="monotone"
              dataKey="normalized"
              stroke="#34d399"
              strokeWidth={2}
              dot={{ r: 1.5, fill: "#34d399" }}
              activeDot={{ r: 4, fill: "#34d399" }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-[10px] text-zinc-300">
        点クリックで該当 snapshot にジャンプ。 緑線 = self 有利、 赤縦線 = 現在位置、 半透明縦線 = ターン境界。
      </div>
    </div>
  );
}
