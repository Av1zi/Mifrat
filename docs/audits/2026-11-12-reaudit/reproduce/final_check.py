"""Final documentation-only integrity and reconciliation; no network."""
import collections as co
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/audits/2026-11-12-reaudit'
RUN=Path(__file__).resolve().parent

def jl(path):return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
def sha(path):return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8').strip()

def main():
    fs=jl(OUT/'findings.jsonl');cs=jl(OUT/'candidates.jsonl');gaps=jl(OUT/'spec-gaps.jsonl')
    coverage=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'))
    assert len(fs)==83 and len({f['finding_id'] for f in fs})==len(fs)
    assert len({c['candidate_id'] for c in cs})==len(cs)
    assert len({(g['product_id'],g['field']) for g in gaps})==len(gaps)==25101
    assert len(cs)==coverage['candidate_count']
    assert co.Counter(c['disposition'] for c in cs)==coverage['candidate_dispositions']
    assert len({pid for f in fs for pid in f['product_ids']})==coverage['confirmed_unique_products']==42
    assert len({k for f in fs for k in f['listing_keys']})==coverage['confirmed_unique_listings']==50
    assert all(f['review']['outcome']!='pending' for f in fs)
    assert all(f['evidence'] for f in fs)
    required=['README.md','manifest.json','coverage.json','findings.jsonl','spec-gaps.jsonl','rejected.jsonl','previous-findings.md','progress.md']
    assert all((OUT/name).exists() for name in required)
    assert len(list(OUT.glob('0?-*.md')))==8
    manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    finalhashes=json.loads((OUT/'reproduce/worktree-final-hashes.json').read_text(encoding='utf-8'))
    changed=[rel for rel,hashvalue in finalhashes.items() if not (ROOT/rel).exists() or sha(ROOT/rel)!=hashvalue]
    assert changed==['decisions.md'], changed
    old=(RUN/'snapshot/decisions.md').read_text(encoding='utf-8')
    now=(ROOT/'decisions.md').read_text(encoding='utf-8')
    assert now.replace('- Full-catalog re-audit (2026-11-12): audit only, pinned main `e7cd95223d684cbbdfe72cc2ca76ef568451e963` / catalog `2026-11-12T12:22:28.077467+00:00`; partial findings/coverage/progress in `docs/audits/2026-11-12-reaudit/`; no production fixes, data changes, git mutations, deployment or issues.\n','')==old
    manifest['final_integrity'].update({'utc_final':dt.datetime.now(dt.timezone.utc).isoformat(),
        'final_status':git('status','--short','--branch'), 'final_head':git('rev-parse','HEAD'),
        'changes_since_checkpoint':changed,'permitted_decisions_record_verified':True,
        'final_decisions_sha256':sha(ROOT/'decisions.md'), 'all_instance_counts_reconciled':True})
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'reproduce/recent-commits.log').write_text(git('log','-30','--format=%H %aI %s')+'\n',encoding='utf-8')
    summary={'status':'partial','instances':len(fs),'products':42,'listing_keys':50,'candidate_records':len(cs),'unresolved':coverage['candidate_unresolved_count'],'null_field_rows':len(gaps),'integrity':manifest['final_integrity']}
    (OUT/'reproduce/reconciliation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
