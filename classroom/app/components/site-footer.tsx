// 모든 페이지 아래에 서는 바닥글(#472). 개인정보처리방침·이용약관은 공개 앱
// (frontend/app/privacy, frontend/app/terms)에만 있다 — 강의실은 자기
// 로그인이 없어(ADR-0038) 공개 앱으로 안내만 하는 것과 같은 이유로, 이
// 문서도 새로 짓지 않고 공개 앱으로 링크만 보낸다. 손으로 관리되는 사본을
// 하나 더 만들면(워크스페이스 패키지를 새로 만드는 것과 같은 대가) 두 문서가
// 갈릴 때 로컬 게이트가 잡지 못한다 — 링크 하나면 그 위험 자체가 없다.
//
// 강의실 미들웨어(middleware.ts)를 고칠 필요가 없다 — 이 화면 자신의 경로가
// 아니라 다른 오리진으로 나가는 링크이므로 인증 구역 예외 목록에 넣을 것이
// 없다. `publicAppOrigin()`은 로그인 화면(app/login/page.tsx)이 이미 쓰는
// 것과 같은 함수다.
import { publicAppOrigin } from "@/lib/auth/public-app";

export function SiteFooter() {
  const origin = publicAppOrigin();

  return (
    <footer className="border-t border-rule bg-surface" data-testid="site-footer">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-4 gap-y-2 px-6 py-6 text-xs text-ink/60">
        <a href={`${origin}/privacy`} data-testid="footer-link-privacy" className="hover:text-ink">
          개인정보처리방침
        </a>
        <a href={`${origin}/terms`} data-testid="footer-link-terms" className="hover:text-ink">
          이용약관
        </a>
        <a
          href="https://sandcorp.co.kr/?utm_source=codemit&utm_medium=footer"
          target="_blank"
          rel="noopener"
          data-testid="footer-link-sandcorp"
          className="hover:text-ink"
        >
          Made by Sandcorp
        </a>
      </div>
    </footer>
  );
}
