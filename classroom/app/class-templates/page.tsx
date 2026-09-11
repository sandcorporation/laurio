// `/class-templates` 자체는 목록 화면이 아니다(#350) — 공유 코드가 붙은
// `[shareCode]/page.tsx` 만 있다. 클래스 템플릿 목록은 `/templates` 의 「클래스」
// 탭에 이미 있으므로(`app/templates/page.tsx`) 새 목록을 만드는 대신 그 탭으로
// 돌려보낸다 — 같은 사실을 두 곳에 두면 갈라진다.
import { redirect } from "next/navigation";

export default function ClassTemplatesIndexRedirect() {
  redirect("/templates?kind=class");
}
