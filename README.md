# cams-manager

IP Camera RTSP Stream Recorder with auto-reconnect and retention management.

> 🚀 **想快速開始？** 查看 [快速啟動指南](QUICKSTART.md)

## 功能特色

- 🎥 同時錄製多個 IP camera 的 RTSP stream
- 🔄 自動重連機制，當 stream 中斷時自動恢復
- ⏱️ 可設定的分段錄影時間（預設 1 分鐘）
- 🗑️ 自動清理舊檔案（預設保留 7 天）
- 🚀 使用 Python 3.13 和 uv 套件管理
- 🔧 優化的 FFmpeg 參數，適合長時間錄影

## 系統需求

- Python 3.13+
- FFmpeg（需安裝在系統中）
- uv 套件管理工具
- 樹莓派或任何 Linux 系統

## 安裝步驟

### 快速安裝（推薦）

在樹莓派上可以使用自動安裝腳本：

```bash
cd ~/cams-manager
chmod +x install.sh
./install.sh
```

此腳本會：
- 檢查並安裝 FFmpeg
- 檢查並安裝 uv
- 安裝 Python 依賴
- 建立範例設定檔
- 可選安裝 systemd 服務

### 手動安裝

#### 1. 安裝系統依賴

```bash
# 在樹莓派上安裝 FFmpeg
sudo apt update
sudo apt install ffmpeg
```

#### 2. 安裝 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 3. Clone 專案

```bash
cd ~
git clone <repository-url> cams-manager
cd cams-manager
```

#### 4. 安裝 Python 依賴

```bash
uv sync
```

#### 5. 建立設定檔

```bash
cp config.yaml.example config.yaml
```

編輯 `config.yaml`，設定你的 camera 資訊：

```yaml
cameras:
  - name: cam1
    rtsp_url: rtsp://username:password@192.168.1.101:554/stream
    output_dir: /data/recordings/cam1
  - name: cam2
    rtsp_url: rtsp://username:password@192.168.1.102:554/stream
    output_dir: /data/recordings/cam2
  - name: cam3
    rtsp_url: rtsp://username:password@192.168.1.103:554/stream
    output_dir: /data/recordings/cam3

recording:
  segment_duration: 60  # 1 分鐘
  retention_days: 7
  reconnect_delay: 5  # 重連等待時間（秒）
  
ffmpeg:
  rtbufsize: 100M
  timeout: 5000000  # 5 秒（微秒）
  rw_timeout: 5000000  # 5 秒（微秒）
```

#### 6. 建立錄影目錄

```bash
sudo mkdir -p /data/recordings/cam1
sudo mkdir -p /data/recordings/cam2
sudo mkdir -p /data/recordings/cam3
sudo chown -R $USER:$USER /data/recordings
```

## 測試設定

在執行之前，建議先測試設定是否正確：

```bash
python3 test_config.py
```

這個腳本會檢查：
- Python 版本是否符合要求
- FFmpeg 是否已安裝
- 設定檔是否存在且格式正確
- 輸出目錄是否存在

## 使用方式

### 直接執行

```bash
# 使用預設設定檔 (config.yaml)
uv run cams-manager

# 指定設定檔
uv run cams-manager -c /path/to/config.yaml

# 啟用詳細日誌
uv run cams-manager -v
```

### 作為 systemd 服務運行（推薦）

使用安裝腳本時會自動建立 systemd 服務。如果你需要手動設定：

```bash
sudo systemctl enable cams-manager.service
sudo systemctl start cams-manager.service
```

### 查看服務狀態：

```bash
sudo systemctl status cams-manager.service
```

4. 查看日誌：

```bash
# 即時查看日誌
sudo journalctl -u cams-manager.service -f

# 查看最近的日誌
sudo journalctl -u cams-manager.service -n 100
```

5. 控制服務：

```bash
# 停止服務
sudo systemctl stop cams-manager.service

# 重啟服務
sudo systemctl restart cams-manager.service

# 停用開機自動啟動
sudo systemctl disable cams-manager.service
```

## 錄影檔案格式

錄影檔案會以以下目錄結構和檔案名稱儲存：

```
output_dir/YYYY/mm/dd/HHMMSS.mp4
```

例如：
```
/data/recordings/cam1/2024/10/18/143025.mp4
```

檔案會自動按年/月/日組織在子目錄中。

## FFmpeg 參數說明

本專案使用的 FFmpeg 參數：

- `rtsp_transport tcp`：使用 TCP 傳輸（較穩定）
- `rtbufsize`：RTSP buffer 大小
- `timeout`：Socket timeout
- `rw_timeout`：讀寫 timeout
- `use_wallclock_as_timestamps`：使用系統時間作為時間戳
- `reset_timestamps`：重置時間戳
- `c:v copy`：視訊直接複製（不重新編碼）
- `c:a aac`：音訊轉為 AAC 編碼
- `segment`：分段錄影模式
- `segment_time`：每個分段的長度（秒）

## 疑難排解

### FFmpeg 找不到

確保 FFmpeg 已安裝並在 PATH 中：

```bash
which ffmpeg
ffmpeg -version
```

### 連線失敗

1. 檢查 RTSP URL 是否正確
2. 測試是否能用 FFmpeg 直接連線：

```bash
ffmpeg -rtsp_transport tcp -i rtsp://username:password@ip:port/stream -t 10 test.mp4
```

3. 檢查網路連線和防火牆設定

### 磁碟空間不足

1. 檢查磁碟使用情況：

```bash
df -h /data/recordings
```

2. 調整 `retention_days` 設定以保留更少天數
3. 考慮使用較低的視訊品質或降低 segment_duration

### 查看詳細日誌

```bash
uv run cams-manager -v
```

## 授權

See [LICENSE](LICENSE) file.

## 貢獻

歡迎提交 Issue 和 Pull Request！
