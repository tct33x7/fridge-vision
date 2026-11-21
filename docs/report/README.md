# 报告

**正文由项目成员写**，这里只放结构和每一节该用的材料。建议英文正文。
图放 `figures/`：只放挑过的、**没有人脸**的帧和图表。

## 结构（每节大约写多少、用什么材料）

| 节 | 回答什么问题 | 材料 |
| --- | --- | --- |
| 1 问题 | 家里冰箱的什么事让你想做这个？之前的拍照 / 扫码版本为什么没人用？ | `archive/` 里的旧项目（研究素材 PPT）；自己家冰箱的一次盘点（有几样、几样过期、门格占多少、初始化花了几分钟） |
| 1b 别人怎么做的 | 这个想法谁做过？商用的、论文里的、学生做的分别怎么做、做到什么程度？我们和他们**哪里一样、哪里不同**？ | 下面"相关工作线索"；**每一篇都要自己打开读过才能引用** |
| 2 装置 | 相机装在哪、怎么触发、主机是什么、整套怎么连 | [ARCHITECTURE §2–4](../ARCHITECTURE.md)；实物照片（`hardware/`） |
| 3 测量方法与第一次结果 | 怎么记真值？测了哪些指标？正面机位的结果说明了什么？真值本身错了多少？ | [E01](../experiments/E01_front_20261107.md)、人工可见性表、失败帧；[数字口径核对表](../experiments/CLAIMS_CHECK.md) |
| 4 设计与改动 | 为什么换到门洞上方？方向怎么判、手里的东西怎么认、库存怎么维护？ | ARCHITECTURE §3、§5、§6；[DECISIONS](../DECISIONS.md) |
| 5 前后对比 | 同一套指标，E01 和 E04 并排；你做的那一次改进前后差多少？ | E04 记录；对比表；折线图 |
| 6 局限 | 门格、冷冻抽屉、只有一个人测、真值本身的错误率、规则是在哪些录像上调的、数字来自 Mac 还是板子…… | 各实验的"局限"一节；[数字口径核对表](../experiments/CLAIMS_CHECK.md) |
| 7 学到什么 | 哪个假设被数据推翻了？下次会怎么做？ | DECISIONS；各实验的"对设计的影响" |
| 8 协作说明 | 你做了什么，老师做了什么，AI 写了什么代码和文档，你怎么确认自己理解了 | 根目录 [README](../../README.md)"协作与 AI 使用"；`git log` |

## 写之前自查

- 报告里每个数字都能在 `docs/experiments/` 里找到出处，你能说出它是怎么算的。
- 每个比例都写成 k/n（分子 / 分母），样本少时再加区间；不要只写百分比。
- 每个数字标明来自哪条识别路线：Mac 上的 YOLO11s、板子代码在 Mac 上的代理、还是板子上实际运行的 NPU。
- 每个数字标明是"调规则用的录像"上的还是"冻结规则以后新录的"录像上的。
- [数字口径核对表](../experiments/CLAIMS_CHECK.md) 里每一行都复核过，原文改好了。
- 引用的论文、专利、产品资料，作者自己打开读过；AI 给的链接和摘要只当线索。
- 每张图都标了来自哪次会话、哪个实验。
- 第 8 节如实写分工：谁做了什么、AI 写了哪些代码和文档、成员怎么确认自己理解了。

## 相关工作线索（只是线索）

下面是 Claude 11-13 查到的资料，链接是查的时候打开过的。**引用前必须自己打开读一遍**，确认内容和这里的一句话描述一致。
有两处要特别核对：两次查资料对 CN113743530A 的描述不一样；三星关于门格的那条脚注只有一次看到了全文。

| 类别 | 资料 | 为什么相关 |
| --- | --- | --- |
| 先例：专利 | Samsung US10956856B2（2015 优先权）<https://patents.google.com/patent/US10956856B2/en> | 按"伸进去 / 拿出来时手里有没有东西"分四种情况，和 ARCHITECTURE §5.2 的表基本一样 |
| 先例：专利 | Samsung KR20250116217A（2024）<https://patents.google.com/patent/KR20250116217A/en> | 顶部正中相机，另加副相机覆盖门格 |
| 先例：专利 | 美国专利申请 2022/0414391 <https://ipiq.io/patents/428345> | 相机看门口，按运动方向判断放入还是取出 |
| 先例：专利 | 华南理工 CN112991379A <https://eureka.patsnap.com/patent-CN112991379A> | 售货柜：手离开区域的方向判断拿走还是放回 |
| 先例：专利 | CN113743530A <https://patents.google.com/patent/CN113743530A/zh> | 售货柜：两种方法算的数量不一致时转人工 |
| 先例：论文 | Morris, Welch & Schroeder，IEEE SoutheastCon 2021 <https://par.nsf.gov/servlets/purl/10319207> | 冰箱顶部相机 + 手部检测，按脚本录的视频，规模和 E01 相近 |
| 先例：产品 | 三星 AI Vision Inside <https://news.samsung.com/uk/samsung-unveils-new-refrigerator-lineup-equipped-with-screens-and-enhanced-ai-vision-inside-feature> | 量产的放入 / 取出识别；官方说明里写了能认的食物种类和门格的限制 |
| 先例：行业 | 视觉售货柜综述（36Kr，2019）<https://www.36kr.com/p/1723152711681> | 每样商品要大量训练图、要挡板限制一次拿多少；都是厂商说法 |
| 教训 | Which? 评测加装式冰箱相机（2019）<https://www.which.co.uk/news/article/is-it-worth-buying-a-fridge-camera-aNLE02N0tb1Z> | 认不出东西、手动标注太烦 |
| 教训 | 博世关闭已售冰箱的摄像头功能（heise，2026-03）<https://www.heise.de/news/Bosch-Smarte-Kuehlschraenke-verlieren-Kamerafunktion-11195405.html> | 需求不足；联网功能可以被厂家关掉 |
| 教训 | Amazon Just Walk Out 和人工复核的争议 <https://www.aboutamazon.com/news/retail/amazon-just-walk-out-improves-accuracy> | 拿取 / 放回识别即使大公司也难；冰箱门是它点名的难点 |
| 学术 | 100DOH（CVPR 2020）<https://arxiv.org/abs/2006.06669>；EPIC-KITCHENS-100 <https://arxiv.org/abs/2006.13256> | 手和物体的接触；厨房里的东西是长尾分布 |
| 学术 | Kyocera 冰箱食物识别（Frontiers in AI，2024）<https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2024.1442948/full> | 按单张图评，不是按每次开门评 |
| 学术 | YOLO-World <https://arxiv.org/abs/2401.17270>；OWL-ViT <https://arxiv.org/abs/2205.06230>；CLIP <https://arxiv.org/abs/2103.00020> | 不限于 80 类的识别办法 |
| 背景 | UNEP 食物浪费指数 2024（联合国新闻）<https://news.un.org/en/node/1148036>；郑州家庭食物浪费称重研究（《自然资源学报》2024）<https://www.jnr.ac.cn/CN/abstract/article/1000-3037/69666> | 两者的估计差很多，因为方法不同；引用时各自写清方法 |
| 背景 | Parker & Stedman 1992 <https://www.aceee.org/files/proceedings/1992/data/papers/SS92_Panel3_Paper21.pdf> | 美国的老数据：每天开冷藏门几十次 |

### 开源项目线索（GitHub，11-21 查）

下面是 Claude 11-21 在 GitHub 上搜到的（搜了"冰箱 + 相机 / 库存 / 进出""售货柜 / 无人货柜""手–物体检测""过线计数""A733 NPU"几组词，中英文都搜了）。
和上表一样只是线索，**引用前必须自己打开读一遍**。最后一列写明 Claude 当时核对到哪一步。

- **这几轮搜索里，没有找到**做"门洞上方相机 + 自动判断放入 / 拿出 + 逐动作对照真值评测"的开源项目。这是"没搜到"，不等于"不存在"。
- **没有许可证的仓库只能借思路、在报告里引用，不能复制代码。**
- 星标数、更新日期这些会变，这里不写；引用时以当天打开看到的为准。

| 类别 | 资料 | 许可证 | 为什么相关 | 核对到哪 |
| --- | --- | --- | --- | --- |
| 先例：黑客松 | stphnhng/SmartFridgeImageRecognition（2017，T-Mobile IoT 黑客松）<https://github.com/stphnhng/SmartFridgeImageRecognition> | MIT | 按方向判断进出：面对相机从左往右算放入，从右往左算拿出。README 里没有准确率数字 | 读了 README 全文 |
| 先例：课程项目 | ticiive/Smart-Fridge-User-Presented-Item-Recognition（2026-09，Ibmec 的课程作业，葡萄牙语）<https://github.com/ticiive/Smart-Fridge-User-Presented-Item-Recognition> | 无 | 相机在冰箱上方；YOLO-World 找东西，再按"OCR → CLIP → 本地大模型"三级认名，每样东西只要一张参考图，不训练。README 写：22 次经过里 20 次给出判断、19 次对（目录 6 样东西，人把东西举到相机前）；局限一节写明进和出没有自动区分，全记成放入（有按过线判方向的选项，默认关） | 读了 README 全文 |
| 先例：课程项目 | Zilinghan/smart-fridge（FreshIO，UIUC CS598，2022）<https://github.com/Zilinghan/smart-fridge> | 无 | 光线传感器触发录像（README 说代码里是用键盘输 0 / 1 模拟的，传感器没接上）；食物检测模型自己训练；README 说主要问题是训练数据不够 | 读了 README 前半 |
| 先例：开源 | dk0113-Y/image-based-inventory-management（2026）<https://github.com/dk0113-Y/image-based-inventory-management> | 无 | C++ 写的冰箱库存：开门前后各取一张关键帧，比较两次 YOLO 结果；事件类型里有"不确定"，进待确认；README 有一张"证据等级"表，写明真实相机和板子上还没验证 | 读了 README 全文 |
| 先例：开源 | Dilyar93/fridge-inventory-exploration（2026-09）<https://github.com/Dilyar93/fridge-inventory-exploration> | 无 | 用前后两张图数瓶子，8 个场景 16 张图；真值分"看得见的数"和"实际的数"；每次运行记下模型哈希、库版本和阈值 | 读了 README 全文 |
| 先例：售货柜 | liliwo0117/vending-cabinet-tight-roi-recognition（2026-11，论文的参考实现）<https://github.com/liliwo0117/vending-cabinet-tight-roi-recognition> | MIT | 售货柜商品识别：YOLO11m 找到商品 → 贴边裁图 → 小分类器；8 类测试集 632/680。阈值只在验证集上选、选完冻结、测试集只用一次、报 Wilson 区间 | 读了 README 开头 |
| 先例：售货柜 | Kylie12347/Graduation（2026，毕业设计）<https://github.com/Kylie12347/Graduation> | 无 | 无人售货柜：重量 + RFID + 大模型看多帧图片，几个来源对不上就转人工；全部是仿真，没有真柜子 | 读了 README 开头 |
| 先例：课程项目（不在 GitHub） | Cornell ECE 5725 Smart Fridge（2023）<https://courses.ece.cornell.edu/ece5990/ECE5725_Fall2023_Projects/4%20Friday%20December%208/2%20Smart%20Fridge/Thursday_ft243_zl874/index.html> | — | 门磁接 GPIO，扫条码认东西；放入还是拿出由用户在界面上选 | 由 Claude 的查资料子任务读的网页，没有再核对一遍 |
| 可借的库 | roboflow/supervision 的 `LineZone`（0.32.0）<https://github.com/roboflow/supervision> | MIT | 现成的过线计数。两个参数和 `counter.py` 的滞回、丢失续接是同一类想法：`minimum_crossing_threshold`（过线后在另一侧连续看到几帧才算）、`max_absent_frames`（短暂消失后还记得在哪一侧）。可以当对照组，回答"为什么不用现成的库" | 读了这两个参数的源码和说明 |
| 可借的库 | roboflow/trackers <https://github.com/roboflow/trackers> | Apache-2.0 | 重新实现的 SORT、ByteTrack、OC-SORT、BoT-SORT、C-BIoU、McByte。[E02b](../experiments/E02b_trackers_20261108.md) 没试过的是后两个；C-BIoU 的说明写的是针对快速或不规则运动 | 读了 README 的算法表 |
| 可借的方法 | YOLO-World / YOLOE（开放词表检测，ultralytics 里自带）<https://github.com/AILab-CVC/YOLO-World> <https://github.com/THU-MIG/yoloe> | GPL-3.0 / AGPL-3.0 | 用文字指定要找的类别（jar、bag、box），不用训练，对付 YOLO 不认识的东西。上面 ticiive 那个项目用的就是 yolov8s-worldv2 | 只核对了本机 ultralytics 8.4.87 里有这两个类；没有跑过 |
| 可借的方法 | 手–物体检测：ddshan/hand_object_detector（100DOH）<https://github.com/ddshan/hand_object_detector>、EvaCheng-cty/hands23_detector <https://github.com/EvaCheng-cty/hands23_detector>、AhmadDarKhalil/HOI-DETR <https://github.com/AhmadDarKhalil/HOI-DETR> | 都是 MIT | 直接找"手和手里拿着的东西"，不管东西是什么类别。三个 README 里都只有配 NVIDIA 显卡（CUDA）的装法，Mac 和板子上能不能跑没人写过 | 只按关键词看了 README |
| 板子 | Radxa 文档：全志 A733 的 NPU 上跑 YOLO11 <https://docs.radxa.com/en/cubie/a7a/app-dev/npu-dev/model-zoo/yolo11> | — | 和 OrangePi 4 Pro 同一颗芯片：导出 ONNX → 全志 Model Zoo 的 Docker 里量化 → 导出 `.nb`。文档列的 yolo11s@640 单帧推理 31.9 ms，只算推理，而且是 Radxa 的板子，不能直接和这里板子的帧率比。转换要一台 x86 的 Linux 电脑，后处理要重写 | 读了网页 |
| 工程参照 | blakeblackshear/frigate <https://github.com/blakeblackshear/frigate> | MIT | 家用监控：先用很省资源的运动检测，决定在哪里跑识别（第 3 步待机的参照） | 只看了 README 的功能列表 |
| 工程参照 | grocy/grocy <https://github.com/grocy/grocy> | MIT | 自建的家庭库存管理，有 REST 接口（库存后端的参照） | 只看了 README 里的几行 |

另外两条没法用的：CMU 课程项目 FreshEyes 的仓库（arstrasser/ece-capstone）11-21 已经打不开；路易斯维尔大学 Morris 的硕士论文（2020）<https://ir.library.louisville.edu/etd/3497> 看起来和上表里的 Morris 等 2021 是同一组工作，没有核实，也没找到代码。
