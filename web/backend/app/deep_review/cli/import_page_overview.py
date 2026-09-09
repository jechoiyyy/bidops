"""Import exactly one frozen reference output. No model client is constructed."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import tempfile

from ...core.clamav import ClamAVScanner
from ...core.config import get_settings
from ...core.db import SessionLocal
from ...core.model_client import build_prompt
from ...core.object_store import object_store, MAX_OBJECT_BYTES
from ..services.page_overview import import_page_overview, require, digest, canonical, PageOverviewError, verified_input_pages


def read_file(root: Path, name: str, limit: int = MAX_OBJECT_BYTES) -> bytes:
    # Fixed filenames only; directory FDs + NOFOLLOW forbid file/symlink substitution.
    require('/' not in name and name not in {'.', '..'}, "invalid_path")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "invalid_path")
            data = stream.read(limit + 1)
            require(len(data) <= limit, "input_size_limit")
            return data
    finally:
        os.close(directory)


def extract_pages(pdf: bytes) -> list[str]:
    """Clean environment, no shell, bounded memory/output/time; no DB or secrets in child."""
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OBJECT_BYTES,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    with tempfile.TemporaryDirectory(prefix='bidops-page-import-') as directory:
        root = Path(directory)
        (root / 'source.pdf').write_bytes(pdf)
        result = subprocess.run(['/usr/bin/pdftotext', '-layout', '-enc', 'UTF-8', 'source.pdf', 'pages.txt'],
                                cwd=root, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=40, preexec_fn=limits, check=False)
        require(result.returncode == 0, "pdf_extraction_failed")
        pages = read_file(root, 'pages.txt').decode('utf-8').split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        return pages


def load_frozen(root: Path, notice_id: int) -> dict:
    require(root.is_absolute() and not root.is_symlink() and root.resolve() == root, "invalid_path")
    read_json = lambda name: json.loads(read_file(root, name, 4 * 1024 * 1024))
    record = read_json(f'{notice_id}-input.json')
    manifest = read_json('run-manifest.json')
    outcome = read_json(f'{notice_id}-outcome.json')
    output = read_json(f'{notice_id}-output.json')
    code = root / 'code'
    policy = json.loads(read_file(code, 'policy.json', 1024 * 1024))
    require(record['notice_id'] == notice_id, "input_binding_mismatch")
    require(digest(canonical(policy)) == manifest['policy_digest'], "policy_binding_mismatch")
    require(policy['model_name'] == manifest['model'] and policy['prompt_version'] == manifest['prompt_version'], "policy_binding_mismatch")
    prompt = build_prompt(policy['stages'][0]['stage'], record['model_input'], policy)
    require(digest(prompt.encode()) == outcome['prompt_sha256'], "prompt_binding_mismatch")
    source = read_file(root, f'{notice_id}.hwp')
    require(digest(source) == record['source_sha256'], "source_hash_mismatch")
    pdf = read_file(root, f'{notice_id}.pdf')
    require(digest(pdf) == record['pdf_sha256'], "pdf_hash_mismatch")
    return dict(record=record, manifest=manifest, outcome=outcome, output=output, pdf=pdf, pdf_pages=extract_pages(pdf))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--notice-id', type=int, required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--check-only', action='store_true', help='Check frozen files and PDF without database writes')
    args = parser.parse_args(argv)
    try:
        data = load_frozen(args.run_dir, args.notice_id)
        if args.check_only:
            from ..services.page_overview_validation import validate_page_overview
            errors = validate_page_overview(data['output'], verified_input_pages(data['record'], data['pdf'], data['pdf_pages']))
            print(json.dumps({'notice_id': args.notice_id, 'evidence_check_errors': errors, 'model_calls': 0}))
            return 0
        settings = get_settings()
        scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds)
        with SessionLocal() as session:
            row, created = import_page_overview(session, **data, actor=args.actor, scanner=scanner, store=object_store(namespaces=('source', 'structure')))
            session.commit()
            print(json.dumps({'id': str(row.id), 'created': created, 'validation_status': row.validation_status, 'model_calls': 0}))
        return 0
    except Exception as error:
        # Parser/filesystem/provider exceptions can contain source text or paths.
        code = str(error) if isinstance(error, PageOverviewError) else 'page_import_failed'
        print(json.dumps({'error': code}))
        return 1
