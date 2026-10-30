// 약관·방침이 싣는 문의 주소(#472 후속).
//
// **개인정보 보호책임자와 문의처는 방침의 필수 기재사항이다**(개인정보 보호법
// 제30조 제1항). 그래서 값을 코드에 박지 않고 실행 env(`CODEMIT_PUBLIC_SUPPORT_EMAIL`,
// 서버의 `docker/.env.prod`)로 받는다 — 담당이 바뀌면 그 값을 고치고
// 컨테이너를 다시 띄우면 된다(이미지를 다시 굽지 않는다, #711).
//
// **값이 없으면 폴백을 지어내지 않는다**(#297 의 교훈). dev·CI 는 주지 않으므로
// 주소 없이 그려지고, 배포에 값이 빠진 것은 `frontend-deploy-guard` 가 `/privacy` 에서
// 직접 잡는다.
import { publicConfig } from "@/lib/public-config";

export function supportEmail(): string | null {
  return publicConfig().CODEMIT_PUBLIC_SUPPORT_EMAIL ?? null;
}
