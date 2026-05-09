import Link from "next/link";
import { fetchMatchGames, fetchMatchSummary } from "@/lib/api";
import type { GameLog, MatchSummary } from "@/lib/types";

export default async function MatchJobPage({
  params,
}: {
  params: Promise<{ slug: string; job_id: string }>;
}) {
  const { slug, job_id } = await params;

  let summary: MatchSummary | null = null;
  let games: GameLog[] = [];
  let error: string | null = null;

  try {
    [summary, games] = await Promise.all([
      fetchMatchSummary(job_id),
      fetchMatchGames(job_id),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-6">
      <header className="space-y-1">
        <Link
          href={`/decks/${encodeURIComponent(slug)}`}
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← /decks/{slug}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          試合ログ ({job_id})
        </h1>
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
          <div className="mt-2 text-red-800 dark:text-red-300">
            ジョブが in-memory cache から消えた可能性があります (API 再起動など、最大 10 件保持)。
          </div>
        </div>
      ) : summary ? (
        <>
          <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="text-sm text-zinc-500 dark:text-zinc-400">
              {summary.deck_a_name} vs {summary.deck_b_name}
            </div>
            <div className="mt-1 flex flex-wrap items-baseline gap-3">
              <span className="font-mono text-2xl">
                {(summary.deck_a_winrate * 100).toFixed(1)}%
              </span>
              <span className="text-sm text-zinc-500 dark:text-zinc-400">
                ({summary.deck_a_wins}-{summary.deck_b_wins}
                {summary.draws > 0 && `, ${summary.draws} draws`} / {summary.n_games}戦)
              </span>
              <span className="text-sm text-zinc-500 dark:text-zinc-400">
                avg {summary.avg_turns.toFixed(1)} ターン
              </span>
            </div>
          </div>

          <section className="space-y-2">
            <h2 className="text-lg font-medium">試合一覧</h2>
            <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full text-sm">
                <thead className="bg-zinc-50 dark:bg-zinc-900">
                  <tr className="text-left">
                    <th className="p-2 font-medium">#</th>
                    <th className="p-2 font-medium">先攻</th>
                    <th className="p-2 font-medium">勝者</th>
                    <th className="p-2 text-right font-medium">turns</th>
                    <th className="p-2 text-right font-medium">actions</th>
                    <th className="p-2 text-right font-medium">P0 life</th>
                    <th className="p-2 text-right font-medium">P1 life</th>
                    <th className="p-2 font-medium">log</th>
                  </tr>
                </thead>
                <tbody>
                  {games.map((g) => (
                    <tr
                      key={g.index}
                      className="border-t border-zinc-200 dark:border-zinc-800"
                    >
                      <td className="p-2 font-mono">{g.index}</td>
                      <td className="p-2">
                        {g.first_player === 0
                          ? summary.deck_a_name
                          : summary.deck_b_name}
                      </td>
                      <td className="p-2">
                        {g.winner === -1
                          ? "draw"
                          : g.winner === 0
                            ? summary.deck_a_name
                            : summary.deck_b_name}
                      </td>
                      <td className="p-2 text-right font-mono">{g.turns}</td>
                      <td className="p-2 text-right font-mono text-xs">
                        {g.actions}
                      </td>
                      <td className="p-2 text-right font-mono text-xs">
                        {g.p0_life_left}
                      </td>
                      <td className="p-2 text-right font-mono text-xs">
                        {g.p1_life_left}
                      </td>
                      <td className="p-2">
                        <Link
                          href={`/decks/${encodeURIComponent(slug)}/match/${encodeURIComponent(job_id)}/${g.index}`}
                          className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                        >
                          開く →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
