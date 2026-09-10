// 참여자 명단·내보내기 백엔드 호출 (#281).
import { backendJson } from "@/lib/backend/client";

export type MemberRow = {
  id: number;
  display_name: string;
  joined_at: string;
  expelled: boolean;
  is_instructor: boolean;
};

export function fetchMembers(classId: number): Promise<MemberRow[]> {
  return backendJson<MemberRow[]>(`/classroom/classes/${classId}/members`);
}

export function expelMember(classId: number, memberId: number): Promise<MemberRow> {
  return backendJson<MemberRow>(`/classroom/classes/${classId}/members/${memberId}/expel`, {
    method: "POST",
  });
}
