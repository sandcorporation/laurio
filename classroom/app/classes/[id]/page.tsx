"use client";

// 클래스 상세 (#278). 이름과 만든 날짜만 보여준다 — 문제 목록은 #282가 이
// 화면에 이어 붙인다. 남의 클래스는 백엔드가 404를 주므로 그대로 "찾을 수
// 없다"로 보여준다(존재를 알려주지 않는다).
import { useParams } from "next/navigation";

import { useClass } from "@/lib/classes/use-class";

export default function ClassDetailPage() {
  const params = useParams<{ id: string }>();
  const classId = Number(params.id);
  const state = useClass(classId);

  if (state.status === "loading") {
    return (
      <main>
        <p data-testid="classroom-detail-loading">불러오는 중...</p>
      </main>
    );
  }

  if (state.status === "notFound") {
    return (
      <main>
        <h1 data-testid="classroom-detail-not-found">클래스를 찾을 수 없습니다</h1>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main>
        <p data-testid="classroom-detail-error">클래스 정보를 불러오지 못했습니다.</p>
      </main>
    );
  }

  return (
    <main>
      <h1 data-testid="classroom-detail-heading">{state.classroom.name}</h1>
      <p data-testid="classroom-detail-created-at">
        {new Date(state.classroom.created_at).toLocaleDateString("ko-KR")} 만듦
      </p>
    </main>
  );
}
