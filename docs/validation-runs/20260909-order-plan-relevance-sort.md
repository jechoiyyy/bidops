# 발주계획 검토 목록 relevance 우선순위 정렬

2026-09-09 사용자 요청으로 복수 필터 선택 시 섞여 보이던 검토 목록을
`relevant → uncertain → not_relevant → null` 순으로 표시한다.
같은 relevance 안에서는 API 응답 순서를 유지한다. 전체 필터 결과에 적용한 뒤
500건 단위로 나누므로 방향키와 다음 건 이동도 같은 순서를 따른다.
API·모델 판정·사람 추적 상태는 변경하지 않았다.

## 검증

- `npm run build -- --outDir /tmp/bidops-sort-build/dist`: 통과.
- `npm run test:contrast`: 9개 통과.
- `PW_PORT=4297 PW_OUT_DIR=/tmp/bidops-sort-build/dist npm run test:screens -- --workers=4`:
  502개 통과, 5개 skip, 사업 추적 미저장 입력 검사 1개 실패.
  실패는 저장 후 beforeunload 기본 방지 해제가 아직 반영되지 않은 단언이었다.
- 테스트 작성 중 페이지 경계 검사에서 선택 URL 갱신을 기다리지 않아 실패한 사례가 있어,
  기존 키보드 테스트와 같이 선택 행의 aria-current 갱신을 기다리도록 했다.
- 최종 `tests/order-plans.spec.ts tests/draft.spec.ts --project=app --workers=2`:
  42개 전부 통과. 위 전체 실행 실패도 재현되지 않았다.
  혼합 순서 API 응답, 역순 필터 토큰, 같은 그룹 순서 보존, 600건의 API/화면 페이지 경계 및
  키보드 이동을 포함한다. 테스트 데이터 외 실제 판정 쓰기는 수행하지 않았다.

## 배포

- `bidops-relevance-sort:20260909` 이미지로 기존 web만 재생성했다.
- 환경변수·mount·network·port 설정을 보존했고 health는 healthy다.
- 실제 18887 서버의 정적 파일 75개가 검증 빌드와 SHA-256 일치했다.
- 1280×800 및 1440×900에서 `qwen=uncertain,relevant`로 조회해
  실제 153건이 relevant 52건 다음 uncertain 101건 순으로 표시됨을 확인했다.
- 실행 로그와 이전 이미지 복귀 설정:
  `/home/jechoi/.local/state/bidops/deployments/relevance-sort-cb79b858/`.
