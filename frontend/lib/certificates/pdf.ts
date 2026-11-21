"use client";

import { bffClient } from "@/lib/bff/client";

type PdfResult = { ok: true; blob: Blob } | { ok: false; message: string };

const FALLBACK = "파일을 받지 못했습니다.";

async function readPdf(path: string, init?: RequestInit): Promise<PdfResult> {
  let response: Response;
  try {
    response = await bffClient.fetch(path, init);
  } catch {
    return { ok: false, message: FALLBACK };
  }
  if (response.ok) return { ok: true, blob: await response.blob() };
  const body: unknown = await response.json().catch(() => undefined);
  const detail =
    body !== null && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  return { ok: false, message: typeof detail === "string" ? detail : FALLBACK };
}

export function fetchPdf(path: string): Promise<PdfResult> {
  return readPdf(path, { cache: "no-store" });
}

export function postForPdf(path: string, body: unknown): Promise<PdfResult> {
  return readPdf(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** 받은 PDF 를 내려받는다 — 임시 링크를 눌러 저장하게 한다. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
