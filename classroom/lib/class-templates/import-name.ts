// 클래스 템플릿을 가져갈 때 새 클래스 이름 칸의 기본값(#1455 4번) — 원본과 같은 이름이면 「대상 클래스」
// select 에 같은 이름이 둘 보이므로 「(가져옴)」 꼬리를 붙인다. 클래스 이름 한도(200자)를 넘으면 원본 쪽을 자른다.

export const CLASS_NAME_MAX_LENGTH = 200;
export const IMPORTED_SUFFIX = " (가져옴)";

export function defaultImportName(templateName: string): string {
  const room = CLASS_NAME_MAX_LENGTH - IMPORTED_SUFFIX.length;
  const base = templateName.length > room ? templateName.slice(0, room).trimEnd() : templateName;
  return `${base}${IMPORTED_SUFFIX}`;
}
