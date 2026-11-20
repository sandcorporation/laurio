import { expect, test } from "@playwright/test";

import { KakaoTokenExchangeError, exchangeKakaoCodeForToken } from "../../lib/auth/kakao";

// 카카오 code→token 교환의 옵인 live 테스트 (#95, spec #92 Testing Decisions).
// 이 티켓의 유일한 벤더 호출을 검증한다 — 백엔드의 tests/live.py(#83,
// live_vendor 마커 + require_live_credential)가 세운 관용구를 프론트 쪽에서
// 흉내낸다: 자격증명이 없으면 실패가 아니라 skip되고, 값이 아니라 "인증이
// 통했다"는 모양만 본다.
//
// **기본 실행에서 항상 skip된다** — KAKAO_LIVE_REST_API_KEY/
// KAKAO_LIVE_SECRET_KEY가 있을 때만 돈다. 이 두 값은 frontend/lib/auth/kakao.ts
// 가 실제로 읽는 KAKAO_REST_API_KEY/KAKAO_SECRET_KEY와 일부러 다른 이름이다 —
// dev/CI는 BFF 왕복(authorize→callback state 검증 등)을 결정적으로 테스트하려고
// docker/compose.dev.yaml의 frontend 서비스에 그 이름으로 더미 값을 채워
// 둔다(e2e/oauth-kakao.spec.ts). 이름을 겹치면 이 live 테스트가 dev/CI에서도
// 매번 돌며 더미 값으로 실제 카카오 서버에 네트워크 요청을 보내다 실패해
// "옵인"이라는 전제가 깨진다.
//
// code는 사람이 카카오 동의 화면에서 로그인해야만 얻을 수 있다 — 백그라운드
// 에이전트도, CI도 브라우저로 그 동의를 대신할 수 없다. 그래서 "제대로 된
// code로 로그인이 끝까지 된다"는 이 테스트가 증명하지 않는다(그건 사람이
// 실제 브라우저로 한 번 확인해야 하는 몫이다 — payments.spec류 live 테스트가
// confirm을 못 미는 것과 같은 한계). 대신 **자격증명 자체가 카카오에
// 인식되는지**만 본다: 일부러 잘못된 code로 교환을 시도해, 카카오가
// "code가 틀렸다"(invalid_grant류)로 거절하는지 "앱 자체를 모른다"
// (invalid_client류)로 거절하는지를 구분한다 — 전자면 client_id/secret은
// 카카오가 이미 인식했다는 뜻이다.
test.describe("카카오 OAuth — 옵인 live 테스트", () => {
  test("실제 client_id/secret이 카카오에 인식된다 — 잘못된 code는 invalid_client가 아니라 invalid_grant로 거절된다", async () => {
    const clientId = process.env.KAKAO_LIVE_REST_API_KEY;
    const clientSecret = process.env.KAKAO_LIVE_SECRET_KEY;
    const redirectUri =
      process.env.KAKAO_LIVE_REDIRECT_URI ??
      "https://codemit.kr/api/auth/social/kakao/callback";

    test.skip(
      !clientId || !clientSecret,
      "KAKAO_LIVE_REST_API_KEY/KAKAO_LIVE_SECRET_KEY 가 설정되지 않았다 — live 테스트는 " +
        "실제 카카오 자격증명이 있을 때만 돈다(#83과 같은 원칙). CI·신선한 체크아웃은 " +
        "이 값을 갖지 않으므로 정상적으로 skip된다.",
    );

    let thrown: unknown = null;
    try {
      await exchangeKakaoCodeForToken(
        { clientId: clientId!, clientSecret: clientSecret!, redirectUri },
        "obviously-invalid-authorization-code",
      );
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(KakaoTokenExchangeError);
    const message = (thrown as Error).message;
    // invalid_client(앱 자격증명 자체가 틀렸다)가 나오면 이 테스트가 증명하려는
    // 것과 정반대다 — client_id/secret이 카카오에 거절당했다는 뜻이다.
    expect(message).not.toContain("invalid_client");
    expect(message.toLowerCase()).toMatch(/invalid_grant|authorization code|invalid.*code/);
  });
});
