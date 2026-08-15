<p align="center">
  <strong>English</strong> · <a href="#-繁體中文-traditional-chinese">繁體中文</a>
</p>

<h1 align="center">FetchJAV</h1>

<p align="center">
  <strong>The Ultimate Desktop Downloader, Video Streamer & AI Subtitle Generator</strong><br />
  Stream, download, and automatically transcribe videos from <strong>JableTV</strong>, <strong>MissAV</strong>, and <strong>SupJav</strong> with local & cloud AI subtitle engines.
</p>

<p align="center">
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DeepanshuK2002/FetchJAV?style=flat-square&label=release&color=ff5263" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases"><img alt="Total downloads" src="https://img.shields.io/github/downloads/DeepanshuK2002/FetchJAV/total?style=flat-square&label=downloads&color=2ea44f" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV"><img alt="GitHub stars" src="https://img.shields.io/github/stars/DeepanshuK2002/FetchJAV?style=flat-square&logo=github&color=f5b942" /></a>
  <a href="./LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/github/license/DeepanshuK2002/FetchJAV?style=flat-square" /></a>
  <a href="https://github.com/DeepanshuK2002/FetchJAV/pkgs/container/jabletv"><img alt="Docker amd64 and arm64" src="https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ed?style=flat-square&logo=docker&logoColor=white" /></a>
</p>

<p align="center">
  <strong><a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe">⬇️ Download FetchJAV.exe (Windows Direct)</a></strong>
  ·
  <a href="https://github.com/DeepanshuK2002/FetchJAV/releases/latest">📦 View Latest Release</a>
</p>

---

## 🌟 Key Features & Visual Walkthrough

### 1. Multi-Site Browse & Discovery Gallery
Browse, search, and filter videos across **JableTV**, **MissAV**, and **SupJav** in a single unified interface. Features responsive high-resolution cover cards, actress links, studio details, and multi-selection for bulk downloads.

<p align="center">
  <img src="./img/screenshots/02_browse_gallery.png" width="100%" alt="Multi-Site Browse & Discovery Gallery" />
</p>

---

### 2. Real-Time Streaming Video Preview
Watch full streams directly inside FetchJAV before downloading! Built-in local HTTP streaming proxy automatically handles HTTP range requests, repairs segmented TS/MP4 chunks, and strips anti-scraping fake headers on the fly.

<p align="center">
  <img src="./img/screenshots/01_streaming_preview.png" width="100%" alt="Real-Time Streaming Video Preview" />
</p>

<p align="center">
  <img src="./img/screenshots/06_video_player_controls.png" width="100%" alt="Video Player Controls" />
</p>

---

### 3. High-Performance Multi-Threaded Download Manager
Download multiple videos simultaneously with individual segment worker threads (1–16 workers per video), real-time bandwidth meters, segment progress trackers, and individual retry for interrupted chunks.

<p align="center">
  <img src="./img/screenshots/05_download_queue.png" width="100%" alt="High-Performance Download Queue" />
</p>

---

### 4. Built-in Local & Cloud AI Subtitle Pipeline
Automatically extract Japanese audio and generate `.ja.srt`, `.en.srt`, and `.zh-TW.srt` subtitle files right after downloading—without altering the original MP4 video:
- **Local Offline ASR**: Integrated **ReazonSpeech** and **Whisper** speech recognition running directly on your CPU/GPU with zero cloud dependencies.
- **AI Translation Options**: Optional integration with OpenAI, Claude, DeepSeek, Ollama, and Gemini API endpoints for precision subtitle translation.

<p align="center">
  <img src="./img/screenshots/04_ai_subtitles_config.png" width="100%" alt="AI Subtitle Configuration" />
</p>

<p align="center">
  <img src="./img/screenshots/09_translation_models.png" width="100%" alt="Translation Model Settings" />
</p>

---

### 5. Persistent Download History & Metadata Inspector
Never lose track of your library. All completed downloads and metadata (actresses, tags, release dates, video codes) are preserved across app restarts with 1-click folder opening and instant re-downloading.

<p align="center">
  <img src="./img/screenshots/03_download_history.png" width="100%" alt="Persistent Download History" />
</p>

---

### 6. Modern Dark UI & Accent Color Customization
Designed with a sleek CustomTkinter interface supporting high-DPI scaling, dark/light themes, and selectable accent color themes (Pink, Blue, Violet, Amber, Green).

<p align="center">
  <img src="./img/screenshots/08_theme_customization.png" width="100%" alt="Theme & Accent Customization" />
</p>

---

### 7. Advanced Network & Proxy Architecture
Full support for custom HTTP, HTTPS, SOCKS4, and SOCKS5 proxies, plus automatic synchronization with Windows manual proxy server settings. Built with `curl_cffi` and a shared SSLContext to eliminate native OpenSSL crash issues.

<p align="center">
  <img src="./img/screenshots/10_network_proxy_config.png" width="100%" alt="Network & Proxy Configuration" />
</p>

---

### 8. System Tray Minimization & Background Operation
Minimize FetchJAV to the Windows system tray via `pystray` to allow uninterrupted background batch downloading, complete with status notifications.

<p align="center">
  <img src="./img/screenshots/11_tray_behavior_settings.png" width="100%" alt="System Tray Settings" />
</p>

---

### 9. Comprehensive General Settings
Configure destination folders, default resolution preferences (Highest, 1080p, 720p, 480p, Lowest), multi-language UI selection (English, 繁體中文, 简体中文, 日本語), and auto-update checks.

<p align="center">
  <img src="./img/screenshots/07_general_settings.png" width="100%" alt="General Application Settings" />
</p>

---

## 🚀 Windows: Quick Start in 30 Seconds

1. **Download**: Get the latest **[FetchJAV.exe](https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe)**.
2. **Run**: Place it in any writable folder and double-click to launch (no Python or FFmpeg installation required).
3. **Choose Language**: On first launch, pick your language and preferred theme.
4. **Browse & Download**:
   - In **Browse**, choose JableTV, MissAV, or SupJav, search keywords or browse categories.
   - Click preview to watch immediately, or select cards to add to the download queue.
   - Paste URLs directly or import `.txt` / `.csv` batches in the **Download** tab.

---

## 🛠️ Run from Source (macOS / Linux / Developer)

Requires **Python 3.10+** and Tk:

```bash
# Clone the repository
git clone https://github.com/DeepanshuK2002/FetchJAV.git
cd FetchJAV

# Install dependencies
python -m pip install -r requirements.txt

# Run the complete GUI
python main.py

# Or run headlessly with CLI options
python main.py --nogui --url "https://jable.tv/videos/example/" --output "./download" --max-workers-per-video 4
```

---

## 🐳 Docker / NAS Headless Deployment

The public container image is available at `ghcr.io/deepanshuk2002/fetchjav:latest`:

```bash
# Download a single URL to /downloads folder
docker run --rm -v "/path/to/downloads:/downloads" \
  ghcr.io/deepanshuk2002/fetchjav:latest "https://jable.tv/videos/example/"

# Docker Compose: pass urls via urls.txt
docker compose run --rm jabletv
```

---

## 🤝 Contributing & Bug Reports

When opening a [GitHub Issue](https://github.com/DeepanshuK2002/FetchJAV/issues/new), please include:
- App version and operating system.
- Target website, reproducible URL, and error messages.
- If a crash occurred, attach `crash_log.txt` from beside the executable.

---
---

# 🇹🇼 繁體中文 (Traditional Chinese)

## FetchJAV
**JableTV、MissAV、SupJav 的桌面下載器、即時串流預覽與 AI 生成字幕工具。**

---

### 🌟 核心功能與圖文介紹

#### 1. 多平台瀏覽與挑片圖庫
在單一介面中暢遊 **JableTV**、**MissAV** 與 **SupJav**，支援高畫質封面卡片、女優連結、片商資訊與批次多選下載。
<p align="center">
  <img src="./img/screenshots/02_browse_gallery.png" width="100%" alt="多平台瀏覽圖庫" />
</p>

#### 2. 即時影片串流預覽
下載前可直接在軟體內點擊串流播放！內建本機 HTTP 串流代理伺服器，即時轉發 Range 請求並自動修復分段檔頭。
<p align="center">
  <img src="./img/screenshots/01_streaming_preview.png" width="100%" alt="即時串流預覽" />
</p>

#### 3. 高效能多執行緒下載佇列
支援多部影片同時下載（1–32），每部影片自適應多工作執行緒（1–16），即時顯示速度計與進度條，斷點續傳獨立重試。
<p align="center">
  <img src="./img/screenshots/05_download_queue.png" width="100%" alt="下載佇列" />
</p>

#### 4. 本機離線與雲端 AI 字幕生成
影片下載完成後自動擷取日語音軌，生成獨立 `.ja.srt`、`.en.srt`、`.zh-TW.srt` 字幕：
- **本機離線辨識**：內建 **ReazonSpeech** 與 **Whisper** 模型，本機 CPU/GPU 快速推論。
- **雲端 LLM 翻譯**：支援接入 OpenAI、Claude、DeepSeek、Ollama、Gemini 進行高品質翻譯。
<p align="center">
  <img src="./img/screenshots/04_ai_subtitles_config.png" width="100%" alt="AI 字幕設定" />
</p>

#### 5. 下載歷史記錄與影音資訊庫
重開軟體依然完整保留已下載歷史，支援一鍵開啟資料夾、重新下載與女優標籤檢視。
<p align="center">
  <img src="./img/screenshots/03_download_history.png" width="100%" alt="歷史記錄分頁" />
</p>

#### 6. 現代深色 UI 與主題強調色自訂
基於 CustomTkinter 打造，支援高解析度縮放與粉紅、藍、紫、琥珀、綠等多種主題強調色自訂。
<p align="center">
  <img src="./img/screenshots/08_theme_customization.png" width="100%" alt="主題自訂" />
</p>

#### 7. 代理伺服器與網路架構
完整支援 HTTP、HTTPS、SOCKS4、SOCKS5 代理與 Windows 系統代理自動同步，徹底杜絕 Windows SSL 崩潰。
<p align="center">
  <img src="./img/screenshots/10_network_proxy_config.png" width="100%" alt="網路代理設定" />
</p>

#### 8. 系統匣背景下載
支援縮小至 Windows 系統匣（System Tray）持續背景下載，並於完成時發送系統通知。
<p align="center">
  <img src="./img/screenshots/11_tray_behavior_settings.png" width="100%" alt="系統匣設定" />
</p>

---

### 🚀 30 秒快速開始 (Windows)

1. **下載**：取得最新版 **[FetchJAV.exe](https://github.com/DeepanshuK2002/FetchJAV/releases/latest/download/FetchJAV.exe)**。
2. **執行**：將檔案放入任意可讀寫資料夾，**直接雙擊執行**（免安裝 Python、免額外配置）。
3. **開始使用**：在「瀏覽」選擇網站、搜尋關鍵字，點擊預覽或加入佇列下載。

> SmartScreen 信譽提醒與 Defender Antivirus 隔離是不同事件。請先閱讀 [Windows 下載與安全驗證](./WINDOWS_SECURITY.md)：核對 `SHA256SUMS.txt` 與 GitHub provenance；若 Defender 顯示 threat name，請勿直接降低防護設定。若備用包也被偵測，請停止並回報。

---

## 📜 授權與責任聲明

本專案採 [Apache License 2.0](./LICENSE) 授權開源。本工具僅供個人研究與合法備份使用，請遵守當地法規與各網站服務條款。
版本更新記錄請參閱 [GitHub Releases](https://github.com/DeepanshuK2002/FetchJAV/releases)。
