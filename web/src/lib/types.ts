export type Dimension = 'structure' | 'content' | 'relevance';
export type Block = { id: string; text: string; kind: 'paragraph' | 'bullet' | 'heading' };
export type Section = { id: string; kind: 'contact' | 'education' | 'experience' | 'projects' | 'skills' | 'other'; title: string; blocks: Block[] };
export type Resume = { sections: Section[]; warnings: string[]; estimated_pages: number | null; rendered_pages?: number | null; page_count_verified: boolean };
export type Suggestion = {
 id: string; dimension: Dimension; title: string; priority: 'P0'|'P1'|'P2'|'P3';
 target_block_id: string|null; resume_quote: string; jd_quote: string; reason: string;
 rewrite: string; needs_fact: boolean; question: string; decision: 'pending'|'accepted'|'skipped';
 edited_text: string|null; user_fact: string; target_section_id: string|null;
};
export type Session = {
 id:string; created_at:number; last_active:number; expires_at:number;
 state:'parsed'|'analyzing'|'ready'|'partial'|'failed'|'answering'|'interrupted';
 resume: Resume; jd:string; suggestions:Suggestion[]; dimensions:Record<string,string>;
 error:string|null; revision:number;
};
export type ModelSettings = {provider:string; model:string; key:string};
export type Configuration = {station_configured:boolean; providers:{id:string;name:string}[]; upload_bytes:number; idle_seconds:number; hard_seconds:number; development:boolean};
