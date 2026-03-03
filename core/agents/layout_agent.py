from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json
import os
import re

class LayoutAgent:
    def __init__(self, output_dir="artifacts/final"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _clean_title(self, title):
        """剥离标题中的手动编号。"""
        if not title: return ""
        patterns = [r'^[0-9\.]+\s+', r'^[一二三四五六七八九十百]+、\s*', r'^第[一二三四五六七八九十百]+章\s*']
        for p in patterns:
            title = re.sub(p, '', title)
        return title.strip()

    def generate_word(self, task_id, toc, nodes_text, images_meta_map=None, template_path="template/standard_template.docx", style_profile=None):
        if images_meta_map is None: images_meta_map = {}
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"找不到原生模板: {template_path}")
        
        doc = Document(template_path)
        global_image_counter = 1
        
        # 严格映射：优先使用用户确认存在的中文样式名
        STYLE_MAP = {
            1: '一级标题',
            2: '二级标题',
            3: '三级标题',
            4: '四级标题',
            'body': 'Normal',
            'table': 'BiddingTable'
        }
        
        def process_node(node, level):
            nonlocal global_image_counter
            node_id = node.get('node_id')
            node_content = nodes_text.get(node_id)
            
            # 确定当前标题层级样式
            style_name = STYLE_MAP.get(min(level, 4), '三级标题')
            
            clean_title = self._clean_title(node.get('title', ''))
            if clean_title:
                doc.add_paragraph(clean_title, style=style_name)
            
            if node_content:
                node_images = images_meta_map.get(node_id, [])
                for section in node_content.get('sections', []):
                    # 正文中的小节标题，由于已经在 L3 节点下，我们通常使用 四级标题 或 三级标题
                    h_text = self._clean_title(section.get('h', ''))
                    if h_text:
                        doc.add_paragraph(h_text, style=STYLE_MAP[4])
                    
                    # 插入表格
                    if section.get('table_ref'):
                        table = doc.add_table(rows=3, cols=3)
                        table.style = STYLE_MAP['table']
                        data = [['序号', '核心能力', 'V3 标准'], ['1', '样式绑定', '中文原生'], ['2', '排版质量', '完美渲染']]
                        for r in range(3):
                            for c in range(3): table.cell(r, c).text = data[r][c]

                    # 插入正文
                    text = section.get('text', '')
                    if text:
                        p_text = doc.add_paragraph(text, style=STYLE_MAP['body'])
                        # 重难点高亮处理
                        if "重难点" in section.get('h', ''):
                            for run in p_text.runs:
                                run.font.color.rgb = RGBColor(255, 0, 0)
                                run.bold = True

                    # 插入图片
                    for img_meta in node_images:
                        doc.add_paragraph()
                        p_img = doc.add_paragraph()
                        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        img_path = img_meta.get('file')
                        if img_path and os.path.exists(img_path):
                            p_img.add_run().add_picture(img_path, width=Inches(5.0))
                        
                        doc.add_paragraph(f"图 {global_image_counter} {img_meta.get('caption', '')}", style=STYLE_MAP['body']).alignment = WD_ALIGN_PARAGRAPH.CENTER
                        global_image_counter += 1
                        
            for child in node.get('children', []):
                process_node(child, level + 1)

        for node in toc.get('tree', []):
            process_node(node, 1)
            
        output_path = os.path.join(self.output_dir, f"{task_id}_v3_rendering.docx")
        doc.save(output_path)
        return output_path
