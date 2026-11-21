"use client";

// 제보 버튼 + 제보 창 (#1241, 스펙 #1237). 권한을 켠 계정에만 보인다(`GET /feedback/permission`).
// 버튼 → 지금 화면 캡처 → 미리보기·가리기 → 갈래·내용 → 보내기. 화면 주소·앱·브라우저·화면 크기는
// 자동으로 붙는다. 캡처에 실패하거나 「그림 빼기」면 그림 없이 보낸다.

import { useCallback, useEffect, useRef, useState } from "react";

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
import { MarkupEditor, type MarkupHandle } from "./markup";

type Phase = "closed" | "capturing" | "editing" | "sending" | "done";

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
    setPhase("closed");
    setSource(null);
    setCaptureFailed(false);
    setBody("");
    setError(null);
  }, []);

  useEffect(() => {
    if (phase === "closed") return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && phase !== "sending" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, close]);

  if (!granted) return null;

  async function open() {
    setPhase("capturing");
    setError(null);
    const canvas = await captureViewport();
    setSource(canvas);
    setCaptureFailed(canvas === null);
    setPhase("editing");
  }

  async function retakeFromDisplay() {
    setHiddenForShare(true);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const canvas = await captureFromDisplay();
    setHiddenForShare(false);
    if (canvas) {
      setSource(canvas);
      setCaptureFailed(false);
    }
  }

  async function attachFile(file: File | undefined) {
    if (!file) return;
    const canvas = await canvasFromFile(file);
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

      {phase !== "closed" && phase !== "capturing" && !hiddenForShare && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/40 p-3">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="제보"
            data-testid="feedback-dialog"
            className="flex max-h-[92vh] w-full max-w-2xl flex-col gap-3 overflow-y-auto border border-rule bg-surface p-4 text-ink"
          >
            {phase === "done" ? (
              <>
                <p data-testid="feedback-done" className="text-[15px]">접수했습니다.</p>
                <div className="flex gap-2">
                  <a href={myReportsHref} className={buttonClass}>내 제보</a>
                  <button type="button" onClick={close} className={buttonClass}>닫기</button>
                </div>
              </>
            ) : (
              <>
                {source ? (
                  <MarkupEditor ref={markup} source={source} />
                ) : (
                  captureFailed && <p className="text-[13px] text-warning">화면을 뜨지 못했습니다.</p>
                )}
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
                <label className="flex flex-col gap-1 text-[13px]">
                  내용
                  <textarea
                    data-testid="feedback-body"
                    value={body}
                    maxLength={FEEDBACK_BODY_MAX}
                    rows={5}
                    onChange={(event) => setBody(event.target.value)}
                    className="border border-rule bg-paper p-2 text-[14px] text-ink"
                  />
                  <span className="self-end text-[12px] text-ink/60">{body.length}/{FEEDBACK_BODY_MAX}</span>
                </label>
                {error && <p role="alert" data-testid="feedback-error" className="text-[13px] text-error">{error}</p>}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={close} disabled={phase === "sending"} className={buttonClass}>닫기</button>
                  <button type="button" data-testid="feedback-submit" onClick={submit} disabled={phase === "sending"} className={buttonClass}>
                    {phase === "sending" ? "보내는 중" : "보내기"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
