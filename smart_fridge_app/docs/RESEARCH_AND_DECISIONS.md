# 调研、demo 审查与长期路线

日期：2026-08-07

## 1. 材料回顾后的真实需求

研究素材 PPT 确定了 Orange Pi、摄像头、GPIO 按钮、本地 OCR/YOLO、库存和个性化食谱
方向；思维导图进一步给出首页、食物录入、营养、下一餐、食物展示、初始化设置与装置
六个板块。老师 demo 证明了 FastAPI + SQLite + Vanilla JS 在 Orange Pi 上适合作为原型，
但它的拍照只是手机 `<input capture>`，不包含设备端实时预览、硬件拍照、应用自有图库或
可恢复的录入事务。

因此当前阶段不是“先做一个看起来像 AI 的页面”，而是先完成四个可验证事实：

1. 原始证据图先安全保存，摄像头断线不能损坏主软件；
2. 照片与确认过程跨关闭/重启可恢复，重复确认不会重复入库；
3. 首页只显示真正存在或需要处理的内容；
4. 库存减少不等于摄入，只有用户明确记录为吃下的内容才进入营养和口味趋势。

## 2. 老师 demo：保留与拒绝

### 值得保留

- FastAPI API、Service、Repository、Schema 的分层；
- 商品、库存批次、库存流水三层模型；
- 识别候选必须人工确认后入库；
- 本地优先、原生前端、SQLite 与 ONNX CPU 推理方向；
- 外部服务失败时回退到本地规则。

### 不能直接复制

| 问题 | 后果 | 当前框架的处理 |
| --- | --- | --- |
| 压缩包含疑似真实 DeepSeek Key | 凭据泄露和费用风险 | 不复制；只提供环境变量模板，原 Key 应撤销/轮换 |
| 打包运行数据库、上传图、处理图、缓存 | 隐私泄露、污染初始化状态 | 运行目录被忽略，发布使用源码白名单 |
| 根据原文件名触发固定 demo 结果 | 同名文件可绕过真实识别 | demo fixture 以后必须是服务端显式开关 |
| 日期确认不校验目标批次 | A 的日期可写到 B | 会话绑定选中媒体和不可变 ID，确认在事务内完成 |
| 已确认的日期证据仍可删除 | 审计链断裂 | 媒体、会话、批次与流水使用明确外键和保留策略 |
| WAL 下只复制主 `.db` | 在线备份可能不完整 | SQLite Backup API；应用备份包同时收集正式图片并生成 SHA manifest |
| async 接口同步跑 OCR/YOLO | 阻塞全部请求 | 识别应做持久化任务；CPU 推理不占事件循环 |
| 识别失败删除原图 | 无法复查或重试 | 证据先保存，失败作为可见状态 |
| YOLO 只有 banana，番茄是 fixture | 演示能力被误当成泛化能力 | 模型必须记录版本、类别、阈值和验收集 |
| 原图目录静态公开、无鉴权 | LAN 外泄露 | 图片经主软件 capture ID 端点返回；公网前仍需认证/TLS |

## 3. 当前已经落地的产品与技术决策

### 3.1 首页是行动队列，不是功能入口墙

当前首页固定保留日期和“拍照添加食材”，其他区块由后端 `availability` 与真实数组决定：

- 主系统和摄像头都正常时不显示绿色“正常”状态；只有异常才占据顶栏；
- 无库存、无照片、无待续会话时，只显示一个“拍下第一件食材”的主空状态；
- 活动库存存在后才显示库存概览；临期、过期、日期待补只有数量大于 0 才出现；
- “现在要处理”只列过期、临期、日期待补或未完成会话；
- 确定性食谱只有匹配到所需且未过期的库存时出现；
- 最近拍摄和识别记录仅在主应用媒体库确有图片时出现；
- 没有真实餐食样本时整段摄入区隐藏，而不是展示 `0 kcal` 和空趋势线。

加载中、有效的零、首次使用、筛选无结果、数据不足和错误是不同状态。当前首页已经实现
首次使用/有效零/数据不足的显隐；库存页的筛选无结果仍保留上下文空状态，网络错误显示
错误信息而不伪装成零。

### 3.2 拍照添加是持久化会话

拍照使用原生 `<dialog>` 打开大画幅实时取景，而不是把摄像头塞进一个小表单。打开时
创建或恢复 `intake_session`；每张照片先由摄像头服务落盘，再由主软件下载、核验并原子
写入正式媒体目录，随后附加到会话。用户可以：

- 在一次会话连续拍多张并选择证据图；
- 使用 `×` 关闭窗口、停止 MJPEG，之后从首页或本地会话 ID 继续；
- 从应用图库把尚未确认的历史照片附加到新/恢复会话；
- 明确“放弃本次”，但保留已经保存的证据图；
- 人工确认名称、数量、位置、到期日、口味和可选营养后再写库存。

会话确认把批次、`receive` 流水、会话与结果放在同一事务；重复确认返回已有批次。当前
恢复边界覆盖会话状态、照片、选择和结果，尚不覆盖刷新后的未提交表单文字。

### 3.3 主应用拥有正式图片副本

旧设计只在 `media_assets` 记录摄像头元数据，主库恢复后仍依赖 camera_system 路径。当前
设计已经改为：导入即把 JPEG 写入
`SMART_FRIDGE_DATA_DIR/media/captures/YYYY/MM/DD/<capture-id>.jpg`，数据库保存相对路径
和 SHA-256，主应用图库从该副本读取。摄像头离线后，已导入照片仍能查看。

摄像头 catalog/images 仍是采集侧记录，可能包含尚未同步的 GPIO 拍摄；因此“恢复主应用”
与“恢复整台设备全部采集历史”是两个边界。主应用备份命令会原子发布一个
`smart_fridge_YYYYMMDD_HHMMSS/` 目录包：一致性 SQLite 快照、该快照引用到的主应用
正式图片和记录数据库/每张图片大小及 SHA-256 的 `manifest.json`。camera_system 未同步
数据仍需由设备级备份另行覆盖。

### 3.4 只有 `record_meal` 产生真实摄入

`inventory_events` 回答“库存发生了什么”，`meal_logs/meal_items` 回答“用户明确吃了什么”。
任何 `consume` 都会写数量流水，但 API 的 `record_meal` 默认为 `false`；当前网页“吃掉”
操作明确传 `true`，丢弃不产生餐食。

餐食项保存当时的商品名称、类别、数量、单位、主要口味和可计算营养快照。营养只在同单位、
g↔kg 或 ml↔l 时缩放；不能确定“一盒是多少克”时保留餐食事实，但营养字段为空。
`/insights` 只查询餐食表：

- 至少一条带营养的餐食才显示营养合计；至少两个有记录日期才画每日趋势；
- 至少一条口味记录才显示口味分布；累计 3 次后才把标题称为“趋势”；
- 覆盖率与样本量同时显示，避免把少量手填数据包装成完整膳食评估。

### 3.5 动效和可访问性是功能约束

当前 modal 进入/退出分别为 250/150 ms，遮罩 150/100 ms；实时画面仅淡入，不缩放。
浏览器启用 `prefers-reduced-motion: reduce` 后，动画与平滑滚动缩短为近乎即时。原生
`<dialog>` 负责 modal/inert 语义，`Escape` 走受控关闭，关闭后焦点返回原按钮；放弃会话是
单独的明确动作，关闭窗口不会误删草稿或照片。

## 4. 权威资料与同类项目证据

### 食品库存与首页信息架构

[Grocy](https://github.com/grocy/grocy) 及其
[食品库存教程](https://github.com/grocy/grocy-docs/blob/master/tutorials/food.md)表明，成熟食品
库存至少需要产品、位置、批次/最佳食用期、购买、消耗、转移和单位换算；其主工作窗口
也是 stock overview，而不是通用内容 feed。

[MyFitnessPal Today](https://support.myfitnesspal.com/hc/en-us/articles/39985611667341-Your-Today-tab)
把用户最频繁的 Diary/当日记录放到首页，并让常用添加动作保持直接可达。
[Apple Health Summary](https://support.apple.com/en-mide/guide/iphone/iphe3d379c32/ios)允许用户
固定重要指标，并只在系统检测到趋势后呈现 Trends。两者共同支持“高频动作常驻、推导
内容按资格出现”的首页策略。

IBM [Carbon Empty States](https://carbondesignsystem.com/patterns/empty-states-pattern/)明确区分
首次无数据、操作后无结果和错误状态；空状态应替换缺失元素，并给出一个主要下一步，而
不是保留空表头或在仪表盘重复多个主按钮。

### 摄像头单一所有者与预览

Picamera2 官方
[MJPEG 示例](https://github.com/raspberrypi/picamera2/blob/main/examples/mjpeg_server.py)使用一个
摄像头实例、最新帧槽和条件变量服务多个客户端；维护者在
[讨论 #569](https://github.com/raspberrypi/picamera2/discussions/569) 中说明 libcamera 的同一相机
应由单一进程控制。FastAPI
[worker 文档](https://fastapi.tiangolo.com/deployment/server-workers/)说明 `--workers` 会启动
多个独立进程。因此相机保留为独立 daemon，主软件单 worker。

首版使用 `<img>` + MJPEG：每帧独立、慢客户端可跳帧、浏览器原生展示。标准 WebSocket
[没有自动背压](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)，不适合首版
连续推送 JPEG；以后小事件可用 WebSocket，远程多消费者视频再评估
[MediaMTX](https://github.com/bluenviron/mediamtx) 或
[Frigate restream](https://docs.frigate.video/configuration/restream/)。

### 拍照复核、权限与 modal

Google [ML Kit Document Scanner](https://developers.google.com/ml-kit/vision/doc-scanner/android)
采用专用取景页加预览页；这个模式支持“先捕获、复核/重拍、再提交”，虽然本项目拍的是
食材而不是文件。未来加入手机相册时应使用系统
[Android Photo Picker](https://developer.android.com/training/data-storage/shared/photo-picker)，只给
应用访问用户选择的照片，而不是申请整个图库。

W3C [Modal Dialog Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)要求背景 inert、
焦点保持在 modal、`Escape` 可关闭并在关闭后返回触发点。当前使用原生 `<dialog>` 和显式
焦点恢复遵循这一边界。

[Material Motion tokens](https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md)
提供语义化缓动/时长，并强调运动面积越大时长才增加；
[Atlassian Motion](https://atlassian.design/foundations/motion/)给出约 250 ms 的 modal entrance、
退出更快和 reduced-motion 即时化建议。W3C
[Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html)
要求非必要的交互动画可关闭。

### SQLite 并发与备份

[SQLite WAL 文档](https://sqlite.org/wal.html)说明 WAL 让读写更容易并行，但仍然只有一个
写者。2026 年披露的 WAL-reset 问题影响部分旧版本；代码只有在确认运行库包含修复时才
启用 WAL，否则使用 rollback journal。外键依照
[SQLite foreign key 文档](https://sqlite.org/foreignkeys.html)逐连接开启；在线快照使用
Python/SQLite Backup API，而不是复制正在运行的主文件。

### 事件式拍摄的后续价值

[FridgeBot](https://github.com/saubury/fridgebot_openai) 使用亮度判断冰箱门状态，并等待
白平衡稳定后保存前后图。这个思路适合后续门事件触发，但它没有可靠库存账本、失败恢复、
应用自有媒体和人工确认，不能作为底座直接复制。

## 5. 主要工程风险与验收门槛

| 风险 | 当前策略 | 进入下一阶段前的验证 |
| --- | --- | --- |
| 相机被多进程抢占 | 独立 camera daemon；主软件只走 8001 API | 两个预览页同时运行 30 分钟 |
| 断线后旧帧被再次保存 | 帧时间戳、`--max-frame-age`、错误 gate | 拔线拍照必须 503；重插后恢复 |
| 摄像头已写、主软件导入失败 | 主软件 `.part` + fsync + replace；DB 失败移 quarantine | 每个故障点注入异常并启动对账 |
| GPIO 拍摄未同步 | 识别记录页同步最近 24 条 | 后台增量同步与断点/分页测试 |
| CPU JPEG/OCR 抢占预览 | 最新帧槽；领域 OCR 默认不在 camera daemon | 预览中连续拍 100 张 |
| 模型错识别污染库存 | 候选 → 人工确认 → 流水 | 模型输出永远不能直接写库存事件 |
| 刷新丢失表单文字 | 会话/照片已持久化，字段尚未自动保存 | 增加 draft 更新、版本和恢复测试 |
| 单位语义混乱 | 只做同单位、质量和体积换算 | 商品级单位换算与验收集 |
| 多端并发覆盖 | lot `version` + expected_version | 两页面并发时旧请求返回 409 |
| 库存减少污染摄入 | `record_meal` 默认 false；Insights 只读 meal 表 | 导入/丢弃/纠错均不得改变趋势 |
| 数据库有记录但图片缺失 | 导入核验 SHA；应用备份包含引用媒体与 manifest | 从备份包恢复并逐项校验 SHA |
| camera 有未同步图片 | 设备级备份另含 camera catalog/images | 从空设备恢复并补齐未同步历史 |
| 磁盘持续增长 | 当前不自动删除 | 磁盘告警、缩略图、配额、保留期测试 |
| 无鉴权局域网服务 | 8001 仅 localhost；8000 限可信 LAN | 远程访问前加入认证、TLS、速率限制 |

## 6. 当前已知限制

- 目标 Orange Pi 上的双预览、连续 100 张、断线恢复、磁盘满和整机恢复尚未验收；
- 会话只确认一个库存批次；没有多物体候选、识别任务、置信度或逐项确认；
- 会话照片和选择可恢复，但刷新页面后未提交表单字段需重填；
- 没有相册上传、条码、语音、包装日期二次拍摄或小票入口；
- 营养/口味由用户手动填写，未连接权威食品营养数据库；
- “吃掉”目前是一条食材一条 meal，餐型默认为 `other`；无餐食编辑、撤销或组合；
- 图库只在进入页面时同步有限数量，尚无后台 worker、启动对账、缩略图和清理；
- 主应用备份包不等于整机采集备份；camera_system 未同步内容仍在边界外；
- 规则食谱覆盖很小，尚无完整偏好、营养目标或采购建议；
- 没有账号、PIN、TLS、速率限制、多用户或公网支持。

## 7. 分阶段路线

### Phase 0（当前已实现）

- 8000 主应用与 8001 摄像头进程隔离、相机离线降级；
- 应用自有 JPEG、媒体索引、图库同步与 SHA-256 校验；
- persistent intake session、多图选择、恢复、取消和幂等确认；
- 商品、批次、库存流水、真实餐食快照、设置和显式 availability；
- “无数据不显示”的首页、原生 modal、reduced-motion；
- SQLite 迁移/日志模式保护、测试和部署模板；
- 一条命令生成数据库 + 正式媒体 + SHA manifest 的主应用备份包。

### Phase 1：可靠性与恢复验收

- 100 张连续拍摄、双预览、浏览器中断、摄像头拔插和服务重启；
- 图片/数据库启动对账、quarantine 管理、后台增量同步；
- 应用备份包自动恢复验证；设备级 camera catalog/images 备份与恢复演练；
- 缩略图、磁盘空间告警、配额、保留期、软删除和导出；
- `/dev/v4l/by-id` 设备选择、GPIO 失败重试；
- 同源登录，或至少设备 PIN/session。

### Phase 2：多入口与完整人工账本

- 会话表单 draft 自动保存、版本检查和跨设备恢复；
- 一次会话多个食材候选、逐项确认和幂等键；
- 系统 Photo Picker、条码枪/相机条码、文字、语音作为平级入口；
- 包装日期二次拍摄并强绑定目标批次；
- 商品别名、多个条码、商品级单位换算；
- 餐食编辑/撤销、餐型、多个食材组合和营养来源标记。

### Phase 3：模型评测后接入

- RapidOCR、本地 ONNX、云端多模态使用统一 Recognizer 契约；
- 持久化 `recognition_job/candidate/confirmation`，保存 provider、model、version、hash、
  threshold、latency 和 raw result；
- 建立真实冰箱反光、凝露、遮挡、倾斜和中文日期的数据集；
- 只在验收集达到门槛后开放默认入口，始终保留人工确认和失败回退。

### Phase 4：推荐与营养

- 接入可追溯营养资料，持续展示样本量和覆盖率；
- 先使用客观膳食规则和确定性库存筛选，优先临期但排除过期食材；
- 推荐可直接进入餐计划/购物清单，不做不可执行的内容 feed；
- LLM 只生成候选，必须有本地回退、缓存、费用上限和来源；
- 过敏/用药只做警示和人工升级，不承诺医疗安全。

### 暂缓

多设备离线写入、全自动库存变化、连续录像、WebRTC/HLS、云同步和公网访问，都不应在
采集可靠性、媒体恢复和库存一致性门槛通过前启动。
