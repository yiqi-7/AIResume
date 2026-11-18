import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react';
import CustomAPIEditor from './CustomAPIEditor';
import { customAPIStorageKey, fromCustomAPI, loadCustomAPIs, maxCustomAPIs, modelIDPattern, modelStorageKey, persistCustomAPIs, stationSettings } from '../lib/model-settings';
import type { Configuration, CustomAPI, ModelSettings } from '../lib/types';

type Props = {open:boolean; onOpenChange:(v:boolean)=>void; settings:ModelSettings; config:Configuration|null; onSave:(s:ModelSettings)=>void};
const emptyAPI=():CustomAPI=>({id:`api-${crypto.randomUUID()}`,name:'',base_url:'',protocol:'chat_completions',key:'',models:[],model:''});

export default function ModelDialog({open,onOpenChange,settings,config,onSave}:Props) {
  const [tab,setTab]=useState<'builtin'|'custom'>('builtin');
  const [draft,setDraft]=useState(settings);
  const [profiles,setProfiles]=useState<CustomAPI[]>([]);
  const [modelChoices,setModelChoices]=useState<Record<string,string>>({});
  const [editing,setEditing]=useState<CustomAPI|null>(null);
  const [editingId,setEditingId]=useState<string|null>(null);
  const [remember,setRemember]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const feedback=useRef<HTMLParagraphElement>(null);
  useEffect(()=>{
    if(open){
      const saved=loadCustomAPIs();
      setDraft(settings.provider==='custom'?stationSettings:settings);setProfiles(saved);
      setModelChoices(Object.fromEntries(saved.map(p=>[p.id,settings.provider==='custom'&&settings.id===p.id?settings.model:p.model])));
      setTab(settings.provider==='custom'?'custom':'builtin');setEditing(null);setEditingId(null);
      setError('');setNotice('');
      try{setRemember(!!localStorage.getItem(modelStorageKey));}catch{setRemember(false);}
    }
  },[open,settings]);
  useEffect(()=>{if(error)feedback.current?.focus();},[error]);
  useEffect(()=>{
    const sync=(event:StorageEvent)=>{if(event.key===customAPIStorageKey)setProfiles(loadCustomAPIs());};
    window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync);
  },[]);
  function fail(message:string){setNotice('');setError(message);}
  function selectCustom(profile:CustomAPI,selectedModel=profile.model){
    const latest=loadCustomAPIs().find(p=>p.id===profile.id);
    if(!latest){setProfiles(loadCustomAPIs());fail('这组配置已被删除，请重新选择。');return;}
    if(!modelIDPattern.test(selectedModel)){fail('请选择或填写有效的模型名称。');return;}
    try{localStorage.setItem(modelStorageKey,JSON.stringify({provider:'custom',id:latest.id,model:selectedModel}));}
    catch{fail('浏览器不允许保存配置，请检查本地存储设置。');return;}
    onSave(fromCustomAPI(latest,selectedModel));onOpenChange(false);
  }
  function saveBuiltin(e:React.SyntheticEvent<HTMLFormElement>){
    e.preventDefault();
    if(draft.provider!=='station'&&(!draft.key.trim()||!modelIDPattern.test(draft.model))){fail('请填写 API Key 和模型名称。');return;}
    const selected=draft.provider==='station'?stationSettings:draft;
    try{if(remember&&selected.provider!=='station')localStorage.setItem(modelStorageKey,JSON.stringify(selected));else localStorage.removeItem(modelStorageKey);}
    catch{fail('浏览器不允许保存本地设置。请取消“记住”后再试。');if(remember)return;}
    onSave(selected);onOpenChange(false);
  }
  function begin(profile?:CustomAPI){
    if(!profile&&loadCustomAPIs().length>=maxCustomAPIs){fail('最多保存 3 组自定义 API，请先删除一组。');return;}
    setError('');setNotice('');setEditingId(profile?.id??null);setEditing(profile??emptyAPI());
  }
  function saveCustom(profile:CustomAPI){
    const latest=loadCustomAPIs();
    if(!editingId&&latest.some(p=>p.id===profile.id)){fail('未能保存，请重新添加这组 API。');return;}
    if(editingId&&!latest.some(p=>p.id===editingId)){fail('这组配置已在其他页面删除，请取消后重新添加。');return;}
    if(!editingId&&latest.length>=maxCustomAPIs){setProfiles(latest);fail('最多保存 3 组自定义 API，请先删除一组。');return;}
    const updated=editingId?latest.map(p=>p.id===editingId?profile:p):[...latest,profile];
    try{persistCustomAPIs(updated);}catch{fail('浏览器不允许保存配置，请检查本地存储设置。');return;}
    setProfiles(updated);selectCustom(profile);
  }
  function removeProfile(id:string){
    const updated=loadCustomAPIs().filter(p=>p.id!==id);
    try{persistCustomAPIs(updated);if(settings.provider==='custom'&&settings.id===id)localStorage.removeItem(modelStorageKey);}
    catch{fail('删除未完成，请检查浏览器存储权限。');return;}
    setProfiles(updated);if(settings.provider==='custom'&&settings.id===id)onSave(stationSettings);
    setNotice('已删除这组 API 和保存的 Key。');setError('');
  }
  function clear(){
    try{localStorage.removeItem(modelStorageKey);localStorage.removeItem(customAPIStorageKey);}
    catch{fail('清除未完成，请检查浏览器存储权限。');return;}
    setProfiles([]);setEditing(null);setRemember(false);setDraft(stationSettings);onSave(stationSettings);
    setNotice('已清除全部 Key。');setError('');
  }
  function moveTab(event:React.KeyboardEvent,next:'builtin'|'custom'){
    if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
      event.preventDefault();setTab(next);document.getElementById(`${next}-tab`)?.focus();
    }
  }
  const providers=(config?.providers??[{id:'deepseek',name:'DeepSeek'}]).filter(p=>p.id==='deepseek');
  const hasKeys=profiles.length>0||!!draft.key||!!settings.key||remember;
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content model-dialog">
    <Dialog.Title>模型设置</Dialog.Title>
    <Dialog.Description className="sr-only">设置本次简历分析使用的模型服务。</Dialog.Description>
    <div className="model-tabs" role="tablist" aria-label="API 配置类型">
      <button role="tab" id="builtin-tab" aria-controls="builtin-panel" aria-selected={tab==='builtin'} tabIndex={tab==='builtin'?0:-1} onKeyDown={e=>moveTab(e,'custom')} onClick={()=>{setTab('builtin');setEditing(null);setError('');}}>模型服务</button>
      <button role="tab" id="custom-tab" aria-controls="custom-panel" aria-selected={tab==='custom'} tabIndex={tab==='custom'?0:-1} onKeyDown={e=>moveTab(e,'builtin')} onClick={()=>{setTab('custom');setError('');}}>自定义 API <span>{profiles.length}/3</span></button>
    </div>
    {error&&<p ref={feedback} tabIndex={-1} role="alert" className="field-error model-feedback">{error}</p>}
    {notice&&<p role="status" className="model-feedback">{notice}</p>}
    {tab==='builtin'?<div role="tabpanel" id="builtin-panel" aria-labelledby="builtin-tab"><form onSubmit={saveBuiltin} className="settings-form">
      <label htmlFor="model-provider">选择服务</label>
      <select id="model-provider" value={draft.provider} onChange={e=>setDraft({provider:e.target.value,model:'',key:''})}><option value="station">默认模型{config?.station_configured?'':'（暂不可用）'}</option>{providers.map(p=><option key={p.id} value={p.id}>{p.name} · 自己的 Key</option>)}</select>
      {draft.provider!=='station'?<>
        <label htmlFor="model-name">模型名称</label><input id="model-name" value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value})} maxLength={100} autoComplete="off" required/>
        <label htmlFor="model-key">API Key</label><input id="model-key" type="password" value={draft.key} onChange={e=>setDraft({...draft,key:e.target.value})} autoComplete="off" maxLength={512} required/>
        <label className="check-label"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/><span>在此浏览器保存 Key</span></label>
        <p className="field-hint">调用费用由服务商收取。</p>
      </>:<div className="station-model-info"><strong>{config?.station_configured?config.station_model??'暂时无法获取模型名称':'默认模型暂不可用'}</strong>{!config?.station_configured&&<p className="field-hint">请稍后重试，或使用自己的 API。</p>}</div>}
      <div className="dialog-actions">{hasKeys&&<button type="button" className="text-button" onClick={clear}>清空全部 Key</button>}<button className="button primary" type="submit">保存设置</button></div>
    </form></div>:<div role="tabpanel" id="custom-panel" aria-labelledby="custom-tab">
      <p className="field-hint model-storage-note">Key 保存在当前浏览器，请勿在公用设备上保存。</p>
      {editing?<CustomAPIEditor initial={editing} editing={!!editingId} onSave={saveCustom} onCancel={()=>{setEditing(null);setError('');setNotice('');}}/>:<>
        <div className="custom-api-list">{profiles.length?profiles.map(profile=><article className="custom-api-card" key={profile.id}>
          <div className="custom-api-heading"><h3>{profile.name}</h3>{settings.provider==='custom'&&settings.id===profile.id&&<span className="api-selected"><Check size={13}/>正在使用</span>}</div>
          <p>{profile.base_url}</p>
          <label className="profile-model-label" htmlFor={`profile-model-${profile.id}`}>本次使用的模型 · {profile.name}</label>
          <input id={`profile-model-${profile.id}`} list={`profile-models-${profile.id}`} value={modelChoices[profile.id]??profile.model} onChange={e=>setModelChoices({...modelChoices,[profile.id]:e.target.value})} maxLength={100} autoComplete="off"/>
          <datalist id={`profile-models-${profile.id}`}>{[...new Set([profile.model,...profile.models])].map(model=><option key={model} value={model}/>)}</datalist>
          <div className="custom-api-actions"><button className="button quiet" onClick={()=>begin(profile)}><Pencil size={14}/>编辑</button><button className="button quiet" aria-label={`删除 ${profile.name}`} onClick={()=>removeProfile(profile.id)}><Trash2 size={14}/>删除</button><button className="button primary" onClick={()=>selectCustom(profile,modelChoices[profile.id]??profile.model)}>使用</button></div>
        </article>):<div className="custom-api-empty"><p>尚未添加自定义 API</p></div>}</div>
        <button className="button quiet add-api" onClick={()=>begin()} disabled={profiles.length>=maxCustomAPIs}><Plus size={16}/>添加自定义 API</button>
        {profiles.length>=maxCustomAPIs&&<p className="field-hint">已达到 3 组上限，删除一组后可以继续添加。</p>}
        <div className="dialog-actions">{hasKeys&&<button className="text-button" onClick={clear}>清空全部 Key</button>}<Dialog.Close className="button primary">完成</Dialog.Close></div>
      </>}
    </div>}
    <Dialog.Close className="icon-button dialog-close" aria-label="关闭模型设置"><X size={20}/></Dialog.Close>
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
