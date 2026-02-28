from src.agents.base_agent import BaseAgent

class ConsistencyCheckAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Consistency Check Agent")
        
        self.system_prompt = """你是项目方案全局校验专家。
检查以下生成数据的全局逻辑：
1. 甘特图时间与 Plan/Content 描述是否冲突。
2. 所有需求子系统是否均有对应的 Plan。
3. 设备型号和品牌在各章节是否一致。
4. 图片方案是否出现逻辑重复。

输入：全流程生成数据的汇总 JSON。
输出 JSON：
- conflicts: 冲突列表。
- suggestions: 修改建议。
- score: 方案整体质量分。
"""

    def run(self, final_data: dict) -> dict:
        print(f"[{self.name}] 正在进行全局逻辑校验...")
        user_prompt = f"""全部生成数据汇总如下：
{final_data}
请进行一致性检查。"""
        
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 全局校验完成。")
        return result_json
