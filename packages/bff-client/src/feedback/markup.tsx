"use client";

// 캡처 미리보기 위의 가리기·표시 편집기 (#1241). 가리기는 불투명 칠(되돌릴 수 없게 그림에 구워진다),
// 표시는 펜. 획은 원본 그림 좌표로 쌓아 두고 매번 다시 그린다 — 되돌리기·지우기가 그 목록만 고친다.

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

export type MarkupTool = "redact" | "pen";

type Stroke =
  | { tool: "redact"; x: number; y: number; w: number; h: number }
  | { tool: "pen"; points: Array<[number, number]> };

export interface MarkupHandle {
  /** 칠한 결과를 합친 캔버스. */
  compose(): HTMLCanvasElement;
}

const REDACT_FILL = "#000000";
const PEN_STROKE = "#e11d48";

function paint(ctx: CanvasRenderingContext2D, strokes: Stroke[], scale: number) {
  for (const stroke of strokes) {
    if (stroke.tool === "redact") {
      ctx.fillStyle = REDACT_FILL;
      ctx.fillRect(stroke.x, stroke.y, stroke.w, stroke.h);
    } else if (stroke.points.length > 0) {
      ctx.strokeStyle = PEN_STROKE;
      ctx.lineWidth = Math.max(3, 4 * scale);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      stroke.points.forEach(([x, y], index) => (index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
      if (stroke.points.length === 1) ctx.lineTo(stroke.points[0][0] + 0.1, stroke.points[0][1]);
      ctx.stroke();
    }
  }
}

export const MarkupEditor = forwardRef<MarkupHandle, { source: HTMLCanvasElement }>(function MarkupEditor(
  { source },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tool, setTool] = useState<MarkupTool>("redact");
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [draft, setDraft] = useState<Stroke | null>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0);
    paint(ctx, draft ? [...strokes, draft] : strokes, canvas.width / 1000);
  }, [source, strokes, draft]);

  useEffect(render, [render]);

  useImperativeHandle(ref, () => ({
    compose() {
      const out = document.createElement("canvas");
      out.width = source.width;
      out.height = source.height;
      const ctx = out.getContext("2d");
      if (ctx) {
        ctx.drawImage(source, 0, 0);
        paint(ctx, strokes, source.width / 1000);
      }
      return out;
    },
  }));

  function point(event: React.PointerEvent<HTMLCanvasElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      ((event.clientX - rect.left) / rect.width) * source.width,
      ((event.clientY - rect.top) / rect.height) * source.height,
    ];
  }

  const origin = useRef<[number, number]>([0, 0]);

  function onDown(event: React.PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    const p = point(event);
    origin.current = p;
    setDraft(tool === "pen" ? { tool, points: [p] } : { tool, x: p[0], y: p[1], w: 0, h: 0 });
  }

  function onMove(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!draft) return;
    const p = point(event);
    if (draft.tool === "pen") setDraft({ tool: "pen", points: [...draft.points, p] });
    else {
      const [ox, oy] = origin.current;
      setDraft({ tool: "redact", x: Math.min(ox, p[0]), y: Math.min(oy, p[1]), w: Math.abs(p[0] - ox), h: Math.abs(p[1] - oy) });
    }
  }

  function onUp() {
    if (draft && (draft.tool === "pen" || (draft.w > 2 && draft.h > 2))) setStrokes((list) => [...list, draft]);
    setDraft(null);
  }

  const toolClass = (active: boolean) =>
    `border px-3 py-1.5 text-[13px] ${active ? "border-ink bg-ink text-paper" : "border-rule text-ink hover:border-ink"}`;
  const plainClass = "border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink disabled:opacity-40";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2" role="toolbar" aria-label="그림 도구">
        <button type="button" data-testid="feedback-tool-redact" aria-pressed={tool === "redact"} className={toolClass(tool === "redact")} onClick={() => setTool("redact")}>
          가리기
        </button>
        <button type="button" data-testid="feedback-tool-pen" aria-pressed={tool === "pen"} className={toolClass(tool === "pen")} onClick={() => setTool("pen")}>
          표시
        </button>
        <button type="button" data-testid="feedback-undo" className={plainClass} disabled={strokes.length === 0} onClick={() => setStrokes((list) => list.slice(0, -1))}>
          되돌리기
        </button>
        <button type="button" data-testid="feedback-clear" className={plainClass} disabled={strokes.length === 0} onClick={() => setStrokes([])}>
          지우기
        </button>
      </div>
      <canvas
        ref={canvasRef}
        data-testid="feedback-canvas"
        width={source.width}
        height={source.height}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        className="cursor-crosshair touch-none border border-rule bg-paper"
        style={{
          aspectRatio: `${source.width} / ${source.height}`,
          width: `min(100%, calc(40vh * ${source.width / source.height}))`,
        }}
      />
    </div>
  );
});
