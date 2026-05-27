import type { HTMLAttributes, ReactNode } from "react";

/**
 * 全 page で 統一 する panel / card。
 * surface-panel utility (= globals.css) を 適用。
 */
export function Card({
  children,
  className = "",
  ...rest
}: {
  children: ReactNode;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`surface-panel p-4 ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * Card 内 section 区切り (= title + content)。
 */
export function CardSection({
  title,
  children,
  className = "",
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`space-y-2 ${className}`}>
      {title && (
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}
