from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import json
import os

class LayoutAgent:
    def __init__(self, output_dir="artifacts/final"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _set_font_style(self, run, font_name="宋体", size_pt=12, bold=False, color=None):
        run.font.name = font_name
        # For setting east asian font in docx
        run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
        run.font.size = Pt(size_pt)
        run.bold = bold
        if color:
            run.font.color.rgb = color

    def generate_word(self, task_id: str, toc: dict, nodes_text: dict) -> str:
        """
        nodes_text: Dict mapping node_id to NodeText dictionary
        """
        from docx.oxml.ns import qn
        
        doc = Document()
        
        # We will iterate through the TOC and print headers, then append node text if it's a level 3 node.
        
        def process_node(node, level):
            # Heading
            if level == 1:
                h = doc.add_heading(node['title'], level=1)
                for run in h.runs:
                    run.font.name = '黑体'
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
            elif level == 2:
                h = doc.add_heading(node['title'], level=2)
                for run in h.runs:
                    run.font.name = '黑体'
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
            elif level == 3:
                h = doc.add_heading(node['title'], level=3)
                for run in h.runs:
                    run.font.name = '黑体'
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
            elif level == 4:
                h = doc.add_heading(node['title'], level=4)
                for run in h.runs:
                    run.font.name = '黑体'
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                    
                # Append text if we have generated content for this level 4 node
                node_content = nodes_text.get(node['node_id'])
                if node_content:
                    for section in node_content.get('sections', []):
                        p_h = doc.add_paragraph()
                        r_h = p_h.add_run(section.get('h', ''))
                        r_h.font.name = '黑体'
                        r_h._element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
                        r_h.bold = True
                        
                        text = section.get('text', '')
                        if text:
                            p = doc.add_paragraph()
                            r = p.add_run(text)
                            r.font.name = '宋体'
                            r._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
                            
                            # Handle "关键重难点"
                            if "重难点" in section.get('h', ''):
                                r.font.color.rgb = RGBColor(255, 0, 0)
                                r.bold = True

            for child in node.get('children', []):
                process_node(child, level + 1)
                
        for node in toc.get('tree', []):
            process_node(node, 1)
            
        output_path = os.path.join(self.output_dir, f"{task_id}_output.docx")
        doc.save(output_path)
        return output_path
