// 개인정보처리방침 화면. 로그인 없이 누구나 닿아야 하고(개인정보 보호법 제30조는
// 공개 자체를 의무로 정한다) 서버 렌더링돼야 한다 — 공개 표면의 규율을 그대로
// 따른다(app/developers/[id]/page.tsx와 같은 패턴, "use client" 를 붙이지 않는다).
//
// **여기 적힌 항목은 전부 코드에서 다시 확인한 것이다** — 문서(docs/legal/
// personal-data.md)를 베끼지 않았다. 특히 휴대폰 본인확인(실명·생년월일·CI·DI·
// 전화번호)은 유료 개최·유료 제출에만 걸리는 관문이고(`backend/contests/
// submission_api.py`의 `_require_verification_unless_free`, `backend/contests/
// api.py`의 무료 개최는 `HostingPermission`만 본다) 지금 유료 공모전 자체가
// 꺼져 있어 이 관문을 지나는 사람이 아무도 없다 — 그래서 그 항목은 실제 수집이
// 아니라 아래 6절의 자리 표시로 옮겼다. 알림 발송 대행사로 연락처가 나가는 것도
// 같은 이유로 지금은 일어나지 않는다 — 연락처(전화번호)는 그 본인확인에서만
// 들어오기 때문이다(`backend/accounts/models.py`의 `PhoneContact`을 채우는
// 곳은 `backend/verification/api.py` 한 곳뿐이다).
//
// 사업자 정보(상호·사업자등록번호·대표자·주소)와 개인정보 보호책임자 지정은
// 이번에 넣지 않는다 — 사업자 등록 자체가 아직 저장소 밖의 사람 작업으로 남아
// 있고(docs/legal/README.md 열린 항목 2), 있지도 않은 사업자를 있는 것처럼
// 적으면 그것대로 거짓 고지가 된다. 사업자 등록이 끝나고 유료 공모전 스위치를
// 켜는 작업이 이 자리를 채운다(BUSINESS-INFO-PLACEHOLDER, docs/legal/README.md
// 참고).
import Link from "next/link";
import type { ReactNode } from "react";

import { Note, PageHeader, PageShell } from "@/app/components/ui";

export const metadata = {
  title: "개인정보처리방침",
  description: "Codemit 이 수집하는 개인정보 항목과 보유 기간, 위탁·국외 이전 상대를 밝힙니다.",
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

export default function PrivacyPolicyPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="공개 문서"
        title="개인정보처리방침"
        titleTestId="privacy-heading"
        description={`시행일 ${EFFECTIVE_DATE}`}
      />

      <div className="flex flex-col gap-8" data-testid="privacy-body">
        <P>
          Codemit(이하 서비스)는 개인정보 보호법 제30조에 따라 이용자의 개인정보를 보호하고
          관련한 고충을 처리하기 위해 이 방침을 정해 공개합니다. 이 방침은 지금 실제로
          운영되는 무료 공모전·클래스 범위에 적용됩니다 — 결제·본인확인이 필요한 유료
          공모전 기능은 지금 꺼져 있어 그 경로의 처리는 아직 일어나지 않으며, 그 항목은
          6절에 자리만 남겨 두었습니다. 그 기능을 열 때 실제로 수집·처리하는 항목을 이
          방침에 반영합니다.
        </P>

        <section className="flex flex-col gap-3">
          <SectionTitle>1. 수집하는 개인정보 항목과 수집 시점</SectionTitle>
          <P>
            구경만 하는 사람의 정보는 받지 않습니다. 아래 각 행위를 하는 시점에만 그
            행위에 필요한 항목을 받습니다.
          </P>

          <SubTitle>가입할 때 (소셜 로그인)</SubTitle>
          <List>
            <li>
              로그인 제공자가 내려주는 고유 식별자 — 지금 실제로 쓸 수 있는 제공자는
              카카오 하나입니다(다른 제공자는 로그인 화면에 「준비 중」으로 보이며,
              연결되면 이 방침에 더합니다).
            </li>
            <li>제공자가 인증한 이메일 주소 — 제공자가 값을 내려줄 때만</li>
            <li>
              카카오 로그인이고 닉네임 제공에 동의한 경우 카카오 닉네임 — 클래스에 가입할
              때 이름 칸을 미리 채우는 데만 쓰고, 다른 이용자에게 따로 보이지 않습니다.
            </li>
          </List>

          <SubTitle>공모전을 열거나 참가할 때</SubTitle>
          <List>
            <li>
              공개용 이름과 소개(선택) — 개최자·참가자 본인이 직접 입력하고, 공모전
              화면·참가 이력에 공개적으로 노출됩니다.
            </li>
            <li>
              제출한 소스코드 전체와 요구사항에 대한 자가 응답 — 채점을 위해 받습니다
              (국외 이전은 4절).
            </li>
          </List>

          <SubTitle>클래스에 가입할 때</SubTitle>
          <List>
            <li>
              그 클래스에서 쓰일 이름 — 계정의 표시 이름과 별개로 참여자 본인이 정하고,
              강사와 같은 클래스 참여자에게 보입니다. 나중에 바꿀 수 있는 사람은 본인뿐
              입니다.
            </li>
            <li>제출한 소스코드 전체 — 채점을 위해 받습니다(국외 이전은 4절).</li>
          </List>

          <SubTitle>클래스를 열 때 (강사)</SubTitle>
          <List>
            <li>
              강사 본인의 OpenAI API 키 — 암호화해 저장하고 화면에는 끝 네 자리만
              보여줍니다. 자기 클래스의 채점 비용을 강사 본인이 직접 부담하기 위한
              것으로, 서비스가 대신 요금을 내지 않습니다.
            </li>
            <li>이 클래스에서 불릴 강사 이름(선택) — 가입 미리보기 화면에 노출됩니다.</li>
          </List>

          <SubTitle>서비스를 이용하는 동안</SubTitle>
          <List>
            <li>로그인 상태를 유지하기 위한 세션 쿠키</li>
            <li>화면을 밝게·어둡게 보여줄지 정하는 설정 쿠키</li>
            <li>
              소셜 로그인 절차가 끝날 때까지만 쓰고 곧바로 지워지는 임시 쿠키(로그인
              시작 위치를 기억하는 용도)
            </li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>2. 개인정보의 이용 목적</SectionTitle>
          <List>
            <li>회원 식별과 로그인 상태 유지</li>
            <li>공모전·클래스 운영 — 개최자·참가자·강사·참여자를 서로 구별해 보여줌</li>
            <li>제출물의 AI 채점과 그 결과 통지</li>
            <li>이의 심판 — 운영자가 제출 소스를 열람해 AI 판정이 맞았는지 확인</li>
            <li>서비스 화면 설정 유지</li>
            {/* 자전거래 차단은 본인확인 CI 로 판정하므로 **유료 공모전에서만** 돈다
                (`_require_verification_unless_free` 가 무료에서 None 을 돌려주면
                호출부가 `_reject_self_dealing` 도 함께 건너뛴다). 지금은 그 경로가
                꺼져 있어 일어나지 않는 처리라 6절의 자리 표시로 옮겼다 — 본인확인
                항목을 그렇게 다룬 것과 같은 기준이다. */}
            <li>서비스 운영에 필요한 문의·고충 처리</li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>3. 보유 기간과 파기</SectionTitle>
          <P>
            목적을 다한 개인정보는 지체 없이 파기합니다. 탈퇴하면 계정 이메일, 소셜
            로그인으로 받은 이메일·닉네임, 공개 프로필의 이름과 소개가 즉시 지워집니다.
            휴대폰 본인확인을 거친 적이 있다면(6절) 그 정보도 같은 시점에 즉시 지워집니다.
          </P>
          <P>
            남는 것도 있습니다 — 참가한 공모전과 제출물 기록은 이름 없이 남습니다. 계약
            상대방의 기록이라 삭제하면 다른 이용자의 참가 이력이 함께 훼손되기 때문입니다.
            결제·지급이 있었던 거래의 원장 기록은 법이 보존을 요구하는 기간 동안(전자상거래법
            시행령 기준 5년) 남습니다 — 다만 지금은 그런 거래 자체가 없습니다(6절).
          </P>
          <P>
            2년 동안 서비스 이용이 없으면 휴면으로 보아 남아 있는 본인확인 정보를 파기하고,
            다음 행위 때 본인확인을 다시 받습니다. 지금은 본인확인 자체가 없어 이 규칙이
            적용될 대상이 없습니다 — 유료 공모전이 열리면 그때부터 적용됩니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>4. 국외 이전 — 제출물이 AI 채점을 위해 해외로 나갑니다</SectionTitle>
          <P>
            제출한 소스코드 전체와 요구사항 자가 응답이 채점을 위해 미국에 서버를 둔
            OpenAI 로 전송됩니다. 판정 근거 문장에는 판정에 실제로 쓰인 코드의 짧은 조각
            (함수 이름 등)이 그대로 옮겨질 수 있습니다 — 판정과 무관한 코드나 주석까지
            함께 옮겨지지는 않는다는 것을 직접 확인했습니다.
          </P>
          <P>
            <strong className="font-semibold text-ink">누구의 이름으로 전송되는지가 갈립니다.</strong>{" "}
            공모전 제출물은 서비스 자신의 계정으로 전송됩니다. 클래스 제출물은{" "}
            <strong className="font-semibold text-ink">그 클래스 강사 본인의 계정</strong>으로
            전송됩니다 — 강사가 자기 채점 비용을 직접 부담하는 것과 같은 이유이고, 이
            경우 그 소스가 강사의 OpenAI 이용 기록에도 남습니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>5. 위탁</SectionTitle>
          <List>
            <li>
              오브젝트 스토리지 — 제출한 파일과 소스코드 원본, 운영팀이 보내는 알림에
              첨부되는 이미지를 저장합니다.
            </li>
            <li>
              OpenAI — 4절과 같습니다. AI 채점을 위한 국외 이전이 곧 이 위탁입니다.
            </li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>6. 유료 공모전을 여는 시점에 채우는 항목</SectionTitle>
          <Note tone="neutral">
            <p>
              결제·본인확인이 필요한 개최와 재개최, 심사기간 연장, 결제, 그리고 환불·배분·
              지급·인수인계는 지금 서비스에서 꺼져 있어 아무도 이 경로를 지나지 않습니다.
              그래서 아래 항목은 실제 수집이 아니라, 그 기능을 열 때 채울 자리입니다.
              사업자 등록과 개인정보 보호책임자 지정도 그 작업과 함께 채워집니다.
            </p>
          </Note>
          <List>
            <li>휴대폰 본인확인 — 실명, 생년월일, 본인확인기관 고유식별정보, 전화번호</li>
            <li>결제 정보</li>
            <li>지급 확정 시 세금 신고를 위한 주민등록번호</li>
            <li>지급대행 등록을 위한 이름·이메일·전화번호·계좌</li>
            <li>마감 임박·지급 등 문자·카카오 알림톡으로 나가는 통지에 필요한 연락처</li>
            <li>
              부정 이용 방지 — 같은 사람이 개최와 참가를 동시에 해 상금을 되가져가는지
              본인확인 정보로 가려냅니다. 본인확인이 없는 무료 공모전에서는 이 검사
              자체가 성립하지 않습니다.
            </li>
          </List>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>7. 이용자의 권리</SectionTitle>
          <P>
            이용자는 언제든 자기 정보를 열람·정정·삭제하도록 요구할 수 있습니다. 계정
            탈퇴 화면에서 본인이 직접 신원 정보를 지우고 계정을 닫을 수 있고, 그 밖의
            요청은 사업자 등록이 끝나고 접수 창구가 마련되는 대로 이 방침에 채웁니다.
          </P>
          <P>
            운영자는 이의 심판 과정에서 제출 소스를 열람할 수 있고, 그 열람은 누가·언제
            열었는지 기록되며 본인이 그 기록을 확인할 수 있습니다. 클래스에서는 강사가
            지도·채점을 위해 제출물을 언제든 열람할 수 있고, 이 열람은 지도 행위 자체라
            기록하지 않습니다 — 저작권은 지도와 무관하게 제출한 사람에게 그대로 남습니다.
          </P>
        </section>

        <section className="flex flex-col gap-3">
          <SectionTitle>8. 처리방침의 변경</SectionTitle>
          <P>
            이 방침을 바꾸면 시행일을 다시 적고 바뀐 내용을 이 화면에 고지합니다.
          </P>
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
