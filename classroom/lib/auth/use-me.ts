"use client";

// 로그인한 본인의 User pk (#286) — 소스 제출의 target_ref
// (`classroom-submission:<problem_id>:<user_id>:source`)를 조립하는 데
// 필요하다. `accounts.DeveloperProfile`이 없는 강의실 참여자가 자기 pk를
// 알 수 있는 유일한 경로가 공유층의 `GET /api/accounts/me`다.
//
// `username`·`email`도 같은 응답(`accounts.schemas.MeOut`)에서 함께 받는다(#306)
// — 로그인 여부(로딩·성공·실패)를 판정하는 데 이 호출 하나면 된다.
//
// **계정 메뉴 버튼은 이 값들을 화면에 그리지 않는다**(#376) — 예전에는
// `accountLabel`이 username(소셜 로그인 계정이면 `kakao:5069350637` 같은 제공자
// 식별자 — staging 에서 실제로 그 문자열이 헤더에 떠 있었다) 대신 email을 우선
// 보여줬는데, 공개 앱과 모양을 맞추며 버튼 문구 자체를 항상 「내 계정」으로
// 고정했다 — 그 판단표가 더는 필요 없어 함께 지웠다.
//
// **조회 자체는 `./me-context`(`MeProvider`)가 한다(#322)** — 헤더의 종(#304)과
// 계정 메뉴(#306)가 나란히 서면서 각자 `useState`+`useEffect`로 이 훅을 부르면
// `GET /accounts/me`가 페이지 한 번 열 때 두 번 나갔다. 이 파일은 그 훅을 `useMe`
// 라는 익숙한 이름으로 다시 내보내기만 한다 — 소비자 쪽 호출부는 하나도 안
// 바뀐다.
export { useMeState as useMe, type MeState } from "./me-context";

