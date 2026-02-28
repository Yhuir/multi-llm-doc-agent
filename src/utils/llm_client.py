import os
import json
import base64
import time
from typing import Optional, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

# 2026 最新 Google GenAI SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

load_dotenv()

class LLMClient:
    def __init__(self, model: str = "gemini-3.1-pro-preview"):
        """
        初始化 LLM 客户端。
        完美适配 2026 Gemini 3 开发者指南 及 DeepSeek 国内直连。
        """
        self.model = model
        self.openai_client = None
        self.gemini_client = None

    def _init_client(self):
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise ValueError("未检测到有效 API Key，请在侧边栏配置。")

        # 1. Gemini 3 系列接入
        if "gemini" in self.model.lower():
            if self.gemini_client is None:
                self.gemini_client = genai.Client(api_key=api_key)
        
        # 2. DeepSeek / OpenAI 兼容平台接入
        else:
            if self.openai_client is None:
                # 自动匹配 Base URL
                if "deepseek-ai" in self.model: # SiliconFlow
                    base_url = "https://api.siliconflow.cn/v1"
                elif "deepseek-" in self.model: # DeepSeek 官方
                    base_url = "https://api.deepseek.com"
                else:
                    base_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")

                self.openai_client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    def generate_json(self, system_prompt: str, user_prompt: str, retries: int = 2) -> Dict[str, Any]:
        self._init_client()
        last_error = None
        for attempt in range(retries + 1):
            try:
                if "gemini" in self.model.lower():
                    # 适配 Gemini 3 新规范：Temperature 1.0, JSON Response
                    response = self.gemini_client.models.generate_content(
                        model=self.model,
                        contents=f"{system_prompt}\n\nUSER INPUT:\n{user_prompt}",
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=1.0 
                        )
                    )
                    text = response.text.strip()
                    if text.startswith("```json"): text = text[7:-3].strip()
                    return json.loads(text)
                else:
                    response = self.openai_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                        response_format={"type": "json_object"},
                        temperature=0.2
                    )
                    return json.loads(response.choices[0].message.content)
            except Exception as e:
                last_error = e
                time.sleep(2 * (attempt + 1))
        raise last_error

    def generate_text(self, system_prompt: str, user_prompt: str, retries: int = 2) -> str:
        self._init_client()
        last_error = None
        for attempt in range(retries + 1):
            try:
                if "gemini" in self.model.lower():
                    # 适配 Gemini 3 新特性：thinking_level="high"
                    response = self.gemini_client.models.generate_content(
                        model=self.model,
                        contents=f"{system_prompt}\n\n{user_prompt}",
                        config=types.GenerateContentConfig(
                            temperature=1.0,
                            thinking_config=types.ThinkingConfig(thinking_level="high")
                        )
                    )
                    return response.text
                else:
                    response = self.openai_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                        temperature=0.7
                    )
                    return response.choices[0].message.content
            except Exception as e:
                last_error = e
                time.sleep(2 * (attempt + 1))
        raise last_error

    def generate_image(self, prompt: str, output_path: str) -> str:
        """调用豆包 (Ark) 接口生成 4K 高清图"""
        api_key = os.getenv("ARK_API_KEY")
        mid = os.getenv("ARK_MODEL_ID")
        if not api_key or not mid: return ""
        try:
            img_client = OpenAI(api_key=api_key, base_url="https://ark.cn-beijing.volces.com/api/v3")
            response = img_client.images.generate(
                model=mid,
                prompt=f"Professional engineering illustration, high detail, 4K: {prompt}",
                response_format="b64_json"
            )
            image_data = base64.b64decode(response.data[0].b64_json)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f: f.write(image_data)
            return output_path
        except: return ""
