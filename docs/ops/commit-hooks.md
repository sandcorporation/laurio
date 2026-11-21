# 커밋 훅

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

**백엔드를 고치고 타입 재생성을 잊으면, 예전에는 push 하고 6분 뒤 CI 에서야
알았다**(#272). 지금은 `.githooks/pre-commit` 이 저장소에 커밋되어 있고, 루트
`package.json` 의 `postinstall` 이 `git config core.hooksPath .githooks` 한
줄로 그것을 건다 — `pnpm install` 이 이미 Orca 셋업 훅이자 Dockerfile 단계라
저절로 깔린다. **`.git` 이 없는 환경(Docker 빌드 단계)에서는 그 한 줄이
`|| true` 로 실패를 삼킨다** — 이미지를 굽는 데는 훅이 필요 없다.
`core.hooksPath` 가 **상대 경로**라 워크트리마다 자기 디렉터리 기준으로
풀리므로 워크트리는 손댈 것 없이 공짜로 따라온다.

훅이 매 커밋 하는 일 넷:

- **배경 진단 세션이면**(브랜치가 `auto-` 로 시작하거나 `CODEMIT_UNATTENDED=1`)
  `CLAUDE.md`·`docs/ops/`·`CONTEXT.md`·`docs/features/`·`docs/adr/` 가 staged 된 커밋을 **거절한다**
  (2026-09-18) — 위 「그 오류를 에이전트가 집어 진단한다」의 게이트다. 사람이 쓰는
  브랜치(`main`·`chain-*`·`int-*`)는 영향을 받지 않는다.

- `backend/**/*.py` 가 **staged 일 때만** `scripts/pre_commit_backend_checks.sh` 를 먼저 돈다(#1226) —
  CI 에서야 잡히던 실수를 당긴다. 앞이 실패하면 뒤는 안 돈다:
  1. **문법** — `scripts/check_staged_python_syntax.py`(`ast.parse`, 닫히지 않은 docstring 은 CI `plan` 잡이 잡던 것).
  2. **Django 검사** — `manage.py check --fail-level WARNING`(CI `checks static` 과 같다). 같은 잡의
     `check --deploy`(운영 설정 필요)·마이그레이션 호환(DB 필요)은 뺐다.
  3. **DB 없이 도는 구조 시험 셋** — `test_banned_word_field_registration`(새 입력 필드를 금칙어 표에
     등록했나)·`test_app_boundaries`·`test_classroom_instructor_scope_structure`. `-n 0` 으로 DB 템플릿을
     미리 만들지 않고, `CODEMIT_TEST_ENTRY` 로 `scripts/test.sh` 의 칸 대기를 건너뛴다(DB 를 안 쓰는 2초라 칸을
     잡을 까닭이 없다). 새 「등록 누락」 구조 시험이 생기면 이 스크립트의 목록에 더한다.

  더하는 시간은 **백엔드 파일 하나 staged 기준 약 2.5초**(따뜻한 `uv` 환경, 3회 재서 2.51·2.54·2.54초).
  뒤따르는 타입 재생성은 그대로다. 훅이 세 실수를 거절하는지는 `python3 scripts/test_pre_commit_backend.py`
  (임시 index 에 심어 돌린다 — CI 이미지에는 `.git` 이 없어 PR 검사에는 걸지 않았다).
- `backend/**/*.py` 가 **staged 일 때만** `pnpm --dir frontend generate:api`
  를 돌려 `packages/bff-client/src/schema.gen.ts` 를 재생성하고, 바뀌었으면
  자동으로 같이 스테이징한다(생성물이라 사람이 리뷰할 것이 없다) — 문서만
  고친 커밋은 이 2.1초를 안 낸다. 재생성 명령이 실패하면 커밋을 거절한다.
- **항상** `check_adr_status.py`·`check_screen_language.py`·
  `check_backend_error_language.py`·`check_test_waits.py`(시험의 고정 대기, #808) 네 검사를 돈다(합쳐 0.4초) — 하나라도
  걸리면 커밋을 거절한다.

**`git commit --no-verify` 로 넘어갈 수 있다** — 훅은 피드백을 6분에서 몇
초로 당기는 장치일 뿐 문이 아니다. `frontend-openapi-types`·`adr-status`·
`screen-language` CI 잡은 그대로 진짜 문이고, 이 훅이 그것들을 대체하지
않는다 — 셋 다 지우지 않았다. 훅 프레임워크(husky·lefthook 등)는 쓰지
않는다, 셸 스크립트 하나면 되는 일에 의존성을 더할 값이 없다.
