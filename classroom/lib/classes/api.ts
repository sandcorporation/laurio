// Class 백엔드 호출 (#278).
import { backendJson } from "@/lib/backend/client";

export type ClassRow = {
  id: number;
  name: string;
  created_at: string;
};

export function fetchMyClasses(): Promise<ClassRow[]> {
  return backendJson<ClassRow[]>("/classroom/classes");
}

export function fetchClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}`);
}

export function createClass(name: string): Promise<ClassRow> {
  return backendJson<ClassRow>("/classroom/classes", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}
