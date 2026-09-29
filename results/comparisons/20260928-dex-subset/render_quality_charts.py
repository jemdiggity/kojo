"""Horthy-style summary plots and paper-style quality trajectories, from frozen data."""
import json,runpy
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
base=runpy.run_path(str(P/'render_suite_charts.py'))
plt=base['plt'];original_save=base['save'];names=base['names'];colors=base['colors'];models=base['models'];problems=base['problems'];counts=base['counts'];rows=base['rows']
from matplotlib.ticker import FuncFormatter
def save(fig,name,foot):
    for ax in fig.axes:
        for axis in [ax.xaxis,ax.yaxis]:
            if max((abs(v) for v in axis.get_ticklocs()),default=0)>=1000:
                axis.set_major_formatter(FuncFormatter(lambda x,p:f'{x/1e6:.1f}M' if abs(x)>=1e6 else f'{x/1000:g}K' if abs(x)>=1000 else f'{x:g}'))
    original_save(fig,name,foot)
quality=json.loads((P/'quality-suite/quality.json').read_text())['rows']
by={(next(m for m in models if '-'+m+'-medium-' in r['run_id']),r['problem'],r['checkpoint']):r for r in quality}
def metrics(m,p,cp,variant='entrypoint-normalized'):return by[m,p,cp]['variants'][variant]['metrics']
def total(m,k):return sum(metrics(m,p,n)[k] for p,n in zip(problems,counts))
def title(ax,p):ax.set_title(p,fontfamily='DejaVu Sans Mono',fontsize=11)
def legend(fig,ax):fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.5,1.09),ncol=len(models),frameon=False)
fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
sortedrows=rows
y=np.arange(len(models));rates=[100*r['strict']/17 for r in sortedrows]
ax.barh(y,rates,color=[colors[r['model']] for r in sortedrows]);ax.set_yticks(y,[names[r['model']] for r in sortedrows]);ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xlabel('Strict checkpoint pass rate (%)');ax.grid(axis='x',alpha=.2)
for i,(r,v) in enumerate(zip(sortedrows,rates)):ax.text(v+1,i,f"{r['strict']}/17 · {v:.1f}%",va='center')
fig.suptitle('Figure 1. How many checkpoints passed every required test?',fontsize=17)
save(fig,'strict-pass-bars','All three problems; one run per model. No paper-wide reference bars: those use different datasets and protocols.')
fig,axs=plt.subplots(1,3,figsize=(15,5),layout='constrained',gridspec_kw={'width_ratios':[8,5,4]})
from matplotlib.colors import ListedColormap
for ax,p,n in zip(axs,problems,counts):
 data=np.array([[metrics(m,p,c)['total_loc'] for c in range(1,n+1)] for m in models]) # dimensions only
 for i,m in enumerate(models):
  r=next(r for r in rows if r['model']==m)
  for c in range(1,n+1):
   v=next(x for x in r['checkpoints'] if x['problem']==p and x['checkpoint']==c);data[i,c-1]=v['strict']
 ax.imshow(data,cmap=ListedColormap(['#f3d6c5','#88baa5']),vmin=0,vmax=1,aspect='auto')
 for i,m in enumerate(models):
  r=next(r for r in rows if r['model']==m)
  for c in range(1,n+1):
   v=next(x for x in r['checkpoints'] if x['problem']==p and x['checkpoint']==c);ax.text(c-1,i,("100%" if v["strict"] else f"{100*v['passed']/sum(v[s] for s in ['passed','failed','skipped']):.1f}%"),ha='center',va='center',fontsize=9)
 ax.set_xticks(range(n),range(1,n+1));ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.set_xlabel('Checkpoint');title(ax,p)
fig.suptitle('Figure 2. Every checkpoint at a glance',fontsize=17)
save(fig,'checkpoint-grid','Green: all collected tests passed. Peach: not a strict pass. Text: passed/collected %, including skips. Not an independent-task heatmap.')
fig,axs=plt.subplots(1,2,figsize=(13,5),layout='constrained')
for ax,k,lab in [(axs[0],'total_loc','Final Python source lines'),(axs[1],'total_functions','Functions and methods in final submissions')]:
 vals=[total(m,k) for m in models];ax.barh(range(len(models)),vals,color=[colors[m] for m in models]);ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.invert_yaxis();ax.set_xlim(0,max(vals)*1.25);ax.set_xlabel(lab);ax.grid(axis='x',alpha=.2)
 for i,v in enumerate(vals):ax.text(v+max(vals)*.015,i,f'{v/1000:.1f}K' if v>=1000 else str(v),va='center')
fig.suptitle('Figure 9. How much code did each model leave behind?',fontsize=17)
save(fig,'code-volume','Sum of the three final snapshots, not summed checkpoint copies or cumulative lines written. Includes agent-written tests; Python only.')
fig,ax=plt.subplots(figsize=(11,5),layout='constrained')
other=np.array([total(m,'other_sloc') for m in models]);tests=np.array([total(m,'test_sloc') for m in models]);ax.barh(range(len(models)),other,color='#477e95',label='Other Python');ax.barh(range(len(models)),tests,left=other,color='#dfa44a',label='Test-named Python');ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.invert_yaxis();ax.set_xlim(0,max(other+tests)*1.28);ax.set_xlabel('Python source lines · sum of final snapshots');ax.legend(loc='lower right',frameon=False)
for i,(a,b) in enumerate(zip(other,tests)):ax.text(a+b+max(other+tests)*.015,i,f'{100*b/(a+b):.0f}% tests',va='center')
fig.suptitle('Figure 10. How much of that code is tests?',fontsize=17)
save(fig,'test-code-split','Filename/directory heuristic; “other” may include utilities or vendored code. SLOC uses the pinned analyzer, not physical line count.')
fig,axs=plt.subplots(2,3,figsize=(15,8),layout='constrained')
for j,p in enumerate(problems):
 for ax,k,label in [(axs[0,j],'cc_mean','Mean cyclomatic complexity'),(axs[1,j],'clone_fraction','Duplicated SLOC (%)')]:
  for m in models:
   vals=[metrics(m,p,c)[k]*(100 if k=='clone_fraction' else 1) for c in range(1,counts[j]+1)];ax.plot(range(1,counts[j]+1),vals,marker='o',ms=3,color=colors[m],label=names[m])
  title(ax,p);ax.set_xlabel('Checkpoint');ax.set_ylabel(label);ax.grid(alpha=.2)
legend(fig,axs[0,0]);fig.suptitle('Figure 11. Complexity and duplication as requirements grow',y=1.16,fontsize=17)
save(fig,'complexity-duplication','All discovered Python, including tests; duplicate lines are structurally detected. These proxies do not establish maintainability.')
fig,axs=plt.subplots(1,3,figsize=(15,5),layout='constrained')
for ax,p,n in zip(axs,problems,counts):
 for m in models:
  v=metrics(m,p,n);ax.scatter(v['total_functions'],v['cc_mean'],s=65,color=colors[m],label=names[m])
 title(ax,p);ax.set_xlabel('Callables in final snapshot');ax.set_ylabel('Mean cyclomatic complexity');ax.grid(alpha=.2);ax.set_xlim(left=0);ax.set_ylim(bottom=0)
legend(fig,axs[0]);fig.suptitle('Figure 12. Many small functions or fewer complex ones?',y=1.16,fontsize=17)
save(fig,'functions-complexity','One point per model/problem final snapshot. Includes tests. A lower mean can reflect many small tests rather than simpler production code.')
fig,ax=plt.subplots(figsize=(11,5),layout='constrained');vals=[100*total(m,'single_use_functions')/total(m,'total_functions') for m in models]
ax.barh(range(len(models)),vals,color=[colors[m] for m in models]);ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xlabel('Callables with exactly one statically detected use (%)')
for i,v in enumerate(vals):ax.text(v+1,i,f'{v:.1f}%',va='center')
fig.suptitle('Figure 13. Functions referenced once',fontsize=17)
save(fig,'single-use-functions','Pooled final-snapshot callable counts. Static references are not runtime call counts; frameworks, dynamic dispatch and tests affect this proxy.')
# Paper-style normalized progress: interpolate each of 3 trajectories, then equal-weight mean.
fig,axs=plt.subplots(2,2,figsize=(12,7),layout='constrained');grid=np.linspace(0,1,5);aggregates=[]
for i,(group,ms) in enumerate([('Anthropic',[m for m in models if m in {'opus5','opus55','sonnet55','fable51'}]),('OpenAI',[m for m in models if m in {'astra6','sol56','sol6'}])]):
 for j,k in enumerate(['erosion','verbosity']):
  ax=axs[i,j]
  for m in ms:
   vals=np.array([np.interp(grid,np.linspace(0,1,n),[metrics(m,p,c)[k] for c in range(1,n+1)]) for p,n in zip(problems,counts)]);mean=vals.mean(axis=0)
   ax.plot(grid,mean,marker='o',color=colors[m],label=names[m]);aggregates.append(dict(model=m,metric=k,values=mean.tolist()))
  ax.set_title(group+' · '+k.capitalize());ax.set_xticks(grid,['Start','25%','50%','75%','Final']);ax.set_ylabel(k.capitalize());ax.set_ylim(0,1);ax.grid(alpha=.2);ax.legend(frameon=False,fontsize=9)
fig.suptitle('Figure 14. Quality across normalized problem progress',fontsize=17)
save(fig,'quality-progress','Inspired by paper Figure 3 (v2). Linear interpolation to five positions; equal weight per problem. Three trajectories/model; no confidence intervals.')
fig,axs=plt.subplots(2,3,figsize=(15,8),layout='constrained')
for j,p in enumerate(problems):
 for i,k in enumerate(['erosion','verbosity']):
  ax=axs[i,j]
  for m in models:ax.plot(range(1,counts[j]+1),[metrics(m,p,c)[k] for c in range(1,counts[j]+1)],marker='o',ms=3,label=names[m],color=colors[m])
  title(ax,p);ax.set_xlabel('Checkpoint');ax.set_ylabel(k.capitalize());ax.set_ylim(0,1);ax.grid(alpha=.2)
legend(fig,axs[0,0]);fig.suptitle('Figure 15. The quality trajectory of each problem',y=1.16,fontsize=17)
save(fig,'quality-by-problem','Lower erosion/verbosity is better according to these proxies. Pinned scb-check 0.1.3, including its trivial-wrapper contribution to verbosity.')
fig,axs=plt.subplots(1,2,figsize=(13,5),layout='constrained')
for ax,k in zip(axs,['erosion','verbosity']):
 for i,m in enumerate(models):
  allv=np.mean([metrics(m,p,n)[k] for p,n in zip(problems,counts)]);prod=np.mean([metrics(m,p,n,'non-test-python')[k] for p,n in zip(problems,counts)])
  ax.plot([allv,prod],[i,i],color=colors[m],lw=3);ax.scatter([allv],[i],color=colors[m],marker='o',s=55);ax.scatter([prod],[i],color=colors[m],marker='s',s=55)
 ax.set_yticks(range(len(models)),[names[m] for m in models]);ax.invert_yaxis();ax.set_xlim(0,1);ax.set_xlabel('Mean final '+k+' (lower is better)');ax.grid(axis='x',alpha=.2)
fig.suptitle('Figure 16. Quality scores with and without generated tests',fontsize=17)
save(fig,'quality-test-sensitivity','● All discovered Python; ■ excludes test-named files and recomputes metrics. Equal mean of three final snapshots. Heuristic classification.')
# Relative change panel in Horthy's style; zero baselines are not ratios.
keys=['cc_mean','cc_max','clone_fraction','erosion','verbosity','single_use_fraction'];labels=['Mean CC','Maximum CC','Duplicated fraction','Erosion','Verbosity','Single-use fraction'];deltas={k:[] for k in keys}
for k in keys:
 for m in models:
  a=metrics(m,'circuit_eval',1)[k];b=metrics(m,'circuit_eval',8)[k];deltas[k].append(None if not a else 100*(b/a-1))
idx=sorted(range(len(keys)),key=lambda i:max(x for x in deltas[keys[i]] if x is not None)-min(x for x in deltas[keys[i]] if x is not None),reverse=True)
fig,ax=plt.subplots(figsize=(12,6),layout='constrained')
for j,m in enumerate(models):ax.scatter([deltas[keys[i]][j] for i in idx],np.arange(6)+(j-(len(models)-1)/2)*.07,color=colors[m],label=names[m],s=45)
ax.set_yticks(range(6),[labels[i] for i in idx]);ax.invert_yaxis();ax.axvline(0,color='#888',lw=1);ax.grid(axis='x',alpha=.2);ax.set_xlabel('Change from checkpoint 1 to checkpoint 8 (%)');ax.legend(frameon=False,ncol=3,loc='lower right')
fig.suptitle('Figure 17. Relative metric growth in circuit_eval',fontfamily='DejaVu Sans Mono',fontsize=14)
save(fig,'metric-spread','Change = 100 × (CP8 / CP1 − 1), not the metric itself. Zero-baseline ratios omitted (Opus 5.5/Sonnet 5.5 duplication). Includes generated tests.')
(P/'quality-suite/chart_aggregates.json').write_text(json.dumps({'model_order':models,'normalized_progress':aggregates,'circuit_relative_changes':deltas},indent=2)+'\n')
print('Rendered Figures 5–15.')
