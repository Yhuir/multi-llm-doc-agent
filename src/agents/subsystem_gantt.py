from src.agents.base_agent import BaseAgent

class SubsystemGanttAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Subsystem Gantt Agent")
        
        self.system_prompt = """你是子系统施工进度专家。
根据项目总体甘特图数据和子系统名称，生成该子系统的细化进度计划。
要求输出 JSON，包含以下字段：
1. subsystem_name: 子系统名称。
2. start_date, end_date: 子系统的施工起止日期。
3. tasks: 该子系统的细化任务列表。
4. dependencies: 标注对其他子系统或前置工序的依赖。
5. mermaid_code: 该子系统的细化的 Mermaid 甘特图代码。
"""

    def run(self, master_gantt_json: dict, subsystem_name: str) -> dict:
        print(f"[{self.name}] 正在细化子系统 [{subsystem_name}] 的进度...")
        user_prompt = f"""总体进度 JSON: {master_gantt_json}
子系统名称: {subsystem_name}
请生成细化进度。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 子系统 [{subsystem_name}] 进度细化完成。")
        return result_json
