from src.agents.base_agent import BaseAgent

class PlanGeneratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Plan Generator Agent")
        
        self.system_prompt = """你是工程阶段与动作规划专家。
根据子系统的进度数据，生成该子系统的阶段级 Plan 及其具体包含的施工动作 Contents。

输出 JSON，包含一个 "plans" 列表，每个计划包含：
- plan_id: 唯一标识
- title: 计划标题 (如：施工准备、设备安装、调试等)
- duration: 该阶段持续时间
- objective: 阶段目标
- contents: 列表，每个包含：
  - title: 具体施工动作标题 (如：现场勘察、光缆铺设、熔接测试等)
  - summary: 简短的动作描述

请确保逻辑顺序合理，动作描述详尽且符合实际工程逻辑。
"""

    def run(self, subsystem_gantt_json: dict) -> dict:
        print(f"[{self.name}] 正在生成阶段级计划与详细施工动作...")
        user_prompt = f"""子系统进度数据:
{subsystem_gantt_json}
请规划各阶段及其具体施工动作。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 计划与动作规划生成完成。")
        return result_json
