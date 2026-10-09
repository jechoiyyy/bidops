# DEMO-01 회사 문맥과 독립 추적

- 기준 SHA: `c2428508ff728b9039158474bafae5bb5357a3d4`.
- 대상: `demo/local-20261009` 전용. main·운영 통합, 실행 중인 로컬 앱 재배포, 실제 모델 호출은 수행하지 않았다.
- 사용자 요청에 따라 현재 로컬/LiteLLM 상황을 반영한 계획을 적용하고 회사 문맥 기능을 구현했다. 기존 커밋·반영 요청의 범위 안에서 검증된 변경을 데모 기준 브랜치에 수동 통합한다. push·브랜치 삭제는 하지 않는다.

## 구현과 증거

| 범위 | 리더 검증 | 증거 |
|---|---|---|
| 회사·추적 스키마, NULL 계보, migration, 역할별 권한 | 132 통과 후 명시적 스키마 기대 목록 4개 보정·4개 통과; skip 0 | [STEP001](step001-result.md) |
| 회사 목록·상세, 비활성 경로 404, legacy 자동 분석 분리 | 신규 SQLite/PG 14개 최종 통과, 기존 관련 121개 통과 | [STEP002](step002-result.md) |
| 기존 자동 경로 | 63개 통과 + 활성 분기 명시 후 13개 통과, 기존 실패 1개 분리 | [기준 실패 대조](step002-baseline-failure.md) |
| 회사별 추적 저장·동시성·회귀·모듈 경계 | PostgreSQL 17.11 환경 57 passed, skip 0 | [STEP003 로그](step003-tests.log) |
| 최종 회사 API·3사 분리·동일 상태 재결정·손상 replay·앱 역할 UPDATE/reset·자동 enqueue | SQLite/PG 27 passed, skip 0 | [최종 인수 로그](step004-tests.log) |
| 프런트 오류 코드 등록 | Node 22 Docker에서 TypeScript/Vite production build 통과; UI 레이아웃 변경 없음 | [빌드 로그](step002-frontend-build.log) |
| 문서·근거 | doctor 6 features, diff 검사, source-baseline hash 불일치 0 | [최종 변경 소스 hash](final-source-hashes.json) |

검사 수는 실행 묶음별이며 서로 중복된다. 실패 로그와 수정 후 차이 검사를 보존했고, 이미 통과한 변경 없는 경로는 소스 동일성을 대조하여 재사용했다. 독립 최종 판정은 [review.md](review.md)에 기록한다.

## 한계와 후속

- `test_the_flag_opens_preparation_for_sw_business_without_a_grade`는 변경 전 main에서도 동일 실패했다. 이번 회사 기능의 성공으로 기존 자동 준비 전체가 검증됐다고 주장하지 않는다.
- 회사 메뉴·검토 화면은 DEMO-04, 회사 지식 원본/그래프/CLI는 DEMO-02, 회사별 실제 분석은 DEMO-03 이후다.
- ID 직접 보고서/근거/재시도 경로의 전수 회사 격리 감사는 main 병합 전 별도 게이트다. 이번 기능을 운영에 배포하지 않는다.
- 실제 Luna 대표 1건은 DEMO-03 STEP-007, 핏 18건·최소 보고서 3건/목표 9건 및 담당자 인수는 DEMO-05에 남는다. 기존 LiteLLM 개요 참조 실행을 Luna 품질 근거로 승격하지 않는다.
