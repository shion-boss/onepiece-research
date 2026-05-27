import Link from "next/link";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";

const FEATURES = [
  {
    href: "/cards",
    label: "カード",
    description: "全 4,518 枚 の 検索・ フィルタ・ 詳細表示",
  },
  {
    href: "/decks",
    label: "デッキ",
    description: "メタデッキ 16 件 の 管理・ 静的分析・ AI vs AI 対戦",
  },
  {
    href: "/play",
    label: "対戦",
    description: "人間 が AI と 対戦 (= プレイ感確認 / 学習データ収集)",
  },
  {
    href: "/research",
    label: "研究",
    description: "対策デッキ 探索 (= クイック / 進化的 アルゴリズム)",
  },
  {
    href: "/meta",
    label: "メタ分析",
    description: "デッキ間 N×N 勝率行列 + AI vs AI ライブ観戦",
  },
  {
    href: "/faq",
    label: "Q&A",
    description: "公式ルール Q&A 横断検索 (= 2,500+ 件)",
  },
] as const;

export default function Home() {
  return (
    <PageShell>
      <PageHeader
        title="ワンピースカード研究所"
        description="公式準拠 100% の OPTCG エンジン 上で、 デッキ研究 と AI 対戦 を 集合知 で 進める 研究プラットフォーム"
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ href, label, description }) => (
          <Link
            key={href}
            href={href}
            className="surface-panel group flex flex-col gap-2 p-5 transition-colors hover:border-[color:var(--brand)] hover:bg-[color:var(--brand-soft)] dark:hover:bg-zinc-900"
          >
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-zinc-900 dark:text-zinc-100">
                {label}
              </h2>
              <span
                className="text-zinc-400 transition-all group-hover:translate-x-0.5 group-hover:text-[color:var(--brand)] dark:text-zinc-500"
                aria-hidden
              >
                →
              </span>
            </div>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              {description}
            </p>
          </Link>
        ))}
      </div>
    </PageShell>
  );
}
