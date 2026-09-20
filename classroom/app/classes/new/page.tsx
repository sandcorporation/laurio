"use client";

// 새 클래스 만들기 (#278, 스타일 #298). 이름만 받는다 — 가입 링크는 만들면
// 상세 화면에서 바로 나온다(#279).
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import {
  Card,
  ErrorNote,
  FieldLabel,
  INPUT_CLASS,
  PageHeader,
  PageShell,
  buttonClass,
} from "@/app/components/ui";
import { createClass } from "@/lib/classes/api";

export default function NewClassPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [instructorDisplayName, setInstructorDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await createClass(name.trim(), instructorDisplayName.trim());
    if (result.ok) {
      router.push(`/classes/${result.data.id}`);
    } else {
      setError(result.detail);
      setSubmitting(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="내 클래스"
        title="새 클래스"
        titleTestId="new-class-heading"
        description="만들고 나면 가입 링크가 바로 나옵니다. 그 링크를 받은 사람은 회원가입과 클래스 가입이 한 번에 끝납니다."
      />

      <Card className="max-w-[560px] p-5">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="class-name">
              <FieldLabel>클래스 이름</FieldLabel>
            </label>
            <input
              id="class-name"
              data-testid="new-class-name-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              className={INPUT_CLASS}
              placeholder="예: 프론트엔드 입문 3기"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="class-instructor-display-name">
              <FieldLabel>이 클래스에서 불릴 강사 이름</FieldLabel>
            </label>
            <input
              id="class-instructor-display-name"
              data-testid="new-class-instructor-display-name-input"
              value={instructorDisplayName}
              onChange={(event) => setInstructorDisplayName(event.target.value)}
              required
              className={INPUT_CLASS}
              placeholder="예: 김강사"
            />
            <span className="text-[11.5px] leading-relaxed text-ink/45">
              가입 미리보기에 이 이름으로 보입니다 — 계정 이름과 달라도 됩니다.
            </span>
          </div>
          <div>
            <button
              type="submit"
              data-testid="new-class-submit"
              disabled={submitting || name.trim() === "" || instructorDisplayName.trim() === ""}
              className={buttonClass("primary")}
            >
              {submitting ? "만드는 중..." : "만들기"}
            </button>
          </div>
          {error ? (
            <ErrorNote>
              <span data-testid="new-class-error">{error}</span>
            </ErrorNote>
          ) : null}
        </form>
      </Card>
    </PageShell>
  );
}
