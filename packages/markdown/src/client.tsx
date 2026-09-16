"use client";

// 코드블록·인라인 코드에 붙는 **작은 클라이언트 섬**(2026-09-16).
//
// 본문(제목·문단·표·코드)은 서버가 그린다 — 공개 앱의 공모전 상세는 색인 대상이라
// 서버 HTML 에 글자가 있어야 한다(ADR-0015·0017). 그래서 손이 필요한 조각만 여기서
// 클라이언트로 내려간다: 복사 버튼, 파일로 저장 버튼, 눌러서 복사되는 인라인 코드.
//
// 이 파일이 받는 것은 **이미 뽑아 둔 글자**뿐이다(트리를 넘기지 않는다) — 서버에서
// `codeTextOf` 로 뽑은 문자열을 prop 으로 받으므로 직렬화할 수 없는 값이 경계를
// 넘지 않는다.
import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { copyToClipboard } from "./code-copy";

type CopyState = "idle" | "copied" | "failed";

/** 누르면 복사하고 2초 동안 결과를 보인 뒤 원래대로 돌아간다. */
function useCopy(text: string) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  async function copy() {
    const ok = await copyToClipboard(text);
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }
  return { state, copy };
}

const BUTTON =
  "border border-rule bg-surface px-2 py-0.5 text-[11.5px] text-ink/70 hover:text-ink";

/**
 * 코드블록 오른쪽 위에 붙는 버튼들. `fileName` 이 없으면 저장 버튼은 나오지 않는다
 * (언어가 적히지 않은 블록 — 확장자를 지어내지 않는다).
 */
export function CodeBlockActions({ text, fileName }: { text: string; fileName: string | null }) {
  const { state, copy } = useCopy(text);

  function download() {
    if (!fileName) return;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // 다음 순간에 거둔다 — 브라우저가 내려받기를 시작할 틈을 준다.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="absolute top-1.5 right-1.5 flex gap-1">
      {fileName && (
        <button
          type="button"
          onClick={download}
          data-testid="code-block-download"
          title={`${fileName} 으로 저장`}
          className={BUTTON}
        >
          파일로 저장
        </button>
      )}
      <button type="button" onClick={() => void copy()} data-testid="code-block-copy" className={BUTTON}>
        {state === "copied" ? "복사됨" : state === "failed" ? "복사 실패" : "복사"}
      </button>
    </div>
  );
}

/**
 * 설명 안의 이미지. **주소가 죽었을 때 그 자리만 비우기 위해** 클라이언트 섬이다 —
 * `onError` 는 브라우저에서만 일어나는 일이라 서버에서 달 수 없다. 서버 HTML 에는
 * `<img>` 가 그대로 들어가므로(색인·JS 없는 방문자) 성한 이미지는 이 섬이 깨어나기
 * 전에 이미 보인다.
 */
export function RemoteImage(props: ComponentProps<"img">) {
  const [dead, setDead] = useState(false);
  if (dead) return null;
  return (
    // referrerPolicy="no-referrer" — 이 이미지를 불러올 때 어느 페이지에서 왔는지를
    // 이미지가 사는 서버에 붙이지 않는다. 접속한 인터넷 주소까지 숨기지는 못한다.
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    <img
      {...props}
      referrerPolicy="no-referrer"
      className="my-1 max-w-full border border-rule"
      onError={() => setDead(true)}
    />
  );
}

/** 눌러서 복사되는 인라인 코드. 키보드는 Enter·Space 로 누른다. */
export function InlineCode({ text, children }: { text: string; children: ReactNode }) {
  const { state, copy } = useCopy(text);

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      void copy();
    }
  }

  return (
    <span className="relative inline-block">
      <code
        role="button"
        tabIndex={0}
        title="눌러서 복사"
        aria-label={`${text} 복사`}
        onClick={() => void copy()}
        onKeyDown={onKeyDown}
        data-testid="inline-code-copy"
        className="cursor-pointer border border-rule bg-paper px-1 py-0.5 font-mono text-[0.9em] hover:border-ink/40"
      >
        {children}
      </code>
      {state !== "idle" && (
        <span
          role="status"
          className="pointer-events-none absolute bottom-full left-0 mb-1 whitespace-nowrap border border-rule bg-surface px-1.5 py-0.5 text-[11px] text-ink/70"
        >
          {state === "copied" ? "복사됨" : "복사 실패"}
        </span>
      )}
    </span>
  );
}
