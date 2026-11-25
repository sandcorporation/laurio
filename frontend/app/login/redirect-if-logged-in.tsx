"use client";

// 세션 쿠키를 들고 `/login` 에 온 사람(#1381). 쿠키가 있다는 것만으로는 보내지 않는다 — 죽은
// 세션이면 도착지가 다시 `/login` 으로 돌려보내 끝없이 오간다. `/api/auth/session` 이 백엔드까지
// 확인하고(만료면 리프레시해 새 쿠키를 심는다) 200 일 때만 보내며, 아니면 폼을 보인다.
// `bffClient` 를 쓰지 않는다 — 401 에서 `/login` 으로 보내는 클라이언트다.
import { useEffect, useState, type ReactNode } from "react";

export default function RedirectIfLoggedIn({ destination, children }: { destination: string; children: ReactNode }) {
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/auth/session", { cache: "no-store" })
      .then((response) => {
        if (cancelled) return;
        if (response.ok) window.location.replace(destination);
        else setShowForm(true);
      })
      .catch(() => {
        if (!cancelled) setShowForm(true);
      });
    return () => {
      cancelled = true;
    };
  }, [destination]);

  return showForm ? children : null;
}
