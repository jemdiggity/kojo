"""Conservative external-source inventory from native CLI evidence, not packet capture."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote

URL = re.compile(r"(?:https?|git|ssh)://[^\s<>\"'`\\]+", re.I)
NETWORK = re.compile(r'\b(?:curl|wget|urlopen|urlretrieve|urllib3|git\s+(?:clone|fetch|pull|ls-remote)|pip(?:\d+(?:\.\d+)*)?\s+(?:install|download|index)|uv\s+(?:add|sync|pip)|npm\s+(?:install|ci)|cargo\s+(?:fetch|install)|go\s+get|requests\.(?:get|post|request)|httpx\.(?:get|post|request)|fetch|socket\.(?:connect|create_connection)|Invoke-WebRequest)\b', re.I)
BENCHMARK = re.compile(r'\b(?:scbench|slop[\s_-]*code(?:[\s_-]*bench)?|scb[\s_-]*(?:problems|bench))\b', re.I)
SEARCH = re.compile(r'search|google|bing|duckduckgo|query|\bq=', re.I)
TASK = re.compile(r'\bcode[\s_-]*search\b', re.I)
SOLUTION = re.compile(r'solution|answer|reference[\s_-]*implementation|test_checkpoint|checkpoint_[1-5]', re.I)
PACKAGE = re.compile(r'\b(?:pip(?:\d+(?:\.\d+)*)?\s+(?:install|download|index)|uv\s+(?:add|sync|pip)|npm\s+(?:install|ci)|cargo\s+(?:fetch|install)|go\s+get)\b', re.I)
CALLS = {'custom_tool_call', 'function_call', 'web_search_call'}
OUTPUTS = {'custom_tool_call_output', 'function_call_output', 'web_search_call_output'}


def flatten(value, depth=0):
    """Decode nested JSON tool output while retaining code/command strings."""
    if depth > 8:
        return [str(value)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in flatten(v, depth+1)]
    if isinstance(value, list):
        return [s for v in value for s in flatten(v, depth+1)]
    if isinstance(value, str):
        try:
            parsed=json.loads(value)
        except (ValueError, TypeError):
            return [value]
        if isinstance(parsed,(dict,list)):
            return flatten(parsed,depth+1)
        return [value]
    return []


def redact_url(url):
    url=url.rstrip('.,);]}')
    try:
        parts=urlsplit(url)
        host=parts.hostname or ''
        if parts.port:host+=':'+str(parts.port)
        query=[(k,'[redacted]' if re.search('token|secret|key|auth|signature|credential|password',k,re.I) else v) for k,v in parse_qsl(parts.query,keep_blank_values=True)]
        return urlunsplit((parts.scheme,host,parts.path,urlencode(query),''))
    except ValueError:
        return '[unparseable URL]'


def urls(text):
    return sorted({redact_url(u) for u in URL.findall(text)})


def redacted_excerpt(text):
    text=URL.sub(lambda m:redact_url(m.group()),text)
    text=re.sub(r'(?i)(authorization\s*[:=]\s*["\']?bearer\s+)\S+',r'\1[redacted]',text)
    text=re.sub(r'(?i)((?:token|password|api_key|secret)\s*[=:]\s*)[^\s,;]+',r'\1[redacted]',text)
    return text[:1200]


def audit_external_sources(path):
    path=Path(path)
    if not path.exists():
        return {'status':'incomplete_evidence','review_suggested':True,'events':[], 'limitations':['Native transcript is missing.']}
    rows=[];errors=[]
    for number,line in enumerate(path.read_text().split("\n"),1):
        if not line.strip():continue
        try:rows.append((number,json.loads(line)))
        except ValueError:errors.append(number)
    calls=[];outputs={}
    for number,row in rows:
        if row.get('type') in {'assistant','user'}:
            content=row.get('message',{}).get('content',[])
            if isinstance(content,list):
                for block in content:
                    if block.get('type')=='tool_use':
                        calls.append((number,{'type':'function_call','call_id':block['id'],
                                              'name':block['name'],'input':block.get('input',{})}))
                    elif block.get('type')=='tool_result':
                        outputs.setdefault(block['tool_use_id'],[]).append((number,{'output':block.get('content')}))
            continue
        if row.get('type')!='response_item':continue
        p=row.get('payload',{});kind=p.get('type');identity=p.get('call_id',p.get('id'))
        if kind in CALLS:calls.append((number,p))
        elif kind in OUTPUTS:outputs.setdefault(identity,[]).append((number,p))
    events=[];flags=[];unclassified=[]
    for number,p in calls:
        identity=p.get('call_id',p.get('id'));name=p.get('name',p.get('type',''))
        action='\n'.join(flatten(p.get('input',p.get('arguments',p.get('action',{})))))
        related=outputs.get(identity,[])
        output='\n'.join(s for _,item in related for s in flatten(item.get('output',item)))
        decoded=unquote(action)
        web_call=bool(re.search(r'web__run|web\.run|web_search|search_query',name+' '+action))
        is_search='web_search' in name or 'search_query' in action or bool(SEARCH.search(decoded) and urls(action))
        # Ignore ordinary local edits, fixtures and system/user instructions, even if they contain URLs.
        if not (NETWORK.search(action) or is_search or web_call or (re.search('browser|navigate|open_url',name) and urls(action))):continue
        requested=urls(action);observed=urls(output)
        suspicion=[]
        if BENCHMARK.search(decoded):suspicion.append('benchmark_targeted_access_attempt')
        if any(TASK.search(unquote(u)) and (SEARCH.search(u) or SOLUTION.search(u)) for u in requested):
            suspicion.append('task_specific_external_search_or_solution_target')
        if is_search and TASK.search(decoded) and SOLUTION.search(decoded):suspicion.append('task_solution_search')
        if BENCHMARK.search(unquote(output)):suspicion.append('benchmark_reference_in_tool_output')
        if any(TASK.search(unquote(u)) and SOLUTION.search(unquote(u)) for u in observed):suspicion.append('task_solution_reference_in_output')
        if re.search('truncat',output,re.I):unclassified.append({'record':number,'reason':'Tool output may be truncated.'})
        if not related and p.get('type')!='web_search_call':unclassified.append({'record':number,'reason':'No matching tool output recorded.'})
        event={'record':number,'output_records':[n for n,_ in related],'call_id':identity,'tool':name,
               'kind':'package_operation' if PACKAGE.search(action) else ('search' if is_search else 'network_capable_operation'),
               'requested_urls':requested,'urls_in_output':observed,
               'action_excerpt':redacted_excerpt(action),'output_excerpt':redacted_excerpt(output),
               'action_sha256':hashlib.sha256(action.encode()).hexdigest(),
               'flags':sorted(set(suspicion)),
               'evidence':'Recorded tool action/output; URLs may be attempted targets or references, not confirmed individual fetches.'}
        events.append(event)
        if suspicion:flags.append(number)
    if not calls:unclassified.append({'reason':'No tool actions observed in the supplied transcript.'})
    status='suspected_benchmark_access' if flags else ('incomplete_evidence' if errors else 'no_benchmark_access_observed')
    return {'schema_version':2,'status':status,'review_suggested':bool(flags or errors),
            'transcript_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'records':len(rows),
            'tool_calls':len(calls),'events':events,'flagged_records':flags,'parse_or_coverage_errors':errors,
            'coverage_notes':unclassified,
            'limitations':['Heuristic transcript audit, not a complete egress log or proof of no contamination.',
                           'Silent/encoded/generated scripts, redirects, package transitive fetches and truncated output may hide destinations.',
                           'Report only: no automatic stop, exclusion or validity verdict. The user judges whether external sources contaminated the experiment.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('transcript',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=audit_external_sources(args.transcript)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'events':len(report['events']),'review_suggested':report['review_suggested']}))
    # Findings are data, not a process failure or experiment validity decision.


if __name__=='__main__':main()
