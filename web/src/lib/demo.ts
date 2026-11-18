import type { Resume, Session, Suggestion } from './types';

export const sampleJD = '产品经理实习生：能够进行需求分析，并将需求转化为产品原型。参与用户访谈，梳理业务流程，与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。有校园项目经历者优先。';
export function demoSession(): Session {
  const suggestions: Suggestion[] = [
    { id:'demo-fact', dimension:'relevance', title:'补充需求沟通的具体经历', priority:'P0', target_block_id:null, resume_quote:'', jd_quote:'与设计和研发同学沟通需求', reason:'岗位要求包含需求沟通，可以补充你与团队协作的具体做法。', rewrite:'', needs_fact:true, question:'在这个项目中，你怎样向设计或开发同学说明需求？如果没有相关经历，直接跳过。', decision:'pending', edited_text:null, user_fact:'', target_section_id:null },
    { id:'demo-action', dimension:'content', title:'让个人行动更容易被看见', priority:'P1', target_block_id:'b4', resume_quote:'访谈同学并整理需求，梳理发布和检索流程，完成平台原型。', jd_quote:'能够进行需求分析，并将需求转化为产品原型', reason:'先交代校园交易场景，再说明需求分析、流程梳理和原型设计，能让项目经历更清楚。', rewrite:'围绕校园二手交易场景，访谈同学并整理需求；梳理物品发布与检索流程，输出产品原型。', needs_fact:false, question:'', decision:'pending', edited_text:null, user_fact:'', target_section_id:null },
  ];
  return {id:'demo', created_at:Date.now()/1000, last_active:Date.now()/1000, expires_at:Date.now()/1000+7200, state:'ready', jd:sampleJD, revision:1, error:null, dimensions:{structure:'complete', content:'complete', relevance:'complete'}, suggestions,
    resume:{estimated_pages:1, page_count_verified:false, warnings:[], sections:[
      {id:'contact',kind:'contact',title:'基本信息',blocks:[{id:'b1',kind:'paragraph',text:'陈同学'},{id:'b2',kind:'paragraph',text:'应届毕业生 · 产品经理方向'}]},
      {id:'edu',kind:'education',title:'教育经历',blocks:[{id:'b3',kind:'paragraph',text:'示例大学 · 信息管理与信息系统 · 本科'}]},
      {id:'project',kind:'projects',title:'项目经历',blocks:[{id:'project-title',kind:'heading',text:'校园二手交易平台｜课程项目'},{id:'b4',kind:'paragraph',text:'访谈同学并整理需求，梳理发布和检索流程，完成平台原型。'}]},
      {id:'skills',kind:'skills',title:'技能',blocks:[{id:'b5',kind:'paragraph',text:'需求整理、流程梳理、低保真原型、团队协作'}]},
    ]}};
}
export function applyDemo(session: Session): Resume {
  const resume = structuredClone(session.resume);
  for (const s of session.suggestions.filter(s=>s.decision==='accepted')) {
    const text = s.edited_text ?? s.rewrite;
    for (const section of resume.sections) for (const b of section.blocks) if (b.id===s.target_block_id) b.text=text;
    if (s.user_fact) resume.sections.find(section=>section.id===s.target_section_id)?.blocks.push({id:'new-'+s.id,kind:'bullet',text});
  }
  return resume;
}
