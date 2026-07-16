"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDeckReport, requestDeckAnalysis, type DeckReport, type DeckReportBody } from "@/lib/api";

// ユーザーデッキの裏分析レポート (= AI vs AI 相性 + 役割内訳 + キーカード)。
// 保存時に enqueue されワーカーが 1マッチずつ計算 → ここは読むだけ + 実行中は poll して
// 途中経過(相性が1つずつ埋まる)を表示。 失敗時は「再分析」で再開できる。
export function DeckReportPanel({ slug }: { slug: string }) {
  const [data, setData] = useState<DeckReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetchDeckReport(slug);
      setData(r);
      if (r.status === "pending" || r.status === "running") {
        timer.current = setTimeout(load, 5000); // 実行中は 5 秒ごとに更新
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [slug]);

  useEffect(() => {
    load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const onRequest = async () => {
    setRequesting(true);
    setError(null);
    try {
      await requestDeckAnalysis(slug);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRequesting(false);
    }
  };

  if (!data) {
    return (
      <Shell>
        <div className="text-sm text-[color:var(--text-muted)]">
          {error ? `分析の読み込みに失敗: ${error}` : "読み込み中…"}
        </div>
      </Shell>
    );
  }

  const { status, stale, report } = data;
  const running = status === "pending" || status === "running";
  const done = report?.matchups?.length ?? 0;
  const total = report?.n_opponents ?? 16;

  const AnalyzeButton = ({ label }: { label: string }) => (
    <button
      type="button"
      onClick={onRequest}
      disabled={requesting}
      className="rounded-[var(--radius)] bg-[color:var(--brand)] px-4 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
    >
      {requesting ? "受付中…" : label}
    </button>
  );

  return (
    <Shell>
      {/* 状態ヘッダー */}
      {status === "none" && (
        <div className="flex flex-col items-start gap-3">
          <div className="text-sm text-[color:var(--text-muted)]">
            このデッキはまだ分析されていません。
          </div>
          <AnalyzeButton label="分析する" />
        </div>
      )}

      {status === "failed" && (
        <div className="flex flex-col items-start gap-3">
          <div className="text-sm text-[color:var(--danger)]">
            分析に失敗しました{done > 0 ? `（${done}/${total} まで計測済み）` : ""}。
            もう一度お試しください（途中から再開します）。
          </div>
          <AnalyzeButton label="再分析" />
        </div>
      )}

      {running && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm text-[color:var(--text-default)]">
            <Spinner />
            <span>
              {status === "pending" && done === 0
                ? "分析待ち… 順番が来たら AI 対戦で相性を計測します。"
                : `相性を計測中… ${done}/${total} デッキ`}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[color:var(--surface-2)]">
            <div
              className="h-full rounded-full bg-[color:var(--brand)] transition-all"
              style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* レポート本体 (= 実行中は途中経過、 完了なら全体) */}
      {report && (report.roles.length > 0 || done > 0) && (
        <ReportBody report={report} running={running} stale={stale && !running} onReanalyze={onRequest} requesting={requesting} />
      )}

      {error && <div className="text-xs text-[color:var(--danger)]">{error}</div>}
    </Shell>
  );
}

function ReportBody({
  report,
  running,
  stale,
  onReanalyze,
  requesting,
}: {
  report: DeckReportBody;
  running: boolean;
  stale: boolean;
  onReanalyze: () => void;
  requesting: boolean;
}) {
  const played = report.matchups.filter((m) => m.n > 0);
  const avgPct = Math.round(report.matchup_summary.avg * 100);
  return (
    <div className="space-y-3">
      {!running && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="rounded px-2 py-0.5 text-xs font-bold text-white" style={{ background: "var(--brand)" }}>
              {report.archetype}
            </span>
            {played.length > 0 && (
              <span className="text-sm text-[color:var(--text-default)]">
                メタ{played.length}デッキ相手の平均勝率{" "}
                <span className="font-semibold text-[color:var(--text-strong)]">{avgPct}%</span>
              </span>
            )}
          </div>
          {stale && (
            <button
              type="button"
              onClick={onReanalyze}
              disabled={requesting}
              className="rounded-[var(--radius)] border border-[color:var(--border-2)] px-2.5 py-1 text-xs text-[color:var(--text-default)] hover:border-[color:var(--brand)] disabled:opacity-50"
            >
              {requesting ? "受付中…" : "デッキ変更後 · 再分析"}
            </button>
          )}
        </div>
      )}

      {/* ⭐ 戦略分析 (= 探索で発掘した「戦い方の型・機能条件」) を最上部に。 */}
      {report.insights && report.insights.length > 0 && (
        <Section title="戦略分析（AIが多数の試合を探索して発掘）">
          <div className="space-y-2">
            {report.insights.map((ins, i) => (
              <InsightCard key={i} insight={ins} />
            ))}
          </div>
        </Section>
      )}

      {/* ⭐ 相手タイプ別の立ち回り (#8)。 */}
      {report.matchup_plans && report.matchup_plans.length > 0 && (
        <Section title="相手タイプ別の立ち回り">
          <div className="space-y-1.5">
            {report.matchup_plans.map((p) => {
              const pct = Math.round(p.win_rate * 100);
              const tone = pct >= 55 ? "var(--brand)" : pct <= 45 ? "var(--danger)" : "var(--text-muted)";
              return (
                <div
                  key={p.archetype}
                  className="rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-2)] px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-[color:var(--text-strong)]">vs {p.archetype}</span>
                    <span className="text-xs font-semibold" style={{ color: tone }}>
                      勝率 {pct}%
                    </span>
                    <span className="text-[10px] text-[color:var(--text-muted)]">（{p.n}戦）</span>
                  </div>
                  <div className="mt-0.5 text-xs leading-relaxed text-[color:var(--text-default)]">{p.detail}</div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* ⭐ 勝ちに繋がるコンボ (#5)。 */}
      {report.win_combos && report.win_combos.length > 0 && (
        <Section title="勝ちに繋がるコンボ（実戦で検証）">
          <div className="space-y-1.5">
            {report.win_combos.map((c, i) => (
              <div
                key={i}
                className="rounded-[var(--radius)] border border-l-[3px] bg-[color:var(--surface-2)] px-3 py-2"
                style={{ borderColor: "var(--border-1)", borderLeftColor: "#9333ea" }}
              >
                <div className="text-sm font-semibold text-[color:var(--text-strong)]">
                  {c.cards.join(" ＋ ")}
                </div>
                <div className="mt-0.5 text-xs leading-relaxed text-[color:var(--text-default)]">
                  揃った試合の勝率 <span className="font-semibold">{Math.round(c.win_rate * 100)}%</span>
                  （片方だけ/未達 {Math.round(c.base_win_rate * 100)}%）。 この組み合わせが決め手になる。
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* 回り方サマリ (= 勝敗に依らず常に出る記述統計)。 */}
      {report.profile && Object.keys(report.profile).length > 0 && (
        <Section title="このデッキの回り方（平均）">
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {profileStat("平均決着", report.profile.avg_turns, "T")}
            {profileStat("攻め始め", report.profile.first_attack_turn, "T目")}
            {profileStat("攻撃(通し)", report.profile.attacks_landed, "回")}
            {profileStat("相手キャラ除去", report.profile.ko_dealt, "体")}
            {profileStat("自キャラ喪失", report.profile.ko_lost, "体")}
            {profileStat("被攻撃", report.profile.opp_attacks, "回")}
          </div>
        </Section>
      )}

      {report.top_cards && report.top_cards.length > 0 && (
        <Section title="よく盤面に出るカード（出現率）">
          <div className="flex flex-wrap gap-1.5">
            {report.top_cards.map((c) => (
              <span
                key={c.card_id}
                className="rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-2)] px-2 py-0.5 text-xs text-[color:var(--text-default)]"
              >
                {c.name}
                <span className="ml-1 text-[10px] text-[color:var(--text-muted)]">{Math.round(c.play_rate * 100)}%</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {report.roles.length > 0 && (
        <Section title="役割の内訳">
          <div className="flex flex-wrap gap-1.5">
            {report.roles.map((r) => (
              <span
                key={r.role}
                className="rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-2)] px-2 py-0.5 text-xs text-[color:var(--text-default)]"
              >
                {r.label} <span className="font-semibold text-[color:var(--text-strong)]">{r.count}</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {report.key_cards.length > 0 && (
        <Section title="キーカード（勝ち筋）">
          <div className="flex flex-wrap gap-1.5">
            {report.key_cards.map((k) => (
              <span
                key={k.card_id}
                className="rounded-[var(--radius)] border border-[color:var(--border-1)] px-2 py-0.5 text-xs text-[color:var(--text-default)]"
              >
                {k.name}
                <span className="ml-1 text-[10px] text-[color:var(--text-muted)]">{k.label}</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {played.length > 0 && (
        <Section title="メタ相性（AI対戦で計測）">
          <ul className="space-y-1">
            {[...played]
              .sort((a, b) => b.win_rate - a.win_rate)
              .map((m) => {
                const pct = Math.round(m.win_rate * 100);
                const tone = pct >= 60 ? "var(--brand)" : pct <= 40 ? "var(--danger)" : "var(--border-2)";
                return (
                  <li key={m.slug} className="flex items-center gap-2 text-xs">
                    <span className="w-28 shrink-0 truncate text-[color:var(--text-default)]">
                      {m.leader_name || m.name}
                    </span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-[color:var(--surface-2)]">
                      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
                    </div>
                    <span className="w-9 shrink-0 text-right font-mono text-[color:var(--text-strong)]">{pct}%</span>
                  </li>
                );
              })}
          </ul>
        </Section>
      )}

      {!running && (
        <p className="text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          ※ 両者を同じ基準 AI が操縦した時の相対勝率です（理論上の有利不利ではなく、
          現状の AI がこのデッキを操縦した場合の目安）。1マッチアップ {report.n_games_per_matchup} 戦。
        </p>
      )}
    </div>
  );
}

// 洞察の種別ごとの見た目 (色 + アイコン + ラベル)。
const INSIGHT_META: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  playstyle: { color: "#2563eb", label: "戦い方", icon: <IconCompass /> },
  tempo: { color: "#16a34a", label: "テンポ", icon: <IconBolt /> },
  removal: { color: "#dc2626", label: "除去", icon: <IconTarget /> },
  key_play: { color: "#d97706", label: "着地タイミング", icon: <IconClock /> },
  key_card: { color: "#9333ea", label: "機能条件", icon: <IconKey /> },
};

function InsightCard({ insight }: { insight: { kind: string; title: string; detail: string; strength?: number } }) {
  const meta = INSIGHT_META[insight.kind] ?? { color: "var(--brand)", label: "傾向", icon: <IconKey /> };
  const strength = Math.max(0, Math.min(1, insight.strength ?? 0));
  return (
    <div
      className="rounded-[var(--radius)] border border-l-[3px] bg-[color:var(--surface-2)] p-3"
      style={{ borderColor: "var(--border-1)", borderLeftColor: meta.color }}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded"
          style={{ background: `${meta.color}22`, color: meta.color }}
        >
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
              style={{ background: `${meta.color}22`, color: meta.color }}
            >
              {meta.label}
            </span>
            {insight.strength != null && (
              <span
                className="inline-flex items-center gap-1 text-[10px] text-[color:var(--text-muted)]"
                title={`勝率差 ${Math.round(strength * 100)}pt`}
              >
                <span className="h-1 w-10 overflow-hidden rounded-full bg-[color:var(--surface-3)]">
                  <span className="block h-full rounded-full" style={{ width: `${strength * 100}%`, background: meta.color }} />
                </span>
                相関 {strength >= 0.35 ? "強" : strength >= 0.2 ? "中" : "弱"}
              </span>
            )}
          </div>
          <div className="mt-1 text-sm font-semibold text-[color:var(--text-strong)]">{insight.title}</div>
          <div className="mt-0.5 text-xs leading-relaxed text-[color:var(--text-default)]">{insight.detail}</div>
        </div>
      </div>
    </div>
  );
}

function IconCompass() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="9" />
      <path d="M16 8l-2.5 5.5L8 16l2.5-5.5z" strokeLinejoin="round" />
    </svg>
  );
}
function IconBolt() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
      <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
    </svg>
  );
}
function IconTarget() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
    </svg>
  );
}
function IconClock() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" />
    </svg>
  );
}
function IconKey() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8">
      <circle cx="8" cy="15" r="4" />
      <path d="M11 12l8-8M17 6l2 2M14 9l2 2" strokeLinecap="round" />
    </svg>
  );
}

function profileStat(label: string, value: number | undefined, unit: string) {
  if (value == null) return null;
  return (
    <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-2)] px-2 py-1">
      <div className="text-[10px] text-[color:var(--text-muted)]">{label}</div>
      <div className="text-sm font-semibold text-[color:var(--text-strong)]">
        {value}
        <span className="ml-0.5 text-[10px] font-normal text-[color:var(--text-muted)]">{unit}</span>
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4">
      <h3 className="text-sm font-semibold text-[color:var(--text-strong)]">AI分析レポート</h3>
      {children}
    </section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-[color:var(--text-muted)]">{title}</div>
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <svg className="h-4 w-4 shrink-0 animate-spin text-[color:var(--brand)]" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
    </svg>
  );
}
