# ADR-0074 분석 엔진을 BidOps 개발 기준선에 통합

2026-11-17 사용자 통합 요청에 따른 구현 결정. 품질 인수·운영 활성화 결정은 아니다.

## 결정

BidOps가 수집·공고 identity·회사 근거·사람 결정·PostgreSQL·MinIO·공용 작업 슬롯을 계속 소유한다. bid-deep-agent의 분석 로직은 `packages/bid-deep-engine`으로 가져와 버전 adapter로 연결한다. 별도 SQLite task store·CLI/A2A/chat 서버와 원본 회사 파일 정본은 이식하지 않는다. 제품 소비자는 기존 사전규격 관리 화면이다.

원본의 Claude direct/gateway/CLI·fallback 및 Langfuse 전송은 현재 RL의 Luna/high·사전 정책 승인·건별 감사와 다르다. 이번 adapter는 mock_reference 실행을 명시적으로 제공하며 live 선택을 fail closed한다. 원본 transport를 감춘 채 기존 승인으로 호출하지 않는다. 제품 모델 변경이나 새 승인 정책 발행은 이 결정에 포함하지 않는다.

새 분석은 공고·묶음·회사 입력과 엔진 revision을 고정하고 별도 실행/결과로 남긴다. 기존 분석·사람 리뷰·최종 결정을 덮지 않는다. 원본의 abstain/null/unknown, 실패·부분 결과를 보존한다. 실제 분석 품질은 기존 reject와 미측정 상태를 유지한다.

Compose는 서비스 선택과 네트워크 권한을 분리한다. 개발 기본 project는 운영 `bidops`, 기존 데모 `bidops-local`과 다르며 운영 volume 이름을 바꾸지 않는다. Make/운영 스크립트는 공통 selector를 사용한다. 초기화·migration은 별도 명령이다. Mac 문서 worker는 native arm64 제약을 유지한다.

## 근거와 대안

두 저장소를 서버째 결합하면 SQLite/DB 큐·회사 정본·전송 승인이 이중화된다. 원본을 subprocess CLI로 무조건 호출하면 source transport와 로그·비용·observability 전송이 함께 따라온다. 따라서 분석 코어만 분리하고 저장/실행 책임은 제품 adapter에 둔다.

기존 모든 품질 문제를 먼저 해결하는 방법은 사용자가 지정한 개발 기준선 우선 목표와 다르다. 요구사항 누락·회사 정책의 차단 의미와 품질 재측정은 후속으로 유지한다.

## 검증과 한계

[RL-09 계획](../../work/groups/RL/features/RL-09-engine-integration/plan.md)의 입력·기대 결과·증거를 따른다. mock 결과는 연결만 검증하며 Luna 품질·모델 전송·운영 활성화를 입증하지 않는다. 운영 web의 기존 restarting/unhealthy 상태는 복구 범위에 포함하지 않는다.

## 2026-11-20 후속 결정

사용자가 실제 사전규격 분석과 상세 검토를 목표로 확인했다. `bid-deep-agent` 코어는 확인된 BidOps 회사 사실과 승인된 루트랩 위키 발췌를 입력으로 받는다. 새로운 Luna 경로는 공고별 미리보기·승인과 건별 감사를 적용한다. 장문 처리와 결정적 차단·근거 검증 뒤 기존 RL 카드와 같은 입력으로 평가하고, 사람 인수 결과로 상세의 기본 표시를 확정한다. 실행·전송·운영 승인 경계는 [후속 계획](../../work/groups/RL/features/RL-11-live-prespec-engine/plan.md)을 따른다.

## 2026-11-22 후속 결정

사용자가 "원본 회사 파일 정본은 이식하지 않는다"는 처음 결정을 바꿨다. 분석 엔진은 원본 `bid-deep-agent`가 준비한 루트랩 회사 자료 전체(`rootlab.yaml`·실적·출처 sidecar)와 회사 위키(`company/knowledge/`, 원본 revision `7ad9283`)를 그대로 받는다. 공고마다 위키에서 유형을 고르고 관련 페이지를 발췌해 대조·종합 단계에 넣는 원본 동작도 그대로 쓴다. 2026-11-20 결정의 "확인된 BidOps 회사 사실과 승인된 위키 발췌만"이라는 입력 범위와 [RL-11 매핑안](../../work/groups/RL/features/RL-11-live-prespec-engine/company-wiki-mapping.md)의 문장 단위 승인·전송 제외 범위는 이 결정과 어긋나므로 RL-11을 진행할 때 다시 맞춘다.

- 입력 계약은 `bidops.engine-input.v2`(`company_bundle`)다. v1(BidOps 회사 사실의 보수적 사상)은 묶음 폴더를 설정하지 않은 환경에서 그대로 쓴다. 계약은 [engine-runs](../../contracts/engine-runs.md).
- 회사 자료는 저장소 밖 로컬 사본 `wiki/`에 두고 Git·이미지에 넣지 않는다. mock 스택만 읽기 전용으로 붙인다. 운영 스택 연결과 live 전송 승인은 별개이며 아직 없다.
- 이 제품은 데모 버전이다. 원본 자료의 데모 임의값(공개 검색으로 찾지 못해 임의로 넣은 값)은 원본과 같이 판정에 그대로 쓴다(사용자 결정 2026-11-22). 프로젝트 소개에는 그 사실을 한 줄로 밝힌다.

## 2026-11-23 후속 결정: 회사 위키의 정본과 정리 계층

- **정본 위치:** 회사 위키와 프로필의 정본은 이 작업 폴더의 `wiki/`다(사용자 결정 2026-11-23). 원본 저장소(`bid-deep-agent`)의 `company/`는 버전 이력을 남기는 사본이며 BidOps → 원본 방향으로만 복사한다. `wiki/`는 계속 Git과 이미지 밖에 둔다. 그래서 정본 자체에는 버전 이력이 없고, 바꾸기 전 `backups/`에 사본을 남기고 바꾼 뒤 원본 저장소에 복사·커밋한다.
- **정리 계층:** 위키에 업무별 근거 지도(`work-units.json` 곁 파일과 `capabilities/work-*.md`)를 둔다. 수주 사업의 요구사항을 업무 단위로 분류해 넣고(ingest), 분석에서 확인된 사실을 사람 승인 뒤 되돌려 쓰며, 내용 점검을 한다. 명령은 엔진 패키지의 `bid_deep_engine.wiki_tools`이고 모델 호출은 그 안에 없다.
- **회사 규칙:** 참가자격 판단 기준(`rules/eligibility.md`), 하드웨어 범위(`rules/no-bid.md`), 상주·이동 조건(`rules/region.md`: 장소 미지정은 상주 공고가 아님, "원칙·협의 가능"은 확인 항목)을 위키에 글로 둔다.
- **읽기 방식(평가 도구 기준):** 에이전트가 실적을 전부 읽고 인용을 검증하는 방식을 기본으로 한다. 위키 탐색 방식과 같은 입력으로 20회 A/B를 돌린 결과 판정 품질은 같고(대조 일치 평균 89.8% 대 88.4%) 전부 읽기가 시간 12%·캐시 적중 입력 34%·출력 10%를 덜 썼다. 넣은 사업이 약 46건이 되거나 실적 페이지가 약 50만 자를 넘으면 같은 A/B를 다시 돌려 전환 여부를 정한다. 제품 경로에는 어느 방식도 연결돼 있지 않다.
- 근거와 측정은 업무별 근거 지도와 위키 탐색(`docs/validation-runs/20261123-llm-wiki-evidence-map/README.md`, git 이력)에 있다. 시험 기록이며 품질 합격 근거가 아니다. 엔진 스위치와 제품 경로(mock_reference)는 그대로다.
