import json
import urllib.request
from urllib.error import URLError, HTTPError

# --- 配置区 ---
TARGET_URL = "https://api.frankfurter.app/2024-01-01?from=USD&to=CNY"
PROXY_ADDR = "http://127.0.0.1:6244"  # 你的代理地址
USE_PROXY = True  # 是否启用代理进行测试

def test_request():
    print(f"开始测试请求: {TARGET_URL}")
    print(f"代理状态: {'启用' if USE_PROXY else '禁用'} ({PROXY_ADDR})")
    print("-" * 30)

    # 1. 准备 Header（解决 403 的关键）
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # 2. 配置代理 Handler
        if USE_PROXY:
            proxy_handler = urllib.request.ProxyHandler({'http': PROXY_ADDR, 'https': PROXY_ADDR})
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()

        # 3. 构建 Request 对象并添加 Header
        req = urllib.request.Request(TARGET_URL, headers=headers)

        # 4. 发起请求
        with opener.open(req, timeout=10) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            print(f"✅ 请求成功！状态码: {status}")
            print("响应内容:")
            print(json.dumps(json.loads(body), indent=4, ensure_ascii=False))

    except HTTPError as e:
        print(f"❌ 发生 HTTP 错误: {e.code} {e.reason}")
        print("提示: 403 通常是因为缺少 User-Agent 或代理节点被封禁。")
    except URLError as e:
        print(f"❌ 发生网络错误: {e.reason}")
        print("提示: 请检查本地代理服务 (127.0.0.1:6244) 是否已开启。")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")

if __name__ == "__main__":
    test_request()