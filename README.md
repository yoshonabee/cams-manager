# cams-manager

IP Camera RTSP Stream Recorder with auto-reconnect and retention management.

> 🚀 **想快速開始？** 查看 [快速啟動指南](QUICKSTART.md)

## 功能特色

- 🎥 同時錄製多個 IP camera 的 RTSP stream
- 🔄 自動重連機制，當 stream 中斷時自動恢復
- ⏱️ 可設定的分段錄影時間（預設 2 秒）
- 🔗 自動合併短片段為分鐘級檔案，減少檔案數量
- 🗑️ 自動清理舊檔案（預設保留 7 天）
- 🚀 使用 Python 3.13 和 uv 套件管理
- 🔧 優化的 FFmpeg 參數，適合長時間錄影

## TODO

- [x] 解決 FFmpeg 重連問題：當網路中斷或 camera 重啟時，需改善重連邏輯確保錄影不中斷。
  - 目前 ffmpeg 會 hang 住，不會自動重連，且 python 無法得知 ffmpeg 有問題。
- [ ] 支援 error 發生或斷線重新連接時，使用 telegram 通知使用者。

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
  segment_duration: 2          # 短 segment 長度（秒）
  retention_days: 7            # 保留天數
  reconnect_delay: 5           # 重連延遲（秒）
  merge_interval: 30           # 合併檢查間隔（秒）
  merge_delay: 120             # 檔案至少要等多久才會被合併（秒）
  
ffmpeg:
  rtbufsize: 100M
  timeout: 5000000  # 5 秒（微秒）
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

#### 查看服務狀態

```bash
sudo systemctl status cams-manager.service
```

#### 查看日誌

```bash
# 即時查看日誌
sudo journalctl -u cams-manager.service -f

# 查看最近的日誌
sudo journalctl -u cams-manager.service -n 100
```

#### 控制服務

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

### 短片段（segments）
錄影時會先產生短片段，儲存在 `segments` 子目錄：
```
output_dir/segments/YYYYMMDD_HHMMSS.mp4
```

例如：
```
/data/recordings/cam1/segments/20241018_143025.mp4
```

### 合併後檔案（merged）
系統會自動將短片段合併為分鐘級檔案，儲存在 `merged` 子目錄：
```
output_dir/merged/YYYYMMDD_HHMM.mp4
```

例如：
```
/data/recordings/cam1/merged/20241018_1430.mp4
```

合併後的檔案會自動刪除對應的短片段，以節省儲存空間。

## 工作原理

### 錄影流程

1. **錄製短片段**：FFmpeg 會持續錄製 RTSP stream，並根據 `segment_duration` 設定產生短片段（預設 2 秒）
2. **自動合併**：`SegmentAggregator` 會定期檢查 `segments` 目錄，將超過 `merge_delay` 時間的短片段合併為分鐘級檔案
3. **清理舊檔**：`RecordingCleaner` 會定期清理超過 `retention_days` 的舊檔案

### FFmpeg 參數說明

錄影時使用的 FFmpeg 參數：

- `rtsp_transport tcp`：使用 TCP 傳輸（較穩定）
- `rtbufsize`：RTSP buffer 大小
- `timeout`：Socket timeout（微秒）
- `use_wallclock_as_timestamps`：使用系統時間作為時間戳
- `reset_timestamps`：重置時間戳
- `c:v copy`：視訊直接複製（不重新編碼）
- `c:a aac`：音訊轉為 AAC 編碼
- `segment`：分段錄影模式
- `segment_time`：每個分段的長度（秒）
- `segment_atclocktime`：在整點時間切換 segment

合併時使用的 FFmpeg 參數：

- `concat demuxer`：使用 FFmpeg concat demuxer 合併多個檔案
- `c copy`：直接複製，不重新編碼，保持原始品質

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
3. 考慮使用較低的視訊品質或增加 `segment_duration`（較長的片段會產生較少的檔案）

### 查看詳細日誌

```bash
uv run cams-manager -v
```

## 授權

See [LICENSE](LICENSE) file.

## 貢獻

歡迎提交 Issue 和 Pull Request！
