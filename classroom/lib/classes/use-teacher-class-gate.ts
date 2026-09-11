"use client";

// 빈 상태 문구가 「강사인 클래스가 있는가」로 갈리는 화면 셋이 같은 판정을
// 쓴다(#343: 알림, 내가 올린 템플릿의 문제·클래스 탭). `useMyClasses`의 세
// 상태(loading·error·ready)를 문구 결정에 필요한 두 값으로 좁힌다 —
// 판정이 끝나기 전에는 어느 쪽으로도 단정하지 않고(pending), 확인되지
// 않으면(error 포함) 있다고 가정한다(hasTaughtClasses 기본 true) — 첫
// 화면(#332)의 "조회 실패는 모른다이지 없다가 아니다"와 같은 기준.
import { useMyClasses } from "./use-my-classes";

export type TeacherClassGate = { pending: boolean; hasTaughtClasses: boolean };

export function useTeacherClassGate(): TeacherClassGate {
  const taught = useMyClasses();
  return {
    pending: taught.status === "loading",
    hasTaughtClasses: taught.status !== "ready" || taught.classes.length > 0,
  };
}
