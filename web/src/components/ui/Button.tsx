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
    "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const sizes: Record<Size, string> = {
    sm: "px-2.5 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
  };
  // VSCode 風: フラット・青 primary・トークン基調。
  const variants: Record<Variant, string> = {
    primary:
      "text-white bg-[color:var(--brand)] hover:bg-[color:var(--brand-strong)]",
    secondary:
      "border border-[color:var(--border-2)] bg-[color:var(--surface-2)] text-[color:var(--text-default)] hover:bg-[color:var(--surface-3)]",
    ghost:
      "border border-[color:var(--border-2)] text-[color:var(--text-default)] hover:bg-[color:var(--surface-2)]",
    danger: "bg-[color:var(--danger)] text-white hover:opacity-90",
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
