// 계정 표의 열 정의 — 검색 결과 표(`account-search.tsx`)와 보유 계정 표
// (`app/hosting-permissions/page.tsx`)가 같은 열을 쓴다(#424, 골간으로 옮긴다).
// 헤더와 행이 서로 다른 파일에서 각자 너비를 정하면 어긋나므로 한 곳에 둔다 —
// `app/payouts/page.tsx`의 `COL`과 같은 이유, 다만 여기는 두 표가 같은 열을
// 써서 상수를 공유로 뺐다.
export const HOSTING_PERMISSION_COL = {
  nickname: "w-[140px]",
  granted: "w-[90px]",
  action: "w-[220px]",
};

export function HostingPermissionTableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">이메일</div>
      <div className={`${HOSTING_PERMISSION_COL.nickname} shrink-0`}>닉네임</div>
      <div className={`${HOSTING_PERMISSION_COL.granted} shrink-0`}>개최 권한</div>
      <div className={`${HOSTING_PERMISSION_COL.action} shrink-0`}>작업</div>
    </div>
  );
}
