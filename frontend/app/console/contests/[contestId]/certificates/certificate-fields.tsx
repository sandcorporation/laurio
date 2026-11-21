"use client";

// 상장 한 장의 칸 — 발급할 때와 다시 발급할 때 같은 칸을 쓴다.
import type { ReactNode } from "react";

import { FieldLabel } from "@/app/components/ui";
import { INPUT_CLASS } from "@/lib/ui/classnames";
import { FIELD_LIMITS, type CertificateTextIn } from "@/lib/certificates/types";

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 ${wide ? "sm:col-span-2" : ""}`}>
      <FieldLabel>{label}</FieldLabel>
      {children}
    </label>
  );
}

export function CertificateFields({
  value,
  onChange,
  dateMin,
  dateMax,
  testIdPrefix,
}: {
  value: CertificateTextIn;
  onChange: (next: CertificateTextIn) => void;
  dateMin: string;
  dateMax: string;
  testIdPrefix: string;
}) {
  const set = <K extends keyof CertificateTextIn>(key: K, next: CertificateTextIn[K]) =>
    onChange({ ...value, [key]: next });

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="받는 사람">
        <input
          className={INPUT_CLASS}
          value={value.recipient_name}
          maxLength={FIELD_LIMITS.recipient_name}
          onChange={(event) => set("recipient_name", event.target.value)}
          data-testid={`${testIdPrefix}-recipient-name`}
        />
      </Field>
      <Field label="상 이름">
        <input
          className={INPUT_CLASS}
          value={value.award_name}
          maxLength={FIELD_LIMITS.award_name}
          placeholder="최우수상"
          onChange={(event) => set("award_name", event.target.value)}
          data-testid={`${testIdPrefix}-award-name`}
        />
      </Field>
      <Field label="본문" wide>
        <textarea
          className={`${INPUT_CLASS} resize-none`}
          rows={2}
          value={value.body}
          maxLength={FIELD_LIMITS.body}
          onChange={(event) => set("body", event.target.value.replace(/\r?\n/g, " "))}
          data-testid={`${testIdPrefix}-body`}
        />
      </Field>
      <Field label="수여자">
        <input
          className={INPUT_CLASS}
          value={value.giver_name}
          maxLength={FIELD_LIMITS.giver_name}
          onChange={(event) => set("giver_name", event.target.value)}
          data-testid={`${testIdPrefix}-giver-name`}
        />
      </Field>
      <Field label="직함">
        <input
          className={INPUT_CLASS}
          value={value.giver_title}
          maxLength={FIELD_LIMITS.giver_title}
          onChange={(event) => set("giver_title", event.target.value)}
          data-testid={`${testIdPrefix}-giver-title`}
        />
      </Field>
      <Field label="수여 날짜">
        <input
          type="date"
          className={INPUT_CLASS}
          value={value.award_date}
          min={dateMin}
          max={dateMax}
          onChange={(event) => set("award_date", event.target.value)}
          data-testid={`${testIdPrefix}-award-date`}
        />
      </Field>
    </div>
  );
}
