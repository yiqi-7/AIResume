import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ArrowLeft, ArrowRight, Check, ChevronLeft, ChevronRight, Download, FileText, LoaderCircle, Settings2, Upload, X } from 'lucide-react';
import ModelDialog from './ModelDialog';
import ResumePreview from './ResumePreview';
import { ApiError, download, modelHeaders, request } from '../lib/api';
import { modelErrorMessage } from '../lib/model-errors';
import { applyDemo, demoSession } from '../lib/demo';
import { customAPIStorageKey, loadModelSettings, modelRequest, modelStorageKey } from '../lib/model-settings';
import type { Configuration, Dimension, ModelSettings, Resume, Session } from '../lib/types';

const dimensionNames:Record<Dimension,string>={structure:'结构与阅读',content:'经历表达',relevance:'岗位相关'};
const priorities={P0:'关键缺口',P1:'表达不清',P2:'强化呈现',P3:'细节打磨'};
const defaults:ModelSettings={provider:'station',model:'',key:''};
const isRunning=(s:Session|null)=>!!s&&['analyzing','answering'].includes(s.state);
const isReviewable=(s:Session|null)=>!!s&&['ready','partial'].includes(s.state);

export default function Workspace(){
  const [session,setSession]=useState<Session|null>(null);
  const [config,setConfig]=useState<Configuration|null>(null);
  const [model,setModel]=useState<ModelSettings>(defaults);
  const [settingsOpen,setSettingsOpen]=useState(false);
  const [demo,setDemo]=useState(false);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [file,setFile]=useState<File|null>(null);
  const [jd,setJD]=useState('');
  const [consent,setConsent]=useState(false);
  const [active,setActive]=useState('');
  const [filter,setFilter]=useState('all');
  const [tab,setTab]=useState<'review'|'preview'>('review');
  const [previewZoom,setPreviewZoom]=useState<'fit'|'actual'>('fit');
  const [preview,setPreview]=useState<Resume|null>(null);
  const [confirm,setConfirm]=useState<'end'|'export'|null>(null);
  const [draft,setDraft]=useState('');
  const [fact,setFact]=useState('');
  const [sectionId,setSectionId]=useState('');
  const [factsConfirmed,setFactsConfirmed]=useState(false);
  const fileInput=useRef<HTMLInputElement>(null);
  const lastTouch=useRef(0);
  const visible=session?.suggestions.filter(s=>filter==='all'||s.decision===filter)??[];
  const item=visible.find(s=>s.id===active)??visible[0];
  const running=isRunning(session);
  const reviewable=isReviewable(session);

  useEffect(()=>{
    let cancelled=false;
    const isDemo=new URLSearchParams(location.search).get('demo')==='1';
    setDemo(isDemo);
    setModel(loadModelSettings());
    if(isDemo){setSession(demoSession());setLoading(false);return;}
    Promise.allSettled([request<Configuration>('/api/config'),request<{session:Session|null}>('/api/session')]).then(results=>{
      if(cancelled)return;
      if(results[0].status==='fulfilled')setConfig(results[0].value);
      if(results[1].status==='fulfilled')setSession(results[1].value.session);
      if(results.some(r=>r.status==='rejected'))setError('暂时无法连接后端，请确认服务已启动后刷新。你仍可以查看虚构示例。');
      setLoading(false);
    });
    return()=>{cancelled=true;};
  },[]);

  useEffect(()=>{
    const sync=(event:StorageEvent)=>{if(event.key===modelStorageKey||event.key===customAPIStorageKey||event.key===null)setModel(loadModelSettings());};
    window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync);
  },[]);

  useEffect(()=>{
    if(!session||!running||demo)return;
    let stopped=false,timer:ReturnType<typeof setTimeout>;
    let failures=0;
    const poll=async()=>{
      try{
        const updated=await request<Session>(`/api/sessions/${session.id}`);
        if(stopped)return;
        setSession(updated);failures=0;
        if(!isRunning(updated))return;
      }catch(e){
        if(stopped)return;
        failures++;
        if(e instanceof ApiError&&e.status===410){setError(e.message);setSession(null);return;}
        if(failures>=3)setError('分析进度连接中断，正在自动重连。已提交的任务可能仍在处理。');
      }
      timer=setTimeout(poll,document.hidden?10000:Math.min(2000*2**failures,15000));
    };
    timer=setTimeout(poll,1500);
    return()=>{stopped=true;clearTimeout(timer);};
  },[session?.id,running,demo]);

  useEffect(()=>{
    if(!session||demo)return;
    const touch=()=>{
      if(document.hidden||Date.now()-lastTouch.current<60000)return;
      lastTouch.current=Date.now();
      request<{expires_at:number}>(`/api/sessions/${session.id}/touch`,{method:'POST'}).then(result=>setSession(s=>s?{...s,expires_at:result.expires_at}:s)).catch(e=>{if(e instanceof ApiError&&e.status===410){setError(e.message);setSession(null);}});
    };
    window.addEventListener('pointerdown',touch);window.addEventListener('keydown',touch);
    return()=>{window.removeEventListener('pointerdown',touch);window.removeEventListener('keydown',touch);};
  },[session?.id,demo]);

  useEffect(()=>{setDraft(item?.edited_text??item?.rewrite??'');setFact('');setFactsConfirmed(false);setSectionId(session?.resume.sections.find(s=>s.kind==='projects'||s.kind==='experience')?.id??session?.resume.sections[0]?.id??'');},[item?.id,item?.needs_fact]);
  useEffect(()=>{if(session&&tab==='preview'&&!demo){let stale=false;setPreview(null);request<Resume>(`/api/sessions/${session.id}/preview`).then(r=>{if(!stale)setPreview(r);}).catch(e=>{if(!stale)fail(e);});return()=>{stale=true;};}},[tab,session?.revision,session?.id,demo]);

  function fail(e:unknown){setError(e instanceof Error?e.message:'操作未完成，请重试。');if(e instanceof ApiError&&['MODEL_NOT_CONFIGURED','MODEL_KEY_REQUIRED','MODEL_KEY_INVALID','MODEL_NAME_REQUIRED'].includes(e.code))setSettingsOpen(true);if(e instanceof ApiError&&e.status===410)setSession(null);}
  async function action(fn:()=>Promise<void>){if(busy)return;setBusy(true);setError('');setNotice('');try{await fn();}catch(e){fail(e);}finally{setBusy(false);}}
  function chooseFile(selected:File|null){
    setError('');
    if(selected&&(!/^.+\.(docx?|pdf)$/i.test(selected.name)||selected.size>5*1024*1024)){setError('请选择不超过 5 MB 的 DOC、DOCX 或文字型 PDF 文件。');setFile(null);if(fileInput.current)fileInput.current.value='';return;}
    setFile(selected);
  }
  async function upload(e:React.SyntheticEvent<HTMLFormElement>){e.preventDefault();await action(async()=>{
    if(!file){setError('请先选择 Word 或 PDF 简历。');return;}
    if(new Blob([jd]).size>2*1024*1024){setError('岗位描述超过 2 MB，请精简后重试。');return;}
    const form=new FormData();form.append('file',file);form.append('jd',jd);form.append('consent',String(consent));
    const created=await request<Session>('/api/sessions',{method:'POST',body:form});setSession(created);setFile(null);setJD('');setConsent(false);setTab('review');
  });}
  async function analyze(){if(!session)return;await action(async()=>{setSession(await request<Session>(`/api/sessions/${session.id}/analyze`,{method:'POST',headers:modelHeaders(model.key),body:JSON.stringify(modelRequest(model))}));});}
  async function decide(decision:'accept'|'skip'|'restore'){
    if(!session||!item)return;
    await action(async()=>{
      if(demo){setSession({...session,revision:session.revision+1,suggestions:session.suggestions.map(s=>s.id===item.id?{...s,decision:decision==='accept'?'accepted':decision==='skip'?'skipped':'pending',edited_text:decision==='accept'?draft:null}:s)});setNotice(decision==='accept'?'已采纳这条示例修改。可以在预览中查看。':'示例状态已更新。');return;}
      const updated=await request<Session>(`/api/sessions/${session.id}/suggestions/${item.id}`,{method:'PATCH',body:JSON.stringify({action:decision,text:decision==='accept'?draft:undefined,revision:session.revision,confirmed_facts:factsConfirmed})});
      setSession(updated);setNotice(decision==='accept'?'已保存修改。可以继续检查下一条，或打开预览。':'建议状态已更新。');
    });
  }
  async function answer(){if(!session||!item)return;await action(async()=>{
    if(demo){setNotice('示例不调用模型。请使用自己的简历与模型设置，体验补充事实后的改写。');return;}
    setSession(await request<Session>(`/api/sessions/${session.id}/suggestions/${item.id}/answer`,{method:'POST',headers:modelHeaders(model.key),body:JSON.stringify({answer:fact,section_id:sectionId,confirmed:factsConfirmed,...modelRequest(model)})}));
  });}
  async function finish(){if(!session)return;const choice=confirm;setConfirm(null);await action(async()=>{
    if(choice==='export'){
      await download(`/api/sessions/${session.id}/export`);
      setSession(null);setPreview(null);setNotice('下载已发起，本次会话已结束，服务端临时数据正在清理。请在浏览器下载列表中确认文件。');
    }else{if(!demo)await request(`/api/sessions/${session.id}`,{method:'DELETE'});if(demo){location.href='/app/';return;}setSession(null);setPreview(null);setNotice('本次会话已结束，服务端材料已清除。');}
  });}
  const accepted=session?.suggestions.filter(s=>s.decision==='accepted').length??0;
  const currentIndex=visible.findIndex(s=>s.id===item?.id);
  const step=!session?1:session.state==='parsed'?2:3;

  return <div className="workbench">
    <header className="work-header"><a href="/" className="brand"><span className="brand-symbol" aria-hidden="true"><span/><span/><span/></span><strong>叙职</strong><span className="brand-en">AIResume</span></a><span className="work-header-label">简历工作台</span><button className="button quiet model-trigger" onClick={()=>setSettingsOpen(true)}><Settings2 size={16}/>模型设置</button></header>
    {demo&&<div className="demo-banner"><span><strong>示例体验</strong> · 以下内容均为虚构，不调用模型</span><a href="/app/">使用自己的简历<ArrowRight size={15}/></a></div>}
    <main id="main" className="work-main">
      {!demo&&<p className="current-model" aria-live="polite">当前模型：<strong>{model.provider==='station'?(config?.station_configured?`站方 · ${config.station_model??'模型信息暂不可用'}`:config?'站方尚未配置模型':'正在读取配置…'):`${model.name??config?.providers.find(p=>p.id===model.provider)?.name??'自定义 API'} · ${model.model}`}</strong></p>}
      <div className="workspace-heading"><div><h1>{!session?'上传简历':session.state==='parsed'?'核对简历内容':running?'正在分析':tab==='preview'?'简历预览':'修改建议'}</h1></div>{session&&<button className="text-button end-session" onClick={()=>setConfirm('end')} disabled={busy}>结束会话</button>}</div>
      <ol className="stepper" aria-label="修改进度">{['上传','核对','修改与导出'].map((label,i)=><li key={label} className={step===i+1?'current':step>i+1?'done':''} aria-current={step===i+1?'step':undefined}><span>{step>i+1?<Check size={13}/>:i+1}</span>{label}</li>)}</ol>
      {error&&<div className="message error" role="alert"><span>{error}</span><button className="icon-button" onClick={()=>setError('')} aria-label="关闭错误提示"><X size={17}/></button></div>}
      {notice&&<div className="message success" role="status">{notice}</div>}
      {loading?<div className="loading-state" role="status"><LoaderCircle className="spin" size={22}/>正在检查当前会话…</div>:!session?<>
        <form className="intake-grid" onSubmit={upload}>
          <section className="intake-resume"><div className="form-section-title"><h2>你的现有简历</h2></div>
            <label className={'upload-zone '+(file?'has-file':'')} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();chooseFile(e.dataTransfer.files[0]??null);}}>
              <input ref={fileInput} type="file" accept=".doc,.docx,.pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf" onChange={e=>chooseFile(e.target.files?.[0]??null)} aria-label="选择 Word 或 PDF 简历"/>
              <span className="upload-illustration"><FileText size={34} strokeWidth={1.3}/></span><strong>{file?file.name:'选择或拖入 Word / PDF'}</strong><span>{file?`${(file.size/1024).toFixed(0)} KB · 点击重新选择`:'DOC / DOCX / 文字型 PDF · 5 MB 内 · 最多 8 页'}</span><span className="button quiet"><Upload size={15}/>{file?'更换文件':'选择文件'}</span>
            </label>
          </section>
          <section className="intake-jd"><div className="form-section-title"><label htmlFor="jd"><h2>目标岗位描述</h2></label></div><textarea id="jd" value={jd} onChange={e=>setJD(e.target.value)} placeholder="粘贴岗位职责和任职要求" minLength={40} required aria-describedby="jd-hint"/><div className="input-meta"><span id="jd-hint">至少 40 字符</span><span>{jd.length.toLocaleString()} 字符</span></div></section>
          <div className="intake-submit"><label className="check-label"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} required/><span>同意按<a href="/privacy/" target="_blank" rel="noreferrer">数据处理说明</a>临时处理材料，并将文字发送给所选模型。</span></label><button className="button primary large" disabled={busy||!file||!consent||jd.trim().length<40} type="submit">{busy?<LoaderCircle size={18} className="spin"/>:'读取简历'}{!busy&&<ArrowRight size={18}/>}</button></div>
        </form>
        <div className="intake-aside"><a className="text-link" href="/app/?demo=1">查看虚构示例<ArrowUpRightIcon/></a></div>
      </>:<>
        {session.state==='parsed'?<>
          <div className="parsed-grid"><section className="source-document"><div className="panel-heading"><FileText size={17}/><h2>读取到的简历内容</h2></div><SourceResume resume={session.resume}/></section><aside className="source-context"><h2>请核对</h2><p>检查姓名、经历和提取顺序，确认完整后再开始分析。</p>{session.resume.page_count_verified&&<p className="field-hint">已校验页数：{session.resume.rendered_pages} / 8 页</p>}{session.resume.warnings.map(w=><p key={w} className="parse-warning">{w}</p>)}<details open><summary>目标岗位原文</summary><p className="jd-full">{session.jd}</p></details><p className="field-hint">读取不完整时，请结束会话，调整文档后重新上传。</p></aside></div>
          <div className="confirmation-bar"><button className="button primary" onClick={analyze} disabled={busy}>{busy?<LoaderCircle size={17} className="spin"/>:<>读取无误，开始分析<ArrowRight size={17}/></>}</button></div>
        </>:running?<div className="analysis-state" role="status"><LoaderCircle size={30} className="spin"/><h2>{session.state==='answering'?'正在生成改写':'正在分析简历'}</h2><p>模型响应可能需要几分钟。</p><div className="dimension-progress">{(Object.keys(dimensionNames) as Dimension[]).map(d=><div key={d}><span className={session.dimensions[d]==='complete'?'complete':''}>{session.dimensions[d]==='complete'?<Check size={16}/>:<span className="progress-dot"/>}</span>{dimensionNames[d]}</div>)}</div></div>:reviewable?<>
          <div className="review-toolbar"><div className="view-tabs" aria-label="工作区视图"><button className={tab==='review'?'active':''} aria-pressed={tab==='review'} onClick={()=>setTab('review')}>逐条修改<span>{session.suggestions.length}</span></button><button className={tab==='preview'?'active':''} aria-pressed={tab==='preview'} onClick={()=>setTab('preview')}>简历预览</button></div><div className="review-summary"><span>已采纳 {accepted} 条</span><button className="button primary small-button" onClick={()=>{if(demo){setNotice('示例仅展示交互。使用自己的简历后，可以导出真实的 Word 文档。');return;}setConfirm('export');}} disabled={busy}><Download size={16}/>导出 Word</button></div></div>
          {session.state==='partial'&&<div className="inline-note partial-note" role="status"><span>部分分析未完成，已有建议可继续使用。</span><button className="button quiet" onClick={analyze} disabled={busy||running}><ArrowRight size={15}/>重试未完成的分析</button></div>}
          {session.error&&<p className="inline-note" role="status">{modelErrorMessage(session.error)} 原文与已采纳内容仍会保留。</p>}
          {tab==='preview'?<div className="preview-area"><div className="preview-controls"><p className="preview-disclaimer">仅展示已采纳的修改，其他内容保留原文。浏览器和 Word 的分页可能不同。</p><div role="group" aria-label="预览缩放"><button className={previewZoom==='fit'?'active':''} aria-pressed={previewZoom==='fit'} onClick={()=>setPreviewZoom('fit')}>适合屏幕</button><button className={previewZoom==='actual'?'active':''} aria-pressed={previewZoom==='actual'} onClick={()=>setPreviewZoom('actual')}>实际尺寸</button></div></div>{demo?<ResumePreview resume={applyDemo(session)} zoom={previewZoom}/>:preview?<ResumePreview resume={preview} zoom={previewZoom}/>:<p role="status">正在准备预览…</p>}</div>:session.suggestions.length===0?<div className="empty-state"><Check size={30}/><h2>这次没有可展示的建议</h2><p>可能没有发现值得调整的内容，也可能候选建议未通过依据校验。可以预览并导出原文；这不代表简历已经完整或一定匹配岗位。</p><button className="button quiet" onClick={()=>setTab('preview')}>查看简历</button></div>:<div className="review-grid">
            <aside className="suggestion-index"><div className="filter-buttons" aria-label="筛选建议">{[['all','全部'],['pending','待处理'],['accepted','已采纳'],['skipped','已跳过']].map(([value,label])=><button key={value} className={filter===value?'active':''} aria-pressed={filter===value} onClick={()=>{setFilter(value);const first=session.suggestions.find(s=>value==='all'||s.decision===value);if(first)setActive(first.id);}}>{label}</button>)}</div><nav aria-label="修改建议">{visible.map(s=><button key={s.id} className={'suggestion-link '+(item?.id===s.id?'active':'')} aria-current={item?.id===s.id?'true':undefined} onClick={()=>{setActive(s.id);setNotice('');}}><span className="suggestion-meta">{dimensionNames[s.dimension]}<span>{s.decision==='accepted'?<Check size={13}/>:s.decision==='skipped'?'已跳过':priorities[s.priority]}</span></span><strong>{s.title}</strong></button>)}{!visible.length&&<p className="filter-empty">这个分类暂时没有建议。</p>}</nav></aside>
            {item&&<section className="suggestion-detail" aria-label="当前修改建议"><div className="detail-meta"><span className={'priority '+item.priority}>{priorities[item.priority]}</span><span>{dimensionNames[item.dimension]}</span></div><h2>{item.title}</h2><p className="suggestion-reason">{item.reason}</p>
              <div className="evidence-grid"><div><h3>简历原文</h3>{item.resume_quote?<blockquote>{item.resume_quote}</blockquote>:<p className="muted">需要补充真实经历。</p>}</div><div><h3>岗位依据</h3><blockquote>{item.jd_quote}</blockquote></div></div>
              {item.needs_fact?<div className="rewrite-editor fact-editor"><label htmlFor="fact-answer">{item.question}</label><textarea id="fact-answer" value={fact} onChange={e=>{setFact(e.target.value);setFactsConfirmed(false);}} placeholder="只写你确实做过的事情。没有相关经历可以跳过。" maxLength={2000}/><label htmlFor="fact-section">加入哪个章节</label><select id="fact-section" value={sectionId} onChange={e=>setSectionId(e.target.value)}>{session.resume.sections.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select><label className="check-label"><input type="checkbox" checked={factsConfirmed} onChange={e=>setFactsConfirmed(e.target.checked)}/><span>我确认补充内容真实，生成后还会再次核对。</span></label><button className="button primary" onClick={answer} disabled={busy||!factsConfirmed||fact.trim().length<2}>{busy?<LoaderCircle className="spin" size={16}/>:null}根据补充生成改写</button></div>:<div className="rewrite-editor"><div className="editor-heading"><label htmlFor="rewrite">建议改写</label></div>{item.user_fact&&<details><summary>查看我补充的事实</summary><p>{item.user_fact}</p></details>}<textarea id="rewrite" value={draft} onChange={e=>{setDraft(e.target.value);setFactsConfirmed(false);}} maxLength={3000}/><label className="check-label"><input type="checkbox" checked={factsConfirmed} onChange={e=>setFactsConfirmed(e.target.checked)}/><span>我已核对，改写符合我的真实经历。</span></label><div className="decision-actions"><button className="button primary" onClick={()=>decide('accept')} disabled={busy||!factsConfirmed||!draft.trim()}><Check size={16}/>{item.decision==='accepted'?'保存这条修改':'采纳这条修改'}</button><span className="decision-status">{item.decision==='accepted'?'当前已采纳':item.decision==='skipped'?'当前已跳过':'尚未采纳'}</span></div></div>}
              <div className="suggestion-bottom"><div><button className="text-button" onClick={()=>decide('skip')} disabled={busy||item.decision==='skipped'}>跳过这条</button>{item.decision!=='pending'&&<button className="text-button" onClick={()=>decide('restore')} disabled={busy}>撤销选择</button>}</div><div className="suggestion-pager"><button className="icon-button" aria-label="上一条建议" disabled={currentIndex<=0} onClick={()=>setActive(visible[currentIndex-1].id)}><ChevronLeft size={18}/></button><span>{currentIndex>=0?currentIndex+1:'—'} / {visible.length}</span><button className="icon-button" aria-label="下一条建议" disabled={currentIndex<0||currentIndex>=visible.length-1} onClick={()=>setActive(visible[currentIndex+1].id)}><ChevronRight size={18}/></button></div></div>
            </section>}
          </div>}
        </>:<div className="empty-state"><h2>这次分析没有完成</h2><p role="alert" className="analysis-failure">{modelErrorMessage(session.error)}</p><p>你的原文仍保留在有效会话中。可以修改模型设置后重新分析。</p><div className="hero-actions"><button className="button primary" onClick={analyze} disabled={busy}>重新分析</button><button className="button quiet" onClick={()=>setSettingsOpen(true)}>检查模型设置</button></div><details><summary>查看保留的原文</summary><SourceResume resume={session.resume}/></details></div>}
      </>}
      <footer className="workspace-footer"><a href="/" className="back-link"><ArrowLeft size={14}/>返回首页</a><a href="/privacy/" target="_blank" rel="noreferrer">数据处理说明</a></footer>
    </main>
    <ModelDialog open={settingsOpen} onOpenChange={setSettingsOpen} settings={model} config={config} onSave={setModel}/>
    <Dialog.Root open={!!confirm} onOpenChange={open=>{if(!open)setConfirm(null);}}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content confirm-dialog"><Dialog.Title>{confirm==='export'?'导出并结束本次会话？':'结束本次会话？'}</Dialog.Title><Dialog.Description>{confirm==='export'?'将生成包含已采纳修改的 Word 文档。服务端在响应完成后清理本次材料，无法确认文件是否成功保存到你的设备，请及时检查下载。':'简历、岗位描述与本次修改将从服务端清除。结束后需要重新上传，才能再次开始。'}</Dialog.Description><div className="dialog-actions"><Dialog.Close className="button quiet">继续检查</Dialog.Close><button className="button primary" onClick={finish}>{confirm==='export'?'确认导出 Word':'确认结束'}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}

function SourceResume({resume}:{resume:Resume}){return <div className="source-text">{resume.sections.map(section=><section key={section.id}><h3>{section.title}</h3>{section.blocks.map(b=><p key={b.id}>{b.text}</p>)}</section>)}</div>;}
function ArrowUpRightIcon(){return <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M4 12 12 4M4 4h8v8" stroke="currentColor" strokeWidth="1.4"/></svg>;}
