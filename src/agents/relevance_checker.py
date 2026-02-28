from src.agents.base_agent import BaseAgent

class RelevanceCheckerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Image-Text Relevance Agent")
        
        self.system_prompt = """你是图文一致性检查专家。
校验给定的技术细化文本与推荐图片方案的一致性。
任务：
1. 检查每张图片是否与技术文本内容强关联。
2. 识别内容无关或逻辑冲突的图片。
3. 输出 JSON，包含：
   - results: 列表，每个包含 image_id, status (Pass/Fail), reason。
   - overall_status: Pass/Fail。
"""

    def run(self, technical_detail_text: str, image_list: list) -> dict:
        print(f"[{self.name}] 正在校验图文一致性...")
        user_prompt = f"""技术文本：
{technical_detail_text}
图片方案：
{image_list}
请进行校验。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 图文一致性校验完成。")
        return result_json
