from src.agents.base_agent import BaseAgent
import os
import uuid

class DiagramImageAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Diagram & Image Generation Agent")
        
        self.system_prompt = """你是工程绘图专家。
根据技术文本，生成 2-3 张强关联图片的生成指令（Prompt）。
图片应有助于理解施工流程、系统架构或技术原理。

输出 JSON，字段如下：
1. images: 列表，每个包含：
   - prompt: 详细的绘图描述（建议使用工程专业词汇）
   - caption: 图片标题
"""

    def run(self, technical_detail_text: str) -> dict:
        print(f"[{self.name}] 正在生成绘图方案与图片...")
        user_prompt = f"技术细化文本如下：\n{technical_detail_text}\n请生成绘图 Prompt。"
        
        # 1. 获取绘图 Prompt
        result_json = self.llm.generate_json(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        
        # 2. 调用 豆包/Ark API 真实生图
        os.makedirs("data/images", exist_ok=True)
        for img in result_json.get("images", []):
            prompt = img.get("prompt")
            # 生成唯一文件名
            file_id = str(uuid.uuid4())[:8]
            output_path = f"data/images/img_{file_id}.png"
            
            # 调用真实的生图方法
            print(f"[{self.name}] 正在调用豆包生成图片: {img.get('caption')}...")
            real_path = self.llm.generate_image(prompt, output_path)
            img["source"] = real_path
            
        print(f"[{self.name}] 图片生成完成。")
        return result_json
