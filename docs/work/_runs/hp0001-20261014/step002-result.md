# HP-00 STEP-002

- 구현자 gpt-5.6-sol/high, hp00_step002. 신규 정책 2개, identity map, 회사 정책 집합·전역 거부·선택 순서, worker/slice 분기, 정책 fixture.
- 리더 검사: step002-tests.log 7 passed (T3/T4 및 legacy canonical 보존); step002-boundaries.log 5 passed (slice identity·legacy mapping·회사 전역 active 거부). 일회용 PostgreSQL 17.11 포함, skip 없음.
- hp-v1 SHA256 776c3efc908bf005f57df58d153406add592103d7cd7d3874ae9984cd363184b
- v5 SHA256 f575e827d592fbe8c90bb4f2210d242351e805cd0975212559b2fa7a615cce2e
- 회사 preview·attempt metadata·NULL 실행 guard는 STEP-003 의존이며 그 뒤 T5~T9 통합 검사.
