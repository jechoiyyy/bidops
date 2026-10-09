# 2026-10-09 로컬 개발 준비 증거 대조

사용자 요청: “지금 상황에 맞게 수정해서 진행해봐”. 현재 로컬 환경·실제 수집 공고·LiteLLM을 개발 기준으로 재계획하며, 개요 검증을 Luna 심층검토 품질로 대체하지 않는다.

## 확인한 사실

- 현재 main과 배치 HEAD는 d75499594977555b1fecd44870e6c14a22796823. 기존 Luna v4 구현은 main에 반영됐으나 실제 Luna 보고서 인수는 미완료다.
- 수집 기준은 2026-10-06~08 KST 3일, 총3277건(입찰2187·사전규격1090). 로컬 적재348건 중 사전규격182건. 적재 경고300건은 해소/성공으로 변경하지 않는다.
- `docs/validation-runs/20261009-litellm-reference/`의 result·test-result·review·document-delta-review·target179 결과와 승인·런타임·브라우저 증거를 대조했다.
- final-source-hashes.json에 기록한8개 제품 파일의 현재 SHA256이 모두 일치한다. 제품 변경 없이 문서와 작업 상태만 갱신하므로 기존 관련 검사231건과 문서/첨부155건의 증거를 재사용한다. 이를 이번 재계획에서 새로 실행한 검사로 표기하지 않는다. 155건은 초기154통과와 이미지 checksum 포장 수정 후 해당1건 통과의 조합이다.
- 실제 개요 run ff144ffa-7495-4672-99ae-7a2e27a67c1d는 승인된 notice179 물리PDF4쪽779자만 사용,2calls,completed.8개 문장의 인용과 offset이 승인 원문에 일치한다. quantity 경고4종과 unmeasured_reference를 보존한다.
- 1280x800·1440x900 실서버 화면과 PDF4쪽 근거 링크 확인, 브라우저/HTTP 오류0. WorkJob1개 completed, 자동 overview/deep-review false.
- native ARM 문서 worker는 기존 pinned rhwp commit·DATA512MiB·network none·자격증명 없는 격리를 유지한다.80쪽 snapshot 준비 성공은80쪽 시각 검증 성공이 아니다.5쪽 표시와 text-layer 불일치는 미해결이며 해당쪽은 모델 전송에서 제외됐다.

## 유지하는 미완료 검증

Luna v4 실제 심층 보고서 검증과 다회사 최종 인수는 후속 DEMO-03/05 게이트로 남긴다. 운영1489 과거 실패 비교와 운영 적용은 완료 처리하지 않는다. 이번 문서 승인은 새 모델 payload 전송, 운영 배포, 정책 활성화, 수집 재실행 승인이 아니다.

## 실행 경계

다음 기능은 DEMO-01 회사 문맥·격리·독립 추적이다. 신규 회사 API/DB/화면은 아직 구현되지 않았다. commit/merge 수동 정책과 지정 모델 독립 리뷰를 유지한다.

## 커밋·통합 승인 근거

앞선 사용자 명시 요청 “변경을 커밋하고 main에 반영해줘”와 현재 같은 작업의 “지금 상황에 맞게 수정해서 진행해봐”를 지속 승인으로 적용한다. 자동 커밋 설정을 바꾸지 않고 리더가 검토된 DEMO-00 로컬 연결·준비·재계획만 수동 커밋·main 통합한다. DEMO-01~05는 별도 데모 기준 브랜치에서 구현·통합하고 main/운영에는 반영하지 않는다. 이 판단은 추가 모델 전송·운영 변경·push·브랜치 삭제를 승인하지 않는다.

## 재계획 정적 검증 결과

리더 실행: `python3 scripts/feature_status.py doctor _` → 6 features/schema2/tool0.6.0 정상, `git diff --check` exit0. 변경한 docs/work Markdown 상대 링크 누락0, source-baseline.json 모든 원본 hash 일치. STEP003 모델 태그 뒤 설명이 parser에 포함되는 문서 형식 오류를 발견해 설명을 하위 줄로 옮기고 sync-plan에서 complex 프로필을 확인했다. 소스/검증 기준 변경 없이 형식만 바로잡았다.
