# 세션은 localStorage의 JWT + 블랙리스트로 관리한다

SPA(frontend, admin)와 향후 모바일까지 붙이기 쉬운 구성을 우선해 JWT를 localStorage에 둔다. stateless JWT의 고질적 문제인 "탈취를 알아도 만료까지 못 막는다"는 서버측 블랙리스트로 해결한다.

HttpOnly 쿠키를 쓰면 토큰이 JS에 노출되지 않지만, 별도 도메인 구성과 SameSite·CORS 제약이 따라붙는다. 그 편의를 택한 대신 XSS로 토큰이 유출되는 경로는 열려 있으므로, 방어를 다른 층에서 세운다.

## Consequences

이 결정은 다음 보완책과 한 묶음이며, 셋 중 하나라도 빠지면 결정 자체가 무효다.

- 사용자 입력 서식(특히 Developer 프로필 자기소개)의 sanitize를 강제한다
- CSP 헤더로 외부 스크립트 실행과 데이터 반출을 제한한다
- 액세스 토큰 수명을 짧게 두고 리프레시 토큰을 회전시킨다

블랙리스트를 두므로 완전한 stateless는 아니며, 토큰 검증 경로에 조회가 하나 들어간다. 계정 탈취가 곧 금전 탈취인 서비스이므로, XSS가 실제로 발견되면 이 ADR을 HttpOnly 쿠키 방향으로 다시 열어야 한다.

---

**Amended by ADR-0016** — 웹 프론트엔드는 토큰을 HttpOnly 쿠키에 두고 BFF로 프록시한다. Django의 Bearer 인증은 그대로이며, 모바일 경로는 이 ADR 그대로 유지된다.
