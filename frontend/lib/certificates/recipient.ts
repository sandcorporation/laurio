// 받는 사람의 상장 줄(#1130, 스펙 #1071 결정 5) — 내 참가 현황의 제출 행에 붙는다.
// 상태·닫힘 판정은 서버가 하고(`GET /certificates/mine`), 여기서는 이름표와 단추 문구만 정한다.

export type MyCertificate = {
  id: number;
  submission_id: number;
  contest_id: number;
  contest_title: string;
  number: string;
  award_name: string;
  state: "valid" | "cancelled";
  hidden: boolean;
  verify_url: string;
};

export type CertificateLine = {
  stateLabel: string;
  tone: "verified" | "neutral";
  /** 취소된 상장은 받을 파일도, 닫을 확인 페이지도 없다. */
  canDownload: boolean;
  visibilityAction: { label: string; hidden: boolean } | null;
};

export function describeCertificateLine(certificate: MyCertificate): CertificateLine {
  if (certificate.state === "cancelled") {
    return { stateLabel: "취소됨", tone: "neutral", canDownload: false, visibilityAction: null };
  }
  return {
    stateLabel: certificate.hidden ? "유효 · 확인 페이지 닫힘" : "유효",
    tone: "verified",
    canDownload: true,
    visibilityAction: certificate.hidden
      ? { label: "확인 페이지 열기", hidden: false }
      : { label: "확인 페이지 닫기", hidden: true },
  };
}

/** 제출 행마다 붙일 상장 — 한 제출에 상장은 많아야 하나지만 취소된 것이 함께 남을 수 있다. */
export function certificatesBySubmission(certificates: MyCertificate[]): Map<number, MyCertificate[]> {
  const grouped = new Map<number, MyCertificate[]>();
  for (const certificate of certificates) {
    grouped.set(certificate.submission_id, [...(grouped.get(certificate.submission_id) ?? []), certificate]);
  }
  return grouped;
}
