// 공동 강사가 빠졌을 때 강사 탭이 읽어 줄 한 줄(#1517 1). 명단에는 빠진 줄이 없어 까닭은 신호의 `departed` 만이 안다.
export type Departure = { coInstructorId: number; displayName: string; left: boolean };

export function parseDeparture(payload: Record<string, unknown>): Departure | null {
  const d = payload.departed;
  if (typeof d !== "object" || d === null) return null;
  const { co_instructor_id: id, display_name: name, left } = d as Record<string, unknown>;
  if (typeof id !== "number" || typeof name !== "string" || typeof left !== "boolean") return null;
  return { coInstructorId: id, displayName: name, left };
}

export function departureNote(name: string, left: boolean): string {
  const who = name || "이름 없음";
  return left ? `${who}님이 클래스를 떠났습니다` : `${who}님이 클래스에서 내보내졌습니다`;
}

/** 새 명단에서 사라진 공동 강사 줄 — 알던 줄(id→이름)과 새 id 집합을 견준다. */
export function vanishedInstructors(known: Map<number, string>, now: Set<number>): Array<{ id: number; name: string }> {
  return [...known].filter(([id]) => !now.has(id)).map(([id, name]) => ({ id, name }));
}

/** 사라진 줄마다 신호가 실어 온 까닭으로 문구를 만든다. 신호가 없는 줄은 말하지 않는다 — 소유권이 넘어가며 줄이
 *  바뀐 것과 갈리지 않아 틀린 안내가 되기 때문이다. */
export function departureNotes(vanished: Array<{ id: number; name: string }>, departures: Map<number, Departure>): string {
  return vanished
    .flatMap(({ id }) => {
      const d = departures.get(id);
      return d ? [departureNote(d.displayName, d.left)] : [];
    })
    .join(". ");
}
