# 공모전 검색 실물 어댑터가 붙는 OpenSearch — nori(한국어 형태소 분석기) 플러그인만
# 더한다 (#450, 부모 #444 스펙). dev `search` 프로필과 staging·prod(#451)가 같은
# 이미지를 쓴다 — Jenkins `codemit/deploy` 잡의 이미지 단계(scripts/ci/images.sh, #705)가 이 파일로
# amd64·arm64 를 굽는다.
#
# 보안 플러그인은 켜진 채로 두지 않는다(부모 스펙 "보안 플러그인은 끈다") — 이미지
# 자체는 지우지 않고(베이스 이미지 구성 그대로), compose 의 DISABLE_SECURITY_PLUGIN
# 환경변수로 런타임에 끈다(dev/staging/prod 세 compose 가 공통으로 준다) — 이미지를
# 둘로 가르는 것보다 단순하다.
FROM opensearchproject/opensearch:2.19.1

# --batch 는 대화형 확인(플러그인이 요구하는 권한 목록 승인)을 건너뛴다 — Docker
# 빌드는 TTY 가 없어 대화형 프롬프트가 그대로 빌드를 멈춘다.
RUN /usr/share/opensearch/bin/opensearch-plugin install --batch analysis-nori
