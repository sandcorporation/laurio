// 상한이 있는 입력칸 아래의 글자 수(#1390) — 90% 부터 보이고, 상한에 닿으면 색만 바뀐다.
import { charCountText } from "@/lib/forms/limits";

export function CharCount({ value, limit, testId }: { value: string; limit: number; testId: string }) {
  const text = charCountText(value.length, limit);
  if (text === null) return null;
  return (
    <span
      data-testid={testId}
      className={`self-end font-mono text-[11.5px] ${value.length >= limit ? "text-error" : "text-ink/45"}`}
    >
      {text}
    </span>
  );
}
