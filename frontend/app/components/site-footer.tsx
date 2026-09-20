// 모든 페이지 아래에 서는 바닥글(#472). 개인정보처리방침·이용약관은 로그인
// 없이 누구나 닿아야 하는 공개 문서라(개인정보 보호법 제30조는 공개 자체를
// 의무로 정한다) 헤더처럼 이 레이아웃에서 한 번만 그린다 — 서버 컴포넌트라
// 인증 구역(app/console/**)을 포함해 어느 화면 아래 걸리든 서버에서 그려진다.
import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-rule bg-surface" data-testid="site-footer">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-4 gap-y-2 px-6 py-6 text-xs text-ink/60">
        <Link
          href="/privacy"
          data-testid="footer-link-privacy"
          className="hover:text-ink"
        >
          개인정보처리방침
        </Link>
        <Link href="/terms" data-testid="footer-link-terms" className="hover:text-ink">
          이용약관
        </Link>
      </div>
    </footer>
  );
}
