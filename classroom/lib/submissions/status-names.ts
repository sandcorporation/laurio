// 강사·참여자 화면이 미채점 시도를 부르는 두 이름의 단일 출처(#1430).
// 키·모델 사정으로 멈춘 시도(`pending_reason`·`needs_setup`)는 어느 화면에서나 「채점 대기」다.
export const WAITING_LABEL = "채점 대기";
export const SCORING_LABEL = "채점 중";

/** 미채점 시도의 이름 — 사유가 있으면(키·모델 사정으로 멈춤) 대기, 없으면 채점 중. */
export function pendingLabel(blocked: boolean): string {
  return blocked ? WAITING_LABEL : SCORING_LABEL;
}
