# 연결된 앱의 OAuth·MCP 몸을 공유층으로 올리고, 허락에 범위를 단다

Status: Accepted (2026-11-05 결정)

## 맥락 (#870)

연결된 앱(ADR-0052)은 강의실에만 있었다. 허락·토큰·확인 표(`ConnectedApp`·`OAuthClient`·
`OAuthToken`·`OAuthAuthorizationCode`·`ConnectedAppConfirmation`)도, OAuth 2.1 인가 서버도, MCP
JSON-RPC 디스패치도 `classroom` 앱 안에 있었다.

대표가 무료 공모전을 MCP 로 만들고 고치게 하기로 했다(#870). 인증은 「강의실 자체 OAuth 2.1 을
넓힌다」로 정해졌다 — 새 범위 `contests`, 새 MCP 자원(공개 앱의 `/mcp`), 허락은 사용자 본인
계정. 그런데 앱 경계 규칙 A(ADR-0037)는 공모전 가족이 강의실을 임포트하는 것을 예외 없이 막는다.

## 결정

1. **모델 다섯을 `core` 로 옮긴다 — 테이블은 그대로.** `db_table` 로 `classroom_*` 이름을 붙들고,
   `core.0005`·`classroom.0035` 가 상태만 옮긴다(DB 연산 없음). 강의실 대상(클래스·문제)을 적는
   쓰기 기록 `ConnectedAppWrite` 는 강의실에 남는다.
2. **허락에 범위(`ConnectedApp.scope`)를 단다** — `classroom` 또는 `contests`. 같은 외부 앱이라도
   범위마다 따로 허락한다. 토큰은 그 자원의 주소(`resource`)에 묶이고, 토큰 확인은 허락의 범위도
   본다 — 강의실 토큰으로 공모전 MCP 를 부를 수 없고 그 반대도 같다. 기존 행은 `db_default` 로
   `classroom` 이 된다.
3. **엔진은 공유층, 자원은 기능 앱.** `core.oauth`(인가 서버)·`core.oauth_views`(규격 뷰 한 벌을
   만드는 팩토리)·`core.mcp_server`(JSON-RPC·두 세대·호출 상한·쓰기 기록 트랜잭션)·`core.mcp_tool`·
   `core.mcp_confirmation` 이 몸이다. 기능 앱은 `OAuthResource`(범위·공개 오리진 설정·이름)와
   `McpServer`(도구 등록부·안내문·쓰기 기록 함수·상한 설정·입장 검사)를 하나씩 만든다.
4. **만료 스캔과 탈퇴·휴면 끊기는 `core` 가 맡는다** — 허락이 거기 있으므로. 탈퇴·휴면은 범위를
   가리지 않고 그 계정의 허락을 모두 끊는다. 스캔 이름은 처음 생긴 그대로다.
5. **입장 검사(`McpServer.admit`)** — 토큰이 살아 있어도 지금 그 일을 할 자격이 없으면(공모전
   개최 권한 회수) 모든 메서드를 403 으로 거절한다. 강의실은 쓰지 않는다.

## 결과

- 강의실 MCP·OAuth 의 바깥 동작은 바뀌지 않는다 — 같은 주소, 같은 응답, 같은 호출 상한 키.
- `ConnectedApp.instructor` 라는 필드 이름은 강의실에서 시작한 역사로 남는다 — 공모전 범위에서는
  허락한 계정(개최 자격자 본인)이다.
- 공모전 MCP 는 이 위에 자기 자원과 도구만 더하면 된다(#870 의 둘째 PR).
