import json
import os
import fitz  # PyMuPDF
from typing import Dict, List
from core.models import StyleProfile
from utils.llm_client import LLMClient

class StyleExtractorAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract_pdf_style_data(self, pdf_path: str) -> str:
        """
        Extract a summary of fonts, sizes, and colors from the PDF.
        We don't need every single span, just a representative sample.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Template PDF not found: {pdf_path}")

        doc = fitz.open(pdf_path)
        style_samples = []
        
        # Limit to first few pages to avoid overwhelming the LLM
        max_pages = min(10, len(doc))
        
        for i in range(max_pages):
            page = doc[i]
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            # Clean up font name (often includes subsets like ABCDEF+FontName)
                            font_name = s["font"]
                            if "+" in font_name:
                                font_name = font_name.split("+")[-1]
                            
                            # Convert color to hex
                            # fitz color is an int: (R << 16) + (G << 8) + B
                            color_int = s["color"]
                            r = (color_int >> 16) & 255
                            g = (color_int >> 8) & 255
                            b_val = color_int & 255
                            hex_color = f"#{r:02X}{g:02X}{b_val:02X}"
                            
                            sample = {
                                "text": s["text"][:100],
                                "font": font_name,
                                "size": round(s["size"], 1),
                                "color": hex_color,
                                "flags": s["flags"] # can detect bold/italic
                            }
                            style_samples.append(sample)
                            
                            # Limit samples per page
                            if len(style_samples) > 200 * (i + 1):
                                break
        doc.close()
        
        # Convert to string for LLM
        return json.dumps(style_samples[:1000], ensure_ascii=False)

    def generate_style_profile(self, pdf_path: str) -> StyleProfile:
        style_data = self.extract_pdf_style_data(pdf_path)
        
        system_prompt = """
        You are a document design expert. Analyze the provided font and style data from a reference PDF.
        Your goal is to extract a 'Style Profile' that captures the visual identity of the document.
        
        Key elements to identify:
        - Palette: Primary colors for titles, headings, and emphasis.
        - Fonts: The main Chinese font (e.g., 宋体), fallback, and mono.
        - Sizes: Typical point sizes for document title, H1, H2, H3, body, and captions.
        - Paragraph: Line spacing, indentation, and spacing before/after headings.
        - Table: Standard table styles (header bold, center, borders).
        - Image: Layout preferences (width, alignment, caption styles).
        
        Note: If the data doesn't explicitly show paragraph spacing or line spacing, use industry standards for professional engineering documents (e.g., 1.5 line spacing, 2 chars indent).
        
        Respond STRICTLY in JSON format matching the StyleProfile schema.
        """
        
        user_prompt = f"Extracted style samples from PDF:\n{style_data}\n\nPlease generate the StyleProfile JSON."
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=StyleProfile)
        
        try:
            return StyleProfile.model_validate_json(response_json_str)
        except Exception as e:
            print(f"Error validating StyleProfile JSON: {e}")
            # Fallback to a default if parsing fails
            return self.get_default_style_profile()

    def get_default_style_profile(self) -> StyleProfile:
        return StyleProfile(
            palette={
                "title": "#C00000", "h1": "#0B7A6B", "h2": "#000000",
                "em_blue": "#1F4E79", "em_green": "#00B050", "em_red": "#C00000",
                "table_header_fill": "#D9EAF7", "caption": "#C00000"
            },
            fonts={"cn": "宋体", "fallback": "微软雅黑", "mono": "Consolas"},
            sizes={
                "doc_title_pt": 16, "h1_pt": 14, "h2_pt": 13, "h3_pt": 12,
                "body_pt": 12, "caption_pt": 10.5
            },
            paragraph={
                "line_spacing": 1.0, "first_line_indent_chars": 2,
                "space_before_pt": {"h1": 12, "h2": 10, "h3": 8, "body": 0},
                "space_after_pt": {"h1": 6, "h2": 6, "h3": 4, "body": 0}
            },
            table={
                "header_bold": True, "header_center": True, "repeat_header": True,
                "borders": "single", "cell_padding_pt": 3
            },
            image={
                "default_width_in": 5.0, "max_width_in": 6.2, "align": "center",
                "caption_enabled_default": True, "caption_color": "#C00000",
                "grid": {"enabled": True, "max_images": 8, "layout_candidates": ["2x4", "4x2"], "cell_padding_pt": 2}
            }
        )
