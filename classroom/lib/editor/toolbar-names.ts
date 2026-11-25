// Toast UI 툴바에서 접근성 이름이 빈 단추에 이름을 준다(#1517). 라이브러리는 대부분의 단추에
// `aria-label` 을 달지만 「…」(more) 단추는 비워 둔다 — 낭독기가 이름 없는 「버튼」으로 읽는다.
const NAMES_BY_CLASS: ReadonlyArray<readonly [string, string]> = [
  ["more", "더보기"],
  ["scroll-sync", "스크롤 동기화"],
];

function hasName(button: HTMLElement): boolean {
  return Boolean(
    (button.getAttribute("aria-label") || button.getAttribute("aria-labelledby") || button.textContent || "").trim(),
  );
}

export function nameUnlabeledEditorButtons(root: ParentNode): void {
  for (const button of root.querySelectorAll<HTMLElement>("button")) {
    if (hasName(button)) continue;
    const fallback = NAMES_BY_CLASS.find(([cls]) => button.classList.contains(cls))?.[1] ?? button.getAttribute("title");
    if (fallback) button.setAttribute("aria-label", fallback);
  }
}
