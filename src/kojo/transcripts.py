"""Retain and verify native Codex session logs for exactly one known CLI thread."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def inspect_transcript(path, thread_id, instructions, prompt, guidance):
    rows = records(path)
    metas = [r['payload'] for r in rows if r.get('type') == 'session_meta']
    if len(metas) != 1 or metas[0].get('id') != thread_id:
        raise RuntimeError('Session log identity mismatch')
    base = metas[0].get('base_instructions', {})
    base = base.get('text', '') if isinstance(base, dict) else base
    messages = [r['payload'] for r in rows if r.get('type') == 'response_item' and r.get('payload', {}).get('type') == 'message']
    text = lambda m: '\n'.join(c.get('text', '') for c in m.get('content', []) if isinstance(c, dict))
    verified = {
        'thread_id': thread_id,
        'base_instructions_exact': base.strip() == instructions.strip(),
        'guidance_in_session_base_instructions': not guidance or guidance.strip() in base,
        'exact_user_prompt_in_session': any(m.get('role') == 'user' and text(m) == prompt for m in messages),
        'assistant_messages': sum(m.get('role') == 'assistant' for m in messages),
        'response_items': sum(r.get('type') == 'response_item' for r in rows),
        'records': len(rows),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'evidence': 'Native CLI session log, not an independent provider receipt. Retains what the CLI records; does not guarantee untruncated outputs or every wire request.',
    }
    if not all(verified[k] for k in ['base_instructions_exact', 'guidance_in_session_base_instructions', 'exact_user_prompt_in_session']):
        raise RuntimeError('Native session log does not contain the expected instructions and prompt')
    return verified


def capture(run, instructions, prompt, guidance='', *, audit=False):
    events = records(run / ('audit-events.jsonl' if audit else 'events.jsonl'))
    ids = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
    if len(ids) != 1 or not re.fullmatch(r'[0-9a-f-]{36}', ids[0]):
        raise RuntimeError('Exactly one valid thread ID required to capture transcript')
    codex_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    matches = list((codex_home / 'sessions').glob(f'*/*/*/*{ids[0]}*.jsonl'))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one native session log; found {len(matches)}')
    prefix = 'audit-' if audit else ''
    dest = run / (prefix + 'transcript.jsonl')
    shutil.copyfile(matches[0], dest)
    verified = inspect_transcript(dest, ids[0], instructions, prompt, guidance)
    verified['offline_audit'] = audit
    (run / (prefix + 'transcript-verification.json')).write_text(json.dumps(verified, indent=2) + '\n')
    lines = ['# Native Codex session transcript', '', verified['evidence'], '',
             'OFFLINE AUDIT: no inference.' if audit else 'Live CLI session record.', '']
    for row in records(dest):
        # Render all recorded payloads, without inventing missing messages or tool output.
        lines += ['## ' + row.get('type', 'record'), '', '````json', json.dumps(row.get('payload', row), ensure_ascii=False, indent=2), '````', '']
    (run / (prefix + 'transcript.md')).write_text('\n'.join(lines))
    return verified
