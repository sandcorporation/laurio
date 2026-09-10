"""storage target_ref의 슬롯 이름 — 두 제품이 공유한다 (#270, ADR-0039).

**슬롯 이름만 여기 있다.** target_ref 전체 형식(지금은
``"submission:<contest_id>:<developer_user_id>:<slot>"``, 공모전 모양이다)을
조립하는 함수는 `contests.submission_target_refs`로 옮겨갔다 — 그 형식이
`contest_id`를 품고 있어 강의실이 자기 형식을 더할 때는 다른 모양이 필요하기
때문이다(ADR-0039). 슬롯 **이름**(`source`·`demo-video`·`screenshot`·
`build-asset`)은 `SubmissionAsset.Kind`에 매인 값이라 제품과 무관하게 공유되고,
`submissions.resolvers.SubmissionTargetStateResolver`가 그 이름으로 슬롯을
가른다.
"""

from __future__ import annotations

SOURCE_SLOT = "source"
DEMO_VIDEO_SLOT = "demo-video"
# 스크린샷(#264, ADR-0036) — 마감 전 비공개·마감 후 공개라는 점에서 DEMO_VIDEO_SLOT과
# 같은 취급이다(`submissions.resolvers.SubmissionTargetStateResolver`의 "그 외 슬롯"
# 분기가 그대로 적용된다). 다만 파일이 사는 버킷은 여전히 private다 — `ContestImage`의
# 공개 버킷과는 다르다(ADR-0032/0036).
SCREENSHOT_SLOT = "screenshot"
# Award 이후 Developer가 추가로 올리는 빌드 자산(빌드 설정·서명키·스토어 메타데이터·
# 실행 문서, #14 Handover). SOURCE_SLOT과 같은 이유로 별도 슬롯을 둔다 — 소스와
# 가시성 판정 시점이 다르기 때문은 아니고(둘 다 Award 이후 Sponsor에게 열린다),
# 여러 파일이 한 target_ref 네임스페이스 아래 쌓일 수 있어야 해서다(각 업로드가
# 고유한 object_key를 받으므로 이름이 겹쳐도 안전하다).
BUILD_ASSET_SLOT = "build-asset"
