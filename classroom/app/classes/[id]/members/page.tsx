"use client";

// 참여자 명단 (#281). 클래스에서 불릴 이름으로 보여주고, 내보내도 행을
// 지우지 않고 "내보냄"으로 표시한다. 강사 본인이 참여자로 들어와 있으면
// 그렇게 구별된다.
import Link from "next/link";
import { useParams } from "next/navigation";

import { useMembers } from "@/lib/members/use-members";

export default function MembersPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, expel } = useMembers(classId);

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="members-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="members-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="members-error">참여자 명단을 불러오지 못했습니다.</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="members-heading">참여자 명단</h1>
      <p>
        <Link href={`/classes/${classId}`} data-testid="members-back-link">
          클래스로 돌아가기
        </Link>
      </p>

      {state.expelError ? (
        <p data-testid="members-expel-error">내보내지 못했습니다. 다시 시도해주세요.</p>
      ) : null}

      {state.members.length === 0 ? (
        <p data-testid="members-empty-state">아직 참여자가 없습니다.</p>
      ) : (
        <ul data-testid="members-list">
          {state.members.map((member) => (
            <li key={member.id} data-testid={`member-row-${member.id}`}>
              <span data-testid={`member-row-${member.id}-name`}>{member.display_name}</span>
              {member.is_instructor ? (
                <span data-testid={`member-row-${member.id}-instructor-badge`}> · 강사 본인</span>
              ) : null}
              {member.expelled ? (
                <span data-testid={`member-row-${member.id}-expelled-badge`}> · 내보냄</span>
              ) : (
                <button
                  type="button"
                  data-testid={`member-row-${member.id}-expel`}
                  onClick={() => expel(member.id)}
                >
                  내보내기
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
