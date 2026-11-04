# 饮食均衡助手：本地优先主软件

这是面向 Orange Pi、HDMI 触摸屏和可信局域网手机的本地优先应用。当前版本把
摄像头采集、可恢复的拍照录入、库存账本和“真实摄入”分开建模；视觉识别仍是后续可替换
能力，任何模型结果都不能绕过人工确认直接修改库存。

## 当前已经实现

- “今天”首页按真实数据动态显示：待处理事项、库存、临期食材、可做菜品、摄入记录和
  最近拍摄；没有数据的区块不会渲染成一排 `0` 或空图表；
- 持久化拍照录入会话：可在同一次会话拍多张照片、选择证据图、关闭后稍后继续、明确
  放弃，确认请求重复提交也不会重复创建库存；
- 摄像头集成：状态、同源 MJPEG 实时预览、网页快门、GPIO 实体按钮拍摄同步和本地图库；
- 主软件自有图片库：从摄像头取得 JPEG 后校验 SHA-256，再原子写入主软件媒体目录；
- 库存批次、搜索、位置筛选、使用、丢弃以及不可丢失的数量流水；
- 商品口味和可选营养基准；只有明确 `record_meal=true` 的“吃掉”操作才进入真实摄入记录；
- 7/28 天营养与口味视图；样本不足时隐藏趋势，而不是生成模拟数据；
- 初始化设置：饮食目标、偏好、过敏和用药记录；相机离线时库存仍可使用；
- 数据库迁移、外键、短事务、乐观版本检查，以及数据库与正式图片的一键校验备份包。

## 运行架构与端口

```text
浏览器 / 触摸屏
        │ 只访问同源 HTTP
        ▼
主软件 FastAPI 0.0.0.0:8000
  ├─ 前端、REST、MJPEG 代理
  ├─ SQLite：库存、会话、媒体索引、餐食快照
  ├─ 正式图片：SMART_FRIDGE_DATA_DIR/media/captures/
  └─ Camera Gateway
             │ localhost HTTP
             ▼
摄像头服务 127.0.0.1:8001
  ├─ USB 摄像头唯一所有者
  ├─ GPIO 实体按钮
  └─ 摄像头侧图片、拍摄索引、MJPEG
```

主软件不直读摄像头数据库或图片目录；两者只通过版本化 HTTP API、capture UUID、时间和
SHA-256 协作。浏览器也不应直接访问 8001。详见
[ARCHITECTURE.md](ARCHITECTURE.md)，研究依据和路线见
[docs/RESEARCH_AND_DECISIONS.md](docs/RESEARCH_AND_DECISIONS.md)。

## 本地安装与预览

Python 3.10–3.12。首次安装主软件：

```bash
cd smart_fridge_app
chmod +x install.sh start.sh
./install.sh
cp .env.example .env
```

之后使用两个终端。终端 A 从项目工作区启动摄像头服务：

```bash
cd camera_system
python3 capture_service.py \
  --host 127.0.0.1 \
  --port 8001 \
  --no-ocr
```

终端 B 启动主软件：

```bash
cd smart_fridge_app
./start.sh
```

本机预览打开 `http://127.0.0.1:8000`；同一可信局域网的其他设备打开
`http://设备IP:8000`。API 文档位于 `http://127.0.0.1:8000/docs`。点击首页的
“拍照添加食材”才会开始 MJPEG 预览；关闭对话框时浏览器会断开预览，避免无意义占用。

没有连接摄像头时可以只运行主软件并检查首页、库存、图库和设置；拍摄区域会明确显示
相机不可用。主软件固定使用 8000，集成模式下摄像头固定使用本机 8001，不要让两个服务
同时占用 8000。

## 拍照录入与真实摄入的语义

1. 打开拍照窗口时，后端创建或恢复一个 `intake_session`；浏览器本地只保存会话 ID，
   会话状态、照片关系、所选照片和确认结果都在 SQLite；
2. 每次拍摄先由 8001 保存，主软件随后下载 JPEG、核验校验和、写入自己的图片库，并把
   照片附加到会话；
3. 关闭 `×` 只是“稍后继续”；“放弃本次”才把会话标成 `cancelled`，已经安全保存的照片
   不会被删除；
4. “确认加入库存”在一个事务中创建商品/批次、`receive` 流水、会话结果并将会话标成
   `confirmed`；再次提交同一会话返回已创建批次，不会重复入库；
5. 库存减少不自动等于吃下。API 的 `record_meal` 默认为 `false`；当前网页的“吃掉”操作
   明确发送 `record_meal=true`，丢弃和普通库存调整不会进入营养或口味统计。

营养数值只在库存单位与营养基准单位相同，或属于可换算的质量单位（g/kg）或体积单位
（ml/l）时按本次食用量缩放。系统尚不知道“一盒等于多少克”这类商品级换算，无法换算时
仍保留真实餐食记录，但不捏造营养数值。

## 正式数据位置

`SMART_FRIDGE_DATA_DIR` 默认为 `smart_fridge_app/runtime`；示例 systemd 服务将其设为
`/var/lib/smart-fridge`。

| 数据 | 本地开发默认 | 示例生产部署 |
| --- | --- | --- |
| 主软件数据库 | `smart_fridge_app/runtime/database/smart_fridge.sqlite3` | `/var/lib/smart-fridge/database/smart_fridge.sqlite3` |
| 主软件正式图片 | `smart_fridge_app/runtime/media/captures/YYYY/MM/DD/<capture-id>.jpg` | `/var/lib/smart-fridge/media/captures/YYYY/MM/DD/<capture-id>.jpg` |
| 主软件隔离区 | `smart_fridge_app/runtime/media/quarantine/` | `/var/lib/smart-fridge/media/quarantine/` |
| 摄像头侧索引 | `camera_system/data/capture_catalog.sqlite3` | `/var/lib/camera-capture/catalog.sqlite3` |
| 摄像头侧图片 | `camera_system/captures/` | `/var/lib/camera-capture/images/` |

对已经导入主软件的照片，`SMART_FRIDGE_DATA_DIR/media` 是主应用读取和展示的正式副本；
摄像头侧目录仍是采集服务的运行记录，并可能包含尚未同步的 GPIO/历史拍摄。

## 备份边界

创建主应用完整备份包：

```bash
cd smart_fridge_app
PYTHONPATH=. .venv/bin/python -m app.tasks.backup --output-dir backups
```

成功后会得到一个原子发布的目录，例如：

```text
backups/smart_fridge_YYYYMMDD_HHMMSS/
├── smart_fridge.sqlite3
├── manifest.json
└── media/
    └── captures/YYYY/MM/DD/<capture-id>.jpg
```

命令先用 SQLite Backup API 取得一致性快照并执行 `integrity_check`，再按该快照中的
`media_assets` 复制所有正式图片。源文件和副本都会核对 SHA-256，已记录大小也会复核；
`manifest.json` 保存数据库与每张图片的路径、字节数和 SHA-256。任何引用图片缺失或不匹配
都会让整个备份失败，临时目录不会冒充成功备份。

边界是：

- 这个目录包就是主应用恢复集，包含该数据库快照及它引用的全部正式图片，不需再手工分开
  复制 `media/`；
- 包只收集数据库引用的 `ready` 图片，不包含 quarantine、孤儿文件或快照之后才产生的记录；
- 恢复整台设备的全部采集历史仍要另行备份摄像头侧 catalog 和 images，尤其是尚未同步到
  主软件的 GPIO 拍摄；当前还没有协调“主应用包 + 摄像头数据”的整机备份命令；
- 不要直接复制正在运行的 SQLite 主文件替代这个命令。完整恢复能力仍须通过定期还原与
  manifest 全量校验来证明。

运行数据已被 `.gitignore` 排除，不应装入源码发布包。SQLite 运行时没有 2026 WAL-reset
修复时，程序自动使用 rollback journal；主软件必须保持 `--workers 1`。

## 测试

首次运行完整测试前安装测试客户端：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

无需硬件即可运行：

```bash
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
cd ../camera_system
PYTHONPATH=. ../smart_fridge_app/.venv/bin/python -m unittest discover -s tests -v
```

当前测试覆盖数据库迁移、库存/流水、媒体索引、持久化录入会话、重复确认、真实餐食统计、
健康检查、相机离线降级、JPEG/SHA-256 安全检查和数据库+媒体备份包。

## 已知限制

- 单用户、可信局域网原型：没有账号、设备 PIN、TLS、速率限制或多用户权限；
- 会话会保存照片、选择和确认结果，但表单字段尚未自动保存到后端草稿；刷新页面后需重填；
- 一次会话当前确认一个库存批次，还没有一张照片识别多个食材的候选编辑器；
- OCR/视觉/条码/语音/相册导入尚未接入；营养和口味目前由用户手动填写；
- 餐食记录还没有编辑、撤销和多食材合并成同一餐的 UI；网页暂将餐型记录为 `other`；
- 图库进入时只同步最近一批摄像头记录；尚无后台持续同步、启动对账、缩略图、磁盘配额、
  自动保留期、软删除或包含 camera_system 未同步记录的整机备份；
- 食谱建议是少量确定性规则，不是完整营养推荐，也不提供医疗安全结论；
- 尚未在目标 Orange Pi 上完成双预览、连续 100 张、断线重连、磁盘满和完整恢复验收。

## 安全边界

不要把 8000 或 8001 直接暴露到公网。摄像头画面、图库和 API 都只经主软件同源入口提供；
远程使用前必须加入认证、TLS、速率限制和明确的数据保留/删除策略。任何 API 密钥只能放在
设备环境变量或权限受限的 secrets 文件中。老师 demo 压缩包中的真实配置、数据库和上传
图片均未复制到本项目。
