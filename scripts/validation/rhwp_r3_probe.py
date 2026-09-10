"""R3 native scratch → disposable PostgreSQL/versioned filesystem roundtrip.

Run with the backend venv. Only caller-owned temporary paths and an isolated
Docker PostgreSQL are written. The scanner is an explicit test double; this
probe supplies no production ClamAV or model-quality evidence.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web/backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--image", default="bidops-rdp-r0:20260910")
    args = parser.parse_args()
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.image], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="bidops-rhwp-r3-") as directory:
        runtime = Path(directory)
        scratch = runtime / "scratch"
        scratch.mkdir()
        os.environ.update(BIDOPS_ROOT=str(ROOT), BIDOPS_DATA_DIR=str(runtime / "data"), BIDOPS_ATTACHMENTS_DIR=str(runtime / "attachments"), BIDOPS_DATABASE_URL="sqlite://", BIDOPS_SCHEDULER_ENABLED="false", BIDOPS_OPENAI_ENABLED="false")
        from tests.postgres import temporary_postgres_server, migrated_engine
        from sqlalchemy.orm import Session
        from app.lifecycle.models import Notice
        from app.core.object_store import FilesystemObjectStore
        from app.deep_review.document_mcp.safety import ProcessorOptions
        from app.deep_review.models import ContentObject, ContentObjectLocation, ContentScan, DocumentVersion
        from app.deep_review.services.document_converter import ScratchDocumentProcessor
        from app.deep_review.services.prespec_v4 import prepare_v4_pdf_snapshot

        options = ProcessorOptions(renderer="rhwp-svg-pdf", prepare_pdf=True, ocr=False, timeout_seconds=300, max_output_bytes=64 * 1024 * 1024, max_pdf_objects=100_000)
        renderer = {"renderer": "rhwp-svg-pdf", "rhwp_version": "0.8.6", "rhwp_binary_sha256": hashlib.sha256((ROOT / "web/backend/app/deep_review/document_mcp/vendor/rhwp/bin/rhwp").read_bytes()).hexdigest(), "backend": "svg", "compat": "2022", "fallback_fonts": {"serif": "NanumMyeongjo", "sans": "NanumGothic", "mono": "NanumGothicCoding"}, "worker_image_digest": None}
        font = {"font_manifest_sha256": "92e5dc4ff6e83ab2008e636169bf0b24df0cb404214af33946a73f010f1650a9"}
        worker_code = "import sys,time;sys.path.insert(0,'/app/web/backend')\nfrom pathlib import Path\nfrom app.deep_review.document_protocol import convert_one\nwhile True:\n if not convert_one(Path('/scratch')): time.sleep(0.05)\n"
        name = "bidops-rhwp-r3-" + uuid4().hex[:12]
        command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--user", "1000:1000", "--memory", "1g", "--pids-limit", "128", "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--mount", f"type=bind,src={ROOT},dst=/app,readonly", "--mount", f"type=bind,src={scratch},dst=/scratch", "--workdir", "/app/web/backend", "--entrypoint", "/usr/local/bin/python", image_id, "-c", worker_code]
        records = []
        with (runtime / "worker.log").open("w") as log:
            worker = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                with temporary_postgres_server() as url:
                    os.environ["BIDOPS_TEST_POSTGRES_URL"] = url
                    with migrated_engine() as engine:
                        store = FilesystemObjectStore(runtime / "objects")
                        class CountingConverter(ScratchDocumentProcessor):
                            calls = 0
                            def process(self, *args, **kwargs):
                                self.calls += 1
                                return super().process(*args, **kwargs)
                        converter = CountingConverter(scratch, wait_seconds=310, clamav_checker=lambda _: True)
                        for ordinal, (label, filename, mime) in enumerate((
                            ("notice-142", "notice-142.hwpx", "application/hwp+zip"),
                            ("notice-10-rfp", "notice-10-rfp.hwp", "application/x-hwp"),
                            ("notice-10-sow", "notice-10-sow.hwp", "application/x-hwp"),
                        ), 1):
                            source = (args.input_dir / filename).read_bytes()
                            digest = hashlib.sha256(source).hexdigest()
                            with Session(engine) as session:
                                session.add(Notice(id=ordinal, notice_key=f"r3-probe-{ordinal}", title="isolated fixture"))
                                content = ContentObject(sha256=digest, size_bytes=len(source), detected_mime=mime, retention_class="document-source")
                                session.add(content)
                                session.flush()
                                stored = store.put("source", f"source/{digest}", source, content_type=mime)
                                location = ContentObjectLocation(content_object_id=content.id, namespace_key="source", object_key=stored.object_key, object_version_id=stored.object_version_id, etag=stored.etag, status="verified")
                                document = DocumentVersion(id=uuid4(), notice_id=ordinal, content_object_id=content.id, version=1, source_kind="manual", original_filename="isolated.hwp", role="제안요청서", is_current=True, safety_status="safe", needs_human_review=False)
                                session.add_all([location, document, ContentScan(content_object_id=content.id, scanner="test-double", scanner_version="1", status="clean", safe_result={"sha256": digest})])
                                session.flush()
                                kwargs = dict(document_version_id=document.id, source_location_id=location.id, source_bytes=source, media_type=mime, converter=converter, store=store, options=options, renderer=renderer, font=font, config={"options": vars(options)})
                                started = time.monotonic()
                                snapshot = prepare_v4_pdf_snapshot(session, **kwargs)
                                session.commit()
                                preparation_seconds = time.monotonic() - started
                                calls = converter.calls
                                repeated = prepare_v4_pdf_snapshot(session, **kwargs)
                                assert repeated.id == snapshot.id and converter.calls == calls
                                assert not [p for p in scratch.rglob("*") if p.is_file()]
                                assert hashlib.sha256((args.input_dir / filename).read_bytes()).hexdigest() == digest
                                record = {"sample": label, "source_sha256": digest, "pdf_sha256": snapshot.pdf_sha256, "page_count": snapshot.pdf_page_count, "page_text_sha256": snapshot.page_text_sha256, "map_sha256": snapshot.para_page_map_sha256, "has_hwpx": snapshot.hwpx_content_object_id is not None, "hwpx_verify": snapshot.hwpx_verify_jsonb, "structure_bound": snapshot.structure_id is not None and snapshot.structure_location_id is not None, "cache_reused_without_converter": True, "scratch_cleaned": True, "source_preserved": True, "preparation_seconds": round(preparation_seconds, 3)}
                                records.append(record)
                                print(json.dumps(record, sort_keys=True), flush=True)
            finally:
                subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                worker.wait(timeout=15)
        args.output.write_text(json.dumps({"schema": "bidops.rhwp-r3-roundtrip.v1", "image_id": image_id, "scanner": "test-double", "object_store": "versioned-filesystem-test-double", "database": "disposable PostgreSQL 17", "renderer": renderer, "font": font, "samples": records}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
