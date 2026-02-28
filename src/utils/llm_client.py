import os
import json
import base64
import time
import hashlib
from typing import Optional, Dict, Any, List
from openai import OpenAI
from dotenv import load_dotenv

# 2026 最新 Google GenAI SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

load_dotenv()

CACHE_DIR = "outputs/generation_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

class LLMClient:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.openai_client = None
        self.gemini_client = None
        # 锁定官方推荐且经过验证的备选池
        self.available_gemini_models = [
            "gemini-2.5-flash", 
            "gemini-2.5-flash-lite",
            "gemini-3.0-flash", 
            "gemini-2.5-pro"
        ]
        self.available_openai_models = [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"
        ]

    def _get_cache_path(self, system_prompt: str, user_prompt: str) -> str:
        content = f"{self.model}{system_prompt}{user_prompt}"
        h = hashlib.md5(content.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{h}.json")

    def _ensure_client(self, model_name: str):
        """根据模型名称动态确保对应的客户端已初始化"""
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            return

        # 1. Gemini / Gemma 系列
        if "gemini" in model_name.lower() or "gemma" in model_name.lower():
            if self.gemini_client is None:
                self.gemini_client = genai.Client(api_key=api_key)
        
        # 2. OpenAI 系列或其他兼容平台
        else:
            if self.openai_client is None:
                if "gpt-" in model_name.lower():
                    base_url = "https://api.openai.com/v1"
                elif "deepseek-ai" in model_name: 
                    base_url = "https://api.siliconflow.cn/v1"
                elif "deepseek-" in model_name:
                    base_url = "https://api.deepseek.com"
                else:
                    base_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")

                self.openai_client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    def generate_json(self, system_prompt: str, user_prompt: str, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache:
            cache_path = self._get_cache_path(system_prompt, user_prompt)
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        # 构造重试列表
        models_to_try = [self.model]
        if "gpt-" in self.model.lower():
            models_to_try += [m for m in self.available_openai_models if m != self.model]
        else:
            models_to_try += [m for m in self.available_gemini_models if m != self.model]
        
        last_error = None
        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    self._ensure_client(model_name)
                    if "gemini" in model_name.lower() or "gemma" in model_name.lower():
                        prompt = f"{system_prompt}\n\nUSER INPUT:\n{user_prompt}"
                        response = self.gemini_client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0)
                        )
                        result = json.loads(response.text)
                    else:
                        response = self.openai_client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                            response_format={"type": "json_object"},
                            temperature=0.2
                        )
                        result = json.loads(response.choices[0].message.content)
                    
                    if use_cache:
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                    return result
                except Exception as e:
                    last_error = e
                    if any(x in str(e).lower() for x in ["429", "limit", "exhausted"]):
                        break 
                    time.sleep(2)
        raise last_error

    def generate_text(self, system_prompt: str, user_prompt: str, use_cache: bool = True) -> str:
        if use_cache:
            cache_path = self._get_cache_path(system_prompt, user_prompt) + ".txt"
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    return f.read()

        models_to_try = [self.model]
        if "gpt-" in self.model.lower():
            models_to_try += [m for m in self.available_openai_models if m != self.model]
        else:
            models_to_try += [m for m in self.available_gemini_models if m != self.model]

        last_error = None
        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    self._ensure_client(model_name)
                    if "gemini" in model_name.lower() or "gemma" in model_name.lower():
                        full_response = []
                        for chunk in self.gemini_client.models.generate_content_stream(
                            model=model_name,
                            contents=f"{system_prompt}\n\n{user_prompt}",
                            config=types.GenerateContentConfig(temperature=1.0, max_output_tokens=8192)
                        ):
                            if chunk.text: full_response.append(chunk.text)
                        result = "".join(full_response)
                    else:
                        response = self.openai_client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                            temperature=0.7
                        )
                        result = response.choices[0].message.content
                    
                    if use_cache:
                        cache_path = self._get_cache_path(system_prompt, user_prompt) + ".txt"
                        with open(cache_path, "w", encoding="utf-8") as f: f.write(result)
                    return result
                except Exception as e:
                    last_error = e
                    if any(x in str(e).lower() for x in ["429", "limit", "exhausted"]):
                        break
                    time.sleep(2)
        raise last_error

    def generate_image(self, prompt: str, output_path: str) -> str:
        ark_api_key = os.getenv("ARK_API_KEY")
        ark_mid = os.getenv("ARK_MODEL_ID")
        if not ark_api_key: return ""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            img_client = OpenAI(api_key=ark_api_key, base_url="https://ark.cn-beijing.volces.com/api/v3")
            response = img_client.images.generate(model=ark_mid, prompt=prompt, response_format="b64_json")
            image_data = base64.decodebytes(response.data[0].b64_json.encode())
            with open(output_path, "wb") as f: f.write(image_data)
            return output_path
        except: return ""
