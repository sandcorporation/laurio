"use client";

// 과제 만들기 (#207, ADR-0028/0029) — 본인확인도 결제도 요구하지 않는다.
//
// `/console/contests/new`(공모전 브리프)와 같은 자리지만 카테고리·상금이 없고
// 본인확인 게이트도 없다 — 있는 것은 자격 게이트뿐이고, 그마저 이 화면이 직접
// 확인하지 않는다: `POST /api/backend/assignments`가 자격 없는 계정을 403으로
// 거부하면 그 메시지를 그대로 보여준다(백엔드가 유일한 판정자다).
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";

type DeliverableType = { id: number; name: string; minimum_prize: number };

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; deliverableTypes: DeliverableType[] };

type AssignmentForm = {
  title: string;
  deliverableTypeIds: number[];
  deadlineAt: string;
  description: string;
};

const EMPTY_FORM: AssignmentForm = {
  title: "",
  deliverableTypeIds: [],
  deadlineAt: "",
  description: "",
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function NewAssignmentPage() {
  const session = useSession();
  const router = useRouter();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [form, setForm] = useState<AssignmentForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    void bffClient.get<unknown>("/api/backend/contests/deliverable-types").then((result) => {
      if (cancelled) return;
      if (!result.ok || !Array.isArray(result.data)) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }
      setLoad({ status: "ready", deliverableTypes: result.data as DeliverableType[] });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="new-assignment-loading">불러오는 중...</p>
      </main>
    );
  }
  if (session.status === "unauthenticated") return null;

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="new-assignment-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  const { deliverableTypes } = load;

  function toggleDeliverableType(id: number) {
    setForm((prev) => ({
      ...prev,
      deliverableTypeIds: prev.deliverableTypeIds.includes(id)
        ? prev.deliverableTypeIds.filter((x) => x !== id)
        : [...prev.deliverableTypeIds, id],
    }));
  }

  async function handleCreate() {
    setCreateError(null);

    const title = form.title.trim();
    if (!title) {
      setCreateError("제목을 입력해주세요.");
      return;
    }
    if (form.deliverableTypeIds.length === 0) {
      setCreateError("산출물 종류를 하나 이상 선택해주세요.");
      return;
    }
    if (!form.deadlineAt) {
      setCreateError("마감 기한을 선택해주세요.");
      return;
    }

    setCreating(true);
    try {
      const created = await bffClient.post<unknown>("/api/backend/assignments", {
        title,
        deliverable_type_ids: form.deliverableTypeIds,
        description: form.description,
        deadline_at: new Date(form.deadlineAt).toISOString(),
        requirements: [],
      });

      if (!created.ok) {
        setCreateError(created.detail);
        return;
      }
      if (!isPlainRecord(created.data) || typeof created.data.id !== "number") {
        setCreateError("과제 생성 응답을 해석하지 못했습니다. 다시 시도해 주세요.");
        return;
      }

      router.push(`/console/assignments/${created.data.id}`);
    } catch {
      setCreateError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col gap-6 p-10">
      <div>
        <p className="text-xs font-medium tracking-widest text-ink/60">과제 만들기</p>
        <h1 className="text-2xl font-semibold" data-testid="new-assignment-heading">
          기본 정보를 알려주세요
        </h1>
        <p className="mt-2 text-sm text-ink/70">
          상금·결제·본인확인 없이 InviteCode로만 여는 과제입니다.
        </p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        제목
        <input
          value={form.title}
          onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
          maxLength={200}
          data-testid="new-assignment-title"
          className="border border-rule bg-surface px-3 py-2"
        />
      </label>

      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="mb-1">산출물 종류 · 복수 선택</legend>
        {deliverableTypes.map((dt) => (
          <label
            key={dt.id}
            className="flex items-center justify-between border border-rule px-3 py-2"
            data-testid={`new-assignment-deliverable-type-${dt.id}`}
          >
            <span className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.deliverableTypeIds.includes(dt.id)}
                onChange={() => toggleDeliverableType(dt.id)}
                data-testid={`new-assignment-deliverable-type-${dt.id}-checkbox`}
              />
              {dt.name}
            </span>
          </label>
        ))}
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        마감 기한
        <input
          type="datetime-local"
          value={form.deadlineAt}
          onChange={(event) => setForm((prev) => ({ ...prev, deadlineAt: event.target.value }))}
          data-testid="new-assignment-deadline"
          className="border border-rule bg-surface px-3 py-2"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        설명 (선택)
        <textarea
          value={form.description}
          onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
          rows={3}
          data-testid="new-assignment-description"
          className="border border-rule bg-surface px-3 py-2"
        />
      </label>

      {createError && (
        <p role="alert" data-testid="new-assignment-error" className="text-sm text-attention">
          {createError}
        </p>
      )}

      <button
        type="button"
        onClick={() => void handleCreate()}
        disabled={creating}
        data-testid="new-assignment-submit"
        className="w-fit border border-ink bg-ink px-6 py-2 text-sm text-paper disabled:opacity-50"
      >
        {creating ? "만드는 중..." : "과제 만들기"}
      </button>
    </main>
  );
}
