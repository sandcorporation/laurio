"use client";

// 로그인한 본인의 User pk (#286) — 소스 제출의 target_ref
// (`classroom-submission:<problem_id>:<user_id>:source`)를 조립하는 데
// 필요하다. `accounts.DeveloperProfile`이 없는 강의실 참여자가 자기 pk를
// 알 수 있는 유일한 경로가 공유층의 `GET /api/accounts/me`다.
//
// `username`·`email`도 같은 응답(`accounts.schemas.MeOut`)에서 함께 받는다(#306)
// — 헤더 계정 메뉴가 "지금 누구로 들어와 있는지"를 보여줘야 하는데, 그 값을 얻는
// 유일한 경로도 이 호출뿐이라 새 요청을 늘리지 않고 이미 있는 필드를 더 읽는다.
//
// **`username`을 화면에 그대로 그리면 안 된다.** 소셜 로그인 계정의 username 은
// `kakao:5069350637` 같은 제공자 식별자다 — staging 에서 실제로 그 문자열이 헤더에
// 떠 있었다. `accountLabel`이 그 판단을 한 곳에 둔다.
//
// **조회 자체는 `./me-context`(`MeProvider`)가 한다(#322)** — 헤더의 종(#304)과
// 계정 메뉴(#306)가 나란히 서면서 각자 `useState`+`useEffect`로 이 훅을 부르면
// `GET /accounts/me`가 페이지 한 번 열 때 두 번 나갔다. 이 파일은 그 훅을 `useMe`
// 라는 익숙한 이름으로 다시 내보내기만 한다 — 소비자 쪽 호출부는 하나도 안
// 바뀐다.
export { accountLabel } from "./account-label";
export { useMeState as useMe, type MeState } from "./me-context";

