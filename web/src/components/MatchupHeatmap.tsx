"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { MatchupMatrix } from "@/lib/types";

function winrateColor(wr: number | null): string {
  if (wr === null) return "bg-zinc-100 dark:bg-zinc-800";
  if (wr >= 0.7) return "bg-emerald-600 text-white";
  if (wr >= 0.55) return "bg-emerald-300 text-emerald-900";
  if (wr >= 0.45) return "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100";
  if (wr >= 0.3) return "bg-red-300 text-red-900";
  return "bg-red-600 text-white";
}

export function MatchupHeatmap({ data }: { data: MatchupMatrix }) {
  const [sortByAvg, setSortByAvg] = useState(true);

  const { rows, decks } = useMemo(() => {
    // 平均勝率を計算
    const avgMap = new Map<string, number>();
    for (const r of data.matrix) {
      let sum = 0;
      let n = 0;
      for (const c of r.row) {
        if (c.winrate !== null) {
          sum += c.winrate;
          n++;
        }
      }
      avgMap.set(r.deck_a, n > 0 ? sum / n : 0);
    }
    let order = data.matrix.map((r) => r.deck_a);
    if (sortByAvg) {
      order = [...order].sort(
        (a, b) => (avgMap.get(b) ?? 0) - (avgMap.get(a) ?? 0),
      );
    }
    const rowsByA = new Map(data.matrix.map((r) => [r.deck_a, r]));
    const rows = order.map((slug) => {
      const original = rowsByA.get(slug)!;
      // 列ヘッダの順序 (order) に合わせて各行の cell も並び替え。
      // これをしないと、 ソート時に列ヘッダの「対戦相手」 とセルの結果が対応しなくなる。
      const cellByB = new Map(original.row.map((c) => [c.deck_b, c]));
      const sortedRow = order.map(
        (bSlug) =>
          cellByB.get(bSlug) ?? {
            deck_b: bSlug,
            winrate: null,
            wins: 0,
            losses: 0,
            draws: 0,
            avg_turns: 0,
          },
      );
      return {
        ...original,
        row: sortedRow,
        avg: avgMap.get(slug) ?? 0,
      };
    });
    const decks = order.map(
      (slug) =>
        data.decks.find((d) => d.slug === slug) ?? { slug, name: slug },
    );
    return { rows, decks };
  }, [data, sortByAvg]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1 text-xs text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={sortByAvg}
            onChange={(e) => setSortByAvg(e.target.checked)}
          />
          平均勝率順 (強い順) でソート
        </label>
        <span className="ml-auto text-xs text-zinc-500 dark:text-zinc-400">
          色: 緑 = 勝ち越し / 赤 = 負け越し / 灰 = 五分
        </span>
      </div>

      <div className="overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="text-xs">
          <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900">
            <tr>
              <th className="sticky left-0 z-10 min-w-[160px] border-b border-r border-zinc-200 bg-zinc-50 px-2 py-1 text-left font-medium dark:border-zinc-800 dark:bg-zinc-900">
                自 \ 対戦相手
              </th>
              {decks.map((d) => (
                <th
                  key={d.slug}
                  className="border-b border-zinc-200 px-1 py-1 text-center font-normal dark:border-zinc-800"
                  style={{ writingMode: "vertical-rl", height: 90 }}
                  title={d.name}
                >
                  <Link
                    href={`/decks/${encodeURIComponent(d.slug)}`}
                    className="hover:underline"
                  >
                    {d.name}
                  </Link>
                </th>
              ))}
              <th className="border-b border-l border-zinc-200 px-2 py-1 text-right font-medium dark:border-zinc-800">
                平均
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.deck_a}>
                <th className="sticky left-0 z-10 border-r border-t border-zinc-200 bg-white px-2 py-1 text-left font-normal dark:border-zinc-800 dark:bg-zinc-950">
                  <Link
                    href={`/decks/${encodeURIComponent(r.deck_a)}`}
                    className="hover:underline"
                  >
                    {r.deck_a_name}
                  </Link>
                </th>
                {r.row.map((cell) => (
                  <td
                    key={cell.deck_b}
                    className={`border-t border-zinc-200 px-1 py-1 text-center font-mono text-[11px] dark:border-zinc-800 ${winrateColor(cell.winrate)}`}
                    title={
                      cell.winrate === null
                        ? "self"
                        : `vs ${cell.deck_b}: ${cell.wins}-${cell.losses}${cell.draws ? `/d${cell.draws}` : ""} avg ${cell.avg_turns}t`
                    }
                  >
                    {cell.winrate === null
                      ? "—"
                      : `${Math.round(cell.winrate * 100)}`}
                  </td>
                ))}
                <td className="border-l border-t border-zinc-200 px-2 py-1 text-right font-mono dark:border-zinc-800">
                  {Math.round(r.avg * 100)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
