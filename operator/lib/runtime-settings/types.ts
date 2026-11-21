// 운영 설정(#922, ADR-0075) — 백엔드 `policies.schemas.RuntimeSetting*Out` 의 모양.
// 비밀 값은 어느 응답에도 오지 않는다 — `configured`·`last4` 만 온다.

export type RuntimeSettingKind = "secret" | "text" | "float" | "switch" | "choice";
export type RuntimeSettingSource = "db" | "env" | "none";
export type ProbeResult = "ok" | "invalid_key" | "unavailable";

export interface RuntimeSetting {
  key: string;
  label: string;
  kind: RuntimeSettingKind;
  source: RuntimeSettingSource;
  configured: boolean;
  /** 비밀이 아닌 설정의 지금 값. 비밀이면 언제나 null. */
  value: string | null;
  /** 출처가 없을 때 어댑터가 쓰는 기본값. 비밀이면 null. */
  default: string | null;
  /** 비밀의 끝 4자리(짧은 키면 ""). 비밀이 아니면 null. */
  last4: string | null;
  updated_at: string | null;
  updated_by: string | null;
  /** `choice` 가 받는 값(#994). 그 밖의 kind 는 null. */
  choices: string[] | null;
  /** 스위치만(#1221) — 마지막 변경 시각, 그 뒤의 「이대로 둔다」(시각·확인한 운영자), 경보 대상이라 확인이 필요한가. */
  changed_at?: string | null;
  confirmed_at?: string | null;
  confirmed_by?: string | null;
  needs_confirm?: boolean;
}

export interface RuntimeSettingChange {
  id: number;
  key: string;
  label: string;
  action: "set" | "clear" | "ack";
  before: string;
  after: string;
  operator_username: string;
  changed_at: string;
}

export interface RuntimeSettingSaveResult {
  changed: boolean;
  setting: RuntimeSetting;
}

/** 에이전트 실행이 벤더 계정 쪽으로 마지막에 거절당한 기록(#1058). `kind` 는 백엔드 `ACCOUNT_REFUSAL_KINDS` 의 키. */
export interface AccountRefusal {
  at: string;
  vendor: string;
  kind: string;
}
