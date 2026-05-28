import Link from "next/link";
import { fetchAuditCoverage } from "@/lib/api";
import type { AuditCardHealth, AuditCoverage } from "@/lib/api";
import { PageShell } from "@/components/ui/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";

/**
 * 徹底改善 system coverage dashboard (= docs/AUTO_AUDIT_SYSTEM.md)。
 *
 * per-card 健全性 + per-primitive 統計 を 一覧 表示。 health=warn/error の card は
 * 優先 review queue。
 */
export default async function AuditPage() {
  let data: AuditCoverage | null = null;
  let error: string | null = null;
  try {
    data = await fetchAuditCoverage();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !data) {
    return (
      <PageShell>
        <PageHeader
          title="徹底改善 system audit"
          description="docs/AUTO_AUDIT_SYSTEM.md 全 4 layer の 健全性 ダッシュボード"
        />
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-700 dark:bg-red-950 dark:text-red-200">
          audit_coverage.json が ありません。 先 に 以下 を 実行 してください:
          <pre className="mt-2 rounded bg-white p-2 text-xs dark:bg-zinc-900">
            {`.venv/bin/python scripts/audit_overlay_static.py
.venv/bin/python scripts/audit_runtime_invariants.py --n-games 10
.venv/bin/python scripts/audit_cardqa_tag.py
.venv/bin/python scripts/audit_coverage_report.py`}
          </pre>
          {error && <div className="mt-2 text-xs">error: {error}</div>}
        </div>
      </PageShell>
    );
  }

  const warnCards = data.cards.filter((c) => c.health === "warn" || c.health === "error");
  const topPrimitives = data.primitives.slice(0, 20);
  const overallPct = ((data.summary.by_health.ok ?? 0) / data.summary.total_cards) * 100;

  return (
    <PageShell>
      <PageHeader
        title="徹底改善 system audit"
        description="docs/AUTO_AUDIT_SYSTEM.md Layer 1-4 の 自動 監査 結果 ダッシュボード"
        meta={`generated: ${data.generated_at}`}
      />

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="全 card" value={data.summary.total_cards} />
        <Metric
          label="健全 (= ok)"
          value={data.summary.by_health.ok ?? 0}
          sub={`${overallPct.toFixed(1)}%`}
          tone="green"
        />
        <Metric
          label="warn / error"
          value={(data.summary.by_health.warn ?? 0) + (data.summary.by_health.error ?? 0)}
          tone="amber"
        />
        <Metric label="runtime 違反" value={data.summary.runtime_violations_total} tone="red" />
        <Metric label="Layer 1 静的 issues" value={data.summary.static_issues_total} />
        <Metric label="runtime effect events" value={data.summary.runtime_events_total} />
        <Metric label="cardqa 件数" value={data.summary.cardqa_total} />
        <Metric label="primitive 種別 数" value={data.summary.primitive_distinct} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200">
          優先 review queue (= warn/error, {warnCards.length} 件)
        </h2>
        {warnCards.length === 0 ? (
          <p className="text-sm text-zinc-500">全 card 健全 (= warn/error なし)</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-zinc-300 text-xs uppercase text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                <tr>
                  <th className="py-2 pr-3">card</th>
                  <th className="py-2 pr-3">health</th>
                  <th className="py-2 pr-3">静的 issues</th>
                  <th className="py-2 pr-3">runtime 違反</th>
                  <th className="py-2 pr-3">cardqa</th>
                  <th className="py-2 pr-3">rules</th>
                </tr>
              </thead>
              <tbody>
                {warnCards.slice(0, 100).map((c) => (
                  <tr key={c.card_id} className="border-b border-zinc-100 dark:border-zinc-800">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/cards?card=${encodeURIComponent(c.card_id)}`}
                        className="text-blue-700 hover:underline dark:text-blue-400"
                      >
                        {c.card_id}
                      </Link>
                      <div className="text-xs text-zinc-500">{c.name}</div>
                    </td>
                    <td className="py-2 pr-3">
                      <HealthBadge health={c.health} />
                    </td>
                    <td className="py-2 pr-3">{c.static_issue_count}</td>
                    <td className="py-2 pr-3">{c.runtime_violation_count}</td>
                    <td className="py-2 pr-3">{c.cardqa_count}</td>
                    <td className="py-2 pr-3 text-xs">
                      {c.static_issues.map((i) => i.rule_id).join(", ") ||
                        c.runtime_violations.map((i) => i.rule_id).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {warnCards.length > 100 && (
              <p className="mt-2 text-xs text-zinc-500">…他 {warnCards.length - 100} 件</p>
            )}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200">
          top 20 primitives (= overlay 使用 頻度)
        </h2>
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
          {topPrimitives.map((p) => (
            <div
              key={p.primitive}
              className="rounded border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
            >
              <div className="font-mono text-xs text-zinc-700 dark:text-zinc-300">
                {p.primitive}
              </div>
              <div className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                {p.usage_count}
              </div>
            </div>
          ))}
        </div>
      </section>
    </PageShell>
  );
}

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number;
  sub?: string;
  tone?: "green" | "amber" | "red";
}) {
  const toneClass =
    tone === "green"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "amber"
      ? "text-amber-700 dark:text-amber-400"
      : tone === "red"
      ? "text-red-700 dark:text-red-400"
      : "text-zinc-900 dark:text-zinc-100";
  return (
    <div className="rounded border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`text-2xl font-semibold ${toneClass}`}>{value.toLocaleString()}</div>
      {sub && <div className="text-xs text-zinc-500">{sub}</div>}
    </div>
  );
}

function HealthBadge({ health }: { health: AuditCardHealth["health"] }) {
  const cls =
    health === "ok"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
      : health === "info"
      ? "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
      : health === "warn"
      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
      : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {health}
    </span>
  );
}
