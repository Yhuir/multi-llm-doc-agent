from src.agents.base_agent import BaseAgent

class LengthControlAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Length Control Agent")
        
        self.system_prompt = """你是方案审核专家。
检查提供的技术细化文本。
要求：
1. 计算字数（中文字符数）。
2. 如果字数不足 1800，请根据全文逻辑补充内容。
补充方向：
- 增加施工中的国家/行业标准引用。
- 详细化设备参数描述。
- 增加更细化的施工质量验收标准表格内容。
- 细化风险预警与应对矩阵。
输出补全后的完整文本。
"""

    def run(self, technical_detail_text: str) -> str:
        word_count = len(technical_detail_text)
        print(f"[{self.name}] 当前动作技术文本字数为: {word_count}")
        
        if word_count >= 1800:
            print(f"[{self.name}] 字数符合要求。")
            return technical_detail_text
        else:
            print(f"[{self.name}] 字数不足 1800，正在补充...")
            user_prompt = f"""以下文本字数不足 1800，请补充更多施工细化细节、规范引用和标准，使其达到 1800 字以上。

{technical_detail_text}"""
            
            completed_text = self.llm.generate_text(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt
            )
            print(f"[{self.name}] 文本补充完成，最终字数约为: {len(completed_text)}")
            return completed_text
