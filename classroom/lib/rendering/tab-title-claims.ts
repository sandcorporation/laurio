// 탭 제목을 쓰는 곳은 하나다(#1406). 화면과 그 안의 접근 안내가 저마다 감시자를 달면 서로의 제목을
// 끝없이 덮어써 탭이 멈춘다 — 훅들은 제목을 맡기기만 하고, 이긴 하나를 감시자 하나가 반영한다.

export type TabTitleTarget = {
  read: () => string;
  write: (title: string) => void;
  /** 제목이 바깥에서 바뀔 수 있을 때마다 `onChange` 를 부른다. 돌려주는 함수는 감시를 끊는다. */
  watch: (onChange: () => void) => () => void;
};

type Claim = { title: string; override: boolean };

export function createTabTitleClaims(target: TabTitleTarget) {
  const claims: Claim[] = [];
  let stop: (() => void) | null = null;

  /** `override` 가 있으면 그중 마지막, 없으면 전체의 마지막이 이긴다. */
  const apply = () => {
    const winner = claims.filter((claim) => claim.override).at(-1) ?? claims.at(-1);
    if (winner && target.read() !== winner.title) target.write(winner.title);
  };

  return function claim(title: string, override = false): () => void {
    const entry = { title, override };
    claims.push(entry);
    apply();
    stop ??= target.watch(apply);
    return () => {
      claims.splice(claims.indexOf(entry), 1);
      if (claims.length > 0) return apply();
      stop?.();
      stop = null;
    };
  };
}
