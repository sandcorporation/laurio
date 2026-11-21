// 운영자 상장 목록(#1131)이 쓰는 타입 — 응답 모양은 생성 타입 그대로다.
import type { components } from "@codemit/bff-client/schema";

export type CertificateList = components["schemas"]["OperatorCertificateListOut"];
export type Certificate = components["schemas"]["OperatorCertificateOut"];
