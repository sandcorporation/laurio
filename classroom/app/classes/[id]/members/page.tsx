"use client";

// 참여자 명단 (#281, 스타일 #298). 클래스에서 불릴 이름으로 보여주고, 내보내도
// 행을 지우지 않고 "내보냄"으로 표시한다 — 지우면 그 사람이 낸 제출물이 이름을
// 잃는다. 강사 본인이 참여자로 들어와 있으면 그렇게 구별된다(집계에서 빠진다).
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Note,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { useMembers } from "@/lib/members/use-members";

export default function MembersPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const { state, expel } = useMembers(classId);

  if (state.status === "loading") {
    return (
      <PageShell>
        <p data-testid="members-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  if (state.status === "notFound") {
    return (
      <PageShell>
        <h1 data-testid="members-not-found" className="text-[22px] font-semibold">
          클래스를 찾을 수 없습니다
        </h1>
      </PageShell>
    );
  }

  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="members-error">참여자 명단을 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }

  const counted = state.members.filter((m) => !m.expelled && !m.is_instructor).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="클래스"
        title="참여자 명단"
        titleTestId="members-heading"
        description={`달성률을 셀 때 세는 참여자는 ${counted}명입니다 — 강사 본인과 내보낸 사람은 빠집니다.`}
        actions={
          <Link href={`/classes/${classId}`} data-testid="members-back-link" className={buttonClass()}>
            클래스로 돌아가기
          </Link>
        }
      />

      <div className="flex flex-col gap-4">
        {state.expelError ? (
          <ErrorNote>
            <span data-testid="members-expel-error">내보내지 못했습니다. 다시 시도해주세요.</span>
          </ErrorNote>
        ) : null}

        {state.members.length === 0 ? (
          <Card>
            <EmptyState>
              <span data-testid="members-empty-state">
                아직 참여자가 없습니다. 클래스 상세의 가입 링크를 공유해 보세요.
              </span>
            </EmptyState>
          </Card>
        ) : (
          <Card>
            <ul data-testid="members-list" className="divide-y divide-rule">
              {state.members.map((member) => (
                <li
                  key={member.id}
                  data-testid={`member-row-${member.id}`}
                  className="flex items-center justify-between gap-4 px-4 py-3.5"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span
                      data-testid={`member-row-${member.id}-name`}
                      className={`text-[14px] ${member.expelled ? "text-ink/40 line-through" : ""}`}
                    >
                      {member.display_name}
                    </span>
                    <span
                      data-testid={`member-row-${member.id}-joined-at`}
                      className="shrink-0 text-[12px] text-ink/45"
                    >
                      {new Date(member.joined_at).toLocaleDateString("ko-KR")} 가입
                    </span>
                    {member.is_instructor ? (
                      <span data-testid={`member-row-${member.id}-instructor-badge`}>
                        <Badge>강사 본인 · 집계 제외</Badge>
                      </span>
                    ) : null}
                    {member.expelled ? (
                      <span data-testid={`member-row-${member.id}-expelled-badge`}>
                        <Badge tone="attention">내보냄</Badge>
                      </span>
                    ) : null}
                  </div>
                  {member.expelled ? null : (
                    <button
                      type="button"
                      data-testid={`member-row-${member.id}-expel`}
                      onClick={() => expel(member.id)}
                      className={buttonClass("danger", "sm")}
                    >
                      내보내기
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}

        <Note>
          내보내도 이름과 지난 제출·판정은 그대로 남습니다. 다만 다시 가입하거나 제출할 수는
          없고, 달성률을 셀 때도 빠집니다.
        </Note>
      </div>
    </PageShell>
  );
}
