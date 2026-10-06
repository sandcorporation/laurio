// 「추론 모델」 스위치(#602) — 호환 서버의 모델은 이름으로 추론 모델인지 알 수 없어 강사가
// 정한다. 켜면 추론 강도 칸이 열리고 채점 요청에 그 값이 실린다. 클래스 기본 모델과 문제별
// 모델이 같은 모양을 쓴다.
export function ReasoningModelSwitch({
  checked,
  onChange,
  testId,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  testId: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex items-center gap-2.5 text-[13.5px]">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          data-testid={testId}
          className="accent-ink"
        />
        추론 모델
      </label>
      <span className="text-[11.5px] leading-relaxed text-ink/45">
        이 모델이 추론 모델이면 켜세요 — 추론 강도를 정해 채점 요청에 함께 보냅니다.
      </span>
    </div>
  );
}
