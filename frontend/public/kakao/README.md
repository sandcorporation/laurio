# 카카오 로그인 버튼 이미지

`kakao_login_large_wide.png` 는 카카오가 배포하는 **공식 완성형 버튼 이미지**다
(600×90, 리소스 다운로드 > 카카오 로그인 > 완성형 > 한국어 > large/wide).
받은 곳: https://developers.kakao.com/tool/resource/login

**직접 그리지 않고 이 파일을 쓰는 이유**: 카카오 로그인 디자인 가이드가 말풍선
심볼을 필수로 요구하면서 **심볼의 형태·비율·색상 변경을 금지**하는데, 공식
벡터(SVG)는 배포하지 않는다(PNG·PSD 뿐이다). 그래서 우리가 심볼을 그리면 그
조항에 걸린다 — 배포본을 그대로 쓰는 것이 규정을 지키는 유일한 길이다.

**고치지 않는다.** 자르기·색 변경·회전·비율 변경 모두 가이드가 막는다. 화면은
이 파일을 폭 300·높이 45(원본의 정확히 1/2)로 **비율 그대로** 줄여 그린다
(`frontend/app/login/login-form.tsx`). 더 큰 자리에 쓸 일이 생기면 원본 크기를
그대로 쓰거나, 카카오가 주는 다른 크기 판을 다시 받는다.

가이드: https://developers.kakao.com/docs/latest/ko/kakaologin/design-guide
