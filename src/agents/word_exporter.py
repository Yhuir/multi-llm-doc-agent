import os
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

class WordExporterAgent:
    def __init__(self):
        self.name = "Layout & Word Export Agent"

    def run(self, final_data: dict, output_path: str = "outputs/工程实施方案.docx"):
        print(f"[{self.name}] 正在开始排版导出 Word...")
        doc = Document()
        
        # 项目名称 (大标题)
        title = project_info = final_data.get("project_info", {}).get("project_name", "工程实施方案")
        doc.add_heading(title, 0)
        
        # 子系统循环
        for sub in final_data.get("subsystem_details", []):
            # 一级标题：子系统名称
            h1 = doc.add_heading(sub["name"], level=1)
            
            for plan in sub.get("plans", []):
                # 二级标题：阶段名称
                doc.add_heading(plan["plan_title"], level=2)
                
                for content in plan.get("contents", []):
                    # 三级标题：动作名称
                    doc.add_heading(content["title"], level=3)
                    
                    # 正文
                    para = doc.add_paragraph(content["text"])
                    style = doc.styles['Normal']
                    style.font.name = '宋体'
                    style.font.size = Pt(10.5) # 小四
                    
                    # 图片方案占位 (由于无法真实获取图片，仅输出图片占位说明)
                    for img in content.get("images", []):
                        img_para = doc.add_paragraph(f"[此处插入图片: {img.get('caption')}]")
                        img_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        desc_para = doc.add_paragraph(f"(图片描述: {img.get('content_description')})")
                        desc_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # 自动生成目录在实际 docx 中比较复杂，这里仅保存文件
        doc.save(output_path)
        print(f"[{self.name}] Word 文档导出成功: {output_path}")
        return output_path
