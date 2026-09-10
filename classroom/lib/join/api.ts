// 가입 링크 미리보기·가입 (#280).
import { backendJson } from "@/lib/backend/client";

export type JoinPreview = {
  class_name: string;
  instructor_email: string;
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
