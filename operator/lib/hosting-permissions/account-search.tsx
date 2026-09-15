"use client";

// 계정 검색(#414) — 이메일·닉네임으로 찾는다. 빈 검색어는 백엔드가 아무것도
// 돌려주지 않으므로(`contests.hosting_permission_services.search_accounts`)
// 여기서도 빈 채로 눌러도 결과가 비어 있다.
//
// **`refreshSignal`이 바뀌면 이미 낸 검색을 다시 낸다.** 아래 「권한 보유
// 계정」 표에서 같은 계정을 회수해도 이 컴포넌트의 결과는 자기 상태라 저절로
// 안 바뀐다 — 그대로 두면 검색 결과가 "있음"인 채로 멎어 다시 누르면 이미
// 회수된 상태를 또 회수하려다 409를 받는다(직접 걸어보다 발견). 부모가 두
// 표(보유 목록·이력)를 새로고침하는 바로 그 신호를 여기도 받는다 — 아직
// 검색한 적 없으면("idle") 아무 일도 하지 않는다.
import { useEffect, useState } from "react";

import { searchHostingPermissionAccounts } from "./actions";
import { HostingPermissionAccountRow } from "./account-row";
import type { HostingPermissionAccount } from "./types";

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; accounts: HostingPermissionAccount[] };

export function HostingPermissionAccountSearch({
  canEdit,
  refreshSignal,
  onChanged,
  onSessionExpired,
}: {
  canEdit: boolean;
  refreshSignal: number;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<SearchState>({ status: "idle" });

  async function handleSearch() {
    setState({ status: "loading" });
    const result = await searchHostingPermissionAccounts(query);
    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setState({ status: "error" });
      return;
    }
    setState({ status: "loaded", accounts: result.data });
  }

  function handleRowChanged() {
    onChanged();
    handleSearch();
  }

  useEffect(() => {
    if (state.status === "idle") return;
    handleSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  return (
    <div data-testid="hosting-permission-account-search">
      <label>
        이메일 또는 닉네임
        <input
          data-testid="hosting-permission-search-query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") handleSearch();
          }}
        />
      </label>
      <button
        type="button"
        data-testid="hosting-permission-search-button"
        onClick={handleSearch}
        disabled={state.status === "loading"}
      >
        검색
      </button>

      {state.status === "error" && (
        <p role="alert" data-testid="hosting-permission-search-error">
          검색하지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {state.status === "loaded" && state.accounts.length === 0 && (
        <p data-testid="hosting-permission-search-empty">일치하는 계정이 없습니다.</p>
      )}

      {state.status === "loaded" && state.accounts.length > 0 && (
        <table data-testid="hosting-permission-search-results">
          <thead>
            <tr>
              <th>이메일</th>
              <th>닉네임</th>
              <th>개최 권한</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {state.accounts.map((account) => (
              <HostingPermissionAccountRow
                key={account.user_id}
                account={account}
                canEdit={canEdit}
                onChanged={handleRowChanged}
                onSessionExpired={onSessionExpired}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
