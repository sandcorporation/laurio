// 개인정보처리방침 화면(#472). 로그인 없이 누구나 닿아야 하고(개인정보 보호법
// 제30조는 공개 자체를 의무로 정한다) 서버 렌더링돼야 한다 — 공개 표면의 규율을
// 그대로 따른다(ADR-0015, 이 파일에 클라이언트 지시어를 붙이지 않는다).
//
// **한국 방침의 표준 목차로 쓴다**(2026-09-21). 처음 판은 이 저장소의 설명문
// 말투였고 「채우는 항목」 같은 **문서가 자기 자신을 설명하는 절**이 있어
// 「다른 서비스와 달리 이상하다」는 지적을 받았다. 지금 처리하지 않는 것은
// **적지 않는다** — 유료 기능을 열 때 12절에 따라 개정해 알린다.
//
// **여기 적힌 항목은 전부 코드에서 확인한 것이다.** 특히 휴대폰 본인확인
// (실명·생년월일·연계정보·전화번호)은 **유료 개최·유료 제출에만** 걸리는
// 관문이고(`backend/contests/submission_api.py` 의
// `_require_verification_unless_free`, 무료 개최는 `HostingPermission` 만 본다)
// 지금은 그 경로가 열려 있지 않아 실제로 수집하지 않는다 — 그래서 이 방침에
// 적지 않는다. 알림 발송 대행사로 연락처가 나가는 것도 같은 이유로 지금은
// 일어나지 않는다(전화번호는 그 본인확인에서만 들어온다).
//
// **강사가 연결한 앱(#517, ADR-0052)은 4절에 적는다 — 5절(위탁)이 아니다.**
// 그 도구는 강사가 고르고 강사가 그 운영사와 계약하며, 서비스는 그 운영사와
// 위탁계약을 맺지도 감독하지도 않는다 — 위탁의 요건이 없다. 그렇다고 4절의
// 「제공하지 않습니다」를 그대로 두면 거짓이 되므로, 전달되는 항목·받는 자·
// 서비스가 통제하지 않는다는 사실을 4절 ②~④에 적는다. 이 분류가 법적으로
// 맞는지는 docs/legal/personal-data.md 의 열린 항목으로 남아 있다.
import type { ReactNode } from "react";

import { PageHeader, PageShell } from "@/app/components/ui";
import { supportEmail } from "@/lib/legal/contact";
import { effectiveNotice, koreanDate } from "@/lib/legal/effective-notice";

export const metadata = {
  title: "개인정보처리방침",
  description: "Codemit 이 수집하는 개인정보 항목과 보유 기간, 위탁·국외 이전 상대를 밝힙니다.",
};

// 이 판(완성도 채점을 6항 이전 목적에 더한 개정, #897)의 시행일은 병합일(KST)+7일이다(방침 12항의
// 7일 전 공지). 시행일 전에는 머리에 「개정 예정 · 시행일 …」이 뜨고 시행일부터 저절로 내린다(#892).
const EFFECTIVE_ISO = "2026-11-12";
const EFFECTIVE_DATE = koreanDate(EFFECTIVE_ISO);

// Anthropic, PBC 이전을 더한 개정(#803)의 시행일 — 이 판의 시행일이 아니다. 백엔드 설정
// `PRIVACY_POLICY_EFFECTIVE_DATE` 와 같은 값이어야 하고(Claude 키 저장 잠금의 기준일이다 — 이 값을 옮기면
// 열린 키 저장이 다시 잠긴다), `backend/tests/test_privacy_policy_lock.py` 가 아래 한 줄을 읽어 지킨다.
const ANTHROPIC_TRANSFER_EFFECTIVE_ISO = "2026-11-06";
const PREVIOUS_EFFECTIVE_DATE = koreanDate(ANTHROPIC_TRANSFER_EFFECTIVE_ISO);

function Article({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
      <div className="flex flex-col gap-1.5 text-sm leading-relaxed text-ink/70">{children}</div>
    </section>
  );
}

function Items({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink/70">{children}</ul>;
}

export default function PrivacyPolicyPage() {
  const email = supportEmail();

  return (
    <PageShell>
      <PageHeader
        eyebrow="공개 문서"
        title="개인정보처리방침"
        titleTestId="privacy-heading"
        description={effectiveNotice(EFFECTIVE_ISO, new Date())}
      />

      <div className="flex flex-col gap-7" data-testid="privacy-body">
        <p className="text-sm leading-relaxed text-ink/70">
          Codemit(이하 “서비스”)은 개인정보 보호법 제30조에 따라 정보주체의 개인정보를 보호하고
          이와 관련한 고충을 신속하게 처리하기 위하여 다음과 같이 개인정보처리방침을 수립·공개합니다.
        </p>

        <Article title="1. 수집하는 개인정보의 항목과 수집 방법">
          <p>
            서비스는 회원가입과 각 기능을 이용하는 시점에 그 기능에 필요한 항목만 수집합니다.
            둘러보기만 하는 이용자에게서는 아래 방문 기록 외의 개인정보를 수집하지 않습니다.
          </p>
          <Items>
            <li>
              회원가입: 소셜 로그인 제공자가 전달하는 고유 식별자, 제공자가 확인한 이메일 주소,
              제공자에게 동의한 경우 닉네임
            </li>
            <li>
              공모전 이용: 공개 프로필에 표시할 이름과 소개(회원이 직접 입력), 제출한 소스코드와
              요구사항에 대한 자가 응답
            </li>
            <li>클래스 이용: 해당 클래스에서 사용할 표시 이름(참여자가 직접 입력), 제출한 소스코드</li>
            <li>클래스 개설: 강사가 등록한 인공지능 서비스 키(암호화하여 저장)</li>
            <li>서비스 이용 중: 로그인 상태 유지와 화면 설정을 위한 쿠키(9항)</li>
            <li>
              서비스 이용 중: 방문한 페이지의 주소와 유입 경로(쿠키와 이용자 식별자 없이 방문 수를
              집계하는 데에만 쓰며, 회원 정보와 연결하지 않습니다)
            </li>
            <li data-testid="privacy-error-log-item">
              서비스 이용 중: 오류 기록 — 오류가 났을 때 오류 내용과 발생 위치, 발생 시각, 서비스
              버전, 페이지 주소, 브라우저·기기 정보, 서버 오류의 요청 경로와 요청 방식, 접속 IP
              주소(끝자리를 가려 저장), 로그인한 경우 회원 식별 번호. 쿠키·인증 정보·비밀번호·
              요청 내용은 지우고 보내며, 이메일과 이름은 보내지 않습니다. 오류 기록은 서비스가 직접
              운영하는 국내 서버에 저장하며 위탁하거나 국외로 이전하지 않습니다.{" "}
              <a
                href="https://sandcorporation.github.io/privacy-and-terms/errors/"
                className="underline underline-offset-2"
                target="_blank"
                rel="noopener noreferrer"
              >
                서비스 오류 기록 안내
              </a>
            </li>
          </Items>
          <p>
            수집 방법은 회원이 서비스 화면에서 직접 입력하거나, 소셜 로그인 제공자로부터 회원의
            동의를 거쳐 전달받는 방법입니다.
          </p>
        </Article>

        <Article title="2. 개인정보의 이용 목적">
          <Items>
            <li>회원 식별과 로그인 상태 유지</li>
            <li>공모전과 클래스의 운영 — 개최자·참가자·강사·참여자를 구분하여 표시</li>
            <li>제출물의 채점(요구사항 충족 여부와 완성도)과 그 결과 통지</li>
            <li>이의 제기 절차의 처리</li>
            <li>서비스 이용에 관한 문의 응대와 고충 처리</li>
            <li>서비스 오류의 발견·수정과 안정성 확보</li>
          </Items>
        </Article>

        <Article title="3. 개인정보의 보유·이용 기간과 파기">
          <p>
            ① 서비스는 개인정보의 수집·이용 목적이 달성되면 지체 없이 해당 개인정보를 파기합니다.
          </p>
          <p>
            ② 회원이 탈퇴하면 신원 정보와 공개 프로필 정보를 지체 없이 파기합니다. 2년 이상
            서비스를 이용하지 않은 회원의 신원 정보도 같은 방법으로 파기합니다.
          </p>
          <p>
            ③ 이미 진행된 공모전·클래스의 제출물과 채점 기록은 다른 이용자의 권리와 서비스 운영을
            위해 계정 식별자와 분리된 형태로 보관합니다.
          </p>
          <p>
            ④ 관계 법령에 따라 보존해야 하는 기록이 있는 경우에는 그 법령이 정한 기간 동안
            보관한 뒤 파기합니다.
          </p>
          <p>
            ⑤ 파기 방법: 전자적 파일 형태의 정보는 복구할 수 없는 방법으로 삭제합니다.
          </p>
          <p data-testid="privacy-error-log-retention">
            ⑥ 오류 기록은 수집한 날부터 90일이 지나면 자동으로 삭제합니다.
          </p>
        </Article>

        <Article title="4. 개인정보의 제3자 제공">
          <p>
            ① 서비스는 정보주체의 개인정보를 제3자에게 제공하지 않습니다. 다만 ②의 경우와
            법령에 따라 제공이 요구되는 경우에는 그 범위에서 제공합니다.
          </p>
          <p>
            ② 클래스의 강사는 자신의 계정으로 외부 인공지능 도구를 서비스에 연결하여(이하
            “연결된 앱”) 자신의 클래스를 관리할 수 있습니다. 강사가 연결된 앱으로 참여자의
            제출물이나 채점 결과를 열람하면 다음 정보가 그 도구와 그 도구의 운영사에 전달됩니다.
          </p>
          <Items>
            <li>전달받는 자: 해당 클래스의 강사가 연결한 인공지능 도구와 그 운영사</li>
            <li>
              전달 항목: 그 강사의 클래스에 낸 제출물(소스코드와 저장소의 내용), 클래스에서
              사용하는 표시 이름, 문제별 통과 여부·점수·시도 횟수·채점 근거. 이메일 주소는
              전달되지 않습니다.
            </li>
            <li>전달 목적: 강사의 클래스 운영과 참여자에 대한 지도·채점</li>
            <li>보유·이용 기간: 그 도구의 운영사가 정한 기간</li>
          </Items>
          <p>
            ③ 어떤 도구를 연결할지는 강사가 정합니다. 서비스는 연결된 앱의 운영사에 개인정보
            처리를 위탁하지 않으며, 전달된 정보가 그 도구에서 처리되는 방식을 통제하지 않습니다.
            전달된 정보는 그 운영사의 개인정보 처리방침에 따라 처리되며, 운영사가 국외에 있는
            경우 국외로 이전될 수 있습니다.
          </p>
          <p>
            ④ 강사는 연결된 앱을 언제든 끊을 수 있으며, 끊은 뒤에는 그 도구로 정보가 전달되지
            않습니다. 참여자는 연결된 앱으로의 전달에 관하여 해당 클래스의 강사나 10항의
            문의처에 문의할 수 있습니다.
          </p>
        </Article>

        <Article title="5. 개인정보 처리의 위탁">
          <p>서비스는 원활한 서비스 제공을 위해 다음과 같이 개인정보 처리 업무를 위탁합니다.</p>
          <Items>
            <li>OpenAI, L.L.C. — 제출물의 채점(위탁 항목: 제출한 소스코드와 자가 응답)</li>
            <li>
              Anthropic, PBC — 강사가 Claude 키로 채점을 연결한 클래스의 제출물 채점(위탁 항목:
              제출한 소스코드)
            </li>
            <li>Oracle Corporation — 제출 파일과 이미지의 보관(위탁 항목: 제출물 파일)</li>
          </Items>
          <p>
            서비스는 위탁계약을 체결할 때 개인정보가 안전하게 관리되도록 필요한 사항을 규정하고,
            수탁자가 이를 준수하는지 감독합니다. 위탁 내용이나 수탁자가 변경되면 이 방침을 통해
            알립니다.
          </p>
        </Article>

        <Article title="6. 개인정보의 국외 이전">
          <p>서비스는 제출물의 채점을 위해 다음과 같이 개인정보를 국외로 이전합니다.</p>
          <p>① OpenAI, L.L.C.</p>
          <Items>
            <li>이전받는 자: OpenAI, L.L.C.</li>
            <li>이전되는 국가: 미국</li>
            <li>이전 일시와 방법: 회원이 제출물을 낸 즉시 정보통신망을 통해 전송</li>
            <li>이전 항목: 제출한 소스코드와 요구사항에 대한 자가 응답</li>
            <li>이전 목적: 요구사항 충족 여부의 자동 채점, 완성도 채점과 그 근거 생성</li>
            <li>보유·이용 기간: 채점에 필요한 기간</li>
          </Items>
          <p>② Anthropic, PBC</p>
          <Items>
            <li>이전받는 자: Anthropic, PBC</li>
            <li>이전되는 국가: 미국</li>
            <li>이전 일시와 방법: 채점할 때마다 정보통신망을 통해 전송</li>
            <li>이전 항목: 강사가 Claude 키로 채점을 연결한 클래스에서 제출한 소스코드</li>
            <li>이전 목적: 요구사항 충족 여부의 자동 채점, 완성도 채점과 그 근거 생성</li>
            <li>
              보유·이용 기간: 이전받는 자가 받은 날부터 30일 이내에 삭제(이용 정책 위반으로
              분류된 경우 최대 2년)
            </li>
          </Items>
          <p>
            채점 결과에 함께 표시되는 판정 근거에는 제출한 소스의 일부가 인용될 수 있습니다.
            클래스의 채점은 강사가 등록한 키로 이루어지며, 강사가 OpenAI 키를 등록한 클래스는
            OpenAI, L.L.C. 로, Claude(Anthropic) 키를 등록한 클래스는 Anthropic, PBC 로 이전되고
            이전 항목은 위와 같습니다.
          </p>
          <p>
            정보주체는 국외 이전을 거부할 수 있습니다. 다만 거부하는 경우 제출물의 채점을 이용할
            수 없습니다.
          </p>
          <p>강사가 연결한 앱으로 전달되는 정보는 이 항이 아니라 4항 ②~④를 따릅니다.</p>
        </Article>

        <Article title="7. 정보주체의 권리와 행사 방법">
          <p>
            ① 정보주체는 언제든 자신의 개인정보에 대한 열람, 정정, 삭제, 처리정지를 요구할 수
            있습니다.
          </p>
          <p>
            ② 권리 행사는 서비스 화면에서 직접 하거나 10항의 문의처로 요청할 수 있으며, 서비스는
            지체 없이 조치합니다.
          </p>
          <p>
            ③ 정보주체는 법정대리인이나 위임받은 사람을 통해 권리를 행사할 수 있습니다.
          </p>
        </Article>

        <Article title="8. 개인정보의 안전성 확보 조치">
          <Items>
            <li>암호화: 신원 정보와 강사가 등록한 인공지능 서비스 키는 암호화하여 저장합니다.</li>
            <li>접근 통제: 개인정보에 접근할 수 있는 권한을 업무에 필요한 최소한으로 제한합니다.</li>
            <li>
              접근 기록: 이의 제기 절차에서 운영자가 제출물의 소스를 열람하면 그 사실을 기록하고,
              제출한 회원이 확인할 수 있게 합니다.
            </li>
            <li>전송 구간 암호화: 서비스와 이용자 사이의 통신은 암호화된 연결로 이루어집니다.</li>
          </Items>
        </Article>

        <Article title="9. 쿠키의 사용">
          <p>
            서비스는 로그인 상태를 유지하기 위한 쿠키, 화면을 밝게 또는 어둡게 표시하기 위한
            쿠키, 소셜 로그인 절차가 끝날 때까지만 사용하는 임시 쿠키를 사용합니다. 광고나 행태
            정보 수집을 위한 쿠키는 사용하지 않습니다.
          </p>
          <p>
            이용자는 브라우저 설정에서 쿠키 저장을 거부할 수 있습니다. 다만 로그인에 필요한
            쿠키를 거부하면 로그인이 필요한 기능을 이용할 수 없습니다.
          </p>
        </Article>

        <Article title="10. 개인정보 보호책임자와 문의처">
          <p>
            서비스는 개인정보 처리에 관한 업무를 총괄하고 정보주체의 고충을 처리하기 위하여
            개인정보 보호책임자를 다음과 같이 지정합니다.
          </p>
          <Items>
            <li>개인정보 보호책임자: 서비스 운영자</li>
            <li>
              문의처:{" "}
              {email ? (
                <a
                  href={`mailto:${email}`}
                  className="underline underline-offset-2 hover:text-ink"
                  data-testid="privacy-contact-email"
                >
                  {email}
                </a>
              ) : (
                "서비스 운영자"
              )}
            </li>
          </Items>
        </Article>

        <Article title="11. 권익침해 구제 방법">
          <p>
            정보주체는 개인정보 침해로 인한 구제를 받기 위하여 다음 기관에 분쟁 해결이나 상담을
            신청할 수 있습니다.
          </p>
          <Items>
            <li>개인정보분쟁조정위원회 (국번 없이 1833-6972)</li>
            <li>개인정보침해신고센터 (국번 없이 118)</li>
            <li>대검찰청 사이버수사과 (국번 없이 1301)</li>
            <li>경찰청 사이버수사국 (국번 없이 182)</li>
          </Items>
        </Article>

        <Article title="12. 처리방침의 변경">
          <p>
            이 방침의 내용이 추가·삭제·수정되는 경우에는 시행일 7일 전부터 서비스 화면에
            공지합니다.
          </p>
        </Article>

        <Article title="부칙">
          <p>① 이 방침은 {EFFECTIVE_DATE}부터 시행합니다.</p>
          <p>② {PREVIOUS_EFFECTIVE_DATE}부터 시행된 종전 방침은 이 방침의 시행일 전날까지 적용됩니다.</p>
        </Article>
      </div>
    </PageShell>
  );
}
