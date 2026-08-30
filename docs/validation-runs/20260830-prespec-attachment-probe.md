# 사전규격 첨부 응답 실측 (2026-08-30)

T-20(사전규격 첨부 다운로드 경로)의 취득 경계를 설계하려면 실제 응답 형태가 필요했다.
이전 기록은 "규격서 첨부는 인증 없이 받아지고 실제 내용이 과업지시서(hwp)다"(5건)뿐이고
파일명 전달 방식, 확장자 분포, 크기를 남기지 않았다.

## 방법

모집단은 2026-08-28 고정 3일 표본의 사전규격 650건에서 추출한 `specDocFileUrl1~5`
**1,011개**다(586건이 1개 이상). 그중 `random.sample(seed=20260830)`으로 **30개**를 GET했다.
인증 정보는 보내지 않았고 redirect는 따르지 않았다. 본문 바이트는 저장하지 않고
sha256과 앞 16바이트만 남겼다. 증거는
[`data/experiments/prespec-attachment-probe/20260830/probe.json`](../../data/experiments/prespec-attachment-probe/20260830/probe.json)다.

## 확인된 사실

| 사실 | 값 |
|---|---|
| 응답 | 30/30 HTTP 200. 인증 불필요, redirect 0건 |
| host | `www.g2b.go.kr` 단일. 수집 OpenAPI(`apis.data.go.kr`)와 **다른 host**다 |
| 경로 | `/pn/pnz/pnza/UntyAtchFile/downloadFile.do?bfSpecRegNo=…&fileType=BFDTL&fileSeq=N` |
| `Content-Length` | 30/30이 실제 읽은 바이트와 정확히 일치한다 |
| 50MiB 초과 | 0건 |
| gateway | Kong(`x-kong-proxy-latency`). `set-cookie`를 보내므로 connector는 쿠키를 저장·재전송하지 않아야 한다 |

### 파일명은 percent-encoded UTF-8이다

30/30이 아래 한 가지 형태다. RFC 5987 `filename*`는 **0건**이고 EUC-KR raw byte도 0건이다.

```
Content-Disposition: attachment;filename=%EC%A0%9C%EC%95%88%EC%9A%94%EC%B2%AD%EC%84%9C.hwp;
```

`filename=` 값이 percent-encoding된 것은 RFC 6266 표준이 아니다. 따라서
`email.message.Message.get_filename()`, `cgi.parse_header` 같은 표준 파서는
`%EC%A0%9C…` 리터럴을 그대로 돌려준다. **UTF-8 percent-decode를 명시적으로 해야 한다.**
값 뒤에 세미콜론이 하나 더 붙는다.

디코드한 파일명에는 공백, 괄호, 대괄호, `·`(U+00B7), `ㆍ`(U+318D)가 들어간다.
예: `[과업지시서 및 제안요청서] 한국해양과학기술원 해양위성센터 전산장비 통합유지보수_.hwp`

### `Content-Type`은 형식 판정에 쓸 수 없다

| 확장자 | 건수 | `Content-Type` | 앞 4바이트 |
|---|---|---|---|
| `.hwp` | 16 | `application/octet-stream` | `d0cf11e0` (OLE CFB) |
| `.hwpx` | 7 | `application/octet-stream` | `504b0304` (ZIP) |
| `.hwpx` | **1** | `application/octet-stream` | **`d0cf11e0`** (OLE CFB) |
| `.pdf` | 5 | `application/pdf` | `25504446` (`%PDF`) |
| `.docx` | **1** | `application/vnd.openxmlformats-…` | `504b0304` (ZIP) |

HWP와 HWPX가 모두 `application/octet-stream`으로 오므로 declared type의 유일한 근거는
확장자이고, 확장자는 `Content-Disposition`에서만 온다. magic만으로도 부족하다 —
**HWPX와 DOCX는 둘 다 ZIP이라 앞 바이트가 같다.**

### 정책상 차단되는 건이 실재한다 (30건 중 2건, 6.7%)

- `입찰서식.docx` 1건 — `docs/security.md`가 허용하는 HWP·HWPX·PDF 밖이다.
  `assets.SUPPORTED_EXTENSIONS`에도 없다.
- 확장자가 `.hwpx`인데 내용이 OLE CFB인 파일 1건 — `inspect_quarantine()`이
  확장자 기반 declared type과 내용 기반 detected type을 비교하므로 `mime_mismatch`로 막힌다.

둘 다 결함이 아니라 정책대로 사람에게 가야 하는 결과다. 다만 **재시도해도 달라지지 않으므로
실패가 아니라 종료 상태**로 다뤄야 한다. 30건 표본의 6.7%이며 모집단 비율은 `unknown`이다.

### 크기와 저장량

| 통계 | 값 |
|---|---|
| 최소 | 27,136 B |
| 중앙값 | 176,788 B |
| p90 | 993,570 B |
| 최대 | 3,031,040 B |
| 평균 | 410,899 B |

평균 × 1,011파일 = **약 396 MiB / 3일**. 같은 비율이면 전량 다운로드는 **약 47 GiB/년**이다.
`swBizObjYn=Y`만이면 8.5%인 약 4 GiB/년이다. 이 추정은 30건 평균에 기반하며
모집단 크기 분포는 측정하지 않았다.

## 측정하지 않은 것

- 첨부 URL의 **수명**. 사전규격 등록 후 며칠이 지나도 같은 URL이 응답하는지 `unknown`이다.
  추적 상태가 나중에 정해지는 설계에서는 이 값이 다운로드 실패율을 좌우한다.
- 모집단 1,011건 전체의 확장자·크기 분포. 30건 표본만 확인했다.
- rate limit. 30회 연속 호출에서 제한을 만나지 않았다는 것 외에는 `unknown`이다.
