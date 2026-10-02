"use client";

// 「사용 현황」의 기간 입력(#494) — 시작일·종료일을 고르고 「보기」를 누르면
// `onApply` 가 부른다. 기간은 주소에 살므로(lib/usage/period.ts) 부르는 화면이
// 주소를 바꾸고, 주소가 바뀌면 표가 다시 온다. 입력칸의 처음 값은 `initial` 이고,
// 부르는 쪽이 `key` 를 바꾸면 그 값으로 다시 태어난다.
import { type FormEvent, useState } from "react";

import type { UsagePeriod } from "@/lib/usage/period";

const INPUT_CLASS = "border border-rule bg-paper px-[11px] py-[7px] text-[13px] text-ink";

export function UsagePeriodForm({
  initial,
  onApply,
}: {
  initial: UsagePeriod;
  onApply: (period: UsagePeriod) => void;
}) {
  const [from, setFrom] = useState(initial.from ?? "");
  const [to, setTo] = useState(initial.to ?? "");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onApply({ from: from || null, to: to || null });
  }

  return (
    <form onSubmit={handleSubmit} data-testid="usage-period-form" className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-[5px]">
        <span className="text-[11.5px] text-ink/45">시작일</span>
        <input
          type="date"
          data-testid="usage-period-from"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          className={INPUT_CLASS}
        />
      </label>
      <label className="flex flex-col gap-[5px]">
        <span className="text-[11.5px] text-ink/45">종료일</span>
        <input
          type="date"
          data-testid="usage-period-to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          className={INPUT_CLASS}
        />
      </label>
      <button type="submit" data-testid="usage-period-apply" className="bg-ink px-4 py-2 text-[13px] font-medium text-paper">
        보기
      </button>
    </form>
  );
}
