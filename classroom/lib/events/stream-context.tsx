"use client";

// 강의실 레이아웃이 탭마다 여는 스트림 하나(ADR-0046) — 참여자·강사 화면은
// `useEventStream()`으로 이 스트림을 나눠 구독만 한다. 새 신호 종류가
// 생겨도(#381~#383) 이 파일은 신호를 그대로 넘겨줄 뿐 해석하지 않는다 —
// "무엇에 반응할지"는 구독하는 화면의 몫이다(`lib/notifications/read-bus.ts`와
// 같은 원칙, 다만 여기는 서버가 미는 진짜 스트림이다).
//
// **세션이 확인되기 전에는 열지 않는다** — `useMeState()`와 같은 신호를 쓴다
// (`use-unread-count.ts`와 같은 이유): `/login`·`/join/{code}`처럼 로그인
// 없이도 보이는 페이지에서 매번 401 스트림을 열 이유가 없다.
//
// **탭이 숨겨지면 닫고, 다시 보이면 새로 연다**(ADR-0046 Implementation
// Decisions) — 보고 있지 않은 탭이 서버 연결을 계속 붙잡지 않는다. 다시
// 보이면 새 연결이 열리고, 그 연결이 실제로 열리는 순간(`open` 이벤트) 아래
// `decideStreamRefresh`를 쓰는 각 구독자가 알아서 재조회한다 — 이 파일은
// "지금 상태가 무엇인가"만 들고 있는다.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useMeState } from "@/lib/auth/me-context";

import {
  ATTEMPT_SCORED,
  NOTIFICATION_CHANGED,
  type StreamConnectionState,
  type StreamEvent,
} from "./types";

type Listener = (event: StreamEvent) => void;

interface EventStreamContextValue {
  connectionState: StreamConnectionState;
  subscribe: (listener: Listener) => () => void;
}

const EventStreamContext = createContext<EventStreamContextValue | null>(null);

const STREAM_URL = "/api/backend/classroom/events/stream";

// 지금 백엔드가 내는 신호 종류 전부 — 새 종류가 생기면 여기 한 줄만 늘린다
// (`EventSource`는 이름이 등록된 이벤트만 `addEventListener`로 받는다).
const KNOWN_EVENT_KINDS = [ATTEMPT_SCORED, NOTIFICATION_CHANGED];

export function EventStreamProvider({ children }: { children: ReactNode }) {
  const me = useMeState();
  const isReady = me.status === "ready";
  const [connectionState, setConnectionState] = useState<StreamConnectionState>("connecting");
  const listenersRef = useRef<Set<Listener>>(new Set());

  useEffect(() => {
    if (!isReady) return;
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") return;

    let source: EventSource | null = null;

    const open = () => {
      if (source !== null) return;
      setConnectionState("connecting");
      source = new EventSource(STREAM_URL);
      source.onopen = () => setConnectionState("open");
      // `EventSource`는 끊기면 스스로 재연결을 시도한다 — 그때마다 다시
      // `onopen`이 온다. 우리는 그 사이 "끊긴 동안"을 폴링 대상으로 본다.
      source.onerror = () => setConnectionState("closed");
      for (const kind of KNOWN_EVENT_KINDS) {
        source.addEventListener(kind, (messageEvent: MessageEvent<string>) => {
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(messageEvent.data) as Record<string, unknown>;
          } catch {
            return;
          }
          const event: StreamEvent = { kind, payload };
          for (const listener of listenersRef.current) listener(event);
        });
      }
    };

    const close = () => {
      source?.close();
      source = null;
      setConnectionState("closed");
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") open();
      else close();
    };

    if (document.visibilityState === "visible") open();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      close();
    };
  }, [isReady]);

  const subscribe = useCallback((listener: Listener) => {
    listenersRef.current.add(listener);
    return () => {
      listenersRef.current.delete(listener);
    };
  }, []);

  const value = useMemo<EventStreamContextValue>(
    () => ({ connectionState, subscribe }),
    [connectionState, subscribe],
  );

  return <EventStreamContext.Provider value={value}>{children}</EventStreamContext.Provider>;
}

export function useEventStream(): EventStreamContextValue {
  const ctx = useContext(EventStreamContext);
  if (ctx === null) {
    throw new Error("useEventStream()은 EventStreamProvider 트리 안에서만 쓸 수 있다");
  }
  return ctx;
}
