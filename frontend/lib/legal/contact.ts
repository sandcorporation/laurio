// 약관·방침이 싣는 문의 주소(#472 후속).
//
// **개인정보 보호책임자와 문의처는 방침의 필수 기재사항이다**(개인정보 보호법
// 제30조 제1항). 그래서 값을 코드에 박지 않고 빌드 인자로 받는다 — 담당이
// 바뀌면 저장소 변수(`STAGING_SUPPORT_EMAIL`·`PROD_SUPPORT_EMAIL`)만 고치고
// 이미지를 다시 구우면 된다.
//
// **`NEXT_PUBLIC_*` 이라 브라우저 번들과 서버 렌더 양쪽에 빌드 시점 값이
// 굳는다** — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 와 같은 제약이고, 값을 바꾸면
// 이미지를 다시 굽는 것이 반영의 유일한 길이다(CLAUDE.md 「이미지는 CI 가
// 굽는다」).
//
// **값이 없으면 폴백을 지어내지 않는다**(#297 의 교훈 — 빌드 시점에 빈 값이
// 박히면 폴백이 그대로 배포에 나간다). dev·CI 는 주지 않으므로 주소 없이
// 그려지고, 배포 이미지에 값이 빠진 것은 `frontend-deploy-guard` 가 구운
// 이미지의 `/privacy` 에서 직접 잡는다.
export function supportEmail(): string | null {
  const value = (process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "").trim();
  return value === "" ? null : value;
}
