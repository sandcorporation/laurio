// GitHub 저장소 주소를 제출 전에 판정하고 정리한다 — 강의실·공개 앱의 제출 화면이 같이 쓴다.
// 모양의 원본은 백엔드 `submissions.models.GITHUB_REPO_URL_PATTERN` 이고, 백엔드도 끝의 `.git`·`/`
// 를 떼고 저장한다(`normalize_github_repo_url`). 여기서는 그 전에 참여자에게 바로 말해 준다:
// - 끝의 `.git`·`/`, `http://`·`www.` 는 같은 저장소라 말없이 고친다.
// - SSH 주소(`git@github.com:…`, `ssh://…`)·파일이나 브랜치 주소는 거부하고, 고칠 수 있으면 https
//   저장소 주소를 제안한다.
// React·Next 를 모르는 순수 함수다.

export type RepositoryUrlCheck =
  | { ok: true; url: string }
  | { ok: false; message: string; suggestion: string | null };

const SEGMENT = /^[A-Za-z0-9._-]{1,100}$/;
const FORMAT_MESSAGE = "GitHub 저장소 주소만 받습니다 — https://github.com/<owner>/<repo> 형식으로 넣어 주세요.";

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
  if (rest !== "") {
    return {
      ok: false,
      message: "저장소 주소만 넣어 주세요 — 파일·브랜치 주소가 아니라 저장소 첫 화면의 주소입니다.",
      suggestion: url,
    };
  }
  return { ok: true, url };
}
