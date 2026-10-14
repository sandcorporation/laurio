// `/classes/{id}/members` 는 참여자 탭으로 합쳐졌다(#634) — 예전 주소로 들어온 링크·북마크를
// 탭으로 돌려보낸다.
import { redirect } from "next/navigation";

import { detailTabHref } from "@/lib/classes/detail-tab";

export default async function MembersRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(detailTabHref(Number(id), "participants"));
}
