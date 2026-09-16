"use client";

// 새 문제 화면의 「이미 있는 문제로 시작하기」 시트(#326). 대상 클래스는
// 묻지 않는다 — 지금 있는 클래스(`classId`)가 대상이다. 탭 셋이 서로 다른
// 자원이다: 공개된 문제(`/templates` 목록과 같은 엔드포인트), 내가 올린 것
// (같은 엔드포인트, 내려간 것은 걸러 보여준다 — 내려간 템플릿은 본인도 더
// 못 가져온다, `template_api.import_template`), 내 다른 클래스에서(#326이
// 새로 낸 `from-other-classes`, 방향만 반대인 #292의 그 복사를 그대로
// 부른다).
//
// **채점 모델은 따라오지 않는다** — 세 경로 모두 백엔드가 이미 그렇게
// 만든다(`services.import_problem_template`/`copy_problem_to_class`). 여기서는
// 그 사실을 문구로만 말한다.
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { MarkdownView } from "@codemit/markdown";

import { Badge, EmptyState, ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";
import { BackendError } from "@/lib/backend/client";
import {
  fetchMyProblemTemplates,
  fetchProblemTemplate,
  fetchProblemTemplates,
  importProblemTemplate,
  type ProblemTemplateListItem,
  type ProblemTemplateRow,
} from "@/lib/problem-templates/api";
import { copyProblem, fetchImportableProblems, type ImportableProblemRow, type ProblemRow } from "@/lib/problems/api";

type PickerTab = "public" | "mine" | "other-classes";

/** 세 탭이 서로 다른 자원이라 목록 항목의 모양이 갈린다 — 미리보기·가져오기가
 *  쓸 수 있게 이 컴포넌트 안에서만 공통 모양으로 좁혀 쓴다. */
type Candidate = {
  key: string;
  title: string;
  meta: string;
  description: string | null;
  checklistItems: { label: string; required: boolean }[] | null;
  runImport: () => Promise<ProblemRow>;
};

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("ko-KR");
}

export function TemplatePickerSheet({
  classId,
  onClose,
  onImported,
}: {
  classId: number;
  onClose: () => void;
  onImported: (problem: ProblemRow) => void;
}) {
  const [tab, setTab] = useState<PickerTab>("public");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // --- 공개된 문제 ---------------------------------------------------------
  const [publicQuery, setPublicQuery] = useState("");
  const [publicCommittedQuery, setPublicCommittedQuery] = useState("");
  const [publicState, setPublicState] = useState<
    { status: "idle" | "loading" | "error" } | { status: "ready"; items: ProblemTemplateListItem[] }
  >({ status: "idle" });

  useEffect(() => {
    if (tab !== "public") return;
    let cancelled = false;
    setPublicState({ status: "loading" });
    fetchProblemTemplates({ q: publicCommittedQuery || undefined })
      .then((result) => {
        if (!cancelled) setPublicState({ status: "ready", items: result.items });
      })
      .catch(() => {
        if (!cancelled) setPublicState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [tab, publicCommittedQuery]);

  // --- 내가 올린 것 ---------------------------------------------------------
  const [mineState, setMineState] = useState<
    { status: "idle" | "loading" | "error" } | { status: "ready"; items: ProblemTemplateRow[] }
  >({ status: "idle" });

  useEffect(() => {
    if (tab !== "mine" || mineState.status !== "idle") return;
    setMineState({ status: "loading" });
    fetchMyProblemTemplates()
      .then((items) => setMineState({ status: "ready", items: items.filter((t) => !t.taken_down) }))
      .catch(() => setMineState({ status: "error" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // --- 내 다른 클래스에서 ----------------------------------------------------
  const [otherState, setOtherState] = useState<
    { status: "idle" | "loading" | "error" } | { status: "ready"; items: ImportableProblemRow[] }
  >({ status: "idle" });

  useEffect(() => {
    if (tab !== "other-classes" || otherState.status !== "idle") return;
    setOtherState({ status: "loading" });
    fetchImportableProblems(classId)
      .then((items) => setOtherState({ status: "ready", items }))
      .catch(() => setOtherState({ status: "error" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, classId]);

  // 공개 템플릿은 목록에 설명·체크리스트가 없다 — 고른 항목의 상세를
  // 그때그때 따로 불러온다(내가 올린 것/내 다른 클래스에서는 목록 자체에
  // 이미 다 있다).
  const [publicDetail, setPublicDetail] = useState<
    { shareCode: string; status: "loading" } | { shareCode: string; status: "ready"; template: ProblemTemplateRow } | null
  >(null);

  function selectPublic(item: ProblemTemplateListItem) {
    setSelectedKey(`public:${item.share_code}`);
    setImportError(null);
    setPublicDetail({ shareCode: item.share_code, status: "loading" });
    fetchProblemTemplate(item.share_code)
      .then((template) => setPublicDetail({ shareCode: item.share_code, status: "ready", template }))
      .catch(() => setPublicDetail(null));
  }

  function switchTab(next: PickerTab) {
    setTab(next);
    setSelectedKey(null);
    setImportError(null);
  }

  function buildCandidate(): Candidate | null {
    if (tab === "public") {
      if (!selectedKey || publicState.status !== "ready") return null;
      const item = publicState.items.find((i) => `public:${i.share_code}` === selectedKey);
      if (!item) return null;
      const detail =
        publicDetail && publicDetail.shareCode === item.share_code && publicDetail.status === "ready"
          ? publicDetail.template
          : null;
      return {
        key: selectedKey,
        title: item.title,
        meta: `${item.publisher_display_name} · ${formatDate(item.created_at)} 공개`,
        description: detail?.description ?? null,
        checklistItems: detail?.checklist_items ?? null,
        runImport: () => importProblemTemplate(item.share_code, classId),
      };
    }
    if (tab === "mine") {
      if (!selectedKey || mineState.status !== "ready") return null;
      const item = mineState.items.find((i) => `mine:${i.share_code}` === selectedKey);
      if (!item) return null;
      return {
        key: selectedKey,
        title: item.title,
        meta: `${formatDate(item.created_at)} 공개`,
        description: item.description,
        checklistItems: item.checklist_items,
        runImport: () => importProblemTemplate(item.share_code, classId),
      };
    }
    if (!selectedKey || otherState.status !== "ready") return null;
    const item = otherState.items.find((i) => `other:${i.id}` === selectedKey);
    if (!item) return null;
    return {
      key: selectedKey,
      title: item.title,
      meta: item.classroom_name,
      description: item.description,
      checklistItems: item.checklist_items,
      runImport: () => copyProblem(item.classroom_id, item.id, classId),
    };
  }

  const candidate = buildCandidate();

  async function handleImport() {
    if (!candidate) return;
    setImporting(true);
    setImportError(null);
    try {
      const problem = await candidate.runImport();
      onImported(problem);
    } catch (err) {
      setImportError(err instanceof BackendError ? err.message : "가져오지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <button
        type="button"
        aria-label="닫기"
        onClick={onClose}
        className="fixed inset-0 cursor-default"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="템플릿에서 가져오기"
        data-testid="template-picker-sheet"
        className="relative flex max-h-[85vh] w-full max-w-[820px] flex-col border border-rule bg-surface"
      >
        <div className="flex items-start justify-between gap-3 border-b border-rule p-5">
          <div>
            <h2 className="text-[17px] font-semibold">템플릿에서 가져오기</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/60">
              고른 문제가 지금 이 클래스에 초안으로 들어옵니다 — 가져온 뒤 고칠 수 있습니다.
            </p>
          </div>
          <button
            type="button"
            data-testid="template-picker-close"
            onClick={onClose}
            className={buttonClass("secondary", "sm")}
          >
            닫기
          </button>
        </div>

        <div role="tablist" aria-label="템플릿 종류" className="flex items-end gap-0.5 border-b border-rule px-5 pt-2">
          {(
            [
              ["public", "공개된 문제", "template-picker-tab-public"],
              ["mine", "내가 올린 것", "template-picker-tab-mine"],
              ["other-classes", "내 다른 클래스에서", "template-picker-tab-other-classes"],
            ] as const
          ).map(([key, label, testId]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              data-testid={testId}
              onClick={() => switchTab(key)}
              className={
                tab === key
                  ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13px] font-medium"
                  : "px-4 py-2 text-[13px] text-ink/60 hover:text-ink"
              }
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "public" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setPublicCommittedQuery(publicQuery.trim());
            }}
            className="flex gap-2 border-b border-rule px-5 py-3"
          >
            <input
              data-testid="template-picker-search-input"
              value={publicQuery}
              onChange={(event) => setPublicQuery(event.target.value)}
              placeholder="문제 제목으로 찾기"
              className={INPUT_CLASS}
            />
            <button type="submit" data-testid="template-picker-search-submit" className={buttonClass("secondary", "sm")}>
              검색
            </button>
          </form>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col gap-0 overflow-y-auto lg:flex-row">
          <div className="min-h-0 flex-1 overflow-y-auto border-b border-rule lg:w-1/2 lg:border-b-0 lg:border-r">
            {tab === "public" ? (
              <PickerList
                status={publicState.status}
                isEmpty={publicState.status === "ready" && publicState.items.length === 0}
                emptyMessage={
                  publicCommittedQuery
                    ? "검색 결과가 없습니다. 다른 제목으로 찾아보세요."
                    : "아직 공개된 템플릿이 없습니다."
                }
              >
                {publicState.status === "ready"
                  ? publicState.items.map((item) => (
                      <PickerRow
                        key={item.share_code}
                        name="template-picker-selection"
                        testId={`template-picker-row-public-${item.share_code}`}
                        selected={selectedKey === `public:${item.share_code}`}
                        title={item.title}
                        meta={`${item.publisher_display_name} · ${formatDate(item.created_at)} 공개`}
                        onSelect={() => selectPublic(item)}
                      />
                    ))
                  : null}
              </PickerList>
            ) : tab === "mine" ? (
              <PickerList
                status={mineState.status}
                isEmpty={mineState.status === "ready" && mineState.items.length === 0}
                emptyMessage="아직 공개한 템플릿이 없습니다."
              >
                {mineState.status === "ready"
                  ? mineState.items.map((item) => (
                      <PickerRow
                        key={item.share_code}
                        name="template-picker-selection"
                        testId={`template-picker-row-mine-${item.share_code}`}
                        selected={selectedKey === `mine:${item.share_code}`}
                        title={item.title}
                        meta={`${formatDate(item.created_at)} 공개`}
                        onSelect={() => {
                          setSelectedKey(`mine:${item.share_code}`);
                          setImportError(null);
                        }}
                      />
                    ))
                  : null}
              </PickerList>
            ) : (
              <PickerList
                status={otherState.status}
                isEmpty={otherState.status === "ready" && otherState.items.length === 0}
                emptyMessage="다른 클래스에 가진 문제가 없습니다."
              >
                {otherState.status === "ready"
                  ? otherState.items.map((item) => (
                      <PickerRow
                        key={item.id}
                        name="template-picker-selection"
                        testId={`template-picker-row-other-classes-${item.id}`}
                        selected={selectedKey === `other:${item.id}`}
                        title={item.title}
                        meta={item.classroom_name}
                        onSelect={() => {
                          setSelectedKey(`other:${item.id}`);
                          setImportError(null);
                        }}
                      />
                    ))
                  : null}
              </PickerList>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5 lg:w-1/2">
            {!candidate ? (
              <EmptyState>
                <span data-testid="template-picker-preview-empty">
                  왼쪽에서 문제를 고르면 여기에 설명과 체크리스트가 보입니다.
                </span>
              </EmptyState>
            ) : (
              <div className="flex flex-col gap-4" data-testid="template-picker-preview">
                <div>
                  <h3 className="text-[15px] font-semibold" data-testid="template-picker-preview-title">
                    {candidate.title}
                  </h3>
                  <p className="mt-1 text-[12px] text-ink/45">{candidate.meta}</p>
                </div>
                <div>
                  <p className="mb-1.5 text-[12px] text-ink/60">설명</p>
                  {candidate.description === null ? (
                    <p className="text-[12.5px] text-ink/45">불러오는 중...</p>
                  ) : candidate.description.trim() === "" ? (
                    <p className="text-[12.5px] text-ink/45">설명이 없습니다.</p>
                  ) : (
                    <div data-testid="template-picker-preview-description">
                      <MarkdownView markdown={candidate.description} fileBaseName={candidate.title} />
                    </div>
                  )}
                </div>
                <div>
                  <p className="mb-1.5 text-[12px] text-ink/60">체크리스트</p>
                  {candidate.checklistItems === null ? null : candidate.checklistItems.length === 0 ? (
                    <p className="text-[12.5px] text-ink/45">아직 항목이 없습니다.</p>
                  ) : (
                    <ul data-testid="template-picker-preview-checklist" className="divide-y divide-rule border border-rule">
                      {candidate.checklistItems.map((item, index) => (
                        <li key={index} className="flex items-center gap-2 px-3 py-2 text-[12.5px]">
                          <span className="flex-1">{item.label}</span>
                          {item.required ? <Badge tone="attention">필수</Badge> : <Badge tone="neutral">선택</Badge>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2.5 border-t border-rule bg-paper p-4">
          <p className="text-[12px] leading-relaxed text-ink/60">
            제목·설명·체크리스트가 따라옵니다.{" "}
            <b className="font-medium text-ink">채점 모델은 따라오지 않습니다</b> — 이 클래스의
            기본값을 따릅니다.
          </p>
          {importError ? (
            <ErrorNote>
              <span data-testid="template-picker-import-error">{importError}</span>
            </ErrorNote>
          ) : null}
          <div className="flex justify-end">
            <button
              type="button"
              data-testid="template-picker-import-submit"
              disabled={!candidate || importing}
              onClick={handleImport}
              className={buttonClass("primary")}
            >
              {importing ? "가져오는 중..." : "이 문제 가져오기"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PickerList({
  status,
  emptyMessage,
  isEmpty,
  children,
}: {
  status: "idle" | "loading" | "error" | "ready";
  emptyMessage: string;
  isEmpty: boolean;
  children: ReactNode;
}) {
  if (status === "idle" || status === "loading") {
    return <p className="p-5 text-[13px] text-ink/45">불러오는 중...</p>;
  }
  if (status === "error") {
    return (
      <div className="p-5">
        <ErrorNote>
          <span>목록을 불러오지 못했습니다.</span>
        </ErrorNote>
      </div>
    );
  }
  if (isEmpty) {
    return (
      <div className="p-5">
        <EmptyState>
          <span>{emptyMessage}</span>
        </EmptyState>
      </div>
    );
  }
  // 라디오 그룹 하나 — 키보드 화살표로도 항목을 오갈 수 있다(네이티브
  // `<input type="radio">`가 그 동작을 공짜로 준다).
  return <ul className="divide-y divide-rule">{children}</ul>;
}

function PickerRow({
  testId,
  name,
  selected,
  title,
  meta,
  onSelect,
}: {
  testId: string;
  name: string;
  selected: boolean;
  title: string;
  meta: string;
  onSelect: () => void;
}) {
  return (
    <li>
      <label
        className={`flex w-full cursor-pointer items-start gap-3 px-4 py-3 ${
          selected ? "bg-paper" : "hover:bg-paper/60"
        }`}
      >
        <input
          type="radio"
          name={name}
          data-testid={testId}
          checked={selected}
          onChange={onSelect}
          className="mt-1 shrink-0 accent-ink"
        />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-medium">{title}</span>
          <span className="mt-0.5 block text-[11.5px] text-ink/45">{meta}</span>
        </span>
      </label>
    </li>
  );
}
