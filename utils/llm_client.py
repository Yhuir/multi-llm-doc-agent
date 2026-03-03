import os
import time
import requests
import json
from google import genai
from google.genai import types
import httpx
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self, provider="volcengine-deepseek"):
        self.provider = provider
        self.ark_api_key = os.getenv("ARK_API_KEY", "")
        self.doubao_base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.doubao_model = os.getenv("ARK_CHAT_MODEL", "ep-20260302152925-62nm8")
        self.volc_base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.volc_model = os.getenv("ARK_DEEPSEEK_MODEL", "deepseek-v3-2-251201")
        self.deepseek_base_url = "https://api.deepseek.com/chat/completions"
        self.deepseek_model = "deepseek-reasoner"
        self.httpx_client = httpx.Client(http2=False, timeout=180.0)

    def _get_gemini_client(self):
        api_key = os.getenv("GEMINI_API_KEY")
        return genai.Client(
            api_key=api_key,
            http_options={'api_version': 'v1alpha', 'httpx_client': self.httpx_client}
        )

    def _retry_request(self, func, *args, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"[{self.provider} Attempt {attempt+1}/{max_retries}] API Error: {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 * (attempt + 1))

    def generate_json(self, system_prompt: str, user_prompt: str, response_schema=None):
        """生成 JSON，修复 max_tokens 冲突"""
        
        if self.provider == "volcengine-deepseek":
            def _make_volc_call():
                api_key = os.getenv("ARK_API_KEY")
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                
                payload = {
                    "model": self.volc_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    # 关键修复：不要同时设置这两个参数
                    # "max_tokens": 4096, 
                    "max_completion_tokens": 8192, 
                    "temperature": 1.0,
                    "thinking": {"type": "enabled"}
                }
                
                if response_schema and hasattr(response_schema, "model_json_schema"):
                    payload["messages"][1]["content"] += f"\n\n请严格返回如下 JSON 结构，不要包含任何 Markdown 格式，只返回 JSON 字符串：\n{json.dumps(response_schema.model_json_schema(), ensure_ascii=False)}"

                response = requests.post(self.volc_base_url, headers=headers, json=payload, timeout=300, proxies={"http": None, "https": None})
                
                # 如果 400 报错，可能是因为模型不支持 thinking 或 max_completion_tokens
                if response.status_code == 400:
                    error_msg = response.text
                    print(f"⚠️ 初始请求失败，尝试降级兼容模式... 详情: {error_msg}")
                    
                    # 降级：改回 max_tokens，去掉 thinking
                    payload.pop("max_completion_tokens", None)
                    payload.pop("thinking", None)
                    payload["max_tokens"] = 4096
                    payload["temperature"] = 0.7
                    
                    response = requests.post(self.volc_base_url, headers=headers, json=payload, timeout=300, proxies={"http": None, "https": None})

                if response.status_code != 200:
                    print(f"❌ 火山引擎 API 最终报错: {response.text}")
                    raise Exception(f"API Error {response.status_code}: {response.text}")
                
                res_json = response.json()
                content = res_json['choices'][0]['message']['content']
                return self._clean_markdown(content)
            
            return self._retry_request(_make_volc_call)

        if self.provider == "gemini-2.5-pro":
            def _make_gemini_call():
                client = self._get_gemini_client()
                config = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=response_schema if response_schema else None
                )
                response = client.models.generate_content(model='gemini-2.5-pro', contents=user_prompt, config=config)
                return response.text
            return self._retry_request(_make_gemini_call)

        def _make_openai_call():
            api_key = os.getenv("DEEPSEEK_API_KEY") if self.provider == "deepseek-reasoner" else os.getenv("ARK_API_KEY")
            base_url = self.deepseek_base_url if self.provider == "deepseek-reasoner" else self.doubao_base_url
            model = self.deepseek_model if self.provider == "deepseek-reasoner" else self.doubao_model
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            full_user_prompt = user_prompt
            if response_schema and hasattr(response_schema, "model_json_schema"):
                full_user_prompt += f"\n\n请严格返回如下 JSON 结构：\n{json.dumps(response_schema.model_json_schema(), ensure_ascii=False)}"

            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": full_user_prompt}],
                "temperature": 1.0 if self.provider == "deepseek-reasoner" else 0.2,
                "max_tokens": 4096
            }
            response = requests.post(base_url, headers=headers, json=payload, timeout=240, proxies={"http": None, "https": None})
            response.raise_for_status()
            res_json = response.json()
            return self._clean_markdown(res_json['choices'][0]['message']['content'])

        return self._retry_request(_make_openai_call)

    def _clean_markdown(self, content):
        content = content.strip()
        if content.startswith("```json"): content = content[7:]
        elif content.startswith("```"): content = content[3:]
        if content.endswith("```"): content = content[:-3]
        return content.strip()

    def generate_text(self, system_prompt: str, user_prompt: str):
        return self.generate_json(system_prompt, user_prompt)
