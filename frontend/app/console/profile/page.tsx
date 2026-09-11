// 서버 절반 (#307) — `?from_origin=`을 검증해 강의실에서 건너온 사람에게만
// "강의실로 돌아가기"를 보여줄지 정한다. 클라이언트 컴포넌트
// (`profile-page-client.tsx`, #228)는 이미 있는 세션·저장 로직을 그대로 갖고
// 여기서는 오리진 판정만 한다 — `resolveSiblingOrigin`이 `process.env`를 직접
// 읽어(`LAURIO_CLASSROOM_ORIGIN`) 브라우저 번들에서는 값을 얻을 수 없으므로
// 서버 컴포넌트에서만 부를 수 있다(로그인 화면의 `classroomOrigin()`과 같은
// 제약, app/login/page.tsx).
import { resolveSiblingOrigin } from "@/lib/auth/sibling-origins";

import { ProfilePageClient } from "./profile-page-client";

export default async function ProfilePage({
  searchParams,
}: {
  searchParams: Promise<{ from_origin?: string }>;
}) {
  const params = await searchParams;
  const returnOrigin = resolveSiblingOrigin(params.from_origin);
  return <ProfilePageClient returnOrigin={returnOrigin} />;
}
