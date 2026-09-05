"""사전규격 mock 종단 인수 흐름 (명세 §2 완료 기준 1·§12).

저장소만으로, 모델과 외부망 없이 다음을 한 번에 완주시킨다.

    회차 적재 → 1차 판정 적재(mock) → `우선 검토` 건의 자동 문서 준비
    (fake 취득 connector) → 개요 검토(mock transport) → SW사업대상=Y의 자동
    심층 검토(mock) → 보고서·최종 의견 → 증거 JSON

`bc_e2e`·`agent_e2e`가 도는 API 인수 흐름의 형제지만 **전송 계층이 다르다.**
저 둘은 떠 있는 API를 HTTP로 부르고, 이것은 격리된 workspace 안에서 같은
service·worker 함수를 직접 부른다. 사전규격 흐름의 촉발점(회차 적재 hook,
취득 종결, 개요 완료)이 REST가 아니라 프로세스 안의 이벤트이기 때문이다.

경계 규칙:

- **선별 모듈을 import하지 않는다(명세 §4).** 1차 판정 적재는 lifecycle 확장점
  (`RunIngestHook`)의 몫이고, 이 모듈은 등록된 제공자가 무엇인지 모른다.
  등록은 호출자(CLI)가 이름으로 받아 하며, 판정이 하나도 적재되지 않으면
  fail closed한다 — 등급 없는 회차를 "자동 준비 대상 없음"으로 조용히 통과
  시키지 않는다는 뜻이다.
- **live 호출이 없다.** 첨부는 fixture bytes를 돌려주는 fake connector,
  개요는 `MockOverviewTransport`, 심층은 `MockAnalysisClient`다. 어떤 경로도
  vLLM·Ollama·나라장터 주소를 열지 않는다.
- **증거 JSON에는 안전한 식별자·상태·건수만 담는다.** 원문, 프롬프트, 모델
  응답, object key, filesystem 경로, 회사 프로필 본문은 넣지 않는다(§7).
- 참조 실행이므로 심층 검토의 `quality_status`는 `mock_reference`이며 운영
  완료·품질 근거로 집계하지 않는다(§8).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.constants import DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND
from ...core.models import AuditEvent
from ...core.db import isolated_test_boundary_active
from ...core.model_client import ModelClient
from ..document_mcp.processor import DocumentProcessor
from ...lifecycle import ingest_run
from ...lifecycle.models import Attachment, Notice
from ..models import (
    AttachmentFetch,
    DeepReview,
    DeepReviewStage,
    DocumentBundle,
    DocumentBundleItem,
    PreSpecOverviewAttempt,
    PreSpecOverviewReview,
)
from ..schemas.reports import FinalOpinionRequest
from ..workers.deep_review import run_once as run_deep_review_once
from ..workers.prespec_attachment import run_once as run_prespec_attachment_once
from ..workers.prespec_overview import run_once as run_prespec_overview_once
from .auto_preparation import AUTO_ACTOR_NAME, auto_preparation_fields
from .deep_reviews import DeepReviewService, quality_status_for_review
from .effective_grade import effective_grades
from .input_versions import import_policy_version, import_profile_version
from .mock_analysis_client import MockOverviewTransport
from .prespec_overview import (
    OverviewPolicyError,
    load_overview_policy,
    overview_quality_status,
)
from .prespec_overview_runner import PreSpecOverviewRunner
from .reports import ReportService
from . import assets


PRESPEC_E2E_FIXTURE_SCHEMA = "bidops.prespec-e2e-fixture.v1"
PRESPEC_E2E_PLAN_SCHEMA = "bidops.prespec-e2e-plan.v1"
PRESPEC_E2E_RESULT_SCHEMA = "bidops.prespec-e2e-result.v1"
PRESPEC_E2E_WORKFLOW = "prespec-mock-reference"

#: 회차 디렉터리 이름. fixture의 회차 원본은 workspace로 복사해서만 읽는다.
RUN_DIRECTORY_NAME = "20260901-20260903"
#: 취득 worker의 fake source system. fixture manifest도 이 이름을 쓴다.
SOURCE_SYSTEM = "g2b"
#: 한 단계가 도는 최대 poll 수. 무한 재시작을 만들지 않기 위한 상한이다.
MAX_FETCH_POLLS = 24
MAX_OVERVIEW_POLLS = 12
MAX_DEEP_REVIEW_POLLS = 6
#: 개요 mock transport가 쓰는 loopback 주소. 호출은 주입 seam이 가져가므로
#: 이 주소로 나가는 요청은 없다. 값이 필요한 이유는 용도별 설정이 없으면
#: `ModelClient.for_purpose`가 fail closed하기 때문이다(§6.6).
OVERVIEW_LOOPBACK_BASE_URL = "http://127.0.0.1:9/v1"
OVERVIEW_LOOPBACK_HOST = "127.0.0.1"


class PreSpecE2EError(RuntimeError):
    """안정 code만 갖는 인수 실행 실패. 예외 본문은 밖으로 내보내지 않는다."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


# --- fixture -----------------------------------------------------------------


@dataclass(frozen=True)
class FixtureAttachment:
    """fake connector가 한 첨부 URL에 돌려줄 이름과 bytes 위치."""

    source_url: str
    filename: str
    path: Path

    @property
    def unsupported(self) -> bool:
        """형식 밖 첨부인가. 확장자 판정은 취득 경계와 같은 표를 쓴다."""

        return Path(self.filename).suffix.casefold() not in assets.SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class PreSpecE2EFixture:
    """회차 원본과 첨부 bytes를 함께 갖는 불변 입력."""

    root: Path
    run_directory: Path
    attachments: tuple[FixtureAttachment, ...]
    notice_keys: tuple[str, ...]

    @classmethod
    def load(cls, root: Path) -> "PreSpecE2EFixture":
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise PreSpecE2EError("invalid_fixture", "fixture는 절대 경로의 실제 디렉터리여야 한다")
        run_directory = root / "run"
        manifest_path = root / "attachments" / "attachment-manifest.json"
        if not run_directory.is_dir() or not manifest_path.is_file():
            raise PreSpecE2EError("invalid_fixture", "fixture에 회차 디렉터리나 첨부 manifest가 없다")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            collected = json.loads((run_directory / "collected-notices.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PreSpecE2EError("invalid_fixture", "fixture JSON을 읽을 수 없다") from error
        if not isinstance(manifest, Mapping) or manifest.get("schema") != PRESPEC_E2E_FIXTURE_SCHEMA:
            raise PreSpecE2EError("invalid_fixture", "첨부 manifest schema가 올바르지 않다")
        if manifest.get("source_system") != SOURCE_SYSTEM:
            raise PreSpecE2EError("invalid_fixture", "첨부 manifest의 source system이 올바르지 않다")
        rows = manifest.get("attachments")
        if not isinstance(rows, list) or not rows:
            raise PreSpecE2EError("invalid_fixture", "첨부 manifest가 비어 있다")
        attachments: list[FixtureAttachment] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise PreSpecE2EError("invalid_fixture", "첨부 manifest 항목이 객체가 아니다")
            source_url = row.get("source_url")
            filename = row.get("filename")
            name = row.get("file")
            if not all(isinstance(value, str) and value for value in (source_url, filename, name)):
                raise PreSpecE2EError("invalid_fixture", "첨부 manifest 항목에 빠진 값이 있다")
            path = root / "attachments" / str(name)
            if "/" in str(name) or not path.is_file() or path.is_symlink():
                raise PreSpecE2EError("invalid_fixture", "첨부 bytes 파일을 찾을 수 없다")
            attachments.append(
                FixtureAttachment(source_url=str(source_url), filename=str(filename), path=path)
            )
        notices = collected.get("notices") if isinstance(collected, Mapping) else None
        if not isinstance(notices, list) or not notices:
            raise PreSpecE2EError("invalid_fixture", "회차 원본에 공고가 없다")
        keys = tuple(str(item.get("notice_id")) for item in notices if isinstance(item, Mapping))
        return cls(
            root=root,
            run_directory=run_directory,
            attachments=tuple(attachments),
            notice_keys=keys,
        )

    def plan(self) -> dict[str, Any]:
        """변경 없이 확인 가능한 실행 계획. 원문도 경로도 담지 않는다."""

        return {
            "schema": PRESPEC_E2E_PLAN_SCHEMA,
            "workflow": PRESPEC_E2E_WORKFLOW,
            "run_directory_name": RUN_DIRECTORY_NAME,
            "notice_count": len(self.notice_keys),
            "notice_keys": list(self.notice_keys),
            "attachment_count": len(self.attachments),
            "unsupported_attachment_count": sum(
                1 for attachment in self.attachments if attachment.unsupported
            ),
            "attachment_filenames": sorted(
                {attachment.filename for attachment in self.attachments}
            ),
        }


class FixtureAttachmentConnector:
    """fixture bytes만 돌려주는 fake 취득 connector.

    `ProviderConnector`와 같은 자리이지만 socket을 열지 않는다. manifest에 없는
    URL은 취득 실패로 남고 다른 주소로 넘어가지 않는다.
    """

    source_system = SOURCE_SYSTEM

    def __init__(self, attachments: Sequence[FixtureAttachment]) -> None:
        self._by_url = {attachment.source_url: attachment for attachment in attachments}
        self.calls = 0

    def fetch(self, url: str) -> assets.ProviderResponse:
        self.calls += 1
        attachment = self._by_url.get(url)
        if attachment is None:
            raise assets.ProviderSecurityError(
                "provider_connector_blocked", "fixture에 없는 첨부 주소다"
            )
        return assets.ProviderResponse(
            body=attachment.path.read_bytes(),
            final_url=url,
            suggested_filename=attachment.filename,
        )


# --- 실행 환경 ----------------------------------------------------------------


def _model_response_key() -> str:
    """실행 한 번만 사는 model-response 암호화 key.

    저장소에 커밋된 비밀값을 쓰지 않고, 실행이 끝나면 환경과 함께 사라진다.
    값은 어디에도 기록하지 않는다.
    """

    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def workspace_environment(workspace: Path) -> dict[str, str]:
    """이 인수 실행이 소유하는 환경변수.

    운영 기본값을 그대로 두면 실행이 PostgreSQL·MinIO·vLLM을 요구한다. 이
    명령은 격리 실행이므로 자기 workspace 안의 SQLite와 filesystem 객체
    저장소만 쓰고, scheduler와 실제 취득기는 꺼 둔다.
    """

    return {
        "BIDOPS_DATA_DIR": str(workspace / "data"),
        "BIDOPS_ATTACHMENTS_DIR": str(workspace / "assets"),
        "BIDOPS_DATABASE_URL": f"sqlite:///{workspace / 'prespec-e2e.db'}",
        "BIDOPS_OBJECT_STORE_BACKEND": "filesystem",
        "BIDOPS_SCHEDULER_ENABLED": "false",
        "BIDOPS_G2B_ATTACHMENT_ENABLED": "false",
        "BIDOPS_OPENAI_ENABLED": "false",
        "BIDOPS_ANALYSIS_PROVIDER": "mock",
        "BIDOPS_REFERENCE_WORKFLOW_MODE": "true",
        "BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY": _model_response_key(),
        "BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY_REF": "prespec-e2e-ephemeral",
        "BIDOPS_VLLM_OVERVIEW_BASE_URL": OVERVIEW_LOOPBACK_BASE_URL,
        "BIDOPS_VLLM_OVERVIEW_ALLOWED_HOSTS": OVERVIEW_LOOPBACK_HOST,
        "BIDOPS_VLLM_OVERVIEW_MODEL_REVISION": hashlib.sha256(
            b"bidops.prespec-overview.mock-reference"
        ).hexdigest(),
    }


@contextmanager
def run_environment(workspace: Path) -> Iterator[None]:
    """workspace 환경을 적용하고 끝나면 **반드시** 원래대로 돌린다.

    이 명령을 프로세스 안에서 부르는 호출자(테스트)가 뒤따르는 작업의 설정을
    잃지 않게 하려는 것이다. `get_settings` 캐시도 앞뒤로 비운다.
    """

    values = workspace_environment(workspace)
    managed = (*values, "BIDOPS_ACTIVE_PROFILE_VERSION_ID", "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID")
    previous = {name: os.environ.get(name) for name in managed}
    os.environ.update(values)
    get_settings.cache_clear()
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def write_evidence(path: Path, payload: Mapping[str, Any]) -> None:
    """증거 JSON을 **덮어쓰지 않고** 원자적으로 publish한다.

    `bc_e2e`의 publish와 같은 규칙이다. `link(2)`는 다른 실행이 같은 경로를
    이미 만들었으면 실패하므로 인수 증거가 조용히 갈리지 않는다.
    """

    if (
        not path.is_absolute()
        or path.exists()
        or path.is_symlink()
        or not path.parent.is_dir()
        or path.parent.resolve() != path.parent
    ):
        raise PreSpecE2EError("invalid_output", "output은 존재하는 디렉터리의 새 절대 경로여야 한다")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as error:
        temporary.unlink(missing_ok=True)
        raise PreSpecE2EError("invalid_output", "output이 이미 있다") from error
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


# --- 단계 --------------------------------------------------------------------


def _copy_run_directory(fixture: PreSpecE2EFixture, workspace: Path) -> Path:
    """fixture 회차 원본을 workspace로 복사한다. 원본은 읽기만 한다."""

    target = workspace / "data" / "runs" / RUN_DIRECTORY_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PreSpecE2EError("workspace_not_empty", "workspace에 같은 회차가 이미 있다")
    shutil.copytree(fixture.run_directory, target)
    return target


def _ingest(session: Session, run_directory: Path, workspace: Path) -> dict[str, Any]:
    result = ingest_run(run_directory, session, reports_root=workspace / "reports").as_dict()
    if int(result.get("judgments") or 0) <= 0:
        # 판정이 없으면 effective grade가 없고 자동 준비 자격도 열리지 않는다.
        # 조용히 "대상 없음"으로 통과시키지 않고 여기서 멈춘다.
        raise PreSpecE2EError(
            "screening_provider_missing",
            "회차 적재 hook이 판정을 적재하지 않았다. 판정 제공자를 등록해야 한다",
        )
    return {
        "run_id": str(result.get("run_id")),
        "notices": int(result.get("notices") or 0),
        "judgments": int(result.get("judgments") or 0),
        # 경고는 code만 센다. message·context에는 파일 경로가 들어 있다.
        "warning_codes": sorted(
            {
                str(warning.get("code"))
                for warning in result.get("warnings", [])
                if isinstance(warning, Mapping) and warning.get("code")
            }
        ),
    }


def _activate_input_versions(session: Session, actor: str) -> dict[str, str]:
    """불변 profile·analysis policy 판을 만들고 이 실행의 active로 지정한다.

    운영과 같은 import 경로를 쓰고, active 지정은 배포 환경변수로만 한다
    (`active_version_ids`). 이 실행의 환경은 `run_environment`가 소유하므로
    값은 실행이 끝나면 사라진다. 품질 측정값은 넣지 않는다 — 참조 실행이므로
    `BIDOPS_REFERENCE_WORKFLOW_MODE`가 미측정 policy를 허용한다.
    """

    profile = import_profile_version(session, None, created_by_name=actor, label="company-profile")
    policy = import_policy_version(
        session, None, created_by_name=actor, label="analysis-policy-lean-v1"
    )
    identifiers = {
        "BIDOPS_ACTIVE_PROFILE_VERSION_ID": str(profile.id),
        "BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID": str(policy.id),
    }
    session.commit()
    os.environ.update(identifiers)
    get_settings.cache_clear()
    return {
        "profile_version_id": identifiers["BIDOPS_ACTIVE_PROFILE_VERSION_ID"],
        "analysis_policy_version_id": identifiers["BIDOPS_ACTIVE_ANALYSIS_POLICY_VERSION_ID"],
    }


def _fetch_all(session: Session, fixture: PreSpecE2EFixture) -> None:
    """취득 큐가 빌 때까지 취득 worker를 상한 안에서 돌린다."""

    connectors = {SOURCE_SYSTEM: FixtureAttachmentConnector(fixture.attachments)}
    # malware 검사기는 fixture bytes에 대한 결정적 통과다. 검사 seam 자체를
    # 없애지 않는다 — 검사기가 없으면 취득은 fail closed한다.
    processor = DocumentProcessor(clamav_checker=lambda _content: True)
    for _index in range(MAX_FETCH_POLLS):
        claimed = run_prespec_attachment_once(
            session,
            "prespec-e2e-fetch-worker",
            connectors=connectors,
            processor=processor,
        )
        if not claimed:
            return
    raise PreSpecE2EError("fetch_not_settled", "취득 큐가 상한 안에 종결되지 않았다")


def _overview_runner() -> tuple[PreSpecOverviewRunner, MockOverviewTransport]:
    """policy가 지정한 모델명으로 묶인 mock transport 실행기.

    binding은 `approved_overview_binding`이 만든다 — 여기서 `reference_only`나
    `deployable`을 손으로 정하지 않는다는 뜻이다.
    """

    try:
        policy = load_overview_policy()
    except OverviewPolicyError as error:
        raise PreSpecE2EError("overview_policy_unavailable", "개요 policy를 읽을 수 없다") from error
    if policy is None:
        raise PreSpecE2EError("overview_policy_unavailable", "개요 policy를 읽을 수 없다")
    transport = MockOverviewTransport(policy.model_name)
    client = ModelClient.for_purpose(
        "overview",
        model=policy.model_name,
        output_contract=policy.output_contract,
        settings=get_settings(),
        completion_create=transport.completion_create,
        models_list=transport.models_list,
    )
    return PreSpecOverviewRunner(client=client, policy=policy), transport


def _run_overviews(session: Session) -> None:
    """개요 슬롯을 상한 안에서 돌린다.

    합성 analysis worker의 한 poll과 같은 자리를 부른다. 개요 전용 진입점을
    만들지 않는다는 규칙은 그대로다.
    """

    runner, _transport = _overview_runner()
    for _index in range(MAX_OVERVIEW_POLLS):
        if not run_prespec_overview_once(session, "prespec-e2e-analysis-worker", runner=runner).claimed:
            return
    raise PreSpecE2EError("overview_not_settled", "개요 큐가 상한 안에 종결되지 않았다")


def _run_deep_reviews(session: Session, service: DeepReviewService) -> None:
    for _index in range(MAX_DEEP_REVIEW_POLLS):
        if not run_deep_review_once(session, "prespec-e2e-analysis-worker", service=service).claimed:
            return
    raise PreSpecE2EError("deep_review_not_settled", "심층 검토 큐가 상한 안에 종결되지 않았다")


# --- 증거 --------------------------------------------------------------------


def _bundle_evidence(session: Session, notice_id: int) -> dict[str, Any] | None:
    bundle = session.scalars(
        select(DocumentBundle)
        .where(DocumentBundle.notice_id == notice_id)
        .order_by(DocumentBundle.revision.desc())
        .limit(1)
    ).first()
    if bundle is None:
        return None
    issues = bundle.issues_snapshot if isinstance(bundle.issues_snapshot, list) else []
    documents = session.scalars(
        select(DocumentBundleItem.document_version_id).where(
            DocumentBundleItem.bundle_id == bundle.id
        )
    ).all()
    return {
        "id": str(bundle.id),
        "revision": int(bundle.revision),
        "status": str(bundle.status),
        "confirmed_by": bundle.confirmed_by_name,
        "auto_confirmed": bundle.confirmed_by_name == AUTO_ACTOR_NAME,
        "document_count": len(documents),
        "issue_codes": sorted(
            {str(issue.get("code")) for issue in issues if isinstance(issue, Mapping) and issue.get("code")}
        ),
        "blocking_issue_count": sum(
            1 for issue in issues if isinstance(issue, Mapping) and issue.get("blocking")
        ),
    }


def _overview_evidence(session: Session, notice_id: int) -> dict[str, Any] | None:
    review = session.scalar(
        select(PreSpecOverviewReview).where(PreSpecOverviewReview.notice_id == notice_id)
    )
    if review is None:
        return None
    attempt = session.scalars(
        select(PreSpecOverviewAttempt)
        .where(PreSpecOverviewAttempt.review_id == review.id)
        .order_by(PreSpecOverviewAttempt.sequence.desc())
        .limit(1)
    ).first()
    return {
        "status": str(review.status),
        "result": review.result,
        "transport": "mock",
        "attempt_status": str(attempt.status) if attempt is not None else None,
        # 결정적 mock attempt는 완료할 수 없으므로(ADR·DB CHECK) 이 실행의
        # 표식은 `unmeasured_reference`다. 운영 완료로 집계하지 않는다.
        "quality_status": overview_quality_status(attempt) if attempt is not None else None,
    }


def _final_opinion(session: Session, review_id: Any, report: Mapping[str, Any], actor: str) -> dict[str, Any]:
    validation = report["validation"]
    payload = FinalOpinionRequest(
        request_id=uuid4(),
        report_revision_id=report["current_revision_id"],
        validation_run_id=validation["validation_run_id"],
        value="보류",
        reason="모의 종단 인수 실행의 기록이며 실제 입찰 결정이 아닙니다.",
        acknowledged_validation_failure=validation["status"] == "failed",
    )
    opinion = ReportService().create_final_opinion(session, review_id, actor, payload)
    return {
        "id": str(opinion["id"]),
        "sequence": int(opinion["sequence"]),
        "value": str(opinion["value"]),
        "validation_status_at_opinion": str(opinion["validation_status_at_opinion"]),
        "acknowledged_validation_failure": bool(opinion["acknowledged_validation_failure"]),
    }


def _deep_review_evidence(session: Session, notice_id: int, actor: str) -> dict[str, Any] | None:
    review = session.scalars(
        select(DeepReview)
        .where(DeepReview.notice_id == notice_id)
        .order_by(DeepReview.created_at.desc())
        .limit(1)
    ).first()
    if review is None:
        return None
    report = ReportService().get_report(session, review.id)
    payload = report["report"]
    validation = report["validation"]
    projection = payload if isinstance(payload, Mapping) else {}
    return {
        "id": str(review.id),
        "status": str(review.status),
        "created_by_actor_kind": _creation_actor_kind(session, review.id),
        "analysis_transport": "mock",
        "quality_status": quality_status_for_review(session, review.id),
        "effective_grade_at_start": review.effective_grade_at_start,
        "stages": _stage_rows(session, review),
        "report_revision_id": str(report["current_revision_id"]),
        "validation_status": str(validation["status"]),
        "validation_checks": [
            {"check_type": str(check.get("check_type")), "status": str(check.get("status"))}
            for check in (validation.get("checks") or [])
            if isinstance(check, Mapping)
        ],
        "report_sections": [
            str(section.get("section_key"))
            for section in projection.get("sections", [])
            if isinstance(section, Mapping)
        ],
        "system_recommendation": projection.get("system_recommendation"),
        "document_bundle_limitation_codes": _limitation_codes(session, review),
        "final_opinion": _final_opinion(session, review.id, report, actor),
    }


def _creation_actor_kind(session: Session, review_id: Any) -> str | None:
    """이 검토를 만든 것이 사람인지 시스템인지.

    검토 행에는 그 값이 없다 — 생성 경로가 하나이고 감사 이벤트의 action이
    누가 만들었는지를 말하기 때문이다(`deep_review.create` 대
    `deep_review.auto_create`). 감사가 없으면 ``None``이며 사람으로 접지 않는다.
    """

    action = session.scalar(
        select(AuditEvent.action)
        .where(
            AuditEvent.action.in_(tuple(DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND.values())),
            AuditEvent.aggregate_type == "deep_review",
            AuditEvent.aggregate_id == str(review_id),
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(1)
    )
    for actor_kind, value in DEEP_REVIEW_CREATION_ACTION_BY_ACTOR_KIND.items():
        if value == action:
            return actor_kind
    return None


def _stage_rows(session: Session, review: DeepReview) -> list[dict[str, Any]]:
    """현재 attempt의 stage 이름과 상태. 모델 산출물 본문은 담지 않는다."""

    return [
        {"stage": str(row.stage), "status": str(row.status)}
        for row in session.scalars(
            select(DeepReviewStage)
            .where(DeepReviewStage.attempt_id == review.current_attempt_id)
            .order_by(DeepReviewStage.sequence.asc())
        ).all()
    ]


def _limitation_codes(session: Session, review: DeepReview) -> list[str]:
    """보고서의 묶음 한계 절이 옮긴 issue code. 문장은 담지 않는다."""

    bundle = session.get(DocumentBundle, review.bundle_id)
    issues = bundle.issues_snapshot if bundle is not None and isinstance(bundle.issues_snapshot, list) else []
    return sorted(
        {
            str(issue.get("code"))
            for issue in issues
            if isinstance(issue, Mapping) and issue.get("code") == "unsupported_attachment_excluded"
        }
    )


def _fetch_counts(session: Session, notice_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in session.scalars(
        select(AttachmentFetch.status)
        .join(Attachment, Attachment.id == AttachmentFetch.attachment_id)
        .where(Attachment.notice_id == notice_id)
    ).all():
        counts[str(status)] = counts.get(str(status), 0) + 1
    return counts


def _notice_evidence(session: Session, notice: Notice, actor: str) -> dict[str, Any]:
    fields = auto_preparation_fields(session, [notice.id]).get(notice.id, {})
    grade = effective_grades(session, [notice.id]).get(notice.id)
    flags = notice.qualification_flags_json if isinstance(notice.qualification_flags_json, Mapping) else {}
    return {
        "notice_key": str(notice.notice_key),
        "sw_business_status": flags.get("sw_business_status"),
        "effective_grade": grade.grade if grade is not None else None,
        "grade_source": grade.source if grade is not None else None,
        "fetch_statuses": _fetch_counts(session, notice.id),
        "bundle": _bundle_evidence(session, notice.id),
        "overview": _overview_evidence(session, notice.id),
        "auto_preparation_status": fields.get("auto_preparation_status"),
        "auto_preparation_reason": fields.get("auto_preparation_reason"),
        "deep_review": _deep_review_evidence(session, notice.id, actor),
    }


def _attachment_totals(session: Session) -> dict[str, int]:
    counts: dict[str, int] = {"completed": 0, "unsupported_excluded": 0, "other": 0}
    for status, code in session.execute(
        select(AttachmentFetch.status, AttachmentFetch.last_error_code)
    ).all():
        if status == "완료":
            counts["completed"] += 1
        elif code == "unsupported_extension":
            counts["unsupported_excluded"] += 1
        else:
            counts["other"] += 1
    return counts


# --- 실행 --------------------------------------------------------------------


def run_prespec_e2e(
    fixture: PreSpecE2EFixture,
    workspace: Path,
    session_factory: Any,
    *,
    actor_name: str = "E2E 담당자",
) -> dict[str, Any]:
    """§2-1의 흐름을 한 번 완주시키고 경계 있는 증거를 돌려준다."""

    if not isolated_test_boundary_active():
        # 이 명령은 격리 실행 전용이다. 운영 PostgreSQL·MinIO를 건드릴 수 있는
        # 프로세스에서는 아무것도 하지 않는다.
        raise PreSpecE2EError(
            "isolated_boundary_required",
            "이 인수 실행은 격리 실행 경계(BIDOPS_TEST_MODE=1)에서만 돈다",
        )
    run_directory = _copy_run_directory(fixture, workspace)

    with session_factory() as session:
        ingest = _ingest(session, run_directory, workspace)
        session.commit()
    with session_factory() as session:
        active_versions = _activate_input_versions(session, actor_name)
    with session_factory() as session:
        _fetch_all(session, fixture)
    with session_factory() as session:
        _run_overviews(session)
    service = DeepReviewService()
    with session_factory() as session:
        _run_deep_reviews(session, service)

    with session_factory() as session:
        notices = session.scalars(
            select(Notice).where(Notice.source_type == "pre_spec").order_by(Notice.id.asc())
        ).all()
        evidence = {
            "schema": PRESPEC_E2E_RESULT_SCHEMA,
            "workflow": PRESPEC_E2E_WORKFLOW,
            "ingest": ingest,
            "active_input_versions": active_versions,
            "attachments": _attachment_totals(session),
            "notices": [_notice_evidence(session, notice, actor_name) for notice in notices],
            "passed": True,
        }
        session.commit()
    return evidence


__all__ = [
    "MAX_DEEP_REVIEW_POLLS",
    "MAX_FETCH_POLLS",
    "MAX_OVERVIEW_POLLS",
    "PRESPEC_E2E_FIXTURE_SCHEMA",
    "PRESPEC_E2E_PLAN_SCHEMA",
    "PRESPEC_E2E_RESULT_SCHEMA",
    "PRESPEC_E2E_WORKFLOW",
    "FixtureAttachment",
    "FixtureAttachmentConnector",
    "PreSpecE2EError",
    "PreSpecE2EFixture",
    "run_environment",
    "run_prespec_e2e",
    "workspace_environment",
    "write_evidence",
]
