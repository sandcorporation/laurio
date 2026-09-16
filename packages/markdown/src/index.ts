// 설명 마크다운을 그리는 공유 렌더러(#313, ADR-0047 — 2026-09-16 에 강의실에서
// 워크스페이스 패키지로 옮겼다).
//
// **강의실의 문제 설명과 공개 앱의 공모전 설명이 같은 것을 그린다** — 둘 다 사람이
// 마크다운으로 적은 설명이고, 코드블록을 복사하거나 파일로 받는 필요도 같다. 복사해
// 두면 갈라지므로(#166 이 세운 「손으로 관리되는 목록」 비용을 알면서도) 패키지로
// 뽑았다: 허용 목록 스키마가 두 벌이 되면 한쪽만 조여지는 날이 온다.
//
// 이 진입점은 **서버에서 그릴 수 있는 것만** 내보낸다. 손이 필요한 조각은
// `@codemit/markdown/client` 에 있고 `MarkdownView` 가 알아서 쓴다.
export { MarkdownView } from "./view";
export { parseDescription } from "./parse";
export { codeTextOf } from "./code-copy";
export { downloadNameFor, extensionFor } from "./code-files";
