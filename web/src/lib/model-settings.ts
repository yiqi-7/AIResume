import type { CustomAPI, ModelSettings } from './types';

export const modelStorageKey = 'airesume-model-v1';
export const customAPIStorageKey = 'airesume-custom-apis-v1';
export const maxCustomAPIs = 3;
export const stationSettings:ModelSettings = {provider:'station', model:'', key:''};
export const modelIDPattern = /^[\w./:+-]{1,100}$/u;

function isCustomAPI(value:unknown):value is CustomAPI {
  if (!value || typeof value !== 'object') return false;
  const p=value as CustomAPI;
  return typeof p.id==='string' && /^[a-z][a-z0-9_-]{0,39}$/.test(p.id)
    && typeof p.name==='string' && p.name.length>0 && p.name.length<=60
    && typeof p.base_url==='string' && p.base_url.length<=2048
    && (p.protocol==='chat_completions'||p.protocol==='responses')
    && typeof p.key==='string' && p.key.length>0 && p.key.length<=512
    && typeof p.model==='string' && modelIDPattern.test(p.model)
    && Array.isArray(p.models) && p.models.length<=100
    && p.models.every(m=>typeof m==='string'&&modelIDPattern.test(m));
}

export function loadCustomAPIs():CustomAPI[] {
  try {
    const saved:unknown=JSON.parse(localStorage.getItem(customAPIStorageKey)??'[]');
    if (!Array.isArray(saved)) return [];
    const ids=new Set<string>();
    return saved.filter(isCustomAPI).filter(p=>{if(ids.has(p.id))return false;ids.add(p.id);return true;}).slice(0,maxCustomAPIs);
  } catch { return []; }
}

export function fromCustomAPI(profile:CustomAPI):ModelSettings {
  return {provider:'custom',id:profile.id,name:profile.name,base_url:profile.base_url,
    protocol:profile.protocol,model:profile.model,key:profile.key};
}

export function loadModelSettings():ModelSettings {
  try {
    const saved=JSON.parse(localStorage.getItem(modelStorageKey)??'null');
    if (saved?.provider==='custom') {
      const profile=loadCustomAPIs().find(p=>p.id===saved.id);
      return profile?fromCustomAPI(profile):stationSettings;
    }
    if (saved && ['deepseek','qwen','zhipu'].includes(saved.provider)
      && typeof saved.model==='string' && typeof saved.key==='string') return saved;
  } catch { /* A blocked store leaves the station default available. */ }
  return stationSettings;
}

export function persistCustomAPIs(profiles:CustomAPI[]) {
  if (profiles.length>maxCustomAPIs || !profiles.every(isCustomAPI)) throw new Error('配置无效或超过 3 组。');
  localStorage.setItem(customAPIStorageKey,JSON.stringify(profiles));
}

export function modelRequest(settings:ModelSettings) {
  return {provider:settings.provider,model:settings.model,
    ...(settings.provider==='custom'?{base_url:settings.base_url,protocol:settings.protocol}:{})};
}
