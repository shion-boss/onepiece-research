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
    <header className="border-b pb-4" style={{ borderColor: "var(--border-1)" }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className="mt-1 h-7 w-1 rounded-sm"
            style={{ background: "var(--brand)" }}
            aria-hidden
          />
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              {title}
            </h1>
            {description && (
              <p className="text-sm text-[color:var(--text-muted)]">
                {description}
              </p>
            )}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {meta && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[color:var(--text-muted)]">
          {meta}
        </div>
      )}
    </header>
  );
}
