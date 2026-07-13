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
      <div className="text-sm text-[color:var(--text-muted)]">
        履歴読み込み中…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-3 text-sm text-[color:var(--danger)]">
        {error}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-3 text-sm text-[color:var(--text-muted)]">
        まだ対戦履歴がありません (上の対戦ランナーで実行すると蓄積されます)
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-[color:var(--border-1)]">
      <table className="w-full text-sm">
        <thead className="bg-[color:var(--surface-2)]">
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
                ? "text-[color:var(--accent)]"
                : myWinrate <= 0.45
                  ? "text-[color:var(--danger)]"
                  : "text-[color:var(--text-default)]";

            return (
              <tr
                key={r.job_id}
                className="border-t border-[color:var(--border-1)]"
              >
                <td className="p-2 font-mono text-xs text-[color:var(--text-muted)]">
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
                <td className="p-2 text-right font-mono text-xs text-[color:var(--text-muted)]">
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
