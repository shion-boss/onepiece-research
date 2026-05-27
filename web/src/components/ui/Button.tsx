import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

/**
 * 全 page で 統一 する button。
 * - primary: brand 色 (= ワンピース赤)、 主要 action
 * - secondary: zinc 系、 中立 action
 * - ghost: 枠線 のみ、 軽い action
 * - danger: 削除 等 危険 action
 */
export function Button({
  variant = "secondary",
  size = "md",
  children,
  className = "",
  ...rest
}: {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const sizes: Record<Size, string> = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
  };
  const variants: Record<Variant, string> = {
    primary:
      "text-white shadow-sm bg-[color:var(--brand)] hover:bg-[color:var(--brand-strong)]",
    secondary:
      "bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700",
    ghost:
      "border border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800",
    danger:
      "bg-red-600 text-white hover:bg-red-700 dark:bg-red-700 dark:hover:bg-red-600",
  };
  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
