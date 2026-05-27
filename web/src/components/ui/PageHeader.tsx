import type { ReactNode } from "react";

/**
 * 全 page で 共通 の page header。
 * title + 任意 description + 右側 actions (= button / link) + meta 行 (= data 鮮度 等)。
 *
 * 視覚的特徴 (= ワンピース カード研究所 統一 design):
 * - title 左 に brand 縦バー (= 海賊旗 accent)
 * - bottom border で content と 区切り
 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="border-b border-zinc-200 pb-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="mt-1 h-7 w-1 rounded-full"
            style={{
              background:
                "linear-gradient(180deg, var(--brand) 0%, var(--accent) 100%)",
            }}
            aria-hidden
          />
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              {title}
            </h1>
            {description && (
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                {description}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {meta && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
          {meta}
        </div>
      )}
    </header>
  );
}
