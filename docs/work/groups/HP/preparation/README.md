# HP-02~06 loop 전 준비

현재 기준은 회사 v2·온톨로지 v1·선정10사례다. 설정 승인은 완료됐으며 **제품 구현·실제 비교·독립 정답·최종 인수는 아직 완료되지 않았다.** 기능별 최신 intent/spec/plan이 실행 계약이고 preparation 문서는 의사결정 경과다.

## 확정 입력과 작성 자료

- [회사 v2 승인 원본](company.experience.approved.v2.json): 14기존사실·세 가상 실적 담당 범위·표준 절차. 현재 인력/자격/SLA/계약 수용은 따로 판단한다.
- [평가 basis v2](company.evaluation-basis.v2.json)·[검토 입력 동결](review-inputs.frozen.v2.json): company SHA는 basis 파일 bytes, ontology는 canonical SHA. 제품 등록 projection은 HP02 구현 대상이다.
- [승인 온톨로지](ontology.approved.v1.json): 51concept·4kind·11관계. [선정 문서](evaluation-documents.selected.v1.json): 10사업·11원문·541카드, inherited312/unavailable229. 직접 매핑 쪽은0이며 정확도 지표가 아니다.
- [인수 후보 기준](acceptance-criteria.approved.v1.json)·[그래프 채택 후보 기준](graph-adoption-criteria.approved.v1.json): 기준 승인과 실제 인수·채택은 별개다.
- 사람이 읽는 자료: `/Users/temp/orca/bidops/.sdlc/local-runtime/hp-evaluation-20261015/index.company-v2.html`; 빈 작성 양식 `assisted-review.worksheet.blank.v2.json`. 모델 답 없이 원문·회사 사실을 제공한다. 폴리텍 초안 노출 이력 때문에 이 작성 흐름은 독립 blind gold가 아니다.
- 원문·파생 자료 위치와 해시: [artifact-manifest.json](artifact-manifest.json). v1/draft/이전 양식은 불변 보존하며 v2로 자동 이관하지 않는다.

## 구현 준비 범위

| 기능 | 실행 명세·계획 | loop에서 해야 할 일 |
|---|---|---|
| HP02 | [spec](../features/HP-02-homepage-ontology-company/spec.md) · [plan](../features/HP-02-homepage-ontology-company/plan.md) | v2 projection·binding·격리 등록/조회·coverage |
| HP03 | [spec](../features/HP-03-two-tier-analysis/spec.md) · [plan](../features/HP-03-two-tier-analysis/plan.md) | 추출/대조/역할/종합·저장·worker·대표 실제검증 |
| HP04 | [spec](../features/HP-04-practitioner-verdict/spec.md) · [plan](../features/HP-04-practitioner-verdict/plan.md) | 읽기 REST·다섯블록 화면·두 폭/실제조회 검증 |
| HP05 | [spec](../features/HP-05-neo4j-experiment/spec.md) · [plan](../features/HP-05-neo4j-experiment/plan.md) | 엔진 adapter·동등성·사람 기대경로 후 실제비교 |
| HP06 | [spec](../features/HP-06-gold-acceptance/spec.md) · [plan](../features/HP-06-gold-acceptance/plan.md) | export/채점 연결·독립정답·실제10건·사람 인수 |

18개 STEP을 동기화했고 독립 문서 리뷰(수정 차이1회 재검토 포함)는 PASS/차단0이다. HP02~06은 review 상태로 실행 큐에 등록했다. 다음 착수 기능은 HP02이며 나머지는 명시된 선행 기능을 기다린다. 구현 run은 시작하지 않았다. 단계/큐의 정본은 status.json과 queue.json, 변경은 feature_status.py만 사용한다.

## 남은 사람 참여와 권장 순서

1. HP02~04 구현 전 추가 제품 설정 결정은 없다. 검토 가능한 문서를 수동 커밋한 뒤 loop를 시작한다.
2. 독립 평가 전에 **모델 답을 보지 않은 평가자**를 우선 권장한다. 같은10건을 재사용할 수 있다. 불가능하면 새 미노출 holdout을 선정한다. 현재 모델 보조 기록을 독립 정답으로 바꾸지 않는다.
3. HP05 실제 비교 전에 원본 그래프의 기대·필수 경로를 사람이 동결한다. 결과 뒤 질의 작성/수정 용이성과 설명을 평가하고 도입을 결정한다.
4. HP06 사람 정답·불일치·중대 오류를 검토한 뒤 최종 인수한다. 미확정 사업별 비용/책임/기한 등은 unknown으로 보존하며 해당 공고를 판단할 때만 묻는다.

## 오프라인 도구 실행

저장소 루트에서 backend 의존성이 설치된 Python으로 실행한다. 이번 검증 Python은 `/tmp/bidops-hp0001-20261014-venv/bin/python`이었다. 다음 예시의 출력은 반드시 **새 경로**를 지정한다. 현재 v2 파일을 덮어쓰지 않는다.

```sh
python docs/work/groups/HP/preparation/hp_prepare.py export /path/to/structure-pairs --out /outside/git/cards.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py coverage /outside/git/cards.NEW.json docs/work/groups/HP/preparation/ontology.approved.v1.json --out /outside/git/coverage.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py blank-gold /outside/git/cards.NEW.json --out /outside/git/human-worksheet.blank.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py gold-check /outside/git/human-written-gold.json --out /outside/git/gold-check.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py score /outside/git/human-written-gold.json /outside/git/predictions.json --out /outside/git/score.NEW.json
python docs/work/groups/HP/preparation/hp_prepare.py graph-score /outside/git/expected-paths.json /outside/git/actual-paths.json --out /outside/git/graph-score.NEW.json
```

export 입력은 `sources.json`의 name/file/source_sha256 및 `<name>.structure.json`, `<name>.para_page_map.json`, 원본 파일이다. 원본 hash·structure source hash를 검사하고 입력 디렉터리 이탈·symlink를 거부한다. 제품의 build_manifest_payload/resolve_card_pages만 호출하며 DB·네트워크·모델은 쓰지 않는다. 출력0600·exclusive create, 원문/오류값을 stdout에 내보내지 않는다. 원문 자료 디렉터리는0700이다.

## 검증과 한계

HP00·01은 완료 커밋 `95d361d`와 [최종 검증](../../../_runs/hp0001-20261014/hp0001-final-validation.md)이 있다: 관련 backend333·browser31·build·독립리뷰 통과. MinIO fixture1 skip, 실제 모델 분석 실패, 최초198카드 쪽110미확인과 기본 backfill3건 구조 부재는 유지한다.

이전 준비 도구는23검사, 보조 그래프 질의는 합성1검사가 통과했다. 이를 실제 엔진 비교/모델 품질 근거로 쓰지 않는다. 이번 문서 작업에서는 doctor·5개 check-plan·JSON 파싱·v2 동결 파일 해시·10건 정답 빈칸 보존과 제품 소스 동일성을 검사했다. 제품 코드 변경이 없어 앱 재빌드·배포·모델 실행을 반복하지 않았다.

최종 독립 리뷰·원본 증거 재사용 판단은 [preloop-review.md](preloop-review.md)에 기록했다. loop 이전 기록 검증과 제품 기능 검증은 구분한다.
