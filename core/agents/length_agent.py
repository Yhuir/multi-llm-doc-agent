import json
from core.models import NodeText
from utils.llm_client import LLMClient

class LengthControlAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def count_words(self, node_text: dict) -> int:
        count = 0
        for section in node_text.get('sections', []):
            if section.get('text'):
                count += len(section['text'])
        return count

    def adjust_length(self, node_text: dict, target_min=1800, target_max=2000, max_retries=2) -> tuple:
        current_text = node_text
        for attempt in range(max_retries + 1):
            word_count = self.count_words(current_text)
            
            if target_min <= word_count <= target_max:
                return current_text, word_count, True
            
            if attempt == max_retries:
                break
                
            if word_count < target_min:
                # 触发补写
                current_text = self._expand_content(current_text)
            elif word_count > target_max:
                # 触发精简
                current_text = self._reduce_content(current_text)
                
        word_count = self.count_words(current_text)
        return current_text, word_count, (target_min <= word_count <= target_max)

    def _expand_content(self, node_text: dict) -> dict:
        system_prompt = """
        你是工程实施方案撰写专家。当前的内容字数不足1800字，请你按以下优先级对各章节进行补充：
        1. 验收步骤（详细说明每个步骤的测试标准，记录表字段）
        2. 参数控制（补充具体的线径、扭矩、弯曲半径、测试阈值等）
        3. 规范条款落地（解释引用的规范是如何在具体施工中落地的）
        4. 风险矩阵（补充更多风险点与应对措施）
        5. 施工记录、旁站留痕要求
        
        要求：
        - 保持原有的10个模块结构不变。
        - 严禁出现Markdown标记！
        - 补充后总字数尽量达到 1850字 以上。
        - 严格返回要求的 JSON 结构。
        """
        
        user_prompt = f"当前节点内容：\n{json.dumps(node_text, ensure_ascii=False)}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=NodeText)
        try:
            return json.loads(response_json_str)
        except Exception:
            return node_text
            
    def _reduce_content(self, node_text: dict) -> dict:
        system_prompt = """
        你是工程实施方案撰写专家。当前内容字数超过2000字，请按“去冗余”策略进行精简：
        - 优先删减空泛的描述、重复的话语。
        - 必须保留硬信息：关键流程、技术参数控制点、验收点、表格字段、风险与安全措施。
        
        要求：
        - 保持原有的10个模块结构不变。
        - 严禁出现Markdown标记！
        - 精简后总字数尽量控制在 1950字 左右。
        - 严格返回要求的 JSON 结构。
        """
        
        user_prompt = f"当前节点内容：\n{json.dumps(node_text, ensure_ascii=False)}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=NodeText)
        try:
            return json.loads(response_json_str)
        except Exception:
            return node_text
