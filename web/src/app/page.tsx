import Link from "next/link";
import { PageShell } from "@/components/ui/PageShell";

// VSCode の "Welcome" タブ風ランディング。 公開プロダクトの 3 機能 + カード/Q&A に絞る
// (研究/メタ分析/コンボ探索 は非表示、 PUBLIC_MODE でナビからも撤去済み)。
const START: { href: string; label: string; desc: string; primary?: boolean }[] = [
  { href: "/play", label: "対戦する", desc: "自分のデッキで AI と対戦する", primary: true },
  { href: "/decks/new", label: "デッキを作る", desc: "推しキャラでデッキを構築（非公開で保存）" },
  { href: "/decks", label: "マイデッキ", desc: "保存したデッキの一覧・分析" },
  { href: "/cards", label: "カードを見る", desc: "全カードの検索・フィルタ" },
  { href: "/faq", label: "ルール Q&A", desc: "公式ルール・カードの裁定を検索" },
];

export default function Home() {
  return (
    <PageShell>
      <div className="mx-auto max-w-3xl">
        <div className="flex items-center gap-3">
          <span
            className="flex h-11 w-11 items-center justify-center rounded text-base font-bold text-white"
            style={{ background: "var(--brand)" }}
            aria-hidden
          >
            OP
          </span>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              OPTCG 対戦コンパニオン
            </h1>
            <p className="font-mono text-xs text-[color:var(--text-muted)]">
              One Piece Card Game · 公式準拠エンジン + AI 対戦
            </p>
          </div>
        </div>

        <p className="mt-5 text-sm text-[color:var(--text-default)]">
          推しキャラのデッキを組んで、環境デッキの AI と対戦。自分の一手がどこまで通用するかを試そう。
        </p>

        <div className="mt-8 text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">
          スタート
        </div>
        <div
          className="mt-2 overflow-hidden rounded-[var(--radius)] border"
          style={{ borderColor: "var(--border-1)" }}
        >
          {START.map((s) => (
            <Link
              key={s.href}
              href={s.href}
              className="group flex items-center justify-between gap-4 border-t px-4 py-3 transition-colors first:border-t-0 hover:bg-[var(--list-hover)]"
              style={{ borderColor: "var(--border-1)" }}
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span
                  className="text-sm font-medium"
                  style={{ color: s.primary ? "var(--brand-strong)" : "var(--text-strong)" }}
                >
                  {s.label}
                </span>
                <span className="text-xs text-[color:var(--text-muted)]">{s.desc}</span>
              </div>
              <span
                className="text-[color:var(--text-muted)] transition-transform group-hover:translate-x-0.5"
                aria-hidden
              >
                →
              </span>
            </Link>
          ))}
        </div>

        <p className="mt-6 font-mono text-[11px] text-[color:var(--text-muted)]">
          公式準拠 100% · 全 4,675 カード登録済み
        </p>
      </div>
    </PageShell>
  );
}
