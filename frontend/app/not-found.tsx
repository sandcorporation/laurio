// 주소를 잘못 친 사람이 보던 화면 — 프레임워크 기본 404(영어) (#348). Next 가
// 일치하는 라우트를 못 찾을 때, 그리고 어느 페이지든 `notFound()` 를 부를 때
// 이 화면으로 온다(가장 가까운 상위 세그먼트에 `not-found.tsx` 가 없으면 여기까지
// 올라온다 — `app/contests/[id]/page.tsx` 의 `notFound()` 가 그 예다). 권한이
// 없어 못 보는 것과 아예 없는 것을 여기서 가르지 않는다, 둘 다 같은 문장으로 나온다.
import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-2xl p-10">
      <h1 className="text-2xl font-semibold" data-testid="not-found-heading">
        페이지를 찾을 수 없습니다
      </h1>
      <p className="mt-3 text-sm leading-relaxed text-ink/60">
        주소가 바뀌었거나, 존재하지 않거나, 볼 수 없는 페이지입니다.
      </p>
      <p className="mt-6">
        <Link
          href="/"
          data-testid="not-found-home-link"
          className="inline-flex w-fit items-center rounded-sm border border-ink bg-ink px-6 py-2.5 text-sm font-medium text-paper hover:bg-ink/90"
        >
          홈으로
        </Link>
      </p>
    </main>
  );
}
