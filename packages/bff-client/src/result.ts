// 인증 구역 호출의 결과는 한 모양이다 (#146, #122).
//
// 화면 22개가 각자 `response.ok` · `status === 401` · `.detail` 파싱 · 폴백 문구를 다시 배우던 것을
// 여기 한 번으로 줄인다. 특히 `detail` — django-ninja 의 요청 검증 422 는 `detail` 이 오류 객체
// **배열**이라 그대로 React 자식으로 렌더하면 「Objects are not valid as a React child」로 화면
// 전체가 죽는다(운영자 앱이 #69 에서 배운 것, 공개 앱에는 없던 방어). `normalizeDetail` 이 문자열
// detail 과 배열 detail 을 사람이 읽는 문자열 하나로 좁힌다 — 폴백 문구도 여기 한 곳이다.

export type ApiFailure = {
  ok: false;
  /** HTTP 상태. 네트워크 실패는 0. */
  status: number;
  /** 화면이 분기할 때 쓰는 짧은 코드 — 상태의 이름이다. */
  code:
    | "unauthorized"
    | "forbidden"
    | "not_found"
    | "conflict"
    | "validation"
    /** 2xx 인데 본문을 해석하지 못했다 — 프록시가 HTML 에러 페이지를 대신 돌려준 경우처럼.
     * 「서버가 거절했다」와 다르므로 호출부가 갈라 다룰 수 있어야 한다(대화 화면은 이때 사과
     * 한 턴만 남기고 대화를 끊지 않는다). */
    | "malformed"
    | "network"
    | "error";
  /** 사람이 읽는 문구 — 서버 문구를 그대로, 없으면 폴백. */
  detail: string;
};

export type ApiSuccess<T> = { ok: true; status: number; data: T };

export type ApiResult<T> = ApiSuccess<T> | ApiFailure;

export const FALLBACK_DETAIL = "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.";

type ValidationItem = { loc?: unknown; msg?: unknown };

/** 서버의 `detail` 을 사람이 읽는 문자열 하나로 좁힌다.
 *
 * 문자열이면 그대로. django-ninja 요청 검증 422 의 배열이면 각 항목의 `msg` 를 이어 붙이고, 어느
 * 필드인지 알 수 있게 `loc` 의 마지막 조각을 앞에 붙인다(`body`·`payload` 같은 껍데기 조각은
 * 사람에게 의미가 없어 뺀다). 그 밖의 모양이면 `fallback` — 객체를 그대로 렌더해 화면을 죽이는
 * 경로가 여기서 닫힌다.
 */
export function normalizeDetail(detail: unknown, fallback: string = FALLBACK_DETAIL): string {
  if (typeof detail === "string" && detail.trim() !== "") return detail;

  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (entry === null || typeof entry !== "object") return null;
        const item = entry as ValidationItem;
        if (typeof item.msg !== "string") return null;
        const loc = Array.isArray(item.loc) ? item.loc : [];
        const field = loc.length > 0 ? String(loc[loc.length - 1]) : "";
        const named = field !== "" && field !== "body" && field !== "payload";
        return named ? `${field}: ${item.msg}` : item.msg;
      })
      .filter((part): part is string => part !== null);
    if (parts.length > 0) return parts.join(" ");
  }

  return fallback;
}

export function codeForStatus(status: number): ApiFailure["code"] {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422) return "validation";
  if (status === 0) return "network";
  return "error";
}
