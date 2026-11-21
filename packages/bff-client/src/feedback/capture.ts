// 지금 화면을 그림으로 뜬다 (#1241).
//
// 기본은 DOM 캡처다 — 버튼 한 번으로 되고 허락 창이 없다. 보조로 화면 공유(`getDisplayMedia`)와 파일.
// 한계(PR 에 같이 적는다): DOM 을 SVG foreignObject 로 옮겨 그리는 방식이라 iframe·`<video>`·canvas
// 속 내용은 담기지 않는다 — 그 자리는 회색 칸과 짧은 라벨로 바꿔 놓고 뜬다. 교차 출처 이미지는
// 라이브러리가 `fetch`(CORS)로 읽어 data URL 로 넣으므로 캔버스가 오염되지 않는다(버킷이
// `access-control-allow-origin: *` 를 준다). 읽지 못한 이미지는 빈 칸으로 남는다.

import { SCREENSHOT_MAX_BYTES, type ScreenshotType } from "./api";

/** 캡처에서 빼는 요소의 표지 — 제보 버튼·창 자신. */
export const IGNORE_ATTR = "data-feedback-ignore";

type Restore = () => void;

function blankOut(): Restore {
  const swapped: Array<{ original: HTMLElement; placeholder: HTMLElement }> = [];
  document.querySelectorAll<HTMLElement>("iframe, video").forEach((original) => {
    const rect = original.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const placeholder = document.createElement("div");
    const label = original.tagName === "VIDEO" ? "동영상" : "삽입된 화면";
    placeholder.textContent = `${label} — 캡처에서 빠짐`;
    placeholder.setAttribute("style", `width:${rect.width}px;height:${rect.height}px;display:flex;align-items:center;justify-content:center;background:#c8c8c8;color:#444;font:12px sans-serif;box-sizing:border-box;`);
    original.replaceWith(placeholder);
    swapped.push({ original, placeholder });
  });
  return () => swapped.forEach(({ original, placeholder }) => placeholder.replaceWith(original));
}

/** 지금 보이는 구역(스크롤 위치 기준 뷰포트)을 캔버스로. 실패하면 null. */
export async function captureViewport(): Promise<HTMLCanvasElement | null> {
  const restore = blankOut();
  try {
    const { toCanvas } = await import("html-to-image");
    const root = document.documentElement;
    const width = window.innerWidth;
    const height = window.innerHeight;
    const background = getComputedStyle(document.body).backgroundColor || "#ffffff";
    const options = {
      width,
      height,
      pixelRatio: 1,
      backgroundColor: background,
      style: { transform: `translate(${-window.scrollX}px, ${-window.scrollY}px)`, transformOrigin: "top left" },
      filter: (node: Node) => !(node instanceof HTMLElement && node.hasAttribute(IGNORE_ATTR)),
    };
    try {
      return await toCanvas(root, options);
    } catch {
      // 글꼴을 읽지 못해 실패하는 일이 있다 — 글꼴 없이 한 번 더.
      return await toCanvas(root, { ...options, skipFonts: true });
    }
  } catch {
    return null;
  } finally {
    restore();
  }
}

export function displayCaptureSupported(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getDisplayMedia === "function";
}

/** 브라우저의 화면 공유로 한 장 뜬다. 거절·실패하면 null. */
export async function captureFromDisplay(): Promise<HTMLCanvasElement | null> {
  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    return canvas.width > 0 ? canvas : null;
  } catch {
    return null;
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}

/** 이미지 파일을 캔버스로. 읽지 못하면 null. */
export async function canvasFromFile(file: File): Promise<HTMLCanvasElement | null> {
  try {
    const bitmap = await createImageBitmap(file);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
    bitmap.close();
    return canvas;
  } catch {
    return null;
  }
}

function toBlob(canvas: HTMLCanvasElement, type: ScreenshotType, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** 5MB 안으로 내보낸다 — webp 로 먼저(지원 않는 브라우저는 png 로 떨어진다), 넘으면 화질·크기를 줄인다. */
export async function exportUnderLimit(source: HTMLCanvasElement): Promise<Blob | null> {
  let canvas = source;
  let quality = 0.92;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const blob = await toBlob(canvas, "image/webp", quality);
    if (blob && blob.size <= SCREENSHOT_MAX_BYTES) return blob;
    if (attempt % 2 === 1 || quality <= 0.5) {
      const smaller = document.createElement("canvas");
      smaller.width = Math.max(1, Math.round(canvas.width * 0.8));
      smaller.height = Math.max(1, Math.round(canvas.height * 0.8));
      smaller.getContext("2d")?.drawImage(canvas, 0, 0, smaller.width, smaller.height);
      canvas = smaller;
    } else {
      quality -= 0.2;
    }
  }
  return null;
}
