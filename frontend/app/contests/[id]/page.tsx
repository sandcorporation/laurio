// FE-05(#30) — 공개 SSR 공모전 상세. `GET /api/contests/{contest_id}` 도 auth=None
// 공개 표면이다(ADR-0015) — 서버 컴포넌트가 백엔드에서 요구사항·Requirement 체크리스트·
// Prize·기한을 가져와 그대로 렌더링한다. 이 페이지는 클라이언트 컴포넌트 지시어를
// 붙이지 않는다.
//
// 마감된 Contest 도 그대로 보여준다(spec #25 — 마감은 결제 취소가 아니라 데모·영상이
// 공개되는 시점이다, ADR-0014). 존재하지 않거나 draft 인 Contest 는 백엔드가 이미
// 404 로 답하므로(contests.api.get_contest) `fetchContest` 가 null 을 돌려주는 자리에서
// `notFound()` 를 부른다 — draft 존재 여부를 응답 형태로 드러내지 않는다.
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { fetchContest, type Requirement } from "@/lib/api/contests";
import { formatDday, formatPrize, isImminent } from "@/lib/contest-format";

type Params = { id: string };

function parseContestId(raw: string): number | null {
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { id } = await params;
  const contestId = parseContestId(id);
  const contest = contestId === null ? null : await fetchContest(contestId);

  if (!contest) {
    return { title: "공모전을 찾을 수 없습니다 — Laurio" };
  }

  const description =
    contest.description.trim().length > 0
      ? contest.description
      : `상금 ${formatPrize(contest.prize)}원 · 마감 ${formatDday(contest.deadline_at)}`;

  // OG 이미지는 `opengraph-image.tsx`(Next 파일 컨벤션, app/contests/[id]/ 아래)가
  // 이 Contest 제목으로 매번 새로 그려 자동으로 이 메타데이터에 연결한다 — 여기서
  // 수동으로 images 를 채우지 않는다.
  return {
    title: `${contest.title} — Laurio`,
    description,
    openGraph: {
      title: contest.title,
      description,
      type: "website",
    },
  };
}

export default async function ContestDetailPage({ params }: { params: Promise<Params> }) {
  const { id } = await params;
  const contestId = parseContestId(id);
  const contest = contestId === null ? null : await fetchContest(contestId);

  if (!contest) {
    notFound();
  }

  const imminent = isImminent(contest.deadline_at);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 bg-paper p-10 text-ink">
      <header className="flex flex-col gap-3 border-b border-rule pb-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink/60">
          <span>{contest.category.name}</span>
          {contest.status === "closed" && (
            <span className="border border-rule px-1.5 py-0.5">마감된 공모전 — 데모·영상 공개</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{contest.title}</h1>
          {contest.is_underfunded && <UnderfundedBadge />}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {contest.deliverable_types.map((dt) => (
            <span key={dt.id} className="border border-rule px-1.5 py-0.5 text-xs text-ink/70">
              {dt.name}
            </span>
          ))}
        </div>
      </header>

      <section className="grid grid-cols-2 gap-6 border-b border-rule pb-6">
        <div className="flex flex-col gap-1">
          <span className="text-xs tracking-wide text-ink/60">상금</span>
          <span
            className={`font-mono text-2xl font-medium ${contest.is_underfunded ? "text-attention" : ""}`}
          >
            {formatPrize(contest.prize)}원
          </span>
          {contest.is_underfunded && (
            <span className="text-xs text-ink/60">
              최소 제안 상금 합계 {formatPrize(contest.required_minimum_prize)}원에 미달합니다.
              참가를 막지는 않습니다.
            </span>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs tracking-wide text-ink/60">마감</span>
          <span
            data-testid="deadline"
            className={`font-mono text-2xl font-medium ${imminent ? "text-attention" : ""}`}
          >
            {formatDday(contest.deadline_at)}
          </span>
          <span className="font-mono text-xs text-ink/60">
            {new Date(contest.deadline_at).toLocaleString("ko-KR")}
          </span>
        </div>
      </section>

      {contest.description && (
        <section className="flex flex-col gap-2 border-b border-rule pb-6">
          <h2 className="text-sm font-medium">요구사항</h2>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/80">
            {contest.description}
          </p>
        </section>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Requirement 체크리스트</h2>
        {contest.requirements.length === 0 ? (
          <p className="text-sm text-ink/60">등록된 Requirement 가 없습니다.</p>
        ) : (
          <ul className="flex flex-col">
            {contest.requirements.map((requirement) => (
              <RequirementRow key={requirement.id} requirement={requirement} />
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function RequirementRow({ requirement }: { requirement: Requirement }) {
  const isRequired = requirement.grade === "required";
  return (
    <li
      data-requirement-grade={requirement.grade}
      className="flex items-center gap-3 border-b border-rule py-3"
    >
      <span
        className={
          isRequired
            ? "border border-attention px-1.5 py-0.5 text-[11px] font-medium text-attention"
            : "border border-rule px-1.5 py-0.5 text-[11px] text-ink/60"
        }
      >
        {isRequired ? "필수" : "선택"}
      </span>
      <span className="text-sm">{requirement.text}</span>
    </li>
  );
}

function UnderfundedBadge() {
  return (
    <span className="inline-flex items-center gap-1 border border-attention px-1.5 py-0.5 text-[10.5px] font-medium text-attention">
      상금미달
    </span>
  );
}
