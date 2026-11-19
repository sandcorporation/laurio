"use client";

// 판정 도장(#963) — 살짝 기운 테두리. 통과는 success, 완벽은 advanced 색.
// `scope` 를 주면 그 도장을 처음 렌더할 때 한 번 찍히는 움직임이 붙는다(없으면 정지).
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { consumeFirstView, STAMP_LABEL, type StampKind } from "@/lib/design/stamp";

const COLOR: Record<StampKind, string> = {
  passed: "border-success text-success",
  perfect: "border-advanced text-advanced",
};

export function Stamp({
  kind,
  scope,
  size = "md",
  children,
}: {
  kind: StampKind;
  scope?: string;
  size?: "md" | "sm";
  /** 라벨 덮어쓰기(예: 「통과 · 권장 기한 뒤」). 기본은 도장 이름. */
  children?: ReactNode;
}) {
  const [press, setPress] = useState(false);
  useEffect(() => {
    if (scope && consumeFirstView(scope, kind, window.localStorage)) setPress(true);
  }, [scope, kind]);
  const dims = size === "sm" ? "px-1.5 py-px text-[10.5px]" : "px-2.5 py-0.5 text-[12px]";
  return (
    <span
      data-stamp={kind}
      style={{ "--stamp-tilt": size === "sm" ? "-3deg" : "-4deg", transform: "rotate(var(--stamp-tilt))" } as CSSProperties}
      className={`inline-block shrink-0 border-2 font-semibold tracking-[0.04em] whitespace-nowrap ${dims} ${COLOR[kind]} ${press ? "stamp-press" : ""}`}
    >
      {children ?? STAMP_LABEL[kind]}
    </span>
  );
}
