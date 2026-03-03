import json
from core.models import NodeText
from utils.llm_client import LLMClient

class SectionWriterAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def write_node(self, node_info: dict, parsed_req: dict, template1_text: str = "", template2_text: str = "") -> dict:
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

        约束与要求：
        - 语气：专业工程实施方案风格，可执行，可验收。
        - 严禁出现Markdown标记！
        - 总字数必须在 1850-1950 之间（为了给后续补写和精简留出缓冲）。
        - 请模仿模板写作风格，但不得复用模板任何目录标题与句子；目录与内容必须来自 requirement.json 与 toc 节点信息。
        - 需要提供 2–3 条图片生成所需的关键信息（实体/必须元素/绑定段落锚点），这些配置请放在 image_configs 数组中。每一条配置包括 image_id, bind_anchor (段落小节名或关键句), must_have_elements (必须出现元素清单)。
        """
        
        user_prompt = f"""
        任务节点信息：
        节点ID: {node_info.get('node_id')}
        节点标题: {node_info.get('title')}
        层级信息: {json.dumps(node_info, ensure_ascii=False)}
        
        全局需求参考：
        {json.dumps(parsed_req.get('scope', {}), ensure_ascii=False)[:2000]}
        
        模板参考1（主风格基准：昆烟范本，学习其结构、密度、验收/记录表写法）：
        {template1_text[:1000] if template1_text else "无"}
        
        模板参考2（技术写法补充：施组PDF，学习其工艺细化、术语、质量安全措辞）：
        {template2_text[:1000] if template2_text else "无"}
        """
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=NodeText)
        
        try:
            return json.loads(response_json_str)
        except Exception as e:
            print(f"Error parsing writer JSON: {e}")
            return {
                "node_id": node_info.get('node_id'),
                "title": node_info.get('title'),
                "sections": [],
                "image_configs": []
            }
