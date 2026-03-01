import json
import os
import subprocess
from docx import Document
from core.models import ParsedRequirement
from utils.llm_client import LLMClient

class RequirementParserAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract_text(self, file_path: str) -> str:
        # If the file is .doc, try to convert it to .docx first (Mac specific workaround)
        if file_path.lower().endswith('.doc'):
            docx_path = file_path + 'x'
            if not os.path.exists(docx_path):
                try:
                    # using textutil built-in on macOS
                    subprocess.run(['textutil', '-convert', 'docx', '-output', docx_path, file_path], check=True)
                except Exception as e:
                    print(f"Warning: .doc to .docx conversion failed using textutil: {e}")
                    raise ValueError("无法解析旧版 .doc 格式，请将文件另存为 .docx 后重新上传。")
            file_path = docx_path

        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    def parse(self, docx_path: str) -> dict:
        text = self.extract_text(docx_path)
        
        # In a real app, if text is too long, we might need to chunk it.
        # Assuming the document is reasonable size for a single LLM call for now.
        system_prompt = """
        You are a senior system architect. Your task is to parse the user's project requirements document.
        Extract the project name, customer, duration, milestones, scope, subsystems, requirements, and constraints.
        Respond STRICTLY in JSON format matching the schema provided.
        """
        
        user_prompt = f"Document content:\n{text[:30000]}..." # Truncating for safety in prototype
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=ParsedRequirement)
        
        try:
            return json.loads(response_json_str)
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            print(response_json_str)
            return {}
