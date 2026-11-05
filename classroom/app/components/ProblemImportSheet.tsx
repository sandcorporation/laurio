"use client";

// 「문제 가져오기」 시트(#326, #876 에서 공모전 탭을 합쳤다). 새 문제 화면과 클래스 상세가 같이 쓴다. 대상 클래스는
// 묻지 않는다 — 지금 있는 클래스(`classId`)가 대상이다. 탭 셋이 서로 다른
// 자원이다: 공개된 문제(`/templates` 목록과 같은 엔드포인트), 내가 올린 것
// (같은 엔드포인트, 내려간 것은 걸러 보여준다 — 내려간 템플릿은 본인도 더
// 못 가져온다, `template_api.import_template`), 내 다른 클래스에서(#326이
// 새로 낸 `from-other-classes`, 방향만 반대인 #292의 그 복사를 그대로
// 부른다). 네 번째 탭 「공모전」(#548)은 개최자가 클래스에서 들여오기를 허용한
// 공개 중 · 마감 전 무료 공모전이다 — 제목 검색과 「더 보기」(20개씩)가 있어 목록만
// 따로 이어 받고, 들여온 문제는 제목·설명·체크리스트가 공모전을 **따라간다**(강사가
// 못 고친다. CONTEXT.md 「공모전 문제」). 앞 세 탭과 고른 항목의 상세(공개 탭만)는 공용
// 불러오기 도우미 `useLoadable`(#443)을 쓴다 — 탭을 오가도 매번 최신으로 다시 불러온다.
//
// **채점 모델은 따라오지 않는다** — 세 경로 모두 백엔드가 이미 그렇게
// 만든다(`services.import_problem_template`/`copy_problem_to_class`). 여기서는
// 그 사실을 문구로만 말한다.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { MarkdownView } from "@codemit/markdown";

import {
  Badge,
  EmptyState,
  ErrorNote,
  INPUT_CLASS,
  buttonClass,
} from "@/app/components/ui";
import { unwrap } from "@/lib/bff/client";
import {
  fetchMyProblemTemplates,
  fetchProblemTemplate,
  fetchProblemTemplates,
  importProblemTemplate,
} from "@/lib/problem-templates/api";
import {
  formatPickerDate,
  selectPickerCandidate,
  type PickerTab,
} from "@/lib/problem-templates/picker-selection";
import {
  copyProblem,
  fetchImportableContests,
  fetchImportableProblems,
  importContestProblem,
  type ImportableContestRow,
  type ProblemRow,
} from "@/lib/problems/api";
import { useLoadable, type LoadableState } from "@/lib/rendering/use-loadable";

type ContestListState =
  | { status: "loading" }
  | { status: "error" }
  | {
      status: "ready";
      items: ImportableContestRow[];
      next: string | null;
      loadingMore: boolean;
    };

export function ProblemImportSheet({
  classId,
  onClose,
  onImported,
  initialTab = "public",
}: {
  classId: number;
  onClose: () => void;
  onImported: (problem: ProblemRow) => void;
  /** 처음 열 탭. 기본은 「공개된 문제」다. */
  initialTab?: PickerTab;
}) {
  const [tab, setTab] = useState<PickerTab>(initialTab);
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
  const publicState = useLoadable(
    tab === "public",
    () =>
      unwrap(
        fetchProblemTemplates({ q: publicCommittedQuery || undefined }),
      ).then((page) => page.items),
    [publicCommittedQuery],
  );
  const selectedPublicItem =
    tab === "public" && publicState.status === "ready"
      ? (publicState.data.find(
          (i) => `public:${i.share_code}` === selectedKey,
        ) ?? null)
      : null;

  // --- 내가 올린 것 ---------------------------------------------------------
  const mineState = useLoadable(
    tab === "mine",
    () =>
      unwrap(fetchMyProblemTemplates()).then((items) =>
        items.filter((t) => !t.taken_down),
      ),
    [],
  );
  const selectedMineItem =
    tab === "mine" && mineState.status === "ready"
      ? (mineState.data.find((i) => `mine:${i.share_code}` === selectedKey) ??
        null)
      : null;

  // --- 내 다른 클래스에서 ----------------------------------------------------
  const otherState = useLoadable(
    tab === "other-classes",
    () => unwrap(fetchImportableProblems(classId)),
    [classId],
  );
  const selectedOtherItem =
    tab === "other-classes" && otherState.status === "ready"
      ? (otherState.data.find((i) => `other:${i.id}` === selectedKey) ?? null)
      : null;

  // --- 공모전 --------------------------------------------------------------
  // 제목으로 찾고, 마감 빠른 순 20개씩 「더 보기」로 이어 받는다.
  const [contestQuery, setContestQuery] = useState("");
  const [contestCommittedQuery, setContestCommittedQuery] = useState("");
  const [contestState, setContestState] = useState<ContestListState>({
    status: "loading",
  });
  // 검색어를 빠르게 바꾸면 늦게 온 옛 응답이 새 목록을 덮지 않게 한다.
  const contestRequestId = useRef(0);
  useEffect(() => {
    if (tab !== "contest") return;
    const id = ++contestRequestId.current;
    setContestState({ status: "loading" });
    void fetchImportableContests(classId, {
      query: contestCommittedQuery,
    }).then((result) => {
      if (id !== contestRequestId.current) return;
      setContestState(
        result.ok
          ? {
              status: "ready",
              items: result.data.items,
              next: result.data.next,
              loadingMore: false,
            }
          : { status: "error" },
      );
    });
  }, [tab, classId, contestCommittedQuery]);

  async function loadMoreContests() {
    if (
      contestState.status !== "ready" ||
      contestState.next === null ||
      contestState.loadingMore
    )
      return;
    const id = contestRequestId.current;
    const before = contestState;
    setContestState({ ...before, loadingMore: true });
    const result = await fetchImportableContests(classId, {
      query: contestCommittedQuery,
      after: before.next,
    });
    if (id !== contestRequestId.current) return;
    setContestState(
      result.ok
        ? {
            status: "ready",
            items: [...before.items, ...result.data.items],
            next: result.data.next,
            loadingMore: false,
          }
        : { ...before, loadingMore: false },
    );
  }
  const selectedContest =
    tab === "contest" && contestState.status === "ready"
      ? (contestState.items.find(
          (i) => `contest:${i.contest_id}` === selectedKey,
        ) ?? null)
      : null;

  // 공개 템플릿은 목록에 설명·체크리스트가 없다 — 고른 항목의 상세를
  // 선택 자체에 반응해(`useLoadable`의 deps) 따로 불러온다(내가 올린
  // 것/내 다른 클래스에서는 목록 자체에 이미 다 있다).
  const publicDetailState = useLoadable(
    selectedPublicItem !== null,
    () => unwrap(fetchProblemTemplate(selectedPublicItem!.share_code)),
    [selectedPublicItem?.share_code],
  );

  function switchTab(next: PickerTab) {
    setTab(next);
    setSelectedKey(null);
    setImportError(null);
  }

  function selectItem(key: string) {
    setSelectedKey(key);
    setImportError(null);
  }

  const preview = selectPickerCandidate({
    tab,
    selectedKey,
    publicItems: publicState.status === "ready" ? publicState.data : null,
    publicDetail:
      publicDetailState.status === "ready" ? publicDetailState.data : null,
    mineItems: mineState.status === "ready" ? mineState.data : null,
    otherItems: otherState.status === "ready" ? otherState.data : null,
  });

  async function handleImport() {
    if (!preview && !selectedContest) return;
    setImporting(true);
    setImportError(null);
    const result = selectedContest
      ? await importContestProblem(classId, selectedContest.contest_id)
      : selectedPublicItem
        ? await importProblemTemplate(selectedPublicItem.share_code, classId)
        : selectedMineItem
          ? await importProblemTemplate(selectedMineItem.share_code, classId)
          : selectedOtherItem
            ? await copyProblem(
                selectedOtherItem.classroom_id,
                selectedOtherItem.id,
                classId,
              )
            : null;
    setImporting(false);
    if (!result) return;
    if (result.ok) {
      onImported(result.data);
    } else {
      setImportError(result.detail);
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
        aria-label="문제 가져오기"
        data-testid="problem-import-sheet"
        className="relative flex max-h-[85vh] w-full max-w-[820px] flex-col border border-rule bg-surface"
      >
        <div className="flex items-start justify-between gap-3 border-b border-rule p-5">
          <div>
            <h2 className="text-[17px] font-semibold">문제 가져오기</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/60">
              고른 문제가 지금 이 클래스에 초안으로 들어옵니다 — 가져온 뒤 고칠
              수 있습니다.
            </p>
          </div>
          <button
            type="button"
            data-testid="problem-import-close"
            onClick={onClose}
            className={buttonClass("secondary", "sm")}
          >
            닫기
          </button>
        </div>

        <div
          role="tablist"
          aria-label="가져올 곳"
          className="flex items-end gap-0.5 overflow-x-auto border-b border-rule px-3 pt-2 sm:px-5"
        >
          {(
            [
              ["public", "공개된 문제", "problem-import-tab-public"],
              ["mine", "내가 올린 것", "problem-import-tab-mine"],
              [
                "other-classes",
                "다른 클래스",
                "problem-import-tab-other-classes",
              ],
              ["contest", "공모전", "problem-import-tab-contest"],
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
                  ? "-mb-px whitespace-nowrap border border-rule border-b-surface bg-surface px-3 py-2 text-[13px] font-medium sm:px-4"
                  : "whitespace-nowrap px-3 py-2 text-[13px] text-ink/60 hover:text-ink sm:px-4"
              }
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "public" || tab === "contest" ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (tab === "contest")
                setContestCommittedQuery(contestQuery.trim());
              else setPublicCommittedQuery(publicQuery.trim());
            }}
            className="flex gap-2 border-b border-rule px-5 py-3"
          >
            <input
              data-testid="problem-import-search-input"
              value={tab === "contest" ? contestQuery : publicQuery}
              onChange={(event) =>
                tab === "contest"
                  ? setContestQuery(event.target.value)
                  : setPublicQuery(event.target.value)
              }
              placeholder={
                tab === "contest"
                  ? "공모전 제목으로 찾기"
                  : "문제 제목으로 찾기"
              }
              className={INPUT_CLASS}
            />
            <button
              type="submit"
              data-testid="problem-import-search-submit"
              className={buttonClass("secondary", "sm")}
            >
              검색
            </button>
          </form>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col gap-0 overflow-y-auto lg:flex-row">
          <div className="min-h-0 flex-1 overflow-y-auto border-b border-rule lg:w-1/2 lg:border-b-0 lg:border-r">
            {tab === "public" ? (
              <PickerList
                state={publicState}
                isEmpty={
                  publicState.status === "ready" &&
                  publicState.data.length === 0
                }
                emptyMessage={
                  publicCommittedQuery
                    ? "검색 결과가 없습니다. 다른 제목으로 찾아보세요."
                    : "아직 공개된 템플릿이 없습니다."
                }
              >
                {publicState.status === "ready"
                  ? publicState.data.map((item) => (
                      <PickerRow
                        key={item.share_code}
                        name="problem-import-selection"
                        testId={`problem-import-row-public-${item.share_code}`}
                        selected={selectedKey === `public:${item.share_code}`}
                        title={item.title}
                        meta={`${item.publisher_display_name} · ${formatPickerDate(item.created_at)} 공개`}
                        onSelect={() => selectItem(`public:${item.share_code}`)}
                      />
                    ))
                  : null}
              </PickerList>
            ) : tab === "mine" ? (
              <PickerList
                state={mineState}
                isEmpty={
                  mineState.status === "ready" && mineState.data.length === 0
                }
                emptyMessage="아직 공개한 템플릿이 없습니다."
              >
                {mineState.status === "ready"
                  ? mineState.data.map((item) => (
                      <PickerRow
                        key={item.share_code}
                        name="problem-import-selection"
                        testId={`problem-import-row-mine-${item.share_code}`}
                        selected={selectedKey === `mine:${item.share_code}`}
                        title={item.title}
                        meta={`${formatPickerDate(item.created_at)} 공개`}
                        onSelect={() => selectItem(`mine:${item.share_code}`)}
                      />
                    ))
                  : null}
              </PickerList>
            ) : tab === "contest" ? (
              <>
                <PickerList
                  state={
                    contestState.status === "ready"
                      ? { status: "ready", data: contestState.items }
                      : contestState.status === "error"
                        ? { status: "error" }
                        : { status: "loading" }
                  }
                  isEmpty={
                    contestState.status === "ready" &&
                    contestState.items.length === 0
                  }
                  emptyMessage={
                    contestCommittedQuery
                      ? `「${contestCommittedQuery}」이 든 공모전이 없습니다.`
                      : "지금 들여올 수 있는 공모전이 없습니다."
                  }
                >
                  {contestState.status === "ready"
                    ? contestState.items.map((item) => (
                        <PickerRow
                          key={item.contest_id}
                          name="problem-import-selection"
                          testId={`problem-import-row-contest-${item.contest_id}`}
                          selected={
                            selectedKey === `contest:${item.contest_id}`
                          }
                          title={item.title}
                          meta={`${formatPickerDate(item.deadline_at)} 마감 · 요구사항 ${item.requirement_count}개`}
                          onSelect={() =>
                            selectItem(`contest:${item.contest_id}`)
                          }
                        />
                      ))
                    : null}
                </PickerList>
                {contestState.status === "ready" &&
                contestState.next !== null ? (
                  <div className="border-t border-rule p-3">
                    <button
                      type="button"
                      data-testid="problem-import-contest-more"
                      disabled={contestState.loadingMore}
                      onClick={() => void loadMoreContests()}
                      className={`${buttonClass("secondary", "sm")} w-full`}
                    >
                      {contestState.loadingMore ? "불러오는 중..." : "더 보기"}
                    </button>
                  </div>
                ) : null}
              </>
            ) : (
              <PickerList
                state={otherState}
                isEmpty={
                  otherState.status === "ready" && otherState.data.length === 0
                }
                emptyMessage="다른 클래스에 가진 문제가 없습니다."
              >
                {otherState.status === "ready"
                  ? otherState.data.map((item) => (
                      <PickerRow
                        key={item.id}
                        name="problem-import-selection"
                        testId={`problem-import-row-other-classes-${item.id}`}
                        selected={selectedKey === `other:${item.id}`}
                        title={item.title}
                        meta={item.classroom_name}
                        onSelect={() => selectItem(`other:${item.id}`)}
                      />
                    ))
                  : null}
              </PickerList>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-5 lg:w-1/2">
            {selectedContest ? (
              <div
                className="flex flex-col gap-1"
                data-testid="problem-import-preview"
              >
                <h3
                  className="text-[15px] font-semibold"
                  data-testid="problem-import-preview-title"
                >
                  {selectedContest.title}
                </h3>
                <p className="text-[12px] text-ink/45">
                  {formatPickerDate(selectedContest.deadline_at)} 마감 ·
                  요구사항 {selectedContest.requirement_count}개
                </p>
              </div>
            ) : !preview ? (
              <EmptyState>
                <span data-testid="problem-import-preview-empty">
                  왼쪽에서 문제를 고르면 여기에 설명과 체크리스트가 보입니다.
                </span>
              </EmptyState>
            ) : (
              <div
                className="flex flex-col gap-4"
                data-testid="problem-import-preview"
              >
                <div>
                  <h3
                    className="text-[15px] font-semibold"
                    data-testid="problem-import-preview-title"
                  >
                    {preview.title}
                  </h3>
                  <p className="mt-1 text-[12px] text-ink/45">{preview.meta}</p>
                </div>
                <div>
                  <p className="mb-1.5 text-[12px] text-ink/60">설명</p>
                  {preview.description === null ? (
                    <p className="text-[12.5px] text-ink/45">불러오는 중...</p>
                  ) : preview.description.trim() === "" ? (
                    <p className="text-[12.5px] text-ink/45">
                      설명이 없습니다.
                    </p>
                  ) : (
                    <div data-testid="problem-import-preview-description">
                      <MarkdownView
                        markdown={preview.description}
                        fileBaseName={preview.title}
                      />
                    </div>
                  )}
                </div>
                <div>
                  <p className="mb-1.5 text-[12px] text-ink/60">체크리스트</p>
                  {preview.checklistItems === null ? null : preview
                      .checklistItems.length === 0 ? (
                    <p className="text-[12.5px] text-ink/45">
                      아직 항목이 없습니다.
                    </p>
                  ) : (
                    <ul
                      data-testid="problem-import-preview-checklist"
                      className="divide-y divide-rule border border-rule"
                    >
                      {preview.checklistItems.map((item, index) => (
                        <li
                          key={index}
                          className="flex items-center gap-2 px-3 py-2 text-[12.5px]"
                        >
                          <span className="flex-1">{item.label}</span>
                          {item.required ? (
                            <Badge tone="attention">필수</Badge>
                          ) : (
                            <Badge tone="neutral">선택</Badge>
                          )}
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
          {tab === "contest" ? (
            <p className="text-[12px] leading-relaxed text-ink/60">
              <b className="font-medium text-ink">
                제목·설명·체크리스트는 공모전을 따라갑니다
              </b>{" "}
              — 개최자가 고치면 함께 바뀌고, 여기서는 고칠 수 없습니다. 수업용
              안내·채점 지침·채점 모델·받는 형식은 정할 수 있습니다. 참여자는 낼
              때마다 이 공모전에도 낼지 고릅니다.
            </p>
          ) : (
            <p className="text-[12px] leading-relaxed text-ink/60">
              제목·설명·체크리스트가 따라옵니다.{" "}
              <b className="font-medium text-ink">
                채점 모델은 따라오지 않습니다
              </b>{" "}
              — 이 클래스의 기본값을 따릅니다.
            </p>
          )}
          {importError ? (
            <ErrorNote>
              <span data-testid="problem-import-import-error">
                {importError}
              </span>
            </ErrorNote>
          ) : null}
          <div className="flex justify-end">
            <button
              type="button"
              data-testid="problem-import-import-submit"
              disabled={(!preview && !selectedContest) || importing}
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

/** 세 탭이 공용 불러오기 도우미(`useLoadable`)의 상태를 같은 방식으로
 *  보여준다 — 불러오는 중/오류/빈 목록/목록. */
function PickerList<T>({
  state,
  emptyMessage,
  isEmpty,
  children,
}: {
  state: LoadableState<T>;
  emptyMessage: string;
  isEmpty: boolean;
  children: ReactNode;
}) {
  if (state.status === "idle" || state.status === "loading") {
    return <p className="p-5 text-[13px] text-ink/45">불러오는 중...</p>;
  }
  if (state.status === "error") {
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
