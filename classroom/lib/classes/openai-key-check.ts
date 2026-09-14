// 채점 키를 붙여넣는 순간, 저장 전에 브라우저가 직접 벤더에게 물어 쓸 수
// 있는 키인지 미리 말한다(#357). 저장은 백엔드가 다시 확인한다(#354) —
// 이건 문이 아니라 안내다: 판정과 무관하게 저장 버튼은 항상 눌린다.
//
// **브라우저가 우리 서버를 거치지 않고 OpenAI를 직접 친다** — 키의 주인이
// 자기 브라우저에서 자기 키를 쓰는 것이라 키가 새는 경로가 늘지 않고,
// 이 서버의 로그·오류 보고 어디에도 키가 남지 않는다(staging 오리진에서
// api.openai.com으로 나가는 요청이 CORS를 통과하고 잘못된 키에 401을
// 그대로 돌려준다는 것을 실측으로 확인했다). 채점 호출(`/chat/completions`)이
// 아니라 모델 목록 조회(`/v1/models`)를 친다 — 프롬프트도 토큰도 필요 없는
// 가장 값싼 확인이다(백엔드 `core.llm_scoring.OpenAIScoringAdapter.check_key`
// 와 같은 선택).
export type OpenAIKeyCheckResult = "valid" | "invalid" | "unknown";

const OPENAI_MODELS_URL = "https://api.openai.com/v1/models";

export async function checkOpenAIKeyFromBrowser(
  apiKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<OpenAIKeyCheckResult> {
  let response: Response;
  try {
    response = await fetchImpl(OPENAI_MODELS_URL, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
  } catch {
    // 네트워크 자체가 실패했다(사내 프록시·확장 프로그램의 차단 등) —
    // 키가 나쁘다는 뜻이 아니다.
    return "unknown";
  }

  if (response.status === 401 || response.status === 403) return "invalid";
  if (response.ok) return "valid";
  // 그 밖의 상태(429·5xx 등)는 벤더의 그 순간 가용성 문제이지 키 자체의
  // 결함이 아니다 — 「확인할 수 없다」로 묶는다(#354의 백엔드 판정과 같은
  // 원칙: 401·403만 확실한 거절이다).
  return "unknown";
}
