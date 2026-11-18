import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, LoaderCircle, Plus, X } from 'lucide-react';
import { modelHeaders, request } from '../lib/api';
import { fromCustomAPI, modelIDPattern, modelRequest } from '../lib/model-settings';
import type { CustomAPI } from '../lib/types';

type Props = {initial:CustomAPI; editing:boolean; onSave:(profile:CustomAPI)=>void; onCancel:()=>void};
type Errors = Partial<Record<'id'|'name'|'base_url'|'key'|'model',string>>;

function validate(profile:CustomAPI):Errors {
  const errors:Errors={};
  if(!/^[a-z][a-z0-9_-]{0,39}$/.test(profile.id)) errors.id='以小写字母开头，可使用字母、数字、下划线和短横线，最多 40 字符。';
  if(!profile.name.trim()) errors.name='请填写显示名称。';
  try {
    const url=new URL(profile.base_url);
    if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash) throw new Error();
  } catch {errors.base_url='请填写公网 HTTPS API 根地址，不要包含账号或查询参数。';}
  if(!/^[\x21-\x7e]{1,512}$/.test(profile.key.trim())) errors.key='请填写 API Key，不能包含空格或换行。';
  if(!modelIDPattern.test(profile.model.trim())) errors.model='请填写该服务支持的默认模型 ID。';
  return errors;
}

export default function CustomAPIEditor({initial,editing,onSave,onCancel}:Props) {
  const [profile,setProfile]=useState({...initial,models:[...initial.models]});
  const [showKey,setShowKey]=useState(false);
  const [newModel,setNewModel]=useState('');
  const [fetching,setFetching]=useState(false);
  const [errors,setErrors]=useState<Errors>({});
  const [message,setMessage]=useState('');
  const [failed,setFailed]=useState(false);
  const feedback=useRef<HTMLParagraphElement>(null);
  const controller=useRef<AbortController|null>(null);
  useEffect(()=>()=>controller.current?.abort(),[]);

  function notify(text:string,failure=false){setMessage(text);setFailed(failure);}
  function blur(field:keyof Errors){setErrors(current=>({...current,[field]:validate(profile)[field]}));}
  function submit(e:React.SyntheticEvent<HTMLFormElement>){
    e.preventDefault();
    const cleaned={...profile,name:profile.name.trim(),base_url:profile.base_url.trim().replace(/\/+$/,''),key:profile.key.trim(),model:profile.model.trim()};
    const invalid=validate(cleaned);setErrors(invalid);
    if(Object.keys(invalid).length){notify('请检查标出的配置项。',true);requestAnimationFrame(()=>feedback.current?.focus());return;}
    cleaned.models=[...new Set([cleaned.model,...cleaned.models])].slice(0,100);
    onSave(cleaned);
  }
  async function fetchModels(){
    const invalid=validate(profile);
    if(invalid.base_url||invalid.key){setErrors(current=>({...current,base_url:invalid.base_url,key:invalid.key}));notify('请先填写有效的 API 地址和 Key。',true);return;}
    const active=new AbortController();controller.current=active;setFetching(true);notify('');
    try {
      const result=await request<{models:string[]}>('/api/models',{
        method:'POST',signal:active.signal,headers:modelHeaders(profile.key.trim()),
        body:JSON.stringify(modelRequest(fromCustomAPI(profile))),
      });
      if(active.signal.aborted)return;
      setProfile(current=>({...current,models:[...new Set([...current.models,...result.models])].slice(0,100),model:current.model||result.models[0]||''}));
      notify(`已获取 ${result.models.length} 个模型，可选择或手动填写模型 ID。`);
    } catch(e){if(!active.signal.aborted)notify(e instanceof Error?e.message:'获取失败，可以手动填写模型 ID。',true);}
    finally{if(!active.signal.aborted)setFetching(false);}
  }
  function addModel(){
    const model=newModel.trim();
    if(!modelIDPattern.test(model)){notify('请输入有效的模型 ID。',true);return;}
    if(profile.models.length>=100&&!profile.models.includes(model)){notify('模型目录最多保留 100 项，请先移除不需要的模型。',true);return;}
    setProfile({...profile,models:[...new Set([...profile.models,model])],model:profile.model||model});setNewModel('');notify('');
  }
  function fieldError(field:keyof Errors){return errors[field]?<p id={`custom-${field}-error`} className="field-error">{errors[field]}</p>:null;}
  return <form className="settings-form custom-api-form" onSubmit={submit} noValidate>
    {message&&<p ref={feedback} tabIndex={-1} role={failed?'alert':'status'} className={failed?'field-error model-feedback':'model-feedback'}>{message}</p>}
    <label htmlFor="custom-id">Provider ID</label>
    <input id="custom-id" value={profile.id} disabled={editing} onChange={e=>setProfile({...profile,id:e.target.value})} onBlur={()=>blur('id')} placeholder="my-gateway" maxLength={40} autoComplete="off" required aria-invalid={!!errors.id} aria-describedby="custom-id-hint custom-id-error"/>
    <p id="custom-id-hint" className="field-hint">当前浏览器中的唯一标识，创建后不可修改。</p>{fieldError('id')}
    <label htmlFor="custom-name">显示名称</label>
    <input id="custom-name" value={profile.name} onChange={e=>setProfile({...profile,name:e.target.value})} onBlur={()=>blur('name')} maxLength={60} placeholder="我的模型服务" autoComplete="off" required aria-invalid={!!errors.name} aria-describedby="custom-name-error"/>{fieldError('name')}
    <label htmlFor="custom-url">API 地址</label>
    <input id="custom-url" type="url" value={profile.base_url} disabled={fetching} onChange={e=>setProfile({...profile,base_url:e.target.value})} onBlur={()=>blur('base_url')} placeholder="https://api.example.com/v1" maxLength={2048} autoComplete="off" required aria-invalid={!!errors.base_url} aria-describedby="custom-url-hint custom-base_url-error"/>
    <p id="custom-url-hint" className="field-hint">填写 API 根地址及 /v1 等必要路径，无需填写 /chat/completions 或 /responses。</p>{fieldError('base_url')}
    <label htmlFor="custom-protocol">API 协议</label>
    <select id="custom-protocol" value={profile.protocol} disabled={fetching} onChange={e=>setProfile({...profile,protocol:e.target.value as CustomAPI['protocol']})}><option value="chat_completions">OpenAI Chat Completions</option><option value="responses">OpenAI Responses</option></select>
    <label htmlFor="custom-key">API Key</label>
    <div className="api-key-input"><input id="custom-key" type={showKey?'text':'password'} value={profile.key} disabled={fetching} onChange={e=>setProfile({...profile,key:e.target.value})} onBlur={()=>blur('key')} maxLength={512} autoComplete="off" required aria-invalid={!!errors.key} aria-describedby="custom-key-error"/><button type="button" className="icon-button" aria-label={showKey?'隐藏 API Key':'显示 API Key'} onClick={()=>setShowKey(!showKey)}>{showKey?<EyeOff size={18}/>:<Eye size={18}/>}</button></div>{fieldError('key')}
    <div className="model-catalog">
      <div className="model-catalog-heading"><h3>模型目录</h3><button type="button" className="text-button" onClick={fetchModels} disabled={fetching}>{fetching?<><LoaderCircle className="spin" size={14}/>正在获取…</>:'获取可用模型'}</button></div>
      <p className="field-hint">目录接口不可用时，可以直接填写模型 ID。</p>
      {profile.models.length>0&&<div className="model-chips">{profile.models.map(model=><span key={model}>{model}<button type="button" aria-label={`移除模型 ${model}`} onClick={()=>setProfile({...profile,models:profile.models.filter(m=>m!==model),model:profile.model===model?'':profile.model})}><X size={13}/></button></span>)}</div>}
      <div className="add-model-row"><input aria-label="添加模型 ID" value={newModel} onChange={e=>setNewModel(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();addModel();}}} placeholder="例如 gpt-6-luna" maxLength={100} autoComplete="off"/><button className="button quiet" type="button" onClick={addModel}><Plus size={15}/>添加模型</button></div>
    </div>
    <label htmlFor="custom-model">默认模型 ID</label>
    <input id="custom-model" list="custom-models" value={profile.model} onChange={e=>setProfile({...profile,model:e.target.value})} onBlur={()=>blur('model')} placeholder="选择或填写模型 ID" maxLength={100} autoComplete="off" required aria-invalid={!!errors.model} aria-describedby="custom-model-error"/>
    <datalist id="custom-models">{profile.models.map(model=><option key={model} value={model}/>)}</datalist>{fieldError('model')}
    <p className="field-hint">Key 会长期保存在此浏览器；服务端仅在调用时临时使用。请确认你信任该 API 服务。</p>
    <div className="dialog-actions"><button type="button" className="text-button" onClick={onCancel}>取消</button><button className="button primary" type="submit" disabled={fetching}>{editing?'保存并使用':'创建并使用'}</button></div>
  </form>;
}
