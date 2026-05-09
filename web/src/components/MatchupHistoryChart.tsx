"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchMatchHistory } from "@/lib/api";
import type { MatchHistoryEntry } from "@/lib/types";

const COLORS = ["#dc2626", "#2563eb", "#16a34a", "#9333ea", "#ca8a04", "#52525b"];

type SeriesPoint = {
  idx: number;
  winrate: number;
  n_games: number;
  timestamp: string;
};

export function MatchupHistoryChart({ deckSlug }: { deckSlug: string }) {
  const [rows, setRows] = useState<MatchHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMatchHistory(deckSlug, 200)
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [deckSlug]);

  const { opponents, data } = useMemo(() => {
    if (!rows || rows.length === 0) return { opponents: [], data: [] };
    // 古い順 (recharts は左→右)
    const ordered = [...rows].reverse();
    const byOpp = new Map<string, SeriesPoint[]>();
    let i = 0;
    for (const r of ordered) {
      const isA = r.deck_a_id === deckSlug;
      const oppName = isA ? r.deck_b_name : r.deck_a_name;
      const myWinrate = isA
        ? r.deck_a_winrate
        : 1 - r.deck_a_winrate - r.draws / Math.max(1, r.n_games);
      const list = byOpp.get(oppName) ?? [];
      list.push({
        idx: i++,
        winrate: Math.round(myWinrate * 1000) / 10,
        n_games: r.n_games,
        timestamp: r.timestamp,
      });
      byOpp.set(oppName, list);
    }
    const opponents = Array.from(byOpp.keys());
    const merged = new Map<number, Record<string, number | string>>();
    for (const [opp, pts] of byOpp.entries()) {
      for (const p of pts) {
        const row = merged.get(p.idx) ?? { idx: p.idx };
        row[opp] = p.winrate;
        row["timestamp"] = p.timestamp;
        merged.set(p.idx, row);
      }
    }
    const data = Array.from(merged.values()).sort(
      (a, b) => (a.idx as number) - (b.idx as number),
    );
    return { opponents, data };
  }, [rows, deckSlug]);

  if (error) {
    return (
      <div className="text-sm text-red-600 dark:text-red-400">
        履歴取得失敗: {error}
      </div>
    );
  }
  if (!rows) {
    return (
      <div className="text-sm text-zinc-500 dark:text-zinc-400">読み込み中…</div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-4 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        まだ対戦履歴がありません
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 10, right: 20, bottom: 0, left: -10 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="idx" tick={{ fontSize: 11 }} />
        <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" width={50} />
        <Tooltip
          formatter={(v) => `${v}%`}
          labelFormatter={(l, payload) => {
            const t = payload?.[0]?.payload?.timestamp;
            return t
              ? `#${l} @ ${String(t).replace("T", " ").replace("Z", "")}`
              : `#${l}`;
          }}
        />
        <Legend />
        {opponents.map((opp, i) => (
          <Line
            key={opp}
            type="monotone"
            dataKey={opp}
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
