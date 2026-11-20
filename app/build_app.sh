#!/bin/bash
# 编译菜单栏程序并重新打开。改了 main.swift 后跑这个。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/美国四年周期.app"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>CycleBoard</string>
<key>CFBundleIdentifier</key><string>local.cycleboard</string>
<key>CFBundleName</key><string>美国四年周期</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>2.0</string>
<key>LSUIElement</key><true/>
</dict></plist>
EOF
swiftc -O -o "$APP/Contents/MacOS/CycleBoard" "$HERE/main.swift" -framework Cocoa
codesign -s - --force "$APP" 2>/dev/null
# 菜单栏图标多，固定放在时间左边，免得被刘海挡住
defaults write local.cycleboard "NSStatusItem Preferred Position CycleBoard" -float 330
defaults write local.cycleboard "NSStatusItem Visible CycleBoard" -bool true
# 开机（登录）自动打开：2026-11-20 定。只在登录时打开一次，不常驻拉起——手动退出就一直退出，直到下次登录
AGENT="$HOME/Library/LaunchAgents/local.cycleboard.login.plist"
cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>local.cycleboard.login</string>
<key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>$APP</string></array>
<key>RunAtLoad</key><true/>
<key>LimitLoadToSessionType</key><string>Aqua</string>
</dict></plist>
EOF
plutil -lint -s "$AGENT"
launchctl bootout "gui/$(id -u)/local.cycleboard.login" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"
pkill -x CycleBoard || true
sleep 1
open "$APP"
echo "已重新打开：${APP}；开机自动打开：${AGENT}"
