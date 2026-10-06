"""사용자 입력 문자열 필드마다 금칙어 판정을 어떻게 적용하는지 적는 표
(spec #474, #475, #477, #478, #479, #480).

앱·입력 스키마 클래스 이름·필드 이름이 키다. **등록되지 않은 사용자 입력
문자열 필드가 있으면 안 된다** — `tests/test_banned_word_field_registration.py`
(#480)가 백엔드 입력 스키마를 정적으로 훑어 이 표와 대조한다. 면제할
필드는 `exempt_reason`을 채운다 — 이유가 비면 그 검사가 실패한다
(`scripts/check_screen_language.py`의 `SCREEN-LANGUAGE-EXCEPTION`과 같은
관용구).

#475 가 클래스 참여자 이름(가입 때·나중에 바꿀 때 둘 다)을 담았고, #477 이
강의실의 나머지 이름 세 곳 — 클래스가 들고 있는 강사 이름(만들 때·설정에서
고칠 때), 문제 템플릿·클래스 템플릿 공개자 이름(둘 다 같은 입력 스키마
`PublishTemplateIn`을 쓴다) — 을 더했다. #478 이 개최자 공개용 이름·개발자
표시 이름(둘 다 프로필을 만들 때·나중에 고칠 때가 같은 `POST` 하나라 줄이
하나씩이다)을 더했다. #479 가 공개 제목·본문 넷(공모전 제목·설명, 문제
제목·설명, 클래스 이름, 체크리스트 항목)을 더했다 — **이 넷은 사칭 목록을
걸지 않는다**, 「관리자 페이지 만들기」는 정당한 문제 제목이고 「운영자
대시보드」는 정당한 공모전 제목이다(spec #474 Implementation Decisions).

#480 이 구조 검사를 세우면서 나머지 필드를 전부 등록했다 — 대부분은
면제(운영자 표면·당사자만 읽는 글·식별자나 URL 등 자유 텍스트가 아닌 것)지만,
표를 훑다가 이미 검사하는 필드와 같은 범주(공개 이름·공개 본문)인데 어느
티켓에도 없던 네 자리(필드로는 여덟 줄)를 찾아 면제 대신 실제 검사를
걸었다 — 클래스 템플릿을 가져올 때 새로 붙이는 이름, 채점 지침 "custom"
문장(만들 때·고칠 때), 공모전 요구사항 문구(만들 때 인라인·따로 추가·수정),
개최자·개발자 공개 소개글이다. 아래 그 여덟 줄의 주석이 찾은 경위를 적는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BannedWordRule:
    checks_impersonation: bool
    checks_profanity: bool
    #: 면제라면(둘 다 거짓이면) 왜 면제인지 적는다. 검사 대상이면 빈 문자열.
    exempt_reason: str = ""


#: 키: (앱 라벨, 입력 스키마 클래스 이름, 필드 이름).
RULES: dict[tuple[str, str, str], BannedWordRule] = {
    ("classroom", "JoinIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("classroom", "MemberRenameIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 클래스가 들고 있는 강사 이름 — 만들 때(#477). 로그인하지 않은
    #: 사람도 보는 가입 미리보기에 뜨므로 노출이 가장 크다(spec #474).
    ("classroom", "ClassIn", "instructor_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 같은 필드, 설정 화면에서 고칠 때(#477) — 만들 때만 막으면 그 뒤에
    #: 사칭 이름으로 바꾸면 그만이기 때문이다(참여자 이름과 같은 이유).
    ("classroom", "ClassPatchIn", "instructor_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 공동 강사가 수락할 때 정하는, 이 클래스에서 불릴 강사 이름(#561) — 소유자의
    #: 강사 이름과 같은 자리라 같은 검사를 건다.
    ("classroom", "CoInstructorAcceptIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 강사가 나중에 바꾸는 자기 강사 이름(#565) — 위 둘과 같은 자리라 같은 검사를 건다.
    ("classroom", "InstructorNameIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 템플릿 공개자 이름(#477) — 문제 템플릿 공개(`publish_template`)와
    #: 클래스 템플릿 공개(`publish_class_template`)가 같은 입력 스키마를
    #: 쓰므로 한 줄이 둘 다 검사한다.
    ("classroom", "PublishTemplateIn", "publisher_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("accounts", "SponsorProfileIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("accounts", "DeveloperProfileIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    # --- 공개 제목·본문(#479) — 사칭 목록은 걸지 않는다 ------------------------
    ("contests", "ContestCreateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestCreateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "FreeContestCreateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "FreeContestCreateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestUpdateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestUpdateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ClassIn", "name"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ClassPatchIn", "name"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemPatchIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemPatchIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # 공모전 문제의 수업용 안내(#548) — 참여자 화면에서 설명 위에 보이는 공개 본문이라 설명과
    # 같은 검사를 건다(`problem_authoring.reject_banned_public_text`).
    ("classroom", "ProblemPatchIn", "instructor_note"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ChecklistItemIn", "label"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ChecklistItemPatchIn", "label"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # --- #480 구조 검사가 찾아낸, 앞선 티켓들이 빠뜨린 실제 공개 본문 ----------
    # 아래 여섯은 예외를 적으려 훑다가 발견했다 — 이미 검사하는 필드와 같은
    # 범주(공개 이름·공개 본문)인데 어느 티켓에도 없었다. 면제로 덮지 않고
    # 실제 검사를 걸었다(`classroom.api`·`classroom.template_api`·
    # `contests.api`·`accounts.api`).
    #
    # 가져가는 사람이 새로 붙이는 클래스 이름 — `ClassIn.name`과 같은 필드다.
    ("classroom", "ImportClassTemplateIn", "name"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # 채점 지침 "custom" 문장 — 참여자도 어떤 기준으로 판정되는지 알고
    # 제출해야 하므로(#385 User Story 18) 체크리스트 항목과 같은 노출이다.
    ("classroom", "ProblemIn", "grading_guideline_text"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemPatchIn", "grading_guideline_text"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # 공모전 요구사항 문구 — 상세 화면에서 제목·설명과 나란히, 로그인 없이
    # 보인다(`ContestDetailOut.requirements`).
    ("contests", "RequirementIn", "text"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "RequirementCreateIn", "text"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "RequirementUpdateIn", "text"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # 개최자·개발자 공개 프로필의 소개글 — `display_name`과 같은 화면(공모전
    # 목록·상세, 공개 개발자 프로필)에 뜨는 공개 본문이다. 이름이 아니라
    # 본문이라 사칭 목록은 걸지 않는다(`accounts.api._reject_if_banned_bio`).
    ("accounts", "SponsorProfileIn", "bio"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("accounts", "DeveloperProfileIn", "bio"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    # --- 운영자 표면 — 운영진이 진짜 운영진이라 사칭이 성립하지 않고, ---------
    # 신고된 표현을 그대로 인용해야 할 때가 있다(spec #474).
    ("notifications", "SendOperatorNoticeIn", "title"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자 공지 제목 — 운영진이 진짜 운영진이라 사칭이 성립하지 않고, "
            "신고된 표현을 그대로 인용해야 할 때가 있다(spec #474)."
        ),
    ),
    ("notifications", "SendOperatorNoticeIn", "body"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자 공지 본문 — 운영자 공지 제목과 같은 이유(spec #474)."
        ),
    ),
    ("notifications", "SendOperatorNoticeIn", "image_object_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="스토리지 object key — 사람이 짓는 문구가 아니라 식별자다.",
    ),
    ("appeals", "AppealRulingIn", "decision"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            '"uphold"|"reject" 중 하나로 고정된 값이다 — 자유 텍스트가 아니다.'
        ),
    ),
    ("appeals", "AppealRulingIn", "ruling_note"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "이의 심판 사유 — 운영자만 쓰고(`AppealOut.ruling_note`로 이의를 "
            "제기한 당사자에게만 보인다), 운영진이 진짜 운영진이라 사칭이 "
            "성립하지 않으며 신고된 표현을 그대로 인용해야 할 때가 있다"
            "(spec #474)."
        ),
    ),
    ("classroom", "ModerationDecisionIn", "decision"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            '"takedown"|"dismiss" 중 하나로 고정된 값이다 — '
            "`appeals.AppealRulingIn.decision`과 같은 관용구."
        ),
    ),
    ("classroom", "ModerationDecisionIn", "note"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "신고된 템플릿에 대한 운영자 모더레이션 사유 — "
            "`appeals.AppealRulingIn.ruling_note`와 같은 이유(spec #474 운영자 "
            "표면), 신고된 표현을 그대로 인용해야 할 때가 있다."
        ),
    ),
    ("contests", "DeliverableTypeCreateIn", "name"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자만 만드는 기준데이터(산출물 종류) 이름 — 운영진이 진짜 "
            "운영진이라 사칭이 성립하지 않는다(spec #474 운영자 표면)."
        ),
    ),
    ("contests", "DeliverableTypeCreateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "DeliverableTypeUpdateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "DeactivateDeliverableTypeIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "CategoryCreateIn", "name"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자만 만드는 기준데이터(카테고리) 이름 — "
            "`DeliverableTypeCreateIn.name`과 같은 이유(spec #474 운영자 표면)."
        ),
    ),
    ("contests", "CategoryCreateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정책·기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "CategoryRenameIn", "name"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자만 만드는 기준데이터(카테고리) 이름 — "
            "`DeliverableTypeCreateIn.name`과 같은 이유(spec #474 운영자 표면)."
        ),
    ),
    ("contests", "CategoryRenameIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정책·기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "DeactivateCategoryIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정책·기준데이터 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("contests", "SetHostingPermissionIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정책 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("policies", "PolicyUpdateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정책 변경 사유 — 운영자 표면(spec #474).",
    ),
    ("ledger", "JournalEntryIn", "memo"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "운영자 전용 원장 API(`ledger.api` 모듈 docstring "
            '"운영자 전용 원장 API")의 분개 메모 — 운영자 표면(spec #474).'
        ),
    ),
    ("accounts", "OperatorCreateIn", "username"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "Operator 계정 아이디 — 이름·본문처럼 남에게 보이는 자리가 아니고, "
            "운영자 자신을 만드는 값이라 사칭이 성립하지 않는다."
        ),
    ),
    ("accounts", "OperatorCreateIn", "password"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="자격증명 — 화면에 노출되지 않는다.",
    ),
    ("accounts", "OperatorLoginIn", "username"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="자격증명 — 화면에 노출되지 않는다.",
    ),
    ("accounts", "OperatorLoginIn", "password"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="자격증명 — 화면에 노출되지 않는다.",
    ),
    # --- 당사자만 읽는 글 — 운영자만 읽고, 화난 사람이 권리를 행사하는 길이라 --
    # 낱말로 막을 자리가 아니다(spec #474).
    ("appeals", "AppealCreateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "이의제기 사유 — 운영자만 읽고, 화난 사람이 권리를 행사하는 길이라 "
            "낱말로 막을 자리가 아니다(spec #474)."
        ),
    ),
    ("classroom", "ReportTemplateIn", "reason"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "템플릿 신고 사유 — 이의제기 사유와 같은 이유, 운영자만 읽는다"
            "(spec #474)."
        ),
    ),
    # --- 자유 텍스트가 아니다 — 식별자·URL·object key·자격증명·토큰 등 --------
    ("accounts", "SocialLoginIn", "access_token"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="소셜 로그인 벤더가 발급한 액세스 토큰 — 식별자.",
    ),
    ("accounts", "RefreshIn", "refresh"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="JWT refresh 토큰 — 식별자.",
    ),
    ("accounts", "LogoutIn", "refresh"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="JWT refresh 토큰 — 식별자.",
    ),
    ("verification", "VerifyIn", "verification_token"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="본인확인 벤더가 발급한 토큰 — 식별자.",
    ),
    ("verification", "CiLookupIn", "ci"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="본인확인 연계정보(CI) — 벤더가 발급하는 식별자.",
    ),
    ("payouts", "IdentitySubmitIn", "resident_registration_number"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="주민등록번호 — 숫자 13자리 패턴으로만 검증되는 식별자.",
    ),
    ("payouts", "SellerContactSubmitIn", "email"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="셀러 등록 연락처(이메일) — 식별자, 형식만 검증한다.",
    ),
    ("payouts", "SellerContactSubmitIn", "phone_number"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="셀러 등록 연락처(전화번호) — 숫자 패턴 식별자.",
    ),
    ("classroom", "OpenAIKeyIn", "api_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="강사가 넣는 OpenAI API 키 — 자격증명, 화면에 노출되지 않는다.",
    ),
    ("classroom", "ClassPatchIn", "default_model"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="채점 모델 식별자 — 벤더가 정한 모델 이름 중 하나.",
    ),
    ("classroom", "ClassPatchIn", "default_reasoning_effort"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"low"|"medium"|"high" 중 하나로 고정된 값이다.',
    ),
    ("classroom", "ProblemIn", "model"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="채점 모델 식별자 — `ClassPatchIn.default_model`과 같다.",
    ),
    ("classroom", "ProblemPatchIn", "model"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="채점 모델 식별자 — `ClassPatchIn.default_model`과 같다.",
    ),
    ("classroom", "ProblemIn", "reasoning_effort"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"low"|"medium"|"high" 중 하나로 고정된 값이다.',
    ),
    ("classroom", "ProblemPatchIn", "reasoning_effort"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"low"|"medium"|"high" 중 하나로 고정된 값이다.',
    ),
    ("classroom", "ProblemIn", "grading_strictness"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            '"strict"|"normal"|"lenient"|"custom" 중 하나로 고정된 값이다 — '
            "직접 입력 문장은 `grading_guideline_text`가 따로 검사한다."
        ),
    ),
    ("classroom", "ProblemPatchIn", "grading_strictness"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            '"strict"|"normal"|"lenient"|"custom" 중 하나로 고정된 값이다 — '
            "직접 입력 문장은 `grading_guideline_text`가 따로 검사한다."
        ),
    ),
    ("classroom", "ProblemIn", "submission_formats"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="제출 형식 목록 — 정해진 값 집합 중에서만 고른다.",
    ),
    ("classroom", "ProblemPatchIn", "submission_formats"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="제출 형식 목록 — 정해진 값 집합 중에서만 고른다.",
    ),
    ("classroom", "ClassroomSubmissionIn", "submission_format"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="정해진 값 집합 중 하나 — 문제가 연 형식이어야 422를 피한다.",
    ),
    ("classroom", "ClassroomSubmissionIn", "value"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="storage object_key 또는 GitHub URL — 식별자.",
    ),
    ("classroom", "ClassroomSubmissionIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("contests", "RequirementIn", "grade"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"required"|"optional" 중 하나로 고정된 값이다.',
    ),
    ("contests", "RequirementCreateIn", "grade"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"required"|"optional" 중 하나로 고정된 값이다.',
    ),
    ("contests", "RequirementUpdateIn", "grade"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"required"|"optional" 중 하나로 고정된 값이다.',
    ),
    ("contests", "RequirementChatMessageIn", "message"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "요구사항 AI grill 채팅 입력 — 개최자 본인만 보고 그 자리에서 AI "
            "가 소비할 뿐, 다른 사람에게 공개되는 자리가 아니다."
        ),
    ),
    ("contests", "ContestImageCreateIn", "object_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="업로드 발급 때 받은 storage object_key — 식별자.",
    ),
    ("contests", "ContestImageUploadUrlIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("notifications", "ImageUploadUrlIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("handovers", "BuildAssetIn", "kind"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="빌드 자산 종류 — 정해진 값 집합 중 하나.",
    ),
    ("handovers", "BuildAssetIn", "object_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="storage object_key — 식별자.",
    ),
    ("handovers", "BuildAssetIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("handovers", "BuildAssetIn", "label"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "빌드 자산 설명 — Sponsor의 인수 확인 화면에만 뜬다, 당사자(개발자·"
            "개최자) 간에만 보이고 공개 노출이 없다. v1 적용 범위(spec #474) 밖."
        ),
    ),
    ("payments", "ConfirmPaymentIn", "simulate"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "fake PG 전용 시나리오 선택 — 실물 어댑터에서는 무시된다(ADR-0007, "
            "CLAUDE.md 「tick 은 시간을 앞당기지 않는다」의 `params` 와 같은 원칙)."
        ),
    ),
    ("payments", "ConfirmPaymentIn", "payment_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="실물 PG(토스)가 발급한 결제 건 식별자.",
    ),
    ("contests", "ConfirmJudgingExtensionIn", "simulate"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="fake PG 전용 시나리오 선택 — `ConfirmPaymentIn.simulate`와 같다.",
    ),
    ("contests", "ConfirmJudgingExtensionIn", "payment_key"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="실물 PG가 발급한 결제 건 식별자 — `ConfirmPaymentIn.payment_key`와 같다.",
    ),
    ("payouts", "ConfirmPayoutIn", "simulate"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="fake 지급대행 어댑터 전용 시나리오 선택(ADR-0007).",
    ),
    ("payouts", "ConfirmPayoutIn", "seller_simulate"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="fake Seller 등록 어댑터 전용 시나리오 선택(ADR-0007).",
    ),
    ("payouts", "SellerRegistrationRetryIn", "simulate"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="fake Seller 등록 어댑터 전용 시나리오 선택 — `ConfirmPayoutIn.seller_simulate`와 같다.",
    ),
    ("payments", "WebhookIn", "webhook_id"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="PG 벤더 웹훅 페이로드 — 사람이 입력하지 않는다, 식별자.",
    ),
    ("payments", "WebhookIn", "status"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"paid"|"failed"|"refunded"|"refund_failed" 중 하나 — 벤더 웹훅.',
    ),
    ("payments", "WebhookIn", "signature"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="HMAC-SHA256 서명 — 벤더 웹훅, 사람이 입력하지 않는다.",
    ),
    ("payouts", "WebhookIn", "webhook_id"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="지급대행 벤더 웹훅 페이로드 — `payments.WebhookIn.webhook_id`와 같다.",
    ),
    ("payouts", "WebhookIn", "status"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"paid"|"failed" 중 하나 — 벤더 웹훅.',
    ),
    ("payouts", "WebhookIn", "signature"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="HMAC-SHA256 서명 — 벤더 웹훅, 사람이 입력하지 않는다.",
    ),
    ("submissions", "EvidenceIn", "kind"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"video_timestamp"|"screenshot"|"demo_path"|"source_location" 중 하나.',
    ),
    ("submissions", "EvidenceIn", "value"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "근거가 가리키는 위치(타임스탬프·경로 등) — 제출자 본인과 개최자"
            "(심사)만 보고 다른 참가자나 공개 화면에는 노출되지 않는다. v1 "
            "적용 범위(spec #474) 밖."
        ),
    ),
    ("submissions", "RequirementResponseIn", "note"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "요구사항 자가 응답 메모 — `EvidenceIn.value`와 같은 이유로 제출자 "
            "본인과 개최자만 본다. v1 적용 범위(spec #474) 밖."
        ),
    ),
    ("submissions", "SubmissionAssetIn", "kind"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="자료 종류 — 정해진 값 집합 중 하나(SOURCE·REPOSITORY·DEMO_VIDEO 등).",
    ),
    ("submissions", "SubmissionAssetIn", "value"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="storage object_key 또는 외부 URL — 식별자.",
    ),
    ("submissions", "SubmissionAssetIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("submissions", "SubmissionAssetIn", "test_account"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "데모 열람용 테스트 계정 자격증명 — 제출자 본인과 개최자만 보고, "
            "마감 후 공개되는 자료에서도 이 필드만은 빠진다"
            "(`AssetSummaryOut` docstring)."
        ),
    ),
    ("submissions", "SubmissionAssetIn", "label"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason=(
            "마감 후 공개 프로필·심사 비교 화면에도 뜨는 자료 라벨이다 — "
            "이름·공개 제목/본문 다섯 자리(spec #474 v1 표)와 다른 범주라 "
            "이 표에 없고, 이 티켓 범위 밖이다. 아직 검사하지 않는다."
        ),
    ),
    # 「공모전에도 내기」(#549) — 공모전 직접 제출의 같은 칸(`submissions` 의 EvidenceIn·
    # RequirementResponseIn·SubmissionAssetIn)을 강의실 쪽 스키마로 받는다. 이유도 그대로다.
    ("classroom", "ContestEntryEvidenceIn", "kind"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason='"video_timestamp"|"screenshot"|"demo_path"|"source_location" 중 하나.',
    ),
    ("classroom", "ContestEntryEvidenceIn", "value"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="`submissions.EvidenceIn.value` 와 같다 — 제출자 본인과 개최자만 본다.",
    ),
    ("classroom", "ContestEntryResponseIn", "note"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="`submissions.RequirementResponseIn.note` 와 같다 — 제출자 본인과 개최자만 본다.",
    ),
    ("classroom", "ContestEntryAssetIn", "kind"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="선택 자료 종류 — demo_url·demo_video·screenshot 중 하나.",
    ),
    ("classroom", "ContestEntryAssetIn", "value"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="storage object_key 또는 외부 URL — 식별자.",
    ),
    ("classroom", "ContestEntryAssetIn", "content_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="MIME 타입 — 식별자.",
    ),
    ("classroom", "ContestEntryAssetIn", "label"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="`submissions.SubmissionAssetIn.label` 과 같다 — 아직 검사하지 않는 범주.",
    ),
    # 연결된 앱의 동의 화면이 「허락」·「거절」을 보낼 때(#512, ADR-0052) — 전부 외부
    # 앱이 인가 요청에 실어 온 OAuth 값을 그대로 되돌려 보내는 자리다.
    ("classroom", "AuthorizationDecisionIn", "client_id"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "redirect_uri"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "response_type"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "code_challenge"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "code_challenge_method"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "state"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "scope"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
    ("classroom", "AuthorizationDecisionIn", "resource"): BannedWordRule(
        checks_impersonation=False,
        checks_profanity=False,
        exempt_reason="OAuth 인가 요청의 식별자·주소·PKCE 값 — 사람이 짓는 문구가 아니다.",
    ),
}
