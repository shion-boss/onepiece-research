"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchMetaMatrix } from "@/lib/api";
import type { MatchupMatrix } from "@/lib/types";

interface Props {
  slug: string;
}

interface OpponentRecord {
  slug: string;
  name: string;
  winrate: number | null;
  wins: number;
  losses: number;
  draws: number;
}

export function DeckMatchupRow({ slug }: Props) {
  const [matrix, setMatrix] = useState<MatchupMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchMetaMatrix()
      .then((m) => {
        if (cancelled) return;
        setMatrix(m);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div className="text-sm text-zinc-500">対戦データ読み込み中...</div>;
  }
  if (error) {
    return (
      <div className="text-sm text-zinc-500">
        matchup matrix 未生成 ({error})。<br />
        <code className="font-mono text-xs">
          .venv/bin/python scripts/compute_matchup_matrix.py
        </code>{" "}
        を実行してください
      </div>
    );
  }
  if (!matrix) return null;

  const row = matrix.matrix.find((r) => r.deck_a === slug);
  if (!row) {
    return (
      <div className="text-sm text-zinc-500">
        このデッキ ({slug}) は matchup matrix に登録されていません。
      </div>
    );
  }

  // 自身を除いた相手別の勝率を集計
  const opponents: OpponentRecord[] = row.row
    .filter((c) => c.deck_b !== slug)
    .map((c) => {
      const meta = matrix.decks.find((d) => d.slug === c.deck_b);
      return {
        slug: c.deck_b,
        name: meta?.name ?? c.deck_b,
        winrate: c.winrate,
        wins: c.wins,
        losses: c.losses,
        draws: c.draws,
      };
    })
    .sort((a, b) => (b.winrate ?? -1) - (a.winrate ?? -1));

  // 全体勝率
  const total = opponents.reduce(
    (acc, o) => {
      acc.wins += o.wins;
      acc.losses += o.losses;
      acc.draws += o.draws;
      return acc;
    },
    { wins: 0, losses: 0, draws: 0 },
  );
  const totalGames = total.wins + total.losses + total.draws;
  const overallRate = totalGames ? total.wins / totalGames : 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3 text-sm">
        <span className="rounded bg-zinc-100 px-2 py-1 font-mono dark:bg-zinc-800">
          総合勝率 {(overallRate * 100).toFixed(1)}%
        </span>
        <span className="text-zinc-600 dark:text-zinc-400">
          {total.wins}勝 {total.losses}敗 {total.draws}分 / 計 {totalGames} 戦
          (n={matrix.n_games}/対戦)
        </span>
      </div>
      <ul className="space-y-1">
        {opponents.map((opp) => (
          <li
            key={opp.slug}
            className="grid grid-cols-[160px_1fr_60px] items-center gap-2 text-sm"
          >
            <Link
              href={`/decks/${encodeURIComponent(opp.slug)}`}
              className="truncate hover:underline"
              title={opp.name}
            >
              {opp.name}
            </Link>
            <div className="relative h-4 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
              {opp.winrate !== null && (
                <div
                  className={`absolute inset-y-0 left-0 ${
                    opp.winrate >= 0.6
                      ? "bg-emerald-500"
                      : opp.winrate >= 0.4
                        ? "bg-amber-400"
                        : "bg-rose-500"
                  }`}
                  style={{ width: `${Math.round(opp.winrate * 100)}%` }}
                />
              )}
            </div>
            <span
              className={`text-right font-mono ${
                opp.winrate === null
                  ? "text-zinc-400"
                  : opp.winrate >= 0.6
                    ? "text-emerald-700 dark:text-emerald-400"
                    : opp.winrate >= 0.4
                      ? "text-amber-700 dark:text-amber-400"
                      : "text-rose-700 dark:text-rose-400"
              }`}
            >
              {opp.winrate === null
                ? "—"
                : `${Math.round(opp.winrate * 100)}%`}
            </span>
          </li>
        ))}
      </ul>
      <div className="text-xs text-zinc-500 dark:text-zinc-400">
        matrix 計算日時: {new Date(matrix.computed_at).toLocaleString("ja-JP")}
      </div>
    </div>
  );
}
