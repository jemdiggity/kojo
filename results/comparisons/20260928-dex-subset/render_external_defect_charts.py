"""Published Horthy counts alongside local final-test counts; no imputed paper data."""
import json
import re
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/kojo-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
P=Path(__file__).resolve().parent
external=json.loads((P/'external_defect_sources.json').read_text())
suite=json.loads((P/'suite_analysis.json').read_text())['models']
release=json.loads((P/'model_release_dates.json').read_text())['models']
problems=external['scope'];counts=[8,5,4]
names={'opus5':'Opus 5','opus55':'Opus 5.5','sonnet55':'Sonnet 5.5','astra6':'Astra 6','sol56':'Sol 5.6','sol6':'Sol 6','fable51':'Fable 5.1'}
rows=[]
for r in suite:
    checks=[[c for c in r['checkpoints'] if c['problem']==p] for p in problems]
    if any(len(cs)!=n for cs,n in zip(checks,counts)):continue
    final=[max(cs,key=lambda c:c['checkpoint']) for cs in checks]
    rows.append(dict(model=r['model'],name=names[r['model']],study='Kojo',release_date=release[r['model']]['date'],failed=[c['failed'] for c in final],skipped=[c['skipped'] for c in final]))
for r in external['horthy']['rows']:
    assert sum(r['failed'])==r['published_total']
    rows.append(dict(model=r['model'],name=r['name'],study='Dexter',release_date=r['release_date'],failed=r['failed'],skipped=None))
rows.sort(key=lambda r:(-int(r['release_date'].replace('-','')),r['name'],r['study']))
for r in rows:r['total_failed']=sum(r['failed'])
(P/'external_defect_values.json').write_text(json.dumps({'scope':problems,'rows':rows,'paper_counts_available':False},indent=2)+'\n')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'#faf9f6','axes.facecolor':'#faf9f6','savefig.facecolor':'#faf9f6','svg.fonttype':'none'})
labels=[r['name']+' · '+r['study'] for r in rows];y=np.arange(len(rows));D=P/'charts'
foot=('Final checkpoint only; no sum across checkpoint copies. Counts are failing tests, not distinct root causes. Lower is better.\n'
      'Dexter: published chart labels; test counts/pin/effort/skips unavailable. Kojo: skips excluded and disclosed. Cross-study descriptive comparison.\n'
      'Newest release first; same-day ties alphabetical. Original paper: matching counts unavailable, not zero. Fable omitted until its suite completes.')
figure_numbers=json.loads((P/'figure_numbers.json').read_text())
def save(fig,stem):
    number=figure_numbers[stem]
    fig._suptitle.set_text(re.sub(r"^Figure \d+\.",f"Figure {number}.",fig._suptitle.get_text()))
    fig.tight_layout(rect=(0,.16,1,.91));fig.text(.02,.025,foot,fontsize=9,color='#555')
    for target in [stem,f'figure-{number:02d}-{stem}']:
        for ext in ['png','svg']:fig.savefig(D/(target+'.'+ext),dpi=180,bbox_inches='tight')
    plt.close(fig)
fig,axs=plt.subplots(1,3,figsize=(16,7.8),sharey=True)
for j,(ax,p) in enumerate(zip(axs,problems)):
    vals=[r['failed'][j] for r in rows]
    bars=ax.barh(y,vals,color=['#377e93' if r['study']=='Kojo' else '#b48237' for r in rows])
    for i,(bar,r,v) in enumerate(zip(bars,rows,vals)):
        if r['study']=='Dexter':bar.set_hatch('//')
        extra=f" / {r['skipped'][j]} skip" if r['skipped'] is not None and r['skipped'][j] else ''
        ax.text(v+.4,i,str(v)+extra,va='center',fontsize=9)
    ax.set_yticks(y,labels);ax.set_xlim(0,max(vals)*1.35+8);ax.set_title(p,fontfamily='DejaVu Sans Mono',fontsize=11);ax.set_xlabel('Final failing tests');ax.grid(axis='x',alpha=.2)
axs[0].invert_yaxis();fig.suptitle('Figure 6. Tests still failing at the end of each problem',fontsize=17)
save(fig,'external-final-failures')
fig,ax=plt.subplots(figsize=(13,8));left=np.zeros(len(rows));palette=['#317b90','#ce9543','#8b66ac']
for j,p in enumerate(problems):
    vals=np.array([r['failed'][j] for r in rows]);bars=ax.barh(y,vals,left=left,color=palette[j],label=p)
    for i,(bar,r,v) in enumerate(zip(bars,rows,vals)):
        if r['study']=='Dexter':bar.set_hatch('//')
        if v>=4:ax.text(left[i]+v/2,i,str(v),ha='center',va='center',fontsize=9,color='white')
    left+=vals
for i,(r,v) in enumerate(zip(rows,left)):
    extra=f" + {sum(r['skipped'])} skipped" if r['skipped'] is not None and sum(r['skipped']) else ''
    ax.text(v+.7,i,str(int(v))+extra,va='center',fontsize=9)
ax.set_yticks(y,labels);ax.invert_yaxis();ax.set_xlim(0,max(left)*1.3+8);ax.grid(axis='x',alpha=.2);ax.set_xlabel('Sum of final failing tests across the same three problems')
fig.legend(handles=[Patch(facecolor=c,label=p) for c,p in zip(palette,problems)],loc='upper center',bbox_to_anchor=(.57,.945),ncol=3,frameon=False,prop={'family':'DejaVu Sans Mono','size':9})
fig.suptitle('Figure 7. Total final failing tests per model and study',fontsize=17)
save(fig,'external-total-failures')
lines=['# External defect-count comparison','',
'Figures 6–7 compare our final-checkpoint failing tests with [Dexter’s published chart]('+external['horthy']['source']+'). His printed values are transcribed, not reconstructed from pixels. Exact source commit/blob and extraction notes are saved in `external_defect_sources.json`.','',
'“All tasks” here means the same three named problems. Totals sum their final snapshots once; repeated failures across earlier checkpoints are not added. The two Opus 5 rows are separate studies. Raw counts do not adjust for different test collections, harnesses, or effort. Dexter’s skipped-test counts and test-level records were not located. Our skipped tests remain separate, not counted as passes or failing tests.','',
'| Model | Study | `circuit_eval` | `database_migration` | `dynamic_config_service_api` | Total failing | Total skipped |',
'|---|---|---:|---:|---:|---:|---:|']
for r in rows:lines.append('| '+' | '.join([r['name'],r['study'],*[str(x) for x in r['failed']],str(r['total_failed']),str(sum(r['skipped'])) if r['skipped'] is not None else 'Not reported'])+' |')
for n,stem in [(6,'external-final-failures'),(7,'external-total-failures')]:lines+=['',f'![Figure {n}]({D}/figure-{n:02d}-{stem}.png)','']
lines+=['## Original paper: count data unavailable','',
'The [original paper, v1 Table 1](https://arxiv.org/html/2603.24755v1#S4.T1), reports strict checkpoint rates over 20 problems. These cannot be converted into final failing-test counts for our three problems or the full benchmark. The current public leaderboard also provides aggregate rates rather than the required test counts. The two linked Zenodo manifests contain PDFs, not raw grading records. Missing values below are not zeros.','',
'| Original-paper model | Published strict checkpoint rate | Final failing-test counts |','|---|---:|---|']
for r in external['paper_v1']['rows']:lines.append(f"| {r['model']} | {r['strict_percent']:.1f}% | Unavailable |")
lines+=['','Paper models are therefore documented but not given fabricated defect bars. Matching per-checkpoint grading records would let us add the shared subset and a separately scoped full-benchmark total.','',
'## Reproduction','',
'`intermediate/reporting-venv/bin/python results/comparisons/20260928-dex-subset/render_external_defect_charts.py`','',
'Uses saved suite measurements and the transcribed source manifest; no inference or network calls. Derived chart values are in `external_defect_values.json`.']
(P/'EXTERNAL_DEFECT_COMPARISON.md').write_text('\n'.join(lines)+'\n')
print('Rendered Figures 6–7 and external comparison report.')
