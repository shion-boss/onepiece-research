"use client";

import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DeckAnalysis } from "@/lib/types";
import { MatchupHistoryChart } from "./MatchupHistoryChart";

const COLOR_HEX: Record<string, string> = {
  赤: "#dc2626",
  青: "#2563eb",
  緑: "#16a34a",
  紫: "#9333ea",
  黒: "#262626",
  黄: "#facc15",
};

const NEUTRAL = "#6b7280";

export function DeckAnalyzeCharts({ data }: { data: DeckAnalysis }) {
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <Panel title="色配分">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data.color_dist}
              dataKey="count"
              nameKey="label"
              outerRadius={80}
              label={(p) => `${p.name} ${p.value}`}
            >
              {data.color_dist.map((d) => (
                <Cell key={d.label} fill={COLOR_HEX[d.label] ?? NEUTRAL} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="コストカーブ">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data.cost_curve}>
            <XAxis dataKey="label" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="count" fill="#475569" />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="特徴 Top10">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart
            data={data.feature_top}
            layout="vertical"
            margin={{ left: 60 }}
          >
            <XAxis type="number" allowDecimals={false} />
            <YAxis type="category" dataKey="label" width={100} fontSize={12} />
            <Tooltip />
            <Bar dataKey="count" fill="#0ea5e9" />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="カウンター値分布">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data.counter_dist}>
            <XAxis dataKey="label" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Legend />
            <Bar dataKey="count" name="枚数" fill="#f97316" />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="平均値" className="sm:col-span-2">
        <dl className="grid grid-cols-3 gap-4 text-sm">
          <Stat label="平均コスト" value={data.avg_cost.toFixed(2)} />
          <Stat label="平均パワー" value={data.avg_power.toFixed(0)} />
          <Stat
            label="平均カウンター"
            value={data.avg_counter.toFixed(0)}
            sub={`(0/1k/2k 枚 = ${data.counter_dist
              .map((c) => c.count)
              .join("/")})`}
          />
        </dl>
      </Panel>

      {data.activate_main_cards.length > 0 && (
        <Panel title="起動メイン効果を持つカード" className="sm:col-span-2">
          <ul className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            {data.activate_main_cards.map((c) => (
              <li
                key={c.card_id}
                className="rounded border border-zinc-200 px-2 py-1 dark:border-zinc-800"
              >
                <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">
                  {c.card_id}
                </span>{" "}
                {c.name}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title="対戦相手別の勝率推移" className="sm:col-span-2">
        <MatchupHistoryChart deckSlug={data.slug} />
      </Panel>
    </div>
  );
}

function Panel({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`space-y-2 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800 ${className ?? ""}`}
    >
      <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className="font-mono text-lg">
        {value}
        {sub && (
          <span className="ml-1 text-xs text-zinc-500 dark:text-zinc-400">
            {sub}
          </span>
        )}
      </dd>
    </div>
  );
}
