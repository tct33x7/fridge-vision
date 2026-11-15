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
