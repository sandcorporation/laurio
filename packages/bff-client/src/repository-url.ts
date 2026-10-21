// GitHub 저장소 주소를 제출 전에 판정하고 정리한다 — 강의실·공개 앱의 제출 화면이 같이 쓴다.
// 모양의 원본은 백엔드 `submissions.models.GITHUB_SUBMISSION_URL_PATTERN`(#777) 이고, 백엔드도
// 끝의 `.git`·`/` 를 떼고 저장한다(`parse_github_submission_url`). 여기서는 그 전에 참여자에게
// 바로 말해 준다:
// - 받는 모양은 셋 — 저장소 `https://github.com/<owner>/<repo>`, 브랜치 `…/tree/<ref>`(뒤 전체가
//   브랜치 이름, `release/2024` 처럼 슬래시 포함 — 디렉터리 경로와 구분하지 않고 GitHub 에 묻는다),
//   커밋 `…/commit/<sha>`(7~40자 16진수).
// - 끝의 `.git`·`/`, `http://`·`www.` 는 같은 저장소라 말없이 고친다.
// - SSH 주소(`git@github.com:…`, `ssh://…`)·그 밖의 경로(`/blob/`·`/pull/`·ref 없는 `/tree/`)는
//   거부하고, 고칠 수 있으면 https 저장소 주소를 제안한다.
// React·Next 를 모르는 순수 함수다.

export type RepositoryUrlCheck =
  | { ok: true; url: string }
  | { ok: false; message: string; suggestion: string | null };

const SEGMENT = /^[A-Za-z0-9._-]{1,100}$/;
const COMMIT_SHA = /^[0-9a-f]{7,40}$/i;
const REF_MAX_LENGTH = 255;
const SHAPES = "https://github.com/<owner>/<repo> · …/tree/<브랜치> · …/commit/<sha>";
const FORMAT_MESSAGE = `GitHub 저장소 주소만 받습니다 — ${SHAPES} 형식으로 넣어 주세요.`;

function repositoryUrl(owner: string, repo: string): string | null {
  const name = repo.replace(/\.git$/i, "");
  if (!SEGMENT.test(owner) || !SEGMENT.test(name)) return null;
  return `https://github.com/${owner}/${name}`;
}

/** 빈 입력이면 null. */
export function checkGithubRepositoryUrl(raw: string): RepositoryUrlCheck | null {
  const value = raw.trim();
  if (value === "") return null;

  const ssh = /^(?:ssh:\/\/)?git@github\.com[:/]([^/\s]+)\/([^/\s]+?)\/?$/i.exec(value);
  if (ssh) {
    return {
      ok: false,
      message: "SSH 주소는 받지 않습니다 — 저장소 페이지의 https 주소를 넣어 주세요.",
      suggestion: repositoryUrl(ssh[1], ssh[2]),
    };
  }

  const web = /^https?:\/\/(?:www\.)?github\.com\/([^/?#\s]+)\/([^/?#\s]+)(\/[^?#\s]*)?([?#]\S*)?$/i.exec(value);
  if (!web) return { ok: false, message: FORMAT_MESSAGE, suggestion: null };

  const url = repositoryUrl(web[1], web[2]);
  if (url === null) return { ok: false, message: FORMAT_MESSAGE, suggestion: null };
  const rest = (web[3] ?? "").replace(/\/+$/, "");
  if (rest === "") return { ok: true, url };

  const branch = /^\/tree\/(.+)$/.exec(rest);
  if (branch && branch[1].length <= REF_MAX_LENGTH) return { ok: true, url: `${url}/tree/${branch[1]}` };
  const commit = /^\/commit\/([^/]+)$/.exec(rest);
  if (commit && COMMIT_SHA.test(commit[1])) return { ok: true, url: `${url}/commit/${commit[1].toLowerCase()}` };

  return {
    ok: false,
    message: `저장소·브랜치·커밋 주소만 넣어 주세요 — ${SHAPES} 형식입니다.`,
    suggestion: url,
  };
}

/** 낸 주소에서 저장소 첫 화면 주소만 — `…/tree/<ref>`·`…/commit/<sha>` 를 뗀다. 커밋 링크를 조립할 때 쓴다. */
export function repositoryRootUrl(url: string): string {
  return url.replace(/\/(?:tree|commit)\/.*$/, "");
}

/** 고정 커밋 링크 — `https://github.com/<owner>/<repo>/commit/<sha>`. */
export function commitUrl(submittedUrl: string, sha: string): string {
  return `${repositoryRootUrl(submittedUrl)}/commit/${sha}`;
}

/** 화면에 보일 짧은 SHA(7자). */
export function shortSha(sha: string): string {
  return sha.slice(0, 7);
}
