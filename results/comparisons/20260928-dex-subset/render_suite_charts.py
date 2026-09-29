"""Render report charts from saved receipts. Matplotlib 3.10.6; no inference."""
import json
import re
import os
from pathlib import Path
from datetime import datetime,timedelta
os.environ.setdefault('MPLCONFIGDIR','/tmp/kojo-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
P=Path(__file__).resolve().parent
rows=json.loads((P/'suite_analysis.json').read_text())['models']
release=json.loads((P/'model_release_dates.json').read_text())['models']
models=['opus5','opus55','sonnet55','astra6','sol56','sol6']
names=dict(zip(models,['Opus 5','Opus 5.5','Sonnet 5.5','Astra 6','Sol 5.6','Sol 6']))
colors=dict(zip(models,['#c3573b','#9258ad','#cf9a22','#167c8a','#4563ae','#41975a']))
names['fable51']='Fable 5.1'
colors['fable51']='#a34c7a'
# Chronological public API release; same-day ties use display name.
models=sorted((r['model'] for r in rows),key=lambda m:(-int(release[m]['date'].replace('-','')),names[m]))
rows=sorted(rows,key=lambda r:models.index(r['model']))
problems=['circuit_eval','database_migration','dynamic_config_service_api']
counts=[8,5,4]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','figure.facecolor':'#faf9f6','axes.facecolor':'#faf9f6','savefig.facecolor':'#faf9f6','svg.fonttype':'none'})
D=P/'charts';D.mkdir(exist_ok=True)
figure_numbers=json.loads((P/'figure_numbers.json').read_text())
def save(fig,name,foot):
    number=figure_numbers[name]
    fig._suptitle.set_text(re.sub(r"^Figure \d+\.",f"Figure {number}.",fig._suptitle.get_text()))
    fig.get_layout_engine().set(rect=(0,.12,1,.87))
    fig.text(.05,.015,foot+'\nModels ordered by public API release date, newest first; same-day ties alphabetically.',fontsize=9,color='#555555')
    for stem in [name,f'figure-{number:02d}-{name}']:
        fig.savefig(D/(stem+'.png'),dpi=180,bbox_inches='tight');fig.savefig(D/(stem+'.svg'),bbox_inches='tight')
    plt.close(fig)
def checks(r,p):return sorted([c for c in r['checkpoints'] if c['problem']==p],key=lambda c:c['checkpoint'])
def cost(r,ps):return sum(a['cost'] or 0 for a in r['attempts'] if a['problem'] in ps)
def fraction(cs):return 100*np.mean([c['passed']/sum(c[s] for s in ['passed','failed','skipped']) for c in cs])
def complete(r,ps):return all(len(checks(r,p))==counts[problems.index(p)] for p in ps)
fig,axs=plt.subplots(1,3,figsize=(15,4.8),layout='constrained')
for ax,p in zip(axs,problems):
 for r in rows:
  cs=checks(r,p);ax.plot([c['checkpoint'] for c in cs],[c['failed'] for c in cs],marker='o',markersize=4,color=colors[r['model']],label=names[r['model']])
 ax.set_title(p,fontfamily='DejaVu Sans Mono',fontsize=11);ax.set_xlabel('Checkpoint');ax.set_ylabel('Failing tests');ax.set_xticks(range(1,counts[problems.index(p)]+1));ax.set_ylim(bottom=-1);ax.grid(axis='y',alpha=.2)
fig.legend(*axs[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,1.09),ncol=6,frameon=False)
fig.suptitle('Figure 3. Failures across successive checkpoint implementations',y=1.16,fontsize=17)
save(fig,'failure-trajectories','Skipped tests are excluded. Missing checkpoints are not zeros. Tests change across checkpoints; one failing test is not necessarily one defect.')
fig,axs=plt.subplots(1,3,figsize=(15,5),layout='constrained')
for ax,p in zip(axs,problems):
 for i,r in enumerate(rows):
  cs=checks(r,p)
  if complete(r,[p]):
   c=cs[-1];ax.barh(i,c['failed'],color=colors[r['model']]);ax.text(c['failed']+.5,i,f"{c['failed']} fail / {c['skipped']} skip",va='center',fontsize=8)
  else:ax.text(.5,i,'Pending final checkpoint',va='center',fontsize=8,color='#777')
 ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.invert_yaxis();ax.set_xlim(0,max([c['failed'] for r in rows for c in checks(r,p)] or [1])*1.6+10);ax.set_title(p,fontfamily='DejaVu Sans Mono',fontsize=11);ax.set_xlabel('Final-checkpoint failing tests');ax.grid(axis='x',alpha=.2)
fig.suptitle('Figure 4. What remains broken at the end of each problem',fontsize=17)
save(fig,'final-failures','Counts describe tests, not independent root causes. Pending models are omitted, not counted as failures.')
fig,axs=plt.subplots(1,3,figsize=(15,5),layout='constrained')
for ax,p in zip(axs,problems):
 for r in rows:
  if not complete(r,[p]):continue
  ax.scatter(cost(r,[p]),checks(r,p)[-1]['failed'],s=75,color=colors[r['model']],label=names[r['model']])
  offset={'astra6':(7,10),'sol6':(7,-16),'sol56':(7,-14),'opus55':(7,8),'sonnet55':(7,-16),'opus5':(-7,10)}.get(r['model'],(7,8))
  if p=='dynamic_config_service_api':ax.annotate(names[r['model']],(cost(r,[p]),checks(r,p)[-1]['failed']),xytext=offset,textcoords='offset points',ha='right' if offset[0]<0 else 'left',fontsize=8,arrowprops={'arrowstyle':'-','color':colors[r['model']],'lw':.6})
 ax.set_title(p,fontfamily='DejaVu Sans Mono',fontsize=11);ax.set_xlabel('Total problem cost · API-equivalent USD');ax.set_ylabel('Final-checkpoint failing tests');ax.margins(x=.15,y=.25);ax.set_xlim(left=0);ax.set_ylim(bottom=-.5);ax.grid(alpha=.2)
fig.suptitle('Figure 5. Cost versus remaining failures',fontsize=17,y=1.16)
fig.legend(*axs[0].get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,1.09),ncol=6,frameon=False)
save(fig,'cost-failures','Includes failed attempts, excludes duplicate resume receipts. Codex database_migration costs are lower bounds. Pending final checkpoints omitted.')
fig,axis=plt.subplots(figsize=(10,5.6),layout='constrained');value_rows=[]
for ax,ps,title in [(axis,problems,'All 17 checkpoints · completed runs')]:
 for r in rows:
  if not complete(r,ps):continue
  cs=[c for c in r['checkpoints'] if c['problem'] in ps];v=fraction(cs)/cost(r,ps);date=datetime.fromisoformat(release[r['model']]['date']);upper=any(a['usage'] is None for a in r['attempts'] if a['problem'] in ps)
  ax.scatter(date,v,s=80,color=colors[r['model']],marker='v' if upper else 'o')
  ax.annotate(names[r['model']]+(' ≤' if upper else ''),(date,v),xytext=((6 if r['model']=='sol56' else -5),8),ha=('left' if r['model']=='sol56' else 'right'),textcoords='offset points',fontsize=9)
  value_rows.append(dict(model=r['model'],scope='suite' if len(ps)==3 else 'common13',release_date=date.date().isoformat(),partial_percent=fraction(cs),cost=cost(r,ps),percentage_points_per_dollar=v,upper_bound=upper))
 ax.set_title(title,fontsize=12);ax.set_ylabel('Partial-pass percentage points / USD');ax.set_xlabel('Public API release date · 2026');ax.xaxis.set_major_locator(mdates.MonthLocator());ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'));ax.set_xlim(datetime(2026,7,1),datetime(2026,10,7));ax.set_ylim(bottom=0);ax.margins(y=.2);ax.grid(alpha=.2)
fig.suptitle('Figure 8. Partial-pass value versus model release date',fontsize=18)
save(fig,'value-release-date','Partial pass = mean checkpoint (passed / collected), including skips in denominator. ▼ / ≤ indicate upper bounds from missing cost. No fitted trend.')
(P/'chart_values.json').write_text(json.dumps(value_rows,indent=2)+'\n')
print('Rendered four PNG/SVG charts and chart_values.json')
