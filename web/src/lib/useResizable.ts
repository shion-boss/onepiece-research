"use client";

import { useCallback, useRef, useState } from "react";

// 横幅をドラッグでリサイズするフック。 handle の onMouseDown を要素に付ける。
// invert=true はハンドルが要素の左側にある場合 (= 右パネル: 右ドラッグで縮む)。
export function useResizable(initial: number, min: number, max: number, invert = false) {
  const [width, setWidth] = useState(initial);
  const widthRef = useRef(initial);
  widthRef.current = width;

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = widthRef.current;
      const move = (ev: MouseEvent) => {
        const dx = (ev.clientX - startX) * (invert ? -1 : 1);
        setWidth(Math.max(min, Math.min(max, startW + dx)));
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [min, max, invert],
  );

  return { width, onMouseDown };
}
