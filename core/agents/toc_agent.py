import json
from datetime import datetime
from core.models import TOC
from utils.llm_client import LLMClient

class TOCGeneratorAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate(self, parsed_req: dict) -> dict:
        system_prompt = """
        You are a senior engineering manager. Your task is to generate a structured Table of Contents (TOC) 
        for an engineering implementation plan based on the provided project requirements.
        
        Rules:
        1. The TOC MUST strictly follow a 4-level structure to match Chinese engineering document standards:
           - Level 1: Main Phases (一级目录，如：设备安装与改造阶段)
           - Level 2: Subsystem (子系统，如：制冷站电控系统升级)
           - Level 3: Task Group (二级目录，如：保护性拆除)
           - Level 4: Execution Node (三级目录，如：拆除旧PLC机架、CPU、通讯模块)
        2. Level 4 (Execution Nodes) is the minimum generation unit. Each MUST be a specific, executable task.
        3. If a Phase doesn't naturally have subsystems (like Project Management), create a generic logical grouping (e.g. "Overall Management") as the Level 2 Subsystem to maintain the 4-level structure.
        4. Return strictly in JSON matching the schema provided.
        """
        
        user_prompt = f"Parsed Requirements:\n{json.dumps(parsed_req, ensure_ascii=False, indent=2)}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=TOC)
        
        try:
            toc_data = json.loads(response_json_str)
            toc_data["version"] = 1
            toc_data["generated_at"] = datetime.utcnow().isoformat()
            return toc_data
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return {"version": 1, "generated_at": datetime.utcnow().isoformat(), "tree": []}

class TOCReviewAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def revise(self, current_toc: dict, user_feedback: str) -> dict:
        system_prompt = """
        You are a senior engineering manager. The user has provided feedback on the current Table of Contents.
        Apply the user's feedback to modify the TOC. Ensure it strictly remains a 4-level structure: 
        Level 1 (Phase) -> Level 2 (Subsystem) -> Level 3 (Task Group) -> Level 4 (Execution Node).
        Return strictly in JSON matching the schema provided.
        """
        
        user_prompt = f"Current TOC:\n{json.dumps(current_toc, ensure_ascii=False, indent=2)}\n\nUser Feedback: {user_feedback}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=TOC)
        
        try:
            new_toc = json.loads(response_json_str)
            new_toc["version"] = current_toc.get("version", 1) + 1
            new_toc["generated_at"] = datetime.utcnow().isoformat()
            return new_toc
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return current_toc
