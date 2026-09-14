// 운영자 계정 목록·생성이 쓰는 타입 (#68) — 응답 모양은 생성 타입 그대로다(#148).

import type { components } from "@codemit/bff-client/schema";

export type OperatorAccount = components["schemas"]["OperatorOut"];
