import os
import time
import requests
import urllib3
import json
from dotenv import load_dotenv

# 禁用安全请求警告（针对 verify=False）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

class DoubaoClient:
    def __init__(self):
        # 强力直连：清理代理环境变量
        for env_key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
            if env_key in os.environ:
                del os.environ[env_key]

        # 文本模型接入点
        self.chat_base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.chat_model = os.getenv("ARK_CHAT_MODEL", "ep-20260302152925-62nm8")
        
        # 图片模型接入点 (豆包 Seedream)
        self.image_base_url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        self.image_model = os.getenv("ARK_IMAGE_MODEL", "ep-20260303111621-m5cqp")

    def _retry_request(self, func, *args, **kwargs):
        """通用网络请求重试装饰器"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"[Doubao Attempt {attempt+1}/{max_retries}] API Error: {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 * (attempt + 1))

    def generate_json(self, system_prompt: str, user_prompt: str, response_schema=None):
        """生成结构化文本 JSON"""
        def _make_call():
            api_key = os.getenv("ARK_API_KEY")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            prompt = user_prompt
            if response_schema:
                prompt += "\n\n请严格返回如下 JSON 结构，不要包含 markdown 代码块包裹，只返回 JSON 本身：\n"
                prompt += str(response_schema.model_json_schema())
                
            payload = {
                "model": self.chat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }
            
            response = requests.post(
                self.chat_base_url, 
                headers=headers, 
                json=payload, 
                timeout=120, 
                proxies={"http": None, "https": None}
            )
            response.raise_for_status()
            res_json = response.json()
            
            content = res_json['choices'][0]['message']['content']
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return content.strip()

        return self._retry_request(_make_call)

    def generate_image(self, prompt: str, size: str = "2K") -> str:
        """调用文生图 API 返回图片 URL"""
        def _make_call():
            api_key = os.getenv("ARK_API_KEY")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            payload = {
                "model": self.image_model,
                "prompt": prompt,
                "response_format": "url",
                "size": size,
                "stream": False
            }

            response = requests.post(
                self.image_base_url,
                headers=headers,
                json=payload,
                timeout=180,
                proxies={"http": None, "https": None}
            )
            response.raise_for_status()
            data = response.json()
            if 'data' in data and len(data['data']) > 0:
                return data['data'][0]['url']
            return None

        return self._retry_request(_make_call)

    def download_image(self, url: str, save_path: str, max_retries: int = 3) -> bool:
        """带重试机制的下载函数，绕过 SSL 校验"""
        for attempt in range(1, max_retries + 1):
            try:
                # 确保父目录存在
                os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
                
                # 直连下载，不走代理，解决 SSL EOF 问题
                img_res = requests.get(url, verify=False, timeout=60, proxies={"http": None, "https": None})
                if img_res.status_code == 200:
                    with open(save_path, "wb") as f:
                        f.write(img_res.content)
                    return True
                else:
                    print(f"⚠️ 图片下载失败，状态码: {img_res.status_code}")
            except Exception as e:
                print(f"⚠️ 下载尝试 {attempt}/{max_retries} 失败: {e}")
            
            if attempt < max_retries:
                time.sleep(3 * attempt)
        return False
