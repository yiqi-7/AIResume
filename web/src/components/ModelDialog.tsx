import { useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { Configuration, ModelSettings } from '../lib/types';

export const modelStorageKey = 'airesume-model-v1';
type Props = {open:boolean; onOpenChange:(v:boolean)=>void; settings:ModelSettings; config:Configuration|null; onSave:(s:ModelSettings)=>void};
export default function ModelDialog({open,onOpenChange,settings,config,onSave}:Props) {
  const [draft,setDraft]=useState(settings);
  const [remember,setRemember]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{if(open){setDraft(settings);setError('');try{setRemember(!!localStorage.getItem(modelStorageKey));}catch{setRemember(false);}}},[open,settings]);
  function save(e:React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if(draft.provider!=='station' && (!draft.key.trim() || !draft.model.trim())){setError('请填写 API Key 和模型名称。');return;}
    const selected=draft.provider==='station'?{provider:'station',model:'',key:''}:draft;
    try {
      if(remember && selected.provider!=='station') localStorage.setItem(modelStorageKey,JSON.stringify(selected));
      else localStorage.removeItem(modelStorageKey);
    } catch {setError('浏览器不允许保存本地设置。请取消“记住”后再试。');if(remember)return;}
    onSave(selected);onOpenChange(false);
  }
  function clear(){try{localStorage.removeItem(modelStorageKey);}catch{/* In-memory key is cleared below. */}setRemember(false);setDraft({provider:'station',model:'',key:''});onSave({provider:'station',model:'',key:''});setError('已清除当前页面与浏览器保存的 Key。');}
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content">
    <Dialog.Title>模型设置</Dialog.Title><Dialog.Description>选择本次分析使用的服务。简历文字和岗位描述会发送给该服务商。</Dialog.Description>
    <form onSubmit={save} className="settings-form">
      <label htmlFor="model-provider">模型服务</label><select id="model-provider" value={draft.provider} onChange={e=>setDraft({...draft,provider:e.target.value,model:'',key:''})}>
        <option value="station">站方模型{config?.station_configured?'':'（尚未配置）'}</option>
        {(config?.providers??[{id:'deepseek',name:'DeepSeek'},{id:'qwen',name:'通义千问'},{id:'zhipu',name:'智谱'}]).map(p=><option key={p.id} value={p.id}>{p.name} · 使用自己的 Key</option>)}
      </select>
      {draft.provider!=='station' ? <>
        <label htmlFor="model-name">模型名称</label><input id="model-name" value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value})} placeholder="填写服务商支持的模型 ID" maxLength={100} autoComplete="off" required/>
        <label htmlFor="model-key">API Key</label><input id="model-key" type="password" value={draft.key} onChange={e=>setDraft({...draft,key:e.target.value})} autoComplete="off" maxLength={512} required/>
        <label className="check-label"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/><span>在这台设备记住 Key（公用设备请勿勾选）</span></label>
        <p className="field-hint">不填写自定义 API 地址。Key 仅用于所选服务，不保存在后端。使用自己的 Key 会产生对应服务商费用。</p>
      </> : <p className="inline-note">{config?.station_configured?'使用站方配置的模型，受匿名体验额度限制。':'站方尚未配置模型。你可以选择自己的 Key，或先体验明确标注的虚构示例。'}</p>}
      {error&&<p role="status" className="field-error">{error}</p>}
      <div className="dialog-actions"><button type="button" className="text-button" onClick={clear}>清除已保存的 Key</button><button className="button primary" type="submit">保存设置</button></div>
    </form>
    <Dialog.Close className="icon-button dialog-close" aria-label="关闭模型设置"><X size={20}/></Dialog.Close>
  </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
