import json
from core.models import NodeText
from utils.llm_client import LLMClient

class SectionWriterAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def write_node(self, node_info: dict, parsed_req: dict, template_text: str = "") -> dict:
        system_prompt = """
        你是工程实施方案撰写专家。请严格按指定JSON结构输出，不要输出任何Markdown符号（如 #, *, -, |, 等）。
        你的任务是为一个具体的三级目录节点撰写详细的工程实施方案正文。
        
        必须包含以下10个模块，按此顺序生成：
        1. 工程概述
        2. 设备与材料清单 (如果需要表格，请在 text 里留空，并在 table_ref 里指定引用)
        3. 工具与仪器配置
        4. 人员组织与岗位职责
        5. 施工流程说明 (详细，不少于400字)
        6. 技术控制要点 (详细，不少于400字)
        7. 质量控制措施 (详细，不少于350字)
        8. 安全施工措施 (详细，不少于350字)
        9. 风险分析与应对 (详细，不少于350字)
        10. 关键重难点 (这部分文本将由后续程序标红加粗)

        要求：
        - 语气：专业工程实施方案风格，可执行，可验收。
        - 禁止出现Markdown标记！
        - 总字数尽量超过1800字。
        """
        
        user_prompt = f"""
        任务节点信息：
        节点ID: {node_info.get('node_id')}
        节点标题: {node_info.get('title')}
        层级信息: {json.dumps(node_info, ensure_ascii=False)}
        
        全局需求参考：
        {json.dumps(parsed_req.get('scope', {}), ensure_ascii=False)[:2000]}
        
        模板参考（学习其结构和专业术语，但必须针对当前任务写）：
        {template_text[:1000]}
        """
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=NodeText)
        
        try:
            return json.loads(response_json_str)
        except Exception as e:
            print(f"Error parsing writer JSON: {e}")
            return {
                "node_id": node_info.get('node_id'),
                "title": node_info.get('title'),
                "sections": []
            }
