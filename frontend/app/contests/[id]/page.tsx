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

import { Badge, PageHeader, PageShell } from "@/app/components/ui";
import { fetchContest, type ContestImage, type Requirement } from "@/lib/api/contests";
import { formatDday, formatPrize, formatSubmissionCount, isImminent } from "@/lib/contest-format";

import { SponsorJudgingEntry } from "./judging-entry";
import { SubmitCta } from "./submit-cta";
import { ContestViewBeacon } from "./view-beacon";

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
    return { title: "공모전을 찾을 수 없습니다 — Codemit" };
  }

  const description =
    contest.description.trim().length > 0
      ? contest.description
      : `상금 ${formatPrize(contest.prize)}원 · 마감 ${formatDday(contest.deadline_at)}`;

  // OG 이미지는 `opengraph-image.tsx`(Next 파일 컨벤션, app/contests/[id]/ 아래)가
  // 이 Contest 제목으로 매번 새로 그려 자동으로 이 메타데이터에 연결한다 — 여기서
  // 수동으로 images 를 채우지 않는다.
  return {
    title: `${contest.title} — Codemit`,
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
    <PageShell>
      <ContestViewBeacon contestId={contest.id} />
      <div className="flex flex-col gap-8">
        <PageHeader
          eyebrow={contest.category.name}
          title={contest.title}
          description={
            contest.deliverable_types.length > 0 ? (
              <span className="flex flex-wrap gap-1.5">
                {contest.deliverable_types.map((dt) => (
                  <Badge key={dt.id}>{dt.name}</Badge>
                ))}
              </span>
            ) : undefined
          }
          actions={
            contest.status === "closed" || contest.is_underfunded ? (
              <>
                {contest.status === "closed" && <Badge>마감된 공모전 — 데모·영상 공개</Badge>}
                {contest.is_underfunded && <Badge tone="attention">상금미달</Badge>}
              </>
            ) : undefined
          }
        />

        <section className="grid grid-cols-3 gap-6 border-b border-rule pb-6">
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
          <div className="flex flex-col gap-1">
            <span className="text-xs tracking-wide text-ink/60">참가작</span>
            {/* 백엔드가 낸 숫자(ContestOut.submission_count, #106)를 그대로
                읽되, 0은 "0"이 아니라 문구로 낸다 — formatSubmissionCount가 그
                경계선이고, 화면은 이 함수 말고 다시 세지 않는다. */}
            <span
              data-testid="submission-count"
              data-submission-count={contest.submission_count}
              className={`font-mono font-medium ${
                contest.submission_count === 0 ? "text-base text-ink/60" : "text-2xl"
              }`}
            >
              {formatSubmissionCount(contest.submission_count)}
            </span>
          </div>
        </section>

        {/* 자기 공모전을 연 Sponsor 를 심사 화면으로 보내는 진입점 (#226). */}
        <SponsorJudgingEntry contestId={contest.id} />

        {/* 제출 화면으로 가는 주 CTA (#164) — 공개 상세에 참가·제출로 갈 길이
            하나도 없던 문제 자체를 고친다. `contest.status === "published"`는
            백엔드의 `Contest.Status.SUBMITTABLE`(draft·closed·awarded·
            judging_ended 전부 제외, "status 상 제출을 받는가")과 같은 기준이다 —
            다른 상태에서는 제출 화면에 가도 할 것이 없으므로 여기서 아예
            감춘다. 본인확인·마감 시각은 제출 화면(app/console/contests/
            [contestId]/submit/page.tsx)이 스스로 안내하므로 이 CTA는 그 조건을
            다시 구현하지 않는다 — 이미 제출한 사람에게도 같은 링크가 맞다(그
            화면이 수정도 겸한다). 다만 문구는 다르다(#245) — 누르면 자기가 낸
            것을 덮어쓴다는 것이 눌리기 전에 드러나야 한다. */}
        {/* 마감 뒤에도 이 CTA 를 "제출물 보기"로 남기지 않기로 정했다(#258).
            이 페이지는 SSR 공개 표면이라 `ContestOut` 에 `next_action` 이 없고
            (`is_owner`·`has_own_submission` 둘뿐, ADR-0015), `SubmitCta` 는
            "제출하러/수정하러 가기" 둘 중 하나만 말할 수 있다 — 마감 뒤에도
            이 조건 그대로 노출하면 채점 대기·이의 기간처럼 실제로는 고칠 수
            없는 상태에서 "제출물 수정하러 가기"라고 말하게 되어, 이 티켓이
            「내 참가 현황」에서 고친 바로 그 거짓말을 여기서 다시 만든다.
            `next_action` 기반 문구를 여기 들이려면 공개 스키마에 인증
            구역에서만 뜻이 있는 값을 얹어야 하는데, 그건 이 티켓의 울타리
            (진입점만 고친다) 밖이다. 로그인한 참가자에게는 「내 참가 현황」이
            이미 정확한 문구로 같은 화면을 연결하므로, 공개 상세는 마감 전
            진입점 하나로 남긴다. */}
        {contest.status === "published" && (
          <section className="border-b border-rule pb-6">
            <SubmitCta contestId={contest.id} />
          </section>
        )}

        {/* 참고 이미지 (#234, ADR-0032) — 서버 컴포넌트가 그대로 <img>로 그린다.
            JS 를 끄면 이 태그가 사라지는 게 아니라 그리는 코드 자체가 사라지므로
            (`"use client"` 가 이 파일에 없다), 「공개 페이지가 실제로 서버
            렌더링되는가」(CLAUDE.md 「남길 것」1번)를 이 섹션이 그대로 물려받는다.
            이미지가 없으면 섹션 자체를 그리지 않는다 — 빈 자리가 의도된 것으로
            읽힌다(spec #225 user story 15). 원본만 있다(#235가 파생본을 얹는다)
            — url 은 백엔드가 이미 조립한 서명 없는 공개 주소이므로 화면은 그 값을
            그대로 쓴다. */}
        {contest.images.length > 0 && (
          <section className="flex flex-col gap-3 border-b border-rule pb-6">
            <h2 className="text-sm font-medium">참고 이미지</h2>
            <ul data-testid="contest-images" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {contest.images.map((image) => (
                <ContestImageThumb key={image.id} image={image} />
              ))}
            </ul>
          </section>
        )}

        {contest.description && (
          <section className="flex flex-col gap-2 border-b border-rule pb-6">
            <h2 className="text-sm font-medium">요구사항</h2>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink/80">
              {contest.description}
            </p>
          </section>
        )}

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium">요구사항 체크리스트</h2>
          {contest.requirements.length === 0 ? (
            <p className="text-sm text-ink/60">등록된 요구사항이 없습니다.</p>
          ) : (
            <ul className="flex flex-col">
              {contest.requirements.map((requirement) => (
                <RequirementRow key={requirement.id} requirement={requirement} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </PageShell>
  );
}

function ContestImageThumb({ image }: { image: ContestImage }) {
  return (
    <li>
      {/* 원본을 새 탭에서 그대로 연다(#234 AC "전체 크기로 열어 세부를 읽는다")
          — 별도 라이트박스 없이 <a target="_blank">로 충분하다. 좁은 화면에서
          가로 스크롤을 만들지 않도록 썸네일은 항상 카드 너비를 넘지 않는다. */}
      <a href={image.url} target="_blank" rel="noreferrer" data-testid="contest-image-link">
        {/* eslint-disable-next-line @next/next/no-img-element -- 오브젝트 키가 uuid라 캐시
            무효화가 필요 없고(ADR-0032), next/image의 원격 최적화는 STORAGE_IMAGES_BASE_URL
            을 배포마다 remotePatterns에 등록해야 해 배포 설정을 하나 더 늘린다. */}
        <img
          src={image.url}
          alt=""
          loading="lazy"
          className="aspect-video w-full rounded-sm border border-rule object-cover"
        />
      </a>
    </li>
  );
}

function RequirementRow({ requirement }: { requirement: Requirement }) {
  const isRequired = requirement.grade === "required";
  return (
    <li
      data-requirement-grade={requirement.grade}
      className="flex items-center gap-3 border-b border-rule py-3"
    >
      <Badge tone={isRequired ? "attention" : "neutral"}>{isRequired ? "필수" : "선택"}</Badge>
      <span className="text-sm">{requirement.text}</span>
    </li>
  );
}
