# 시스템 구성 (Lean v1)

## 목표 토폴로지

```text
공개 수집/기존 SQLite backup --(one-time reconciliation)--> PostgreSQL 17 bidops schema
기관 문서 --> FastAPI MinIO quarantine + ClamAV --> MinIO source/structure
                         | hash-bound atomic scratch protocol
                         v
              document-worker (network none, replicas 2)
고정 bundle/profile/policy snapshot ---------------------> analysis worker (concurrency 1)
                                                           |  Ollama/Qwen local only
                                                           v
                                                   3 stages + deterministic validation
                                                           |
                                                   immutable report/evidence/audit
                                                           |
React SPA <---------------- FastAPI ----------------------+
```

PostgreSQL 17.11과 MinIO가 live canonical DB/object store이고 SQLite는 migration input이다. FastAPI는 목적별 MinIO source/structure/quarantine credential과 DB/ClamAV restricted networks를 사용하며, bounded scratch만 임시 staging으로 남긴다. document-worker는 검증된 원문 hash와 clean scan envelope를 가진 credential-free scratch request만 network none에서 신뢰한다. analysis worker는 immutable structure를 읽고 application-encrypted model response를 model-response bucket에 쓴다. worker가 model, DB, object locator를 prompt에 직접 노출하지 않으며 report/evidence/validation과 finish는 동일한 fenced transition에서 확정된다.

## 구성요소와 경계

| 구성요소 | 역할 | 경계 |
|---|---|---|
| legacy 13 tables | 기존 수집·판정·리뷰 projection | SQLite backup에서 한 번 import하고 PostgreSQL에 보존 |
| Lean 25 tables | bundle, structures, attempts, claims, evidence, report, validation, audit | 총 38 application table, actor table 없음 |
| FastAPI document producer | MinIO quarantine/source 저장, 동일 원문의 ClamAV 검사, hash-bound scratch request/result | DB/MinIO/ClamAV restricted networks; purpose credential별 접근 |
| document-worker | HWP/HWPX/PDF 안전 검사·구조화 | credential-free atomic scratch protocol, Node/PDF/OCR 로컬 도구, network none, replicas 2 |
| analysis worker | 요구사항·위험·경제성·종합 3단계 | fixed snapshots와 Qwen/Ollama endpoint만 사용, concurrency 1 |
| FastAPI | 정확히 승인된 새 API #1-14와 기존 조회 API | stable error shape, claimed-name boundary, security headers, SPA fallback after API |
| React frontend | notice detail entry, deep-review route, report/evidence/decision flow | REST API only, keyboard and narrow-viewport fixture |

OpenAI, Langfuse, phase2 기능은 없다. 기존 SQLite-live 문구는 폐기한다.

## 순서와 transaction fence

문서 bundle confirmation이 fixed input을 만들고, attempt는 3 stages를 순서대로 저장한다. 분석과 report는 live attachment/document projection을 다시 읽지 않는다. 세 번째 stage persist 뒤 `ReportService.materialize_machine_report(session, claim)`가 immutable report, validation, evidence joins, audit를 만들고, 바로 `_finish_claim`이 같은 lease를 재검증한 뒤 commit한다. materializer 오류는 rollback 후 safe worker failure로만 기록한다.

## 배포

이 worktree/production template은 `docker-compose.t7.yml`이다. 항상 `COMPOSE_PROJECT_NAME=bidops-deep-review-t7`와 함께 실행하고 main worktree의 compose/data/volume을 공유하지 않는다. Web은 database/storage/scanning과 scratch volume에 연결되고 source/structure/quarantine 목적별 MinIO credential만 받는다. analysis worker는 database/analysis network에서 structure-read와 model-response credential만 받는다. document-worker는 network none의 두 replica로 credential-free scratch만 소비한다. PostgreSQL owner/migrate/app/worker/ro_backup, MinIO purpose-specific credentials/policies, ClamAV, Ollama/Qwen local configuration은 외부 secrets로 주입되며 MinIO 미설정 production은 fail fast한다.
