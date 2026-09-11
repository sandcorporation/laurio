// 가입 링크 미리보기·가입 (#280).
import { backendJson } from "@/lib/backend/client";

export type JoinPreview = {
  class_id: number;
  class_name: string;
  instructor_email: string;
  problem_count: number;
  participant_count: number;
  // 보관된 클래스인가(#294) — 참이면 화면이 가입 폼 대신 "끝났다" 안내를
  // 보여준다. 죽은 링크(404)와 달리 미리보기 자체는 그대로 온다.
  archived: boolean;
  // 로그인한 사람이 이미 이 클래스의 참여자인가(#300) — 내보내진 사람도
  // 참이다. 참이면 화면이 이름 입력 폼을 건너뛰고 곧장 문제 목록으로 보낸다.
  already_joined: boolean;
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
