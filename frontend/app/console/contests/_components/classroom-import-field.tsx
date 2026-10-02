// 무료 공모전의 「클래스에서 들여오기」 허용 (#547, ADR-0054) — 개최 폼과 브리프 수정 패널이
// 함께 쓴다. 켜면 강사가 이 공모전을 클래스의 문제로 들여오고, 그 참여자가 낸 풀이를 이
// 공모전에도 낼 수 있다(CONTEXT.md 「공모전 문제」). 유료 공모전에는 그리지 않는다.

export function ClassroomImportField({
  checked,
  onChange,
  testId,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  testId: string;
}) {
  return (
    <label className="flex items-start gap-2 border border-rule px-3 py-2 text-sm" data-testid={testId}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        data-testid={`${testId}-checkbox`}
        className="mt-1"
      />
      <span className="flex flex-col gap-0.5">
        <span>클래스에서 들여오기 허용</span>
        <span className="text-xs text-ink/60">
          강사가 이 공모전을 자기 클래스의 문제로 들여오고, 그 클래스의 참여자가 낸 풀이를 이 공모전에도 낼 수 있습니다.
          클래스에서 온 제출도 직접 낸 제출과 같은 규칙으로 채점됩니다.
        </span>
      </span>
    </label>
  );
}
