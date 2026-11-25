// 칸이 처음 그려질 때 초점이 갈 곳 없이 body 에 있으면 칸이 받는다(#1431, #1436-3).
// 이미 다른 곳에 있던 초점은 빼앗지 않는다.
export function focusUnlessTaken(
  input: { focus: () => void } | null,
  doc: { activeElement: unknown; body: unknown } = document,
): void {
  if (input && doc.activeElement === doc.body) input.focus();
}
