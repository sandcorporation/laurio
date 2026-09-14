// 비로그인 강사를 위한 소개 랜딩(#395, #391 Implementation Decisions
// 「강의실 랜딩」). `app/page.tsx`가 로그인 쿠키가 없을 때 그린다.
//
// **서버 컴포넌트다 — 클라이언트 지시어를 붙이면 안 된다**(ADR-0017 위험 1).
// 자바스크립트를 끈 요청에도 이 내용이 HTML 에 그대로 있어야 색인이 된다.
//
// **문구는 CONTEXT.md 를 따른다**(클래스·문제·체크리스트·통과·채점 지침) —
// 「강의실」·「과제」같은 접힌 낱말을 쓰지 않는다(CONTEXT.md 「클래스」절
// Avoid 목록). 비용·OpenAI 키 안내는 넣지 않는다(#391 Implementation
// Decisions — 강사가 직접 내는 비용이라 랜딩에서 미리 겁줄 이유가 없다).
import Link from "next/link";

import { Badge, Card, PageShell, buttonClass } from "@/app/components/ui";

export const LANDING_TITLE = "Codemit 클래스 — AI가 채점하는 코드 문제";
export const LANDING_DESCRIPTION =
  "문제를 내고 가입 링크로 참여자를 부르면, 제출할 때마다 AI가 체크리스트 항목별로 채점해 통과 여부를 보여줍니다.";

const STEPS = [
  {
    title: "체크리스트 있는 문제 만들기",
    body: "클래스를 열고 문제마다 통과 조건이 되는 체크리스트를 답니다.",
  },
  {
    title: "가입 링크로 참여자 부르기",
    body: "링크 하나로 계정이 없는 사람도 이름만 정하면 바로 참여합니다.",
  },
  {
    title: "제출하면 AI가 항목별로 판정",
    body: "제출마다 체크리스트 항목별로 채점되고, 통과 여부가 바로 보입니다.",
  },
];

const FEATURES = [
  { title: "채점 지침", body: "엄격·보통·관대 중 고르거나 직접 쓴 기준으로 얼마나 글자 그대로 따질지 정합니다." },
  { title: "항목별 판정 근거", body: "체크리스트 항목마다 왜 통과했는지, 왜 아닌지 이유가 함께 보입니다." },
  { title: "새로고침 없는 제출 현황", body: "참여자가 제출하면 강사 화면이 새로고침 없이 그대로 갱신됩니다." },
  { title: "문제·클래스 템플릿", body: "만든 문제나 클래스를 통째로 공개해 다른 강사가 가져다 쓸 수 있습니다." },
  { title: "카카오 로그인", body: "따로 가입 절차 없이 카카오 계정으로 바로 시작합니다." },
];

export function Landing() {
  return (
    <PageShell>
      <div className="flex flex-col gap-12 py-6">
        <section className="flex flex-col gap-5">
          <Badge>클래스</Badge>
          <h1
            data-testid="classroom-landing-heading"
            className="max-w-[640px] text-[28px] font-semibold leading-tight tracking-[-0.01em] sm:text-[34px]"
          >
            문제를 내면, AI가 체크리스트로 채점합니다
          </h1>
          <p className="max-w-[560px] text-[15px] leading-relaxed text-ink/70">{LANDING_DESCRIPTION}</p>
          <div>
            <Link
              href="/login?next=/classes/new"
              data-testid="classroom-landing-cta"
              className={buttonClass("primary")}
            >
              클래스 만들기
            </Link>
          </div>
        </section>

        <section className="flex flex-col gap-4">
          <h2 className="text-[13px] font-semibold tracking-[0.02em] text-ink/60">쓰는 법</h2>
          <ol className="grid gap-4 sm:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <Card className="flex h-full flex-col gap-2 p-4">
                  <span className="font-mono text-[12px] text-ink/45">{`0${index + 1}`}</span>
                  <span className="text-[14.5px] font-semibold">{step.title}</span>
                  <span className="text-[13px] leading-relaxed text-ink/60">{step.body}</span>
                </Card>
              </li>
            ))}
          </ol>
        </section>

        <section className="flex flex-col gap-4">
          <h2 className="text-[13px] font-semibold tracking-[0.02em] text-ink/60">기능</h2>
          <ul className="grid gap-4 sm:grid-cols-2">
            {FEATURES.map((feature) => (
              <li key={feature.title}>
                <Card className="flex h-full flex-col gap-1.5 p-4">
                  <span className="text-[14.5px] font-semibold">{feature.title}</span>
                  <span className="text-[13px] leading-relaxed text-ink/60">{feature.body}</span>
                </Card>
              </li>
            ))}
          </ul>
        </section>

        <p
          data-testid="classroom-landing-participant-note"
          className="border-t border-rule pt-6 text-[13px] text-ink/60"
        >
          가입 링크를 받았다면 그 링크로 들어오세요.
        </p>
      </div>
    </PageShell>
  );
}
