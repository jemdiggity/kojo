"""Recover completed CLI sessions into new, auditable seed runs. No inference."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from kojo.claude_execution import verify_saved_transcript
from kojo.gauntlet import hashes,copy_code
from kojo.external_access import audit_external_sources
from kojo.factory import last_completed_checkpoint
from kojo.execution import save

for tag in ['opus55','sonnet55']:
    old_id=f'20260928-dynamic-config-service-api-{tag}-medium-01'
    new_id=f'20260929-dynamic-config-service-api-{tag}-medium-recovered'
    old=ROOT/'results/runs'/old_id;out=ROOT/'results/runs'/new_id
    data=ROOT/'intermediate/runs'/new_id/'gauntlet'
    original_data=ROOT/'intermediate/runs'/old_id/'gauntlet'
    if out.exists() or data.exists():raise RuntimeError('Recovery ID already used')
    manifest=json.loads((old/'manifest.json').read_text())
    manifest.update(run_id=new_id,recovered_from=old_id,recovery_kind='No-inference verification and source freeze after JSONL framing fix')
    out.mkdir(parents=True);save(out/'manifest.json',manifest)
    provenance=[]
    for cp in [1,2]:
        original=original_data/f'training-build/dynamic_config_service_api/checkpoint_{cp}'
        dest=data/f'training-build/dynamic_config_service_api/checkpoint_{cp}'
        frozen=out/f'build/checkpoint_{cp}'
        dest.mkdir(parents=True);frozen.mkdir(parents=True)
        for p in original.iterdir():
            if p.is_file() and not p.is_symlink():shutil.copy2(p,dest/p.name)
        for name in ['prompt.md','instructions.md','initial-src.json']:
            shutil.copy2(old/f'build/checkpoint_{cp}'/name,frozen/name)
        row=json.loads((dest/'run.json').read_text())
        if row['status']!='complete' or row['returncode']!=0:raise RuntimeError('Incomplete inference')
        raw=(dest/'transcript.jsonl').read_bytes()
        records=[json.loads(line) for line in raw.decode().split('\n') if line.strip()]
        if {r['sessionId'] for r in records if r.get('sessionId')}!={row['session_id']}:raise RuntimeError('Session mismatch')
        verified=verify_saved_transcript(dest,row['session_id'],(frozen/'prompt.md').read_text(),row['model'],row['reasoning'])
        save(dest/'original-run.json',row)
        row.pop('transcript_error',None);row['transcript']=verified;row['recovered_from']=str(original.relative_to(ROOT))
        save(dest/'run.json',row)
        source=old/f'build/checkpoint_{cp}/submission' if cp==1 else original_data/'builder-workspace/src'
        before=hashes(source,exclude_generated=True)
        if cp==1 and before!=json.loads((old/f'build/checkpoint_{cp}/snapshot.json').read_text()):raise RuntimeError('CP1 snapshot drift')
        # CP2 was the terminal session; reject any source modified after the CLI receipt.
        if cp==2:
            cutoff=(original/'run.json').stat().st_mtime
            if any((source/p).stat().st_mtime>cutoff for p in before):raise RuntimeError('Workspace modified after inference receipt')
        copy_code(source,dest/'submission');shutil.copytree(dest/'submission',frozen/'submission')
        if before!=hashes(frozen/'submission') or before!=hashes(source,exclude_generated=True):raise RuntimeError('Source changed during recovery')
        save(frozen/'snapshot.json',before)
        save(dest/'external-access.json',audit_external_sources(dest/'transcript.jsonl'))
        for name in ['run.json','quota.json','verification.json','transcript-verification.json','answer.txt','stock-instructions.md','external-access.json']:
            if (dest/name).exists():shutil.copy2(dest/name,frozen/name)
        provenance.append(dict(checkpoint=cp,source=str(source.relative_to(ROOT)),source_hashes=before,transcript_sha256=hashlib.sha256(raw).hexdigest(),original_receipt=str((original/'run.json').relative_to(ROOT)),original_error=json.loads((original/'run.json').read_text()).get('transcript_error')))
    save(out/'recovery.json',dict(original_run=old_id,checkpoints=provenance,limitation='CP2 frozen after the event from terminal workspace; source mtimes checked against final CLI receipt; environment rebuilt on continuation. Originals preserved.'))
    assert last_completed_checkpoint(out,row['model'],row['reasoning'],4)==2
    print(new_id,'verified through checkpoint 2')
