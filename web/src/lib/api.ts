export class ApiError extends Error {
 constructor(public code:string, message:string, public status:number){super(message);}
}
export async function request<T>(path:string, options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers);
 if(options.method && options.method !== 'GET') headers.set('X-Resume-Client','web');
 if(options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
 const response=await fetch(path,{...options,headers,credentials:'same-origin'});
 if(!response.ok){
  let problem={code:'NETWORK_ERROR',message:'连接暂时中断，请检查网络后重试。'};
  try{problem=await response.json();}catch{/* Static reverse-proxy errors have no JSON. */}
  throw new ApiError(problem.code,problem.message,response.status);
 }
 if(response.status===204)return undefined as T;
 return await response.json() as T;
}
export function modelHeaders(key:string):Record<string,string>{return key?{'X-LLM-Key':key}:{};}
export async function download(path:string){
 const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'X-Resume-Client':'web'}});
 if(!response.ok){const error=await response.json();throw new ApiError(error.code,error.message,response.status);}
 const blob=await response.blob();
 const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download='简历.docx';link.click();
 window.setTimeout(()=>URL.revokeObjectURL(url),2000);
}
