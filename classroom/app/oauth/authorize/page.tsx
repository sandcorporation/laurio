// 연결된 앱의 동의 화면 (ADR-0052, #512) — OAuth 인가 엔드포인트다.
//
// claude.ai 같은 앱이 강사의 브라우저를 이 주소로 보낸다(`client_id`·`redirect_uri`·
// PKCE·`state`·`resource`). 로그인하지 않았으면 middleware.ts 가 `/login?next=…` 로
// 보내고, 로그인이 끝나면 쿼리까지 그대로 여기로 돌아온다. 누가 허락하는지는 로그인
// 쿠키가 정한다 — 이 화면은 무엇을 허락하는지 보여주고 「허락」·「거절」을 받는다.
//
// 쿼리를 읽는 서버 컴포넌트라 요청마다 그린다.
import { PageShell } from "@/app/components/ui";
import { AUTHORIZE_PARAM_NAMES, type AuthorizeParams } from "@/lib/connected-apps/api";

import { ConsentPanel } from "./consent-panel";

export const dynamic = "force-dynamic";

export default async function AuthorizePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = Object.fromEntries(
    AUTHORIZE_PARAM_NAMES.map((name) => {
      const value = raw[name];
      return [name, typeof value === "string" ? value : ""];
    }),
  ) as AuthorizeParams;

  return (
    <PageShell>
      <ConsentPanel params={params} />
    </PageShell>
  );
}
