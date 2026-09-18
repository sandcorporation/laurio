// 업로드 실패를 사람의 말과 진단용 값으로 가른다 (2026-09-18).
//
// **왜 생겼나.** prod 에서 소스 파일 업로드가
// `Failed to fetch (…objectstorage…oraclecloud.com)` 로 실패했다. 두 가지가
// 한꺼번에 잘못돼 있었다.
//
// 1. **화면이 브라우저의 영어 원문을 그대로 보여 줬다** — 사용자는 무엇을
//    해야 할지 알 수 없고, 화면 문구 규칙(한국어)에도 어긋난다.
// 2. **오류 수집기에 아무것도 남지 않았다** — 코드가 예외를 잡아 화면에만
//    쓰고 끝냈기 때문이다(잡힌 예외는 SDK 가 자동으로 보내지 않는다). 그래서
//    「그때 무슨 일이 있었나」를 나중에 물어볼 자리가 없었다.
//
// 이 모듈은 그 둘을 가른다: 사람에게는 무엇을 하면 되는지, 오류 수집기에는
// 어느 주소로 어떤 방식으로 보내다 실패했는지.
//
// **네트워크 실패와 응답 실패는 다른 사건이다.** `fetch` 가 던지는 TypeError 는
// 요청이 상대에 닿지도 못했다는 뜻이다(끊긴 네트워크·차단 확장·DNS·TLS·CORS).
// 상태 코드가 있는 실패는 닿았는데 거절당한 것이다(서명 만료·크기 초과·권한).
// 사용자가 할 수 있는 일이 서로 다르므로 문구도 가른다.

/** 업로드가 실패한 자리 — 오류 수집기의 태그가 된다. */
export type UploadFailureContext = {
  /** 바이트를 받기로 한 주소. 호스트만 태그로 남긴다(서명 쿼리는 남기지 않는다). */
  uploadUrl: string;
  /** "POST"(서명된 정책, 크기 상한이 있는 슬롯) 또는 "PUT". */
  method: string;
  /** 올리려던 파일 크기(바이트). 크기 때문에 거절당한 경우를 가린다. */
  fileSize: number;
  /** 스토리지가 돌려준 상태 코드. 네트워크 실패면 없다. */
  status?: number;
};

export type UploadFailure = {
  /** 화면에 그대로 보여 줄 한국어 한 문장. */
  message: string;
  /** 오류 수집기에 실을 태그 — 값은 전부 짧은 문자열이다. */
  tags: Record<string, string>;
};

/** 서명 쿼리를 떼고 호스트만 남긴다 — 서명은 짧은 수명이라도 기록에 남기지 않는다. */
function hostOf(uploadUrl: string): string {
  try {
    return new URL(uploadUrl).host;
  } catch {
    return "unknown";
  }
}

/**
 * 던져진 오류와 그 자리를 받아 「사람에게 할 말」과 「수집기에 남길 태그」를 만든다.
 *
 * 화면 문구는 사용자가 다음에 할 수 있는 일로 끝난다 — 주소나 상태 코드 같은
 * 진단값은 문구에 넣지 않는다(그건 태그의 몫이다).
 */
export function describeUploadFailure(
  error: unknown,
  context: UploadFailureContext,
): UploadFailure {
  const tags: Record<string, string> = {
    upload_host: hostOf(context.uploadUrl),
    upload_method: context.method,
    upload_file_bytes: String(context.fileSize),
  };

  if (context.status !== undefined) {
    tags.upload_status = String(context.status);
    tags.upload_failure = "response";
    return {
      message:
        context.status === 403
          ? "업로드 권한이 만료됐습니다. 파일을 다시 선택해주세요."
          : "업로드가 거절됐습니다. 파일을 다시 선택해주세요.",
      tags,
    };
  }

  tags.upload_failure = "network";
  tags.upload_error = error instanceof Error ? error.name : typeof error;
  return {
    message:
      "업로드 서버에 연결하지 못했습니다. 네트워크 상태를 확인하고 다시 시도해주세요.",
    tags,
  };
}
