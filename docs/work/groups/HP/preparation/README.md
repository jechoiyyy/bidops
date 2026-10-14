# HP-02~06 검토 묶음 — 준비만 완료, 결정·구현 전

2026-10-15. HP-00·01 loop은 `demo/local-20261009`에 통합·완료 기록 커밋 `95d361d`까지 끝났다. 관련 backend333·browser31 통과, build·독립 리뷰 PASS/차단0. 상세는 [최종 검증](../../../_runs/hp0001-20261014/hp0001-final-validation.md)과 [격리 적용](../../../_runs/hp0001-20261014/hp01-deployment.md). MinIO fixture1 skip, 실제 모델 분석 실패, 카드 쪽110미확인, 기본 대상3건 구조 부재 한계는 유지한다.

아래 다섯 기능은 계속 **drafting**이며 큐에 구현 승인·완료로 올리지 않았다. 제품·회사 DB·정책·모델 호출·Neo4j 실험 변경 없음. 원문 근거·사람 자료는 Git 밖 제한 디렉터리에 두고 [artifact-manifest.json](artifact-manifest.json)에 위치·hash·규모만 기록했다.

| 기능 | 준비 완료 | 아직 하지 않은 일 |
|---|---|---|
| [HP-02](../features/HP-02-homepage-ontology-company/preparation.md) | 실제198카드 근거, 28concept/분류/alias 후보, 가상회사 초안, 기존 매퍼 연결 coverage 도구 | D1/D2 확정, 정식 fixture·등록·활성화 |
| [HP-03](../features/HP-03-two-tier-analysis/preparation.md) | 기존 함수 연결, frozen input·stage 출력·저장 초안, 경계 사례·구현 순서 | 제품 파이프라인/migration/모델 검증 |
| [HP-04](../features/HP-04-practitioner-verdict/preparation.md) | 다섯 블록·상태표·REST envelope·화면/API 검사 계획 | 실제 화면/API·두 폭 검증 |
| [HP-05](../features/HP-05-neo4j-experiment/preparation.md) | 5개 Python/Cypher 질의쌍·실험 절차·경로 scorer·사람 평가 빈 양식 | Neo4j 실행/동등성·recall 측정·채택 |
| [HP-06](../features/HP-06-gold-acceptance/preparation.md) | 모델 답 없는5문서198카드 작성 자료·gold 검사·채점 도구 | 나머지 표본·사람 gold·모델10건·최종 인수 |

실제 후보 매핑은 **129/198(65.2%)**다. 넓은 관련어 묶음까지 포함한 출현 비율이므로 정확도나 목표 달성으로 해석하지 않는다. 미매핑69카드도 coverage에 남겼다. 28개 후보의 related alias는 사용자 검토 뒤 분리할 수 있다.

## 돌아온 뒤 권장 검토 순서

| 순서/결정 | 근거·추천안 | 대안·영향 | 현재 결정 |
|---|---|---|---|
| 1 D2 온톨로지 | 실제 근거부터 보고 4kind·관계 유지. 관련어/동의어 분리 후 concept·alias 확정 | kind/관계 확장은 validator·DB·검색 범위 변경. 접두는 기존 DEMO 유지도 가능 | 미확정 |
| 2 D1 회사 | 가상 온웹서비스 중간규모, 미보유2·상주상한1·unknown2를 구분 | 더 작은/큰 회사는 결과 분포를 바꿈. 실제 공고에 맞춘 사후 숫자 조정 금지 | 미확정 |
| 3 D4/D5 HP03 | 문서+ordinal 기반 unit ID, 8장/12,000자 시작안, 40분 목표와 hard timeout 구분, 카드외 명시적 selector | 시간상한2400초 대안; 큰 단위 분할은 근거 연결 추가 설계 필요 | 미확정 |
| 4 D3/D6 HP04 | DEMO row 보존+HP 목록 필터, 회사 scoped current/attempt 조회, conflicts는 주의 안 | 모든 회사 탭 노출/404 빈결과 대안은 안내·API 소비자 영향 | 미확정 |
| 5 D7 HP06 | 10문서 선정·회사 동결 후 모델 결과 보기 전에 사람 gold 작성. top5만의 precision 한계 먼저 해소 | 전체정답집합 또는 불일치 사람 adjudication; 기준은 측정 전 결정 | 미확정 |
| 6 D8 HP05 | 기대경로·분모·우위 정의부터 확정. 현행 recall와 보조질의 분리 | 질의 표현력만으로 채택 후보 가능하나 주관 비중 증가. 운영 비용/AGE 제외는 이미 결정 | 미확정 |

원문 쪽 보완은 HP01 findings의 별도 문제다. 110건을 임의 추정하지 않고 후속에서도 unavailable로 처리한다. 최종 인수는 사람이 작성하며 준비 문서나 도구 통과로 대신하지 않는다.

## 오프라인 도구 실행

저장소 루트에서 backend 의존성이 설치된 Python으로 실행한다. 이번 검증 Python은 `/tmp/bidops-hp0001-20261014-venv/bin/python`이었다. 다음 예시의 출력은 반드시 **새 경로**를 지정한다. 현재 v2 파일을 덮어쓰지 않는다.

```sh
python docs/work/groups/HP/preparation/hp_prepare.py export /path/to/structure-pairs --out /outside/git/cards.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py coverage /outside/git/cards.NEW.json docs/work/groups/HP/preparation/ontology.candidates.draft.json --out /outside/git/coverage.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py blank-gold /outside/git/cards.NEW.json --out /outside/git/human-worksheet.blank.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py gold-check /outside/git/human-written-gold.json --out /outside/git/gold-check.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py score /outside/git/human-written-gold.json /outside/git/predictions.json --out /outside/git/score.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py graph-score /outside/git/expected-paths.json /outside/git/actual-paths.json --out /outside/git/graph-score.NEW.json
```

export 입력은 `sources.json`의 name/file/source_sha256 및 `<name>.structure.json`, `<name>.para_page_map.json`, 원본 파일이다. 원본 hash·structure source hash를 검사하고 입력 디렉터리 이탈·symlink를 거부한다. 제품의 build_manifest_payload/resolve_card_pages만 호출하며 DB·네트워크·모델은 쓰지 않는다. 출력0600·exclusive create, 원문/오류값을 stdout에 내보내지 않는다. 원문 자료 디렉터리는0700이다.

## 검증 범위

- `python -m unittest discover -s docs/work/groups/HP/preparation -p test_hp_prepare.py -v`: 초기12개 통과. 이후 입력 경로 격리만 추가하여 `-k input_path` 1개 통과. 변경되지 않은12개 결과 재사용.
- `python -m unittest discover -s docs/work/groups/HP/preparation -p test_graph_queries.py -v`: 합성 그래프1개 통과. 준비 도구 총14검사, 사람 정답/실제 그래프 실험 결과가 아니다.
- 실제 source pack/coverage/blind pack 생성 성공. 경로 검사 추가 뒤 새 v2로 생성하고 cards v1/v2 documents 동일 확인. v1도 불변 보존. v2는 현재 준비 도구 hash에 고정.
- blank 실제 작성자료의 gold-check 거부, 출력 덮어쓰기 거부, 원문 hash·198카드 ID 고유성·blank 정답 유지·근거 block 인용 일치 검사 결과는 [validation.json](validation.json).
- Cypher 실행, Neo4j/PostgreSQL 실험 동등성, 사람 평가, HP03/04 제품, HP06 실제 품질은 미검증이다. 이번 후속 준비는 제품 변경이 없어 앱 재빌드·배포·전체 테스트를 반복하지 않았다.
