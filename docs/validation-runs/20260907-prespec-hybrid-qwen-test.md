# 혼합 파싱의 Qwen 보조 호출 비교 — 2026-09-07

사용자의 요청에 따라 기존 혼합 파싱 선택기 `hybrid_v5.py`를 유지하고, 보조 LLM을 Qwen으로 바꿔 실제 호출했다. 대상은 앞선 Luna 실험과 같은 PDF 공고 1건(`pre:R26BD00269653`), 물리 2·3·4페이지다. 호출 전에 1건·3페이지를 알렸다.

이번 범위에서는 Qwen과 Luna 모두 개요를 3페이지로 선택하고 4페이지의 다음 장을 제외했다. 개요 확인 항목 6개가 모두 보존됐다. Qwen 호출은 41.071초였다. 운영 리뷰·정책·원문·기존 구조는 수정하지 않았다.

## 입력과 실행

- 공개 PDF 페이지 이미지 3개의 SHA-256을 앞선 Luna 입력 manifest와 대조했다. 회사 프로필·내부 리뷰는 입력하지 않았다.
- 같은 작업 지시문을 사용했다. 첫 소개 장은 같은 계층 또는 상위의 다음 장 전에 끝나며, 하위 항목은 소개 장에 포함한다는 조건을 유지했다.
- Luna는 Codex CLI를 사용했고, Qwen은 `ModelClient.for_purpose('overview', ..., verify_identity=True)`의 Ollama 경로를 사용했다. 같은 작업 지시 텍스트라도 system/user 배치·기본 시스템 컨텍스트·토큰화·reasoning 설정은 다르므로 모델만 바꾼 엄밀한 통제 실험은 아니다.
- Qwen 모델: `qwen3.8:27b`.
- 고정 digest: `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`.
- 기존 목적별 허용 host·revision·Ollama top_k 검사를 통과한 뒤 호출했다. temperature=0.7, top_k=20, reasoning_effort=none인 기존 설정을 유지했다.
- 실제 completion 1회, 재시도 0회. 분석 worker 자동 실행이나 hosted fallback은 추가하지 않았다.
- 원응답은 기존 암호화 객체 저장 경로로 보존하고 `parsing_comparison.hybrid_qwen_request/response` 감사를 추가했다.

## 결과

| 항목 | Qwen | 앞선 Luna |
|---|---:|---:|
| 대상 | 1건·3페이지 | 1건·3페이지 |
| 개요 선택 | [3] | [3] |
| 페이지 종류 대조 | 3/3 | 3/3 |
| 개요 확인 항목 | 6/6 | 6/6 |
| 호출 시간 | 41.071초 | 약 61.53초 |
| 입력 토큰 | 4,095 | 17,867 |
| 출력 토큰 | 1,070 | 3,130 |

확인 항목은 기간, 예산, VAT, 발주기관, 경쟁 방식, 계약 방식이다. 앞선 동결 `checks.json`을 변경하지 않고 대조했다. Qwen은 `finish_reason=stop`으로 종료했고, 시스템 Python의 jsonschema로 schema 및 페이지 집합을 검증했다. 새 호출의 후처리 오류는 없었다.

추가로 3페이지 각각의 Qwen/Luna 전사에서 공백·기호를 제외하고 NFKC·casefold로 정규화한 영문·숫자·한글 문자열을 비교했으며 모두 같았다. 목차의 원래 긴 점선을 Qwen이 짧게 표현해 출력이 작아졌지만 이 비교에서는 항목이나 페이지 번호 차이는 없었다. 이 검사는 두 모델의 일치 검사이며 원본 대비 전체 정확도나 기호·표 구조의 동일성을 증명하지 않는다.

Qwen 시간은 모델 completion 호출 구간의 monotonic 측정이고, Luna 시간은 이전 결과 파일 mtime으로 복원한 근사치다. 이미지 렌더·파싱·사람 검토 시간은 제외한다. 1회 실측으로 안정적인 속도 차이나 전체 문서 처리 비용을 일반화하지 않는다.

본문 교체는 필요하지 않았다. PDF 구조 경고는 유지했고, 이번 검증은 개요 범위와 확인 항목에 한정했다. 전체 문서 파싱 보완, 52건 모델 재실행, 개요 사업 분석 및 7범주 검토는 실행하지 않았다. 기존 52건의 결정적 선택 결과는 이 모델 교체 실험으로 변경되지 않았다.

## 재현과 산출물

실험 디렉터리: `.dryforge/prespec-hybrid-test-20260907/qwen/`.

- `run.py`: 기존 실제 분석 컨테이너에서 목적별 ModelClient로 호출. 입력·결과 파일은 배타 생성한다.
- `evaluate.py`: 동일 schema·동결 확인 항목·개요 범위·페이지 종류로 두 결과 대조.
- `038-qwen-input.json`, `038-qwen-result.json`: 입력 manifest와 파생 구조 결과. 원문이 포함되므로 Git에 넣지 않는다.
- `comparison.json`, `comparison-readable.md`, `transcription-crosscheck.json`: 비교 지표와 전사 열람 자료.
- 입력 payload hash: `83487494d1cfc9ea761e7cba466f0ddfdfe7df0b52139736ad01e02da9140770`.
- 암호화 원응답 plaintext hash: `29584350da9375159a515d2a21b4eb9e8bac97de441cf148ad048d1294af9fef`.

실행 명령:

```bash
docker exec -e PYTHONPATH=/app/web/backend bidops-overview-actual python /tmp/prespec-hybrid-qwen-20260907/run.py
python3 .dryforge/prespec-hybrid-test-20260907/qwen/evaluate.py
git diff --check
```

모델 호출·schema·확인 항목·범위 비교 및 diff 검사가 통과했다. 품질 표식은 `unmeasured_reference`이며, 개발 참조 표본의 결과를 사람 승인 정답이나 운영 품질 게이트 통과로 승격하지 않는다.

이번 결과는 의심 구간 보조 처리에 Qwen을 우선 시험할 근거가 된다. 운영 채택 전에는 남은 모호한 문서와 표 손상 사례에서도 같은 검증을 적용해야 한다. 앞선 [혼합 파싱 실험](20260907-prespec-hybrid-parsing-test.md)의 나머지 한계도 유지된다.
