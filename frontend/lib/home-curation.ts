// 홈의 네 묶음을 문구로 옮기는 번역표(#94, spec #92).
//
// **이 파일이 안전망이다.** `HomeCurationBucket`은 백엔드가 정한 enum이고
// (`contests.curation.HomeCurationBucket`), 생성된 타입에서 리터럴 유니온으로
// 내려온다. 아래 두 상수는 그 유니온을 키로 하는 `Record`라서, 값이 하나
// 늘면(예: 새 Contest.Status가 다섯 번째 묶음을 만들면) 이 파일이 모든 키를
// 채우지 못해 `tsc --noEmit`이 빌드타임에 잡는다 — #74의 `can_appeal`,
// #81의 `no_submissions` 가 잡힌 것과 같은 안전망이다. `Partial<Record<...>>`나
// `string`으로 완화하지 않는다 — 그 순간 이 안전망이 사라진다.
import type { HomeCurationBucket } from "./api/contests";

export const HOME_BUCKET_LABELS: Record<HomeCurationBucket, string> = {
  ongoing: "진행중",
  imminent: "마감임박",
  in_judging: "심사중",
  completed: "완료",
};

// 그 묶음에 지금 아무것도 없을 때 보여줄 문구. 섹션 자체를 지우지 않는다 — 홈이
// 네 묶음을 늘 다 보여주는 이유가 여기 있다(#94 인수조건: 어떤 묶음이 비어
// 있어도 그 사실이 보여야 한다).
export const HOME_BUCKET_EMPTY_MESSAGES: Record<HomeCurationBucket, string> = {
  ongoing: "지금 진행 중인 공모전이 없습니다.",
  imminent: "마감이 임박한 공모전이 없습니다.",
  in_judging: "심사 중인 공모전이 없습니다.",
  completed: "아직 끝난 공모전이 없습니다.",
};
