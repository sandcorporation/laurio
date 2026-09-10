// 가입 링크 미리보기·가입 (#280).
import { backendJson } from "@/lib/backend/client";

export type JoinPreview = {
  class_name: string;
  instructor_email: string;
  problem_count: number;
  participant_count: number;
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
