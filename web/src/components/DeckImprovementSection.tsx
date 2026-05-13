"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  applyDeckImprovement,
  fetchDecks,
  fetchDeckImprovements,
  runMctsImprovements,
} from "@/lib/api";
import type {
  DeckImprovementsResponse,
  DeckSummary,
  ImprovementProposal,
  McctsImprovementsResponse,
} from "@/lib/types";
import { CardImage } from "@/components/CardImage";
import { useDeckSimulationStore } from "@/stores/deckSimulation";

export function DeckImprovementSection({ slug }: { slug: string }) {
  const router = useRouter();
  const [data, setData] = useState<DeckImprovementsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());
  const [applyError, setApplyError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const externalRefreshKey = useDeckSimulationStore(
    (s) => s.improvementsRefreshKey,
  );

  // MCTS 補強分析 (U2)
  const [mctsRunning, setMctsRunning] = useState(false);
  const [mctsData, setMctsData] = useState<McctsImprovementsResponse | null>(null);
  const [mctsError, setMctsError] = useState<string | null>(null);
  const [opponents, setOpponents] = useState<DeckSummary[]>([]);
  const [mctsOpponent, setMctsOpponent] = useState<string>("");

  useEffect(() => {
    fetchDecks().then((decks) => {
      const filtered = decks.filter((d) => d.slug !== slug);
      setOpponents(filtered);
      if (!mctsOpponent && filtered.length > 0) {
        setMctsOpponent(filtered[0].slug);
      }
    }).catch(() => {});
  }, [slug, mctsOpponent]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDeckImprovements(slug)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // 内部 reloadKey (= apply 後) と 外部 store key (= 探索後) の両方で再取得
  }, [slug, reloadKey, externalRefreshKey]);

  async function handleMctsAnalyze() {
    if (!mctsOpponent) return;
    setMctsRunning(true);
    setMctsError(null);
    setMctsData(null);
    try {
      const r = await runMctsImprovements(slug, {
        opponent_slug: mctsOpponent,
        seed: 42,
        n_simulations: 10,
      });
      setMctsData(r);
    } catch (e) {
      setMctsError(String(e));
    } finally {
      setMctsRunning(false);
    }
  }

  async function handleApply(proposal: ImprovementProposal) {
    if (!confirm(
      `提案を適用しますか?\n\n` +
        proposal.changes
          .map((c) => `${c.name} ${c.delta > 0 ? "+" : ""}${c.delta}`)
          .join("\n") +
        `\n\n(デッキは上書きされます)`,
    )) {
      return;
    }
    setApplying(proposal.proposal_id);
    setApplyError(null);
    try {
      await applyDeckImprovement(slug, proposal.changes);
      setAppliedIds((prev) => new Set(prev).add(proposal.proposal_id));
      // 改善提案を再取得 (= 適用後のデッキ状態で再評価)
      setReloadKey((k) => k + 1);
      // ページ全体 (= /decks/[slug] の Server Component) を refresh
      // → 下部のメインデッキ grid + ヘッダー枚数 等が更新後の内容を表示
      router.refresh();
    } catch (e) {
      setApplyError(String(e));
    } finally {
      setApplying(null);
    }
  }

  if (loading) {
    return <div className="text-sm text-zinc-500">改善提案を計算中…</div>;
  }
  if (error) {
    return (
      <div className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
        改善提案の取得失敗: {error}
      </div>
    );
  }
  if (!data) return null;

  // 提案を統合: log ベース (data.proposals) + MCTS ベース (mctsData?.proposals)
  const combinedProposals: Array<ImprovementProposal & { source: "log" | "mcts" }> = [
    ...data.proposals.map((p) => ({ ...p, source: "log" as const })),
    ...(mctsData?.proposals.map((p) => ({ ...p, source: "mcts" as const })) ?? []),
  ];

  if (data.n_matches === 0 && !mctsData) {
    return (
      <div className="space-y-3">
        <div className="rounded bg-zinc-50 p-3 text-sm text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          対戦履歴がまだありません。 上の「対戦」 セクションから N 試合走らせると改善提案が表示されます。
        </div>
        {/* MCTS 補強だけは履歴無くても利用可能 */}
        <McctsAnalyzePanel
          opponents={opponents}
          mctsOpponent={mctsOpponent}
          setMctsOpponent={setMctsOpponent}
          running={mctsRunning}
          onRun={handleMctsAnalyze}
          error={mctsError}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-xs text-zinc-500">
        過去 {data.n_matches} 試合 / デッキ勝率 {(data.deck_winrate_baseline * 100).toFixed(1)}% を基準に、
        弱いカードの差替え + 枚数調整を提案 (= 上位 {data.proposals.length} 件)
      </div>

      <McctsAnalyzePanel
        opponents={opponents}
        mctsOpponent={mctsOpponent}
        setMctsOpponent={setMctsOpponent}
        running={mctsRunning}
        onRun={handleMctsAnalyze}
        error={mctsError}
        mctsData={mctsData}
      />

      {applyError && (
        <div className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          適用失敗: {applyError}
        </div>
      )}

      {combinedProposals.length === 0 ? (
        <div className="rounded bg-zinc-50 p-3 text-sm text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          改善提案無し (= 全カードがデッキ平均並み or データ不足)
        </div>
      ) : (
        <ul className="space-y-2">
          {combinedProposals.map((p) => {
            const applied = appliedIds.has(p.proposal_id);
            return (
              <li
                key={p.proposal_id}
                className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${proposalTypeClass(p.proposal_type)}`}
                      >
                        {proposalTypeLabel(p.proposal_type)}
                      </span>
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-bold ${impactClass(p.impact_estimate)}`}
                        title="期待インパクト (= 0..100)"
                      >
                        impact {p.impact_estimate}
                      </span>
                      {p.source === "mcts" && (
                        <span className="rounded bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                          🧠 MCTS 根拠
                        </span>
                      )}
                    </div>
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                      {p.changes.map((c, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          <div className="h-12 w-9 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
                            <CardImage
                              cardId={c.card_id}
                              alt={c.name}
                              className="h-full w-full object-cover"
                            />
                          </div>
                          <div>
                            <div className="text-xs">{c.name}</div>
                            <div
                              className={`text-xs font-bold ${
                                c.delta > 0 ? "text-green-600" : "text-red-600"
                              }`}
                            >
                              {c.delta > 0 ? "+" : ""}
                              {c.delta} 枚
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="text-xs text-zinc-600 dark:text-zinc-400">
                      {p.reason}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleApply(p)}
                    disabled={applying != null || applied}
                    className={`shrink-0 rounded px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${
                      applied
                        ? "bg-green-600"
                        : "bg-blue-600 hover:bg-blue-500"
                    }`}
                  >
                    {applied
                      ? "✓ 適用済"
                      : applying === p.proposal_id
                        ? "適用中…"
                        : "提案を反映"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function McctsAnalyzePanel({
  opponents,
  mctsOpponent,
  setMctsOpponent,
  running,
  onRun,
  error,
  mctsData,
}: {
  opponents: DeckSummary[];
  mctsOpponent: string;
  setMctsOpponent: (s: string) => void;
  running: boolean;
  onRun: () => void;
  error: string | null;
  mctsData?: McctsImprovementsResponse | null;
}) {
  return (
    <div className="rounded-lg border border-purple-200 bg-purple-50/30 p-3 dark:border-purple-900 dark:bg-purple-950/20">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">🧠 MCTS で補強分析</div>
          <div className="mt-0.5 text-xs text-zinc-500">
            1 試合 MCTS を走らせ、 「Greedy が使うが MCTS は使わないカード」 を提案
            (= 本当に弱い可能性)
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={mctsOpponent}
          onChange={(e) => setMctsOpponent(e.target.value)}
          className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-xs dark:border-zinc-700"
        >
          {opponents.map((o) => (
            <option key={o.slug} value={o.slug}>
              vs {o.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onRun}
          disabled={running || !mctsOpponent}
          className="rounded bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-50"
        >
          {running ? "MCTS 解析中… (30〜90秒)" : "🧠 MCTS で補強分析"}
        </button>
        {mctsData && (
          <span className="text-[10px] text-zinc-500">
            {mctsData.n_mcts_turns} action 解析、 {mctsData.proposals.length} 提案追加
          </span>
        )}
      </div>
      {error && (
        <div className="mt-2 rounded bg-red-50 p-1.5 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}

function proposalTypeLabel(type: string): string {
  switch (type) {
    case "swap":
      return "差替え";
    case "count_decrease":
      return "枚数減";
    case "count_increase":
      return "枚数増";
    default:
      return type;
  }
}

function proposalTypeClass(type: string): string {
  switch (type) {
    case "swap":
      return "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300";
    case "count_decrease":
      return "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300";
    case "count_increase":
      return "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300";
    default:
      return "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  }
}

function impactClass(impact: number): string {
  if (impact >= 80) return "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300";
  if (impact >= 50) return "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}
