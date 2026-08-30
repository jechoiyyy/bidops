# 공고는 외부 식별자로 누적하고 회차는 관측 이력으로 강등한다

- 상태: 채택
- 일자: 2026-08-28

## 맥락

현재 스키마는 회차 종속이다.

```
notice.run_id       NOT NULL, ondelete=CASCADE
uq_notice_run_key   (run_id, notice_key)
review.run_id       NOT NULL, ondelete=CASCADE
uq_review_notice_run (notice_id, run_id)
Run.notices/reviews  cascade="all, delete-orphan"
```

같은 외부 공고가 회차마다 새 `notice` 행으로 들어온다. 그래서 담당자 리뷰, 추적 선택,
심층검토가 그 회차의 행에 묶이고 다음 회차의 같은 공고에는 이어지지 않는다.
`docs/business-rules.md:30`은 최초·최근 확인 시각과 탈락 기록의 보존을 요구하는데
현재 구조로는 만족할 수 없다.

조사에서 확인한 사실:

- `notice`는 이미 다형적이다. `source_type`이 `bid_notice`와 `pre_spec`을 구분하고,
  8개 테이블(judgment, attachment, review, document_version, document_bundle, deep_review,
  evidence_ref, screening_execution)이 **대리키 `notice.id`**를 참조한다.
  외부 식별자 기준으로 바꿔도 이 8개 테이블은 바뀌지 않는다.
- 발주계획 갱신은 원 구간 재조회로 재관측된다
  (`docs/validation-runs/20260828-lifecycle-linkage-survey.md`). 관측 이력을 저장할 자리가 필요하다.
- `notice`에 맞지 않는 필드는 유실된다. `pre_spec` 정규화기는 `attachments`를 `[]`로 비우고
  `swBizObjYn`·`bsnsDivNm`은 담을 자리가 없어 `raw_source` JSONB에만 남는다.
- 운영 데이터가 아직 없다. Alembic 마이그레이션은 3개이고 `web/data/`는 비어 있다.
  이 변경의 비용은 지금이 가장 낮다.

## 결정

**1. `notice`를 외부 식별자 기준 누적 테이블로 바꾼다.**

`uq_notice_run_key(run_id, notice_key)`를 `uq_notice_key(notice_key)`로 바꾸고
`notice.run_id`를 제거한다. `Run.notices`의 `delete-orphan` cascade를 없앤다.
회차 삭제가 공고를 지우면 안 된다.

**2. `run`은 관측 회차로 강등하고 관측 이력을 신설한다.**

`notice_observation(notice_id, run_id, observed_at, changed_fields_json)`을 만든다.
공고마다 최초 확인 시각과 최근 확인 시각을 유지하고, 재관측에서 바뀐 필드를 남긴다.
`Run.status='superseded'`는 더 이상 데이터를 대체한다는 뜻이 아니라 그 회차가 끝났다는 뜻이다.

**3. 사람 판정을 회차에서 떼어낸다.**

`review.run_id`를 nullable로 낮추고 "어느 관측에서 작성했는지"의 참고 값으로만 쓴다.
`uq_review_notice_run(notice_id, run_id)`를 공고 기준 유일성으로 바꾼다.
리뷰와 추적 선택은 공고에 붙어 회차를 넘어 유지된다.

**4. 발주계획은 `notice`에 넣지 않고 `order_plan` 별도 테이블로 만든다.**

외부 키는 `orderPlanUntyNo`이고 관측 이력은 `notice_observation`과 같은 패턴으로 둔다.

**5. `opportunity`와 `opportunity_link`가 세 단계를 묶는다.**

[ADR-0022](0022-plan-prespec-centered-lifecycle.md)의 opportunity ID를 여기서 실체화한다.
`opportunity_link`는 [ADR-0025](0025-prespec-link-search-unconfirmed-state.md)가 요구하는
연결 상태 네 가지, 후보 목록과 후보별 전략, 발주기관 일치 여부, 마지막 검색 시각,
사람 판정과 이유를 담는다.

**6. 하위 8개 테이블은 바꾸지 않는다.**

`notice.id`를 계속 참조한다. 사전규격은 `notice`에 그대로 두므로 attachment·document_bundle·
deep_review 경로가 지금처럼 동작한다.

## 대안

**발주계획을 세 번째 `source_type`으로 `notice`에 통합**은 기각했다. 테이블은 줄지만
`pre_spec`에서 이미 관측된 필드 유실이 반복된다. 발주계획의 예정 시기·발주 방식·통합번호는
`notice`의 입찰공고 중심 컬럼에 대응하지 않아 `raw_source`에만 남게 된다.
또한 [ADR-0022](0022-plan-prespec-centered-lifecycle.md)가 심층검토를 사전규격 RFP 기반으로
정했으므로 발주계획에는 attachment·document_bundle·deep_review가 붙지 않는다.
쓰지 않는 관계 여덟 개를 떠안을 이유가 없다.

**새 테이블 계열로 시작하고 `notice`/`run`을 그대로 두기**도 기각했다. `notice`가 이미
`pre_spec`을 담고 있으므로 사전규격이 두 곳에 존재해 정본이 갈라진다. 입찰공고 추적을
구현할 때 같은 회차 종속 문제를 다시 만나고, 그때는 운영 데이터가 있어 비용이 더 크다.

**회차 종속을 유지하고 화면에서 합치기**는 검토하지 않았다. 같은 공고의 리뷰가 여러 행에
흩어지면 어느 것이 현재 판정인지 정할 수 없다.

## 결과

- 담당자 리뷰, 추적 선택, 심층검토가 회차를 넘어 유지된다.
  `docs/business-rules.md:30`의 최초·최근 확인 시각과 탈락 기록 보존을 구조로 만족한다.
- Alembic 마이그레이션이 필요하다. 운영 데이터가 없는 지금 수행한다.
- cascade 정책을 다시 봐야 한다. 회차 삭제가 공고·리뷰·심층검토를 지우면 안 된다.
- 적재 경로가 바뀐다. 회차마다 새 행을 넣던 것을 외부 식별자 기준 upsert와 관측 기록으로
  바꾼다. 원본 불변성은 그대로다. 재관측이 원본을 덮어쓰지 않고 관측 행을 추가한다.
- T-4(사전규격 정규화기 보강)가 함께 가야 한다. 첨부 URL, `swBizObjYn`, `bsnsDivNm`,
  `bidNtceNoList`를 담을 자리를 만들지 않으면 누적으로 바꿔도 유실은 그대로다.
- 입찰공고 추적은 같은 구조 위에서 구현한다. 별도 설계가 필요 없다.
