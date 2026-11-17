import type { CSSProperties } from 'react';
import type { Resume } from '../lib/types';
import template from '../../../shared/template.json';

export default function ResumePreview({resume,zoom='fit'}:{resume:Resume;zoom?:'fit'|'actual'}) {
  const styles = {'--resume-width':`${template.pageWidthMm}mm`,'--resume-padding':`${template.marginMm}mm`,'--resume-body':`${template.bodyPt}pt`,'--resume-heading':`${template.headingPt}pt`,'--resume-name':`${template.namePt}pt`,'--resume-line':template.lineHeight} as CSSProperties;
  const sections=[...resume.sections].sort((a,b)=>template.sectionOrder.indexOf(a.kind)-template.sectionOrder.indexOf(b.kind));
  return <div className="preview-scroll"><article className={'resume-preview '+zoom} style={styles} aria-label="导出简历内容预览">
    {sections.map(section=><section key={section.id} className={'resume-section '+section.kind}>
      {section.kind!=='contact'&&<h2>{section.title}</h2>}
      {section.blocks.map((block,i)=><p key={block.id} className={[block.kind==='bullet'?'resume-bullet':'',section.kind==='contact'&&i===0&&block.text.length<=24?'resume-name':'',block.kind==='heading'?'resume-subheading':''].join(' ')}>{block.text}</p>)}
    </section>)}
  </article></div>;
}
