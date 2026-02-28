import os
import base64
import requests
import uuid

def render_mermaid_to_png(mermaid_code: str, output_dir: str = "data/images") -> str:
    """
    将 Mermaid 代码转换为 PNG 图片路径。
    使用 mermaid.ink 服务进行云渲染。
    """
    if not mermaid_code:
        return ""
    
    try:
        # 1. 对代码进行 Base64 编码
        encoded_string = base64.b64encode(mermaid_code.encode('utf-8')).decode('ascii')
        
        # 2. 构建渲染 URL (支持自定义样式)
        render_url = f"https://mermaid.ink/img/{encoded_string}"
        
        # 3. 发起请求获取图片内容
        os.makedirs(output_dir, exist_ok=True)
        img_filename = f"mermaid_{str(uuid.uuid4())[:8]}.png"
        img_path = os.path.join(output_dir, img_filename)
        
        response = requests.get(render_url, timeout=15)
        if response.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(response.content)
            print(f"[Mermaid] 渲染成功: {img_path}")
            return img_path
        else:
            print(f"[Mermaid] 渲染失败，状态码: {response.status_code}")
            return ""
    except Exception as e:
        print(f"[Mermaid] 渲染出错: {e}")
        return ""
