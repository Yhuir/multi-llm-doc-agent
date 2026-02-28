from src.agents.base_agent import BaseAgent

class TechnicalDetailAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Technical Detail Agent")
        
        self.system_prompt = """你是工程施工方案专家。
根据提供的施工动作 Content，生成深度技术细化文本。
要求：
1. 字数必须充足（目标约 1800-2000 字），覆盖约 2 页 A4 内容。
2. 使用专业术语，内容详实。
3. 必须包含以下标准结构：
  - 一、工程概述
  - 二、设备与材料清单（包含规格型号、数量、品牌，表格形式展示）
  - 三、工具与仪器配置（列表展示）
  - 四、施工人员组织与职责
  - 五、详细施工流程与步骤
  - 六、关键技术控制要点
  - 七、质量控制与检查措施
  - 八、安全文明施工措施
  - 九、风险分析与应急预案
  - 十、关键重难点分析（需包含 <红色加粗>关键重难点</红色加粗> 标记）

输出格式为 Markdown 或纯文本，确保逻辑清晰。
"""

    def run(self, content_json: dict) -> str:
        print(f"[{self.name}] 正在为动作 [{content_json.get('title')}] 生成深度技术方案...")
        user_prompt = f"""施工动作信息如下：
{content_json}
请生成完整的技术细化文本。"""
        
        # 使用 generate_text 获得长文本
        text = self.llm.generate_text(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        print(f"[{self.name}] 技术方案生成完成。")
        return text
