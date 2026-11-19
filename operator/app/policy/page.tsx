// 정책 화면은 설정 화면의 「수수료·세금」 탭으로 옮겼다(#1041) — 옛 링크·북마크는 새 주소로 돌린다.
import { redirect } from "next/navigation";

export default function PolicyPage() {
  redirect("/settings?tab=fees");
}
