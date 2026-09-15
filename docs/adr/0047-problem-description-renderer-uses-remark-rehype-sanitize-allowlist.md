# 문제 설명 렌더러를 remark·rehype-sanitize 허용 목록 스키마로 바꾼다 (ADR-0041 개정)

Status: Accepted (2026-09-15 결정)

ADR-0041은 문제 설명을 sanitize 하지 않는 대신 두 조건을 걸었다: (1) 저장되는 것이 HTML 이
아니다, (2) 렌더가 허용 목록 방식이다(`dangerouslySetInnerHTML` 없음, 아는 노드 타입만 그림,
링크·이미지는 http/https). 그때의 구현은 `marked` 렉서 토큰을 손으로 허용 목록 타입으로
옮기는 렌더러였다.

## 무엇이 문제였나

강사는 Toast UI 에디터로 설명을 쓰고, 그 에디터는 표·취소선·체크박스 목록을 지원한다.
손으로 만든 렌더러는 그 셋을 모르고, 제목도 굵기만 달라 크기가 본문과 같았다 — 에디터에서
보이는 설명이 참여자 화면에서 깨졌다(2026-09-15 사용자 보고). 지원 서식을 늘릴 때마다
토큰 변환을 손으로 늘려야 했다.

## 결정

렌더러를 **remark(+GFM, +줄바꿈 유지) → remark-rehype → rehype-sanitize(허용 목록 스키마)**
파이프라인으로 바꾸고, 걸러진 트리를 `hast-util-to-jsx-runtime` 으로 React 요소로 그린다.

ADR-0041 의 두 조건은 그대로 성립한다:

1. 저장되는 것은 여전히 마크다운 원문이다(백엔드 변경 없음).
2. 렌더는 여전히 허용 목록이다 — 원문의 raw HTML 은 HTML 트리로 옮기지 않고(remark-rehype
   기본값), rehype-sanitize 스키마가 허용한 태그·속성·스킴(http/https)만 남는다. 결과는
   HTML 문자열이 아니라 트리이고 `dangerouslySetInnerHTML` 을 쓰지 않는다. 파싱·거르기는
   여전히 React 없는 순수 함수(`classroom/lib/rendering/problem-description.ts`)라 공격
   문자열 단위 테스트가 이 조건을 고정한다.

허용 목록이 넓어졌다: 표·취소선·체크박스 목록(`disabled` 로만)이 더해졌다.

## 대가

- 의존성이 늘었다(unified·remark·rehype 생태계). 허용 목록의 **정의**는 우리 스키마지만
  **적용**은 라이브러리가 한다 — 라이브러리 결함이 곧 우리 결함이 된다. 공격 문자열 테스트가
  그 경계를 계속 친다.
- 체크박스 `input` 이 허용 태그에 들어갔다 — 스키마가 `type="checkbox"`·`disabled` 만
  남기고 이벤트 속성은 떨어뜨리는 것을 테스트로 고정했다.

---

**Amends ADR-0041** — 허용 목록 렌더의 구현을 바꾸고 허용 서식을 넓힌다. 두 조건은 그대로다.
