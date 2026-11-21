// 상장 확인 페이지 `/c/{token}`(#1128, 스펙 #1071 「확인 페이지 상태 셋」)의 표시 규칙.
//
// 어느 칸을 보여도 되는지는 백엔드가 이미 정했다(상태마다 비어 오는 칸이 있다). 여기서는
// 상태 이름표와 줄 순서만 정한다 — 화면이 원시 응답에서 다시 판정하지 않게 한다.
import type { components } from "@codemit/bff-client/schema";

export type CertificateVerification = components["schemas"]["CertificateVerifyOut"];

export interface VerifyRow {
  label: string;
  value: string;
  mono?: boolean;
}

export interface VerifyView {
  stateLabel: string;
  tone: "valid" | "void";
  rows: VerifyRow[];
}

/** `2026-12-01` → `2026년 12월 1일`. 시간대를 타지 않게 문자열을 그대로 자른다. */
export function formatKoreanDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  return `${year}년 ${month}월 ${day}일`;
}

function giverLine(name: string, title: string): string {
  return title ? `${name} · ${title}` : name;
}

export function describeVerification(v: CertificateVerification): VerifyView {
  const number: VerifyRow = { label: "상장 번호", value: v.number, mono: true };

  if (v.state === "hidden") {
    return { stateLabel: "확인할 수 없는 상장", tone: "void", rows: [number] };
  }

  if (v.state === "cancelled") {
    return {
      stateLabel: v.reissued ? "취소됨 — 다시 발급됨" : "취소됨",
      tone: "void",
      rows: [
        number,
        { label: "공모전", value: v.contest_title ?? "" },
        { label: "취소일", value: v.cancelled_on ? formatKoreanDate(v.cancelled_on) : "" },
      ],
    };
  }

  return {
    stateLabel: "✓ 유효한 상장",
    tone: "valid",
    rows: [
      number,
      { label: "공모전", value: v.contest_title ?? "" },
      { label: "상", value: v.award_name ?? "" },
      { label: "받는 사람", value: v.recipient_name ?? "" },
      { label: "수여자", value: giverLine(v.giver_name ?? "", v.giver_title ?? "") },
      { label: "발급일", value: v.issued_on ? formatKoreanDate(v.issued_on) : "" },
    ],
  };
}
