// 참여자 명단·내보내기 백엔드 호출 (#281). 공유 클라이언트 위에 선다(#462).
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type MemberRow = {
  id: number;
  display_name: string;
  joined_at: string;
  expelled: boolean;
  is_instructor: boolean;
};

export function expelMember(classId: number, memberId: number): Promise<ApiResult<MemberRow>> {
  return bffClient.post<MemberRow>(
    `/api/backend/classroom/classes/${classId}/members/${memberId}/expel`,
  );
}
