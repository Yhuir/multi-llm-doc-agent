import os
import time
import requests
import json
import urllib3
from google import genai
from google.genai import types
import httpx
from dotenv import load_dotenv

# 禁用全局 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

class LLMClient:
    def __init__(self, provider="volcengine-deepseek"):
        self.provider = provider
        
        # --- 强力直连保障：清理当前进程的代理环境变量 ---
        for env_key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            if env_key in os.environ:
                del os.environ[env_key]

        self.ark_api_key = os.getenv("ARK_API_KEY", "")
        # ... (保持原有地址定义)
        self.volc_base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.volc_model = os.getenv("ARK_DEEPSEEK_MODEL", "deepseek-v3-2-251201")
        
        self.doubao_base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.doubao_model = os.getenv("ARK_CHAT_MODEL", "ep-20260302152925-62nm8")
        
        self.deepseek_base_url = "https://api.deepseek.com/chat/completions"
        self.deepseek_model = "deepseek-reasoner"
        
        # httpx 必须设置 trust_env=False 才会忽略 Mac 系统代理设置
        self.httpx_client = httpx.Client(http2=False, timeout=300.0, verify=False, trust_env=False)

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
                if attempt == max_retries - 1: raise e
                time.sleep(3 * (attempt + 1))

    def generate_json(self, system_prompt: str, user_prompt: str, response_schema=None):
        """增强版 JSON 生成，强制绕过代理，忽略 SSL，设置超长上限"""
        
        if self.provider == "volcengine-deepseek":
            def _make_volc_call():
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.ark_api_key}"}
                
                payload = {
                    "model": self.volc_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    # 设置更大的补全长度 (思考+正文总上限)，防止截断导致 JSON 损坏
                    "max_completion_tokens": 16384, 
                    "temperature": 1.0,
                    "thinking": {"type": "enabled"}
                }
                
                if response_schema and hasattr(response_schema, "model_json_schema"):
                    payload["messages"][1]["content"] += f"\n\n请直接输出纯 JSON，不要包含任何推理思维链，务必确保 JSON 结构闭合：\n{json.dumps(response_schema.model_json_schema(), ensure_ascii=False)}"

                # 强制 verify=False 且不走任何代理，解决 SSL EOF 和长连接中断问题
                response = requests.post(
                    self.volc_base_url, 
                    headers=headers, 
                    json=payload, 
                    timeout=300, 
                    verify=False,
                    proxies={"http": None, "https": None} 
                )
                
                if response.status_code == 400:
                    print("⚠️ 尝试普通模式...")
                    payload.pop("thinking", None)
                    payload["temperature"] = 0.7
                    response = requests.post(self.volc_base_url, headers=headers, json=payload, timeout=300, verify=False, proxies={"http": None, "https": None})

                response.raise_for_status()
                res_json = response.json()
                return self._clean_markdown(res_json['choices'][0]['message']['content'])
            return self._retry_request(_make_volc_call)

        # Gemini 逻辑
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

        # OpenAI 协议模型 (DeepSeek 官网/豆包)
        def _make_openai_call():
            is_ds = (self.provider == "deepseek-reasoner")
            api_key = os.getenv("DEEPSEEK_API_KEY") if is_ds else os.getenv("ARK_API_KEY")
            base_url = self.deepseek_base_url if is_ds else self.doubao_base_url
            model = self.deepseek_model if is_ds else self.doubao_model
            
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                "temperature": 1.0 if is_ds else 0.2,
                "max_tokens": 4096
            }
            response = requests.post(base_url, headers=headers, json=payload, timeout=240, verify=False, proxies={"http": None, "https": None})
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
