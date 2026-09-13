// 계정 메뉴의 서버 절반(#306) — 프로필·탈퇴로 나가는 주소는 이 앱의 오리진과
// 공개 앱의 오리진을 알아야 짓는다. 로그인 화면(app/login/page.tsx)과 같은
// 이유로 서버에서만 `headers()`·환경변수를 읽고, 상호작용(useMe·드롭다운)은
// 클라이언트 컴포넌트에 넘긴다.
import { headers } from "next/headers";

import { classroomOrigin, publicAppOrigin } from "@/lib/auth/public-app";
import { buildProfileUrl } from "@/lib/auth/return-link";

import { AccountMenuClient } from "./account-menu-client";

export async function AccountMenu() {
  const requestHeaders = await headers();
  const origin = classroomOrigin(
    requestHeaders.get("host"),
    requestHeaders.get("x-forwarded-proto"),
  );
  const publicOrigin = publicAppOrigin();

  // origin이 null이 되는 건 host 헤더 자체가 없을 때뿐이다(실제 요청에서는
  // 일어나지 않는다) — 그래도 폴백 없이 죽지 않도록 이 앱 자신을 가리키는
  // 값 대신 그대로 publicOrigin 만으로 짓는다(from_origin이 빈 값이 되지
  // 않게, 검증은 어차피 받는 쪽이 한다).
  const safeOrigin = origin ?? publicOrigin;

  return (
    <AccountMenuClient
      profileUrl={buildProfileUrl(publicOrigin, safeOrigin)}
    />
  );
}
