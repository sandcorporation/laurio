import type { Metadata } from "next";

import { LANDING_DESCRIPTION } from "../landing-copy";
import type { JoinPreview } from "./api";

// 가입 링크(`/join/<코드>`)를 메신저·SNS 에 붙였을 때 뜨는 공유 카드(#788).
// 크롤러는 JS 를 돌리지 않으므로 서버가 만든 `<head>` 만 본다.
//
// **카드에 싣는 것은 클래스 이름과 열린 문제 수뿐이다.** 참여자 수·강사 이름·가입 여부는
// 싣지 않는다(개인정보·가입 상태) — 화면에는 지금처럼 보인다. 죽은 코드(404·보관)와 백엔드
// 실패는 이유를 가리지 않고 같은 일반 카드로 떨어진다.
export const GENERIC_JOIN_TITLE = "Codemit 클래스";

const SUFFIX = "Codemit 클래스";
// 카드 제목이 메신저에서 한 줄로 보이는 길이를 넘지 않게 이름만 자른다(접미사는 남긴다).
export const MAX_CLASS_NAME_LENGTH = 60;

const GRADING = "제출할 때마다 AI가 체크리스트 항목별로 채점합니다";

function card(title: string, description: string): Metadata {
  return {
    title,
    description,
    openGraph: { title, description, type: "website" },
    twitter: { card: "summary_large_image", title, description },
  };
}

export function joinShareMetadata(
  preview: Pick<JoinPreview, "class_name" | "open_problem_count" | "archived"> | null,
): Metadata {
  if (preview === null || preview.archived) {
    return card(GENERIC_JOIN_TITLE, LANDING_DESCRIPTION);
  }
  const chars = Array.from(preview.class_name.trim());
  const name =
    chars.length > MAX_CLASS_NAME_LENGTH
      ? `${chars.slice(0, MAX_CLASS_NAME_LENGTH).join("")}…`
      : chars.join("");
  if (name === "") return card(GENERIC_JOIN_TITLE, LANDING_DESCRIPTION);
  const count = preview.open_problem_count;
  const description = count > 0 ? `열린 문제 ${count}개 · ${GRADING}` : GRADING;
  return card(`${name} — ${SUFFIX}`, description);
}

const FETCH_TIMEOUT_MS = 3000;

// 서버에서 공개 미리보기를 부른다. 어떤 실패도(네트워크·타임아웃·404·모양 불일치) 던지지
// 않고 `null` — 페이지를 500 으로 만들지 않는다. 코드 재발급 뒤 옛 카드가 남지 않게 캐시하지 않는다.
export async function fetchJoinPreviewForCard(
  baseUrl: string,
  code: string,
): Promise<JoinPreview | null> {
  try {
    const res = await fetch(`${baseUrl}/api/classroom/join/${encodeURIComponent(code)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as JoinPreview;
    if (typeof body?.class_name !== "string") return null;
    return body;
  } catch {
    return null;
  }
}
