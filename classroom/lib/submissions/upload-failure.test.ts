// 업로드 실패가 사람에게는 한국어로, 수집기에는 진단값으로 갈리는가 (2026-09-18).
//
// prod 에서 소스 업로드가 `Failed to fetch (…oraclecloud.com)` 로 실패했는데,
// 그 영어 원문이 화면에 그대로 나왔고 오류 수집기에는 아무것도 남지 않았다.
import { describe, expect, test } from "vitest";

import { describeUploadFailure } from "./upload-failure";

const CONTEXT = {
  uploadUrl: "https://example-store.objectstorage.example.com/codemit-prod?X-Amz-Signature=deadbeef",
  method: "POST",
  fileSize: 1234,
};

describe("describeUploadFailure — 네트워크 실패", () => {
  test("브라우저의 영어 원문 대신 무엇을 하면 되는지 한국어로 말한다", () => {
    const { message } = describeUploadFailure(new TypeError("Failed to fetch"), CONTEXT);

    expect(message).toContain("네트워크");
    expect(message).not.toContain("Failed to fetch");
  });

  test("어디로 보내다 실패했는지를 태그로 남긴다 — 서명은 남기지 않는다", () => {
    const { tags } = describeUploadFailure(new TypeError("Failed to fetch"), CONTEXT);

    expect(tags.upload_host).toBe("example-store.objectstorage.example.com");
    expect(tags.upload_method).toBe("POST");
    expect(tags.upload_file_bytes).toBe("1234");
    expect(tags.upload_failure).toBe("network");
    expect(tags.upload_error).toBe("TypeError");
    expect(Object.values(tags).join(" ")).not.toContain("deadbeef");
  });

  test("주소가 망가져 있어도 태그를 만들다 죽지 않는다", () => {
    const { tags } = describeUploadFailure(new TypeError("Failed to fetch"), {
      ...CONTEXT,
      uploadUrl: "(not a url)",
    });

    expect(tags.upload_host).toBe("unknown");
  });
});

describe("describeUploadFailure — 응답 실패", () => {
  test("서명이 만료된 403 은 파일을 다시 고르라고 말한다", () => {
    const { message, tags } = describeUploadFailure(new Error("403"), { ...CONTEXT, status: 403 });

    expect(message).toContain("다시 선택");
    expect(tags.upload_status).toBe("403");
    expect(tags.upload_failure).toBe("response");
  });

  test("그 밖의 상태 코드도 상태를 태그로 남긴다", () => {
    const { tags } = describeUploadFailure(new Error("400"), { ...CONTEXT, status: 400 });

    expect(tags.upload_status).toBe("400");
    expect(tags.upload_failure).toBe("response");
  });
});
