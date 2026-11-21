import { expect, request as playwrightRequest } from "@playwright/test";

import { e2eRunId } from "./run-id";
import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "./seed-operator";

// 운영자 API 로 계정의 제보 권한을 켜거나 끈다(스펙 #1237) — 시드가 없고 사슬 A 의 계약 그대로 쓴다.
// 최고 운영자 계정을 시드해 운영자 앱에 로그인한 뒤 `/api/backend/operator/feedback-permissions/…` 를 친다.
function operatorOrigin(): string {
  return new URL(process.env.CODEMIT_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001").origin;
}

export async function setFeedbackPermission(email: string, granted: boolean): Promise<void> {
  const operator = await seedE2eOperator({ username: `e2e-fb-op-${e2eRunId()}`.slice(0, 40), superuser: true });
  const origin = operatorOrigin();
  const ctx = await playwrightRequest.newContext({ baseURL: origin });
  try {
    const login = await ctx.post("/api/auth/login", {
      data: { username: operator.username, password: E2E_OPERATOR_PASSWORD },
      headers: { origin },
    });
    expect(login.ok(), await login.text()).toBe(true);
    const found = await ctx.get(`/api/backend/operator/feedback-permissions/search?q=${encodeURIComponent(email)}`);
    expect(found.ok(), await found.text()).toBe(true);
    const accounts = (await found.json()) as Array<{ user_id: number; email: string }>;
    const account = accounts.find((item) => item.email === email);
    expect(account, `계정 ${email}`).toBeTruthy();
    const put = await ctx.post(`/api/backend/operator/feedback-permissions/${account!.user_id}`, {
      data: { granted, reason: "e2e" },
      headers: { origin },
    });
    expect(put.ok(), await put.text()).toBe(true);
  } finally {
    await ctx.dispose();
  }
}

