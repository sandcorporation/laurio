// 이용약관 화면. 개인정보처리방침(app/privacy/page.tsx)과 같은 이유로 로그인
// 없이 닿아야 하고 서버 렌더링돼야 한다.
//
// **돈이 오가는 조항(환불·배분·지급·인수인계, 통신판매중개자 고지, 사업자 정보)은
// 이번에 채우지 않는다** — 유료 공모전이 꺼져 있어 그 경로 자체가 없고
// (`backend/core/contest_switch.py`), 사업자 등록도 저장소 밖의 사람 작업으로
// 아직 끝나지 않았다(docs/legal/README.md 열린 항목 2). 유료 공모전 스위치를 켜는
// 작업이 이 자리를 채운다(BUSINESS-INFO-PLACEHOLDER).
//
// **무료 공모전의 선정은 저작권 이전이 아니다** — `backend/awards/api.py`가
// `contest.is_free`면 인수인계 행을 만들지 않는다. 선정되면 개최자에게 그
// 제출물의 소스를 열어 줄 뿐, 소유권은 계속 제출한 사람에게 남는다. **본인확인
// 관문도 무료 공모전에는 없다** — `backend/contests/submission_api.py`의
// `_require_verification_unless_free`가 무료 공모전이면 본인확인도 동일인
// 제출 차단도 건너뛴다. 그래서 만 19세 제한과 동일인 제출 금지는 지금
// 무료 공모전·클래스 둘 다 자기신고에 의존한다 — docs/legal/contracts-and-ip.md
// 가 「강의실만 자기신고」라고 적은 것을 이 사실에 맞춰 함께 고쳤다.
import Link from "next/link";
import type { ReactNode } from "react";

import { Note, PageHeader, PageShell } from "@/app/components/ui";

export const metadata = {
  title: "이용약관",
  description: "Codemit 을 이용하는 조건과 서로의 책임 범위를 정합니다.",
};

const EFFECTIVE_DATE = "2026년 9월 20일";

function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-lg font-semibold tracking-tight text-ink">{children}</h2>;
}

function SubTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-semibold text-ink">{children}</h3>;
}

function P({ children }: { children: ReactNode }) {
  return <p className="text-sm leading-relaxed text-ink/70">{children}</p>;
}

function List({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink/70">{children}</ul>;
}

export default function TermsOfServicePage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="공개 문서"
        title="이용약관"
        titleTestId="terms-heading"
        description={`시행일 ${EFFECTIVE_DATE}`}
      />

      <div className="flex flex-col gap-8" data-testid="terms-body">
        <section className="flex flex-col gap-3">
          <SectionTitle>1. 목적</SectionTitle>
          <P>
            이 약관은 Codemit(이하 서비스)을 이용하는 조건과, 서비스와 이용자 사이의
            권리·의무·책임 범위를 정합니다. 지금 서비스에서 실제로 운영되는 것은
            돈을 다루지 않는 무료 공모전과 클래스이며, 결제·본인확인이 필요한 유료
            공모전 기능은 꺼져 있습니다 — 그 기능과 관련한 조항은 8절에 자리만
            남겨 두었고, 기능을 열 때 채웁니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>2. 회원가입과 계정</SectionTitle>
          <List>
            <li>가입은 소셜 로그인(카카오·GitHub·구글)으로만 합니다.</li>
            <li>계정은 본인만 쓸 수 있고, 다른 사람에게 양도·대여할 수 없습니다.</li>
            <li>
              만 19세 미만은 공모전을 열거나 참가할 수 없고, 클래스를 열거나
              참여할 수 없습니다 — 나이 확인은 본인이 사실대로 밝히는 것을
              전제로 합니다. 결제가 필요한 개최·제출이 열리면 그때부터 휴대폰
              본인확인으로 나이를 실제로 확인합니다.
            </li>
            <li>
              탈퇴하면 계정에 남아 있던 신원·연락처·공개 프로필 정보가 지워지고
              되돌릴 수 없습니다. 자세한 내용은{" "}
              <Link href="/privacy" className="underline decoration-ink/30 underline-offset-2 hover:text-ink">
                개인정보처리방침
              </Link>
              에 있습니다.
            </li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>3. 서비스 내용</SectionTitle>
          <SubTitle>공모전</SubTitle>
          <P>
            개최자가 요구사항과 기한을 걸어 공모전을 열면 참가자가 제출물을 냅니다.
            제출물은 AI가 요구사항 충족 여부를 채점하고, 개최자는 그 결과를
            참고해 선정작을 고릅니다. 채점 결과에 이의가 있으면 정해진 절차로
            다시 심판을 받을 수 있습니다.
          </P>
          <SubTitle>클래스</SubTitle>
          <P>
            강사가 클래스를 열어 문제를 내면 참여자가 풀이를 제출합니다. 채점은
            강사 본인이 등록한 AI 키로 이루어지며, 상금도 결제도 저작권
            이전도 없습니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>4. 지식재산권</SectionTitle>
          <SubTitle>공모전에 낸 제출물</SubTitle>
          <List>
            <li>
              선정되지 않은 제출물의 저작권은 낸 사람이 그대로 가집니다. 공모전
              마감이 지나면 그 제출물의 데모와 영상이 공개됩니다 — 개최자의
              상호·로고·요구사항 내용을 가린 채로 공개하지 않습니다.
            </li>
            <li>
              선정된 제출물은 저작권이 이전되지 않습니다. 대신 개최자에게 그
              소스를 열어 보고 받을 수 있는 권리가 열립니다 — 제출할 때 이
              사실에 동의한 것으로 봅니다. 개최자가 선정된 참가자에게 따로
              주는 보상은 서비스가 관여하지 않는, 둘 사이의 별도 약속입니다.
            </li>
            <li>
              제출 시점에는 소스코드 전체 또는 그 소스에 닿을 수 있는 공개
              저장소 주소 중 하나를 반드시 내야 합니다. 저장소 주소만 낸
              경우, 채점 시점에 그 저장소가 닫혀 있거나 지워져 있으면 요구사항
              전부를 채우지 못한 것으로 채점되며 이 판정은 되돌릴 수 없습니다.
            </li>
            <li>
              개최자는 선정 전까지 어떤 제출물의 소스도 볼 수 없습니다. 다만
              이의 심판 과정에서는 운영자가 소스를 볼 수 있고, 그 열람은
              기록되며 낸 사람이 그 기록을 확인할 수 있습니다.
            </li>
          </List>
          <SubTitle>클래스에 낸 제출물</SubTitle>
          <P>
            저작권은 언제나 낸 사람에게 남고 이전되지 않습니다. 강사는 지도와
            채점을 위해 제출물을 언제든 열어 볼 수 있고, 이 열람은 지도 행위
            자체이므로 따로 기록하지 않습니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>5. 금지행위</SectionTitle>
          <List>
            <li>다른 사람의 제출물을 그대로 옮기거나 베끼는 행위</li>
            <li>근거 없이 요구사항을 충족했다고 주장하는 등 채점을 속이려는 행위</li>
            <li>
              개최자가 자신과 같은 사람을 참가시켜 스스로 선정한 뒤 상금을
              되가져가는 행위, 그리고 이를 이용해 결제 수단을 현금으로
              바꾸려는 행위
            </li>
            <li>진행 중인 다른 참가자의 제출물을 몰래 보거나 퍼뜨리는 행위</li>
            <li>서비스나 다른 이용자에게 손해를 끼치는 그 밖의 부정한 방법의 이용</li>
          </List>
          <P>
            위 행위가 확인되면 해당 제출물·공모전·클래스에 대한 조치와 함께 이용을
            제한할 수 있습니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>6. 서비스의 중단과 변경</SectionTitle>
          <P>
            서비스는 점검, 설비 장애, 그 밖에 운영상 필요한 경우 제공을 일시
            중단할 수 있습니다. 기능의 내용이나 범위는 사전 공지 후 바뀔 수
            있습니다 — 지금 꺼져 있는 유료 공모전 기능을 여는 것도 이 변경에
            해당합니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>7. 책임의 범위</SectionTitle>
          <P>
            서비스는 AI 채점 결과와 개최자의 선정 판단이 공정하게
            이루어지도록 절차(이의 심판 등)를 두지만, 그 판단 자체의 결과를
            보장하지 않습니다. 이용자 사이에서 발생한 다툼은 원칙적으로 당사자
            사이에서 해결하며, 서비스는 기록된 사실(제출 시각, 채점 근거, 열람
            기록 등)을 확인해 주는 역할을 합니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>8. 유료 공모전을 여는 시점에 채우는 조항</SectionTitle>
          <Note tone="neutral">
            <p>
              지금 서비스는 상금을 걸지 않는 무료 공모전만 운영합니다. 아래
              내용은 결제·본인확인이 필요한 유료 공모전을 열 때 이 약관에
              채웁니다 — 사업자 정보(상호·사업자등록번호·대표자·주소)와
              통신판매중개자로서의 고지도 그때 함께 채웁니다.
            </p>
          </Note>
          <List>
            <li>선정작의 저작권 이전과 인수인계 절차</li>
            <li>상금 결제, 예치금의 성격, 환불 조건</li>
            <li>기한 내 선정이 없을 때의 배분 방식</li>
            <li>플랫폼 수수료·원천징수, 지급 절차와 지급대행 등록</li>
            <li>서비스가 통신판매중개자로서 지는 책임의 범위</li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>9. 약관의 변경</SectionTitle>
          <P>이 약관을 바꾸면 시행일을 다시 적고 바뀐 내용을 이 화면에 고지합니다.</P>
          <List>
            <li>{EFFECTIVE_DATE} — 최초 제정</li>
          </List>
        </section>

        <P>
          <Link href="/" className="underline decoration-ink/30 underline-offset-2 hover:text-ink">
            홈으로 돌아가기
          </Link>
        </P>
      </div>
    </PageShell>
  );
}
