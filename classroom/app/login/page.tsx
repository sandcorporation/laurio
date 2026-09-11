// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 회원은 공개 앱과 공유한다. 이
// 화면은 공개 앱의 로그인으로 안내만 한다: 거기서 로그인하면 부모 도메인 쿠키가
// 이 앱에도 실려, 다시 이 링크를 눌러 돌아오면 middleware.ts가 통과시킨다.
//
// next를 그대로 전달하지 않는다 — lib/auth/next-path.ts(공개 앱)의 isSafeNextPath는
// 같은 오리진 상대 경로만 허용해 다른 서브도메인(classroom.laurio.…)으로의
// 복귀를 구조적으로 막는다(오픈 리다이렉트 방지, 그 파일 상단 주석 참고). 그
// 검사를 느슨하게 하지 않는다 — 대신 사람이 로그인 후 직접 이 화면으로 돌아오게
// 안내한다.
import { headers } from "next/headers";

import { PageShell, buttonClass } from "@/app/components/ui";
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

export default async function ClassroomLoginPage() {
  // 로그인이 끝나면 **여기로 돌아온다**(#297 후속). 공개 앱은 `next_origin` 을 자기
  // 허용목록과 대조해 통과한 것만 쓴다 — 임의 URL 로 튕길 수 있는 자리가 아니다
  // (frontend/lib/auth/sibling-origins.ts). 목록에 없으면 지금까지처럼 공개 앱
  // 안에서 끝나고, 사람은 아래 안내대로 직접 돌아온다.
  const requestHeaders = await headers();
  const origin = classroomOrigin(
    requestHeaders.get("host"),
    requestHeaders.get("x-forwarded-proto"),
  );
  const login = new URL("/login", publicAppOrigin());
  if (origin) {
    login.searchParams.set("next_origin", origin);
    login.searchParams.set("next", "/");
  }
  const loginUrl = login.toString();

  return (
    <PageShell>
      <div className="mx-auto max-w-[520px] pt-10">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]" data-testid="classroom-login-heading">
          로그인이 필요합니다
        </h1>
        <p className="mt-3 text-[13.5px] leading-relaxed text-ink/60" data-testid="classroom-login-guide">
          클래스는 별도 계정 없이 Laurio 로그인을 그대로 씁니다. 아래 버튼으로
          로그인한 뒤 이 화면으로 돌아와 주세요.
        </p>
        <p className="mt-6">
          <a href={loginUrl} data-testid="classroom-login-link" className={buttonClass("primary")}>
            Laurio 로그인으로 이동
          </a>
        </p>
        <p className="mt-6 border-t border-rule pt-4 text-[11.5px] leading-relaxed text-ink/45">
          로그인하면 같은 계정으로 공모전과 클래스를 모두 쓸 수 있습니다. 이미 로그인했는데도 이
          화면이 보인다면 세션이 만료된 것입니다.
        </p>
      </div>
    </PageShell>
  );
}
