// 설명의 코드를 클립보드로 복사한다(2026-09-15) — 참여자가 제공 데이터(지도·CSV
// 등)를 손으로 드래그하지 않고 버튼 하나로 자기 에디터에 붙여넣게 한다.
//
// 복사할 글자는 화면이 그린 그 트리(`parseDescription` 결과)에서 뽑는다 —
// 원문 마크다운을 다시 자르면 화면에 보이는 코드와 복사되는 코드가 갈릴 수 있다.
import type { ElementContent, Element } from "hast";

function collect(nodes: ElementContent[]): string {
  let text = "";
  for (const node of nodes) {
    if (node.type === "text") text += node.value;
    else if (node.type === "element") text += collect(node.children);
  }
  return text;
}

/** `<pre>`·`<code>` 안의 글자 전부. 코드블록 끝에 붙는 줄바꿈 하나는 뺀다. */
export function codeTextOf(node: Element): string {
  return collect(node.children).replace(/\n$/, "");
}

/**
 * 클립보드에 쓴다. 성공하면 true. `navigator.clipboard` 는 보안 컨텍스트(https·
 * localhost)에서만 있으므로, 없으면 숨긴 textarea 와 `execCommand("copy")` 로
 * 한 번 더 시도한다.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 권한 거부 등 — 아래 대체 경로로 간다.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
