import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv
import httpx

load_dotenv()

class LLMClient:
    def __init__(self):
        # 初始化客户端。关闭 HTTP/2（http2=False），避免与 Mac 本地 VPN/代理的底层连接产生冲突
        # 新版 SDK 的 HttpOptions 支持传入 httpx_client
        custom_client = httpx.Client(http2=False)
        
        self.client = genai.Client(
            http_options={'api_version': 'v1alpha', 'httpx_client': custom_client}
        )

    def _retry_request(self, func, *args, **kwargs):
        """Helper to retry request on RemoteProtocolError / network disconnects."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 针对代理/VPN常出现的断连等网络异常重试
                print(f"[Attempt {attempt+1}/{max_retries}] API Error: {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 * (attempt + 1))  # Exponential backoff

    def generate_json(self, system_prompt: str, user_prompt: str, response_schema=None):
        """
        Generate a JSON response from Gemini
        """
        config_args = {
            "system_instruction": system_prompt,
            "temperature": 0.2,
            "response_mime_type": "application/json",
        }
        
        if response_schema:
             config_args["response_schema"] = response_schema
             
        config = types.GenerateContentConfig(**config_args)
        
        def _make_call():
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=config
            )
            return response.text

        return self._retry_request(_make_call)

    def generate_text(self, system_prompt: str, user_prompt: str):
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
        )
        def _make_call():
            response = self.client.models.generate_content(
                model='gemini-2.5-pro',
                contents=user_prompt,
                config=config
            )
            return response.text

        return self._retry_request(_make_call)
