// 공개 표면의 현관(#93, spec #92). FE-02(#27)가 토큰 배선을 증명하려고 세운
// 자리표시 페이지였고, 그 주석은 "실제 공개 표면은 FE-04(#29)가 이 자리를
// 대신한다"고 적어 뒀었다 — 하지만 #29 는 `/contests` 를 새로 만들었을 뿐 이
// 자리는 그대로 남겨졌다. #93 이 그 약속을 늦게라도 지켰다.
//
// 이 티켓(#94, spec #92)이 얹는 것은 **큐레이션**이다 — 공모전을 한 덩어리
// 목록이 아니라 진행중·마감임박·심사중·완료 네 묶음으로 갈라 보여준다.
// **묶음 판정은 백엔드가 한다**(`GET /api/contests/home`,
// `contests.curation.home_bucket_for`) — 이 페이지는 `status`·`deadline_at`을
// 다시 보고 재파생하지 않는다. 화면이 원시 상태에서 재파생하다 새 상태가
// 조용히 어느 분기에도 안 걸리는 것을 이 저장소가 반복해서 겪었기 때문이다
// (`submissions.participation`·`contests.sponsorship`과 같은 이유).
//
// 각 묶음은 항상 나온다 — 비어 있어도 섹션째 사라지지 않고 "비어 있다"고
// 말한다(#94 인수조건). 헤더의 「공모전」 링크와 각 묶음의 "전체 보기"는 모두
// 필터·정렬·페이지네이션이 있는 `/contests`(#39)로 안내한다 — 홈은 큐레이션이고
// 목록은 탐색이라 그 경계를 손대지 않는다.
//
// 서버 컴포넌트다. 클라이언트 지시어가 붙으면 안 된다(ADR-0015) — 이 페이지는
// 색인 대상 공개 표면이다.
// **이 페이지는 요청 시점에 렌더된다.** Next 는 기본적으로 이 라우트를 정적
// 프리렌더하려 하고, 그러면 `pnpm build` 중에 백엔드를 치다가 ECONNREFUSED 로
// **빌드가 통째로 실패한다**(`Export encountered an error on /page: /`). 빌드
// 시점에는 백엔드가 없다 — 프로덕션 이미지는 컨테이너 밖에서 혼자 구워진다.
//
// `cache: "no-store"` 만으로는 부족했다. 명시적으로 표시한다.
export const dynamic = "force-dynamic";

// canonical(#394) — 쿼리가 붙은 주소(있다면)가 따로 색인되지 않게 이 경로
// 자체를 정식 주소로 선언한다. 제목은 없다 — 루트 레이아웃의 `default`
// ("Codemit")를 그대로 쓴다(`app/layout.tsx`의 title 템플릿 주석 참고).
export const metadata: Metadata = { alternates: { canonical: "/" } };

import type { Metadata } from "next";
import Link from "next/link";

import { Badge, EmptyState, PageHeader, PageShell } from "@/app/components/ui";
import { fetchHomeCuration, type Contest, type HomeCurationGroup } from "@/lib/api/contests";
import {
  formatPrize,
  formatSubmissionCount,
  remainingTimeIsImminent,
  remainingTimeLabel,
} from "@/lib/contest-format";
import { contestProductEnabled } from "@/lib/contest-switch";
import { HOME_BUCKET_EMPTY_MESSAGES, HOME_BUCKET_LABELS } from "@/lib/home-curation";

export default async function Home() {
  // 공모전 제품 스위치(#271)가 꺼지면 이 홈은 공모전 큐레이션을 그리지 않는다 —
  // 백엔드의 `GET /api/contests/home`도 같은 스위치로 404를 내므로(단일 집행자
  // 원칙), 여기서 미리 갈리지 않으면 이 요청이 그대로 새고 홈 전체가 깨진
  // 화면으로 보인다.
  //
  // **그 자리에 아무것도 두지 않는다**(#359, spec #358). 과제가 걷히기 전에는
  // "초대받은 과제만 이용할 수 있습니다"가 여기 있었다 — 과제 자체가 없어진
  // 지금 그 문장은 거짓이다. 강의실로 보내는 안내도 두지 않는다: 공개 앱과
  // 강의실은 로그인을 공유하지 않고(ADR-0038), 여기서 강의실을 안내하면 그
  // 화면이 실제로 갖지 않은 관계를 지어내게 된다. 빈 화면이 합의된 답이다.
  if (!contestProductEnabled()) {
    return (
      <PageShell>
        <PageHeader title="Codemit" />
      </PageShell>
    );
  }

  const groups = await fetchHomeCuration();

  return (
    <PageShell>
      <div className="flex flex-col gap-8">
        <PageHeader
          title="Codemit"
          description="발주자가 상금을 걸고 요구사항을 공개하면, 개발자들이 만들어 제출하는 공개 공모전 플랫폼입니다."
        />

        {groups.map((group) => (
          <HomeBucketSection key={group.bucket} group={group} />
        ))}

        {/* 「상금미달」이 참가를 막지 않는다는 도메인 규칙은 /contests(app/contests/page.tsx)와
            같은 문구로 반복한다 — 액센트 색만으로는 이 규칙이 안 읽힌다. 홈은 하필 그
            규칙을 가장 모를 첫 방문자가 보는 화면이라, 여기서 빠지면 안 된다. */}
        <p className="flex items-start gap-2 border-t border-rule pt-4 text-xs leading-relaxed text-ink/60">
          <span aria-hidden="true">ⓘ</span>
          <span>
            「상금미달」은 참가를 막지 않습니다. 선택한 요구형태의 최소 제안 상금 합계에 못
            미친다는 표시일 뿐이며, 판단은 개발자의 몫입니다.
          </span>
        </p>
      </div>
    </PageShell>
  );
}

function HomeBucketSection({ group }: { group: HomeCurationGroup }) {
  const label = HOME_BUCKET_LABELS[group.bucket];

  return (
    <section data-testid={`home-bucket-${group.bucket}`} className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-2">
        <h2 className="text-lg font-semibold">{label}</h2>
        <Link
          href="/contests"
          data-testid={`home-bucket-${group.bucket}-view-all`}
          className="text-sm text-ink/60 hover:text-ink"
        >
          전체 보기
        </Link>
      </div>

      {group.contests.length === 0 ? (
        <div data-testid={`home-bucket-${group.bucket}-empty`}>
          <EmptyState>{HOME_BUCKET_EMPTY_MESSAGES[group.bucket]}</EmptyState>
        </div>
      ) : (
        <ul data-testid={`home-bucket-${group.bucket}-list`} className="flex flex-col">
          {group.contests.map((contest) => (
            <HomeContestRow key={contest.id} contest={contest} />
          ))}
        </ul>
      )}
    </section>
  );
}

function HomeContestRow({ contest }: { contest: Contest }) {
  const imminent = remainingTimeIsImminent(contest.deadline_at);

  return (
    <li>
      <Link
        href={`/contests/${contest.id}`}
        data-contest-row={contest.id}
        className="grid grid-cols-[minmax(0,1fr)_150px_88px] items-center gap-6 border-b border-rule px-1 py-4 hover:bg-surface"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[15px] font-medium">{contest.title}</span>
            {contest.is_underfunded && <Badge tone="attention">상금미달</Badge>}
          </div>
          <span className="text-xs text-ink/60">{contest.category.name}</span>
          <span
            data-testid="submission-count"
            data-submission-count={contest.submission_count}
            className="text-xs text-ink/60"
          >
            {formatSubmissionCount(contest.submission_count)}
          </span>
        </div>
        <div
          className={`text-right font-mono text-sm font-medium ${contest.is_underfunded ? "text-attention" : ""}`}
        >
          {formatPrize(contest.prize)}
        </div>
        <div
          className={`text-right font-mono text-sm ${imminent ? "font-semibold text-attention" : "text-ink/70"}`}
        >
          {remainingTimeLabel(contest.deadline_at)}
        </div>
      </Link>
    </li>
  );
}
