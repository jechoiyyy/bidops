# DEMO-00 로컬 재계획 독립 리뷰

- 판정일: 2026-10-09
- 기준: `d75499594977555b1fecd44870e6c14a22796823` 이후 현재 worktree
- 범위: DEMO-00 로컬 준비 재계획, DEMO-01~05 계약·큐 연결, 기존 LiteLLM/선택 첨부 제품 변경과 `docs/validation-runs/20261009-litellm-reference/` 증거의 연결
- 판정: **PASS — 차단 0**

## 확인 결과

1. DEMO-00의 기존 Luna v4 구현과 운영 1489 미실행 이력이 삭제되거나 실제 품질 완료로 바뀌지 않았다. `status.json` history에는 기존 `운영 적용` blocked와 `실제 1489 1건과 판정` pending 및 실제 호출 없음이 남아 있고, 현재 STEP-003/004는 각각 로컬 준비 증거 판정과 후속 게이트 이관으로 명시돼 있다.
2. 실제 Luna 품질 게이트가 후속 기능에 남아 있다. DEMO-03 STEP-007/T9는 대표 1건의 별도 preview·건별 승인·Luna `codex-exec`·3단계 completed·결정적 검증·원문 근거 확인을 요구한다. DEMO-05 T4/T5는 LiteLLM 핏 18건과 대표 1건×3사 최소 인수, Luna 보고서 9건 및 9건 모두의 사람 인수를 구분한다.
3. notice 179 결과의 범위가 증거와 일치한다. 승인된 물리 4쪽 779자, 2 calls, 8 claims, 인용·offset 검증 통과, quantity 경고 4종, `quality_status=unmeasured_reference`, 두 viewport 오류 0이며 Luna 심층 또는 전체 80쪽 품질 근거로 승격하지 않았다. 물리 5쪽 text/display 불일치와 전체 시각 검증 미수행도 남아 있다.
4. 현재 제품과 기존 검사 증거의 연결이 유지된다. 리더가 `final-source-hashes.json`의 제품 파일 8개와 현재 source의 일치를 확인했고, 모델 관련 231건과 문서 관련 155건은 같은 source에 대한 기존 증거로만 기록했다. 이번 문서 재계획에서 새로 실행한 검사로 표기하지 않았다. DB schema·REST shape·frontend 변경이 없다는 N/A 범위도 실제 diff와 맞는다.
5. LiteLLM 목적 분리가 현재 코드와 맞는다. 회사 핏은 기존 `ModelClient.for_purpose("overview")`에 맞춰 `BIDOPS_VLLM_OVERVIEW_API_DIALECT=litellm`과 `local-agent-main`을 사용하고, Luna 심층은 별도 `codex-exec` preview/approval 경계를 유지한다. 전역 fallback이나 key 공유를 추가하지 않았다.
6. 실행 범위와 브랜치 경계가 일치한다. 활성 run은 DEMO-00 하나이고 target은 main, commit/merge는 manual이다. DEMO-01~05는 DEMO-00 통합 뒤 별도 데모 브랜치와 `bidops-local`에서 진행하며 main·운영 반영은 별도다. 기존 ID 직접 조회·수정·재시도 API의 회사 격리 전수 점검은 데모 기능을 main에 병합하기 전 필수 조건으로 유지됐다.
7. intent/spec/plan/constraints/queue가 같은 순서를 가리킨다. DEMO-00 로컬 준비 뒤 DEMO-01→02→03→04→05이며, DEMO-04는 DEMO-03의 실제 Luna 대표 게이트 뒤에 있다. 상태는 DEMO-00 4/4 `validating`, 문서 proof만 이 리뷰를 기다리고 있고 후속 기능은 제품 미구현 상태를 유지한다. 리더가 보고한 doctor·링크 검사·source-baseline hash·diff check도 통과했다.

## 주의

- DEMO-00의 4/4 완료는 개정된 기능의 로컬 준비와 게이트 이관 완료를 뜻한다. 운영 1489 실행, 운영 배포·정책 활성화, Luna 완성 보고서 품질 통과로 인용하면 안 된다.
- PDF 물리 5쪽 문제를 해결하기 전에는 notice 179의 전체 문서 품질을 주장하거나 해당 쪽을 모델 payload에 포함하면 안 된다.
- 이 PASS는 새 모델 전송·운영 변경·DEMO-01~05의 main 병합 승인이 아니다. 실제 Luna 전송은 DEMO-03/05의 각 단계 직전 건별 사람 승인, 후속 main 병합은 기존 ID 직접 API 격리 점검이 필요하다.

제품 검사는 재실행하지 않았다. 변경 없는 source hash에 연결된 기존 231+155 결과와 실제 실행 증거를 읽어 재사용했고, 문서·상태·큐 차이만 검토했다.
