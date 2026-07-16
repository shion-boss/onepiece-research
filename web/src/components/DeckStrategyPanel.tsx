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
    <section className="rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4">
      <h2 className="mb-1 text-lg font-semibold text-[color:var(--text-strong)]">戦略概要（デッキ構成から）</h2>
      <p className="mb-3 text-[11px] text-[color:var(--text-muted)]">
        カード構成から即時に導いた骨格（対戦シミュレーション不要）。
      </p>

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
      <p className="mb-4 text-sm text-[color:var(--text-default)]">
        {strategy.strategy_summary}
      </p>

      {/* 2 段組 */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* 強み */}
        <div className="rounded-[var(--radius)] border border-[color:var(--accent)]/40 bg-[color:var(--accent)]/10 p-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--accent)]">
            強み
          </h3>
          {strategy.strengths.length === 0 ? (
            <p className="text-xs text-[color:var(--text-muted)]">特になし</p>
          ) : (
            <ul className="space-y-1 text-xs text-[color:var(--text-default)]">
              {strategy.strengths.map((s, i) => (
                <li key={i}>+ {s}</li>
              ))}
            </ul>
          )}
        </div>

        {/* 弱点 */}
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--danger)]">
            弱点
          </h3>
          {strategy.weaknesses.length === 0 ? (
            <p className="text-xs text-[color:var(--text-muted)]">特になし</p>
          ) : (
            <ul className="space-y-1 text-xs text-[color:var(--text-default)]">
              {strategy.weaknesses.map((w, i) => (
                <li key={i}>− {w}</li>
              ))}
            </ul>
          )}
        </div>

        {/* マリガン */}
        <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--text-strong)]">マリガン基準</h3>
          <div className="mb-2 text-xs">
            <div className="font-medium text-[color:var(--accent)]">
              キープ:
            </div>
            <ul className="ml-4 list-disc text-[color:var(--text-default)]">
              {strategy.mulligan_keep_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          <div className="text-xs">
            <div className="font-medium text-[color:var(--danger)]">
              戻す:
            </div>
            <ul className="ml-4 list-disc text-[color:var(--text-default)]">
              {strategy.mulligan_throw_criteria.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
          {strategy.mulligan_keep_card_ids.length > 0 && (
            <div className="mt-2 text-xs">
              <div className="font-medium text-[color:var(--text-strong)]">キープしたい主力:</div>
              <div className="font-mono text-[color:var(--text-muted)]">
                {strategy.mulligan_keep_card_ids.join(", ")}
              </div>
            </div>
          )}
        </div>

        {/* 理想ムーブ */}
        <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--text-strong)]">理想ムーブ</h3>
          <ul className="space-y-1 text-xs">
            {strategy.ideal_moves.map((m, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono font-bold text-[color:var(--brand-strong)]">
                  T{m.turn}
                </span>
                <div className="flex-1">
                  <div className="text-[color:var(--text-default)]">
                    {m.description}
                  </div>
                  {m.candidate_cards.length > 0 && (
                    <div className="font-mono text-[10px] text-[color:var(--text-muted)]">
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
      <div className="mt-4 rounded-[var(--radius)] border border-[color:var(--border-1)] p-3">
        <h3 className="mb-2 text-sm font-semibold text-[color:var(--text-strong)]">キーカード (役割別)</h3>
        <div className="grid gap-1 text-xs md:grid-cols-2">
          {strategy.key_cards.map((k) => (
            <div
              key={k.card_id}
              className="flex items-center gap-2 rounded-[var(--radius-sm)] bg-[color:var(--surface-2)] p-1.5"
            >
              <Badge color={roleColor(k.role)} label={k.role} />
              <span className="flex-1 truncate font-medium text-[color:var(--text-default)]">
                {k.name}{" "}
                <span className="font-normal text-[color:var(--text-muted)]">
                  ({k.card_id} ×{k.count})
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* AI ヒント */}
      {strategy.ai_hints.length > 0 && (
        <div className="mt-4 rounded-[var(--radius)] border border-[color:var(--warning)]/40 bg-[color:var(--warning)]/10 p-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--warning)]">
            AI 戦術ヒント
          </h3>
          <ul className="space-y-1 text-xs text-[color:var(--text-default)]">
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
    violet: "bg-[color:var(--brand-soft)] text-[color:var(--brand-strong)]",
    sky: "bg-[color:var(--brand-soft)] text-[color:var(--brand-strong)]",
    emerald: "bg-[color:var(--accent)]/15 text-[color:var(--accent)]",
    rose: "bg-[color:var(--danger)]/15 text-[color:var(--danger)]",
    zinc: "bg-[color:var(--surface-3)] text-[color:var(--text-default)]",
    amber: "bg-[color:var(--warning)]/15 text-[color:var(--warning)]",
    lime: "bg-[color:var(--accent)]/15 text-[color:var(--accent)]",
  };
  return (
    <span className={`rounded-[var(--radius-sm)] px-2 py-0.5 text-[10px] font-medium ${cls[color]}`}>
      {label}
    </span>
  );
}
