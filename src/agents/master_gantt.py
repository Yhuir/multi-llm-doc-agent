from src.agents.base_agent import BaseAgent

class MasterGanttAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Master Gantt Agent")
        
        self.system_prompt = """你是总体进度规划专家。
根据提供的项目需求 JSON，生成项目总体甘特图数据。
要求输出结构化 JSON，包含以下字段：
1. gantt_data: 包含阶段(stage)、开始日期(start)、结束日期(end)、任务(tasks)的列表。
2. mermaid_code: 完整的 Mermaid 甘特图代码。
3. milestones: 关键里程碑列表。

确保甘特图逻辑严密，覆盖项目全周期。
"""

    def run(self, project_reqs: dict) -> dict:
        print(f"[{self.name}] 正在生成总体进度计划...")
        user_prompt = f"""项目需求信息如下：
{project_reqs}
请生成总体甘特图数据。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 总体进度计划生成完成。")
        return result_json
