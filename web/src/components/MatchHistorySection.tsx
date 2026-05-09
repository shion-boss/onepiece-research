"use client";

import { useEffect, useState } from "react";
import { fetchMatchHistory } from "@/lib/api";
import type { MatchHistoryEntry } from "@/lib/types";

export function MatchHistorySection({ deckSlug }: { deckSlug: string }) {
  const [rows, setRows] = useState<MatchHistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetchMatchHistory(deckSlug, 10)
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deckSlug]);

  if (loading) {
    return (
      <div className="text-sm text-zinc-500 dark:text-zinc-400">
        履歴読み込み中…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
        {error}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-3 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        まだ対戦履歴がありません (上の対戦ランナーで実行すると蓄積されます)
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 dark:bg-zinc-900">
          <tr className="text-left">
            <th className="p-2 font-medium">日時</th>
            <th className="p-2 font-medium">対戦相手</th>
            <th className="p-2 text-right font-medium">勝率</th>
            <th className="p-2 text-right font-medium">勝-敗</th>
            <th className="p-2 text-right font-medium">avg ターン</th>
            <th className="p-2 text-right font-medium">seed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isA = r.deck_a_id === deckSlug;
            const myWinrate = isA
              ? r.deck_a_winrate
              : 1 - r.deck_a_winrate - (r.draws / Math.max(1, r.n_games));
            const oppName = isA ? r.deck_b_name : r.deck_a_name;
            const myWins = isA ? r.deck_a_wins : r.deck_b_wins;
            const oppWins = isA ? r.deck_b_wins : r.deck_a_wins;
            const wrColor =
              myWinrate >= 0.55
                ? "text-emerald-600 dark:text-emerald-400"
                : myWinrate <= 0.45
                  ? "text-red-600 dark:text-red-400"
                  : "text-zinc-700 dark:text-zinc-300";

            return (
              <tr
                key={r.job_id}
                className="border-t border-zinc-200 dark:border-zinc-800"
              >
                <td className="p-2 font-mono text-xs text-zinc-500 dark:text-zinc-400">
                  {r.timestamp.replace("T", " ").replace("Z", "")}
                </td>
                <td className="p-2">{oppName}</td>
                <td className={`p-2 text-right font-mono ${wrColor}`}>
                  {(myWinrate * 100).toFixed(1)}%
                </td>
                <td className="p-2 text-right font-mono">
                  {myWins}-{oppWins}
                  {r.draws > 0 && `/d${r.draws}`}
                </td>
                <td className="p-2 text-right font-mono text-xs">
                  {r.avg_turns.toFixed(1)}
                </td>
                <td className="p-2 text-right font-mono text-xs text-zinc-500 dark:text-zinc-400">
                  {r.seed}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
