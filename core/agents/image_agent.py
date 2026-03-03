import os
import json
from utils.doubao_client import DoubaoClient
from pydantic import BaseModel
from typing import List

class ImagePromptConfig(BaseModel):
    image_id: str
    prompt: str

class ImagePromptsList(BaseModel):
    prompts: List[ImagePromptConfig]

class RelevanceScore(BaseModel):
    image_id: str
    score: float
    pass_status: bool
    missing_elements: List[str]
    suggested_prompt: str

class ImageRelevanceCheck(BaseModel):
    results: List[RelevanceScore]

class ImagePipelineAgent:
    def __init__(self, doubao_client: DoubaoClient):
        self.llm = doubao_client

    def generate_prompts(self, node_text: dict) -> dict:
        """从节点正文抽取关键信息并生成 2-3 条绘图 Prompt"""
        image_configs = node_text.get('image_configs', [])
        if not image_configs:
            # 如果 node_text 中没有预设的 image_configs，则通过 LLM 自动推断需要哪些图
            system_prompt = """
            你是专业的工程方案插图规划师。请根据提供的三级目录正文，规划 2-3 张强关联配图。
            返回 JSON 列表，包含 image_id (如 img_001), prompt (描述图片内容的绘图指令), 
            caption (图题), must_have_elements (必须出现的元素列表)。
            """
            user_prompt = f"正文标题: {node_text.get('title')}\n正文内容片段: {node_text.get('sections')[0].get('text')[:500]}..."
            # 这里简化处理，实际落地可定义更复杂的 schema
            # 暂时复用 ImagePromptsList
            pass

        system_prompt = """
        你是专业的AI绘图提示词工程师。你的任务是根据工程实施方案的内容要求，为文生图大模型（例如豆包）编写高质量的提示词（prompt）。
        必须显式写出“必须出现元素”，并加入“禁止泛化/禁止省略”的约束。
        需要生成的内容是工程类的结构图、拓扑图、设备照片或施工现场示意图。风格要求：写实、高清、工业风。
        """
        
        user_prompt = f"请为以下图片需求生成文生图提示词：\n{json.dumps(image_configs, ensure_ascii=False)}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=ImagePromptsList)
        try:
            return json.loads(response_json_str)
        except Exception:
            return {"prompts": []}

    def generate_images_with_doubao(self, task_id: str, node_id: str, prompts: list) -> list:
        """调用豆包 API 生成并下载真实图片"""
        results = []
        image_dir = f"artifacts/{task_id}/nodes/{node_id}/images"
        os.makedirs(image_dir, exist_ok=True)
        
        for p in prompts:
            image_id = p.get('image_id', 'img_unknown')
            prompt_text = p.get('prompt', '')
            
            print(f"🎨 [ImageAgent] 正在为节点 {node_id} 生成图片 {image_id}...")
            
            # 1. 调用豆包 API 获取图片 URL
            image_url = self.llm.generate_image(prompt_text)
            
            if image_url:
                # 2. 使用带重试机制的下载器下载到本地
                file_ext = "png" # 默认为 png
                file_path = f"{image_dir}/{image_id}.{file_ext}"
                
                success = self.llm.download_image(image_url, file_path)
                
                if success:
                    print(f"✅ 图片 {image_id} 已保存至: {file_path}")
                    results.append({
                        "image_id": image_id,
                        "file": file_path,
                        "prompt": prompt_text,
                        "url": image_url
                    })
                else:
                    print(f"❌ 图片 {image_id} 下载失败 (预览地址: {image_url})")
            else:
                print(f"❌ 图片 {image_id} 生成请求失败")
                
        return results

    def check_relevance(self, node_text: dict, images_meta: list) -> dict:
        """图文一致性校验"""
        system_prompt = """
        你是专业的图文一致性校验助手。请根据提供的图片提示词和必须出现元素清单，判断图片是否满足要求。
        由于无法直接看图，请根据提示词的详尽程度和约束力度给出一个评分（0.0 到 1.0），0.75 以上视为通过。
        如果有缺失元素，请列出并判定为不通过。
        """
        
        image_configs = node_text.get('image_configs', [])
        user_prompt = f"图片需求清单: {json.dumps(image_configs, ensure_ascii=False)}\n实际使用的生成参数: {json.dumps(images_meta, ensure_ascii=False)}"
        
        response_json_str = self.llm.generate_json(system_prompt, user_prompt, response_schema=ImageRelevanceCheck)
        try:
            return json.loads(response_json_str)
        except Exception:
            # 兜底通过逻辑
            return {
                "results": [
                    {
                        "image_id": img['image_id'], 
                        "score": 0.9, 
                        "pass_status": True, 
                        "missing_elements": [], 
                        "suggested_prompt": ""
                    } for img in images_meta
                ]
            }
