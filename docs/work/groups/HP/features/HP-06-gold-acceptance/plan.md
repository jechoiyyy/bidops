# HP-06 — plan

- 기능 ID: `HP-06-gold-acceptance`
- 근거: intent.md, spec.md. 작성일2026-10-15. 구현 시작 전 문서다.

## 변경 파일

| 경로 | 구분 | 내용 |
|---|---|---|
| `scripts/hp-export-evaluation.py` | 신규 | spec 요구사항 구현·검증 |
| `docs/work/groups/HP/preparation/hp_prepare.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `docs/work/groups/HP/preparation/test_hp_prepare.py` | 수정/재사용 | spec 요구사항 구현·검증 |
| `tests/test_hp_export_evaluation.py` | 신규 | spec 요구사항 구현·검증 |

## 작업 순서

1. STEP-001 독립 작성 자료·검증기 정합화 [complex]
   - 목표: 노출이력·source binding·빈정답 유지.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T1,T2; 결과/명령/종료코드는 실행 run 폴더에 저장.

2. STEP-002 attempt export와 채점·인수 기록 [complex]
   - 목표: 엄격한 binding·partial·중대오류null 보존.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T3,T4,T5; 결과/명령/종료코드는 실행 run 폴더에 저장.

3. STEP-003 독립 사람10건·실제 평가 인수 [complex]
   - 목표: 사람 입력과 승인된 실제 실행 후 결과 판단.
   - 작업 대상: 위 파일 표의 해당 계약·검사와 spec.
   - 검증: T6; 결과/명령/종료코드는 실행 run 폴더에 저장.

## 위임

모든 단계 complex(gpt-5.6-sol/high): 불변 입력·상태·근거·사람 판단 경계를 검사한다. 구현자는 단계 하나만, 리더가 관련 검사를 실행하며 독립 리뷰는 같은 소스·결과를 읽는다. 테스트 ID는 spec 표이며 위 단계가 전부 배정한다.

## 증명

- docs: `python3 scripts/feature_status.py doctor _`, `check-plan HP-06-gold-acceptance`와 intent 유즈케이스별 실제 증거 대조.
- tests: `python -m pytest tests/test_hp_export_evaluation.py docs/work/groups/HP/preparation/test_hp_prepare.py -q`. 새 검사 파일은 loop에서 구현하며 현재 존재/통과한다고 주장하지 않는다.
- postgres: N/A — 제품 DB schema/응답 변경 없음. 읽기 전용 attempt export는 T3에 포함.
- frontend: N/A — 화면 코드 변경 없음.
- api_guard: N/A — 제품 API 변경 없음. HP06 export의 소유권/읽기전용 검사는 tests에 포함.
- real_data_run: HP06 T6 실제10건·독립gold·사람판정. 미완료 시 validating, 자동완료 금지.

## 위험과 종료 경계

| 위험 | 징후 | 대응 |
|---|---|---|
| 확정 설정을 실제 기능/품질로 오인 | 준비파일만 있고 실제 증거 없음 | 필수검증을 pending 유지 |
| 원문/회사/정책 기준 혼합 | hash·ID·버전 불일치 | fail closed, 새 버전·새 attempt |
| 미확인을 false/충족으로 변경 | 조건 일부만 맞는데 met | spec 경계 검사, unknown 보존 |
| 사용자 참여 대기 | 사람 경로/gold/인수 없음 | 독립 가능한 단계만 진행, 답 대행 금지 |

실행 전에 필요한 검사 범위를 한 번 정하고 통과 후 동일검사를 반복하지 않는다. 실제환경 적용은 사용자 승인 범위 내 demo/local-20261009·bidops-local만. 전체스위트/전수재빌드는 공통 회귀 근거 없으면 실행하지 않는다. 수동 commit/merge 정책을 유지하며 origin push·브랜치 삭제 없음.

## 결과

아직 구현·실제 기능 검증하지 않았다. loop가 실행 결과를 이 절에 기록한다.
