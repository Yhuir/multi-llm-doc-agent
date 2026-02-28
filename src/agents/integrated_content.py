from src.agents.base_agent import BaseAgent
import json
import re

class IntegratedContentAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Integrated Content Agent")
        
        self.system_prompt = """你是顶级工程方案设计专家。
你的任务是根据一个施工计划 Plan 及其包含的多个具体施工动作 Contents，生成一份深度、完整且字数极其丰富的工程技术方案章节。

### 核心任务要求：
1. **内容深度与长度**：
   - 针对提供的每一个 Content，生成极其详尽的技术步骤、材料清单、规范引用和重难点分析。
   - 总字数必须达到 3000-5000 字以上（整章规模），确保能够直接用于标书或施工组织设计。
2. **结构化输出**：
   - 使用 Markdown 格式。每个 Content 标题作为一个二级标题。
   - 每个子章节必须包含标准十项（概述、清单、配置、人员、流程、控制点、质量措施、安全、风险、重难点）。
3. **内置配图建议**：
   - 在每个 Content 章节生成完毕后，紧接着插入一个 JSON 代码块，包含配图指令。
   - 格式如下：```json
{"images": [{"prompt": "...", "caption": "..."}]}
```
   - 配图必须与文字内容高度相关，无需外部校验。
4. **字数填充技巧**：
   - 大量引用国家标准（如 GB/T, JGJ 等）。
   - 细化施工环境准备工作。
   - 增加详尽的设备参数对比表描述。

### 严禁事项：
- 严禁输出概括性语言。
- 严禁出现“此处略”或“详见...”等描述。
"""

    def run(self, plan_title: str, contents: list) -> str:
        print(f"[{self.name}] 正在为计划 [{plan_title}] 批量生成 (包含 {len(contents)} 个动作) 技术方案...")
        
        user_prompt = f"""
计划标题：{plan_title}
包含的施工动作列表：
{json.dumps(contents, ensure_ascii=False, indent=2)}

请一次性生成完整的技术方案章节，包含所有动作的细节和配图建议。"""
        
        # 针对长文本开启思考模式，Gemini 3 会更认真地补全字数
        full_text = self.llm.generate_text(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt
        )
        
        print(f"[{self.name}] 整章集成方案生成完成 (长度: {len(full_text)})。")
        return full_text

    def parse_images(self, text: str) -> list:
        # 解析文本中嵌入的 JSON 配图块
        image_list = []
        # 使用正则表达式匹配 JSON 块，改用三引号处理跨行模式
        matches = re.findall(r"```json\n(.*?)\n```", text, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                if "images" in data:
                    image_list.extend(data["images"])
            except:
                continue
        return image_list
