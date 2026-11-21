"use client";

import { useState } from "react";

import { Badge } from "@/app/components/badge";
import { TableScroll } from "@/app/components/table-scroll";

import { cancelCertificate } from "./actions";
import { certificateStatusLabel } from "./status-label";
import type { Certificate } from "./types";

const COL = {
  number: "w-[148px]",
  recipient: "w-[160px]",
  award: "w-[140px]",
  status: "w-[96px]",
  issued: "w-[196px]",
  action: "w-[200px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={`${COL.number} shrink-0`}>번호</div>
      <div className={`${COL.recipient} shrink-0`}>받는 사람</div>
      <div className={`${COL.award} shrink-0`}>상</div>
      <div className={`${COL.status} shrink-0`}>상태</div>
      <div className={`${COL.issued} shrink-0`}>발급</div>
      <div className="min-w-0 flex-1 text-right">작업</div>
    </div>
  );
}

function CancelCell({
  contestId,
  certificate,
  onCancelled,
}: {
  contestId: string;
  certificate: Certificate;
  onCancelled: () => void;
}) {
  const [step, setStep] = useState<"idle" | "confirm" | "sending">("idle");
  const [error, setError] = useState<string | null>(null);
  const id = certificate.id;

  if (certificate.status !== "valid") return null;

  async function confirm() {
    setStep("sending");
    setError(null);
    const result = await cancelCertificate(contestId, id);
    if (result.ok) {
      onCancelled();
      return;
    }
    setError(result.message);
    setStep("confirm");
  }

  if (step === "idle") {
    return (
      <button
        type="button"
        data-testid={`certificate-cancel-${id}`}
        onClick={() => setStep("confirm")}
        className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink"
      >
        취소
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <p data-testid={`certificate-cancel-warning-${id}`} className="text-[12px] text-attention">
        취소하면 되돌릴 수 없습니다.
      </p>
      <div className="flex gap-1.5">
        <button
          type="button"
          data-testid={`certificate-cancel-confirm-${id}`}
          disabled={step === "sending"}
          onClick={confirm}
          className="border border-attention bg-surface px-2.5 py-1 text-[12px] text-attention disabled:opacity-50"
        >
          취소 확정
        </button>
        <button
          type="button"
          disabled={step === "sending"}
          onClick={() => setStep("idle")}
          className="border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
        >
          닫기
        </button>
      </div>
      {error && (
        <p role="alert" data-testid={`certificate-cancel-error-${id}`} className="text-[12px] text-attention">
          {error}
        </p>
      )}
    </div>
  );
}

export function CertificateTable({
  contestId,
  certificates,
  onCancelled,
}: {
  contestId: string;
  certificates: Certificate[];
  onCancelled: () => void;
}) {
  return (
    <div data-testid="certificate-table" className="border border-rule bg-surface">
      <TableScroll minWidth={1040}>
        <TableHead />
        {certificates.map((c, i) => (
          <div
            key={c.id}
            data-testid={`certificate-row-${c.id}`}
            className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
              i % 2 === 1 ? "bg-ink/[2%]" : ""
            }`}
          >
            <div className={`${COL.number} shrink-0 font-mono text-[12.5px]`}>{c.number}</div>
            <div className={`${COL.recipient} shrink-0 truncate`}>{c.recipient_name || "-"}</div>
            <div className={`${COL.award} shrink-0 truncate`}>{c.award_name}</div>
            <div className={`${COL.status} shrink-0`}>
              <Badge testId={`certificate-status-${c.id}`} tone={c.status === "valid" ? "pass" : "neutral"}>
                {certificateStatusLabel(c.status)}
              </Badge>
            </div>
            <div className={`${COL.issued} shrink-0 whitespace-nowrap font-mono text-[12.5px] text-ink/62`}>
              {new Date(c.issued_at).toLocaleString("ko-KR")}
            </div>
            <div className="min-w-0 flex-1 text-right">
              <CancelCell contestId={contestId} certificate={c} onCancelled={onCancelled} />
            </div>
          </div>
        ))}
      </TableScroll>
    </div>
  );
}
