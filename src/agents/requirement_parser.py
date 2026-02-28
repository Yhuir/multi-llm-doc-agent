import os
import json
import subprocess
import platform
from src.agents.base_agent import BaseAgent

class RequirementParserAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Requirement Parser Agent")
        
        self.system_prompt = """你是项目需求解析专家。
解析用户上传的文档内容，提取以下信息：
1. 项目名称
2. 项目建设范围
3. 技术指标
4. 子系统结构
5. 工期要求
6. 强制规范条款
请输出结构化 JSON，字段必须完整，便于后续 Agent 使用。

JSON 结构示例：
{
    "project_name": "...",
    "scope": "...",
    "technical_specs": ["...", "..."],
    "subsystems": ["...", "..."],
    "schedule_requirements": "...",
    "mandatory_standards": ["...", "..."]
}
"""

    def read_document(self, file_path: str) -> str:
        """读取文档内容（支持 .doc, .docx）"""
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".docx":
            return self._read_docx(file_path)
        elif ext == ".doc":
            return self._read_doc(file_path)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _read_docx(self, file_path: str) -> str:
        """读取 .docx 文档"""
        try:
            import docx
            doc = docx.Document(file_path)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return "\n".join(full_text)
        except Exception as e:
            print(f"Error reading docx {file_path}: {e}")
            raise

    def _read_doc(self, file_path: str) -> str:
        """读取 .doc 文档（通过 macOS textutil 或其他转换工具）"""
        print(f"[{self.name}] 检测到 .doc 格式，正在转换...")
        
        # 在 macOS (Darwin) 上使用 textutil
        if platform.system() == "Darwin":
            try:
                # 将 .doc 转换为 .txt 输出到标准输出
                result = subprocess.run(
                    ["textutil", "-convert", "txt", "-stdout", file_path],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result.stdout
            except Exception as e:
                print(f"textutil conversion failed: {e}")
                raise
        else:
            # 针对其他系统的备选方案（如 antiword）
            try:
                result = subprocess.run(
                    ["antiword", file_path],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result.stdout
            except Exception as e:
                raise RuntimeError("'.doc' format requires 'textutil' (macOS) or 'antiword' (Linux). Please upload '.docx' instead.")

    def run(self, doc_path: str) -> dict:
        """
        运行 Agent：读取文档内容并提取需求 JSON。
        """
        print(f"[{self.name}] 正在处理文档: {doc_path}")
        document_text = self.read_document(doc_path)
        
        user_prompt = f"""以下是文档内容，请按要求解析并返回 JSON 格式：

{document_text}"""
        
        print(f"[{self.name}] 正在请求 LLM 解析需求...")
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt, 
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 解析完成。")
        
        return result_json
