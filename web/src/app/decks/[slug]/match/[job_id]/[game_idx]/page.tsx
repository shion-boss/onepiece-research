import Link from "next/link";
import { fetchMatchGame, fetchMatchSummary } from "@/lib/api";
import { MatchLogViewer } from "@/components/MatchLogViewer";
import type { GameLog, MatchSummary } from "@/lib/types";

export default async function MatchGamePage({
  params,
}: {
  params: Promise<{ slug: string; job_id: string; game_idx: string }>;
}) {
  const { slug: rawSlug, job_id, game_idx } = await params;
  const slug = decodeURIComponent(rawSlug);
  const idx = Number(game_idx);

  let summary: MatchSummary | null = null;
  let game: GameLog | null = null;
  let error: string | null = null;

  try {
    [summary, game] = await Promise.all([
      fetchMatchSummary(job_id),
      fetchMatchGame(job_id, idx),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
      <header className="space-y-1">
        <Link
          href={`/decks/${encodeURIComponent(slug)}/match/${encodeURIComponent(job_id)}`}
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← 試合一覧 ({job_id})
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          Game #{idx}
        </h1>
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      ) : summary && game ? (
        <>
          <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="flex flex-wrap items-baseline gap-3">
              <Badge color={game.winner === 0 ? "green" : game.winner === 1 ? "red" : "gray"}>
                {game.winner === -1
                  ? "DRAW"
                  : `WIN: ${game.winner === 0 ? summary.deck_a_name : summary.deck_b_name}`}
              </Badge>
              <span className="text-sm text-zinc-600 dark:text-zinc-400">
                先攻: {game.first_player === 0 ? summary.deck_a_name : summary.deck_b_name}
              </span>
              <Link
                href={`/decks/${encodeURIComponent(slug)}/match/${encodeURIComponent(job_id)}/${idx}/replay`}
                className="ml-auto rounded bg-violet-600 px-3 py-1 text-sm font-medium text-white hover:bg-violet-500"
              >
                ▶ 盤面リプレイで見る
              </Link>
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-3 text-sm sm:grid-cols-5">
              <Stat label="turns" value={game.turns} />
              <Stat label="actions" value={game.actions} />
              <Stat
                label={`${summary.deck_a_name} life`}
                value={game.p0_life_left}
              />
              <Stat
                label={`${summary.deck_b_name} life`}
                value={game.p1_life_left}
              />
              <Stat
                label="log lines"
                value={game.log.length}
              />
            </dl>
          </div>

          <section className="space-y-2">
            <h2 className="text-lg font-medium">プレイログ</h2>
            <MatchLogViewer log={game.log} />
          </section>
        </>
      ) : null}
    </main>
  );
}

function Badge({
  color,
  children,
}: {
  color: "green" | "red" | "gray";
  children: React.ReactNode;
}) {
  const cls = {
    green:
      "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100",
    red: "bg-red-100 text-red-900 dark:bg-red-900 dark:text-red-100",
    gray: "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100",
  }[color];
  return (
    <span className={`rounded px-2 py-0.5 text-sm font-medium ${cls}`}>
      {children}
    </span>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className="font-mono text-base">{value}</dd>
    </div>
  );
}
