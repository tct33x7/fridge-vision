#!/bin/bash
# Smart Fridge · 开机自动打开浏览器到应用界面
# 由 systemd 服务 ExecStartPost 调用，确保桌面只显示本应用
sleep 5
# 关闭可能残留的 Firefox（避免会话恢复旧标签抢占焦点）
pkill -u orangepi firefox-esr 2>/dev/null
sleep 2
# 写入 Firefox 配置：禁用崩溃会话恢复，主页设为本应用，抑制翻译弹窗
PROFILE=$(ls -d /home/orangepi/.mozilla/firefox*/*.default* 2>/dev/null | head -1)
if [ -n "$PROFILE" ]; then
  cat > "$PROFILE/user.js" <<'EOF'
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.page", 1);
user_pref("browser.startup.homepage", "http://localhost:8080");
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.translation.ui.welcomeMessageShown", true);
user_pref("browser.translations.automaticallyPopup", false);
EOF
  chown orangepi:orangepi "$PROFILE/user.js" 2>/dev/null
fi
# 以 orangepi 用户身份打开浏览器新窗口（获得焦点）
su - orangepi -c "DISPLAY=:0 firefox-esr --new-window http://localhost:8080" &
exit 0
