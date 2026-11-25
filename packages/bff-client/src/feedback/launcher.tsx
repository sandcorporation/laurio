"use client";

// 제보 버튼 + 제보 창 (#1241, 스펙 #1237). 권한을 켠 계정에만 보인다(`GET /feedback/permission`).
// 버튼 → 지금 화면 캡처 → 미리보기·가리기 → 갈래·내용 → 보내기. 화면 주소·앱·브라우저·화면 크기는
// 자동으로 붙는다. 캡처에 실패하거나 「그림 빼기」면 그림 없이 보낸다.

import { useCallback, useEffect, useId, useRef, useState, type MouseEvent } from "react";

import type { BffClient } from "../client";
import {
  FEEDBACK_BODY_MAX,
  KIND_LABELS,
  type FeedbackApp,
  type FeedbackKind,
  createReport,
  fetchPermission,
  uploadScreenshot,
} from "./api";
import {
  IGNORE_ATTR,
  canvasFromFile,
  captureFromDisplay,
  captureViewport,
  displayCaptureSupported,
  exportUnderLimit,
} from "./capture";
import { trapTabTarget } from "./focus-trap";
import { createSessionGate } from "./session-gate";
import { MarkupEditor, type MarkupHandle } from "./markup";

type Phase = "closed" | "capturing" | "editing" | "sending" | "done";

const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const buttonClass = "border border-rule bg-surface px-3 py-1.5 text-[13px] text-ink hover:border-ink disabled:opacity-40";

export function FeedbackLauncher({
  client,
  permissionClient,
  app,
  myReportsHref,
}: {
  client: BffClient;
  /** 권한 조회만 이 클라이언트로 — 되살리기 없는 것을 주면 로그인 안 한 방문자가 재시도를 만들지 않는다. */
  permissionClient?: BffClient;
  app: FeedbackApp;
  myReportsHref: string;
}) {
  const [granted, setGranted] = useState(false);
  const [phase, setPhase] = useState<Phase>("closed");
  const [source, setSource] = useState<HTMLCanvasElement | null>(null);
  const [captureFailed, setCaptureFailed] = useState(false);
  const [kind, setKind] = useState<FeedbackKind>("suggestion");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [hiddenForShare, setHiddenForShare] = useState(false);
  const markup = useRef<MarkupHandle>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  // 제보 버튼 — 창이 닫히면 초점이 돌아올 곳(#1496 ⑧).
  const opener = useRef<HTMLElement | null>(null);
  // 기다리는 일(캡처·화면 공유·파일)이 끝났을 때 그 사이 창이 닫혔으면 늦은 결과를 버린다(#1503 ⑤).
  const gate = useRef(createSessionGate());
  // 창의 설명 — 접수 결과, 아니면 지금 떠 있는 경고·오류. 가리킬 것이 없으면 속성을 달지 않는다.
  const doneId = useId();
  const captureFailedId = useId();
  const errorId = useId();

  useEffect(() => {
    let alive = true;
    void fetchPermission(permissionClient ?? client).then((result) => {
      if (alive) setGranted(result.ok && result.data.granted);
    });
    return () => {
      alive = false;
    };
  }, [client, permissionClient]);

  const close = useCallback(() => {
    gate.current.invalidate();
    setPhase("closed");
    setSource(null);
    setCaptureFailed(false);
    setBody("");
    setError(null);
  }, []);

  // 창의 초점 규약(#1496 ⑧) — Escape 로 닫히고, Tab 은 창 안에 갇힌다. 창 안을 눌러 초점이 body 로 빠져도 먹도록 window 에서 듣는다.
  useEffect(() => {
    if (phase === "closed") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (phase !== "sending") close();
        return;
      }
      if (event.key !== "Tab") return;
      const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
      const target = trapTabTarget(event.shiftKey, items.indexOf(document.activeElement as HTMLElement), items.length);
      if (target === null) return;
      event.preventDefault();
      items[target]?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, close]);

  // 창이 (다시) 그려지면 안으로 들어간다 — 내용 칸, 접수 뒤에는 창 안 첫 대상. 화면 공유로 창이 잠깐 숨었다 돌아올 때도 같다.
  const dialogShown = phase !== "closed" && phase !== "capturing" && !hiddenForShare;
  const done = phase === "done";
  useEffect(() => {
    if (!dialogShown) return;
    (bodyRef.current ?? dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus();
  }, [dialogShown, done]);

  // 닫히면 연 단추로 돌아온다.
  useEffect(() => {
    if (phase !== "closed") return;
    const back = opener.current;
    opener.current = null;
    if (back?.isConnected && (!document.activeElement || document.activeElement === document.body)) back.focus();
  }, [phase]);

  if (!granted) return null;

  // 연 단추는 클릭의 currentTarget 이다 — document.activeElement 는 낭독기 활성화·일부 터치에서 body 다(#1509 ②).
  async function open(event: MouseEvent<HTMLButtonElement>) {
    opener.current = event.currentTarget;
    setPhase("capturing");
    setError(null);
    const ticket = gate.current.begin();
    const canvas = await captureViewport();
    if (!gate.current.isCurrent(ticket)) return;
    setSource(canvas);
    setCaptureFailed(canvas === null);
    setPhase("editing");
  }

  async function retakeFromDisplay() {
    const ticket = gate.current.begin();
    setHiddenForShare(true);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const canvas = await captureFromDisplay();
    setHiddenForShare(false);
    if (canvas && gate.current.isCurrent(ticket)) {
      setSource(canvas);
      setCaptureFailed(false);
    }
  }

  async function attachFile(file: File | undefined) {
    if (!file) return;
    const ticket = gate.current.begin();
    const canvas = await canvasFromFile(file);
    if (!gate.current.isCurrent(ticket)) return;
    if (canvas) {
      setSource(canvas);
      setCaptureFailed(false);
    } else setError("이미지 파일을 읽지 못했습니다.");
  }

  async function submit() {
    if (body.trim() === "") {
      setError("내용을 적어 주세요.");
      return;
    }
    setPhase("sending");
    setError(null);
    let screenshotKey = "";
    if (source) {
      const blob = await exportUnderLimit(markup.current?.compose() ?? source);
      if (!blob) {
        setError("그림이 너무 커서 줄이지 못했습니다. 그림을 빼고 보내 주세요.");
        setPhase("editing");
        return;
      }
      const uploaded = await uploadScreenshot(client, blob);
      if (!uploaded.ok) {
        setError(uploaded.detail);
        setPhase("editing");
        return;
      }
      screenshotKey = uploaded.key;
    }
    const result = await createReport(client, {
      kind,
      body: body.trim(),
      app,
      page_url: window.location.href,
      user_agent: navigator.userAgent,
      screen_width: window.innerWidth,
      screen_height: window.innerHeight,
      screenshot_key: screenshotKey,
    });
    if (!result.ok) {
      setError(result.detail);
      setPhase("editing");
      return;
    }
    setPhase("done");
  }

  const describedBy =
    phase === "done"
      ? doneId
      : [!source && captureFailed ? captureFailedId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div {...{ [IGNORE_ATTR]: "" }}>
      <div className="fixed bottom-4 right-4 z-30 flex gap-2">
        <button type="button" data-testid="feedback-open" onClick={open} disabled={phase !== "closed"} className={buttonClass}>
          제보
        </button>
        <a href={myReportsHref} data-testid="feedback-my-reports-link" className={buttonClass}>
          내 제보
        </a>
      </div>

      {dialogShown && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/40 p-3">
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="제보"
            aria-describedby={describedBy}
            data-testid="feedback-dialog"
            className="flex max-h-[96dvh] lg:h-[96dvh] w-full max-w-[96vw] flex-col gap-3 overflow-y-auto border border-rule bg-surface p-4 text-ink"
          >
            {phase === "done" ? (
              <>
                <p id={doneId} data-testid="feedback-done" className="text-[15px]">접수했습니다.</p>
                <div className="flex gap-2">
                  <a href={myReportsHref} className={buttonClass}>내 제보</a>
                  <button type="button" onClick={close} className={buttonClass}>닫기</button>
                </div>
              </>
            ) : (
              <div className="flex flex-col gap-3 lg:grid lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-4">
                <div className="min-w-0">
                  {source ? (
                    <MarkupEditor ref={markup} source={source} />
                  ) : (
                    captureFailed && <p id={captureFailedId} className="text-[13px] text-warning">화면을 뜨지 못했습니다.</p>
                  )}
                </div>
                <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  {displayCaptureSupported() && (
                    <button type="button" data-testid="feedback-share" className={buttonClass} onClick={retakeFromDisplay}>
                      화면 공유로 다시 뜨기
                    </button>
                  )}
                  <button type="button" data-testid="feedback-attach" className={buttonClass} onClick={() => fileInput.current?.click()}>
                    파일 붙이기
                  </button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    hidden
                    data-testid="feedback-file"
                    onChange={(event) => {
                      void attachFile(event.target.files?.[0]);
                      event.target.value = "";
                    }}
                  />
                  {source && (
                    <button type="button" data-testid="feedback-drop-image" className={buttonClass} onClick={() => setSource(null)}>
                      그림 빼기
                    </button>
                  )}
                </div>
                <fieldset className="flex gap-4 text-[14px]">
                  <legend className="sr-only">갈래</legend>
                  {(["suggestion", "bug"] as const).map((value) => (
                    <label key={value} className="flex items-center gap-1.5">
                      <input type="radio" name="feedback-kind" checked={kind === value} onChange={() => setKind(value)} data-testid={`feedback-kind-${value}`} />
                      {KIND_LABELS[value]}
                    </label>
                  ))}
                </fieldset>
                <label className="flex flex-col gap-1 text-[13px] lg:flex-1">
                  내용
                  <textarea
                    ref={bodyRef}
                    data-testid="feedback-body"
                    value={body}
                    maxLength={FEEDBACK_BODY_MAX}
                    rows={3}
                    onChange={(event) => setBody(event.target.value)}
                    className="border border-rule bg-paper p-2 text-[14px] text-ink lg:flex-1"
                  />
                  <span className="self-end text-[12px] text-ink/60">{body.length}/{FEEDBACK_BODY_MAX}</span>
                </label>
                {error && <p id={errorId} role="alert" data-testid="feedback-error" className="text-[13px] text-error">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={close} disabled={phase === "sending"} className={buttonClass}>닫기</button>
                  <button type="button" data-testid="feedback-submit" onClick={submit} disabled={phase === "sending"} className={buttonClass}>
                    {phase === "sending" ? "보내는 중" : "보내기"}
                  </button>
                </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
