import type { DeckStrategy } from "@/lib/types";

/**
 * デッキ静的分析の表示パネル。
 * /decks/[slug]/analyze ページで使用。
 *
 * 内容:
 *  - サマリ (アーキタイプ / 速度 / 防御 / 安定性)
 *  - 戦略概要
 *  - マリガン基準
 *  - 理想ムーブ (T1〜T6)
 *  - 強み / 弱点
 *  - キーカード
 *  - AI 戦術ヒント
 */
export function DeckStrategyPanel({ strategy }: { strategy: DeckStrategy }) {
  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <h2 className="mb-3 text-lg font-semibold">戦略分析</h2>

      {/* サマリバッジ */}
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <Badge color="violet" label={`アーキ: ${strategy.archetype}`} />
        <Badge color="sky" label={`速度: ${strategy.speed}`} />
        <Badge
          color={
            strategy.defense === "硬い"
              ? "emerald"
              : strategy.defense === "標準"
                ? "zinc"
                : "rose"
          }
          label={`防御: ${strategy.defense}`}
        />
        <Badge
          color={
            strategy.consistency === "高い"
              ? "emerald"
              : strategy.consistency === "標準"
                ? "zinc"
                : "amber"
          }
          label={`安定性: ${strategy.consistency}`}
        />
      </div>
      <p className="mb-4 text-sm text-zinc-700 dark:text-zinc-300">
        {strategy.strategy_summary}
      </p>

      {/* 2 段組 */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* 強み */}
        <div className="rounded border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
          <h3 className="mb-2 text-sm font-semibold text-emerald-800 dark:text-emerald-200">
            強み
          </h3>
          {strategy.strengths.length === 0 ? (
            <p className="text-xs text-zinc-500">特になし</p>
          ) : (
            <ul className="space-y-1 text-xs text-zinc-700 dark:text-zinc-300">
              {strategy.strengths.map((s, i) => (
                <li key={i}>+ {s}</li>
              ))}
            </ul>
          )}
        </div>

        {/* 弱点 */}
        <div className="rounded border border-rose-200 bg-rose-50 p-3 dark:border-rose-900 dark:bg-rose-950/30">
          <h3 className="mb-2 text-sm font-semibold text-rose-800 dark:text-rose-200">
            弱点
          </h3>
          {strategy.weaknesses.length === 0 ? (
            <p className="text-xs text-zinc-500">特になし</p>
          ) : (
            <ul className="space-y-1 text-xs text-zinc-700 dark:text-zinc-300">
              {strategy.weaknesses.map((w, i) => (
                <li key={i}>− {w}</li>
              ))}
            </ul>
          )}
        </div>

        {/* マリガン */}
        <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
          <h3 className="mb-2 text-sm font-semibold">マリガン基準</h3>
          <div className="mb-2 text-xs">
            <div className="font-medium text-emerald-700 dark:text-emerald-400">
              キープ:
            </div>
            <ul className="ml-4 list-disc text-zinc-700 dark:text-zinc-300">
              {strategy.mulligan_keep_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          <div className="text-xs">
            <div className="font-medium text-rose-700 dark:text-rose-400">
              戻す:
            </div>
            <ul className="ml-4 list-disc text-zinc-700 dark:text-zinc-300">
              {strategy.mulligan_throw_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          {strategy.mulligan_keep_card_ids.length > 0 && (
            <div className="mt-2 text-xs">
              <div className="font-medium">キープしたい主力:</div>
              <div className="font-mono text-zinc-600 dark:text-zinc-400">
                {strategy.mulligan_keep_card_ids.join(", ")}
              </div>
            </div>
          )}
        </div>

        {/* 理想ムーブ */}
        <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
          <h3 className="mb-2 text-sm font-semibold">理想ムーブ</h3>
          <ul className="space-y-1 text-xs">
            {strategy.ideal_moves.map((m, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono font-bold text-violet-700 dark:text-violet-400">
                  T{m.turn}
                </span>
                <div className="flex-1">
                  <div className="text-zinc-700 dark:text-zinc-300">
                    {m.description}
                  </div>
                  {m.candidate_cards.length > 0 && (
                    <div className="font-mono text-[10px] text-zinc-500">
                      候補: {m.candidate_cards.join(", ")}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* キーカード */}
      <div className="mt-4 rounded border border-zinc-200 p-3 dark:border-zinc-800">
        <h3 className="mb-2 text-sm font-semibold">キーカード (役割別)</h3>
        <div className="grid gap-1 text-xs md:grid-cols-2">
          {strategy.key_cards.map((k) => (
            <div
              key={k.card_id}
              className="flex items-center gap-2 rounded bg-zinc-50 p-1.5 dark:bg-zinc-900"
            >
              <Badge color={roleColor(k.role)} label={k.role} />
              <span className="flex-1 truncate font-medium">
                {k.name}{" "}
                <span className="font-normal text-zinc-500">
                  ({k.card_id} ×{k.count})
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* AI ヒント */}
      {strategy.ai_hints.length > 0 && (
        <div className="mt-4 rounded border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/30">
          <h3 className="mb-2 text-sm font-semibold text-amber-800 dark:text-amber-200">
            AI 戦術ヒント
          </h3>
          <ul className="space-y-1 text-xs text-zinc-700 dark:text-zinc-300">
            {strategy.ai_hints.map((h, i) => (
              <li key={i}>★ {h}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function roleColor(role: string): BadgeColor {
  if (role === "finisher") return "rose";
  if (role === "removal") return "violet";
  if (role === "search" || role === "draw") return "sky";
  if (role === "ramp") return "amber";
  if (role === "synergy") return "emerald";
  if (role === "blocker") return "zinc";
  if (role === "counter") return "lime";
  return "zinc";
}

type BadgeColor =
  | "violet"
  | "sky"
  | "emerald"
  | "rose"
  | "zinc"
  | "amber"
  | "lime";

function Badge({ color, label }: { color: BadgeColor; label: string }) {
  const cls: Record<BadgeColor, string> = {
    violet: "bg-violet-100 text-violet-900 dark:bg-violet-900 dark:text-violet-100",
    sky: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100",
    emerald: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100",
    rose: "bg-rose-100 text-rose-900 dark:bg-rose-900 dark:text-rose-100",
    zinc: "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100",
    amber: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100",
    lime: "bg-lime-100 text-lime-900 dark:bg-lime-900 dark:text-lime-100",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${cls[color]}`}>
      {label}
    </span>
  );
}
