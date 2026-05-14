"use client";

import useSWR from "swr";
import Link from "next/link";
import {
  fetchMatrixProgress,
  fetchMatrixLogTail,
  type MatrixProgress,
  type MatrixLogTail,
} from "@/lib/api";

/**
 * matrix 進捗 preview ページ。
 *
 * - `db/matchup_matrix.json` の incremental save を polling (= 10s 間隔)
 * - 完了 row / cell 数、 残り見積、 partial tier preview を表示
 * - per-game NDJSON log (= 将来書き出される) があれば末尾を表示
 *
 * polling 設計: matrix プロセスは触らない (= safe in-flight)、 数試合遅れの UI 反映を許容。
 */

const REFRESH_MS = 10_000;

export default function MatrixProgressPage() {
  const { data: progress, error: progressErr } = useSWR<MatrixProgress>(
    "matrix-progress",
    fetchMatrixProgress,
    { refreshInterval: REFRESH_MS },
  );
  const { data: logTail } = useSWR<MatrixLogTail>(
    "matrix-log-tail",
    () => fetchMatrixLogTail(80),
    { refreshInterval: REFRESH_MS },
  );

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 p-6">
      <header className="space-y-1">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            matrix 進捗 preview
          </h1>
          {progress?.running ? (
            <span className="inline-flex items-center gap-1.5 rounded bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              走行中
            </span>
          ) : progress?.exists ? (
            <span className="rounded bg-zinc-200 px-2 py-0.5 text-xs font-bold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              完了
            </span>
          ) : null}
          <Link
            href="/meta"
            className="text-sm text-blue-600 hover:underline dark:text-blue-400"
          >
            → メタ分析 (= 確定 matrix)
          </Link>
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          走行中の matrix を {REFRESH_MS / 1000}s 間隔で polling、 数試合遅れの
          progress を表示。 matrix プロセスは触らないので safe。
        </p>
      </header>

      {progressErr ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">progress 取得失敗</div>
          <div className="mt-1 font-mono">{String(progressErr)}</div>
        </div>
      ) : null}

      {progress?.exists === false ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          matrix がまだ生成されていません。{" "}
          <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">
            scripts/compute_matchup_matrix.py
          </code>{" "}
          を実行してください。
        </div>
      ) : null}

      {progress?.exists ? (
        <>
          <ProgressSummary p={progress} />
          <TierPreview p={progress} />
          <SpectateLink hasDecks={!!progress.decks && progress.decks.length >= 2} />
          <LogTailPanel tail={logTail} running={!!progress.running} />
        </>
      ) : null}
    </main>
  );
}

// ─────────────────────────────────────────────────────
// セクション: 観戦ページへのリンク (= 縦サイズ確保のため別ページ)
// ─────────────────────────────────────────────────────

function SpectateLink({ hasDecks }: { hasDecks: boolean }) {
  if (!hasDecks) return null;
  return (
    <section className="rounded border border-emerald-300 bg-emerald-50 p-4 dark:border-emerald-800 dark:bg-emerald-950/40">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-base font-semibold">観戦 (= サンプル試合 盤面再生)</h2>
        <Link
          href="/meta/spectate"
          className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700"
        >
          ▶ 観戦ページを開く
        </Link>
      </div>
      <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
        指定 2 デッキで 1 試合シミュレートして 既存の MatchReplay UI で 盤面再生。
        画面サイズを最大限使うため別ページに切出し。
      </p>
    </section>
  );
}

// ─────────────────────────────────────────────────────
// セクション: 全体進捗 (= 数値カード)
// ─────────────────────────────────────────────────────

function ProgressSummary({ p }: { p: MatrixProgress }) {
  const cellsDone = p.cells_done ?? 0;
  const cellsTotal = p.cells_total ?? 0;
  const pct = cellsTotal ? Math.round((cellsDone / cellsTotal) * 100) : 0;
  const lastUpdate = p.matrix_mtime
    ? new Date(p.matrix_mtime * 1000).toLocaleString()
    : "—";
  const sinceUpdateSec = p.matrix_mtime
    ? Math.max(0, Math.floor(Date.now() / 1000 - p.matrix_mtime))
    : null;

  // 簡易 ETA: cell あたりの平均所要 (= 全行均等仮定)、 現状 row 数で割って残り cell × 平均
  // 正確な ETA は per-game log があれば計算可、 ここでは粗い見積を出す
  let etaText = "—";
  if (
    p.running &&
    p.rows_done &&
    p.rows_total &&
    p.matrix_mtime &&
    p.computed_at
  ) {
    try {
      const startedAt = Date.parse(p.computed_at);
      // computed_at は最終 row 完了時刻 (= partial save) なので ETA 計算には不向き
      // 代わりに rows_done / rows_total から残り % を求めて、 1 行あたりの所要を推定する
      // 簡略のため: 残り = (1 - rows_done/rows_total) × 経過時間 / (rows_done/rows_total)
      const elapsedMs = p.matrix_mtime * 1000 - startedAt;
      if (p.rows_done > 0 && elapsedMs > 0) {
        const perRowMs = elapsedMs / p.rows_done;
        const remainRows = p.rows_total - p.rows_done;
        const remainMs = perRowMs * remainRows;
        const remainMin = Math.round(remainMs / 60_000);
        if (remainMin > 0)
          etaText = `残り ~${remainMin} 分 (= ${(perRowMs / 60_000).toFixed(1)} 分/行 × ${remainRows} 行)`;
      }
    } catch {
      etaText = "—";
    }
  }

  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="完了 row" value={`${p.rows_done ?? 0} / ${p.rows_total ?? 0}`} />
      <Stat
        label="完了 cell"
        value={`${cellsDone} / ${cellsTotal}`}
        sub={`${pct}%`}
      />
      <Stat
        label="現在 row 内 cell"
        value={`${p.last_row_cells_filled ?? 0}`}
        sub={p.running ? "(走行中)" : ""}
      />
      <Stat label="cell ごと試合数" value={`${p.n_games_per_cell ?? "?"}`} />
      <div className="col-span-2 sm:col-span-4">
        <div className="h-2 w-full overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-zinc-600 dark:text-zinc-400">
          <span>
            AI: <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">{p.ai_version ?? "?"}</code>
          </span>
          <span>
            最終更新: {lastUpdate}
            {sinceUpdateSec !== null
              ? ` (= ${formatSince(sinceUpdateSec)} 前)`
              : ""}
          </span>
          <span>ETA: {etaText}</span>
        </div>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-xs uppercase text-zinc-500">{label}</div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
      {sub ? (
        <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>
      ) : null}
    </div>
  );
}

function formatSince(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

// ─────────────────────────────────────────────────────
// セクション: tier preview (= 完了 row のみ集計)
// ─────────────────────────────────────────────────────

function TierPreview({ p }: { p: MatrixProgress }) {
  const tier = p.tier_preview ?? [];
  if (!tier.length) return null;
  return (
    <section className="rounded border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-2 text-base font-semibold">
        Tier preview ({tier.length} 行完了時点)
      </h2>
      <p className="mb-3 text-xs text-zinc-600 dark:text-zinc-400">
        走行中の row は集計対象外。 全 row 完了で確定 tier 化。
      </p>
      <ol className="space-y-1.5">
        {tier.map((t, i) => (
          <li
            key={t.deck_slug}
            className="flex items-center gap-3 text-sm"
          >
            <span className="w-8 text-right font-mono text-zinc-500">
              {i + 1}.
            </span>
            <span className="flex-1 truncate font-medium">{t.deck_name}</span>
            <span className="font-mono text-xs text-zinc-500">
              {t.matches_played} 戦
            </span>
            <span
              className={`w-16 text-right font-mono font-semibold ${
                t.avg_winrate >= 0.6
                  ? "text-emerald-600 dark:text-emerald-400"
                  : t.avg_winrate >= 0.45
                    ? "text-zinc-700 dark:text-zinc-300"
                    : "text-red-600 dark:text-red-400"
              }`}
            >
              {(t.avg_winrate * 100).toFixed(1)}%
            </span>
            <div className="h-1.5 w-32 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
              <div
                className={`h-full ${
                  t.avg_winrate >= 0.6
                    ? "bg-emerald-500"
                    : t.avg_winrate >= 0.45
                      ? "bg-zinc-400"
                      : "bg-red-500"
                }`}
                style={{ width: `${Math.min(100, t.avg_winrate * 100)}%` }}
              />
            </div>
            <Link
              href={`/meta/spectate?a=${encodeURIComponent(t.deck_slug)}`}
              className="ml-2 rounded border border-emerald-300 px-2 py-0.5 text-xs text-emerald-700 hover:bg-emerald-50 dark:border-emerald-700 dark:text-emerald-300 dark:hover:bg-emerald-950"
              title={`${t.deck_name} を P0 として観戦`}
            >
              ▶ 観戦
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

// ─────────────────────────────────────────────────────
// セクション: per-game log tail (= NDJSON が存在すれば)
// ─────────────────────────────────────────────────────

function LogTailPanel({
  tail,
  running,
}: {
  tail: MatrixLogTail | undefined;
  running: boolean;
}) {
  if (!tail) return null;
  if (!tail.exists) {
    return (
      <section className="rounded border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="mb-1 text-base font-semibold">試合 log (= NDJSON)</h2>
        <p className="text-zinc-600 dark:text-zinc-400">
          <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
            db/matrix_run_log.ndjson
          </code>{" "}
          が無い。 現在走行中の matrix プロセスはこの log を書き出さない。 次回
          matrix 実行から書き出される。
        </p>
      </section>
    );
  }
  return (
    <section className="rounded border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-2 text-base font-semibold">
        試合 log 末尾 ({tail.count ?? 0} 件 / 全 NDJSON 末尾)
        {running ? (
          <span className="ml-2 text-xs font-normal text-emerald-600 dark:text-emerald-400">
            (live)
          </span>
        ) : null}
      </h2>
      <div className="max-h-[500px] overflow-y-auto rounded bg-zinc-50 p-2 font-mono text-xs dark:bg-zinc-950">
        {tail.entries.length === 0 ? (
          <span className="text-zinc-500">log 空</span>
        ) : (
          <ul className="space-y-0.5">
            {tail.entries.slice().reverse().map((e, i) => (
              <li key={i} className="flex flex-wrap gap-2">
                {e.ts ? (
                  <span className="text-zinc-500">{shortTs(e.ts)}</span>
                ) : null}
                <span className="text-blue-600 dark:text-blue-400">
                  {e.event ?? "?"}
                </span>
                {e.deck_a_name || e.deck_a ? (
                  <span className="truncate">
                    {e.deck_a_name ?? e.deck_a}
                    {(e.deck_b_name || e.deck_b)
                      ? ` vs ${e.deck_b_name ?? e.deck_b}`
                      : ""}
                  </span>
                ) : null}
                {e.game_index !== undefined ? (
                  <span className="text-zinc-500">#{e.game_index}</span>
                ) : null}
                {e.winner !== undefined && e.winner !== null ? (
                  <span
                    className={
                      e.winner === 0
                        ? "text-emerald-600"
                        : e.winner === 1
                          ? "text-red-600"
                          : "text-zinc-500"
                    }
                  >
                    W:P{e.winner}
                  </span>
                ) : null}
                {e.turns !== undefined ? (
                  <span className="text-zinc-500">T{e.turns}</span>
                ) : null}
                {e.p0_life_left !== undefined && e.p1_life_left !== undefined ? (
                  <span className="text-zinc-500">
                    life {e.p0_life_left}-{e.p1_life_left}
                  </span>
                ) : null}
                {e.cell_winrate !== undefined ? (
                  <span className="font-semibold">
                    cell {(e.cell_winrate * 100).toFixed(0)}% ({e.cell_wins}-
                    {e.cell_losses}
                    {e.cell_draws ? `-${e.cell_draws}` : ""})
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function shortTs(ts: string): string {
  // "2026-05-14T07:58:54Z" → "07:58:54"
  const m = ts.match(/T(\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : ts;
}
