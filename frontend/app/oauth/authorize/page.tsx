// 공모전 MCP 의 동의 화면 (#870, ADR-0070) — OAuth 인가 엔드포인트다.
//
// claude.ai 같은 앱이 사용자의 브라우저를 이 주소로 보낸다(`client_id`·`redirect_uri`·PKCE·
// `state`·`resource`). 로그인하지 않았으면 middleware.ts 가 `/login?next=…` 로 보내고, 로그인이
// 끝나면 쿼리까지 그대로 여기로 돌아온다. 누가 허락하는지는 로그인 쿠키가 정한다. 개최 권한이
// 없는 사람은 백엔드가 403 으로 거절하고, 이 화면은 그 이유를 보여준다.
import { PageShell } from "@/app/components/ui";
import { pickAuthorizeParams } from "@/lib/connected-apps/format";

import { ConsentPanel } from "./consent-panel";

export const dynamic = "force-dynamic";

export default async function AuthorizePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = pickAuthorizeParams(await searchParams);
  return (
    <PageShell>
      <ConsentPanel params={params} />
    </PageShell>
  );
}
