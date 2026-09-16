// 코드블록을 파일로 받을 때의 이름과 확장자(2026-09-16).
//
// 과제 설명에 지도·CSV·스켈레톤 코드를 코드블록으로 싣기 시작하면서, 참여자가 그것을
// **파일로 저장**해 바로 쓰고 싶어진다. 그때 필요한 것은 두 가지다 — 「무슨 확장자로
// 줄 것인가」와 「이름을 무엇으로 할 것인가」.
//
// **언어가 적힌 블록만 파일로 받을 수 있다.** ```` ```python ```` 처럼 적혀 있으면
// `.py` 로 준다. 언어가 없으면 우리가 확장자를 지어내야 하는데, 그건 「무언가 이상한
// 확장자」를 만드는 길이라 버튼 자체를 보이지 않는다.
//
// **이름은 강사가 적을 수 있다** — ```` ```text map3-terrain.txt ```` 처럼 언어 뒤에
// 적으면 그 이름으로 받는다(지도·CSV 는 이름이 곧 약속이다). 안 적으면 문제 제목에서
// 지은 이름에 순번을 붙인다.

/** 언어 표시 → 확장자. 여기 없는 언어는 파일로 주지 않는다(버튼이 안 보인다). */
const EXTENSIONS: Record<string, string> = {
  python: "py",
  py: "py",
  java: "java",
  kotlin: "kt",
  kt: "kt",
  javascript: "js",
  js: "js",
  jsx: "jsx",
  typescript: "ts",
  ts: "ts",
  tsx: "tsx",
  c: "c",
  cpp: "cpp",
  "c++": "cpp",
  cs: "cs",
  csharp: "cs",
  go: "go",
  rust: "rs",
  rs: "rs",
  ruby: "rb",
  rb: "rb",
  php: "php",
  swift: "swift",
  sql: "sql",
  bash: "sh",
  sh: "sh",
  shell: "sh",
  json: "json",
  yaml: "yml",
  yml: "yml",
  toml: "toml",
  xml: "xml",
  html: "html",
  css: "css",
  markdown: "md",
  md: "md",
  csv: "csv",
  tsv: "tsv",
  text: "txt",
  txt: "txt",
  plaintext: "txt",
  diff: "diff",
  dockerfile: "dockerfile",
};

/** 그 언어로 받을 확장자. 모르는 언어면 null — 파일로 주지 않는다. */
export function extensionFor(language: string): string | null {
  return EXTENSIONS[language.trim().toLowerCase()] ?? null;
}

//: 강사가 적은 이름에서 받아 줄 모양 — 경로 구분자와 공백을 막는다. 디렉터리를
//: 타고 올라가는 이름(`../`)이나 숨김 파일이 브라우저 저장 대화상자에 그대로
//: 흘러가지 않게 하려는 것이다.
const SAFE_NAME = /^[A-Za-z0-9가-힣][A-Za-z0-9가-힣._-]{0,59}$/;

/** 강사가 코드블록 정보 줄에 적은 파일 이름. 쓸 수 없는 모양이면 null. */
export function fileNameFromMeta(meta: string): string | null {
  const first = meta.trim().split(/\s+/)[0] ?? "";
  if (!first || !first.includes(".")) return null;
  if (!SAFE_NAME.test(first)) return null;
  if (first.startsWith(".") || first.endsWith(".")) return null;
  return first;
}

/** 문제 제목에서 파일 이름의 몸통을 짓는다. 쓸 글자가 없으면 "code". */
export function fileBaseFromTitle(title: string): string {
  const base = (title ?? "")
    .trim()
    .replace(/[^A-Za-z0-9가-힣]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return base || "code";
}

/**
 * 이 코드블록을 받을 파일 이름. 언어를 모르면 null — 버튼을 보이지 않는다.
 *
 * 강사가 적은 이름이 있으면 그것이 이긴다. 없으면 `<문제 제목>-<순번>.<확장자>`다 —
 * 같은 설명에 블록이 여럿일 때 이름이 겹치지 않게 순번을 붙인다.
 */
export function downloadNameFor(options: {
  language: string;
  meta?: string;
  title?: string;
  index: number;
}): string | null {
  const extension = extensionFor(options.language);
  if (!extension) return null;

  const fromMeta = fileNameFromMeta(options.meta ?? "");
  if (fromMeta) return fromMeta;

  return `${fileBaseFromTitle(options.title ?? "")}-${options.index}.${extension}`;
}
