# 수집·정규화·표본 모듈 작업 규칙

## 책임

이 모듈은 나라장터 공개 API 호출, 원문 보존, 결정적 정규화, 고재현율 후보 신호, 비교 실험용 표본 선정을 소유한다. 현재 공고 수집 파일 계약을 유지하며, 발주계획·사전규격 수집을 추가할 때도 같은 불변 회차 경계를 사용한다.

회사 적합성의 의미 판정, 첨부 본문 해석, 심층 검토, 최종 등급, HTML 표현은 여기서 수행하지 않는다.

## 경계

- 웹 DB나 서비스 코드를 import하지 않는다. UTF-8 versioned JSON과 종료 상태가 유일한 연결 경계다.
- downstream 등급, 준비 상태, 화면 표시를 이용해 원본 레코드를 제거하지 않는다.
- API 원문을 정규화 결과로 대체하지 않는다. 원문 파일, 요청 window, endpoint, page, 수집 시각, source hash를 보존한다.
- API key는 환경에서만 읽고 URL, 오류, 원문, 로그, artifact에 남기지 않는다.

## 수집 규칙

- 페이지네이션, 빈 페이지, 재시도, 시간대, 중복 응답을 명시적으로 처리한다. 재시도는 제한하고 실제 HTTP 요청 수를 계측한다.
- 공식 식별자를 안정 ID의 우선 근거로 사용한다. 제목이나 배열 순서를 ID로 사용하지 않는다.
- 필드가 없거나 의미가 불확실하면 빈 기본값을 만들지 않고 `unknown_fields`와 원문 위치를 남긴다.
- 같은 원문과 설정은 같은 정규화 결과를 만들어야 한다. 무작위 표본은 기록 가능한 seed를 사용한다.
- 후보 신호의 출처를 제목, 분류, 수행실적, 기타로 구분한다. 일반 조달 분류를 제목 일치와 같은 강도로 취급하지 않는다.
- 후보군은 적합 판정이 아니다. 후보에 들지 않은 레코드도 audit pool이나 전체 모집단에 남긴다.

## 발주계획과 사전규격 추가 시 규칙

- 발주계획은 일반용역·기술용역 전체를 수집하고 SW사업대상 여부로 선필터하지 않는다.
- 선택된 발주계획만 저장하지 않는다. 공식 계획번호, 사업명, 기관 코드·명, 예산, 예정일, 계약 방식, 업무 구분, SW 상태, URL, 최초·최근 발견, source hash를 전체 모집단에 보존한다.
- 사전규격은 선택된 발주계획과 무관하게 매일 독립 수집한다. 현재 범위는 일반용역·기술용역 중 `SW사업대상=대상`인 항목만이다.
- 발주계획·사전규격·입찰공고 연결은 공식 통합번호만 자동 확정한다. 기관·제목·예산·시기 유사도는 점수가 있는 후보로만 출력한다.
- 사람 검토 월·목 일정 때문에 매일 원천 수집을 건너뛰지 않는다.

## 선별 실험 표본

- 한 번 수집한 3일 전체 모집단을 동결하고 키워드 규칙, ColBERT, Qwen3.8:27B, GPT Luna xhigh가 같은 입력을 받게 한다.
- 방식별 score, rank, reason, method·policy version, raw output reference, 비용, 지연을 따로 보존한다.
- 모델 출력은 정답이 아니다. GPT Sol xhigh는 네 방식의 이견을 찾는 silver reference로만 사용하고, 사람 relevance·우선순위와 adjudication을 별도 gold 정답층으로 유지한다.
- 외부 참조 모델용 export는 공개 발주계획 메타데이터와 별도 승인된 회사 역량 요약만 포함한다. 회사 프로필 전문, 첨부, 내부 리뷰를 포함하지 않는다.

## 현재 파일 계약

- 생산 출력은 `bidops.collected.v2`이며 안정 notice ID, source type, source window, 원문 상대 참조, unknown fields, 후보 신호를 포함한다.
- 검증 표본은 `bidops.validation-set.v2`이며 분석층과 감사층을 함께 가진다. 감사층을 제외 정답으로 해석하지 않는다.
- schema 의미를 바꾸면 새 버전을 만든다. 기존 v2를 제자리에서 재정의하지 않는다.

## 검증

```bash
python3 -m unittest discover -s skills/bidops-collect/tests -p 'test_*.py' -v
```

페이지네이션, 제한 재시도, 빈 응답, Asia/Seoul 경계, 안정 ID, 제목·분류 신호 구분, threshold 경계, audit pool, 원문 재분류, key 마스킹, 동일 입력 재현성을 검사한다. 파일 계약에 영향이 있으면 루트 `./run-tests.sh`도 실행한다.

## 발주계획 수집기

`collect_order_plans.py`는 공고 수집기와 별도의 회차로 발주계획을 수집한다. 기본 모드는
Asia/Seoul 오늘을 포함한 최근 21일이며, `--from-date`·`--to-date`를 함께 주면 `to-date`
미만의 명시적인 반개구간으로 조회한다. 범위는 `bsnsDivNm`이 `일반용역` 또는 `기술용역`인
항목이며, 범위 밖 원문 건수도 artifact의 `counts`에 남긴다. 발주월 query 범위
`200412`~`999912`는 생략하지 않는다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --output-dir data/runs/order-plans-$(date +%Y%m%d) \
  --days 21

python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --output-dir data/runs/order-plans-20260808-20260829
```

`BIDOPS_G2B_API_KEY`는 프로세스 환경 또는 루트 `.env`에서만 읽고 query·raw·로그에
저장하지 않는다. API 응답 page는 회차 아래 `raw/`에 먼저 보존하며, 규칙 변경 뒤에는 새
회차 디렉터리를 만들어 API 호출 없이 재정규화한다.

```bash
python3 skills/bidops-collect/scripts/collect_order_plans.py \
  --from-date 2026-08-08 --to-date 2026-08-29 \
  --from-raw data/runs/order-plans-20260808-20260829/raw \
  --output-dir data/runs/order-plans-20260808-20260829-reclassified
```
