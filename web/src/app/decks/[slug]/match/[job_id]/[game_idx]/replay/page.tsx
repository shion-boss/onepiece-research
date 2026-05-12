import Link from "next/link";
import { fetchMatchReplay } from "@/lib/api";
import { MatchReplay } from "@/components/MatchReplay";
import type { ReplayResponse } from "@/lib/types";

export default async function ReplayPage({
  params,
}: {
  params: Promise<{ slug: string; job_id: string; game_idx: string }>;
}) {
  const { slug: rawSlug, job_id, game_idx } = await params;
  const slug = decodeURIComponent(rawSlug);
  const idx = Number(game_idx);

  let replay: ReplayResponse | null = null;
  let error: string | null = null;

  try {
    replay = await fetchMatchReplay(job_id, idx);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <main className="flex h-screen w-full flex-col gap-2 px-4 py-2">
      <header className="flex flex-wrap items-center gap-3 text-xs text-zinc-600 dark:text-zinc-400">
        <Link
          href={`/decks/${encodeURIComponent(slug)}/match/${encodeURIComponent(job_id)}/${idx}`}
          className="hover:underline"
        >
          ← Game #{idx}
        </Link>
        {replay && (
          <>
            <span className="font-medium text-zinc-800 dark:text-zinc-200">
              {replay.deck_a_name}
            </span>
            <span>vs</span>
            <span className="font-medium text-zinc-800 dark:text-zinc-200">
              {replay.deck_b_name}
            </span>
            <span>
              先攻{" "}
              {replay.first_player === 0
                ? replay.deck_a_name
                : replay.deck_b_name}
            </span>
            <span>
              勝者{" "}
              {replay.winner === -1
                ? "DRAW"
                : replay.winner === 0
                  ? replay.deck_a_name
                  : replay.deck_b_name}
            </span>
            <span>{replay.turns} ターン</span>
          </>
        )}
      </header>

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
          <div className="mt-2 text-red-800 dark:text-red-300">
            ジョブが in-memory cache から消えた可能性があります (API 再起動など、最大 10 件保持)。
          </div>
        </div>
      ) : replay ? (
        <MatchReplay replay={replay} />
      ) : null}
    </main>
  );
}
