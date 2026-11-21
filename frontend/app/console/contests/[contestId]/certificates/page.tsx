"use client";

// 개최자의 「상장」 화면 (#1129, 스펙 #1071 「화면 · 개최자」).
//
// 마감 뒤에만 열린다(백엔드가 마감 전·초안에 409). 제출자 표에서 여럿을 고르고, 사람마다
// 칸을 채우고, 미리보기로 확인한 뒤 발급한다. 발급한 것은 아래 목록에서 한 장씩·묶음으로 받고,
// 취소하거나 고쳐 다시 발급한다. **판정은 백엔드가 한다** — 길이·날짜·금칙어·발급 수 한도는
// 서버가 거절하고, 이 화면은 그 문구를 그대로 보여 준다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015).
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, EmptyState, ErrorNote, PageHeader, SectionHeading } from "@/app/components/ui";
import { useSession } from "@/lib/auth/use-session";
import { bffClient } from "@/lib/bff/client";
import { formatDeadlineSeoul } from "@/lib/contest-format";
import { fetchPdf, postForPdf, saveBlob } from "@/lib/certificates/pdf";
import {
  ISSUE_BATCH_LIMIT,
  bundleCount,
  certificateStatus,
  defaultAwardDate,
  type CertificateBoardOut,
  type CertificateOut,
  type CertificateTextIn,
} from "@/lib/certificates/types";
import { buttonClass } from "@/lib/ui/classnames";

import { CertificateFields } from "./certificate-fields";

type ContestMeta = { id: number; title: string };

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "not-yet"; message: string }
  | { status: "forbidden"; message: string }
  | { status: "error"; message: string }
  | { status: "ready"; contest: ContestMeta; board: CertificateBoardOut };

type Preview = { url: string; recipient: string };

const STATUS_LABEL = { valid: "유효", replaced: "다시 발급됨", cancelled: "취소됨" } as const;

function api(contestId: string, suffix = ""): string {
  return `/api/backend/contests/${contestId}/certificates${suffix}`;
}

export default function ContestCertificatesPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  // 고른 사람(제출 id)마다 칸 한 벌. 표의 차례를 지키려고 배열로 둔다.
  const [picked, setPicked] = useState<{ submissionId: number; text: CertificateTextIn }[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
  // 묶어 받을 발급된 상장 id. 비어 있으면 받을 수 있는 것 전부를 받는다.
  const [bundlePicked, setBundlePicked] = useState<ReadonlySet<number>>(new Set());
  const [reissue, setReissue] = useState<{ id: number; text: CertificateTextIn } | null>(null);

  const reload = useCallback(async () => {
    const [contest, board] = await Promise.all([
      bffClient.get<ContestMeta>(`/api/backend/contests/${contestId}`),
      bffClient.get<CertificateBoardOut>(api(contestId)),
    ]);
    if (contest.ok && board.ok) {
      setLoad({ status: "ready", contest: contest.data, board: board.data });
    } else if (contest.status === 404 || (!board.ok && board.status === 404)) {
      setLoad({ status: "not-found" });
    } else if (!board.ok && board.status === 409) {
      setLoad({ status: "not-yet", message: board.detail });
    } else if (!board.ok && board.status === 403) {
      setLoad({ status: "forbidden", message: board.detail });
    } else {
      setLoad({ status: "error", message: "상장 화면을 불러오지 못했습니다." });
    }
  }, [contestId]);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    void reload();
  }, [session.status, reload]);

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="certificates-loading">불러오는 중...</p>
      </main>
    );
  }
  if (session.status === "unauthenticated") return null;
  if (load.status === "not-found") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="certificates-not-found">공모전을 찾을 수 없습니다.</p>
      </main>
    );
  }
  if (load.status !== "ready") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <ErrorNote testId={`certificates-${load.status}`}>{load.message}</ErrorNote>
      </main>
    );
  }

  const { contest, board } = load;
  const { defaults } = board;
  const dateDefault = defaultAwardDate(defaults.award_date_min, defaults.award_date_max);
  const issuable = board.recipients.filter((r) => r.certificate_id === null);
  const validCount = bundleCount(board.certificates);
  const downloadable = (c: CertificateOut) => c.cancelled_at === null && c.pdf_available;
  // 목록이 다시 불렸을 때 이미 취소됐거나 사라진 장은 선택에서 뺀다.
  const bundleIds = board.certificates.filter((c) => bundlePicked.has(c.id) && downloadable(c)).map((c) => c.id);
  const toggleBundle = (id: number) => {
    const next = new Set(bundlePicked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setBundlePicked(next);
  };
  const pickedIds = new Set(picked.map((p) => p.submissionId));

  const togglePick = (submissionId: number, name: string) => {
    setConfirming(false);
    setError(null);
    setNotice(null);
    if (pickedIds.has(submissionId)) {
      setPicked(picked.filter((p) => p.submissionId !== submissionId));
      return;
    }
    if (picked.length >= ISSUE_BATCH_LIMIT) {
      setError(`한 번에 ${ISSUE_BATCH_LIMIT}명까지 발급할 수 있습니다.`);
      return;
    }
    // 앞 사람의 상 이름·본문을 이어 받는다 — 같은 상을 여럿에게 줄 때 다시 치지 않게.
    const last = picked.at(-1)?.text;
    setPicked([
      ...picked,
      {
        submissionId,
        text: {
          award_name: last?.award_name ?? "",
          recipient_name: name,
          body: last?.body ?? "",
          giver_name: last?.giver_name ?? defaults.giver_name,
          giver_title: last?.giver_title ?? defaults.giver_title,
          award_date: last?.award_date ?? dateDefault,
        },
      },
    ]);
  };

  const togglePickAll = () => {
    setConfirming(false);
    setError(null);
    if (picked.length === Math.min(issuable.length, ISSUE_BATCH_LIMIT) && picked.length > 0) {
      setPicked([]);
      return;
    }
    const base = picked.at(-1)?.text;
    setPicked(
      issuable.slice(0, ISSUE_BATCH_LIMIT).map((r) => ({
        submissionId: r.submission_id,
        text: picked.find((p) => p.submissionId === r.submission_id)?.text ?? {
          award_name: base?.award_name ?? "",
          recipient_name: r.default_recipient_name,
          body: base?.body ?? "",
          giver_name: base?.giver_name ?? defaults.giver_name,
          giver_title: base?.giver_title ?? defaults.giver_title,
          award_date: base?.award_date ?? dateDefault,
        },
      })),
    );
  };

  const updateText = (submissionId: number, text: CertificateTextIn) => {
    setConfirming(false);
    setPicked(picked.map((p) => (p.submissionId === submissionId ? { ...p, text } : p)));
  };

  const showPreview = async (key: string, text: CertificateTextIn) => {
    setBusy(true);
    setError(null);
    const result = await postForPdf(api(contestId, "/preview"), text);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setPreview({ url: URL.createObjectURL(result.blob), recipient: key });
  };

  const issue = async () => {
    setBusy(true);
    setError(null);
    const result = await bffClient.post<CertificateOut[]>(api(contestId), {
      items: picked.map((p) => ({ submission_id: p.submissionId, text: p.text })),
    });
    setBusy(false);
    setConfirming(false);
    if (!result.ok) {
      setError(result.detail);
      return;
    }
    setPicked([]);
    setPreview(null);
    setNotice(`${result.data.length}장을 발급했습니다.`);
    await reload();
  };

  const download = async (path: string, filename: string) => {
    setError(null);
    const result = await fetchPdf(path);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    saveBlob(result.blob, filename);
  };

  const cancel = async (certificateId: number) => {
    setBusy(true);
    setError(null);
    const result = await bffClient.post<CertificateOut>(api(contestId, `/${certificateId}/cancel`));
    setBusy(false);
    setCancelling(null);
    if (!result.ok) {
      setError(result.detail);
      return;
    }
    setNotice("상장을 취소했습니다.");
    await reload();
  };

  const reissueNow = async () => {
    if (!reissue) return;
    setBusy(true);
    setError(null);
    const result = await bffClient.post<CertificateOut>(
      api(contestId, `/${reissue.id}/reissue`),
      reissue.text,
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.detail);
      return;
    }
    setReissue(null);
    setNotice(`${result.data.number} 번으로 다시 발급했습니다.`);
    await reload();
  };

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-10 sm:px-10">
      <PageHeader
        title={`${contest.title} — 상장`}
        titleTestId="certificates-contest-title"
        actions={
          <Link className={buttonClass("secondary", "sm")} href="/console/contests">
            내 공모전
          </Link>
        }
      />

      {error ? <ErrorNote testId="certificates-error">{error}</ErrorNote> : null}
      {notice ? (
        <p className="text-sm text-success" role="status" data-testid="certificates-notice">
          {notice}
        </p>
      ) : null}

      <section className="flex flex-col gap-3" data-testid="certificates-recipients">
        <SectionHeading
          title="제출자"
          hint={
            <span data-testid="certificates-picked-count">
              {picked.length}/{Math.min(issuable.length, ISSUE_BATCH_LIMIT)} 선택
            </span>
          }
        />
        {board.recipients.length === 0 ? (
          <EmptyState>
            <span data-testid="certificates-recipients-empty">제출이 없습니다.</span>
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  <th className="w-10 border border-rule bg-surface p-2 text-left">
                    <input
                      type="checkbox"
                      aria-label="전체 선택"
                      checked={issuable.length > 0 && picked.length === Math.min(issuable.length, ISSUE_BATCH_LIMIT)}
                      disabled={issuable.length === 0}
                      onChange={togglePickAll}
                      data-testid="certificates-pick-all"
                    />
                  </th>
                  <th className="border border-rule bg-surface p-2 text-left">이름</th>
                  <th className="border border-rule bg-surface p-2 text-left">상장</th>
                </tr>
              </thead>
              <tbody>
                {board.recipients.map((r) => (
                  <tr key={r.submission_id} data-testid={`certificates-recipient-${r.submission_id}`}>
                    <td className="border border-rule p-2">
                      <input
                        type="checkbox"
                        aria-label={`${r.default_recipient_name} 선택`}
                        checked={pickedIds.has(r.submission_id)}
                        disabled={r.certificate_id !== null}
                        onChange={() => togglePick(r.submission_id, r.default_recipient_name)}
                        data-testid={`certificates-pick-${r.submission_id}`}
                      />
                    </td>
                    <td className="border border-rule p-2 break-all">{r.default_recipient_name}</td>
                    <td className="border border-rule p-2">
                      {r.certificate_id !== null ? <Badge tone="verified">발급됨</Badge> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {picked.length > 0 ? (
        <section className="flex flex-col gap-4" data-testid="certificates-compose">
          <SectionHeading title="발급할 상장" />
          {picked.map((p) => (
            <div
              key={p.submissionId}
              className="flex flex-col gap-3 border border-rule bg-surface p-4"
              data-testid={`certificates-draft-${p.submissionId}`}
            >
              <CertificateFields
                value={p.text}
                onChange={(text) => updateText(p.submissionId, text)}
                dateMin={defaults.award_date_min}
                dateMax={defaults.award_date_max}
                testIdPrefix={`certificates-draft-${p.submissionId}`}
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={buttonClass("secondary", "sm")}
                  disabled={busy}
                  onClick={() => void showPreview(p.text.recipient_name, p.text)}
                  data-testid={`certificates-preview-${p.submissionId}`}
                >
                  미리보기
                </button>
                <button
                  type="button"
                  className={buttonClass("secondary", "sm")}
                  onClick={() => togglePick(p.submissionId, p.text.recipient_name)}
                >
                  빼기
                </button>
              </div>
            </div>
          ))}

          {preview ? (
            <div className="flex flex-col gap-2" data-testid="certificates-preview-panel">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>미리보기 · {preview.recipient}</span>
                <span className="flex gap-3">
                  <a className="underline" href={preview.url} target="_blank" rel="noreferrer">
                    새 탭에서 열기
                  </a>
                  <button type="button" className="underline" onClick={() => setPreview(null)}>
                    닫기
                  </button>
                </span>
              </div>
              <iframe
                title="상장 미리보기"
                src={preview.url}
                className="aspect-[297/210] w-full border border-rule bg-surface"
              />
            </div>
          ) : null}

          {confirming ? (
            <div
              className="flex flex-col gap-3 border border-error p-4 text-sm"
              role="alertdialog"
              data-testid="certificates-confirm"
            >
              <p>
                {picked.length}장을 발급합니다. 발급한 상장은 고칠 수 없고, 받는 사람에게 알림이 갑니다.
                고치려면 취소한 뒤 다시 발급해야 합니다.
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={buttonClass("dangerFilled", "sm")}
                  disabled={busy}
                  onClick={() => void issue()}
                  data-testid="certificates-confirm-issue"
                >
                  발급
                </button>
                <button
                  type="button"
                  className={buttonClass("secondary", "sm")}
                  onClick={() => setConfirming(false)}
                >
                  돌아가기
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                type="button"
                className={buttonClass("primary")}
                disabled={busy}
                onClick={() => setConfirming(true)}
                data-testid="certificates-issue"
              >
                {picked.length}장 발급
              </button>
            </div>
          )}
        </section>
      ) : null}

      <section className="flex flex-col gap-3" data-testid="certificates-issued">
        <SectionHeading
          title="발급한 상장"
          hint={
            validCount > 0 ? (
              <button
                type="button"
                className="underline"
                onClick={() =>
                  void download(
                    api(contestId, bundleIds.length > 0 ? `/bundle.pdf?ids=${bundleIds.join(",")}` : "/bundle.pdf"),
                    `certificates-${contestId}.pdf`,
                  )
                }
                data-testid="certificates-bundle"
              >
                {bundleIds.length > 0 ? `고른 ${bundleIds.length}장 받기` : `묶음 받기 (전체 ${validCount})`}
              </button>
            ) : null
          }
        />
        {board.certificates.length === 0 ? (
          <EmptyState>
            <span data-testid="certificates-issued-empty">발급한 상장이 없습니다.</span>
          </EmptyState>
        ) : (
          <ul className="flex flex-col">
            {board.certificates.map((c) => {
              const status = certificateStatus(c);
              return (
                <li
                  key={c.id}
                  className="flex flex-col gap-3 border border-rule border-t-0 p-3 first:border-t sm:p-4"
                  data-testid={`certificates-row-${c.id}`}
                  data-status={status}
                >
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                    <div className="flex min-w-0 items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1"
                        aria-label={`${c.recipient_name} 상장 선택`}
                        checked={bundleIds.includes(c.id)}
                        disabled={!downloadable(c)}
                        onChange={() => toggleBundle(c.id)}
                        data-testid={`certificates-select-${c.id}`}
                      />
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="break-all font-medium">
                          {c.recipient_name} · {c.award_name}
                        </span>
                        <span className="font-mono text-xs text-ink/60">
                          {c.number} · {formatDeadlineSeoul(c.issued_at)}
                        </span>
                      </div>
                    </div>
                    <Badge tone={status === "valid" ? "verified" : "neutral"}>{STATUS_LABEL[status]}</Badge>
                  </div>

                  {status === "valid" ? (
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                      {c.pdf_available ? null : (
                        <span className="text-ink/60" data-testid={`certificates-unavailable-${c.id}`}>
                          받는 사람 탈퇴 — 파일 없음
                        </span>
                      )}
                      <button
                        type="button"
                        className="underline disabled:no-underline disabled:opacity-40"
                        disabled={!c.pdf_available}
                        onClick={() => void download(api(contestId, `/${c.id}/pdf`), `certificate-${c.number}.pdf`)}
                        data-testid={`certificates-download-${c.id}`}
                      >
                        받기
                      </button>
                      <button
                        type="button"
                        className="underline disabled:no-underline disabled:opacity-40"
                        disabled={!c.pdf_available}
                        onClick={() => {
                          setReissue({
                            id: c.id,
                            text: {
                              award_name: c.award_name,
                              recipient_name: c.recipient_name,
                              body: c.body,
                              giver_name: c.giver_name,
                              giver_title: c.giver_title,
                              award_date: c.award_date,
                            },
                          });
                          setCancelling(null);
                        }}
                        data-testid={`certificates-reissue-${c.id}`}
                      >
                        다시 발급
                      </button>
                      <button
                        type="button"
                        className="underline"
                        onClick={() => {
                          setCancelling(c.id);
                          setReissue(null);
                        }}
                        data-testid={`certificates-cancel-${c.id}`}
                      >
                        취소
                      </button>
                    </div>
                  ) : null}

                  {cancelling === c.id ? (
                    <div
                      className="flex flex-col gap-3 border border-error p-3 text-sm"
                      role="alertdialog"
                      data-testid={`certificates-cancel-confirm-${c.id}`}
                    >
                      <p>
                        {c.number} 을(를) 취소합니다. 확인 페이지에 「취소됨」으로 보이고 되돌릴 수 없습니다.
                        다시 받는 사람에게 발급하려면 새 번호로 발급해야 합니다.
                      </p>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className={buttonClass("dangerFilled", "sm")}
                          disabled={busy}
                          onClick={() => void cancel(c.id)}
                          data-testid={`certificates-cancel-go-${c.id}`}
                        >
                          취소하기
                        </button>
                        <button
                          type="button"
                          className={buttonClass("secondary", "sm")}
                          onClick={() => setCancelling(null)}
                        >
                          돌아가기
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {reissue?.id === c.id ? (
                    <div className="flex flex-col gap-3" data-testid={`certificates-reissue-form-${c.id}`}>
                      <CertificateFields
                        value={reissue.text}
                        onChange={(text) => setReissue({ id: c.id, text })}
                        dateMin={defaults.award_date_min}
                        dateMax={defaults.award_date_max}
                        testIdPrefix={`certificates-reissue-${c.id}`}
                      />
                      <p className="text-sm text-ink/75">
                        지금 상장은 취소되고 새 번호로 발급됩니다. 받는 사람에게 알림이 갑니다.
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className={buttonClass("dangerFilled", "sm")}
                          disabled={busy}
                          onClick={() => void reissueNow()}
                          data-testid={`certificates-reissue-go-${c.id}`}
                        >
                          다시 발급
                        </button>
                        <button
                          type="button"
                          className={buttonClass("secondary", "sm")}
                          onClick={() => setReissue(null)}
                        >
                          돌아가기
                        </button>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </main>
  );
}
