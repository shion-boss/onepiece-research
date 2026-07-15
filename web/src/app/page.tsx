import Link from "next/link";

// タブを何も開いていないときの「空状態 / ようこそ」画面 (= VSCode の Welcome 相当)。
// ルート "/" はタブ化されない (WorkspaceShell) ので、 全タブを閉じるとここに戻る。
// 公開プロダクトの機能 (対戦 / デッキ / カード / Q&A) への入口に絞る。
const START: { href: string; label: string; desc: string; primary?: boolean }[] = [
  { href: "/play", label: "対戦する", desc: "自分のデッキで AI と対戦する", primary: true },
  { href: "/decks/new", label: "デッキを作る", desc: "推しキャラでデッキを構築して保存" },
  { href: "/decks", label: "マイデッキ", desc: "保存したデッキの一覧・分析" },
  { href: "/cards", label: "カードを見る", desc: "全カードの検索・フィルタ" },
  { href: "/faq", label: "ルール Q&A", desc: "公式ルール・カードの裁定を検索" },
];

export default function Home() {
  return (
    <div className="flex min-h-full w-full items-center justify-center px-6 py-12">
      <div className="w-full max-w-2xl">
        <div className="flex items-center gap-3">
          <span
            className="flex h-12 w-12 items-center justify-center rounded text-lg font-bold text-white"
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

        <p className="mt-6 text-center font-mono text-[11px] text-[color:var(--text-muted)]">
          左のメニューから機能を選ぶと、開いた画面がタブになります
        </p>
      </div>
    </div>
  );
}
