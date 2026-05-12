"use client";

import { useState } from "react";
import { exploreCounterDecks } from "@/lib/api";
import { useExploreStore } from "@/stores/explore";
import { MetaDeckPicker } from "@/components/explore/MetaDeckPicker";
import { CardPickerModal } from "@/components/explore/CardPickerModal";
import { CounterCandidateCard } from "@/components/explore/CounterCandidateCard";
import { CounterCandidateDetail } from "@/components/explore/CounterCandidateDetail";

export default function ExplorePage() {
  const {
    target,
    leaderFilter,
    mustInclude,
    candidates,
    selectedRank,
    loading,
    error,
    setTarget,
    addLeaderFilter,
    removeLeaderFilter,
    addMustInclude,
    removeMustInclude,
    setCandidates,
    setSelectedRank,
    setLoading,
    setError,
  } = useExploreStore();

  const [showLeaderPicker, setShowLeaderPicker] = useState(false);
  const [showCardPicker, setShowCardPicker] = useState(false);
  const [nCandidates, setNCandidates] = useState(20);

  const selectedCandidate =
    selectedRank != null
      ? candidates.find((c) => c.rank === selectedRank) ?? null
      : null;

  async function handleExplore() {
    if (!target) {
      setError("対象デッキを選択してください");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await exploreCounterDecks({
        target_slug: target.slug,
        leader_filter: leaderFilter.length > 0 ? leaderFilter.map((l) => l.card_id) : undefined,
        must_include: mustInclude.length > 0 ? mustInclude.map((c) => c.card_id) : undefined,
        n_candidates: nCandidates,
      });
      setCandidates(res.candidates);
      if (res.candidates.length === 0) {
        setError("候補が生成できませんでした (= リーダー候補が無い、 制約が厳しすぎ)");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-bold">対策デッキ探索</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          メタデッキを選んで、 (オプションで) 使いたいリーダーやキャラを指定すると、
          AI が対策候補デッキを {nCandidates} 件提案します。
        </p>
      </header>

      {/* Step 1: 対象デッキ選択 */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          ① 対象メタデッキ
          {target && (
            <span className="ml-2 text-sm font-normal text-zinc-500">
              選択中: {target.name}
            </span>
          )}
        </h2>
        <MetaDeckPicker selected={target} onSelect={setTarget} />
      </section>

      {/* Step 2: 制約設定 (target 選択後に表示) */}
      {target && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">
            ② 制約設定 <span className="text-sm font-normal text-zinc-500">(任意)</span>
          </h2>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* リーダー指定 */}
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">使いたいリーダー</div>
                  <div className="text-xs text-zinc-500">
                    指定なしなら全リーダーから探索
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowLeaderPicker(true)}
                  className="rounded bg-zinc-100 px-3 py-1 text-sm hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700"
                >
                  選択 ({leaderFilter.length})
                </button>
              </div>
              {leaderFilter.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {leaderFilter.map((l) => (
                    <button
                      key={l.card_id}
                      type="button"
                      onClick={() => removeLeaderFilter(l.card_id)}
                      className="rounded bg-blue-100 px-2 py-0.5 text-xs hover:bg-blue-200 dark:bg-blue-900 dark:hover:bg-blue-800"
                    >
                      {l.name} ×
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* 必須カード指定 */}
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">必ず採用したいキャラ・コンボ</div>
                  <div className="text-xs text-zinc-500">複数選択可</div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowCardPicker(true)}
                  className="rounded bg-zinc-100 px-3 py-1 text-sm hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700"
                >
                  選択 ({mustInclude.length})
                </button>
              </div>
              {mustInclude.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {mustInclude.map((c) => (
                    <button
                      key={c.card_id}
                      type="button"
                      onClick={() => removeMustInclude(c.card_id)}
                      className="rounded bg-blue-100 px-2 py-0.5 text-xs hover:bg-blue-200 dark:bg-blue-900 dark:hover:bg-blue-800"
                    >
                      {c.name} ×
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <label className="text-sm">
              候補数:
              <input
                type="number"
                min={1}
                max={50}
                value={nCandidates}
                onChange={(e) =>
                  setNCandidates(Math.max(1, Math.min(50, parseInt(e.target.value) || 20)))
                }
                className="ml-2 w-16 rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              />
            </label>
          </div>
        </section>
      )}

      {/* Step 3: 探索ボタン */}
      {target && (
        <section>
          <button
            type="button"
            onClick={handleExplore}
            disabled={loading}
            className="rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white shadow hover:bg-blue-500 disabled:opacity-50"
          >
            {loading ? "探索中… (約 1〜10 秒)" : "③ 対策デッキを探索"}
          </button>
          {error && (
            <div className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
              {error}
            </div>
          )}
        </section>
      )}

      {/* Step 4: 結果リスト + 詳細 */}
      {candidates.length > 0 && target && (
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-[420px_1fr]">
          <div>
            <h2 className="mb-3 text-lg font-semibold">
              ④ 候補 ({candidates.length} 件) — クリックで詳細
            </h2>
            <div className="space-y-2">
              {candidates.map((cand) => (
                <CounterCandidateCard
                  key={cand.rank}
                  candidate={cand}
                  selected={selectedRank === cand.rank}
                  onSelect={() => setSelectedRank(cand.rank)}
                />
              ))}
            </div>
          </div>
          <div>
            <h2 className="mb-3 text-lg font-semibold">⑤ 詳細</h2>
            {selectedCandidate ? (
              <CounterCandidateDetail
                candidate={selectedCandidate}
                targetSlug={target.slug}
              />
            ) : (
              <div className="rounded border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
                左側のリストから候補を選択してください
              </div>
            )}
          </div>
        </section>
      )}

      {/* Modals */}
      {showLeaderPicker && (
        <CardPickerModal
          title="使いたいリーダーを選択"
          category="LEADER"
          selected={leaderFilter}
          onAdd={addLeaderFilter}
          onRemove={removeLeaderFilter}
          onClose={() => setShowLeaderPicker(false)}
        />
      )}
      {showCardPicker && (
        <CardPickerModal
          title="必ず採用したいキャラ・コンボを選択"
          selected={mustInclude}
          onAdd={addMustInclude}
          onRemove={removeMustInclude}
          onClose={() => setShowCardPicker(false)}
        />
      )}
    </div>
  );
}
