"use client";

// 무료 공모전 개최 — 브리프 (#415, ADR-0048, CONTEXT.md 「무료 공모전」·「개최
// 권한」). 유료 브리프(`../new/page.tsx`)와 같은 자리이지만 셋이 다르다 —
// 본인확인을 요구하지 않고, 그 대신 Operator가 켠 개최 권한(`HostingPermission`)
// 을 확인하며, 상금(Prize)을 아예 받지 않는다(무료 공모전은 상금·결제·Escrow
// 자체가 없다).
//
// 권한이 없으면 폼을 그리지 않고 안내만 보인다(spec #415 user story 13) —
// 헛걸음(체크리스트까지 다 쓴 뒤 만들기가 거절되는 것)을 막는다. 실제 집행자는
// 여전히 백엔드다(`POST /api/backend/contests/free`가 같은 권한을 다시
// 확인한다) — 이 확인은 화면 진입점을 감출 뿐이다.
//
// 제출하면 그 순간 Contest가 draft로 생성되고(`is_free=true`), 화면은 그
// Contest의 URL — `/console/contests/{contestId}/draft` — 로 넘어간다. 그
// 화면은 유료·무료 draft를 `contest.is_free`로 갈라 같은 곳에서 이어받는다
// (요구사항 체크리스트·공개 버튼).
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { DescriptionField } from "@/app/components/description-field";
import { ErrorNote, INPUT_CLASS, PageShell, buttonClass } from "@/app/components/ui";
import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import { checkPublicTextForBannedWords } from "@/lib/contests/banned-words-check";
import type { Category, DeliverableType } from "@/lib/contests/grill-types";

import { ClassroomImportField } from "../_components/classroom-import-field";
import { ContestStageStepper } from "../_components/contest-stage-stepper";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "no-permission" }
  | { status: "ready"; categories: Category[]; deliverableTypes: DeliverableType[] };

type BriefForm = {
  title: string;
  categoryId: number | "";
  deliverableTypeIds: number[];
  deadlineAt: string;
  description: string;
  allowsClassroomImport: boolean;
};

const EMPTY_BRIEF: BriefForm = {
  title: "",
  categoryId: "",
  deliverableTypeIds: [],
  deadlineAt: "",
  description: "",
  allowsClassroomImport: false,
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function NewFreeContestBriefPage() {
  const session = useSession();
  const router = useRouter();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [brief, setBrief] = useState<BriefForm>(EMPTY_BRIEF);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const [permission, categories, deliverableTypes] = await Promise.all([
        bffClient.get<unknown>("/api/backend/contests/free/hosting-permission"),
        bffClient.get<unknown>("/api/backend/contests/categories"),
        bffClient.get<unknown>("/api/backend/contests/deliverable-types"),
      ]);
      if (cancelled) return;

      if (!permission.ok || !categories.ok || !deliverableTypes.ok) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }
      if (
        !isPlainRecord(permission.data) ||
        !Array.isArray(categories.data) ||
        !Array.isArray(deliverableTypes.data)
      ) {
        setLoad({ status: "error", message: "화면을 불러오지 못했습니다." });
        return;
      }

      if (permission.data.is_granted !== true) {
        setLoad({ status: "no-permission" });
        return;
      }

      setLoad({ status: "ready", categories: categories.data, deliverableTypes: deliverableTypes.data });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status]);

  function toggleDeliverableType(id: number) {
    setBrief((prev) => ({
      ...prev,
      deliverableTypeIds: prev.deliverableTypeIds.includes(id)
        ? prev.deliverableTypeIds.filter((x) => x !== id)
        : [...prev.deliverableTypeIds, id],
    }));
  }

  async function handleCreateDraft() {
    setCreateError(null);

    const title = brief.title.trim();
    if (!title) {
      setCreateError("제목을 입력해주세요.");
      return;
    }
    if (brief.categoryId === "") {
      setCreateError("카테고리를 선택해주세요.");
      return;
    }
    if (brief.deliverableTypeIds.length === 0) {
      setCreateError("요구형태를 하나 이상 선택해주세요.");
      return;
    }
    if (!brief.deadlineAt) {
      setCreateError("마감 기한을 선택해주세요.");
      return;
    }
    // 제출을 누르는 순간에만 검사한다 — 타이핑 중에는 부르지 않는다(spec
    // #474, #479). 서버가 진짜 문이다.
    const titleBannedWordMessage = checkPublicTextForBannedWords(title, "제목");
    if (titleBannedWordMessage) {
      setCreateError(titleBannedWordMessage);
      return;
    }
    const descriptionBannedWordMessage = checkPublicTextForBannedWords(brief.description, "설명");
    if (descriptionBannedWordMessage) {
      setCreateError(descriptionBannedWordMessage);
      return;
    }

    setCreating(true);
    try {
      const created = await bffClient.post<unknown>("/api/backend/contests/free", {
        title,
        category_id: brief.categoryId,
        deliverable_type_ids: brief.deliverableTypeIds,
        description: brief.description,
        deadline_at: new Date(brief.deadlineAt).toISOString(),
        requirements: [],
        allows_classroom_import: brief.allowsClassroomImport,
      });

      if (!created.ok) {
        setCreateError(created.detail);
        return;
      }
      if (!isPlainRecord(created.data) || typeof created.data.id !== "number") {
        setCreateError("초안 생성 응답을 해석하지 못했습니다. 다시 시도해 주세요.");
        return;
      }

      router.push(`/console/contests/${created.data.id}/draft`);
    } catch {
      setCreateError("연결에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setCreating(false);
    }
  }

  if (session.status === "loading" || load.status === "loading") {
    return (
      <PageShell>
        <p data-testid="free-brief-loading">불러오는 중...</p>
      </PageShell>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "error") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="free-brief-load-error">{load.message}</span>
        </ErrorNote>
      </PageShell>
    );
  }

  if (load.status === "no-permission") {
    return (
      <PageShell>
        <ErrorNote>
          <span data-testid="free-brief-no-permission">
            무료 공모전 개최 권한이 없습니다. 운영자에게 문의해 주세요.
          </span>
        </ErrorNote>
      </PageShell>
    );
  }

  const { categories, deliverableTypes } = load;

  return (
    <PageShell>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <ContestStageStepper current="brief" variant="free" />
          <div>
            <p className="text-xs font-medium tracking-widest text-ink/60">무료 공모전 개최</p>
            <h1 className="text-2xl font-semibold" data-testid="free-brief-heading">
              기본 정보를 알려주세요
            </h1>
            <p className="mt-2 text-sm text-ink/70">
              본인확인·결제 없이 바로 개최합니다. 다음 단계에서 요구사항 체크리스트를 만듭니다.
            </p>
          </div>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          제목
          <input
            value={brief.title}
            onChange={(event) => setBrief((prev) => ({ ...prev, title: event.target.value }))}
            maxLength={200}
            data-testid="free-brief-title"
            className={INPUT_CLASS}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          카테고리
          <select
            value={brief.categoryId}
            onChange={(event) =>
              setBrief((prev) => ({ ...prev, categoryId: event.target.value ? Number(event.target.value) : "" }))
            }
            data-testid="free-brief-category"
            className={INPUT_CLASS}
          >
            <option value="">선택해주세요</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="mb-1">요구형태 · 복수 선택</legend>
          {deliverableTypes.map((dt) => (
            <label
              key={dt.id}
              className="flex items-center justify-between border border-rule px-3 py-2"
              data-testid={`free-brief-deliverable-type-${dt.id}`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={brief.deliverableTypeIds.includes(dt.id)}
                  onChange={() => toggleDeliverableType(dt.id)}
                  data-testid={`free-brief-deliverable-type-${dt.id}-checkbox`}
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
            value={brief.deadlineAt}
            onChange={(event) => setBrief((prev) => ({ ...prev, deadlineAt: event.target.value }))}
            data-testid="free-brief-deadline"
            className={INPUT_CLASS}
          />
        </label>

        <ClassroomImportField
          checked={brief.allowsClassroomImport}
          onChange={(next) => setBrief((prev) => ({ ...prev, allowsClassroomImport: next }))}
          testId="free-brief-classroom-import"
        />

        <DescriptionField
          label="설명 · 보상 안내(선택)"
          value={brief.description}
          onChange={(next) => setBrief((prev) => ({ ...prev, description: next }))}
          title={brief.title}
          placeholder="우승자에게 드리는 보상이 있다면 여기 적어주세요(예: 기프티콘)."
          testId="free-brief-description"
        />

        {createError && (
          <ErrorNote>
            <span data-testid="free-brief-error">{createError}</span>
          </ErrorNote>
        )}

        <button
          type="button"
          onClick={() => void handleCreateDraft()}
          disabled={creating}
          data-testid="free-brief-submit"
          className={`w-fit ${buttonClass("primary")}`}
        >
          {creating ? "만드는 중..." : "다음"}
        </button>
      </div>
    </PageShell>
  );
}
