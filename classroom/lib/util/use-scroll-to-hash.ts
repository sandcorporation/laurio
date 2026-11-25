import { useEffect, useRef } from "react";

// 주소의 `#구획`은 구획이 데이터를 읽은 뒤에야 그려져 브라우저의 첫 이동이 놓친다 —
// `ready` 가 처음 참이 된 때 한 번 그 구획으로 옮긴다(#658, #1429).
export function useScrollToHash(ready: boolean) {
  const done = useRef(false);
  useEffect(() => {
    if (!ready || done.current) return;
    done.current = true;
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(decodeURIComponent(id))?.scrollIntoView();
  }, [ready]);
}
