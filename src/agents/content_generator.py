from src.agents.base_agent import BaseAgent

class ContentGeneratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Content Generator Agent")
        
        self.system_prompt = """你是施工动作规划专家。
根据 Plan JSON，生成该计划对应的具体施工动作 Content。
要求：
1. 每个 Content 必须是具体的、可执行的。
2. 每个 Content 的细化程度应足够支撑约 2 页 A4 技术细化。
3. 包含内容：
   - content_id: 动作唯一 ID
   - title: 动作标题（例如：光缆敷设施工、机柜安装施工等）
   - diagram_prompts: 该 Content 需要生成的 2-3 张图的描述。
输出 JSON 列表。
"""

    def run(self, plan_json: dict) -> dict:
        print(f"[{self.name}] 正在生成动作级施工内容...")
        user_prompt = f"""Plan JSON 数据: {plan_json}
请生成细化动作 Content。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 动作级施工内容生成完成。")
        return result_json
