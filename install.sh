#!/bin/bash
# Quick installation script for cams-manager on Raspberry Pi

set -e

echo "=== cams-manager 安裝腳本 ==="
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "警告: 此腳本設計用於 Linux 系統（如樹莓派）"
    read -p "是否繼續？ (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if FFmpeg is installed
echo "檢查 FFmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg 未安裝，正在安裝..."
    sudo apt update
    sudo apt install -y ffmpeg
    echo "✓ FFmpeg 已安裝"
else
    echo "✓ FFmpeg 已存在"
fi

# Check if uv is installed
echo ""
echo "檢查 uv..."
if ! command -v uv &> /dev/null; then
    echo "uv 未安裝，正在安裝..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo "✓ uv 已安裝"
else
    echo "✓ uv 已存在"
fi

# Install Python dependencies
echo ""
echo "安裝 Python 依賴..."
uv sync
echo "✓ Python 依賴已安裝"

# Create example config if it doesn't exist
echo ""
if [ ! -f "config.yaml" ]; then
    echo "建立設定檔..."
    cp config.yaml.example config.yaml
    echo "✓ 已建立 config.yaml（請編輯此檔案設定你的 cameras）"
else
    echo "✓ config.yaml 已存在"
fi

# Ask if user wants to create systemd service
echo ""
read -p "是否安裝 systemd 服務（開機自動啟動）？ (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    CURRENT_DIR=$(pwd)
    CURRENT_USER=$(whoami)
    
    # Update service file with current paths
    cat > /tmp/cams-manager.service << EOF
[Unit]
Description=IP Camera RTSP Stream Recorder
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$HOME/.local/bin/uv run cams-manager -c $CURRENT_DIR/config.yaml
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment
Environment="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    
    sudo cp /tmp/cams-manager.service /etc/systemd/system/
    sudo systemctl daemon-reload
    
    echo "✓ systemd 服務已安裝"
    echo ""
    echo "啟用並啟動服務："
    echo "  sudo systemctl enable cams-manager.service"
    echo "  sudo systemctl start cams-manager.service"
    echo ""
    echo "查看服務狀態："
    echo "  sudo systemctl status cams-manager.service"
    echo ""
    echo "查看日誌："
    echo "  sudo journalctl -u cams-manager.service -f"
fi

echo ""
echo "=== 安裝完成 ==="
echo ""
echo "下一步："
echo "1. 編輯 config.yaml 設定你的 cameras"
echo "2. 執行測試: python3 test_config.py"
echo "3. 直接執行: uv run cams-manager"
echo "   或使用 systemd 服務（如果已安裝）"
echo ""

