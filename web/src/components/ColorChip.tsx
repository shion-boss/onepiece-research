const COLOR_CLASS: Record<string, string> = {
  赤: "bg-red-500 text-white",
  青: "bg-blue-500 text-white",
  緑: "bg-green-600 text-white",
  紫: "bg-purple-500 text-white",
  黒: "bg-zinc-800 text-white",
  黄: "bg-yellow-400 text-black",
};

export function ColorChip({ color }: { color: string }) {
  const cls = COLOR_CLASS[color] ?? "bg-zinc-300 text-black";
  return (
    <span
      className={`inline-flex h-5 min-w-5 items-center justify-center rounded px-1.5 text-xs font-medium ${cls}`}
    >
      {color}
    </span>
  );
}
