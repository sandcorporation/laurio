// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 회원은 공개 앱과 공유한다. 이
// 화면은 공개 앱의 로그인으로 안내만 한다: 거기서 로그인하면 부모 도메인 쿠키가
// 이 앱에도 실려, 공개 앱이 `next_origin`·`next`로 실어 보낸 이 앱의 원래
// 주소로 곧장 돌아온다(#334) — 초대 링크(`/join/{code}`)를 받은 사람이 로그인
// 때문에 그 링크를 잃던 사고가 이것이다.
//
// `next`는 이 앱 안의 상대 경로인지 먼저 검증한다(lib/auth/next-path.ts의
// isSafeNextPath) — 검증되지 않은 값을 그대로 실으면 공개 앱을 거쳐 돌아올 때
// (#297 후속) 오픈 리다이렉트 표면이 새로 열린다. 공개 앱 쪽 검사(같은 오리진
// 상대 경로만 허용하는 isSafeNextPath, 허용목록과 대조하는
// resolveSiblingOrigin)는 그대로 둔다 — 이 앱이 하는 일은 "이 목록 중 어느
// 주소로 돌아갈지"를 `next`에 실어 보내는 것뿐이다.
import { headers } from "next/headers";

import { PageShell, buttonClass } from "@/app/components/ui";
import { resolveNextPath } from "@/lib/auth/next-path";
import { classroomOrigin, publicAppOrigin } from "@/lib/auth/public-app";

// **정적으로 구워지면 안 된다** (#297). 이 화면은 `searchParams`·`cookies`·`headers`
// 를 하나도 읽지 않아 Next 가 기본으로 빌드 시점에 HTML 로 구워 버린다. 그러면
// `publicAppOrigin()` 이 **빌드 머신의** 환경(=비어 있음)을 읽어 dev 폴백
// `http://127.0.0.1:53000` 이 박제되고, 배포된 강의실에서 로그인이 아예 불가능해진다.
// 실제로 그렇게 깨졌다 — `x-nextjs-prerender: 1`, `cache-control: s-maxage=31536000`.
//
// dev 도 CI e2e 도 이것을 못 본다(둘 다 그 값이 비어 있어 폴백이 「맞는 답」이다).
// `lib/rendering/runtime-config.test.ts` 가 구조를, CI 의 classroom-deploy-guard 가
// 결과를 잡는다.
export const dynamic = "force-dynamic";

export default async function ClassroomLoginPage({
  searchParams,
}: {
  // `next`가 string[]일 수 있다(같은 쿼리 키가 반복될 때) — resolveNextPath가
  // 그 경우를 안전하지 않은 값으로 거부한다(lib/auth/next-path.ts 상단 주석).
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  // 로그인이 끝나면 **여기로 돌아온다**(#297 후속, #334). 공개 앱은
  // `next_origin` 을 자기 허용목록과 대조해 통과한 것만 쓴다 — 임의 URL 로
  // 튕길 수 있는 자리가 아니다(frontend/lib/auth/sibling-origins.ts). 목록에
  // 없으면 지금까지처럼 공개 앱 안에서 끝나고, 사람은 아래 안내대로 직접
  // 돌아온다.
  //
  // `next` 는 middleware.ts(인증 구역 가드)나 가입 화면의 로그인 링크가
  // `/login?next=<원래 경로>` 로 실어 보낸 값이다 — 이 앱 안의 상대 경로인지
  // 검증한 뒤에만 그대로 돌려보낸다. 검증에 실패하면(또는 애초에 없으면) 첫
  // 화면("/")으로 떨어진다.
  const requestHeaders = await headers();
  const { next } = await searchParams;
  const origin = classroomOrigin(
    requestHeaders.get("host"),
    requestHeaders.get("x-forwarded-proto"),
  );
  const login = new URL("/login", publicAppOrigin());
  if (origin) {
    login.searchParams.set("next_origin", origin);
    login.searchParams.set("next", resolveNextPath(next));
  }
  const loginUrl = login.toString();

  return (
    <PageShell>
      <div className="mx-auto max-w-[520px] pt-10">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]" data-testid="classroom-login-heading">
          로그인이 필요합니다
        </h1>
        <p className="mt-6">
          <a href={loginUrl} data-testid="classroom-login-link" className={buttonClass("primary")}>
            로그인
          </a>
        </p>
      </div>
    </PageShell>
  );
}
