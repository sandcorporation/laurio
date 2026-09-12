// 주소를 잘못 친 사람이 보던 화면 — 프레임워크 기본 404(영어) (#348). Next 가
// 일치하는 라우트를 못 찾을 때, 그리고 어느 페이지든 `notFound()` 를 부를 때
// 이 화면으로 온다(가장 가까운 상위 세그먼트에 `not-found.tsx` 가 없으면 여기까지
// 올라온다). `classes/[id]/page.tsx` 의 「클래스를 찾을 수 없습니다」처럼 이미 쓰던
// 말투를 그대로 따른다 — 권한이 없어 못 보는 것과 아예 없는 것을 여기서 가르지
// 않는다, 둘 다 같은 문장으로 나온다.
import Link from "next/link";

import { PageShell, buttonClass } from "@/app/components/ui";

export default function NotFound() {
  return (
    <PageShell>
      <h1 data-testid="not-found-heading" className="text-[22px] font-semibold">
        페이지를 찾을 수 없습니다
      </h1>
      <p className="mt-3 text-[13.5px] leading-relaxed text-ink/60">
        주소가 바뀌었거나, 존재하지 않거나, 볼 수 없는 페이지입니다.
      </p>
      <p className="mt-6">
        <Link href="/" data-testid="not-found-home-link" className={buttonClass("secondary")}>
          홈으로
        </Link>
      </p>
    </PageShell>
  );
}
