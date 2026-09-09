# 에너지시장 플랫폼 유지·보수 개요 검토 — Qwen think=true

2026-09-07 사용자가 지정한 `세계 에너지시장 정보 플랫폼 시스템 유지·보수` 공고 1건을 Qwen thinking 활성화 상태로 실제 개요 검토했다. 실제 응답에서 thinking 생성이 확인됐다. 형식과 근거 위치 검사는 통과했지만, 승인되지 않은 과거 확인 기한 및 인용 범위 문제가 남아 사람 검토 대상으로 분류했다.

## 대상과 문서 준비

- 공고: `pre:R26BD00270010`, DB 공고 ID 10, 원본 SW사업대상=Y.
- 유사한 이름의 `세계 에너지시장 정보 플랫폼 정보 콘텐츠 운영` 공고(SW=N)는 대상이 아니다.
- 기존에는 제안요청서와 과업지시서가 동시에 후보여서 자동 문서 선택이 대기 상태였다. 이번 사용자가 지정한 개요 테스트에서는 assistant가 제안요청서를 선택했다. 운영 문서 role이나 선택 정책은 바꾸지 않았다.
- 제안요청서 source SHA-256: `ea1e0a45b659a5c46a24b0638be613d6bd2fb4a53985cb7229bdaf107c37dca4`.
- 입력 구조: 기존 실제 문서 worker 산출물 `attachment-062.structure.json`, 전체 2,321블록.
- 기존 실험 선택기 `hybrid_v5.py`는 이 문서의 제목 경계를 찾지 못했다. 네트워크 없는 문서 컨테이너에서 rhwp로 첫 5페이지를 렌더하고 assistant가 이미지와 추출 텍스트를 대조했다. 렌더링 2~3페이지가 사업개요이며 4페이지부터 상세 요구사항이다. 따라서 이번 경계는 자동 판정 성공 사례가 아니다.
- 원본 ordinal [33,156)에서 빈 블록을 제외한 63블록, 원문 1,885자를 사용했다. 모델 프롬프트는 7,244자다. 개요 밖의 요구사항 총괄표·세부 요구사항은 입력하지 않았다.
- 전체 원문·기존 구조·운영 리뷰는 보존했다. 회사 프로필은 입력하지 않았다.

## thinking 활성화와 실제 호출

Ollama의 [공식 Thinking 문서](https://docs.ollama.com/capabilities/thinking)는 native chat 요청의 `think` 값과 응답의 별도 thinking 필드를 설명한다. 이번 실험은 `/api/chat`에 **`think: true`를 실제 전송**했다.

기존 목적별 ModelClient는 Ollama 호환 호출에 thinking 꺼짐을 고정하므로, 이번 실험 파일에서만 completion transport를 native 요청으로 변환했다. `ModelClient.for_purpose('overview')`의 허용 host·revision 검사와 호출 전 모델 identity/top_k 검사를 유지하고, 검증된 같은 origin의 native chat 경로만 사용했다. 운영 ModelClient·정책·환경변수 기본값은 변경하지 않았다.

- 모델: `qwen3.8:27b`.
- digest: `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`.
- 실제 요청: think=true, stream=false, temperature=0.7, top_p=0.8, top_k=20, seed=0, num_predict=16384, JSON schema 적용.
- 실제 completion: 1회, 재시도 0회, done_reason=stop.
- 응답에서 thinking 생성 확인. 추론 본문은 로그·산출물·암호화 원응답에 저장하지 않고 존재 여부와 문자 수만 기록한 뒤 폐기했다.
- 처리 시간: **84.386초**. 요청·저장·검증 구간이며 문서 렌더·사람 대조 시간은 제외한다.
- 서버 보고 prompt_eval_count=5,109, eval_count=2,023. thinking/final의 별도 토큰 수는 측정하지 않았다.
- 응답 저장: 최종 답변과 안전한 metadata를 기존 암호화 model-response 객체로 저장했다. 요청·응답·최종 검증 감사도 남겼다.

앞선 10건과 같은 개요 지시 및 회사 정보 미제공 조건을 유지했다. 이번 공고는 앞선 thinking 꺼짐 10건에 포함되지 않았고 native transport도 다르므로, 같은 문서의 thinking on/off 통제 비교는 아니다.

## 결과와 원문 대조

모델 잠정 권고는 `조건부 추진 검토`다. 주요 요약은 예산 319,000,000원(VAT 포함), 계약체결일부터 2028-09-30까지의 2단계 사업, 플랫폼 기술지원·하자보수·기능개선·데이터 업로드 지원 등이다. 주요 수치와 범위는 원문과 대체로 일치했고 회사 자격·실적·인력은 미확인으로 남겼다. 이는 회사 적합성이나 최종 참여 가능성을 확인한 결과가 아니다.

기존 schema와 원본 ordinal/block_key 검사, 추가 page 일치 검사는 통과했다. 그러나 다음 문제가 남았다.

1. **확인 기한 생성:** 입력에 승인된 확인 기한이 없는데 `2026-09-01T00:00:00Z`를 생성했다. 실행일보다 과거이며 채택하지 않았다.
2. **인용 범위 초과:** 최소 5개 claim에서 한 문단·셀의 내용보다 넓게 주장했다. ordinal 35에는 사업명만 있는데 플랫폼 URL을 포함하고, 45의 총액 문단에 47의 단계별 금액을 묶었다. 107의 기술지원·하자보수 문단에 뒤쪽 여러 과업을 묶었고, 141의 착수보고 기한 셀에 다른 보고·평가 일정까지 포함했다. 해당 내용이 다른 입력에 있는 것과 한 인용이 전체 주장을 뒷받침하는 것은 다르다.

최종 분류는 **`needs_human_review`**, 품질은 **`unmeasured_reference`**다. 원응답을 수정하지 않았고, 운영 개요 리뷰 완료·품질 게이트 통과·7범주 심층 검토 시작으로 반영하지 않았다. Thinking 활성화만으로 확인 기한 계약과 인용 의미 검증 문제가 해결되지 않는 사례다.

## 증거와 재현

실험 디렉터리: `.dryforge/prespec-energy-think-20260907/`.

- `input.json`, `policy.json`, `checks.json`: 동결 입력·실험 정책·모델 결과 확인 전 원문 확인 항목.
- `render.mjs`, `062-page-*.svg/png`: 원문 경계의 시각 대조 자료.
- `run.py`: 실제 think=true 요청. 서버의 별도 reasoning 본문은 폐기한다.
- `result.json`: 최종 답변 및 실행 metadata. 원응답 hash는 `0dd588b8d7c999712430550c27b53c6ae4dbd99f7abc42cf7cd2445fd3b167a9`.
- `evaluation-v2.json`: 최종 원문 대조 결과. 이전 `evaluation.json`은 기한·형식 검사 기록으로 보존한다.
- `result-readable.md`: 모델 요약·미확인 항목·인용 원문 대조. 상세 인용 문제는 최종 evaluation-v2 및 본 문서를 함께 본다.

```bash
docker exec -e PYTHONPATH=/app/web/backend bidops-overview-actual python /tmp/prespec-energy-think-20260907/run.py
python3 .dryforge/prespec-energy-think-20260907/evaluate.py
git diff --check
```

실제 1회 호출, thinking 생성, 원문 hash 및 형식·위치 검사를 확인했다. Python 컴파일과 diff 검사는 통과했다. 원문을 포함한 실험 파일은 Git에 넣지 않는다.
