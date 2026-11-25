// 클라이언트 화면은 `metadata` 를 못 내므로 탭 제목은 이 레이아웃이 단다(#1478 4).
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "이의 신청" };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
