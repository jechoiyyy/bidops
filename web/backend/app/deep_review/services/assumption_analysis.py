"""Explicit consent, append-only results and fenced execution in the shared worker."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import time
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, or_, and_, update

from ...core.models import AuditEvent
from ...core.model_client import InvocationResult, ModelInvocationError
from ...lifecycle import lock_notice
from ..models import AssumptionInputVersion, AssumptionRun, AssumptionStage, WorkJob, DeepReviewPreview
from .assumption_inputs import scenario
from .assumption_report import STAGES, INSTRUCTION, MAX_PROMPT_CHARS, output_schema, prompts, source_units, project_output, AssumptionOutputError
from .deep_reviews import DeepReviewService, DeepReviewServiceError, JobClaim, StaleFenceError, _validate_actor
from .input_versions import resolve_active_versions, canonical_json_hash
from .luna_inputs import snapshot
from .luna_client import LunaClient


def execution_contract():
    files = ('assumption_analysis.py', 'assumption_inputs.py', 'assumption_report.py', 'luna_client.py')
    digest = hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in files)).hexdigest()
    return {'instruction': INSTRUCTION, 'output_schema': output_schema(),
            'max_prompt_characters': MAX_PROMPT_CHARS, 'version': 'three-stage-v1', 'implementation_sha256': digest}


def reject(code, message, status=409):
    raise DeepReviewServiceError(code, message, status_code=status)


class AssumptionAnalysisService:
    def __init__(self, *, base=None, client=None):
        self.base = base or DeepReviewService()
        self.client = client

    def _snapshot(self, session, notice_id, bundle_id):
        notice = lock_notice(session, notice_id)
        if notice is None:
            reject('not_found', '공고를 찾을 수 없습니다', 404)
        if notice_id != 1489:
            reject('unsupported_scenario', '이 가정 버전은 1489번 전용입니다', 400)
        profile, policy = resolve_active_versions(session, allow_unmeasured_reference=True)
        source = snapshot(self.base, session, notice, bundle_id, profile, policy, False)
        # The old policy controls readiness only; this path pins its own prompt/schema.
        source.pop('policy')
        source['schema'] = 'bidops.assumption-input.v1'
        source['scenario'] = scenario()
        source['prompt_contract'] = execution_contract()
        return source, profile.id

    def preview(self, session, notice_id, bundle_id):
        value, profile_id = self._snapshot(session, notice_id, bundle_id)
        previous = session.scalar(select(AssumptionInputVersion).where(AssumptionInputVersion.notice_id == notice_id)
                                  .order_by(AssumptionInputVersion.created_at.desc(), AssumptionInputVersion.id.desc()).limit(1))
        previous_kind = 'assumption_analysis'
        if previous is None:
            previous = session.scalar(select(DeepReviewPreview).where(DeepReviewPreview.notice_id == notice_id)
                                      .order_by(DeepReviewPreview.created_at.desc(), DeepReviewPreview.id.desc()).limit(1))
            previous_kind = 'deep_review'
        changed = [key for key in value if previous is None or canonical_json_hash({'value': value[key]}) !=
                   canonical_json_hash({'value': previous.input_snapshot.get(key)})]
        row = AssumptionInputVersion(notice_id=notice_id, bundle_id=bundle_id, profile_version_id=profile_id,
                                     input_sha256=canonical_json_hash(value), input_snapshot=value)
        session.add(row); session.commit()
        return {'preview_id': str(row.id), 'input_sha256': row.input_sha256, 'input': deepcopy(value),
                'previous_preview_id': str(previous.id) if previous else None, 'previous_preview_kind': previous_kind if previous else None, 'changed_fields': changed}

    def create(self, session, notice_id, preview_id, actor, request_id):
        actor = _validate_actor(actor)
        # All writers serialize on the owning notice; unique request/preview also fence races.
        if lock_notice(session, notice_id) is None:
            reject('not_found', '공고를 찾을 수 없습니다', 404)
        replay = session.scalar(select(AssumptionRun).where(AssumptionRun.request_id == request_id))
        if replay:
            if replay.notice_id != notice_id or replay.input_version_id != preview_id or replay.claimed_name != actor:
                reject('idempotency_conflict', '같은 요청 ID의 입력이 다릅니다')
            return {'id': str(replay.id), 'notice_id': notice_id}
        row = session.get(AssumptionInputVersion, preview_id)
        if row is None or row.notice_id != notice_id:
            reject('preview_required', '이 공고의 미리보기가 필요합니다')
        current, _ = self._snapshot(session, notice_id, row.bundle_id)
        if canonical_json_hash(current) != row.input_sha256 or canonical_json_hash(row.input_snapshot) != row.input_sha256:
            reject('preview_changed', '입력이 변경되었습니다. 새 미리보기를 확인하십시오')
        if session.scalar(select(AssumptionRun.id).where(AssumptionRun.input_version_id == row.id)):
            reject('preview_used', '이미 승인한 미리보기입니다')
        active = session.scalar(select(AssumptionRun.id).join(WorkJob, WorkJob.id == AssumptionRun.work_job_id)
                                .where(AssumptionRun.notice_id == notice_id, WorkJob.status.in_(['queued', 'running'])))
        if active:
            reject('active_run_exists', '이미 대기 또는 실행 중인 가정 분석이 있습니다')
        run_id = uuid4()
        job = WorkJob(job_type='assumption_analysis', aggregate_type='assumption_run', aggregate_id=run_id,
                      status='queued', max_attempts=1)
        session.add(job); session.flush()
        run = AssumptionRun(id=run_id, notice_id=notice_id, input_version_id=row.id, work_job_id=job.id,
                            request_id=request_id, claimed_name=actor)
        session.add(run)
        session.add(AuditEvent(actor_kind='human', claimed_name=actor, action='assumption_analysis.external_transfer_approved',
                              aggregate_type='assumption_run', aggregate_id=str(run_id), request_id=str(request_id),
                              safe_metadata={'preview_id': str(row.id), 'input_sha256': row.input_sha256,
                                             'model': 'gpt-5.6-luna', 'reasoning_effort': 'xhigh'}))
        session.commit()
        return {'id': str(run.id), 'notice_id': notice_id}

    def view(self, session, run_id):
        run = session.get(AssumptionRun, run_id)
        if run is None:
            reject('not_found', '가정 분석을 찾을 수 없습니다', 404)
        version = session.get(AssumptionInputVersion, run.input_version_id)
        if canonical_json_hash(version.input_snapshot) != version.input_sha256:
            reject('input_integrity_error', '입력 무결성을 확인할 수 없습니다', 503)
        job = session.get(WorkJob, run.work_job_id)
        rows = session.scalars(select(AssumptionStage).where(AssumptionStage.run_id == run.id)
                               .order_by(AssumptionStage.started_at, AssumptionStage.part)).all()
        steps = [{'stage': r.stage, 'part': r.part, 'status': r.status, 'started_at': r.started_at,
                  'completed_at': r.completed_at, 'latency_ms': r.latency_ms, 'error_code': r.error_code,
                  'result': r.result} for r in rows]
        started = session.scalars(select(AuditEvent).where(AuditEvent.aggregate_id == str(run.id),
            AuditEvent.action == 'assumption_analysis.call_started').order_by(AuditEvent.created_at)).all()
        finished = {(r.stage, r.part) for r in rows}
        active_call = next(({'stage': e.safe_metadata['stage'], 'part': e.safe_metadata['part'], 'started_at': e.created_at}
                           for e in reversed(started) if (e.safe_metadata['stage'], e.safe_metadata['part']) not in finished), None) if job.status == 'running' else None
        return {'schema_version': 'bidops.assumption-analysis.v1', 'id': str(run.id), 'notice_id': run.notice_id,
                'status': job.status, 'error_code': job.last_error_code, 'approved_at': run.approved_at,
                'input_version_id': str(version.id), 'input_sha256': version.input_sha256,
                'scenario': deepcopy(version.input_snapshot['scenario']), 'stages': steps,
                'call_count': len(started), 'active_call': active_call, 'latency_ms': sum(r.latency_ms for r in rows),
                'sources': source_units(version.input_snapshot),
                'report': next((r.result for r in reversed(rows) if r.stage == 'decision' and r.result and r.result['complete']), None)
                          if job.status == 'completed' else None}

    def listing(self, session, notice_id):
        rows = session.execute(select(AssumptionRun, WorkJob).join(WorkJob, WorkJob.id == AssumptionRun.work_job_id)
                               .where(AssumptionRun.notice_id == notice_id).order_by(AssumptionRun.approved_at.desc())).all()
        return {'items': [{'id': str(r.id), 'status': j.status, 'approved_at': r.approved_at,
                           'error_code': j.last_error_code} for r, j in rows]}

    def run_once(self, session, worker_id):
        now = self.base.clock()
        if session.in_transaction():
            session.commit()
        job = session.scalar(select(WorkJob).where(WorkJob.job_type == 'assumption_analysis',
            or_(WorkJob.status == 'queued', and_(WorkJob.status == 'running', WorkJob.lease_expires_at < now)))
            .order_by(WorkJob.scheduled_at, WorkJob.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            session.commit(); return False
        if job.status == 'running':
            job.status = 'failed'; job.last_error_code = 'lease_expired'; job.lease_fence += 1
            job.completed_at = now; job.lease_expires_at = None
            session.commit(); return True
        job.status = 'running'; job.lease_owner = worker_id; job.lease_fence += 1
        job.lease_expires_at = now + timedelta(seconds=self.base.lease_seconds); job.attempt_count += 1
        claim = JobClaim(job.id, job.aggregate_id, job.aggregate_id, worker_id, job.lease_fence)
        session.commit()
        self._execute(session, claim)
        return True

    def _execute(self, session, claim):
        client = None
        try:
            run = session.get(AssumptionRun, claim.attempt_id)
            version = session.get(AssumptionInputVersion, run.input_version_id)
            data = deepcopy(version.input_snapshot)
            if canonical_json_hash(data) != version.input_sha256:
                reject('approval_invalid', '승인 입력 무결성이 일치하지 않습니다')
            if data['scenario'] != scenario() or data['prompt_contract'] != execution_contract():
                reject('execution_config_changed', '승인 후 실행 설정이 변경되었습니다')
            if not self.base.settings.luna_deep_review_enabled or not self.base.reference_workflow_mode:
                reject('service_unavailable', 'Luna 참조 실행이 비활성입니다', 503)
            client = self.client or LunaClient(self.base.settings.luna_runner_url,
                lambda: self.base._renew_lease(session, claim, require_live=True), time.monotonic() + 7200)
            previous = []
            for stage in STAGES:
                messages = prompts(stage, data, previous)
                # A final report must see the entire approved context in one call.
                # A split final synthesis is explicitly incomplete, never published.
                outputs = []
                for part, prompt in enumerate(messages):
                    self.base._renew_lease(session, claim, require_live=True)
                    started = self.base.clock(); tick = time.monotonic()
                    if not self.base._lock_claim(session, claim):
                        raise StaleFenceError()
                    session.add(AuditEvent(actor_kind='system', action='assumption_analysis.call_started',
                        aggregate_type='assumption_run', aggregate_id=str(run.id),
                        safe_metadata={'stage': stage, 'part': part, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()},
                        created_at=started))
                    session.commit()
                    result = None; output = None; error_code = None
                    try:
                        result = client.invoke_prompt(prompt, contract='assumption-stage-v1')
                        output = project_output(result.structured_output, source_units(data), final=stage == 'decision' and len(messages) == 1)
                    except ModelInvocationError as error:
                        error_code = error.code
                        if error.raw_response:
                            result = InvocationResult({}, error.raw_response, hashlib.sha256(prompt.encode()).hexdigest(),
                                hashlib.sha256(error.raw_response).hexdigest(), None, None, int((time.monotonic()-tick)*1000), (), 'codex-exec', 'gpt-5.6-luna')
                    except AssumptionOutputError as error:
                        error_code = str(error)
                    aggregate, metadata = self.base._store_raw_aggregate([(result, {'stage': stage, 'part': part})]) if result else (None, None)
                    self.base._renew_lease(session, claim, require_live=True)
                    if not self.base._lock_claim(session, claim):
                        raise StaleFenceError()
                    content = self.base._raw_content_row(session, aggregate, metadata) if aggregate else None
                    session.add(AssumptionStage(run_id=run.id, stage=stage, part=part,
                        status='failed' if error_code else 'completed', started_at=started, completed_at=self.base.clock(),
                        latency_ms=int((time.monotonic()-tick)*1000), error_code=error_code, result=output,
                        raw_content_object_id=content.id if content else None))
                    session.commit()
                    if error_code:
                        reject(error_code, '가정 분석 단계가 실패했습니다')
                    outputs.append(output)
                previous.extend(outputs)
            if not outputs or len(outputs) != 1 or not outputs[0]['complete']:
                reject('report_incomplete', '세 단계 결과는 보존했지만 완성 보고서가 없습니다')
            self._finish(session, claim, None)
        except (DeepReviewServiceError, AssumptionOutputError, ModelInvocationError) as error:
            session.rollback()
            self._finish(session, claim, getattr(error, 'code', None) or str(error))
        except Exception:
            session.rollback()
            self._finish(session, claim, 'execution_failed')
        finally:
            if client is not None and self.client is None:
                client.close()

    def _finish(self, session, claim, code):
        if not self.base._lock_claim(session, claim):
            session.rollback(); return
        job = session.get(WorkJob, claim.job_id)
        if job.lease_expires_at <= self.base.clock():
            code = 'lease_expired'
        job.status = 'failed' if code else 'completed'; job.last_error_code = code
        job.completed_at = self.base.clock(); job.lease_expires_at = None
        session.add(AuditEvent(actor_kind='system', action='assumption_analysis.' + job.status,
            aggregate_type='assumption_run', aggregate_id=str(claim.attempt_id),
            safe_metadata={'error_code': code, 'worker_id': claim.worker_id}))
        session.commit()


def run_once(session, worker_id):
    return AssumptionAnalysisService().run_once(session, worker_id)
