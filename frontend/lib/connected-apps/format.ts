// 공모전 연결된 앱의 값과 순수 함수 (#870) — 백엔드 호출은 `api.ts`.

export type AuthorizationPreview = {
  client_name: string;
  redirect_host: string;
};

export type ConnectedAppRow = {
  id: number;
  name: string;
  connected_at: string;
  last_used_at: string | null;
};

/** 동의 화면이 앱에게서 받은 인가 요청 값 — 그대로 백엔드에 넘긴다. */
export const AUTHORIZE_PARAM_NAMES = [
  "client_id",
  "redirect_uri",
  "response_type",
  "code_challenge",
  "code_challenge_method",
  "state",
  "scope",
  "resource",
] as const;

export type AuthorizeParams = Record<(typeof AUTHORIZE_PARAM_NAMES)[number], string>;

/** 쿼리에서 인가 요청 값만 골라낸다 — 없거나 여러 개면 빈 문자열(백엔드가 거절한다). */
export function pickAuthorizeParams(raw: Record<string, string | string[] | undefined>): AuthorizeParams {
  return Object.fromEntries(
    AUTHORIZE_PARAM_NAMES.map((name) => {
      const value = raw[name];
      return [name, typeof value === "string" ? value : ""];
    }),
  ) as AuthorizeParams;
}

/** 앱이 이름을 밝히지 않았을 때 화면에 쓸 말. */
export function appDisplayName(name: string): string {
  return name.trim() || "이름을 밝히지 않은 앱";
}

const DAY = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "numeric", day: "numeric" });

/** 연결 한 줄의 날짜 — 「연결 2026. 11. 5. · 마지막 사용 2026. 11. 6.」(쓴 적이 없으면 「쓴 적 없음」). */
export function connectionDates(row: Pick<ConnectedAppRow, "connected_at" | "last_used_at">): string {
  const connected = `연결 ${DAY.format(new Date(row.connected_at))}`;
  const used = row.last_used_at ? `마지막 사용 ${DAY.format(new Date(row.last_used_at))}` : "쓴 적 없음";
  return `${connected} · ${used}`;
}
