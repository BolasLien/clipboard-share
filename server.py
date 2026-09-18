#!/usr/bin/env python3
import argparse
import datetime
import http.server
import json
import mimetypes
import os
import socket
import subprocess
import sys
from urllib.parse import parse_qs, unquote

DEFAULT_PORT = 8000
DOWNLOADS_DIR = os.path.expanduser('~/Downloads/ClipboardShare')
PREVIEWS_DIR = '/tmp/clip_share_previews'

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(PREVIEWS_DIR, exist_ok=True)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def detect_image_extension(image_bytes: bytes) -> str:
    """透過二進制 Magic Bytes 判斷真實副檔名"""
    if len(image_bytes) >= 8 and image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if len(image_bytes) >= 3 and image_bytes[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if len(image_bytes) >= 12 and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return '.webp'
    if len(image_bytes) >= 6 and (image_bytes[:6] in (b'GIF87a', b'GIF89a')):
        return '.gif'
    if len(image_bytes) >= 12 and image_bytes[4:8] == b'ftyp':
        return '.heic'
    return '.jpg'

def copy_text_to_macos_clipboard(text: str):
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)

def get_macos_clipboard() -> str:
    try:
        return subprocess.check_output(['pbpaste'], text=True)
    except Exception:
        return ""

def ensure_web_preview(file_path: str) -> str:
    """使用 macOS 內建 sips 產生所有瀏覽器 100% 支援的 JPEG 預覽圖"""
    filename = os.path.basename(file_path)
    preview_path = os.path.join(PREVIEWS_DIR, f"{filename}.preview.jpg")
    
    if os.path.exists(preview_path) and os.path.getmtime(preview_path) >= os.path.getmtime(file_path):
        return preview_path

    try:
        subprocess.run(
            ['sips', '-s', 'format', 'jpeg', '-Z', '1200', file_path, '--out', preview_path],
            check=True,
            capture_output=True
        )
        return preview_path
    except Exception:
        return file_path

def copy_image_to_macos_clipboard(image_bytes: bytes) -> str:
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    real_ext = detect_image_extension(image_bytes)
    filename = f"clip_{timestamp}{real_ext}"
    save_path = os.path.join(DOWNLOADS_DIR, filename)

    with open(save_path, 'wb') as f:
        f.write(image_bytes)

    # 產生 Web 預覽圖
    ensure_web_preview(save_path)

    # 轉為標準全尺寸 PNG 注入 macOS 系統剪貼簿
    tmp_png = '/tmp/clip_share_clipboard.png'
    try:
        subprocess.run(
            ['sips', '-s', 'format', 'png', save_path, '--out', tmp_png],
            check=True,
            capture_output=True
        )
        script = f'set the clipboard to (read (POSIX file "{tmp_png}") as «class PNGf»)'
        subprocess.run(['osascript', '-e', script], check=True)
    except Exception as e:
        print(f"⚠️ 寫入剪貼簿警報: {e}")

    return save_path

def get_latest_received_image():
    if not os.path.exists(DOWNLOADS_DIR):
        return None
    valid_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic', '.heif'}
    files = [
        f for f in os.listdir(DOWNLOADS_DIR)
        if os.path.splitext(f)[1].lower() in valid_exts and not f.startswith('.')
    ]
    if not files:
        return None
    files.sort(key=lambda x: os.path.getmtime(os.path.join(DOWNLOADS_DIR, x)), reverse=True)
    latest = files[0]
    full_path = os.path.join(DOWNLOADS_DIR, latest)
    stat = os.stat(full_path)
    size_kb = stat.st_size / 1024
    size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
    mtime_str = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%H:%M:%S')
    return {
        "filename": latest,
        "previewUrl": f"/preview/{latest}",
        "rawUrl": f"/images/{latest}",
        "size": size_str,
        "mtime": mtime_str
    }

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>跨裝置剪貼簿同步 (文字 & 圖片)</title>
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
      --danger: #ef4444;
      --send-accent: #38bdf8;
      --recv-accent: #34d399;
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
    .main-wrapper {
      width: 100%;
      max-width: 1060px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .header {
      text-align: center;
      padding: 6px 0 12px 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
    }
    .header h1 {
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: -0.025em;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--subtext);
      background: #1e293b;
      padding: 4px 12px;
      border-radius: 9999px;
      border: 1px solid var(--border);
    }
    .status-dot {
      width: 8px;
      height: 8px;
      background-color: var(--success);
      border-radius: 50%;
    }

    /* 佈局容器：桌面雙欄 (發送 | 接收)，手機單欄 (發送 上，接收 下) */
    .columns-container {
      display: grid;
      grid-template-columns: 1fr;
      gap: 20px;
      width: 100%;
    }
    @media (min-width: 860px) {
      .columns-container {
        grid-template-columns: 1fr 1fr;
        gap: 24px;
      }
    }

    .section-column {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding-bottom: 4px;
      border-bottom: 2px solid var(--border);
    }
    .section-title {
      font-size: 1.1rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .title-send { color: var(--send-accent); }
    .title-recv { color: var(--recv-accent); }

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
      height: 105px;
      background: #0b1120;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      padding: 12px;
      font-size: 14px;
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
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      transition: background 0.15s, transform 0.1s;
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
    button.danger {
      background-color: #7f1d1d;
      color: #fecaca;
    }
    button.btn-sm {
      flex: 0 0 auto !important;
      width: auto !important;
      white-space: nowrap !important;
      padding: 5px 12px !important;
      font-size: 12px !important;
      border-radius: 6px !important;
      line-height: 1.2 !important;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .dropzone {
      border: 2px dashed var(--border);
      border-radius: 8px;
      padding: 20px 16px;
      text-align: center;
      background: #0b1120;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      transition: border-color 0.2s, background 0.2s;
    }
    .dropzone.dragover {
      border-color: var(--primary);
      background: #172554;
    }
    .preview-box {
      display: none;
      flex-direction: column;
      gap: 10px;
      align-items: center;
      background: #0b1120;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .preview-box img {
      max-width: 100%;
      max-height: 200px;
      object-fit: contain;
      border-radius: 6px;
    }
    .preview-info {
      font-size: 12px;
      color: var(--subtext);
      display: flex;
      justify-content: space-between;
      width: 100%;
    }
    .received-img-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      background: #0b1120;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .received-img-box img {
      max-width: 100%;
      max-height: 240px;
      object-fit: contain;
      border-radius: 6px;
      cursor: pointer;
      box-shadow: 0 4px 10px rgba(0,0,0,0.5);
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
      max-width: 90%;
      text-align: center;
    }
    .toast.show {
      transform: translateX(-50%) translateY(0);
    }
    .qr-card {
      text-align: center;
      padding: 12px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      background: #1e293b;
      border: 1px solid var(--border);
      border-radius: 12px;
    }
    .qr-card img {
      width: 130px;
      height: 130px;
      border-radius: 8px;
      background: #fff;
      padding: 5px;
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
      padding: 6px 12px;
      border-radius: 6px;
      font-family: monospace;
      font-size: 12px;
      color: #38bdf8;
      word-break: break-all;
    }

    /* 手機端專屬隱藏 */
    @media (max-width: 859px) {
      .desktop-only {
        display: none !important;
      }
    }
  </style>
</head>
<body>

<div class="main-wrapper">
  <!-- 頂部資訊 -->
  <div class="header">
    <h1>📋 跨裝置剪貼簿同步</h1>
    <div class="status-badge">
      <span class="status-dot"></span>
      <span id="ipInfo">區域網路直連中</span>
    </div>
  </div>

  <!-- 雙欄/單欄容器 -->
  <div class="columns-container">

    <!-- ==================== 【📤 發送區 (Send)】 ==================== -->
    <div class="section-column" id="colSend">
      <div class="section-header">
        <span class="section-title title-send">📤 發送 (Send to Mac)</span>
        <span class="badge">直接進 Mac 剪貼簿</span>
      </div>

      <!-- 圖片發送卡片 -->
      <div class="card">
        <div class="card-title">
          <span>🖼️ 傳送圖片</span>
          <span style="font-size: 12px; color: var(--subtext);">Cmd + V 貼圖</span>
        </div>
        
        <input type="file" id="fileInput" accept="image/*" style="display: none;">

        <div class="dropzone" id="dropzone">
          <div style="font-size: 1.8rem;">📷</div>
          <div style="font-size: 14px; font-weight: 500;">點擊選擇相片、拍照或貼上截圖</div>
          <div style="font-size: 12px; color: var(--subtext);">支援 JPG、PNG、HEIC、WebP、GIF</div>
        </div>

        <div class="preview-box" id="previewBox">
          <img id="previewImg" alt="Preview" />
          <div class="preview-info">
            <span id="previewName"></span>
            <span id="previewSize"></span>
          </div>
          <div class="btn-group" style="width: 100%;">
            <button type="button" class="danger" style="flex: 0 0 70px;" id="btnCancelImg">清除</button>
            <button type="button" id="btnSendImg">🚀 送圖片到 Mac</button>
          </div>
        </div>
      </div>

      <!-- 文字發送卡片 -->
      <div class="card">
        <div class="card-title">
          <span>📝 傳送文字</span>
          <span style="font-size: 12px; color: var(--subtext);">同步至 pbcopy</span>
        </div>
        <textarea id="textToSend" placeholder="在此輸入文字，或長按貼上..."></textarea>
        <div class="btn-group">
          <button type="button" class="secondary" id="btnPasteText">📋 貼上</button>
          <button type="button" id="btnSendText">🚀 送文字到 Mac</button>
        </div>
      </div>
    </div>

    <!-- ==================== 【📥 接收區 (Receive)】 ==================== -->
    <div class="section-column" id="colRecv">
      <div class="section-header">
        <span class="section-title title-recv">📥 接收 (Received on Mac)</span>
        <span class="badge" style="background: #10b981;">即時同步中</span>
      </div>

      <!-- 最新接收到的圖片卡片 -->
      <div class="card" id="cardLatestImg" style="display: none; border-color: #0284c7;">
        <div class="card-title">
          <span>🖼️ 最新接收的圖片</span>
          <span class="badge" style="background: #10b981;">已在 Mac 剪貼簿</span>
        </div>
        <div class="received-img-box">
          <img id="receivedImg" alt="最新圖片" title="點擊檢視原圖" />
          <div class="preview-info">
            <span id="receivedName" style="font-weight: 600; color: #38bdf8;"></span>
            <span id="receivedMeta"></span>
          </div>
          <div class="btn-group" style="width: 100%;">
            <button type="button" class="secondary desktop-only" id="btnOpenFinder">📂 在 Finder 開啟</button>
            <button type="button" id="btnViewFull">🔍 查看原圖</button>
          </div>
        </div>
      </div>

      <!-- 從 Mac 讀取目前文字剪貼簿 -->
      <div class="card">
        <div class="card-title">
          <span>💻 Mac 目前文字剪貼簿</span>
          <button type="button" class="secondary btn-sm" id="btnRefresh">🔄 重新整理</button>
        </div>
        <textarea id="textFromMac" readonly placeholder="點擊重新整理或等待自動同步 Mac 剪貼簿..."></textarea>
        <button type="button" class="secondary" id="btnCopyFromMac">📄 複製到本裝置</button>
      </div>

      <!-- 桌面端專屬 QR Code 卡片 -->
      <div class="qr-card desktop-only" id="qrCard">
        <div style="font-size: 13px; color: var(--subtext);">📱 手機相機掃描加入此剪貼簿：</div>
        <div class="code-block" id="currentUrl"></div>
        <img id="qrImage" alt="QR Code" />
      </div>

    </div>

  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  const fullUrl = window.location.origin;
  document.getElementById('currentUrl').innerText = fullUrl;
  document.getElementById('ipInfo').innerText = `連線至: ${fullUrl}`;
  document.getElementById('qrImage').src = 'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=' + encodeURIComponent(fullUrl);

  let currentImageFile = null;
  let lastImageFilename = '';
  let currentRawUrl = '';

  function showToast(msg, bg = '#059669') {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.style.background = bg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
  }

  // --- 圖片處理 ---
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  const previewBox = document.getElementById('previewBox');
  const previewImg = document.getElementById('previewImg');
  const previewName = document.getElementById('previewName');
  const previewSize = document.getElementById('previewSize');
  const btnCancelImg = document.getElementById('btnCancelImg');
  const btnSendImg = document.getElementById('btnSendImg');

  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleImageFile(e.target.files[0]);
    }
  });

  window.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (const item of items) {
      if (item.type.indexOf('image') === 0) {
        const file = item.getAsFile();
        handleImageFile(file);
        showToast('📸 已自動偵測貼上的圖片');
        break;
      }
    }
  });

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleImageFile(e.dataTransfer.files[0]);
    }
  });

  function handleImageFile(file) {
    if (!file || !file.type.startsWith('image/')) {
      showToast('請選擇圖片檔案', '#e11d48');
      return;
    }
    currentImageFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
      previewImg.src = e.target.result;
      previewName.innerText = file.name || '貼上的圖片';
      previewSize.innerText = (file.size / 1024).toFixed(1) + ' KB';
      dropzone.style.display = 'none';
      previewBox.style.display = 'flex';
    };
    reader.readAsDataURL(file);
  }

  btnCancelImg.addEventListener('click', () => {
    currentImageFile = null;
    fileInput.value = '';
    previewBox.style.display = 'none';
    dropzone.style.display = 'flex';
  });

  btnSendImg.addEventListener('click', async () => {
    if (!currentImageFile) return;
    btnSendImg.disabled = true;
    btnSendImg.innerText = '傳送中...';
    try {
      const res = await fetch('/api/image', {
        method: 'POST',
        headers: {
          'Content-Type': currentImageFile.type || 'application/octet-stream',
          'X-File-Name': encodeURIComponent(currentImageFile.name || 'image.jpg')
        },
        body: currentImageFile
      });
      const data = await res.json();
      if (data.ok) {
        showToast('✅ 圖片已寫入 Mac 剪貼簿！(可直接 Cmd+V)');
        btnCancelImg.click();
        fetchLatestImage();
      } else {
        showToast('❌ 傳送失敗: ' + (data.error || '未知錯誤'), '#e11d48');
      }
    } catch (err) {
      showToast('❌ 傳送失敗，請檢查網路連線', '#e11d48');
    } finally {
      btnSendImg.disabled = false;
      btnSendImg.innerText = '🚀 送圖片到 Mac';
    }
  });

  // --- 最新接收圖片展示 ---
  const cardLatestImg = document.getElementById('cardLatestImg');
  const receivedImg = document.getElementById('receivedImg');
  const receivedName = document.getElementById('receivedName');
  const receivedMeta = document.getElementById('receivedMeta');
  const btnViewFull = document.getElementById('btnViewFull');
  const btnOpenFinder = document.getElementById('btnOpenFinder');

  async function fetchLatestImage() {
    try {
      const res = await fetch('/api/latest-image');
      const data = await res.json();
      if (data.exists) {
        if (data.filename !== lastImageFilename) {
          lastImageFilename = data.filename;
          currentRawUrl = data.rawUrl;
          receivedImg.src = data.previewUrl;
          receivedName.innerText = data.filename;
          receivedMeta.innerText = `${data.size} (${data.mtime})`;
          cardLatestImg.style.display = 'flex';
        }
      }
    } catch (err) {
      console.error(err);
    }
  }

  receivedImg.addEventListener('click', () => {
    if (currentRawUrl) window.open(currentRawUrl, '_blank');
  });

  btnViewFull.addEventListener('click', () => {
    if (currentRawUrl) window.open(currentRawUrl, '_blank');
  });

  if (btnOpenFinder) {
    btnOpenFinder.addEventListener('click', async () => {
      try {
        await fetch('/api/open-finder', { method: 'POST' });
        showToast('📂 已在 Mac 打開 Finder 資料夾');
      } catch (e) {
        showToast('開啟失敗', '#e11d48');
      }
    });
  }

  // --- 文字處理 ---
  document.getElementById('btnSendText').addEventListener('click', async () => {
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

  document.getElementById('btnPasteText').addEventListener('click', async () => {
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

  async function fetchMacClipboard() {
    try {
      const res = await fetch('/api/clipboard');
      const data = await res.json();
      if (data.content !== undefined) {
        document.getElementById('textFromMac').value = data.content || '';
      }
    } catch (err) {
      console.error(err);
    }
  }

  document.getElementById('btnRefresh').addEventListener('click', () => {
    fetchMacClipboard();
    fetchLatestImage();
    showToast('已刷新 Mac 狀態');
  });

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

  // 初次載入
  fetchMacClipboard();
  fetchLatestImage();

  // 自動每 2.5 秒輪詢
  setInterval(() => {
    fetchLatestImage();
  }, 2500);
</script>

</body>
</html>
"""

class ClipboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
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
        elif self.path == '/api/latest-image':
            latest = get_latest_received_image()
            if latest:
                res = {"exists": True, **latest}
            else:
                res = {"exists": False}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
        elif self.path.startswith('/preview/'):
            filename = os.path.basename(unquote(self.path[len('/preview/'):]))
            file_path = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                preview_file = ensure_web_preview(file_path)
                try:
                    with open(preview_file, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception:
                    self.send_response(500)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path.startswith('/images/'):
            filename = os.path.basename(unquote(self.path[len('/images/'):]))
            file_path = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                mime_type, _ = mimetypes.guess_type(file_path)
                mime_type = mime_type or 'application/octet-stream'
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', mime_type)
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception:
                    self.send_response(500)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
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
                copy_text_to_macos_clipboard(content)
                preview = (content[:50] + '...') if len(content) > 50 else content
                print(f"\n⚡ [Mac 剪貼簿已更新文字]: {preview}\n")
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode('utf-8'))

        elif self.path == '/api/image':
            content_length = int(self.headers.get('Content-Length', 0))
            raw_filename = self.headers.get('X-File-Name', 'image.jpg')
            original_filename = unquote(raw_filename)
            
            try:
                image_bytes = self.rfile.read(content_length)
                if not image_bytes:
                    raise ValueError("未接收到圖片數據")
                
                saved_path = copy_image_to_macos_clipboard(image_bytes)
                print(f"\n🖼️  [Mac 剪貼簿已更新為圖片]: {os.path.basename(saved_path)} (原檔名: {original_filename})")
                print(f"    檔案已保存至: {saved_path}")
                print(f"    👉 您可直接在 Mac 任何應用程式按 Cmd + V 貼上！\n")
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'ok': True,
                    'filename': os.path.basename(saved_path),
                    'path': saved_path
                }).encode('utf-8'))
            except Exception as e:
                print(f"❌ 圖片處理失敗: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode('utf-8'))
        
        elif self.path == '/api/open-finder':
            try:
                os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                subprocess.run(['open', DOWNLOADS_DIR], check=False)
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
    print("=" * 60)
    print("🚀 跨裝置剪貼簿同步服務 (文字 & 圖片) 已啟動！")
    print("=" * 60)
    print(f"👉 請確保手機與 Mac 連接同一個 Wi-Fi")
    print(f"👉 手機 Chrome 請開啟網址：\n   \033[1;32m{url}\033[0m")
    print(f"👉 Mac 本機可開啟：\n   http://localhost:{port}")
    print(f"📁 圖片將自動存放至：{DOWNLOADS_DIR}")
    print("=" * 60)
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
