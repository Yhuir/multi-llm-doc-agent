import os
import requests
import json
import urllib3
import time
from dotenv import load_dotenv

# 禁用安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 加载环境变量
load_dotenv()

def download_image(url, save_path, max_retries=3):
    """带重试机制的图片下载函数"""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"📥 正在下载 {save_path} (第 {attempt}/{max_retries} 次尝试)...")
            # 使用 verify=False 解决部分环境下的 SSL 问题
            img_res = requests.get(url, verify=False, timeout=60)
            if img_res.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(img_res.content)
                print(f"🎉 {save_path} 保存完成！")
                return True
            else:
                print(f"⚠️ 下载失败，状态码: {img_res.status_code}")
        except Exception as e:
            print(f"⚠️ 下载过程中出现异常: {e}")
        
        if attempt < max_retries:
            wait_time = 3 * attempt
            print(f"🔄 将在 {wait_time} 秒后重试下载...")
            time.sleep(wait_time)
            
    return False

def generate_step_poster(step_index, step_title, step_content, api_key, model_id, base_url):
    print(f"\n🎨 正在生成第 {step_index} 步: {step_title}...")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    prompt = (
        f"帮我生成一张流程海报图片，主题为：PLC拆除标准流程。内容为第 {step_index} 步：{step_title}。具体步骤描述如下：{step_content}。"
        "要求：工业风、高科技感、结构清晰、步骤编号明显、适合施工现场张贴。海报上要有醒目的数字编号。构图平衡，视觉效果专业。"
    )

    payload = {
        "model": model_id,
        "prompt": prompt,
        "response_format": "url",
        "size": "2K",
        "stream": False
    }

    try:
        response = requests.post(
            base_url, 
            headers=headers, 
            json=payload, 
            timeout=180,
            proxies={"http": None, "https": None}
        )
        
        if response.status_code != 200:
            print(f"❌ 第 {step_index} 步生成请求失败，状态码: {response.status_code}")
            return None

        data = response.json()
        if 'data' in data and len(data['data']) > 0:
            image_url = data['data'][0]['url']
            print(f"✅ 第 {step_index} 步图片已生成！")
            print(f"🔗 预览地址: {image_url}")

            # 调用带重试机制的下载函数
            save_path = f"step_{step_index}.png"
            success = download_image(image_url, save_path)
            
            if not success:
                print(f"❌ 第 {step_index} 步图片下载最终失败，请手动通过浏览器下载预览地址。")
            return save_path if success else None
        else:
            print(f"❌ 未能获取到图片 URL")

    except Exception as e:
        print(f"❌ 生成过程中出现异常: {e}")
    return None

def main():
    api_key = os.getenv("ARK_API_KEY")
    base_url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    model_id = "ep-20260303111621-m5cqp"
    
    if not api_key:
        print("❌ 错误：未找到 ARK_API_KEY，请检查 .env 文件。")
        return

    steps = [
        ("断电与验电", "1.办理停电工作票；2.断开PLC柜主电源开关（Q01），挂警示牌；3.使用万用表确认电压为0V；4.等待5分钟电容放电。"),
        ("标记与记录", "1.两人配合贴标签并记录；2.标记电源线、通讯线、I/O线；3.多角度拍摄柜内全景、模块特写等；4.填写《PLC模块拆除记录表》。"),
        ("拆除通讯线缆", "1.拆除以太网线并加防尘帽；2.拆除Profibus线并保护接口；3.拆除RS485线并绝缘包扎。"),
        ("拆除CPU模块", "1.取出备份电池并装袋；2.松开卡扣垂直拔出模块；3.放入防静电袋贴标签；4.放入泡沫箱。"),
        ("拆除通讯模块", "1.按顺序拆除1756-ENBT模块；2.立即放入防静电袋贴标签；3.记录原插槽位置。"),
        ("拆除电源模块", "1.确认线缆已拆除；2.松开螺丝垂直拔出模块；3.放入防静电袋并贴标签。"),
        ("拆除机架", "1.检查固定连接；2.使用内六角扳手拆除螺栓；3.两人配合小心取下机架；4.检查插针并包装。"),
        ("清理与封堵", "1.吸尘器清理柜内灰尘；2.用防火泥封堵穿线孔；3.扎带理顺剩余线缆。")
    ]

    print(f"🚀 开始批量生成并下载 8 张流程海报...")
    for i, (title, content) in enumerate(steps, 1):
        generate_step_poster(i, title, content, api_key, model_id, base_url)
    
    print("\n✅ 所有任务处理完毕！")

if __name__ == "__main__":
    main()
