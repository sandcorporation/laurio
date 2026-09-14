// 우리 형제 오리진 목록 (#297 후속). 로그인은 공개 앱 하나에만 있고(ADR-0038)
// 강의실은 거기로 사람을 보낸다. 로그인이 끝나면 **원래 있던 곳으로** 돌아와야
// 하는데, `next` 는 같은 오리진 상대 경로만 허용하므로(lib/auth/next-path.ts)
// 다른 서브도메인으로는 구조적으로 못 돌아간다.
//
// **그 검사를 느슨하게 하지 않는다.** 그 파일 주석이 적어 둔 대로 예전에
// `next=%2F%5Cevil.example.test` 로 실제로 뚫린 적이 있고, 문자열 검사로는 끝없이
// 새 우회가 나온다. 대신 **설정에 적힌 우리 오리진만** 따로 받는다 — 사용자 입력이
// 고르는 것은 「이 목록 중 어느 것인가」뿐이고, 목록 자체는 배포 설정이다.
//
// 값은 `CODEMIT_CLASSROOM_ORIGIN` 에서 온다 — 강의실 컨테이너가 읽는 것과 **같은
// `.env` 줄**이다(`CODEMIT_OPERATOR_ORIGIN` 과 같은 원칙). 어긋나면 복귀가 조용히
// 안 되고 사람은 공개 앱에 남는다 — 안전한 쪽으로 실패한다.

/** 설정된 형제 오리진 전부. 비어 있으면(dev 기본) 복귀 자체가 꺼진다. */
export function configuredSiblingOrigins(): string[] {
  return [process.env.CODEMIT_CLASSROOM_ORIGIN]
    .filter((v): v is string => typeof v === "string" && v.trim() !== "")
    .map(normalizeOrigin)
    .filter((v): v is string => v !== null);
}

/** `https://a.example/` 와 `https://a.example` 를 같은 것으로 본다. 파싱에 실패하면 null. */
function normalizeOrigin(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * 후보가 설정된 형제 오리진 **그 자체**일 때만 돌려준다.
 *
 * 접두어 비교가 아니라 파싱한 `origin` 끼리의 완전 일치다 —
 * `https://classroom.codemit.kr.evil.test` 같은 접미어 트릭과
 * `https://classroom.codemit.kr@evil.test` 같은 authority 트릭을 둘 다 막는다.
 */
export function resolveSiblingOrigin(candidate: string | null | undefined): string | null {
  if (!candidate) return null;
  const normalized = normalizeOrigin(candidate);
  if (normalized === null) return null;
  return configuredSiblingOrigins().includes(normalized) ? normalized : null;
}
