// 백엔드 fetch 공통 래퍼 (#278). 이 앱은 아직 `@laurio/bff-client`를 쓰지
// 않는다(docker/classroom.Dockerfile 주석 참고) — Class·Problem·체크리스트뿐인
// 지금 범위에는 얇은 fetch 래퍼로 충분하고, 프록시(app/api/backend/[...path]/
// route.ts)가 인증 헤더 첨부·리프레시를 이미 처리한다.
//
// 상태 코드를 에러 메시지 문자열 매칭이 아니라 `BackendError.status`로 구별한다
// — 백엔드가 문구를 바꾸면 화면 분기가 조용히 깨지는 일을 막는다.
export class BackendError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // 본문이 JSON이 아니면 아래 기본 문구를 쓴다.
  }
  return "요청을 처리하지 못했습니다.";
}

export async function backendJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new BackendError(response.status, await readErrorDetail(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
