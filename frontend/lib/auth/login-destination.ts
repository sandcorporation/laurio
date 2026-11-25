// 이미 로그인한 사람이 `/login` 에 오면 보낼 자리(#1381). 소셜 로그인의 authorize 라우트와 같은
// 규칙이다 — `next` 는 같은 오리진 경로만, `next_origin` 은 허용목록을 통과한 `returnOrigin` 만.
import { resolveNextPath, withoutForeignNext } from "./next-path";

export function loggedInDestination(
  next: string | null,
  requestedNextOrigin: string | null,
  returnOrigin: string | null,
): string {
  const path = withoutForeignNext(resolveNextPath(next), requestedNextOrigin, returnOrigin);
  return returnOrigin ? new URL(path, returnOrigin).toString() : path;
}
