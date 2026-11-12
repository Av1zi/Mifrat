"""Pin audit inputs without changing any production path or Git state."""
import datetime as dt
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
OUT = ROOT / 'docs/audits/2026-11-12-reaudit'
SNAP = RUN / 'snapshot'

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf-8').strip()

def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

def main():
    if OUT.exists() or SNAP.exists():
        raise SystemExit('Refusing to overwrite an existing audit/snapshot')
    OUT.mkdir(parents=True)
    SNAP.mkdir(parents=True)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    head = git('rev-parse', 'HEAD')
    archive = subprocess.check_output(['git', 'archive', '--format=zip', head], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        z.extractall(SNAP)
    local = []
    for name in ['AGENTS.md', 'decisions.md']:
        source = ROOT / name
        shutil.copy2(source, SNAP / name)
        local.append(name)
    for folder in ['data/pcpartdb', 'data/pckombo']:
        source = ROOT / folder
        if source.exists():
            for p in source.rglob('*'):
                if p.is_file() and p.suffix in {'.json', '.jsonl', '.csv'} and '.cache' not in p.parts:
                    rel = p.relative_to(ROOT)
                    dest = SNAP / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
                    if git('ls-files', '--', rel.as_posix()) == '':
                        local.append(rel.as_posix())
    hashes = {}
    for p in SNAP.rglob('*'):
        if p.is_file():
            rel = p.relative_to(SNAP).as_posix()
            if rel.startswith(('data/', 'scraper/', 'scripts/', 'nano/', '.github/workflows/', 'site/src/', 'site/scripts/')) or rel in {'AGENTS.md', 'decisions.md', 'README.md', 'GLOSSARY.md', 'PROJECT_OVERVIEW.md', 'requirements.txt'}:
                hashes[rel] = {'sha256': sha(p), 'bytes': p.stat().st_size, 'local_only': rel in local}
    (RUN / 'input-hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    catalog = json.loads((SNAP / 'data/catalog.json').read_text(encoding='utf-8'))
    deps = {}
    for package in ['Scrapy', 'rapidfuzz', 'Pillow', 'pytest', 'requests', 'beautifulsoup4', 'PyYAML']:
        try:
            deps[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            deps[package] = None
    manifest = {
        'audit_only': True, 'status': 'in_progress', 'repository': str(ROOT),
        'utc_start': started, 'head': head, 'local_main': git('rev-parse', 'main'),
        'local_origin_main': git('rev-parse', 'origin/main'), 'remote_freshness': 'unknown; no remote check',
        'branch': git('branch', '--show-current'), 'initial_status': '## main...origin/main\n?? docs/prompts/',
        'generated_at': catalog.get('generated_at'), 'schema_version': catalog.get('schema_version'),
        'effective_utc_date': catalog.get('generated_at', '')[:10],
        'snapshot': str(SNAP), 'input_hashes': 'reproduce/input-hashes.json',
        'optional_local_inputs': local, 'dependencies': deps, 'commands': [],
        'host_access_ledger': 'reproduce/host-ledger.json', 'final_integrity': None,
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (OUT / 'progress.md').write_text('# Audit progress\n\nAudit only; no production fixes applied.\n\nPinned baseline and scratch snapshot created. Whole-population inventories, gate baseline and lanes 01–08 remain in progress. No live requests authorized internally until host policy and environment state are established.\n', encoding='utf-8')
    print(json.dumps({'report': str(OUT), 'snapshot': str(SNAP), 'head': head,
                      'generated_at': catalog.get('generated_at'), 'top_level_keys': list(catalog),
                      'products': len(catalog.get('products', [])), 'listings': len(catalog.get('listings', [])),
                      'hashed_files': len(hashes), 'dependencies': deps}, indent=2))

if __name__ == '__main__':
    main()
