# 报告

**正文由项目成员写**，这里只放结构和每一节该用的材料。建议英文正文。
图放 `figures/`：只放挑过的、**没有人脸**的帧和图表。

> **11-25 更新（收尾）**：项目发起人 11-25 决定现在就收尾（[开发故事](../STORY.md)第 15 节）。原来的结构是照"E01 和 E04 前后对比"排的，E04 没有做。
> 所以 Claude 把下表第 2、4、5、6、7、8 节照实际做了的事改了，并在表后面加了一节"每一节能用的数"。改之前的表见 git 历史里这个文件 11-21 的版本。
> 怎么写、哪一节写不写，由项目成员定。

## 结构（每节大约写多少、用什么材料）

| 节 | 回答什么问题 | 材料 |
| --- | --- | --- |
| 1 问题 | 家里冰箱的什么事让你想做这个？之前的拍照 / 扫码版本为什么没人用？ | `archive/` 里的旧项目（研究素材 PPT）；自己家冰箱的一次盘点（有几样、几样过期、门格占多少、初始化花了几分钟） |
| 1b 别人怎么做的 | 这个想法谁做过？商用的、论文里的、学生做的分别怎么做、做到什么程度？我们和他们**哪里一样、哪里不同**？ | 下面"相关工作线索"；**每一篇都要自己打开读过才能引用** |
| 2 装置 | 相机装在哪、怎么触发、主机是什么、整套怎么连。**哪些是做出来并且跑过的，哪些只是定了、没有做** | [ARCHITECTURE §2–4](../ARCHITECTURE.md) 和它开头 11-24、11-25 的两段更新；[SYSTEM_MAP](../SYSTEM_MAP.md)；实物照片（`hardware/`） |
| 3 测量方法与第一次结果 | 怎么记真值？测了哪些指标？正面机位的结果说明了什么？真值本身错了多少？ | [E01](../experiments/E01_front_20261107.md)、人工可见性表、失败帧；[数字口径核对表](../experiments/CLAIMS_CHECK.md) |
| 4 设计与改动 | 为什么换到门洞上方？为什么从"数过线"换成"看手伸进去之前和出来以后手里有什么"？认名字、说不清的时候，各打算怎么办？ | ARCHITECTURE §3、§5、§6；[DECISIONS](../DECISIONS.md) 11-08 和 11-24 的几行；[开发故事](../STORY.md)第 11、12、14 节 |
| 5 前后对比 | 原来打算把 E01 和 E04 并排，E04 没有做。能并排的是位置 D 的同一段录像：数过线对几个，换成你提的判法以后对几个；再加上评判没见过的那 10 次开门。每个数是哪种数据、判的是谁，要跟着数一起写 | [E03 记录](../experiments/E03_position_20261112.md)的"11-21：位置 D"一节（"结果""换一种判法""11-22 下午""11-23""11-24""11-25：收尾"）；下面"每一节能用的数" |
| 6 局限 | 定下来的方案没有在新录像上验证；判的是对话里的 AI，不是程序；真值没有第二个人核对，查出过一次错；只有一个人测、一台冰箱、一个位置；要联网，画面里有人；门格、冷冻抽屉；规则是在哪些录像上调的；数字来自 Mac 不是板子…… | 各实验的"局限"一节；E03 记录的"11-25：收尾"；开发故事的"收尾时停在哪"；[数字口径核对表](../experiments/CLAIMS_CHECK.md) |
| 7 学到什么 | 哪个假设被数据推翻了？下次会怎么做？ | DECISIONS；开发故事"一页看完"里"先以为，再去测"那张表，和最后"留给项目发起人自己写的"那张表；各实验的"对设计的影响" |
| 8 协作说明 | 你做了什么，老师做了什么，AI 写了什么代码和文档，你怎么确认自己理解了 | 根目录 [README](../../README.md)"协作与 AI 使用"；开发故事的"关键决定是谁提的""谁做了什么"；`git log` |

## 每一节能用的数（11-25 收尾时，Claude 整理）

每一行都能在"出处"那份记录里找到。写进报告之前照下面"写之前自查"过一遍；第 3、4 节的几个数还要先过[核对表](../experiments/CLAIMS_CHECK.md)。

"判的是谁"分三种：**程序**（仓库里的代码自己跑出来的）、**对话里的 AI**（Claude 在对话里另开的、没看过答案的子代理，各跑一次，要联网）、**人**。

| 节 | 说的是什么 | 数 | 判的是谁 | 是哪种数据 | 出处 |
| --- | --- | --- | --- | --- | --- |
| 3 | 正面机位录了多少 | 16 次真实开门，都记了真值 | 人记真值 | 实测 | [E01](../experiments/E01_front_20261107.md) |
| 3 | 靠冰箱灯亮判断开门 | 2 次都失败（2/2） | 程序，Mac | 实测，这台相机 | E01 |
| 3 | 什么都没拿的空开门，也被切出了"动作" | 3/3 | 程序，Mac | 实测 | E01；核对表第 11 行 |
| 3 | 手记的真值里，事后要修正的 | 大约 3/13 | 人 | 实测 | E01 |
| 3 | 家里进出的东西，名字能对上检测模型类别的 | 2/27 项 | 程序（yolo11n，按名字匹配） | 实测；怎么读先看核对表第 1、2 行 | E01；核对表 |
| 4 | 桌面录像上改计数规则 | 11 次真实进出：多计 12 → 0，漏计 5 → 2 | 程序，Mac（YOLO11s + ByteTrack） | 开发集：规则是在这批录像上调的 | [E02](../experiments/E02_light_jitter_20261108.md)；核对表第 3 行 |
| 5 | 位置 D，开门检测 | 10 次开门醒了 10 次，没有多醒 | 程序：板子的规则放在 Mac 的录像上重放 | 一段录像 | E03"结果" |
| 5 | 位置 D，数过线：有物品的 8 个动作数对几个 | 0–1/8。那 1 次是碰巧，换一台电脑重跑是 0/8。门格的 3 个，这条线本来就量不到 | 程序，Mac 路线 | 一段录像、10 个动作，开发数据 | E03"结果""换一台电脑重跑" |
| 5 | 同一段录像，改看手里东西的前后状态 | 两个较大的模型都是 8/8（门格 3/3）；最小的模型一次看完 5/8，每个动作单独问 6/8 | 对话里的 AI | 同一段录像，开发数据 | E03"换一种判法"第 1、4 项 |
| 5 | 同上，最小的模型改过问法以后 | 8/8，**不算数**：问法是照着这段录像上的错改的 | 对话里的 AI | 看了答案再改的 | E03"换一种判法"第 4 项 |
| 5 | 评判没见过的录像：一次只拿或只放一样，冰箱里那台相机 | 3/3；另 1 次真值定不了，不算 | 对话里的 AI，最小的模型 | 判法在看之前写下；真值是 Claude 一个人看画面定的 | E03"11-23""11-24" |
| 5 | 评判没见过的录像："拿出来又放回去" | 冰箱里那台相机 0/1，手机 0/3，两路一起 0/1 | 同上 | 同上 | E03"11-23" |
| 5 | 冰箱外面两台相机的 3 个动作 | 单看一路 2/3，两路一起 3/3 | 同上 | 同上；3 个动作说明不了多少 | E03"11-22 下午" |
| 5 | 认出是哪一样（不给参考图），8 个动作里名字对 | 最大的模型 7/8，中等的 3/8，最小的 4/8 | 对话里的 AI | 同一段录像，开发数据 | E03"换一种判法"第 2 项 |
| 5 | 只登记一样东西，给参考图再认 | 中等的模型：是它的 3/3，不是它的 4/4。最小的模型每段单独问：2/3，4/4 | 对话里的 AI | 同上；只登记了 1 样 | 同上 |
| 5 | 每次开门大概花多少 | 最小的模型约 0.0014 美元，每月约 1.7 美元；中等的约 0.029 美元，每月约 35 美元 | — | **估算，不是账单**；"每天开 40 次门"是假设的；程序一次真的请求都没发过 | E03"换一种判法"第 3 项 |
| 6 | 判断程序 | 不联网的自检 33 项通过；真的请求发过 0 次 | 程序 | 自检查的是"有没有照规则办"，不是"判得准不准" | [`fridge_vision/README.md`](../../fridge_vision/README.md) |
| 6 | 事先写定、新录像、只打一次分的测试 | 0 次 | — | 11-22 写定，一直没有做成 | E03"11-25：收尾" |

表里的"E03"都指 [E03 记录](../experiments/E03_position_20261112.md)，引号里是它的小节名。

## 写之前自查

- 报告里每个数字都能在 `docs/experiments/` 里找到出处，你能说出它是怎么算的。
- 每个比例都写成 k/n（分子 / 分母），样本少时再加区间；不要只写百分比。
- 每个数字标明来自哪条识别路线：Mac 上的 YOLO11s、板子代码在 Mac 上的代理、还是板子上实际运行的 NPU。
- 每个数字标明是"调规则用的录像"上的还是"冻结规则以后新录的"录像上的。
- [数字口径核对表](../experiments/CLAIMS_CHECK.md) 里每一行都复核过，原文改好了。
- 引用的论文、专利、产品资料，作者自己打开读过；AI 给的链接和摘要只当线索。
- 每张图都标了来自哪次会话、哪个实验。
- 第 8 节如实写分工：谁做了什么、AI 写了哪些代码和文档、成员怎么确认自己理解了。
- 每个数标明判的是谁：程序、对话里的 AI，还是人。11-22 以后的数大多是对话里的 AI 判的，不能写成"系统的准确率"。
- "方案定了"不等于"做出来了"：写 11-24 定的那套做法时，分清哪几步做了、哪几步只是定了。

## 相关工作线索（只是线索）

下面是 Claude 11-13 查到的资料，链接是查的时候打开过的。**引用前必须自己打开读一遍**，确认内容和这里的一句话描述一致。
有两处要特别核对：两次查资料对 CN113743530A 的描述不一样；三星关于门格的那条脚注只有一次看到了全文。
11-23 又查了一轮（见下面"拿出来又放回去"一节），这两处各又读了一次：CN113743530A 这次读到的和下表那一行一致；三星的脚注在另一个页面上读到了。另外，Samsung KR20250116217A 那一行里"副相机覆盖门格"这半句，11-23 重读时没有在读到的原文里找到（读到的是"每个储藏室里另有副相机"），引用前要再核对。

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

### "拿出来又放回去"别人怎么处理（11-23 查）

起因：11-23 用现有录像判的那一批里，"拿出来又放回去"判不了，换问法也没有解决（[E03 记录](../experiments/E03_position_20261112.md)的"11-23"一节）。项目发起人让查别人是怎么做的。

怎么查的：Claude 用中英文各几组词搜（动态视觉柜、静态视觉、重力感应、放回、人工复核；Amazon 的专利和 Just Walk Out；三星冰箱；冰箱库存的专利和论文；用大模型看图判拿放），再让只会读网页的子任务把最相关的页面打开，按事先列好的问题回答。最后一列写明每一条读到了哪一步。和上面两张表一样只是线索，**引用前必须自己打开读一遍**。

| 类别 | 资料 | 和"拿出又放回"有关的内容 | 核对到哪 |
| --- | --- | --- | --- |
| 先例：专利 | Amazon US 10,268,983 B2，Detecting item interaction and movement（2013-06-26 申请，2019-04-23 授权）<https://patents.google.com/patent/US10268983> | 手每伸进货架一次，比较伸进去之前和出来之后手的图像：出来时手里多了东西算拿，进去时有、出来时没有算放。放回时，从这位顾客已经拿的清单里找是哪一件，再把它从清单里去掉。相机之外可以加秤或压力传感器来发现东西被加上或拿走。把握不够时让顾客自己确认，不确认就通知店员 | 子任务分三段读了专利全文，这几条都读到了原文（图 5、图 6、图 7 的说明和权利要求 1） |
| 先例：报道 | VentureBeat 采访 Just Walk Out 负责人（2024-07-31）<https://venturebeat.com/ai/inside-amazons-new-just-walk-out-ai-transformers-meets-edge-computing> | 旧系统是一串模型挨个问：碰没碰这个位置、是不是这件、拿了几件、有没有放回去。用天花板上的相机，加每层货架前后的秤。新系统改成一个模型一起看；相机被挡住时用秤等别的数据。没有准确率数字 | 子任务读了全文 |
| 教训：报道 | The Batch（2024-05-01）转述 The Information <https://www.deeplearning.ai/the-batch/amazon-scales-back-its-ai-powered-just-walk-out-checkout-service>；亚马逊自己的说明（2024-04-17）<https://www.aboutamazon.com/news/retail/amazon-just-walk-out-dash-cart-grocery-shopping-checkout-stores> | 报道：2022 年年中每 1000 单约 700 单要人工复核，内部目标是 20 到 50 单；一千多名远程员工给视频做标注、复核没判出来的。亚马逊：说它靠人远程看不属实，员工做的是标注；需要人工复核的比例后来下降了，没有给数 | 子任务读了这两页全文。700 这个数只有 The Information 一个来源，亚马逊没有确认 |
| 先例：专利 | CN113743530A（广东培羽科技，2021-09-16 申请）<https://patents.google.com/patent/CN113743530A/zh> | 整个柜子两个相机，拍货物和柜门之间的那一段。商品离货物区越来越远算拿出，越来越近算放回。数量用两种办法各算一遍，对不上就报警转人工；另外用秤核对柜里总重的变化。背景部分说：静态比前后的柜子每层要 1 到 2 个相机，东西不能叠放 | 子任务读了网页 |
| 先例：专利 | US 12,392,548 B2（Springhouse Technologies，2023-09-29 优先权）<https://patents.google.com/patent/US12392548> | 冰箱：相机装在箱体或门上，对着冷藏室的门口，门一开就开始。每个东西逐帧追踪（OCSORT），几台相机的结果合并，比较开头三帧和最后三帧，定它是进去、出来还是在里面挪动。没有写拿出又放回怎么办，没有准确率 | 子任务读了前三分之一的原文，后面是工具给的摘要 |
| 先例：论文 | FAIM（Falcão、Ruiz、Pan、Noh、Zhang，Frontiers in Built Environment，2020）<https://www.frontiersin.org/articles/10.3389/fbuil.2020.568372/full> | 货架上的重量一变就算一次动作，相机只负责认手里是什么。作者认为重量比视觉更稳、更便宜。85 件商品（33 种）上，重量加视觉最高 92.6% | 子任务读了前三分之一的原文（含摘要里的数）。"拿还是放看重量是多了还是少了"这一句只在工具摘要里 |
| 先例：论文 | Grab（Liu、Jiang、Kim、Govindan，2020）<https://arxiv.org/abs/2001.01033> | 相机、货架上的秤、RFID 三样一起用：相机看谁的手靠近了哪层货架，重量变化按时间对上去。准确率和召回率都在九成以上 | 子任务读了摘要和引言；细节来自工具摘要 |
| 先例：行业 | 《无人智能货柜技术方案大盘点，视觉图像识别成主流？》（人人都是产品经理，2020-10-19）<https://www.woshipm.com/it/4223630.html> | 四种做法：RFID、称重、静态比前后、动态视觉（柜子顶上或两侧 1 到 4 个相机，录下开门取货的过程）。称重怕放回到别的位置，静态怕遮挡和叠放。没有准确率数字 | 子任务读了全文 |
| 先例：产品 | 三星 AI Vision Inside 的脚注（2025-04），见 Gizmodo 上三星的推广文（2026-03-23）<https://gizmodo.com/samsung-bespoke-ai-refrigerator-wants-to-take-the-stress-out-of-the-kitchen-2000735929>；Engadget 的试用（2026-05-10）<https://www.engadget.com/2167892/samsungs-bespoke-update-is-big-step-towards-a-useful-ai-for-your-fridge> | 脚注：门格和冷冻室里的东西不识别、不列出；认不出的记成"未知"；结果可能不对，用户可能要自己核对修改。2026 年的更新把一部分识别交给了 Google 的 Gemini，要联网。Engadget 的记者见过它把手指上的创可贴认成蔬菜，当时是在往回放东西 | 子任务读了这两页。三星新闻稿的原文三次都没打开（超时或 404） |
| 先例：个人项目 | CSDN 上一篇无人零售视觉项目的文章（2026-03-26）<https://gitcode.csdn.net/69c4929a54b52172bc64649e.html> | 深度相机看手，RGB 认商品。不单看商品框消失没有，还看手有没有碰到、碰了多久、商品之前是不是稳定在那里、短时间内有没有再出现。作者自己写的待办里有"建评测集量准确率" | 子任务读了全文；没有公开代码 |
| 没打开 | 虎嗅《智能零售柜，背后藏着9分钱一次的打工人？》（2024-07-23）<https://www.huxiu.com/article/3278432.html> | 搜索结果的摘要说：一些智能零售柜是后台的人看视频、手工录入价格来结算 | **原文两次都没打开，只看到搜索摘要，不能引用** |

另外没打开的：AWS 讲 Just Walk Out 新模型的一篇技术博客（只取到了导航栏）、三星的三篇新闻稿（超时或 404）。读到了但没有用上的：密歇根大学 2025 年的一篇无人零售综述（<https://arxiv.org/abs/2503.07997>，没有专门讲放回）、一家标注公司的博客（<https://www.basic.ai/blog-post/computer-vision-for-smart-vending-machines-how-it-works-models-data-and-annotations>，说商用柜子常把动态和静态两种合起来用，是厂商说法）。

Claude 读下来的归纳（不是哪一份资料的原话）：

- 别人是把"拿出又放回"当成一次拿加一次放，各自判，最后相加。但他们都在门口那一个面上连续地看：视频、逐帧追踪、至少两台相机。没有查到谁是靠几张隔开的图来判的。
- 多数做法不只靠相机，还有秤。秤上"拿出又放回"自己就抵消了。
- 每一份讲到把握不够的资料，都留了交给人的路：让顾客确认、转人工、派店员。
- 没有查到任何一家公布过"拿出又放回"判对了多少次；也没有搜到用大模型看隔开的图来判拿放的公开做法和数字。这是"没搜到"，不等于"不存在"。

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
