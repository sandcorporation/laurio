"use client";

// 「시작하기」 카드(#633, 시안 v2) — 방금 연 클래스가 다음에 무엇을 할지 순서로 말한다: 채점 연결 →
// 첫 문제 → 가입 링크. 끝난 단계는 ✓ 이고 다음 단계의 버튼이 주 버튼이다. 셋이 다 끝나면 이 카드는
// 사라지고 그 자리에 「채점」 카드가 들어온다(`page.tsx`).
import Link from "next/link";
import { useState } from "react";

import { Card, CardHeader, buttonClass } from "@/app/components/ui";
import type { ClassRow } from "@/lib/classes/api";
import { describeConnection } from "@/lib/classes/scoring-status";

export type StartSteps = { connected: boolean; hasProblem: boolean; hasMember: boolean };

export function startSteps(classroom: Pick<ClassRow, "has_openai_key" | "problem_count" | "member_count">): StartSteps {
  return {
    connected: classroom.has_openai_key,
    hasProblem: classroom.problem_count > 0,
    hasMember: classroom.member_count > 0,
  };
}

function Step({
  n,
  title,
  detail,
  done,
  current,
  testId,
  action,
}: {
  n: number;
  title: string;
  detail?: string;
  done: boolean;
  current: boolean;
  testId: string;
  action?: React.ReactNode;
}) {
  return (
    <li data-testid={testId} data-done={done ? "true" : "false"} className="flex items-start gap-3.5 border-t border-rule px-4 py-3.5 first:border-t-0">
      {done ? (
        <span aria-label="끝남" className="flex h-[22px] w-[22px] shrink-0 items-center justify-center bg-verified text-[12px] text-paper">
          ✓
        </span>
      ) : (
        <span
          className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center border font-mono text-[12px] ${
            current ? "border-ink text-ink" : "border-rule text-ink/45"
          }`}
        >
          {n}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className={`text-[14px] font-medium ${done ? "text-ink/45" : ""}`}>{title}</div>
        {detail ? <div className="mt-0.5 truncate text-[12.5px] text-ink/60">{detail}</div> : null}
      </div>
      {!done && action ? <div className="shrink-0">{action}</div> : null}
    </li>
  );
}

export function GettingStartedCard({ classroom, joinUrl }: { classroom: ClassRow; joinUrl: string }) {
  const classId = classroom.id;
  const steps = startSteps(classroom);
  const [copied, setCopied] = useState(false);
  const isOwner = classroom.role === "owner";
  const currentStep = !steps.connected ? 1 : !steps.hasProblem ? 2 : 3;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(joinUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Card>
      <CardHeader title="시작하기" />
      <ol data-testid="getting-started">
        <Step
          n={1}
          title="채점 연결 넣기"
          detail={steps.connected ? describeConnection(classroom) : undefined}
          done={steps.connected}
          current={currentStep === 1}
          testId="getting-started-connect"
          action={
            // 연결은 소유자만 넣는다(#561) — 공동 강사에게는 갈 곳 없는 버튼을 보이지 않는다.
            isOwner ? (
              <Link
                href={`/classes/${classId}/settings#scoring-key`}
                data-testid="classroom-missing-api-key-settings-link"
                className={buttonClass(currentStep === 1 ? "primary" : "secondary", "sm")}
              >
                채점 연결 넣기
              </Link>
            ) : null
          }
        />
        <Step
          n={2}
          title="첫 문제 만들기"
          done={steps.hasProblem}
          current={currentStep === 2}
          testId="getting-started-problem"
          action={
            <Link
              href={`/classes/${classId}/problems/new`}
              data-testid="getting-started-new-problem"
              className={buttonClass(currentStep === 2 ? "primary" : "secondary", "sm")}
            >
              새 문제
            </Link>
          }
        />
        <Step
          n={3}
          title="가입 링크 공유하기"
          done={steps.hasMember}
          current={currentStep === 3}
          testId="getting-started-share"
          action={
            <button
              type="button"
              data-testid="getting-started-copy"
              onClick={copy}
              className={buttonClass(currentStep === 3 ? "primary" : "secondary", "sm")}
            >
              {copied ? "복사됨" : "복사"}
            </button>
          }
        />
      </ol>
    </Card>
  );
}
