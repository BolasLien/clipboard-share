#!/usr/bin/env python3
import argparse
import http.server
import json
import socket
import subprocess
import sys
from urllib.parse import parse_qs

DEFAULT_PORT = 8000

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 連接外部地址以確定路由出口 IP（不實際發送封包）
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def copy_to_macos_clipboard(text: str):
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)

def get_macos_clipboard() -> str:
    try:
        return subprocess.check_output(['pbpaste'], text=True)
    except Exception:
        return ""

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>跨裝置剪貼簿同步</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --subtext: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --success: #10b981;
      --border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      padding: 16px;
      display: flex;
      justify-content: center;
      min-height: 100vh;
    }
    .container {
      width: 100%;
      max-width: 520px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .header {
      text-align: center;
      padding: 12px 0;
    }
    .header h1 {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.025em;
    }
    .header p {
      font-size: 0.85rem;
      color: var(--subtext);
      margin-top: 4px;
    }
    .card {
      background-color: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .card-title {
      font-size: 0.95rem;
      font-weight: 600;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    textarea {
      width: 100%;
      height: 140px;
      background: #0b1120;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      padding: 12px;
      font-size: 15px;
      resize: vertical;
      outline: none;
      font-family: inherit;
    }
    textarea:focus {
      border-color: var(--primary);
    }
    .btn-group {
      display: flex;
      gap: 8px;
    }
    button {
      flex: 1;
      background-color: var(--primary);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 12px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: background 0.15s;
    }
    button:active {
      transform: scale(0.98);
    }
    button.secondary {
      background-color: #334155;
    }
    button.secondary:hover {
      background-color: #475569;
    }
    .toast {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: #059669;
      color: white;
      padding: 10px 20px;
      border-radius: 9999px;
      font-size: 14px;
      font-weight: 500;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      transition: transform 0.25s ease;
      pointer-events: none;
      z-index: 100;
    }
    .toast.show {
      transform: translateX(-50%) translateY(0);
    }
    .qr-box {
      text-align: center;
      padding: 8px 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
    }
    .qr-box img {
      width: 160px;
      height: 160px;
      border-radius: 8px;
      background: #fff;
      padding: 6px;
    }
    .badge {
      font-size: 11px;
      background: #0284c7;
      color: #fff;
      padding: 2px 8px;
      border-radius: 9999px;
    }
    .code-block {
      background: #0b1120;
      padding: 8px 12px;
      border-radius: 6px;
      font-family: monospace;
      font-size: 12px;
      color: #38bdf8;
      word-break: break-all;
    }
  </style>
</head>
<body>

<div class="container">
  <div class="header">
    <h1>📋 跨裝置剪貼簿</h1>
    <p>Android 手機 ⇄ Mac 電腦快速同步</p>
  </div>

  <!-- 手機傳給 Mac -->
  <div class="card">
    <div class="card-title">
      <span>📱 傳送文字至 Mac 剪貼簿</span>
      <span class="badge">同步至 pbcopy</span>
    </div>
    <textarea id="textToSend" placeholder="請在此貼上手機複製的文字..."></textarea>
    <div class="btn-group">
      <button type="button" class="secondary" id="btnPaste">📋 讀取並貼上</button>
      <button type="button" id="btnSend">🚀 送到 Mac</button>
    </div>
  </div>

  <!-- 從 Mac 讀取目前剪貼簿 -->
  <div class="card">
    <div class="card-title">
      <span>💻 Mac 剪貼簿內容</span>
      <button type="button" class="secondary" style="flex: 0; padding: 4px 10px; font-size: 12px;" id="btnRefresh">🔄 重新整理</button>
    </div>
    <textarea id="textFromMac" readonly placeholder="點擊重新整理以讀取 Mac 剪貼簿目前內容..."></textarea>
    <button type="button" class="secondary" id="btnCopyFromMac">📄 複製到本裝置</button>
  </div>

  <!-- QR Code 供其他裝置掃描 -->
  <div class="card qr-box" id="qrCard">
    <div style="font-size: 13px; color: var(--subtext);">手機掃碼直接開啟此網頁：</div>
    <div class="code-block" id="currentUrl"></div>
    <img id="qrImage" alt="QR Code" />
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  const fullUrl = window.location.origin;
  document.getElementById('currentUrl').innerText = fullUrl;
  document.getElementById('qrImage').src = 'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=' + encodeURIComponent(fullUrl);

  function showToast(msg, bg = '#059669') {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.style.background = bg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2000);
  }

  // 送出文字到 Mac
  document.getElementById('btnSend').addEventListener('click', async () => {
    const text = document.getElementById('textToSend').value;
    if (!text) {
      showToast('請先輸入或貼上文字', '#e11d48');
      return;
    }
    try {
      const res = await fetch('/api/clipboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text })
      });
      const data = await res.json();
      if (data.ok) {
        showToast('✅ 已成功複製到 Mac 剪貼簿！');
        fetchMacClipboard();
      } else {
        showToast('❌ 同步失敗: ' + (data.error || '未知錯誤'), '#e11d48');
      }
    } catch (err) {
      showToast('❌ 連線錯誤', '#e11d48');
    }
  });

  // 嘗試使用手機瀏覽器 Clipboard API 自動貼上
  document.getElementById('btnPaste').addEventListener('click', async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const clipText = await navigator.clipboard.readText();
        document.getElementById('textToSend').value = clipText;
        showToast('已取得手機剪貼簿內容');
      } else {
        document.getElementById('textToSend').focus();
        showToast('請長按輸入框選擇「貼上」', '#334155');
      }
    } catch (err) {
      document.getElementById('textToSend').focus();
      showToast('請長按輸入框選擇「貼上」', '#334155');
    }
  });

  // 取得 Mac 剪貼簿內容
  async function fetchMacClipboard() {
    try {
      const res = await fetch('/api/clipboard');
      const data = await res.json();
      document.getElementById('textFromMac').value = data.content || '';
    } catch (err) {
      console.error(err);
    }
  }

  document.getElementById('btnRefresh').addEventListener('click', () => {
    fetchMacClipboard();
    showToast('已刷新 Mac 剪貼簿內容');
  });

  // 複製 Mac 剪貼簿到手機
  document.getElementById('btnCopyFromMac').addEventListener('click', async () => {
    const text = document.getElementById('textFromMac').value;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast('✅ 已複製到手機剪貼簿！');
    } catch (err) {
      showToast('❌ 複製失敗，請手動全選複製', '#e11d48');
    }
  });

  // 初次載入自動拉取一次
  fetchMacClipboard();
</script>

</body>
</html>
"""

class ClipboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 覆寫日誌輸出以保持終端乾淨
        print(f"[HTTP] {self.command} {self.path} -> {args[1]}")

    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        elif self.path == '/api/clipboard':
            clip_content = get_macos_clipboard()
            res_data = json.dumps({'content': clip_content}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(res_data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/clipboard':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8', errors='ignore')
            try:
                data = json.loads(body)
                content = data.get('content', '')
                copy_to_macos_clipboard(content)
                preview = (content[:50] + '...') if len(content) > 50 else content
                print(f"\n⚡ [Mac 剪貼簿已更新]: {preview}\n")
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port: int = DEFAULT_PORT, auto_open: bool = False):
    local_ip = get_local_ip()
    server_address = ('0.0.0.0', port)
    httpd = http.server.ThreadingHTTPServer(server_address, ClipboardHandler)
    
    url = f"http://{local_ip}:{port}"
    print("=" * 55)
    print("🚀 剪貼簿同步服務已啟動！")
    print("=" * 55)
    print(f"👉 請確保手機與 Mac 連接同一個 Wi-Fi")
    print(f"👉 手機 Chrome 請開啟網址：\n   \033[1;32m{url}\033[0m")
    print(f"👉 Mac 本機可開啟：\n   http://localhost:{port}")
    print("=" * 55)
    print("等待傳送中... (按 Ctrl + C 可隨時結束服務)\n")

    if auto_open:
        try:
            subprocess.run(['open', f'http://localhost:{port}'], check=False)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服務已停止。")
        sys.exit(0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Cross-device Clipboard Sync (Android/iOS ⇄ macOS)")
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help=f"服務監聽通訊埠 (預設: {DEFAULT_PORT})")
    parser.add_argument('-o', '--open', action='store_true', help="啟動時自動在 Mac 瀏覽器開啟 QR Code 頁面")
    args = parser.parse_args()
    
    run_server(port=args.port, auto_open=args.open)

