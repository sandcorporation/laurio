"use client";

// 채점 키 알림의 도착점(#1426) — 역할을 읽어 소유자는 설정의 채점 연결로, 공동 강사는 클래스 화면으로 보낸다.
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AccessNotice } from "@/app/components/AccessNotice";
import { ErrorNote, PageShell } from "@/app/components/ui";
import { scoringKeyDestination } from "@/lib/classes/scoring-key-destination";
import { useClass } from "@/lib/classes/use-class";

export default function ScoringKeyRedirectPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const router = useRouter();
  const { state, reload } = useClass(classId);
  const role = state.status === "ready" ? state.classroom.role : null;

  useEffect(() => {
    if (role) router.replace(scoringKeyDestination(classId, role));
  }, [role, classId, router]);

  if (state.status === "notFound") {
    return (
      <PageShell>
        <AccessNotice
          page="class"
          classId={classId}
          testId="scoring-key-not-found"
          retry={{ reload, turns: [state] }}
        />
      </PageShell>
    );
  }
  if (state.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="scoring-key-error">클래스 정보를 불러오지 못했습니다.</span>
        </ErrorNote>
      </PageShell>
    );
  }
  return (
    <PageShell>
      <p data-testid="scoring-key-loading" className="text-[13.5px] text-ink/45">불러오는 중...</p>
    </PageShell>
  );
}
