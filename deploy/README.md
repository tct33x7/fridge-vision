# deploy · 在 OrangePi 4 Pro 上跑起来

v4 的主机是 OrangePi 4 Pro（[ARCHITECTURE §7](../docs/ARCHITECTURE.md)）。Mac 继续做开发机，同一套代码复制过来就能跑。
这里先放装机清单，**状态：未开始**。每做完一步，在这里记下实际用的命令和遇到的坑，下次重装照着做就行。

手册在 [archive/reference/OrangePi_4_Pro_A733_User Manual_v1.4.pdf](../archive/reference/)，下面括号里是手册章节和页码。

## 装机清单

- [ ] **烧系统**：官网下载 Ubuntu Jammy 或 Debian Bookworm 镜像，先烧到 TF 卡（§2.4，p.17）；稳定后迁到 eMMC 或 NVMe（§2.5 / §3.35，p.21 / p.193），因为录像会反复写盘。
- [ ] **联网和远程登录**：Wi-Fi（§3.7.2，p.65），SSH（§3.8.1，p.90）。主机名改成 `fridge`，装 `avahi-daemon`，手机就能用 `http://fridge.local:8000` 访问。
- [ ] **相机**：插 USB 后用 `v4l2-ctl --list-devices` 找到设备（§3.12.4，p.106）；用 `v4l2-ctl -d /dev/video0 --list-ctrls` 查看曝光控制项，**锁定曝光**（控制项的名字因相机而异，常见的是 `auto_exposure` / `exposure_time_absolute`）。这是 Mac 上做不到的。
- [ ] **Python 环境**：`python3-venv`；OpenCV 用系统包 `python3-opencv` 或 pip 的 `opencv-python-headless`；从 GitHub 克隆仓库（私有仓库需要令牌，不要把令牌写进任何文件）。
- [ ] **门磁**：干簧管一端接 GPIO，一端接 GND，开内部上拉（引脚说明 §3.15，p.115；GPIO 测试 §3.17，p.117；上拉 §3.17.2，p.118）。旧项目的按钮用的是物理 7 号脚（GPIO 356 / PL4，见 `archive/camera_system/README.md`），可以沿用，以手册引脚表为准。用 `gpioget` 先测开关门时电平变化。
- [ ] **开机自启**：采集、分析、后端三个 systemd 服务（后端模板 `smart_fridge_app/deploy/smart-fridge.service.example`）。
- [ ] **小屏（可选）**：浏览器全屏打开 `http://localhost:8000`（例如 `chromium --kiosk`）；官方 10.1 寸 MIPI 屏见 §3.29，p.164。
- [ ] **存储清理**：录像只留最近 7 天，关键帧和事件长期保留。
- [ ] **电源和散热**：Type-C 5V 3A 电源要稳；加散热片；不要放在冰箱顶部出热口上。

## 原则

- 只在家里局域网用，**不把端口开到公网**（后端没有登录）。
- 密钥只放 `.env` 或环境变量，不进 git。
- NPU（§3.34，p.185）暂时不用：v4 不要求实时识别，工具链成本高。
