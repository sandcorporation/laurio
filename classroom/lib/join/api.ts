// 가입 링크 미리보기·가입 (#280).
import { backendJson } from "@/lib/backend/client";

export type JoinPreview = {
  class_name: string;
  // 강사가 이 클래스에서 불릴 이름으로 정한 값(#299) — 강사 이메일은 더
  // 이상 여기 실리지 않는다. `null`이면(강사가 아직 정하지 않은 예전
  // 클래스) 화면이 이 줄 자체를 생략한다.
  instructor_display_name: string | null;
  problem_count: number;
  participant_count: number;
  // 보관된 클래스인가(#294) — 참이면 화면이 가입 폼 대신 "끝났다" 안내를
  // 보여준다. 죽은 링크(404)와 달리 미리보기 자체는 그대로 온다.
  archived: boolean;
};

export type JoinResult = {
  class_id: number;
  class_name: string;
  display_name: string;
};

export function fetchJoinPreview(code: string): Promise<JoinPreview> {
  return backendJson<JoinPreview>(`/classroom/join/${code}`);
}

export function joinClass(code: string, displayName: string): Promise<JoinResult> {
  return backendJson<JoinResult>(`/classroom/join/${code}`, {
    method: "POST",
    body: JSON.stringify({ display_name: displayName }),
  });
}
