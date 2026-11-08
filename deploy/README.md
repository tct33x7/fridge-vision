# deploy · OrangePi 4 Pro

板子已经由老师装好并在运行（11-08）：系统、联网、SSH、摄像头、拍照按钮、开机自启、桌面自动打开网页都已完成。
板子上的程序在仓库 [orangepi_app/](../orangepi_app/)，运行方式、测速结果和已知问题见 [orangepi_app/ORANGEPI.md](../orangepi_app/ORANGEPI.md)。
手册在 [archive/reference/](../archive/reference/)（OrangePi 4 Pro 用户手册 v1.4），下面括号里是章节和页码。

## 连接

先在自己的 Mac 上配好 SSH 密钥（板子连续输错密码会封禁约 4 分钟），再在 `~/.ssh/config` 里加 `Host opi`（`HostName 192.168.3.167`，`User orangepi`）。之后：

```bash
ssh opi
```

板子的 IP、账号见老师给的交接文档（不放在仓库里）。换了 WiFi 或路由器，IP 可能会变：在路由器后台查 `orangepi4pro` 的地址，再改 `~/.ssh/config` 里的 `HostName`。

## 同步代码

```bash
cd ~/Projects/bx-project && deploy/opi_sync.sh status
```

`status` 看差异，`pull` 把板子上的改动拉回仓库，`push` 推到板子（默认只列出要改的文件，加 `--yes` 才真正同步）。`.env`、数据、模型、密钥都不会动。

## 重启服务

需要 sudo，在终端里运行：

```bash
ssh -t opi 'sudo systemctl restart smart-fridge && systemctl is-active smart-fridge'
```

**可选：只对这个服务免密码。** 加一条只允许启动、停止、重启 `smart-fridge` 的规则，以后部署就不用每次输入密码。这条命令会改动板子的 sudo 设置，要由能做决定的人（你或老师）自己运行：

```bash
ssh -t opi 'echo "orangepi ALL=(root) NOPASSWD: /usr/bin/systemctl restart smart-fridge, /usr/bin/systemctl start smart-fridge, /usr/bin/systemctl stop smart-fridge" | sudo tee /etc/sudoers.d/smart-fridge >/dev/null && sudo chmod 440 /etc/sudoers.d/smart-fridge && sudo visudo -c'
```

## 清单

- [x] 烧系统（Orange Pi 1.0.8 Jammy，内核 6.6），联网，SSH
- [x] 摄像头：UGREEN USB，640×480、15 帧/秒
- [x] 开机自启：systemd `smart-fridge.service`，root 运行，失败自动重启
- [x] 桌面自动打开网页（`open_browser.sh`）
- [x] 拍照按钮（物理 7 脚 PL4）
- [ ] 门磁：备用开关在物理 11 脚（PL9，接 GND，内部上拉），软件还没接，可以用来判断开关门
- [ ] 锁定曝光：`v4l2-ctl -d /dev/video1 --list-ctrls` 查控制项（§3.12.4，p.106）
- [ ] 识别提速：改用 yolo11n 的 ONNX 版本（实测 14.5 帧/秒，现在约 2 帧/秒）
- [ ] 摄像头断开后自动重新打开
- [ ] 存储清理：硬盘只剩约 2.5 GB；以后录像只保留最近几天
- [ ] 散热、电源：Type-C 5V 3A，加散热片

## 原则

- 只在家里或机构的局域网里用，**不把 8080 端口开到公网**（网站没有登录）。以后要远程访问，用 Tailscale 这类组网工具。
- 密钥只放板子上的 `.env` 和 `config/api_settings.json`，不进 git。
