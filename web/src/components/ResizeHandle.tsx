"use client";

// 列の間に置くドラッグリサイズ用の縦バー。 onMouseDown は useResizable から。
export function ResizeHandle({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) {
  return (
    <div
      onMouseDown={onMouseDown}
      title="ドラッグで幅を変更"
      className="w-1 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-[color:var(--brand)]"
      style={{ borderColor: "var(--border-1)" }}
    />
  );
}
