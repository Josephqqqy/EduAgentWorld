# 构建教育Agent环境

> 按照论文《AgentWorld》目前这个项目构造的环境是不是和现实中教育需求偏差太大，比如现实中，面向老师，可能的需求是：搜索2026年上海高考数学解析几何题目及讲解，面向学生，可能的需求是：上传某张数学题目图片请求解答。在这种场景下，该如何构建环境(主题？工具集？数据库？)
>
> User context
>
> Attachments:
> - 环境主题与任务合成方向.md: `./AgentWorld/edu-envs/环境主题与任务合成方向.md`

<details><summary>5 previous messages</summary>

> 我先阅读项目文档、环境实现和仓库约束，再结合 AgentWorld 的构造方式评估偏差，并给出可落地的环境设计。
>
> 当前沙箱初始化被系统权限拦住了；我会用只读授权重试这些仓库检查。
>
> 仓库根目录已确认。接下来我缩小读取范围，重点看主题文档、数学辅导 schema 和已有工具定义。
>
> 核心设计我已看清：现环境强调“可判定的教学过程状态机”，并非真实入口层。现在补查 AgentWorld 的任务合成原则和现有工具契约，厘清哪些该保留、哪些应新增。
>
> 结论已经比较明确：偏差主要不在“数学辅导”主题，而在任务入口、信息检索与多模态链路被抽掉了。我再定位几处关键代码行，随后给你一套兼顾现实性与可验证性的重构方案。
> </details>

结论：**有一定偏差，但不是方向错了，而是目前只覆盖了真实教育产品的“中后段教学决策”，缺少用户真正会触发的“前段入口能力”**。

当前 `math_tutoring` 更像一个“结构化作答诊断与提示控制器”，适合研究 Agent 的工具调用、状态迁移和教学约束；但它还不像老师或学生会直接使用的教育助手。

## 偏差在哪里

现有环境的优点很明确：

- 有完整的“作答→诊断→提示→对话→合规审查”状态链。
- 工具结果和数据库终态可验证，适合 AgentWorld 的强化学习与自动评测。
- 不把“学生是否理解”伪造成数据库事实，这个建模判断是合理的，见 [schema.sql](./AgentWorld/edu-envs/envs/math_tutoring/schema.sql:9)。
- 单环境工具图和确定性拒绝分支，也符合目前项目的任务合成方法，见 [环境主题与任务合成方向.md](./AgentWorld/edu-envs/环境主题与任务合成方向.md:290)。

但现实需求缺失在三个地方：

1. **没有开放世界信息检索**

   当前 `search_problems` 只是查询 8 道预置题目的 SQLite 表，而且只能按 `topic/grade/source` 精确过滤，见 [tools_impl.py](./AgentWorld/edu-envs/envs/math_tutoring/tools_impl.py:45)。它无法完成“搜索 2026 年上海高考数学解析几何真题及权威讲解”。

2. **多模态入口是名义上的**

   图片仅登记 URI 和哈希，工具不读取图片，见 [schema.sql](./AgentWorld/edu-envs/envs/math_tutoring/schema.sql:102)。这可以测试“Agent 自己看图后的记录流程”，但不能测试上传失败、OCR、公式识别、题目区域裁剪、多题拆分、低置信度复核等真实链路。

3. **假定系统已经知道题目和标准解**

   `register_attempt_artifact` 必须传入已有 `problem_id`，见 [tools_impl.py](./AgentWorld/edu-envs/envs/math_tutoring/tools_impl.py:130)。现实中学生上传的通常是一道未知题目，系统首先需要识题、查重或创建临时题目，然后才能解答。

## 建议的主题设计

不建议把所有需求都继续塞进现在的 `math_tutoring`。更合适的是拆成两个面向真实工作流的环境。

### 1. `teacher_resource_research`

主题：**教师备课与教学资源检索**

代表任务：

> 搜索 2026 年上海高考数学解析几何题，核验年份、地区和试卷版本，整理题目、答案、两种讲解方法，并附来源。

核心能力：

- 自然语言检索条件解析
- 多来源搜索与筛选
- 来源可信度判断
- 同题去重和版本识别
- 原题、答案、解析之间的关联
- 引用与版权状态检查
- 生成备课资料包

这个环境训练的是“检索—核验—综合—引用”，不是学生误区诊断。

### 2. `student_math_help`

主题：**学生多模态数学求助**

代表任务：

> 学生上传一张题目图片，请求解答；图片中有两道题且第二题部分模糊。

核心能力：

- 接收图片
- 检测题目区域并拆题
- OCR/公式识别
- 低置信度时请求确认
- 查找相同题或相似题
- 生成解法并校验答案
- 根据用户身份、场景提供提示式或完整讲解
- 保存本次求助和后续追问

现有 `math_tutoring` 可以作为这个环境的后半段，而不是废弃。

## 工具集设计

### 教师资源检索工具

建议约 15 个工具：

- `parse_resource_request`
- `search_resource_index`
- `filter_search_results`
- `get_source_document`
- `extract_problem_candidates`
- `get_problem_version`
- `compare_problem_duplicates`
- `verify_exam_metadata`
- `get_official_answer`
- `get_solution_explanations`
- `check_source_credibility`
- `check_copyright_policy`
- `save_resource_collection`
- `export_lesson_material`
- `read_audit_log`

关键依赖链：

```text
parse request
  → search sources
  → inspect documents
  → extract candidate problems
  → verify year/region/paper
  → associate answer and explanations
  → save/export resource package
```

不要直接提供一个 `search_2026_shanghai_exam()`，否则只是把答案包装成 API，测不到 Agent 的检索和核验能力。

### 学生图片求解工具

建议约 18 个工具：

- `upload_artifact`
- `get_artifact_metadata`
- `detect_problem_regions`
- `crop_problem_region`
- `recognize_math_content`
- `get_recognition_result`
- `correct_recognition`
- `split_problem_statement`
- `search_matching_problems`
- `create_transient_problem`
- `classify_problem`
- `retrieve_relevant_knowledge`
- `register_solution_steps`
- `verify_solution`
- `open_help_session`
- `release_hint`
- `append_student_turn`
- `close_help_session`

关键依赖链：

```text
upload
  → detect/crop
  → OCR + formula recognition
  → confidence check
  → student confirmation if needed
  → identify or create problem
  → solve
  → symbolic/numeric verification
  → explanation or progressive hints
```

这里应保留现有环境“工具负责可验证状态，Agent 负责理解和表述”的原则，但需要把 OCR 输出、置信度、人工修正记录作为可验证状态，而不是仅保存一个图片 URI。

## 数据库设计

建议按四类数据组织，而不是只有“题目—标准解—作答”。

### 资源与来源

```text
sources
- id
- publisher
- domain
- source_type
- authority_level
- copyright_policy

documents
- id
- source_id
- title
- published_date
- fetched_at
- snapshot_uri
- content_hash

exam_papers
- id
- year
- region
- exam_type
- paper_variant
- subject
- official_status
- document_id
```

### 题目知识库

```text
problems
- id
- canonical_statement
- subject
- topic
- grade_band
- difficulty
- provenance_status

problem_occurrences
- problem_id
- document_id
- question_no
- original_text
- page_no

solutions
- id
- problem_id
- solution_type
- final_answer
- source_id
- verified_status

solution_steps
- solution_id
- step_no
- text
- expression
- justification
```

`problem_occurrences` 很重要：同一道题可能出现在官方卷、培训机构解析、网页转载中，不能把它们误认为三道不同题。

### 多模态作答

```text
artifacts
- id
- user_id
- media_type
- uri
- content_hash
- width
- height
- upload_status

artifact_regions
- id
- artifact_id
- bbox
- region_type
- detection_confidence

recognition_runs
- id
- region_id
- engine
- raw_text
- latex
- confidence
- status

recognition_corrections
- id
- recognition_id
- original_value
- corrected_value
- corrected_by
```

### 求助与教学过程

保留现有：

- `attempt_steps`
- `diagnoses`
- `misconceptions`
- `tutoring_sessions`
- `dialog_turns`
- `hint_ladders`
- `audit_log`

但让 `problem_id` 可以来自：

- 题库已有题；
- 搜索检索到的题；
- 图片识别后创建的临时题。

## 如何兼顾现实性与 AgentWorld 的可复现性

不能在训练和评测时直接依赖实时互联网。否则搜索结果每天变化，任务终态不可稳定断言。

推荐采用“**离线 Web 快照环境**”：

- 预先抓取官方考试院、学校、出版社、教育网站和解析页面。
- 保存 HTML/PDF/图片快照、URL、抓取时间和哈希。
- 用 BM25 或本地向量索引模拟搜索引擎。
- 搜索工具返回带噪声的候选结果，而不是直接返回标准答案。
- 数据库保存权威来源标签，但不直接告诉 Agent 哪个结果正确。
- 评测时断言 Agent 是否选对试卷、题号、来源和解析，而不是要求生成文本逐字一致。

同理，多模态环境应使用固定图片集及固定 OCR 候选输出。可以设置：

- 清晰印刷题；
- 手写题；
- 一张图多道题；
- 裁剪缺失；
- OCR 把 `1` 识别成 `l`；
- 根号范围识别错误；
- 图形与文字联合题；
- 图片内容与用户描述冲突。

这样既真实，又能复现。

## 推荐的环境边界

我建议最终形成三层：

```text
teacher_resource_research
  教师找题、核验来源、整理讲解

student_math_help
  图片接入、识题、解题、答案验证

math_tutoring
  对已有作答做误区诊断和渐进式辅导
```

三者可以共享题目、来源和误区编码规范，但按照当前 AgentWorld 的约束，**单条训练任务仍只运行在一个环境内**。需要端到端任务时，可把必要的入口和辅导工具共同放入 `student_math_help`，不要在一条轨迹里跨三个独立数据库。

最值得优先实现的是 `student_math_help`：它与现有 `math_tutoring` 复用最多，只需先补齐“上传→区域检测→识别→确认→创建题目”这一段，就能把当前偏研究型的状态机变成更接近真实学生需求的完整环境。

> 在《AgentWorld》论文的附录里，是如何构建环境的，拿arxiv_local 、Emails、Hotels举例，数据库是如何构建的，工具集是如何构建的，

> 在《AgentWorld》论文的附录里，是如何构建环境的，拿arxiv_local 、Emails、Hotels举例，数据库是如何构建的，工具集是如何构建的
>
> User context
>
> Attachments:
> - AgentWorld.pdf: `./AgentWorld/AgentWorld.pdf`

<details><summary>2 previous messages</summary>

> 我会直接检索论文附录中的环境构建章节，提取 `arxiv_local`、`Emails`、`Hotels` 的数据库、工具和任务生成细节，再按统一框架对比总结。
>
> 环境里没有 `pdftotext`，我改用已安装的 Python PDF 解析库检查本地论文，不访问网络。
> </details>

论文附录的核心做法可以概括为：

> 每个环境不是一个简单 API 集合，而是一个二元组
> `环境 = (数据库 D, 工具集 F)`。
> 数据库承载环境状态，工具是对数据库执行读写的可调用函数。

论文正文中明确写道，数据库 `D` 是环境状态的主要存储载体，工具集 `F` 通过读写数据库产生状态变化。附录 B 则用环境卡片展示了具体目录、文件和工具接口。

## 一、总体构建流程

### 1. 先确定环境主题

主题来源主要有三类：

- 真实 MCP/工具服务器及其说明；
- 开源数据集、工具文档；
- 行业 PRD 和产品需求文档。

这些来源合并形成主题集合 `M`，例如本地论文库、邮箱系统、酒店预订系统。

### 2. 用深度研究 Agent 挖掘数据库

论文不是让 LLM 随便生成几条数据，而是让研究 Agent 使用：

- 搜索工具；
- 浏览器；
- 代码编译器；
- 操作系统工具。

它根据主题搜索真实世界资料，清洗、结构化并持久化，得到：

```text
D(m) = G(m; πθ, T)
```

其中：

- `m` 是环境主题；
- `G` 是自动化研究与数据构造流程；
- `πθ` 是执行研究的模型；
- `T` 是搜索、浏览、编译和 OS 工具；
- `D(m)` 是该主题的环境数据库。

由于一次挖掘得到的数据可能规模小、结构简单，论文还引入数据库复杂化过程：

```text
D(n+1)(m) = ϕ(D(n)(m), ...)
```

也就是让 Agent 多轮扩充数据规模、字段、关系和边界情况。

所以论文里的数据库构建不是：

```text
让 LLM 直接写一个 database.json
```

而是：

```text
主题
→ 网络研究
→ 数据抽取
→ 结构化存储
→ 多轮复杂化
→ 固定到离线环境
```

### 3. 根据数据库生成工具

给定主题和最终数据库，代码生成 Agent 自动生成工具及其测试：

```text
{(f̂, Ĉf)} = ψ(m, D(N)(m); πθ, T̂)
```

每个候选工具都包括：

- 工具函数；
- 参数定义；
- 返回结构；
- 读写数据库逻辑；
- 单元测试集合。

随后逐个验证：

1. Python 代码能否编译；
2. 工具测试准确率是否大于 0.5；
3. 环境中是否至少存在一个有效工具和一个有效测试。

通过筛选后，得到正式工具集：

```text
F(m)
```

最终环境就是：

```text
E = {(D(N)(m), F(m))}
```

## 二、`arxiv_local`：本地 arXiv 论文环境

附录 B.1 中的 `arxiv_local` 是一个完全离线的本地论文库。

### 数据库构造

它没有使用 SQL，而是采用文件型数据库：

```text
./
├── manifest.json
└── papers/
    ├── 1706.03762.md
    ├── 1810.04805.md
    ├── 1512.03385.md
    ├── 1406.2661.md
    ├── 1806.07366.md
    ├── 2005.14165.md
    ├── 2102.12092.md
    ├── 2103.00020.md
    ├── 2003.08934.md
    └── 1910.11333.md
```

`manifest.json` 是快速索引，大致保存：

```json
{
  "papers/1706.03762.md": "Attention Is All You Need",
  "papers/1810.04805.md": "BERT"
}
```

每篇论文是一个 Markdown metadata card，包含：

```text
# Title
Authors:
Abstract:
Subjects:
Comments:
DOI:
URL:
Journal reference:
Project page:
```

论文正文内容并不是重点，环境主要围绕论文元数据查询。

### 工具集

附录列出了三个主要工具：

| 工具                       | 作用                                      |
| -------------------------- | ----------------------------------------- |
| `list_local_papers`        | 从 `manifest.json` 返回全部论文 ID 和标题 |
| `get_local_paper_metadata` | 根据论文 ID 读取 Markdown 并解析标准字段  |
| `search_local_papers`      | 对标题进行不区分大小写的子串搜索          |

其设计特点是：

- 工具完全离线；
- 工具直接读本地文件；
- 搜索只针对标题；
- 返回结构稳定；
- 缺文件时明确报错；
- 工具逻辑简单、容易审计和复现。

例如 `get_local_paper_metadata(paper_id)` 的实现大致是：

```python
md_path = os.path.join("papers", f"{paper_id}.md")

if not os.path.isfile(md_path):
    raise FileNotFoundError(...)

with open(md_path, encoding="utf-8") as f:
    lines = f.readlines()

# 逐行解析 Authors、Abstract、Subjects 等字段
return fields
```

这里的重点不是实现复杂搜索，而是训练 Agent 完成：

```text
列出论文
→ 按标题搜索
→ 读取指定论文元数据
```

## 三、`Emails`：文件型邮箱环境

附录 B.2 中的 `Emails` 模拟的是一个离线邮箱系统。

### 数据库构造

目录结构如下：

```text
./
├── emails_export.json
├── folders.json
├── mailbox_stats.json
├── attachments/
│   ├── attachment1.txt
│   └── attachment2.txt
└── enron_spam_data/
    └── enron_spam_data.csv
```

#### 1. 主邮箱数据

`emails_export.json` 是主要数据集，包含约 2,000 封结构化邮件，每条邮件包括：

```json
{
  "email_id": "...",
  "folder": "inbox",
  "from": "...",
  "to": ["..."],
  "cc": [],
  "bcc": [],
  "subject": "...",
  "body": "...",
  "date": "...",
  "spam_ham": "ham",
  "attachments": []
}
```

它负责：

- 邮件列表；
- 邮件详情；
- 关键词搜索；
- 文件夹过滤；
- spam/ham 统计；
- 附件关联。

#### 2. 轻量索引

`folders.json`：

```json
["inbox", "sent", "archive", "spam"]
```

`mailbox_stats.json`：

```json
{
  "total_emails": 2000,
  "folders": {
    "inbox": 800,
    "sent": 500,
    "spam": 200
  }
}
```

这些文件让 Agent 可以先获得全局信息，不必每次扫描完整邮件数据。

#### 3. 大型统计数据

`enron_spam_data.csv` 是约 81.4 万行的 Enron Spam/Ham 数据，字段包括：

```text
Message ID
Subject
Message
Spam/Ham
Date
```

它不是主邮箱状态，而是用来支持：

- 采样；
- 垃圾邮件分布；
- 大规模统计问题。

附录特别说明，工具不应一次性把整个 CSV 读入内存，而应采用采样或流式读取。

#### 4. 附件

`attachments/` 存放邮件元数据中引用的附件文件。工具会先确认该文件名确实属于目标邮件，再读取内容。

### 工具集

| 工具                                  | 作用                                     |
| ------------------------------------- | ---------------------------------------- |
| `list_emails`                         | 分页列出邮件，可按文件夹过滤             |
| `get_email_by_id`                     | 根据 `email_id` 获取单封邮件             |
| `get_folders`                         | 获取文件夹列表                           |
| `get_mailbox_stats`                   | 获取总邮件数和分文件夹统计               |
| `search_emails`                       | 在主题、正文、发件人和收件人中做子串搜索 |
| `get_attachment_content`              | 校验附件归属后读取附件                   |
| `sample_enron_spam`                   | 从 Enron CSV 中采样 spam/ham 数据        |
| `get_email_counts_by_folder_and_spam` | 统计文件夹和 spam/ham 的组合分布         |

例如 `list_emails` 的实现流程是：

```text
读取 emails_export.json
→ 可选 folder 过滤
→ 计算 total
→ 根据 page/page_size 切片
→ 返回分页结果
```

论文提供的示例实现本质上是普通 Python 文件操作，而不是连接真实 IMAP 服务：

```python
with open("emails_export.json", encoding="utf-8") as f:
    emails = json.load(f)

if folder:
    emails = [e for e in emails if e.get("folder") == folder]

start = (page - 1) * page_size
end = start + page_size

return {
    "total": len(emails),
    "page": page,
    "page_size": page_size,
    "emails": emails[start:end]
}
```

附录还特别指出：真实的 `emails` MCP 可能有 `send_email`、`move_email` 等 25 个工具，但当前评测环境只实现本地文件工具集。也就是说，论文区分了：

```text
概念上的生产工具面
≠
实际用于可复现评测的工具面
```

## 四、`Hotels`：酒店搜索与预订环境

附录 B.4 的 `Hotels` 比前两个环境更接近一个带状态写入的业务系统。

### 数据库构造

目录结构如下：

```text
/app/database/
├── bookings.json
├── facilities.json
├── hotel_details.json
├── hotels.json
├── hotels_sample.csv
├── places.json
├── rates.json
└── world_cities.csv
```

#### 1. 地点数据

`places.json` 用来把用户输入的地点标准化为经纬度：

```json
{
  "query": "Hangzhou",
  "name": "Hangzhou",
  "latitude": 30.27,
  "longitude": 120.15,
  "country": "China"
}
```

工具 `find_place` 会先使用它。

#### 2. 酒店搜索索引

`hotels.json` 保存酒店摘要信息：

```json
{
  "hotel_id": 101,
  "name": "...",
  "address": "...",
  "city": "Hangzhou",
  "province": "...",
  "star_rating": 5,
  "lat": 30.2,
  "lng": 120.1,
  "price_per_night": 500,
  "rating": 4.7,
  "facilities": ["FREE_WIFI", "GYM"]
}
```

它服务于分页搜索。

#### 3. 酒店详情和房型

`hotel_details.json` 保存：

```json
{
  "hotel_id": 101,
  "description": "...",
  "rooms": [
    {
      "rate_id": "101-standard",
      "name": "Standard",
      "price": 500,
      "currency": "CNY",
      "amenities": ["FREE_WIFI"],
      "cancellation_policy": "..."
    }
  ]
}
```

#### 4. 价格数据

`rates.json` 将酒店 ID 映射到多个价格方案：

```text
hotel_id → Standard / Deluxe / Suite rate rows
```

#### 5. 设施字典

`facilities.json` 是规范化设施词典：

```json
{
  "id": "FREE_WIFI",
  "name": "Free WiFi",
  "description": "..."
}
```

酒店搜索结果中只保存设施 ID，通过该文件解释具体设施。

#### 6. 大型辅助数据

- `hotels_sample.csv`：宽表、双语名称、评分、嵌套 JSON、媒体 URL；
- `world_cities.csv`：全球城市、经纬度、人口；
- 这些数据用于更复杂的连接、统计和导出任务。

#### 7. 预订状态

`bookings.json` 初始为空：

```json
[]
```

每次成功调用 `book_hotel` 后追加：

```json
{
  "booking_id": "...",
  "hotel_id": 101,
  "rate_id": "101-standard",
  "user_id": "...",
  "payment_link": "...",
  "status": "pending"
}
```

因此，Hotels 是一个“静态库存 + 动态预订账本”的环境：

```text
places/hotels/details/rates
        ↓
   查询与选择
        ↓
   bookings.json 写入
```

### 工具集

附录使用六个工具：

| 工具                | 作用                               |
| ------------------- | ---------------------------------- |
| `find_place`        | 地点名称转标准地点和经纬度         |
| `search_hotels`     | 根据坐标、日期、人数和名称搜索酒店 |
| `load_more_hotels`  | 使用搜索 session 继续分页          |
| `get_hotel_details` | 查询酒店详情、房型和价格           |
| `book_hotel`        | 根据酒店和 `rate_id` 创建预订      |
| `get_facilities`    | 获取设施字典                       |

典型工具依赖链为：

```text
find_place
  → search_hotels
  → load_more_hotels（可选）
  → get_hotel_details
  → book_hotel
```

其中 `book_hotel` 是唯一会持久化修改状态的工具。

这点很重要：论文不是把每个工具都做成写操作，而是根据真实业务语义区分：

- 查询工具：读取静态 JSON；
- 会话工具：保存搜索上下文或 session；
- 写工具：追加订单记录。

## 五、三个环境的共同设计模式

| 维度       | arxiv_local      | Emails                 | Hotels                          |
| ---------- | ---------------- | ---------------------- | ------------------------------- |
| 数据载体   | Markdown + JSON  | JSON + CSV + 附件      | 多个 JSON + CSV                 |
| 是否离线   | 是               | 是                     | 是                              |
| 主要状态   | 论文元数据       | 邮箱内容与统计         | 酒店库存与预订                  |
| 主要操作   | 列表、搜索、详情 | 分页、搜索、附件、统计 | 地理搜索、详情、预订            |
| 写操作     | 基本无           | 当前版本基本只读       | `book_hotel` 写 `bookings.json` |
| 关系复杂度 | 低               | 中                     | 中高                            |
| 典型链路   | 搜索→详情        | 文件夹→邮件→附件       | 地点→酒店→房型→预订             |

共同点是：

1. 数据来自真实世界数据或真实格式；
2. 运行时固定为离线快照；
3. 文件格式尽量贴近现实系统；
4. 工具函数只暴露有限、稳定的业务接口；
5. 每个工具都可以被单独测试；
6. 复杂任务通过工具之间的数据依赖形成。

## 六、工具集不是简单“把数据库 CRUD 暴露出来”

论文的关键不是：

```text
每张表生成增删改查接口
```

而是：

```text
根据真实业务工作流生成工具
```

例如 Hotels 中没有直接暴露：

```text
read_hotels_json
write_bookings_json
```

而是暴露：

```text
find_place
search_hotels
get_hotel_details
book_hotel
```

这让 Agent 必须理解业务流程。

随后论文为每个环境构造工具依赖图：

- 强依赖，权重 3：后一个工具必须使用前一个工具的输出；
- 弱依赖，权重 2：可以使用前一个输出，也可以从数据库或常量得到；
- 独立边，权重 1：没有参数依赖，但用于保证图连通。

例如 Hotels：

```text
find_place → search_hotels
search_hotels → get_hotel_details
get_hotel_details → book_hotel
```

然后在图上随机游走生成合法工具调用序列，执行序列，记录真实返回值，再生成任务描述、标准答案和评测 rubric。

## 七、对你们教育环境设计的启示

你们当前的 `math_tutoring` 采用 SQL、逻辑时钟、审计表和严格状态机，这比论文附录中的三个环境更强调过程约束，但两者理念是一致的：

```text
固定数据库状态
+ 业务化工具
+ 工具依赖
+ 可执行验证
```

如果要更贴近论文附录，建议教育环境也采用类似分层：

### 教师检索环境

```text
sources.json
documents.json
exam_papers.json
problems.json
solutions.json
```

工具：

```text
search_exam_papers
get_paper
search_problems
get_problem
get_solution
verify_source
save_resource
```

### 学生图片求解环境

```text
artifacts.json
recognized_regions.json
recognition_runs.json
problems.json
solutions.json
sessions.json
```

工具：

```text
upload_image
detect_regions
recognize_math
confirm_recognition
search_matching_problem
get_solution
verify_solution
open_help_session
release_hint
```

也就是说，可以保留你们现有的“诊断和辅导状态机”，但在前面增加论文附录式的：

```text
离线文件型题库
+ 图片/OCR 产物
+ 搜索索引
+ 业务化工具接口
```

这样环境就既具备 AgentWorld 所要求的可复现性，又更接近真实教师和学生的使用场景。

> 那我现在想按照论文这样重新去构建环境，总体分为学生端和教师端，先构思学生端，可以有哪些主题（环境）

学生端建议不要只做一个“数学辅导环境”，而是按学生真实任务拆成多个相对独立的环境。每个环境都应有自己的：

```text
主题 m
+ 离线数据库 D
+ 工具集 F
+ 工具依赖图
+ 可验证任务
```

建议先规划以下 8 个主题。

## 1. `student_math_solver`

学生多模态数学解题环境。

典型需求：

> 上传一道数学题图片，请求解答；图片中有手写公式，部分内容模糊。

数据库可以包括：

- 题目图片；
- OCR 和公式识别候选结果；
- 题目文本；
- 题库与相似题；
- 标准解和分步解；
- 计算验证结果；
- 学生求助会话。

工具链：

```text
upload_image
→ detect_problem_regions
→ recognize_math_content
→ confirm_or_correct_recognition
→ search_matching_problem
→ get_solution
→ verify_solution
→ explain_solution
```

这是最值得优先实现的学生端主题，因为它最贴近真实产品入口。

---

## 2. `student_homework_tutor`

作业辅导与过程性提示环境。

典型需求：

> 我做到第二步不会了，请不要直接告诉我答案，给我提示。

数据库可以包括：

- 题目；
- 学生作答步骤；
- 标准解；
- 错误类型；
- 误区；
- 提示阶梯；
- 对话记录；
- 历史尝试。

工具链：

```text
get_problem
→ register_attempt
→ analyze_steps
→ identify_misconception
→ create_hint_plan
→ release_hint
→ record_student_response
→ evaluate_progress
```

你们现有的 `math_tutoring` 基本属于这个主题，可以将其作为独立环境保留。

与 `student_math_solver` 的区别是：

- `student_math_solver` 重点是“识题和解题”；
- `student_homework_tutor` 重点是“诊断、提示和教学过程”。

---

## 3. `student_exam_prep`

学生备考与错题复习环境。

典型需求：

> 帮我复习上海高考解析几何，找出我最近最薄弱的知识点，并安排练习。

数据库可以包括：

- 历年试卷；
- 题目及知识点；
- 难度；
- 题型标签；
- 学生历史作答；
- 错题记录；
- 掌握度或阶段性估计；
- 练习计划。

工具链：

```text
search_exam_papers
→ filter_by_year_topic
→ get_problem_statistics
→ get_student_error_history
→ identify_weak_topics
→ recommend_problems
→ create_practice_plan
→ record_plan_completion
```

这个环境适合测试 Agent 的：

- 多条件检索；
- 个性化推荐；
- 计划生成；
- 历史数据分析。

建议把“掌握度”做成可解释的统计量，例如正确率、最近一次表现、连续错误次数，而不是直接使用一个没有更新规则的神秘分数。

---

## 4. `student_wrong_answer_book`

错题本与知识薄弱点管理环境。

典型需求：

> 把这道错题加入错题本，标记错误原因，并在下周提醒我重做。

数据库可以包括：

- 错题；
- 原始题目来源；
- 学生答案；
- 正确答案；
- 错误原因；
- 知识点；
- 重做次数；
- 复习时间；
- 遗忘曲线或复习计划。

工具链：

```text
add_wrong_problem
→ classify_error
→ link_knowledge_point
→ schedule_review
→ list_due_reviews
→ submit_reattempt
→ update_review_status
```

这个主题比“作答诊断”更偏向长期学习管理，适合生成带时间和历史状态的任务。

---

## 5. `student_question_search`

学习问题搜索与相似题检索环境。

典型需求：

> 我不会做“圆锥曲线中焦点弦”问题，帮我找几道相似例题。

数据库可以包括：

- 题目全文；
- 公式和 LaTeX；
- 知识点；
- 题型；
- 难度；
- 来源；
- 相似题关系；
- 解析；
- 视频或图文资源元数据。

工具链：

```text
parse_query
→ search_problems
→ filter_by_grade_topic
→ find_similar_problems
→ get_problem_solution
→ compare_problem_variants
```

不要只实现关键词搜索，还可以加入：

- 知识点搜索；
- 题型搜索；
- 难度过滤；
- 结构相似搜索；
- “只看有详细解析”的过滤。

但评测时建议使用离线索引，而不是实时互联网。

---

## 6. `student_learning_record`

学生学习记录与进度分析环境。

典型需求：

> 我这周数学学习情况怎么样？哪些章节还没有掌握？

数据库可以包括：

- 学习活动；
- 视频观看记录；
- 练习记录；
- 作答时间；
- 成绩；
- 重做次数；
- 学习时长；
- 章节结构；
- 阶段目标。

工具链：

```text
get_activity_tree
→ get_recent_activity
→ get_topic_progress
→ detect_learning_risk
→ compare_periods
→ update_learning_goal
```

这个主题可以复用你们的 `xapi_lrs` 思路，但需要从通用学习记录转成面向学生的反馈和计划。

---

## 7. `student_coursework_manager`

学生课程、作业和截止日期管理环境。

典型需求：

> 帮我列出本周所有数学作业，按截止时间排序，并告诉我哪些还没完成。

数据库可以包括：

- 课程；
- 作业；
- 截止时间；
- 提交状态；
- 成绩；
- 教师评语；
- 附件；
- 课程公告。

工具链：

```text
list_courses
→ list_assignments
→ filter_due_assignments
→ get_submission_status
→ get_teacher_comments
→ submit_assignment
```

这个环境更接近 Canvas/OneRoster 类型的学生侧使用场景，但权限应限制为：

- 学生只能读取自己的成绩和提交；
- 学生不能修改教师发布状态；
- 补交或撤回操作需要明确权限和状态检查。

---

## 8. `student_study_resource`

学习资料收藏、整理和引用环境。

典型需求：

> 把这篇解析、这张公式总结和这道例题加入“解析几何复习资料夹”。

数据库可以包括：

- 资料；
- 来源；
- 标签；
- 收藏夹；
- 笔记；
- 个人标注；
- 资料之间的关联；
- 版权和可见性状态。

工具链：

```text
search_resources
→ get_resource
→ verify_source
→ save_to_collection
→ add_note
→ tag_resource
→ list_collection
```

这个环境可以训练 Agent 进行资料筛选和长期组织，而不是只回答一次问题。

## 推荐的第一阶段范围

不建议一开始实现全部 8 个。第一阶段可以先做 4 个：

```text
1. student_math_solver
2. student_homework_tutor
3. student_wrong_answer_book
4. student_exam_prep
```

它们覆盖了学生最主要的完整链路：

```text
上传题目
→ 识别题目
→ 获取解答
→ 过程辅导
→ 记录错题
→ 安排复习
→ 分析薄弱点
```

## 主题之间的边界

为了符合论文的单环境任务设定，每个主题应尽量能独立完成任务。例如：

- “上传图片并解题”属于 `student_math_solver`；
- “根据作答步骤逐级提示”属于 `student_homework_tutor`；
- “整理错题并安排复习”属于 `student_wrong_answer_book`；
- “分析历年考试表现并生成练习计划”属于 `student_exam_prep`。

训练数据可以混合这些环境，但单条任务最好不要跨多个数据库。若确实需要端到端学生流程，可以将相关工具合并成一个更大的环境，而不是让任务隐式跨环境传递 ID。

## 我最推荐的主题层级

可以采用三级主题结构：

```text
学生学习助手 student_learning_assistant
├── student_math_solver
├── student_homework_tutor
├── student_exam_prep
├── student_wrong_answer_book
├── student_question_search
├── student_learning_record
├── student_coursework_manager
└── student_study_resource
```

其中第一阶段优先建设：

```text
student_math_solver
student_homework_tutor
student_exam_prep
student_wrong_answer_book
```

这四个主题既能覆盖现实需求，又能分别形成清晰的数据库、工具集、依赖图和自动评测标准。

> 现在不要看我已经有的环境，而是重新构想，根据中国教育体系，设计面向学生的主题(环境)，如何合理分类

如果完全重新设计，不看现有环境，我建议不要先按“数学、语文、英语、物理”分类，而是按照中国学生的真实学习任务和教育流程分类。

原因是：同一种 Agent 能力，例如“上传题目并请求解答”，会同时适用于数学、物理、化学；如果一开始按学科拆分，会产生大量重复环境。更合理的方式是：

```text
一级分类：学生要完成什么教育任务
二级分类：适用学段、学科或考试类型
```

## 一、学生端总体分类

建议学生端分成六大类、十二个主题。

```text
学生教育助手
├── A. 学习内容获取
├── B. 练习与作业
├── C. 考试与升学
├── D. 学习规划与诊断
├── E. 学习资料与知识管理
└── F. 学校事务与成长支持
```

---

# A. 学习内容获取

## A1. `multimodal_question_solving`

多模态题目理解与解答。

典型需求：

- 上传数学、物理、化学题目图片；
- 识别手写公式和图形；
- 处理题干模糊、裁剪不完整、多题混排；
- 请求答案、思路或分步讲解；
- 对答案进行计算或逻辑验证。

这是学生最常见的入口型环境。

数据库可以包括：

- 题目图片；
- OCR 结果；
- LaTeX 公式；
- 图形识别结果；
- 题目文本；
- 标准答案；
- 分步解法；
- 识别置信度；
- 用户修正记录。

它不应限定为数学，后续可以扩展为：

```text
数学题目识别
物理题目识别
化学方程式识别
英语阅读题识别
```

但初期可以共用一套多模态框架。

## A2. `concept_learning`

知识点学习与概念解释。

典型需求：

- “解释一下二次函数的判别式”；
- “初中生能听懂地解释牛顿第二定律”；
- “比较定语从句和宾语从句”；
- “给我一个生活中的例子”。

数据库可以包括：

- 课程标准；
- 教材章节；
- 知识点图谱；
- 前置知识关系；
- 例题；
- 易错点；
- 不同学段的解释版本。

核心不是搜索答案，而是根据：

```text
年级
→ 教材版本
→ 知识点
→ 前置知识
→ 当前理解水平
```

生成适合学生的解释。

---

# B. 练习与作业

## B1. `homework_assistance`

作业理解、提示和提交前检查。

典型需求：

- 读懂老师布置的作业；
- 判断题目要求；
- 给出提示而不是直接答案；
- 检查作业是否漏题；
- 根据要求整理答案格式。

数据库可以包括：

- 作业任务；
- 题目；
- 截止时间；
- 教师要求；
- 学生草稿；
- 提交格式；
- 评分标准。

重点是帮助学生完成任务，而不是替学生完成作业。

## B2. `adaptive_practice`

自适应练习与即时反馈。

典型需求：

> 我刚做错了三道关于函数的题，请给我安排难度合适的练习。

数据库可以包括：

- 题库；
- 难度；
- 知识点；
- 题型；
- 历史正确率；
- 作答时间；
- 错误模式；
- 题目之间的先后依赖。

工具可以根据学生表现选择：

- 巩固题；
- 同类变式题；
- 降低难度的前置题；
- 综合应用题；
- 迁移题。

## B3. `assessment_feedback`

测验、作业和考试后的反馈解释。

典型需求：

- 查看错题；
- 理解为什么扣分；
- 区分知识错误、审题错误、表达错误和粗心；
- 询问“这一步为什么不能这样写”；
- 根据评分标准重新核对答案。

数据库可以包括：

- 学生答卷；
- 评分结果；
- 分步得分；
- 教师评语；
- 评分 rubric；
- 标准答案；
- 错误标签；
- 申诉或复核记录。

这个主题与“做题辅导”不同：它的输入是已经完成的测评结果，重点是反馈解释。

---

# C. 考试与升学

## C1. `exam_preparation`

中考、高考、学业水平考试备考。

典型需求：

- 查询历年真题；
- 分析题型和考点变化；
- 查找某知识点的高频题；
- 根据近期成绩生成复习任务；
- 模拟考试后的薄弱点分析。

数据库可以包括：

- 历年试卷；
- 地区、年份、科目和版本；
- 题目；
- 知识点；
- 难度；
- 标准答案；
- 官方解析；
- 题型统计；
- 学生历史成绩。

中国教育场景中需要特别建模：

```text
考试类型
+ 年份
+ 省市
+ 科目
+ 试卷版本
+ 选科组合
```

例如“2026 年上海高考数学”不能只用 `year=2026` 表示，还应区分考试类型和地区版本。

## C2. `school_and_major_guidance`

升学、志愿和专业选择辅助。

适用：

- 中考选校；
- 高考志愿；
- 专业选择；
- 研究生方向选择；
- 职业教育专业选择。

数据库可以包括：

- 学校；
- 专业；
- 历年录取分数；
- 位次；
- 招生计划；
- 地区限制；
- 选科要求；
- 学费；
- 就业方向；
- 招生章程；
- 风险提示。

工具任务可以包括：

- 根据分数和位次筛选学校；
- 检查专业选科要求；
- 比较院校；
- 识别数据年份和来源；
- 生成“冲、稳、保”方案。

这个环境必须强调数据时效性和来源核验，不能把推荐当成确定性录取预测。

## C3. `exam_integrity_and_safe_tutoring`

考试诚信和安全学习。

典型需求：

- 学生索要考试答案；
- 试图让 Agent 代写作业或考试；
- 请求绕过在线考试限制；
- 要求伪造学习记录；
- 在允许范围内请求知识讲解。

数据库可以包括：

- 考试规则；
- 作业诚信政策；
- 允许和禁止的帮助类型；
- 对话风险标签；
- 学生请求历史；
- 合规回复模板。

该环境的任务不是单纯拒绝，而是：

```text
识别风险
→ 判断是否允许
→ 给出合规替代帮助
→ 必要时记录事件
```

---

# D. 学习规划与诊断

## D1. `learning_diagnosis`

学生学习状态诊断。

典型需求：

> 我最近数学成绩下降，主要问题在哪？

数据库可以包括：

- 作答记录；
- 测验成绩；
- 知识点表现；
- 作答时间；
- 重复错误；
- 学习活动；
- 缺交和中断记录。

输出应尽量基于证据，例如：

- 解析几何正确率下降；
- 同类题连续三次错误；
- 计算题耗时明显增加；
- 选择题正确但解答题表达不完整。

不要直接把学生标记为“能力低”，而要保留证据链。

## D2. `personal_study_planning`

个性化学习计划。

典型需求：

- 制定一周复习计划；
- 根据考试日期安排倒计时计划；
- 在多个科目之间分配时间；
- 根据完成情况动态调整；
- 处理临时请假、作业增加等变化。

数据库可以包括：

- 学习目标；
- 考试日期；
- 可用时间；
- 任务优先级；
- 任务依赖；
- 完成记录；
- 计划版本；
- 调整原因。

工具重点是计划管理：

```text
create_plan
→ allocate_tasks
→ record_completion
→ detect_delay
→ replan
```

## D3. `learning_habit_and_risk_support`

学习习惯和风险支持。

典型需求：

- 长期拖延；
- 学习活动突然中断；
- 作业连续缺交；
- 熬夜学习；
- 学习计划频繁失败；
- 请求学习方法建议。

数据库可以包括：

- 学习时段；
- 活动连续性；
- 任务完成率；
- 缺交记录；
- 自我报告；
- 干预记录。

它不应直接进行医学或心理诊断，而应定位为学习支持和风险提醒。遇到明显心理危机时，工具需要转介教师、家长或专业机构。

---

# E. 学习资料与知识管理

## E1. `student_resource_search`

学生学习资料搜索。

典型需求：

- 找某知识点讲义；
- 找某版本教材配套资源；
- 找有详细解析的例题；
- 比较不同来源的讲解；
- 查询资料是否可靠。

数据库可以包括：

- 教材；
- 讲义；
- 题库；
- 视频元数据；
- 来源机构；
- 年级；
- 版本；
- 知识点；
- 版权信息；
- 质量评分。

工具应支持来源核验，而不只是关键词搜索。

## E2. `personal_knowledge_management`

个人笔记、收藏和错题知识库。

典型需求：

- 收藏一道题；
- 给资料加标签；
- 把错题归入“圆锥曲线”；
- 为笔记建立链接；
- 根据考试范围生成复习清单。

数据库可以包括：

- 收藏夹；
- 笔记；
- 标签；
- 错题；
- 资料引用；
- 知识点关系；
- 修改历史。

## E3. `language_learning`

英语及其他语言学习。

虽然可以归入通用学习环境，但语言学习的工具和数据库差异很大，适合单独作为主题。

典型需求：

- 作文批改；
- 口语练习；
- 听力材料；
- 生词复习；
- 语法纠错；
- 中英文互译。

数据库可以包括：

- 词汇表；
- 例句；
- 语法规则；
- 作文；
- 语音文件；
- 发音评分；
- 阅读和听力材料；
- 学生遗忘记录。

---

# F. 学校事务与成长支持

## F1. `student_coursework_and_deadlines`

课程、作业和截止时间管理。

典型需求：

- 查看本周作业；
- 查询缺交任务；
- 检查课程公告；
- 查看教师反馈；
- 追踪提交状态。

数据库可以包括：

- 学校；
- 课程；
- 班级；
- 作业；
- 截止时间；
- 提交状态；
- 成绩；
- 教师评语；
- 附件。

## F2. `campus_life_and_services`

校园生活和学生服务。

典型需求：

- 查询图书馆开放时间；
- 预约实验室；
- 查询奖学金申请条件；
- 查看宿舍、食堂、社团信息；
- 办理请假或证明申请。

数据库可以包括：

- 校园地点；
- 服务项目；
- 办事流程；
- 申请材料；
- 时间窗口；
- 权限；
- 申请状态；
- 通知记录。

这个主题对于大学生尤其重要，但与 K12 学习环境不同，建议作为独立环境。

## F3. `student_growth_portfolio`

综合素质、竞赛和成长档案。

典型需求：

- 整理竞赛经历；
- 生成活动档案；
- 记录志愿服务；
- 准备综合素质评价材料；
- 生成个人陈述初稿。

数据库可以包括：

- 活动；
- 证书；
- 竞赛；
- 项目；
- 志愿服务；
- 反思日志；
- 推荐信；
- 材料版本。

需要加入真实性和隐私约束，禁止伪造经历或证书。

---

# 二、推荐的分类原则

## 1. 第一层按“用户目标”，不按学科

推荐：

```text
题目求解
作业辅导
考试备考
学习诊断
升学选择
资料管理
```

不推荐一开始就做：

```text
数学环境
物理环境
化学环境
英语环境
```

因为后者会导致：

- 工具重复；
- 数据库重复；
- 评测任务重复；
- 环境数量快速膨胀。

## 2. 学科作为数据库字段和任务参数

例如同一个 `adaptive_practice` 环境可以通过以下字段区分：

```text
subject = math
grade = high_school
curriculum = shanghai
topic = analytic_geometry
```

环境不变，数据和任务实例变化。

## 3. 需要独立工具链的领域才拆成独立环境

以下情况适合单独拆环境：

- 多模态输入差异明显；
- 数据结构完全不同；
- 权限和安全规则不同；
- 工具调用流程不同；
- 评测标准不同。

例如：

- 数学图片解题和英语口语练习应拆开；
- 学习规划和校园事务应拆开；
- 高考志愿和普通题目搜索应拆开。

---

# 三、建议的首批环境

如果要正式开始构建，不建议一次做十二个。第一阶段可以选择六个最有代表性的主题：

```text
1. multimodal_question_solving
2. homework_assistance
3. adaptive_practice
4. exam_preparation
5. learning_diagnosis
6. personal_study_planning
```

这六个环境覆盖学生端的主要闭环：

```text
遇到问题
→ 获取解答
→ 完成作业
→ 进行练习
→ 分析错误
→ 准备考试
→ 制定计划
```

第二阶段再增加：

```text
7. school_and_major_guidance
8. student_resource_search
9. language_learning
10. student_coursework_and_deadlines
11. exam_integrity_and_safe_tutoring
12. student_growth_portfolio
```

## 四、建议的最终层级

```text
student_learning_assistant
├── multimodal_question_solving
├── concept_learning
├── homework_assistance
├── adaptive_practice
├── assessment_feedback
├── exam_preparation
├── school_and_major_guidance
├── learning_diagnosis
├── personal_study_planning
├── student_resource_search
├── personal_knowledge_management
├── language_learning
├── student_coursework_and_deadlines
├── campus_life_and_services
├── exam_integrity_and_safe_tutoring
└── student_growth_portfolio
```

最核心的设计判断是：

> 学生端环境应围绕“学生在什么场景下需要 Agent”分类，而不是围绕“数据库里有什么表”或“学校里有哪些学科”分类。

这样构建出来的主题既符合中国学生从小学、初中、高中到大学的真实需求，也能直接套用论文中的环境生成流程：为每个主题分别挖掘离线数据库、生成业务工具、建立工具依赖图，再合成可验证任务。

> 按照你所说的初步6主题：
> 1. multimodal_question_solving
> 2. homework_assistance
> 3. adaptive_practice
> 4. exam_preparation
> 5. learning_diagnosis
> 6. personal_study_planning
> 那如何构建来自真实世界的数据和格式呢，如何构建工具集

这 6 个主题可以采用统一的构建框架：

```text
真实世界资料
→ 数据采集与清洗
→ 统一数据模型
→ 离线快照数据库
→ 业务工具生成
→ 工具单元测试
→ 工具依赖图
→ 任务合成与执行验证
```

关键是：**数据库来自真实教育资料和真实业务格式，工具集来自学生实际会完成的任务流程**，而不是简单地为每张表生成 CRUD 接口。

---

# 一、统一的数据构建原则

## 1. 优先采集真实来源

中国教育场景可以使用以下来源：

### 官方来源

- 教育部、各省市教育考试院；
- 上海、北京、浙江等地区考试院；
- 国家中小学智慧教育平台；
- 学校公开课程和作业说明；
- 高校招生章程；
- 官方课程标准和教材目录。

### 公开教育资源

- 开放题库；
- 开源教材；
- 公开课件；
- 公开竞赛题；
- 公开解析文章；
- Kaggle、GitHub 等开放教育数据集；
- 公共邮件、论坛、学习记录数据集。

### 业务格式

尽量保留真实系统常见格式：

- PDF 试卷；
- HTML 教材页面；
- Markdown 讲义；
- JSON API 导出；
- CSV 成绩表；
- 图片题目；
- LaTeX 公式；
- XLSX 课程表；
- 音频和转写文本；
- ICS 日历文件。

不要把所有内容都转换成一个“大 JSON”。应该保留原始快照，再生成结构化索引。

## 2. 采用“原始数据 + 规范化数据 + 索引”三层结构

例如题目数据：

```text
raw/
├── exam_2026_shanghai_math.pdf
├── problem_001.png
└── source_page.html

normalized/
├── problems.json
├── solutions.json
├── knowledge_points.json
└── problem_occurrences.json

indexes/
├── title_index.json
├── topic_index.json
└── embedding_index/
```

每条规范化数据都需要保留来源：

```json
{
  "source_id": "shanghai_exam_office_2026",
  "source_uri": "...",
  "snapshot_path": "raw/exam_2026_shanghai_math.pdf",
  "content_hash": "...",
  "extracted_at": "2026-08-01T00:00:00Z",
  "extraction_method": "manual_review"
}
```

这样可以回答：

- 数据来自哪里；
- 是否为官方来源；
- 哪个版本；
- 何时抓取；
- 是否被人工修订；
- 是否可以重建。

## 3. 对真实数据做脱敏和固定化

学生数据不能直接使用真实个人信息。需要：

- 删除姓名、手机号、身份证号、学校内部账号；
- 将用户替换为稳定的合成 ID；
- 保留统计特征和行为模式；
- 固定随机种子；
- 保存数据版本；
- 用离线快照替代实时网页或实时 LMS。

最终运行时不访问互联网，避免任务结果不稳定。

---

# 二、`multimodal_question_solving`

## 数据库构建

这个环境的核心是真实题目图片和识别链路。

### 数据来源

- 公开试卷 PDF 截图；
- 公开题库图片；
- 手写解题过程；
- 教材例题；
- 竞赛题；
- 人工制作的遮挡、模糊和裁剪版本。

建议每道题同时保留：

```text
原始整图
题目区域裁剪图
OCR 文本
LaTeX 公式
图形识别结果
人工校正结果
标准答案
标准分步解法
```

### 推荐目录

```text
multimodal_question_solving/
├── artifacts/
│   ├── artifact_0001.jpg
│   └── artifact_0002.png
├── recognition/
│   ├── ocr_runs.json
│   ├── formula_runs.json
│   └── corrections.json
├── problems/
│   ├── problems.json
│   ├── problem_regions.json
│   └── solutions.json
├── sources/
│   └── provenance.json
└── README.md
```

### 核心数据格式

```json
{
  "artifact_id": "art_001",
  "media_type": "image",
  "width": 2048,
  "height": 1536,
  "content_hash": "sha256:...",
  "source_id": "public_exam_2025_001"
}
```

```json
{
  "recognition_id": "rec_001",
  "artifact_id": "art_001",
  "region": [120, 80, 1800, 900],
  "raw_text": "已知椭圆...",
  "latex": "\\frac{x^2}{a^2}+...",
  "confidence": 0.86,
  "status": "needs_confirmation"
}
```

## 工具集

不要直接提供 `solve_image()`，而应拆出真实链路：

```text
upload_artifact
→ detect_problem_regions
→ recognize_text
→ recognize_formula
→ get_recognition_result
→ correct_recognition
→ search_matching_problem
→ get_problem_solution
→ register_solution
→ verify_solution
→ generate_explanation
```

推荐工具：

- `upload_artifact`
- `get_artifact_metadata`
- `detect_problem_regions`
- `recognize_math_content`
- `get_recognition_result`
- `correct_recognition`
- `search_matching_problems`
- `get_problem`
- `get_solution`
- `verify_solution`
- `save_student_attempt`
- `generate_explanation`

可验证状态包括：

- 图片是否存在；
- 识别区域是否存在；
- 识别置信度是否低于阈值；
- 学生是否确认了公式；
- 解答是否与标准答案一致；
- 是否完成了数值验证。

---

# 三、`homework_assistance`

## 数据库构建

这个环境不是题库，而是“作业任务管理 + 作业要求理解”。

### 数据来源

- 公开课程作业；
- 教师发布的作业通知；
- LMS 导出数据；
- 课程 syllabus；
- 作业 rubric；
- 学生提交记录；
- 附件和提交格式说明。

### 推荐目录

```text
homework_assistance/
├── courses.json
├── assignments.json
├── assignment_attachments/
├── rubrics.json
├── submissions.json
├── teacher_comments.json
└── policies.json
```

### 核心数据

```json
{
  "assignment_id": "hw_001",
  "course_id": "math_g10",
  "title": "解析几何练习",
  "description": "...",
  "due_at": "2026-09-10T23:59:00+08:00",
  "submission_type": "pdf",
  "required_items": [1, 2, 3, 4],
  "rubric_id": "rubric_001",
  "status": "published"
}
```

```json
{
  "rubric_id": "rubric_001",
  "criteria": [
    {
      "id": "proof_completeness",
      "description": "过程完整",
      "weight": 0.4
    }
  ]
}
```

## 工具集

真实任务链可以是：

```text
list_courses
→ list_assignments
→ get_assignment
→ get_rubric
→ inspect_submission_requirements
→ check_draft_completeness
→ save_draft
→ validate_submission
```

推荐工具：

- `list_courses`
- `list_assignments`
- `get_assignment`
- `get_assignment_rubric`
- `get_assignment_attachment`
- `get_submission_requirements`
- `check_draft_completeness`
- `check_required_questions`
- `save_draft`
- `validate_submission`
- `submit_assignment`

需要设置权限约束：

- 学生只能访问自己的作业；
- 不能修改教师发布的作业；
- 不能伪造提交时间；
- 截止时间之后提交要标记为迟交；
- 不能让 Agent 直接代替学生完成所有作业。

---

# 四、`adaptive_practice`

## 数据库构建

这个环境需要真实题库和学生作答历史。

### 数据来源

- 公开题库；
- 历年试卷；
- 课程教材配套练习；
- Eedi 等带误区标签的数据；
- 学校测验样本；
- 人工标注的题目难度和知识点。

### 推荐数据结构

```text
items.json
item_knowledge_points.json
item_variants.json
item_statistics.json
misconceptions.json
attempts.json
practice_sessions.json
```

题目记录：

```json
{
  "item_id": "item_001",
  "subject": "math",
  "grade": "G10",
  "curriculum": "shanghai",
  "topic": "analytic_geometry",
  "difficulty": 0.68,
  "question_type": "multiple_choice",
  "stem": "...",
  "answer": "B",
  "misconception_tags": ["M_SLOPE_SIGN"]
}
```

作答记录：

```json
{
  "attempt_id": "att_001",
  "student_id": "stu_001",
  "item_id": "item_001",
  "answer": "C",
  "is_correct": false,
  "duration_seconds": 145,
  "submitted_at": "2026-09-01T..."
}
```

## 工具集

```text
get_student_profile
→ get_recent_attempts
→ identify_weak_topics
→ search_candidate_items
→ estimate_practice_difficulty
→ create_practice_session
→ submit_response
→ update_item_statistics
→ get_session_report
```

推荐工具：

- `get_student_learning_profile`
- `list_recent_attempts`
- `get_topic_mastery_summary`
- `search_practice_items`
- `get_item_statistics`
- `create_practice_session`
- `add_item_to_session`
- `submit_item_response`
- `get_instant_feedback`
- `close_practice_session`
- `get_practice_report`

自适应规则必须显式化，例如：

```text
连续两题正确
→ 难度 + 0.1

连续两题错误
→ 提供同知识点低难度题

错误类型稳定
→ 推荐针对性补救题
```

不要让“推荐题目”完全由 LLM 自由决定，应由工具执行明确的筛选约束。

---

# 五、`exam_preparation`

## 数据库构建

这是最需要中国本地化的主题。

### 必须建模的字段

```text
考试类型
省市
年份
科目
试卷版本
题号
分值
知识点
题型
难度
官方答案
官方解析
```

例如：

```json
{
  "paper_id": "gaokao_shanghai_math_2026",
  "exam_type": "gaokao",
  "region": "Shanghai",
  "year": 2026,
  "subject": "Mathematics",
  "paper_variant": "A",
  "source_authority": "official",
  "source_document": "raw/shanghai_2026_math.pdf"
}
```

题目和试卷要分开：

```json
{
  "occurrence_id": "occ_2026_sh_12",
  "paper_id": "gaokao_shanghai_math_2026",
  "problem_id": "canonical_problem_883",
  "question_no": 12,
  "score": 12
}
```

这样可以处理：

- 同一道题被不同网站转载；
- 同一题的不同试卷版本；
- 官方题目和培训机构改编题；
- 题目编号变化。

## 工具集

```text
parse_exam_request
→ search_exam_papers
→ verify_exam_metadata
→ list_paper_problems
→ filter_by_topic
→ get_problem_statistics
→ get_official_solution
→ get_student_exam_history
→ analyze_weak_topics
→ generate_review_plan
```

推荐工具：

- `search_exam_papers`
- `get_exam_paper`
- `verify_paper_metadata`
- `list_paper_problems`
- `search_problems_by_topic`
- `get_problem_occurrences`
- `get_official_answer`
- `get_solution_explanations`
- `get_problem_statistics`
- `get_student_exam_history`
- `generate_exam_review_plan`

需要重点测试：

- 2026 年与 2025 年不能混淆；
- 上海与其他省份不能混淆；
- 高考与学业水平考试不能混淆；
- 官方解析与非官方解析要区分；
- 题目、答案、解析必须正确关联。

---

# 六、`learning_diagnosis`

## 数据库构建

这个环境的数据不是单个题目，而是学生长期学习轨迹。

### 数据来源

- LMS 学习记录；
- 测验和作业结果；
- xAPI statements；
- 题目知识点标签；
- 作答时长；
- 错误类型；
- 复习记录；
- 学生自评问卷。

真实个人数据应脱敏或合成，但需要保留真实分布，例如：

- 某知识点长期错误；
- 只在综合题中出错；
- 正确率高但耗时长；
- 频繁跳过难题；
- 临近考试学习量突增。

### 推荐目录

```text
learning_diagnosis/
├── students.json
├── activities.json
├── activity_tree.json
├── attempts.json
├── scores.json
├── error_annotations.json
├── study_sessions.json
└── interventions.json
```

## 工具集

```text
get_activity_history
→ aggregate_topic_performance
→ analyze_error_patterns
→ detect_learning_risk
→ compare_time_periods
→ generate_diagnosis
→ save_diagnosis
→ recommend_intervention
```

推荐工具：

- `get_student_activity_history`
- `get_topic_performance`
- `get_error_distribution`
- `get_time_on_task`
- `detect_repeated_errors`
- `detect_learning_risks`
- `compare_learning_periods`
- `create_diagnosis_report`
- `save_diagnosis_report`
- `get_intervention_history`

诊断工具必须返回证据：

```json
{
  "topic": "analytic_geometry",
  "risk_level": "medium",
  "evidence": [
    {
      "metric": "recent_accuracy",
      "value": 0.42,
      "sample_size": 12
    },
    {
      "metric": "repeated_misconception",
      "value": "M_SLOPE_SIGN",
      "count": 5
    }
  ]
}
```

不要只返回：

```json
{"student_level": "weak"}
```

否则无法验证，也容易产生不透明的教育判断。

---

# 七、`personal_study_planning`

## 数据库构建

这个环境需要真实学习计划、考试日期和学生时间约束。

### 数据来源

- 课程表；
- 考试安排；
- 作业截止时间；
- 学校校历；
- 学生可用时间；
- 历史计划完成记录；
- 任务优先级；
- 学习时长估计。

### 推荐目录

```text
personal_study_planning/
├── calendars.json
├── courses.json
├── exams.json
├── assignments.json
├── goals.json
├── study_tasks.json
├── availability.json
├── plans.json
└── completion_records.json
```

核心数据：

```json
{
  "availability_id": "avail_001",
  "student_id": "stu_001",
  "weekday": 2,
  "start_time": "19:00",
  "end_time": "21:00",
  "blocked": false
}
```

```json
{
  "task_id": "task_001",
  "student_id": "stu_001",
  "title": "完成解析几何错题复习",
  "subject": "math",
  "estimated_minutes": 60,
  "priority": "high",
  "deadline": "2026-09-12",
  "prerequisites": []
}
```

## 工具集

```text
get_student_calendar
→ get_upcoming_deadlines
→ get_learning_goals
→ get_available_time
→ estimate_task_load
→ create_study_plan
→ validate_schedule
→ record_completion
→ detect_plan_delay
→ replan
```

推荐工具：

- `get_student_calendar`
- `get_upcoming_exams`
- `get_pending_assignments`
- `get_learning_goals`
- `get_available_time`
- `estimate_task_duration`
- `create_study_plan`
- `validate_study_plan`
- `record_task_completion`
- `detect_schedule_conflicts`
- `replan_study_schedule`
- `get_plan_report`

需要设置的确定性约束：

- 不能安排在考试之后；
- 不能超过每天可用时间；
- 任务有前置依赖时必须先完成前置任务；
- 课程、作业、考试时间不能冲突；
- 已完成任务不能重复计入未完成负担；
- 调整计划时必须保留版本和调整原因。

---

# 八、工具集的统一生成方法

## 1. 先写业务流程，不要先写函数

例如学生上传题目：

```text
学生上传图片
→ 系统检测题目区域
→ 识别文字和公式
→ 发现置信度低
→ 请求学生确认
→ 匹配题库
→ 获取标准解
→ 验证结果
→ 生成讲解
```

再把流程节点转换成工具：

```text
upload_artifact
detect_problem_regions
recognize_math_content
request_confirmation
search_matching_problems
get_solution
verify_solution
generate_explanation
```

## 2. 工具分为四类

### 查询工具

只读数据库：

```text
get_problem
search_exam_papers
get_student_history
```

### 状态创建工具

创建会话或任务：

```text
create_practice_session
open_study_plan
start_question_session
```

### 状态变更工具

修改真实业务状态：

```text
submit_assignment
record_completion
book_practice_item
save_diagnosis
```

### 验证和分析工具

根据数据库状态计算结果：

```text
verify_solution
validate_submission
detect_learning_risks
check_schedule_conflicts
```

## 3. 每个工具都要定义

```json
{
  "name": "search_exam_papers",
  "description": "按考试类型、地区、年份和科目搜索试卷",
  "parameters": {
    "exam_type": "string?",
    "region": "string?",
    "year": "integer?",
    "subject": "string?"
  },
  "reads": true,
  "writes": false,
  "errors": [
    "invalid_date",
    "invalid_exam_type"
  ],
  "tests": [
    "上海 2026 高考数学返回目标试卷",
    "北京试卷不能误匹配上海",
    "不存在年份返回空结果"
  ]
}
```

## 4. 工具生成后必须做执行验证

论文中的流程可以直接采用：

```text
生成候选工具
→ Python 编译
→ 单元测试
→ 随机参数测试
→ 数据库状态检查
→ 保留通过工具
```

最低要求：

- 函数可以编译；
- 参数错误会返回稳定错误；
- 不存在的实体不会静默成功；
- 读工具不修改数据库；
- 写工具会产生可检查的状态变化；
- 工具返回结构稳定；
- 关键业务约束有拒绝分支。

---

# 九、六个环境之间如何共享数据

论文强调单条任务可以限制在单个环境，但不同环境之间可以共享数据规范。

建议建立公共数据层：

```text
shared/
├── students.json
├── subjects.json
├── grade_bands.json
├── knowledge_points.json
├── problems.json
├── sources.json
└── provenance.json
```

然后每个环境拥有自己的业务状态：

```text
multimodal_question_solving/
homework_assistance/
adaptive_practice/
exam_preparation/
learning_diagnosis/
personal_study_planning/
```

共享的是：

- `student_id`
- `problem_id`
- `knowledge_point_id`
- `source_id`
- `course_id`

不共享的是：

- 环境内部 session；
- 任务状态；
- 计划版本；
- 识别运行记录；
- 诊断报告；
- 作业提交状态。

这样既能保持数据一致，也不会让单条任务变成难以验证的跨数据库流程。

## 最推荐的建设顺序

```text
第一阶段：multimodal_question_solving
第二阶段：exam_preparation
第三阶段：adaptive_practice
第四阶段：homework_assistance
第五阶段：learning_diagnosis
第六阶段：personal_study_planning
```

理由是：

1. 前两个最容易获得公开真实数据；
2. 多模态题目环境能建立图片、OCR、公式和解答基础设施；
3. 备考环境能建立中国地区、年份、试卷版本等教育字段；
4. 自适应练习依赖题库和作答记录；
5. 学习诊断依赖长期历史数据；
6. 个性化计划需要前面几个环境产生的任务、成绩和截止时间数据。

> 关于面向学生端的环境，写一份md文件，
> 一级主题为学生教育助手，
> 二级主题为
> ├── A. 学习内容获取
> ├── B. 练习与作业
> ├── C. 考试与升学
> ├── D. 学习规划与诊断
> ├── E. 学习资料与知识管理
> └── F. 学校事务与成长支持
> 三级主题进一步按照二级主题细分，每个环境一个三级主题，介绍每个环节的典型需求，数据库包括哪些数据

<details><summary>3 previous messages</summary>

> 我会按你给定的三级分类编写一份独立 Markdown，统一描述主题定位、典型需求和数据库组成，并保存到 `AgentWorld/edu-envs`。
>
> 未发现额外仓库约束。现在写入文档，按六个二级主题展开三级环境，并保持每个环境结构一致。
>
> <details><summary>Created a file</summary>
>
> - Wrote `./AgentWorld/edu-envs/学生端环境主题设计.md` (+461 -0)
>
> </details>
> </details>

已完成文档：[学生端环境主题设计.md](./AgentWorld/edu-envs/学生端环境主题设计.md)

内容包括：

- 一级主题“学生教育助手”
- 六个二级主题
- 16 个三级环境主题
- 每个环境的定位与典型学生需求
- 每个环境对应的数据库内容
- 学科字段与环境划分原则
- 原始数据、规范化数据、索引的三层建库方式
- 数据来源、隐私、权限和可验证任务设计原则

> https://zcnvvrmhxi9w.feishu.cn/file/RDDpbro0qotQmTxL074c8CfMnyg 我的 学生端环境设计是否可以满足以上链接设想的真实场景需求，根据“场景描述”一列的信息
>
> User context
>
> Attachments:
> - 学生端环境主题设计.md: `./AgentWorld2/学生端环境主题设计.md`

<details><summary>1 previous message</summary>

> 我先读取你当前的 `AgentWorld2/学生端环境主题设计.md`，再尝试核对飞书链接；如果链接受权限或网络限制，我会明确指出需要你粘贴“场景描述”列内容。
> </details>

目前无法直接判断“是否满足飞书表格中的真实场景”，因为当前环境无法访问该飞书链接内容；我也看不到其中“场景描述”列的具体记录。

我已经检查了你的 [学生端环境主题设计.md](./AgentWorld2/学生端环境主题设计.md)。这份设计目前覆盖了以下类型：

- 题目图片识别、OCR、公式识别、解题；
- 知识点解释；
- 作业理解、提交检查；
- 自适应练习和错题反馈；
- 考试备考、志愿填报；
- 学习诊断和学习计划；
- 学习资料、错题本和语言学习；
- 课程事务、校园服务和成长档案。

不过，是否满足真实场景，关键要看飞书“场景描述”里是否包含以下需求：

1. **具体用户角色**：小学生、初中生、高中生、大学生，还是家长代学生使用；
2. **输入形式**：图片、语音、视频、PDF、聊天文本、成绩表或课程表；
3. **目标动作**：查询、解答、批改、推荐、规划、提交、预约还是申请；
4. **数据依赖**：是否需要历年试卷、教材版本、学校系统、个人学习记录；
5. **权限要求**：是否涉及成绩、考试、志愿、作业提交或校园事务；
6. **结果形式**：答案、解释、学习计划、提醒、报告还是正式提交；
7. **异常情况**：图片模糊、资料过期、信息冲突、截止时间已过、权限不足等。

从现有文档看，可能还需要重点补充或细化：

- **语音问答和口语输入**：目前主要强调图片和文本；
- **家长协同场景**：例如家长查看学习报告、设置学习目标；
- **跨设备与通知**：手机上传、电脑继续、截止时间提醒；
- **学生身份和权限**：不同年级、选科、学校账号权限；
- **实时学校系统交互**：成绩、作业、课程表、公告同步；
- **中国本地考试差异**：中考、高考、学考、会考、地区和试卷版本；
- **低龄学生保护**：隐私、内容安全、家长授权；
- **学习结果闭环**：建议之后是否记录执行、完成和再次评估。

请把飞书表格中“场景描述”这一列复制出来，或者导出为 Excel/CSV 放到工作区。我可以逐条建立如下映射：

```text
场景描述
→ 用户角色
→ 学习目标
→ 对应三级环境
→ 是否需要新增环境
→ 所需数据库
→ 所需工具链
→ 缺失能力
```

最后会给你一份覆盖矩阵，明确区分：

- 已覆盖；
- 部分覆盖；
- 完全缺失；
- 不应作为独立环境、只需作为任务参数的场景。

> 我的 学生端环境设计是否可以满足以上csv中设想的真实场景需求，主要根据“场景描述”一列的信息
>
> User context
>
> Attachments:
> - ai_education_scenes_with_details.csv: `./AgentWorld2/ai_education_scenes_with_details.csv`
> - 学生端环境主题设计.md: `./AgentWorld2/学生端环境主题设计.md`

<details><summary>1 previous message</summary>

> 我现在读取 CSV 的列结构和“场景描述”内容，并将每条场景映射到现有三级主题，标出覆盖、部分覆盖和缺失项。
> </details>

结论：你的学生端六大类方向基本正确，但当前 16 个三级主题**不能完整覆盖 CSV 中的真实场景**。它更像“通用学生学习助手”的功能地图，而 CSV 更像“面向学科课堂的 AI 教学场景库”。两者存在明显的粒度和视角差异。

我统计了 `ai_education_scenes_with_details.csv`：

- 共 10,249 条场景；
- 学科覆盖语文、数学、英语、物理、化学、生物、历史、地理、政治、体育、德育美育；
- 年级覆盖小学、初中、高中；
- 高频场景关键词包括：学习 3,151 条、练习 1,848 条、游戏 1,348 条、写作 1,085 条、实验 875 条、阅读 814 条、图片 539 条、安全 409 条、语音 344 条、计划 215 条；
- “作业”仅 86 条，“考试”仅 41 条，说明 CSV 重点不是传统 LMS 作业管理，而是课堂学习、练习、互动和能力培养。

## 一、你的主题能够覆盖的部分

### A. 学习内容获取

可以覆盖 CSV 中的：

- 图片识题；
- 概念讲解；
- 阅读理解；
- 写作指导；
- 语音朗读；
- 词汇、语法和知识点解释；
- 图文匹配和知识结构梳理。

但 `multimodal_question_solving` 目前偏“上传题目→求解”，而 CSV 中很多图片场景是：

- 看图说话；
- 图片观察；
- 实验装置识别；
- 地图、图表和历史图片分析；
- 作文图片素材生成；
- 几何图形和生物结构识别。

因此应将它改成更宽的：

```text
multimodal_learning_interaction
```

而不是只强调 `question_solving`。

### B. 练习与作业

可以覆盖：

- 闯关练习；
- 即时反馈；
- 错题重练；
- 个性化练习；
- 作文、阅读和知识点训练；
- 分步提示。

但 `homework_assistance` 与 CSV 不完全匹配。CSV 中大量场景不是“帮助完成作业”，而是：

```text
课堂互动
→ 即时练习
→ 游戏化反馈
→ 分层巩固
```

因此建议新增或改名为：

```text
interactive_practice
```

`adaptive_practice` 应保留，但需要扩展游戏化、分层练习和实时反馈。

### C. 考试与升学

这是当前设计与 CSV 适配度最低的部分之一。

你的：

- `exam_preparation`
- `school_and_major_guidance`
- `exam_integrity_and_safe_tutoring`

更接近高年级考试和升学产品。

但 CSV 中的考试、升学场景数量较少，反而包含大量：

- 课堂知识巩固；
- 材料题分析；
- 学科核心素养；
- 社会议题讨论；
- 安全教育；
- 道德判断；
- 国防教育；
- 法治教育。

所以不能让“考试与升学”成为学生端的主干。它应与“课程学习与素养发展”并列，而不是占据重要中心位置。

建议把 `C` 改为：

```text
C. 考试、升学与综合素养
├── C1. 考试备考
├── C2. 升学与专业选择
├── C3. 学科核心素养与材料分析
└── C4. 诚信、安全与法治教育
```

### D. 学习规划与诊断

可以覆盖：

- 个性化学习；
- 薄弱知识点识别；
- 复习计划；
- 记忆曲线；
- 学习习惯分析；
- 学习风险提醒。

但 CSV 中很多“个性化”场景是短周期的：

```text
当前错误
→ 立即提示
→ 再练一道
→ 当堂纠正
```

而你的 `learning_diagnosis`、`personal_study_planning` 偏长期学习管理。两者需要区分：

```text
即时诊断 / 即时干预
长期学习诊断 / 长期计划
```

建议新增：

```text
instant_learning_feedback
```

或者把它作为 `adaptive_practice` 的一个明确子流程。

### E. 学习资料与知识管理

这一类可以覆盖：

- 资料检索；
- 知识点关联；
- 错题本；
- 生词和记忆曲线；
- 个人笔记；
- 语言学习。

但 CSV 中“资料”不是主要场景，“学习资源搜索”出现较少。相反，语言学习、写作、阅读、词汇、朗读场景非常多。因此 `language_learning` 不应放在资料管理下面，建议单独作为一级或二级重点环境。

### F. 学校事务与成长支持

可以覆盖：

- 校园服务；
- 安全教育；
- 心理健康；
- 综合实践；
- 成长档案；
- 课程和截止日期。

但是 CSV 中的“安全、心理、道德、国防、生态、劳动”等场景，主要是**课程学习和价值素养教育**，不是校园事务。

例如：

- “网络安全专题学习”；
- “生命安全教育”；
- “劳动教育反思”；
- “总体国家安全观分析”；
- “心理健康知识学习”。

这些应从 `F. 学校事务与成长支持` 中独立出来，形成：

```text
F. 综合素养与成长支持
```

## 二、CSV 暴露出的主要缺口

### 1. 缺少课堂互动环境

CSV 大量场景是：

- AI 实时提问；
- 学生回答；
- AI 追问；
- 即时纠错；
- 课堂小游戏；
- 小组讨论；
- 情境任务；
- 课堂表现记录。

现有主题没有明确建模“课堂互动”：

```text
classroom_interaction
```

建议增加：

- 课堂活动；
- 学生回答；
- 教师/AI 追问；
- 互动轮次；
- 即时评价；
- 小组任务；
- 课堂参与记录。

### 2. 缺少语音和朗读环境

CSV 中语音相关场景至少包括：

- 拼音发音；
- 英语口语；
- 朗读评价；
- 听力理解；
- 语调、重音和停顿；
- 语音纠错。

当前 `multimodal_question_solving` 不能充分表达：

```text
speech_pronunciation_and_reading
```

建议新增三级主题：

```text
A3. 语音、朗读与口语训练
```

数据库应包括：

- 音频；
- 转写；
- 音素或词级识别；
- 发音错误；
- 语速；
- 停顿；
- 重音；
- 评分和练习历史。

### 3. 缺少写作与表达环境

CSV 中“写作”有 1,085 条，远高于“作业”和“考试”。

包括：

- 日记；
- 看图写话；
- 作文构思；
- 续写；
- 仿写；
- 病句修改；
- 人物描写；
- 议论文；
- 材料作文；
- 政治论述；
- 历史材料题表达。

现有 `concept_learning` 或 `language_learning` 不能充分承载，建议新增：

```text
A4. 写作与表达指导
```

数据库包括：

- 作文题目；
- 学生草稿；
- 文章版本；
- 段落结构；
- 句法、词汇和标点错误；
- 评分 rubric；
- 修改建议；
- 引用和事实核验结果。

### 4. 缺少实验探究环境

CSV 中“实验”有 875 条，尤其集中在物理、化学、生物。

现有六类主题没有明确支持：

- 虚拟实验；
- 实验器材识别；
- 实验步骤排序；
- 实验变量控制；
- 数据记录；
- 图表分析；
- 实验安全；
- 实验报告生成；
- 实验结果解释。

建议增加：

```text
B4. 实验探究与科学实践
```

数据库包括：

- 实验方案；
- 器材；
- 操作步骤；
- 变量；
- 实验数据；
- 误差；
- 安全规范；
- 实验报告；
- 评分标准。

### 5. 缺少游戏化学习环境

CSV 中“游戏”有 1,348 条。游戏化不是一个独立学科，而是一种重要交互机制：

- 闯关；
- 配对；
- 词语接龙；
- 拖拽分类；
- 角色扮演；
- 模拟决策；
- 积分、徽章和排行榜。

建议不要把它简单写成数据库里的一个 `game=true`，而是建立通用游戏状态：

```text
game_sessions
levels
challenges
attempts
scores
badges
unlock_conditions
```

它可以被语文、英语、数学和科学练习共同调用。

### 6. 缺少学科素养和社会情境环境

政治、历史、地理、德育美育的很多场景不是传统“答题”，而是：

```text
真实材料
→ 观点辨析
→ 价值判断
→ 论证表达
→ 行为选择
```

建议增加：

```text
C3. 学科素养与情境探究
```

覆盖：

- 历史材料分析；
- 地理综合分析；
- 政治议题讨论；
- 道德判断；
- 法治教育；
- 国家安全教育；
- 生态与劳动教育；
- 公共问题论证。

数据库应包括：

- 新闻和政策材料；
- 历史文献；
- 数据图表；
- 情境案例；
- 观点；
- 论证结构；
- 课程标准；
- 价值冲突；
- 参考答案和评分 rubric。

## 三、建议重新调整主题层级

根据 CSV，建议将学生端重新调整为下面的结构：

```text
学生教育助手
├── A. 学习内容获取与表达
│   ├── A1. 多模态学习理解
│   ├── A2. 知识点与概念学习
│   ├── A3. 语音、朗读与口语训练
│   └── A4. 写作与表达指导
├── B. 练习、作业与实验
│   ├── B1. 互动练习与即时反馈
│   ├── B2. 自适应练习
│   ├── B3. 作业理解与提交检查
│   └── B4. 实验探究与科学实践
├── C. 考试、升学与学科素养
│   ├── C1. 考试备考
│   ├── C2. 升学与专业选择
│   ├── C3. 学科素养与情境探究
│   └── C4. 考试诚信与安全辅导
├── D. 学习诊断与规划
│   ├── D1. 即时学习反馈
│   ├── D2. 学习状态诊断
│   ├── D3. 个性化学习计划
│   └── D4. 学习习惯与风险支持
├── E. 学习资料与知识管理
│   ├── E1. 学习资料搜索与核验
│   ├── E2. 个人知识库与错题管理
│   ├── E3. 词汇与记忆复习
│   └── E4. 学习成果整理
└── F. 综合素养与学校支持
    ├── F1. 课程、作业与截止时间管理
    ├── F2. 心理健康与情绪支持
    ├── F3. 安全、法治与公民教育
    ├── F4. 校园生活与学生服务
    └── F5. 综合实践与成长档案
```

## 四、哪些应该是独立环境，哪些只是参数

不建议把 CSV 中每一个场景名称都建成一个环境。可以按照下面规则合并：

### 应独立成环境

如果具有独立的数据和工具链：

- 多模态学习理解；
- 语音、朗读与口语；
- 写作与表达；
- 自适应练习；
- 实验探究；
- 学习诊断；
- 学习规划；
- 升学与专业选择。

### 不必独立成环境

如果只是交互形式或业务参数：

- 游戏化；
- 闯关；
- 图文匹配；
- 分步提示；
- 个性化；
- 即时反馈；
- 小组讨论。

这些可以作为：

```text
interaction_mode
feedback_mode
task_type
difficulty
```

写入任务和数据库，而不是各自单独建环境。

### 应作为数据字段

- 学科；
- 年级；
- 地区；
- 教材版本；
- 考试类型；
- 知识点；
- 能力层级；
- 题型；
- 课程标准。

## 五、最终判断

你的原设计可以覆盖 CSV 中约一部分通用学习需求，但需要做三项根本调整：

1. **将“题目求解”扩展为“多模态学习理解”**；
2. **新增语音、写作、实验、课堂互动和学科素养环境**；
3. **把考试升学和校园事务的比重降低，把课堂练习、表达和综合素养提升为核心。**

更准确地说，当前设计是：

```text
学生个人学习管理系统
```

而 CSV 设想的是：

```text
覆盖小学到高中、多个学科的 AI 课堂学习与能力培养系统
```

因此，两者不是完全不匹配，而是**产品定位和环境粒度不同**。如果目标是覆盖 CSV，建议采用上面的调整版主题树。

> 按照上面的设想 对md进行修改，即按照结构：
> 学生教育助手
> ├── A. 学习内容获取与表达
> │   ├── A1. 多模态学习理解
> │   ├── A2. 知识点与概念学习
> │   ├── A3. 语音、朗读与口语训练
> │   └── A4. 写作与表达指导
> ├── B. 练习、作业与实验
> │   ├── B1. 互动练习与即时反馈
> │   ├── B2. 自适应练习
> │   ├── B3. 作业理解与提交检查
> │   └── B4. 实验探究与科学实践
> ├── C. 考试、升学与学科素养
> │   ├── C1. 考试备考
> │   ├── C2. 升学与专业选择
> │   ├── C3. 学科素养与情境探究
> │   └── C4. 考试诚信与安全辅导
> ├── D. 学习诊断与规划
> │   ├── D1. 即时学习反馈
> │   ├── D2. 学习状态诊断
> │   ├── D3. 个性化学习计划
> │   └── D4. 学习习惯与风险支持
> ├── E. 学习资料与知识管理
> │   ├── E1. 学习资料搜索与核验
> │   ├── E2. 个人知识库与错题管理
> │   ├── E3. 词汇与记忆复习
> │   └── E4. 学习成果整理
> └── F. 综合素养与学校支持
>  ├── F1. 课程、作业与截止时间管理
>  ├── F2. 心理健康与情绪支持
>  ├── F3. 安全、法治与公民教育
>  ├── F4. 校园生活与学生服务
>  └── F5. 综合实践与成长档案
>
> User context
>
> Attachments:
> - 学生端环境主题设计.md: `./AgentWorld2/学生端环境主题设计.md`

<details><summary>2 previous messages</summary>

> 我会将文档重构为你指定的 6 个二级、25 个三级主题，并把 CSV 体现出的课堂互动、语音、写作、实验、素养教育等需求纳入每个环境说明。
>
> 刚才补丁工具遇到沙箱挂载异常；我改用工作区相对路径重试，不改变文档内容。
> </details>

已按你指定的结构完成修改：

[学生端环境主题设计.md](./AgentWorld2/学生端环境主题设计.md)

本次调整包括：

- 重构为 6 个二级主题；
- 增加 25 个三级环境；
- 纳入 CSV 中的多模态、语音朗读、写作、互动练习、实验探究、学科素养、心理支持等场景；
- 为每个三级环境补充典型需求；
- 为每个三级环境补充数据库核心内容；
- 增加统一建库、数据分层、工具集和环境边界原则。

> 比如学生上传一张题目图片请求讲解，这个可以是属于哪个环境的需求

“学生上传一张题目图片请求讲解”主要属于：

**A1. 多模态学习理解（`multimodal_learning_understanding`）**

因为它的核心流程是：

```text
上传图片
→ 检测题目区域
→ OCR/公式/图形识别
→ 确认识别结果
→ 理解题目
→ 获取或生成解法
→ 讲解
```

如果学生还提供了自己的作答过程，并要求“指出我哪一步错了”，则同时涉及：

**D1. 即时学习反馈（`instant_learning_feedback`）**

流程变为：

```text
上传题目和作答图片
→ 识别题目与学生步骤
→ 对照标准解
→ 定位错误
→ 给出分步提示
→ 让学生重新尝试
```

如果学生明确要求“不要直接告诉我答案，只给提示”，还会涉及：

**C4. 考试诚信与安全辅导（`exam_integrity_and_safe_tutoring`）**

这里不是因为学生一定违规，而是需要控制答案披露程度、遵循渐进式辅导规则。

因此可以这样判断：

| 学生请求                         | 主环境            | 可选关联环境            |
| -------------------------------- | ----------------- | ----------------------- |
| 上传题目图片，请讲解             | A1 多模态学习理解 | —                       |
| 上传题目和自己的解答，请指出错误 | A1 多模态学习理解 | D1 即时学习反馈         |
| 上传题目，只给我提示不要给答案   | A1 多模态学习理解 | D1、C4                  |
| 上传错题，加入错题本以后复习     | A1 多模态学习理解 | E2 个人知识库与错题管理 |
| 上传历年试卷题目，分析考试考点   | A1 多模态学习理解 | C1 考试备考             |
| 上传实验题图片，请分析实验步骤   | A1 多模态学习理解 | B4 实验探究与科学实践   |

在 AgentWorld 的单环境任务设定下，建议这样处理：

- 普通“图片识题和讲解”任务：放在 `multimodal_learning_understanding`；
- 如果任务要求完整的“识别—诊断—提示—重试”流程：将这些工具合并到同一个多模态学习环境中；
- 不要在一条任务轨迹中真的跨多个环境传递 `problem_id` 或 `session_id`；
- 其他主题可以作为任务标签、数据字段或扩展能力，而不必真正跨环境调用。

例如可以定义一个环境内的工具链：

```text
upload_artifact
→ detect_problem_regions
→ recognize_math_content
→ confirm_recognition
→ identify_problem
→ get_solution
→ verify_solution
→ generate_explanation
```

如果包含学生作答诊断，则扩展为：

```text
upload_artifact
→ recognize_problem_and_attempt
→ align_attempt_to_solution
→ identify_first_error
→ release_progressive_hint
→ record_retry
```

所以，最简洁的归类是：

> **“学生上传一张题目图片请求讲解”属于 A1 多模态学习理解；如果包含学生作答分析和渐进式提示，则扩展到 D1 即时学习反馈。**

> 把这个md设想的环境进行实现，先把文件目录的框架搭出来

<details><summary>3 previous messages</summary>

> 我先检查 `AgentWorld2` 当前目录与项目约定，然后按 Markdown 中的 25 个三级环境搭建统一目录骨架和共享数据目录，不先实现具体工具逻辑。
>
> 目录目前只有设计文档和场景 CSV。接下来创建共享数据层、25 个环境目录，以及每个环境统一的 `README/schema/tools/seed/tests` 骨架。
>
> <details><summary>Created 3 files</summary>
>
> - Wrote `./AgentWorld2/README.md` (+27 -0)
> - Wrote `./AgentWorld2/envs/ENVIRONMENT_TEMPLATE.md` (+25 -0)
> - Wrote `./AgentWorld2/envs/environment_manifest.json` (+32 -0)
>
> </details>
> </details>

已搭建学生端环境目录框架，共 25 个三级环境。

新增内容：

- [AgentWorld2/README.md](./AgentWorld2/README.md)
  - 说明整体目录结构、共享数据层和环境实现约定。
- [AgentWorld2/envs/environment_manifest.json](./AgentWorld2/envs/environment_manifest.json)
  - 登记 25 个环境的 ID、所属二级主题和中文名称。
- [AgentWorld2/envs/ENVIRONMENT_TEMPLATE.md](./AgentWorld2/envs/ENVIRONMENT_TEMPLATE.md)
  - 统一环境实现模板。

共享目录：

```text
AgentWorld2/shared/
├── raw/
├── normalized/
├── indexes/
├── schemas/
├── provenance/
└── fixtures/
```

每个三级环境均已创建：

```text
envs/<environment>/
├── raw/
├── normalized/
├── indexes/
├── fixtures/
└── tests/
```

当前只搭建目录和元数据骨架，尚未实现具体数据库 schema、种子数据和工具逻辑。

> 环境的目录再整理一下，envs/StudentAssistant，envs/TeacherAssistant 代表一级主题 ，然后子目录是二级主题，对应ABCDEF，然后是A1，A2对应三级主题也即环境本身

<details><summary>1 previous message</summary>

> 我会把现有 25 个环境移动到 `envs/StudentAssistant/{A-F}/`，并创建对应的 `TeacherAssistant` 一级目录，同时更新 manifest 和 README 的目录说明。
> </details>

已完成目录重整。

现在的目录层级为：

```text
AgentWorld2/
├── shared/
├── envs/
│   ├── StudentAssistant/
│   │   ├── A/
│   │   │   ├── A1_multimodal_learning_understanding/
│   │   │   ├── A2_concept_learning/
│   │   │   ├── A3_speech_reading_and_speaking/
│   │   │   └── A4_writing_and_expression/
│   │   ├── B/
│   │   ├── C/
│   │   ├── D/
│   │   ├── E/
│   │   └── F/
│   └── TeacherAssistant/
└── ai_education_scenes_with_details.csv
```

已移动全部 25 个三级环境，并保留每个环境的：

```text
raw/
normalized/
indexes/
fixtures/
tests/
```

同时更新了：

- [README.md](./AgentWorld2/README.md)
- [environment_manifest.json](./AgentWorld2/envs/environment_manifest.json)
- [ENVIRONMENT_TEMPLATE.md](./AgentWorld2/envs/ENVIRONMENT_TEMPLATE.md)

`TeacherAssistant/` 已作为教师端一级主题预留。

> 把ABCDEF改成具体的名称

我会将 `StudentAssistant` 下的 `A-F` 目录改为“字母 + 二级主题中文名”，并同步更新 README 和环境清单中的路径说明。

> 算了，不改了，先这样命名

好的，保持当前目录命名不变：

```text
envs/StudentAssistant/
├── A/
├── B/
├── C/
├── D/
├── E/
└── F/
```

三级环境目录和 `TeacherAssistant/` 预留目录均保持现状。

> 相应地，面向教师端可以如何设计

教师端建议围绕“教师完成什么工作”分类，而不是简单按照教务系统模块分类。与学生端对应，一级主题可以定义为：

```text
教师教育助手（teacher_education_assistant）
```

建议划分为六个二级主题。

```text
教师教育助手
├── A. 教学内容与资源
├── B. 备课与课程设计
├── C. 作业、测验与评价
├── D. 学情分析与教学干预
├── E. 班级与教学管理
└── F. 教师专业发展与学校事务
```

## A. 教学内容与资源

```text
A1. 教学资源搜索与核验
A2. 题目、试卷与题库管理
A3. 课件、教案与素材生成
A4. 多模态教学资源处理
```

### A1. 教学资源搜索与核验

典型需求：

- 搜索某年级、教材版本和知识点的课件、讲义、实验资料；
- 查找历年真题和官方解析；
- 比较不同来源资源；
- 核验资源的适用学段、时效性和版权。

数据库：

- 教材、课程标准和教学大纲；
- 课件、讲义、视频、试卷和实验资料；
- 来源、作者、机构、发布时间、版权状态；
- 年级、学科、教材版本、知识点和难度标签。

### A2. 题目、试卷与题库管理

典型需求：

- 创建、编辑、审核和归档题目；
- 按知识点、难度和题型组卷；
- 查看题目历史使用情况；
- 管理标准答案、解析和评分点。

数据库：

- 题目、选项、答案和解析；
- 知识点、题型、难度、区分度；
- 试卷、试卷版本、分值和题号；
- 题目使用记录、错误率和来源。

### A3. 课件、教案与素材生成

典型需求：

- 根据教学目标生成教案；
- 设计导入、讲解、练习和总结环节；
- 生成板书、课件大纲、课堂问题；
- 针对不同层次学生生成分层材料。

数据库：

- 教学目标、课程标准和核心素养；
- 教案模板、课件模板和教学活动；
- 教学环节、时间分配和前置知识；
- 练习、案例、图片、视频和板书素材；
- 教师修改版本和审核记录。

### A4. 多模态教学资源处理

典型需求：

- 将教材 PDF、试卷图片转换为可编辑题目；
- 识别手写板书、实验装置、图表和地图；
- 从视频或录音中提取教学片段；
- 为资源生成字幕、摘要和知识点标签。

数据库：

- PDF、图片、音频、视频和内容哈希；
- OCR、公式、表格、图形和字幕识别结果；
- 识别置信度、人工修订和版本；
- 资源区域、页码、时间戳和知识点关联。

## B. 备课与课程设计

```text
B1. 课程目标与教学设计
B2. 课堂活动与互动设计
B3. 分层教学与差异化支持
B4. 实验、项目与探究课程设计
```

### B1. 课程目标与教学设计

典型需求：

- 将课程标准转化为可测量教学目标；
- 设计一节课或一个单元的教学流程；
- 安排知识、能力和素养目标；
- 检查教学内容是否覆盖目标。

数据库：

- 课程标准、教材章节和教学进度；
- 教学目标、目标层级和评价指标；
- 单元、课时、知识点和前置关系；
- 教学流程、时间和教师版本。

### B2. 课堂活动与互动设计

典型需求：

- 设计提问、讨论、分组、抢答和闯关活动；
- 为不同课堂阶段配置互动任务；
- 设置学生回答、追问和反馈规则；
- 生成课堂互动脚本。

数据库：

- 活动类型、活动模板和课堂环节；
- 问题、预期答案、追问和反馈；
- 分组规则、角色、时间和积分；
- 课堂互动记录和活动效果。

### B3. 分层教学与差异化支持

典型需求：

- 为不同水平学生提供不同题目和材料；
- 为学习困难学生设计补救任务；
- 为高水平学生设计拓展任务；
- 根据学生表现动态调整教学内容。

数据库：

- 学生群组、知识点表现和能力证据；
- 分层标准、题目难度和支持策略；
- 补救资源、拓展资源和教学记录；
- 教师干预方案及效果。

### B4. 实验、项目与探究课程设计

典型需求：

- 设计物理、化学、生物实验；
- 设计跨学科项目学习；
- 配置器材、变量、步骤和安全要求；
- 生成实验报告 rubric。

数据库：

- 实验方案、器材和操作步骤；
- 自变量、因变量、控制变量和假设；
- 项目任务、角色、里程碑和成果；
- 安全规范、报告模板和评价标准。

## C. 作业、测验与评价

```text
C1. 作业布置与收集
C2. 自动批改与过程评价
C3. 测验组卷与发布
C4. 评分标准与反馈生成
```

### C1. 作业布置与收集

数据库：

- 作业、题目、附件和截止时间；
- 提交格式、迟交政策和补交政策；
- 学生提交、版本和提交状态；
- 作业发布范围和班级关系。

工具流程：

```text
create_assignment
→ add_items
→ define_requirements
→ publish_assignment
→ collect_submissions
```

### C2. 自动批改与过程评价

典型需求：

- 批改选择、填空、计算和简答题；
- 识别步骤错误和常见误区；
- 检查作文结构、语法和表达；
- 对实验报告和项目成果进行 rubric 评价。

数据库：

- 学生答案和作答过程；
- 标准答案、评分点和 rubric；
- 自动评分结果、人工复核和修改；
- 错误标签、教师评语和成绩版本。

### C3. 测验组卷与发布

典型需求：

- 按知识点和难度组卷；
- 平衡题型、分值和误区覆盖；
- 检查题目重复和试卷难度；
- 发布、撤回和复制测验。

数据库：

- 题库、试卷、分节和权重；
- 题目状态、版本、来源和统计；
- 试卷蓝图、难度分布和知识点覆盖；
- 测验会话和发布记录。

### C4. 评分标准与反馈生成

典型需求：

- 为主观题建立评分标准；
- 根据得分点生成个性化评语；
- 区分知识错误、表达错误和过程缺失；
- 生成班级整体反馈。

数据库：

- rubric、评分维度和分值；
- 参考答案、典型答案和等级描述；
- 学生表现、评语和反馈模板；
- 反馈发送记录和教师修改记录。

## D. 学情分析与教学干预

```text
D1. 班级学情分析
D2. 知识点与错误诊断
D3. 学生分层与风险识别
D4. 干预方案与效果跟踪
```

### D1. 班级学情分析

典型需求：

- 查看班级平均分、通过率和知识点掌握情况；
- 对比不同考试或时间段；
- 找出全班共性问题；
- 生成教学调整建议。

数据库：

- 学生、班级、课程和考试；
- 成绩、作答、耗时和题目知识点；
- 班级聚合统计、趋势和对比基线；
- 教学调整记录。

### D2. 知识点与错误诊断

典型需求：

- 识别某知识点的高频错误；
- 分析学生的首次错误步骤；
- 将错误关联到误区；
- 推荐针对性的补救材料。

数据库：

- 作答步骤、标准解和对齐结果；
- 错误类型、误区和知识点；
- 补救资源、针对性练习和诊断报告；
- 诊断证据与教师确认。

### D3. 学生分层与风险识别

典型需求：

- 识别需要重点辅导的学生；
- 区分暂时失误和持续性困难；
- 发现缺交、低分重复和学习中断；
- 生成班级分层名单。

数据库：

- 成绩、作答、学习活动和缺交记录；
- 分层规则、风险阈值和证据；
- 学生支持状态、隐私授权和访问日志。

### D4. 干预方案与效果跟踪

典型需求：

- 为学生安排一对一辅导或补救练习；
- 记录教师干预内容；
- 对比干预前后的表现；
- 判断是否需要升级到班主任、家长或专业支持。

数据库：

- 干预方案、目标、时间和责任人；
- 辅导记录、资源和练习；
- 干预前后指标、反馈和结果；
- 转介记录和审计日志。

## E. 班级与教学管理

```text
E1. 班级、课程与学生管理
E2. 课堂考勤与参与度
E3. 家校沟通
E4. 教学进度与质量管理
```

### E1. 班级、课程与学生管理

数据库：

- 学校、年级、班级、课程和学期；
- 学生、教师、选课和任课关系；
- 座位、分组、权限和班级名单。

### E2. 课堂考勤与参与度

数据库：

- 课程、课次、签到和请假；
- 学生课堂回答、互动、讨论和任务完成；
- 课堂参与指标、异常记录和教师修订。

### E3. 家校沟通

典型需求：

- 向家长发送作业、成绩和学习反馈；
- 记录家长回复；
- 针对风险学生生成沟通建议；
- 追踪沟通是否完成。

数据库：

- 学生、监护人和联系方式；
- 通知、沟通记录和模板；
- 已读状态、反馈、授权和隐私设置；
- 风险事件和转介状态。

### E4. 教学进度与质量管理

典型需求：

- 查看班级教学进度；
- 检查课程目标完成情况；
- 比较多个班级的教学效果；
- 生成教研和质量分析报告。

数据库：

- 教学计划、课时、教材章节和进度；
- 课程目标、测评结果和教学记录；
- 班级比较指标、教研报告和审核版本。

## F. 教师专业发展与学校事务

```text
F1. 教师教研与备课协作
F2. 教师培训与能力发展
F3. 教学成果与工作档案
F4. 学校制度与行政事务
```

### F1. 教师教研与备课协作

数据库：

- 教研组、教师、共享教案和课件；
- 备课版本、批注、审核和协作记录；
- 公开课、听评课和教研活动。

### F2. 教师培训与能力发展

数据库：

- 培训课程、课程目标和学习材料；
- 教师参与记录、测验、证书和学时；
- 能力维度、发展目标和培训计划。

### F3. 教学成果与工作档案

数据库：

- 教案、课件、试卷、教学反思和案例；
- 公开课、竞赛、论文和获奖记录；
- 资源版本、来源、评价和展示权限。

### F4. 学校制度与行政事务

典型需求：

- 查询请假、调课、监考和会议安排；
- 了解学校教学制度和报表要求；
- 填写教学周报、成绩分析和工作记录；
- 查询教室、设备和实验室使用情况。

数据库：

- 校历、课程表、会议和任务；
- 制度文件、流程、表单和截止时间；
- 教师申请、审批、附件和状态；
- 教室、设备、实验室和预约记录。

## 推荐的教师端主题树

```text
教师教育助手
├── A. 教学内容与资源
│   ├── A1. 教学资源搜索与核验
│   ├── A2. 题目、试卷与题库管理
│   ├── A3. 课件、教案与素材生成
│   └── A4. 多模态教学资源处理
├── B. 备课与课程设计
│   ├── B1. 课程目标与教学设计
│   ├── B2. 课堂活动与互动设计
│   ├── B3. 分层教学与差异化支持
│   └── B4. 实验、项目与探究课程设计
├── C. 作业、测验与评价
│   ├── C1. 作业布置与收集
│   ├── C2. 自动批改与过程评价
│   ├── C3. 测验组卷与发布
│   └── C4. 评分标准与反馈生成
├── D. 学情分析与教学干预
│   ├── D1. 班级学情分析
│   ├── D2. 知识点与错误诊断
│   ├── D3. 学生分层与风险识别
│   └── D4. 干预方案与效果跟踪
├── E. 班级与教学管理
│   ├── E1. 班级、课程与学生管理
│   ├── E2. 课堂考勤与参与度
│   ├── E3. 家校沟通
│   └── E4. 教学进度与质量管理
└── F. 教师专业发展与学校事务
    ├── F1. 教师教研与备课协作
    ├── F2. 教师培训与能力发展
    ├── F3. 教学成果与工作档案
    └── F4. 学校制度与行政事务
```

## 与学生端的关系

学生端和教师端可以共享以下稳定实体：

```text
student_id
teacher_id
school_id
class_id
course_id
problem_id
knowledge_point_id
source_id
assessment_id
```

但不应共享所有业务状态：

- 学生端保存自己的作答、错题和学习计划；
- 教师端保存班级成绩、教学计划和干预记录；
- 教师可以读取授权范围内的学生数据；
- 学生不能修改教师评分、题库发布状态或班级统计。

推荐教师端优先实现：

```text
A1 教学资源搜索与核验
A2 题目、试卷与题库管理
B1 课程目标与教学设计
C2 自动批改与过程评价
C3 测验组卷与发布
D1 班级学情分析
D2 知识点与错误诊断
E3 家校沟通
```

这些主题最容易形成真实的“检索—设计—评价—诊断—干预”工具链，也最适合按照 AgentWorld 的数据库、工具集、依赖图和可执行任务方式构建。

> 将这份设想按照学生端的环境主题设计.md 写一份教师端的
>
> User context
>
> Attachments:
> - 学生端环境主题设计.md: `./AgentWorld2/学生端环境主题设计.md`

<details><summary>1 previous message</summary>

> 我会参照学生端文档的写法，创建教师端主题设计文档：包含六个二级主题、三级环境总览、每个环境的典型需求与数据库核心内容，以及统一建库和权限原则。
> </details>

已创建教师端环境设计文档：

[教师端环境主题设计.md](./AgentWorld2/教师端环境主题设计.md)

文档内容包括：

- 教师端一级主题“教师教育助手”；
- 六个二级主题；
- 24 个三级环境；
- 每个三级环境的典型教师需求；
- 每个环境对应的数据库内容；
- 教师端统一建库和工具集原则；
- 教师、学生、家长数据的权限与隐私约束；
- 资源检索、备课、作业、测评、学情分析、班级管理和教师发展等完整流程。

> 按照这个设想构建TeacherAssistant的框架（文件目录）

<details><summary>1 previous message</summary>

> 我会依据教师端文档创建 `envs/TeacherAssistant/A-F/` 六个二级目录，并为 24 个三级环境建立统一的 `raw/normalized/indexes/fixtures/tests` 子目录。
> </details>

已按教师端设计完成框架搭建。

目录结构：

```text
AgentWorld2/envs/
├── StudentAssistant/
│   ├── A/
│   ├── B/
│   ├── C/
│   ├── D/
│   ├── E/
│   └── F/
└── TeacherAssistant/
    ├── A/
    │   ├── A1_teacher_resource_search/
    │   ├── A2_item_bank_and_paper_management/
    │   ├── A3_lesson_material_generation/
    │   └── A4_multimodal_teaching_resource_processing/
    ├── B/
    ├── C/
    ├── D/
    ├── E/
    └── F/
```

教师端共创建 24 个三级环境，每个环境包含：

```text
raw/
normalized/
indexes/
fixtures/
tests/
```

同时更新：

- [environment_manifest.json](./AgentWorld2/envs/environment_manifest.json)
  - 环境总数更新为 49；
  - 增加教师端 24 个环境 ID；
  - 增加教师端六个二级主题映射。
- [README.md](./AgentWorld2/README.md)
  - 更新教师端目录说明。

> 为什么学生端的结构和教师端不同
>
> User context
>
> Attachments:
> - environment_manifest.json: `./AgentWorld2/envs/environment_manifest.json`

学生端和教师端的顶层结构其实是一致的，都是：

```text
一级主题
└── A-F 二级主题
    └── A1、A2... 三级环境
```

差异主要在以下几方面。

## 1. 面向的用户任务不同

学生端围绕：

```text
理解内容
→ 做练习
→ 完成作业
→ 备考
→ 诊断自己
→ 制定学习计划
```

教师端围绕：

```text
获取资源
→ 备课设计
→ 布置评价
→ 分析班级
→ 管理教学
→ 教师发展
```

因此二级主题名称虽然都采用 A-F，但内部含义不同。

例如：

| 层级 | 学生端               | 教师端                 |
| ---- | -------------------- | ---------------------- |
| A    | 学习内容获取与表达   | 教学内容与资源         |
| B    | 练习、作业与实验     | 备课与课程设计         |
| C    | 考试、升学与学科素养 | 作业、测验与评价       |
| D    | 学习诊断与规划       | 学情分析与教学干预     |
| E    | 学习资料与知识管理   | 班级与教学管理         |
| F    | 综合素养与学校支持   | 教师专业发展与学校事务 |

## 2. 学生端有 25 个三级环境，教师端有 24 个

这是因为当前分类粒度还没有完全对齐：

- 学生端 `F` 下有 5 个三级环境；
- 教师端每个二级主题目前有 4 个三级环境；
- 所以学生端是 `4+4+4+4+4+5=25`；
- 教师端是 `4×6=24`。

学生端多出来的是：

```text
F5 综合实践与成长档案
```

教师端的综合实践内容目前合并在：

```text
F3 教学成果与工作档案
```

如果希望结构严格对称，可以给教师端增加：

```text
F5 综合实践课程与学生成长管理
```

这样教师端也变为 25 个环境。

## 3. 三级环境不应机械一一对应

学生端的：

```text
D2 学习状态诊断
```

对应教师端的：

```text
D1 班级学情分析
D2 知识点与错误诊断
```

因为同一个教育事实，学生和教师的任务不同：

- 学生关注“我哪里不会”；
- 教师关注“全班哪里不会、哪些学生需要干预”。

再例如学生端：

```text
E2 个人知识库与错题管理
```

教师端则对应：

```text
A2 题目、试卷与题库管理
C1 作业布置与收集
C2 自动批改与过程评价
```

学生管理的是个人学习材料，教师管理的是公共题库、作业和评价流程。

## 4. 数据权限不同

即使两个端使用同一个实体，例如 `student_id`、`problem_id` 或 `course_id`，数据库中的可见范围也不同：

### 学生端

```text
自己的作答
自己的成绩
自己的错题
自己的计划
自己的成长档案
```

### 教师端

```text
授权班级的学生数据
班级成绩统计
题库和试卷
作业提交
教学干预记录
家校沟通记录
```

所以不能简单复制同一组环境。工具参数、返回字段、写权限和审计规则都需要分别设计。

## 5. 当前目录结构仍然是统一的

目录框架没有本质差异：

```text
envs/
├── StudentAssistant/
│   ├── A/
│   ├── B/
│   ├── C/
│   ├── D/
│   ├── E/
│   └── F/
└── TeacherAssistant/
    ├── A/
    ├── B/
    ├── C/
    ├── D/
    ├── E/
    └── F/
```

差别只在每个 A-F 目录下的三级主题数量和名称。

## 建议

如果你的目标是便于程序处理、对比和批量生成任务，我建议统一为：

```text
学生端：25 个环境
教师端：25 个环境
```

给教师端补充：

```text
F5_综合实践课程与学生成长管理
```

如果你的目标是忠实表达学生和教师的真实工作流程，则保留当前不完全对称的结构更合理。环境分类的原则应是：

> 角色任务相似才对应，不能为了目录对称而强行合并或拆分。

> 教师端有teacher_second_tier_themes学生端没有

<details><summary>1 previous message</summary>

> 我检查一下 `environment_manifest.json` 的实际字段，确认学生端映射是否缺失；如果确实没有，我会补齐并保持两端字段对称。
> </details>

你发现得对，之前 `environment_manifest.json` 中确实只有：

```json
"teacher_second_tier_themes": {...}
```

学生端的 `student_second_tier_themes` 字段缺失了。现在已经补齐：

```json
"student_second_tier_themes": {
  "A": "A_学习内容获取与表达",
  "B": "B_练习作业与实验",
  "C": "C_考试升学与学科素养",
  "D": "D_学习诊断与规划",
  "E": "E_学习资料与知识管理",
  "F": "F_综合素养与学校支持"
}
```

文件位置：

[environment_manifest.json](./AgentWorld2/envs/environment_manifest.json)

现在学生端和教师端都有各自明确的二级主题映射字段。

> readme也更新一下，同时考虑学生端和教师端，不再是只有学生教育助手环境框架
>
> User context
>
> Attachments:
> - README.md: `./AgentWorld2/README.md`

<details><summary>1 previous message</summary>

> 我会更新 README 的定位、目录树和统计信息，使其明确描述“学生教育助手 + 教师教育助手”双端环境框架。
> </details>

README 已更新为双端教育助手框架：

[README.md](./AgentWorld2/README.md)

现在明确包含：

- `StudentAssistant` 学生教育助手；
- `TeacherAssistant` 教师教育助手；
- 学生端 25 个三级环境；
- 教师端 24 个三级环境；
- 双端共享数据层；
- 学生端和教师端完整目录树；
- 单个环境的统一目录骨架；
- 双端共享实体、权限边界和数据审计原则。

> shared目录是放什么的

`shared/` 是学生端和教师端共同使用的“基础数据与规范层”，不是一个独立的可执行环境。

它主要解决两个问题：

1. 两端需要引用同一批教育实体；
2. 不同环境之间需要保持 ID、来源和数据格式一致。

## 目录用途

```text
shared/
├── raw/
├── normalized/
├── indexes/
├── schemas/
├── provenance/
└── fixtures/
```

### `shared/raw/`

保存公共的原始数据快照，不做大规模修改。

例如：

```text
课程标准 PDF
教材章节 HTML
历年试卷 PDF
题目图片
实验视频
招生章程
学校公开制度
```

这里保留原始格式、文件路径和内容哈希，便于追溯。

### `shared/normalized/`

保存学生端和教师端都会引用的规范化实体。

例如：

```text
students.json
teachers.json
schools.json
classes.json
courses.json
subjects.json
knowledge_points.json
problems.json
sources.json
exam_papers.json
```

示例：

```json
{
  "problem_id": "problem_000123",
  "subject": "math",
  "grade_band": "high_school",
  "topic": "analytic_geometry",
  "source_id": "source_exam_sh_2026_001"
}
```

学生端可以用这个题目做练习，教师端可以用同一个题目组卷或批改。

### `shared/indexes/`

保存用于查询的公共索引。

例如：

```text
problem_fulltext_index.json
knowledge_point_index.json
source_index.json
course_index.json
problem_similarity_index.json
```

索引不是新的事实数据，而是为了更快搜索、过滤和关联。

### `shared/schemas/`

保存公共数据格式约束，例如 JSON Schema：

```text
student.schema.json
problem.schema.json
course.schema.json
knowledge_point.schema.json
source.schema.json
```

作用是保证不同环境使用相同字段和类型。例如所有环境中的 `problem_id` 都必须是字符串，不能一个环境用整数、另一个环境用字符串。

### `shared/provenance/`

保存数据来源和版本信息。

例如：

```json
{
  "source_id": "source_exam_sh_2026_001",
  "publisher": "上海市教育考试院",
  "source_type": "official_exam",
  "snapshot_path": "raw/exam_2026_shanghai_math.pdf",
  "content_hash": "sha256:...",
  "fetched_at": "2026-08-01T00:00:00Z",
  "license": "public",
  "verification_status": "verified"
}
```

它用于回答：

- 数据来自哪里；
- 是否官方来源；
- 哪个时间版本；
- 文件是否被修改；
- 是否通过人工核验；
- 是否允许使用。

### `shared/fixtures/`

保存跨环境共用的最小测试数据。

例如：

```text
student_demo.json
teacher_demo.json
class_demo.json
problem_demo.json
knowledge_graph_demo.json
```

这些数据用于：

- 初始化测试环境；
- 验证学生端和教师端 ID 能否正确关联；
- 测试权限；
- 测试跨环境数据契约；
- 保证执行结果可复现。

## 什么不应该放入 `shared/`

环境专属的业务状态不要放进 `shared/`。

例如：

- 学生端的错题本；
- 学生端学习计划；
- 教师端成绩；
- 教师端评分记录；
- 课堂互动会话；
- 教师干预记录；
- 图片识别运行记录；
- 家校沟通记录。

这些应该放在对应三级环境目录中：

```text
envs/StudentAssistant/D/D2_learning_diagnosis/
envs/TeacherAssistant/C/C2_automated_grading_and_process_assessment/
```

## 共享数据和环境数据的区别

可以简单理解为：

```text
shared/
    谁、什么题、哪个课程、哪个知识点、来自哪里

具体环境/
    学生做了什么、教师改了什么、当前流程进行到哪一步
```

例如同一道题：

```text
shared/normalized/problems.json
```

保存题目本身：

```json
{
  "problem_id": "p001",
  "statement": "...",
  "subject": "math",
  "topic": "analytic_geometry"
}
```

学生端自适应练习保存：

```json
{
  "student_id": "s001",
  "problem_id": "p001",
  "attempt_id": "a001",
  "answer": "...",
  "is_correct": false
}
```

教师端批改环境保存：

```json
{
  "teacher_id": "t001",
  "problem_id": "p001",
  "student_id": "s001",
  "score": 8,
  "feedback": "..."
}
```

题目是共享实体，学生作答和教师评分是不同环境的业务状态。

## 与 AgentWorld 的关系

论文中的环境是：

```text
环境 = 数据库 D + 工具集 F
```

在当前双端设计中，可以把数据分为：

```text
公共数据层 shared/
+
环境专属数据库 envs/.../<三级环境>/
```

其中：

- `shared/` 提供稳定、可复用的基础数据；
- 每个三级环境拥有自己的状态数据库或文件；
- 工具只能通过明确接口访问数据；
- 任务执行时使用固定离线快照；
- 共享实体通过稳定 ID 关联，而不是直接共享全部数据库状态。

因此，`shared/` 的本质是：

> 学生端和教师端共同依赖的数据契约、来源底座和测试基线。

> 现在开始设想学生端环境如何构建，先考虑A1，可以怎样构建数据库

A1“多模态学习理解”应首先被设计成一个“输入理解环境”，而不是直接做成“万能解题环境”。

它的核心职责是：

```text
接收学习材料
→ 检测内容区域
→ 识别文字、公式、图形、表格和语音
→ 处理低置信度结果
→ 形成结构化学习对象
→ 为后续讲解、练习或诊断提供可靠输入
```

建议环境目录为：

```text
envs/StudentAssistant/A/A1_multimodal_learning_understanding/
├── raw/
├── normalized/
├── indexes/
├── fixtures/
├── tests/
├── schema.sql
├── seed.py
├── env.py
├── tools.py
├── dependencies.json
└── README.md
```

## 一、数据库总体结构

A1 可以采用：

```text
静态教育数据
+
用户上传产物
+
多模态识别结果
+
人工确认状态
+
结构化学习对象
```

对应数据库分为五组：

```text
1. sources                  来源和原始文件
2. artifacts                学生上传的图片、PDF、音频
3. recognition              OCR、公式、表格、图形、语音识别
4. learning_objects         识别后形成的题目、教材页、实验或图表
5. sessions/audit           识别会话、确认记录和审计
```

## 二、原始数据目录

### `raw/`

保存固定的真实世界数据快照：

```text
raw/
├── exam_images/
│   ├── shanghai_math_2025_q12.png
│   └── shanghai_math_2026_q18.png
├── textbook_pages/
│   ├── physics_grade8_page_32.jpg
│   └── chinese_grade4_page_78.jpg
├── handwritten_attempts/
│   ├── student_attempt_001.jpg
│   └── student_attempt_002.jpg
├── experiment_diagrams/
│   ├── circuit_001.png
│   └── biology_cell_002.jpg
├── charts_and_maps/
│   ├── geography_map_001.png
│   └── history_timeline_002.png
└── audio/
    ├── pinyin_reading_001.wav
    └── english_reading_001.wav
```

这里应保留：

- 原始文件；
- 原始文件名；
- 来源；
- 内容哈希；
- 文件类型；
- 图像宽高或音频时长；
- 版权状态；
- 是否允许评测使用。

不要只保存 OCR 后的文字，否则无法测试识别过程。

## 三、来源表 `sources`

无论数据来自考试院、教材还是学生上传，都应该记录来源。

```sql
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    publisher TEXT,
    title TEXT,
    uri TEXT,
    snapshot_path TEXT,
    content_hash TEXT NOT NULL,
    published_at TEXT,
    fetched_at TEXT,
    license TEXT,
    verification_status TEXT NOT NULL
);
```

建议的 `source_type`：

```text
official_exam
textbook
school_material
public_question_bank
teacher_upload
student_upload
synthetic_fixture
```

示例：

```json
{
  "source_id": "src_shanghai_exam_2026",
  "source_type": "official_exam",
  "publisher": "上海市教育考试院",
  "title": "2026年上海高考数学试卷",
  "snapshot_path": "raw/exam_images/shanghai_math_2026_q18.png",
  "content_hash": "sha256:...",
  "verification_status": "verified"
}
```

## 四、上传产物表 `artifacts`

学生上传的图片或文件是 A1 的入口。

```sql
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_id TEXT REFERENCES sources(source_id),
    media_type TEXT NOT NULL,
    file_name TEXT,
    storage_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER,
    width INTEGER,
    height INTEGER,
    duration_ms INTEGER,
    uploaded_at TEXT NOT NULL,
    status TEXT NOT NULL
);
```

`media_type` 可以是：

```text
image
pdf
audio
video
text
```

`status` 可以是：

```text
uploaded
processing
recognized
needs_confirmation
confirmed
failed
archived
```

示例：

```json
{
  "artifact_id": "art_0001",
  "user_id": "stu_001",
  "media_type": "image",
  "file_name": "math_question.jpg",
  "storage_path": "raw/handwritten_attempts/student_attempt_001.jpg",
  "content_hash": "sha256:abc...",
  "width": 2048,
  "height": 1536,
  "uploaded_at": "2026-09-04T10:00:00Z",
  "status": "uploaded"
}
```

## 五、内容区域表 `artifact_regions`

一张图片可能包含多道题、题干、图形和学生答案，需要先拆分区域。

```sql
CREATE TABLE artifact_regions (
    region_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    region_index INTEGER NOT NULL,
    region_type TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    detection_confidence REAL NOT NULL,
    detection_method TEXT NOT NULL,
    status TEXT NOT NULL
);
```

`region_type` 示例：

```text
question
student_attempt
diagram
table
answer_choice
textbook_paragraph
unknown
```

示例：

```json
{
  "region_id": "reg_0001",
  "artifact_id": "art_0001",
  "region_index": 1,
  "region_type": "question",
  "x": 120,
  "y": 80,
  "width": 1800,
  "height": 650,
  "detection_confidence": 0.96,
  "status": "detected"
}
```

这可以支持以下真实场景：

- 一张图片中有多道题；
- 题目和学生作答同时出现；
- 图片中同时有文字和几何图；
- 系统无法确定某个区域是什么，需要确认。

## 六、识别运行表 `recognition_runs`

同一张图片可能经过多个 OCR 或视觉模型处理，因此不能只在区域表里保存一个结果。

```sql
CREATE TABLE recognition_runs (
    recognition_id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL REFERENCES artifact_regions(region_id),
    modality TEXT NOT NULL,
    engine TEXT NOT NULL,
    engine_version TEXT,
    raw_output TEXT NOT NULL,
    normalized_output TEXT,
    confidence REAL NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL
);
```

`modality` 示例：

```text
ocr
formula
table
diagram
speech_to_text
layout
```

示例：

```json
{
  "recognition_id": "rec_0001",
  "region_id": "reg_0001",
  "modality": "formula",
  "engine": "math_ocr_fixture",
  "engine_version": "1.0",
  "raw_output": "x2/a2+y2/b2=1",
  "normalized_output": "\\frac{x^2}{a^2}+\\frac{y^2}{b^2}=1",
  "confidence": 0.82,
  "status": "needs_confirmation"
}
```

建议同时保存：

- 原始识别结果；
- 规范化文本；
- LaTeX；
- JSON 结构；
- 置信度；
- 模型版本；
- 识别时间；
- 错误信息。

不要覆盖旧识别结果，否则无法评估识别修正过程。

## 七、识别修正表 `recognition_corrections`

低置信度时，学生或教师需要修正结果。

```sql
CREATE TABLE recognition_corrections (
    correction_id TEXT PRIMARY KEY,
    recognition_id TEXT NOT NULL REFERENCES recognition_runs(recognition_id),
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT NOT NULL,
    corrected_by TEXT NOT NULL,
    reason TEXT,
    corrected_at TEXT NOT NULL
);
```

示例：

```json
{
  "correction_id": "cor_0001",
  "recognition_id": "rec_0001",
  "field_name": "normalized_output",
  "old_value": "\\frac{x^2}{a^2}+\\frac{y^2}{b^2}=1",
  "new_value": "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
  "corrected_by": "stu_001",
  "reason": "图片中的分母被识别错误"
}
```

这一步是 A1 的关键，因为真实系统不能假定 OCR 永远正确。

## 八、结构化学习对象表 `learning_objects`

识别结果确认后，需要转成可供后续环境使用的结构化对象。

```sql
CREATE TABLE learning_objects (
    object_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    object_type TEXT NOT NULL,
    subject TEXT,
    grade_band TEXT,
    curriculum TEXT,
    title TEXT,
    statement TEXT,
    normalized_content TEXT,
    confirmation_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

`object_type` 可以是：

```text
question
textbook_excerpt
experiment_setup
chart
map
student_attempt
reading_text
writing_prompt
```

例如一道数学题：

```json
{
  "object_id": "obj_0001",
  "artifact_id": "art_0001",
  "object_type": "question",
  "subject": "math",
  "grade_band": "high_school",
  "curriculum": "shanghai",
  "statement": "已知椭圆...",
  "normalized_content": "...",
  "confirmation_status": "confirmed"
}
```

这里的 `learning_objects` 是 A1 的输出，不等于完整题库。若后续已经匹配到公共题库，可以关联共享的 `problem_id`。

## 九、题目匹配表 `object_matches`

图片识别出的题目可能：

1. 与共享题库中的题目完全相同；
2. 与某道题高度相似；
3. 是全新的临时题目；
4. 识别信息不足，无法匹配。

因此需要单独记录匹配结果：

```sql
CREATE TABLE object_matches (
    match_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES learning_objects(object_id),
    problem_id TEXT,
    match_type TEXT NOT NULL,
    similarity_score REAL,
    matched_by TEXT NOT NULL,
    status TEXT NOT NULL
);
```

`match_type`：

```text
exact
similar
variant
none
```

示例：

```json
{
  "match_id": "match_0001",
  "object_id": "obj_0001",
  "problem_id": "shared_problem_883",
  "match_type": "similar",
  "similarity_score": 0.91,
  "matched_by": "text_formula_index",
  "status": "candidate"
}
```

A1 不应直接把相似题当成同一道题，必须保存匹配置信度和确认状态。

## 十、识别会话和确认表

### 会话表

```sql
CREATE TABLE recognition_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    closed_at TEXT
);
```

`purpose` 示例：

```text
solve_question
understand_textbook
analyze_experiment
read_chart
read_aloud
```

### 确认记录

```sql
CREATE TABLE confirmation_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES recognition_sessions(session_id),
    recognition_id TEXT NOT NULL REFERENCES recognition_runs(recognition_id),
    decision TEXT NOT NULL,
    selected_value TEXT,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

`decision`：

```text
accepted
corrected
rejected
skipped
```

这样可以验证 Agent 是否在识别置信度不足时正确请求确认，而不是直接进入解题。

## 十一、规范化目录

```text
normalized/
├── artifacts.json
├── artifact_regions.json
├── recognition_runs.json
├── recognition_corrections.json
├── learning_objects.json
├── object_matches.json
└── recognition_sessions.json
```

`normalized/` 中的文件应该是工具直接读取和修改的业务数据，而 `raw/` 只保存原始素材。

## 十二、索引目录

```text
indexes/
├── object_text_index.json
├── formula_index.json
├── problem_similarity_index.json
├── source_index.json
└── knowledge_point_index.json
```

建议建立：

### 文本索引

用于：

```text
题干搜索
教材文字搜索
OCR 内容检索
```

### 公式索引

用于：

```text
按 LaTeX 结构匹配数学题
```

### 图形/图表索引

用于：

```text
几何图形相似匹配
实验装置相似匹配
```

### 题目相似度索引

用于区分：

```text
完全相同题
数字不同的变式题
知识点相同但结构不同的题
```

## 十三、建议的最小数据库表

A1 第一版不需要实现所有复杂功能，最小可用版本可以只有：

```text
sources
artifacts
artifact_regions
recognition_runs
recognition_corrections
learning_objects
object_matches
recognition_sessions
audit_log
```

最小流程为：

```text
upload_artifact
→ detect_regions
→ recognize_content
→ get_recognition_result
→ confirm_or_correct
→ create_learning_object
→ match_existing_problem
```

## 十四、真实数据应包含哪些样本

为了覆盖中国学生真实使用场景，建议准备以下固定样本集：

### 清晰印刷题

```text
小学数学
初中几何
高中解析几何
物理计算题
化学方程式
英语阅读题
```

### 手写题

```text
数字潦草
分数线不清晰
根号范围不清晰
上下标混淆
步骤交叉书写
```

### 复杂版面

```text
一图多题
题干和答案混在一起
题目跨页
题目旁有批注
图片旋转或裁剪
表格和公式混排
```

### 图形与实验

```text
几何图形
电路图
生物结构图
化学实验装置
地理地图
统计图表
历史时间轴
```

### 失败和不确定样本

```text
图片模糊
遮挡关键条件
光线过暗
题目只上传一半
OCR 结果存在两个候选
图像与学生文字描述矛盾
```

每个样本都应有人工确认的 ground truth：

```json
{
  "artifact_id": "art_0001",
  "expected_region_count": 2,
  "expected_object_type": "question",
  "expected_text": "...",
  "expected_latex": "...",
  "minimum_confidence": 0.85,
  "requires_confirmation": true
}
```

## 十五、A1 的工具集建议

第一版可以设计以下工具：

```text
upload_artifact
get_artifact_metadata
detect_content_regions
get_region
recognize_content
get_recognition_result
request_user_confirmation
correct_recognition
create_learning_object
search_matching_problems
confirm_problem_match
read_source_provenance
read_audit_log
```

工具依赖关系：

```text
upload_artifact
    → detect_content_regions
    → recognize_content
    → get_recognition_result
    → correct_recognition / request_user_confirmation
    → create_learning_object
    → search_matching_problems
    → confirm_problem_match
```

重要拒绝条件：

- 图片不存在，不能识别；
- 区域不存在，不能识别；
- 识别结果低置信度时不能直接确认；
- 未确认公式时不能进入高风险解题流程；
- 相似题不能自动当成同题；
- 未完成来源核验时不能声称“官方答案”。

## 十六、A1 不应存什么

以下内容不建议直接写入 A1 的事实数据库：

- “学生已经理解了”；
- “学生能力为 82 分”；
- “这一定是某种误区”；
- “学生适合某种教学法”。

这些需要后续诊断或教学环境根据明确规则生成。A1 主要保存：

```text
学生上传了什么
系统看到了什么
识别结果是什么
置信度多高
学生确认或修改了什么
最终形成了哪个学习对象
```

## 十七、最终建议

A1 的数据库可以概括成：

```text
原始学习材料
    ↓
内容区域
    ↓
多模态识别运行
    ↓
置信度与人工确认
    ↓
结构化学习对象
    ↓
题库/知识点/资源匹配
```

最重要的建模原则是：

1. **保留原始图片和识别结果，不只保存最终文本**；
2. **允许一次上传对应多个区域和多个学习对象**；
3. **允许多次识别和人工修正，不能覆盖历史结果**；
4. **将置信度和确认状态作为真实业务状态**；
5. **将题目匹配与题目解答分开**；
6. **A1 负责可靠地“看懂输入”，后续环境负责讲解、练习和诊断**。

这样构建出来的 A1，既能支持“学生上传一张题目图片请求讲解”，也能支持教材页、实验图、地图、图表、朗读材料等更广泛的真实教育场景。

> ├── raw/
> ├── normalized/
> ├── indexes/
> ├── fixtures/
> ├── tests/
> ├── schema.sql
> ├── seed.py
> ├── env.py
> ├── tools.py
> ├── dependencies.json
> └── README.md
> 这些目录分别对应什么功能

这是一套三级环境的标准工程结构。以 A1 多模态学习理解为例：

```text
A1_multimodal_learning_understanding/
├── raw/
├── normalized/
├── indexes/
├── fixtures/
├── tests/
├── schema.sql
├── seed.py
├── env.py
├── tools.py
├── dependencies.json
└── README.md
```

## 目录和文件功能

### `raw/`

保存真实世界的原始数据，不做结构化改写。

例如：

```text
raw/
├── exam_images/
├── textbook_pages/
├── handwritten_attempts/
├── experiment_diagrams/
└── audio/
```

内容可以是：

- PDF；
- HTML；
- JPG/PNG；
- 音频；
- 视频；
- 原始 CSV/XLSX；
- 网页离线快照。

它回答的是：

> 原始资料从哪里来，原始内容是什么？

不要只保存 OCR 结果，否则无法评估识别过程。

### `normalized/`

保存清洗和规范化后的业务数据。

例如：

```text
normalized/
├── artifacts.json
├── artifact_regions.json
├── recognition_runs.json
├── learning_objects.json
└── object_matches.json
```

例如把图片转成如下结构：

```json
{
  "artifact_id": "art_001",
  "media_type": "image",
  "content_hash": "sha256:...",
  "status": "needs_confirmation"
}
```

它回答的是：

> 环境当前有哪些实体和业务状态？

工具通常主要读取和修改这一层。

### `indexes/`

保存为了快速查询而构建的索引，不是权威事实源。

例如：

```text
indexes/
├── text_index.json
├── formula_index.json
├── similarity_index.json
├── source_index.json
└── knowledge_point_index.json
```

用途包括：

- 按题干搜索；
- 按 LaTeX 公式匹配；
- 搜索相似题；
- 按知识点过滤；
- 按来源检索。

索引丢失后可以从 `normalized/` 重新生成。

### `fixtures/`

保存最小、固定、可复现的测试数据。

例如：

```text
fixtures/
├── clear_question.json
├── blurry_question.json
├── multi_problem_image.json
├── handwritten_formula.json
└── expected_results.json
```

用途：

- 初始化测试环境；
- 验证正常识别；
- 验证模糊图片处理；
- 验证低置信度确认；
- 验证多题拆分；
- 验证错误码。

例如：

```json
{
  "artifact_id": "fixture_blurry_001",
  "requires_confirmation": true,
  "expected_region_count": 2
}
```

### `tests/`

保存自动化测试代码。

例如：

```text
tests/
├── test_upload.py
├── test_region_detection.py
├── test_recognition.py
├── test_confirmation.py
└── test_matching.py
```

测试应验证：

- 工具能否正常运行；
- 返回结构是否稳定；
- 非法参数是否返回正确错误码；
- 状态迁移是否符合顺序；
- 低置信度是否强制确认；
- 相似题是否不会被错误认定为同题；
- 读工具是否意外修改状态。

### `schema.sql`

定义数据库结构。

例如：

```sql
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    media_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL
);
```

它定义：

- 表；
- 字段；
- 主键；
- 外键；
- 唯一约束；
- 枚举值；
- 索引；
- 基础完整性规则。

`schema.sql` 只描述结构，不负责填充具体种子数据。

### `seed.py`

初始化数据库中的种子数据。

例如：

```python
def seed(conn):
    conn.execute(
        "INSERT INTO artifacts (...) VALUES (...)",
        (...)
    )
    conn.commit()
```

它负责：

- 插入固定题目；
- 插入识别样例；
- 插入来源数据；
- 插入标准答案；
- 插入测试用户；
- 初始化状态。

`seed.py` 应保证：

```text
同样的 schema + 同样的 seed
→ 得到完全一致的初始状态
```

### `env.py`

环境的入口和装配文件。

它通常负责：

- 创建数据库连接；
- 加载 `schema.sql`；
- 执行 `seed.py`；
- 注册工具；
- 定义环境名称；
- 暴露环境构建函数；
- 挂载工具测试。

示意：

```python
def build(db_path=":memory:"):
    conn = connect("schema.sql", db_path)
    seed(conn)

    return Env(
        theme="multimodal_learning_understanding",
        conn=conn,
        tools={
            "upload_artifact": ToolSpec(...),
            "recognize_content": ToolSpec(...),
            "confirm_recognition": ToolSpec(...),
        },
    )
```

可以把它理解为：

> 这个三级环境如何被启动和使用。

### `tools.py`

实现环境对 Agent 暴露的工具。

例如：

```python
def upload_artifact(conn, user_id, file_path, media_type):
    ...
```

工具应包括：

- 参数校验；
- 权限校验；
- 数据库读写；
- 稳定错误码；
- 返回结构；
- 审计记录；
- 前置条件判断。

不建议只提供：

```python
read_database()
write_database()
```

而应提供业务工具：

```text
upload_artifact
detect_content_regions
recognize_content
confirm_recognition
search_matching_problems
```

### `dependencies.json`

描述工具之间的依赖关系，用于任务合成。

例如：

```json
{
  "edges": [
    {
      "from": "upload_artifact",
      "to": "detect_content_regions",
      "type": "strong",
      "weight": 3
    },
    {
      "from": "detect_content_regions",
      "to": "recognize_content",
      "type": "strong",
      "weight": 3
    },
    {
      "from": "recognize_content",
      "to": "confirm_recognition",
      "type": "weak",
      "weight": 2
    },
    {
      "from": "get_recognition_result",
      "to": "search_matching_problems",
      "type": "weak",
      "weight": 2
    }
  ]
}
```

三类依赖：

- `strong`：后一个工具必须使用前一个工具的输出；
- `weak`：可以使用前一个输出，也可以从数据库或常量获得；
- `independent`：两个工具没有参数依赖，仅用于保证图连通。

它回答的是：

> Agent 应该以什么逻辑顺序调用工具？

### `README.md`

说明该三级环境的设计和使用方式。

应包含：

- 环境名称；
- 真实场景；
- 目录说明；
- 数据来源；
- 数据库实体；
- 工具列表；
- 工具依赖；
- 状态机；
- 任务示例；
- 评测指标；
- 隐私与权限；
- 启动和测试方式。

例如 A1 的 README 可以说明：

```text
学生上传图片
→ 检测题目区域
→ OCR/公式识别
→ 低置信度确认
→ 形成结构化对象
→ 匹配题库
```

## 各部分之间的关系

可以用这个流程理解：

```text
raw/
  原始图片、PDF、音频
       ↓
seed.py
  导入固定样例
       ↓
schema.sql
  约束数据库结构
       ↓
normalized/
  保存实体和状态
       ↓
indexes/
  提供快速搜索
       ↓
tools.py
  对 Agent 暴露业务操作
       ↓
env.py
  装配成可运行环境
       ↓
dependencies.json
  描述工具调用依赖
       ↓
tests/
  验证工具和状态迁移
```

`fixtures/` 则为上述测试提供稳定输入。

## 最核心的区分

| 部分                | 作用                 |
| ------------------- | -------------------- |
| `raw/`              | 原始资料             |
| `normalized/`       | 规范化事实和业务状态 |
| `indexes/`          | 查询加速结构         |
| `fixtures/`         | 固定测试样例         |
| `tests/`            | 自动化验证           |
| `schema.sql`        | 数据库结构           |
| `seed.py`           | 初始数据             |
| `env.py`            | 环境装配             |
| `tools.py`          | Agent 可调用能力     |
| `dependencies.json` | 工具依赖图           |
| `README.md`         | 环境说明文档         |

需要注意的是，`raw/`、`normalized/` 和 `indexes/` 是数据层；`schema.sql`、`seed.py` 和 `env.py` 是运行层；`tools.py` 和 `dependencies.json` 是 Agent 交互层；`tests/` 和 `README.md` 是验证与文档层。

> 那真实场景的 学生上传一张题目图片请求解答  这样的场景可以怎样在这个环境里 实现，用任务描述告诉我

可以把这个真实场景设计成 A1 环境中的一个“多模态识别—题目匹配—解答准备”任务。

环境：

```text
StudentAssistant/A/A1_multimodal_learning_understanding
```

任务不应直接写成：

```text
调用 upload_artifact，然后调用 recognize_content
```

而应像真实用户需求一样描述，不能泄露工具名和数据库表名。

## 一、用户侧任务描述

```text
我拍了一张数学题照片，请帮我讲解。

图片中是一道高中数学解析几何题，照片略微倾斜，题干和一个椭圆示意图都在图片中。请先确认你正确识别了题目和公式。如果图片中的内容不清楚，请指出具体位置并让我确认。确认后，找到题目的标准解法，说明解题思路、关键步骤和最终答案。不要只给最终结果。
```

这是给 Agent 的任务描述。它不包含：

- 工具名称；
- 数据库表名；
- 内部 `artifact_id`；
- 具体调用顺序；
- “必须调用哪些函数”等技术细节。

## 二、环境初始状态

任务执行前，环境中预置一张图片：

```text
fixtures/artifacts/math_analytic_geometry_001.jpg
```

图片内容类似：

```text
已知椭圆 C: x²/4 + y²/9 = 1，
过点 P(1, 2) 作椭圆的两条切线，求切线方程。
```

图片特征：

- 图片存在；
- 有轻微旋转；
- 包含题干和椭圆图形；
- 分式和上下标可以识别；
- 公式 OCR 的初始置信度为 0.82；
- 低于自动确认阈值 0.90；
- 因此必须请求用户确认公式。

环境初始数据库中可以有：

```json
{
  "artifact_id": "art_fixture_001",
  "user_id": "stu_demo_001",
  "media_type": "image",
  "storage_path": "fixtures/artifacts/math_analytic_geometry_001.jpg",
  "status": "uploaded"
}
```

## 三、期望的工具调用轨迹

内部合法轨迹可以是：

```text
1. 读取上传图片的元数据
2. 检测图片中的内容区域
3. 识别题干文字
4. 识别数学公式和几何图形
5. 检查识别置信度
6. 发现公式置信度不足
7. 请求学生确认或修正公式
8. 根据确认结果创建结构化题目对象
9. 搜索题库中的同题或相似题
10. 核验题目匹配结果
11. 读取标准答案和分步解法
12. 生成面向学生的解题讲解
```

对应的业务工具可以设计为：

```text
get_artifact_metadata
detect_content_regions
recognize_content
get_recognition_result
request_user_confirmation
correct_recognition
create_learning_object
search_matching_problems
confirm_problem_match
get_solution
verify_solution
```

## 四、关键中间状态

### 状态 1：图片已上传

```json
{
  "artifact_id": "art_fixture_001",
  "status": "uploaded",
  "media_type": "image"
}
```

### 状态 2：识别出两个区域

```json
{
  "regions": [
    {
      "region_id": "reg_001",
      "region_type": "question",
      "confidence": 0.96
    },
    {
      "region_id": "reg_002",
      "region_type": "diagram",
      "confidence": 0.94
    }
  ]
}
```

### 状态 3：公式识别置信度不足

```json
{
  "recognition_id": "rec_001",
  "modality": "formula",
  "raw_output": "x2/4 + y2/9 = 1",
  "normalized_output": "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
  "confidence": 0.82,
  "status": "needs_confirmation"
}
```

Agent 应向学生询问：

```text
我识别到椭圆方程可能是：

x²/4 + y²/9 = 1

但分母位置的清晰度不足。请确认是否正确？
```

如果学生确认，状态变成：

```json
{
  "status": "confirmed",
  "confirmed_by": "stu_demo_001"
}
```

如果学生说分母是 16 和 9，则写入修正记录，不能覆盖原始识别结果。

### 状态 4：形成结构化题目

```json
{
  "object_id": "obj_001",
  "object_type": "question",
  "subject": "math",
  "grade_band": "high_school",
  "topic": "analytic_geometry",
  "statement": "已知椭圆 ...",
  "confirmation_status": "confirmed"
}
```

### 状态 5：题目匹配

```json
{
  "match_type": "exact",
  "problem_id": "problem_sh_math_analytic_023",
  "similarity_score": 0.97,
  "status": "confirmed"
}
```

如果只有相似题：

```json
{
  "match_type": "similar",
  "similarity_score": 0.84,
  "status": "candidate"
}
```

此时 Agent 不能声称“这是原题”，只能说明“找到一道相似题”。

### 状态 6：解答验证

```json
{
  "problem_id": "problem_sh_math_analytic_023",
  "final_answer": "...",
  "verification_status": "verified",
  "verification_methods": [
    "symbolic_check",
    "substitution_check"
  ]
}
```

## 五、最终面向学生的回复

任务完成后，Agent 应输出类似：

```text
我先确认一下图片内容：

题目是：已知椭圆 x²/4 + y²/9 = 1，过点 P(1,2) 作椭圆的两条切线，求切线方程。

解题思路：

1. 设过 P(1,2) 的直线为 y - 2 = k(x - 1)。
2. 将直线代入椭圆方程。
3. 由于直线与椭圆相切，所得关于 x 的二次方程判别式应为 0。
4. 解出 k 的两个值。
5. 将两个斜率分别代回直线方程，得到两条切线。

关键是使用“相切时判别式为 0”这一条件，而不是只把点 P 代入椭圆方程。

最终答案为：……

如果你愿意，我还可以继续把判别式展开过程逐行写出来。
```

注意：如果用户没有要求只看答案，A1 可以输出完整讲解；如果用户要求“只给提示”，则应将后续过程转交或扩展到渐进式辅导逻辑。

## 六、任务评测标准

这个任务可以设置以下 rubric：

### 1. 输入识别

- 是否找到正确的题目区域；
- 是否识别出题干、公式和图形；
- 是否保留原始识别结果。

### 2. 不确定性处理

- 是否发现公式置信度低于阈值；
- 是否在确认前停止后续匹配；
- 是否指出具体不确定位置；
- 是否正确保存学生确认或修正。

### 3. 题目匹配

- 是否正确区分同题、相似题和无法匹配；
- 是否引用正确的 `problem_id`；
- 是否避免把相似题误说成原题。

### 4. 解答可靠性

- 是否读取标准解；
- 是否进行符号或数值验证；
- 是否正确给出最终答案；
- 是否说明关键步骤，而非只返回结果。

### 5. 对话质量

- 是否使用适合高中生的表达；
- 是否没有暴露内部数据库或工具名称；
- 是否明确说明识别不确定性；
- 是否根据学生需求选择完整解答或提示模式。

## 七、可以生成的负样本

为了符合 AgentWorld 的任务合成方式，还可以在合法任务上注入错误决策：

### 负样本 1：跳过确认

图片公式置信度为 0.82，但 Agent 直接搜索题库并回答。

预期错误：

```text
prerequisite_not_met
recognition_confirmation_required
```

### 负样本 2：误认相似题

搜索结果相似度只有 0.84，却直接声称找到了原题。

预期错误：

```text
match_not_verified
```

### 负样本 3：识别失败后继续解题

OCR 结果为空或公式缺失，Agent 仍然生成答案。

预期错误：

```text
insufficient_recognition
```

### 负样本 4：只看最终答案不做验证

Agent 直接取数据库中的答案，不执行任何校验。

这类任务可以在 rubric 中扣除：

```text
solution_verification_missing
```

## 八、A1 环境中应保持的边界

这个场景属于 A1，A1 主要负责：

```text
图片接收
→ 内容识别
→ 置信度管理
→ 用户确认
→ 结构化题目
→ 题库匹配
→ 解答输入准备
```

如果任务进一步要求：

- 分析学生自己的错误步骤；
- 判断具体误区；
- 多轮逐级提示；
- 记录学生是否掌握；

则可以在 A1 中扩展工具，或者单独放到：

```text
D1 即时学习反馈
B2 自适应练习
E2 个人知识库与错题管理
```

但为了遵守 AgentWorld 的单环境任务规则，最初版本可以将“识别、匹配、解答和一次性讲解”全部放在 A1 内，通过一个完整、可验证的任务轨迹实现。

> 在我构建的环境下， 学生提供的图片是不是应该是题库里有的，这样才能保证可复现性和确定性，也就是所有真实场景的任务在我这个项目里都是基于 构建的数据库来生成的

是的。**在 AgentWorld 这类需要可执行验证和稳定奖励的环境中，学生提供的图片最好来自环境预先构建的数据集，而不是运行时接收任意真实图片。**

但需要区分：

```text
真实场景来源
≠
评测时实时接收任意真实输入
```

推荐采用“真实素材离线化”的方式。

## 推荐流程

```text
真实教育场景
→ 收集真实题目图片
→ 固定离线快照
→ 构建数据库和索引
→ 设计学生任务
→ Agent 调用工具执行
→ 根据固定状态验证结果
```

例如：

```text
raw/
└── math_problem_001.jpg

normalized/
└── artifacts.json

fixtures/
└── task_multimodal_001.json
```

任务中可以写：

> 学生上传了一张高中解析几何题图片，请识别题目并提供讲解。

环境在初始状态中已经预置：

```json
{
  "artifact_id": "art_001",
  "storage_path": "raw/math_problem_001.jpg",
  "content_hash": "sha256:...",
  "status": "uploaded"
}
```

Agent 不需要真正从外部上传文件，而是通过工具获得这个固定产物并完成识别流程。

## 为什么需要预置图片

### 1. 保证结果确定

如果每次图片都不同：

- OCR 结果会变化；
- 题目匹配结果会变化；
- 模型可能出现不同解释；
- 最终答案无法稳定验证。

预置图片可以保证：

```text
同一初始数据库
+ 同一任务
+ 同一工具调用
→ 相同状态和结果
```

### 2. 能够构建 ground truth

每张图片可以预先标注：

```json
{
  "artifact_id": "art_001",
  "expected_region_count": 1,
  "expected_text": "...",
  "expected_latex": "...",
  "expected_problem_id": "problem_001",
  "requires_confirmation": true
}
```

这样可以验证：

- 是否正确检测区域；
- 是否正确识别公式；
- 是否发现低置信度；
- 是否请求学生确认；
- 是否匹配到正确题目；
- 是否调用标准解；
- 是否完成答案验证。

### 3. 能够生成工具依赖图和任务

论文的任务是基于数据库和工具集生成的。对于 A1，可以先有固定数据库，再定义合法工具链：

```text
get_artifact_metadata
→ detect_content_regions
→ recognize_content
→ get_recognition_result
→ request_confirmation
→ correct_recognition
→ create_learning_object
→ search_matching_problems
→ confirm_problem_match
→ get_solution
→ verify_solution
```

然后在这条链路上生成自然语言任务。

## 但不能把图片全部限制为“题库已有题目”

更准确的做法是：

```text
图片必须来自固定数据集，
但不一定都能在题库中找到完全相同的题目。
```

建议分成四类：

### 1. 精确匹配样本

图片中的题目在题库中有对应记录：

```text
match_type = exact
```

用于测试完整的：

```text
图片识别 → 题目匹配 → 标准解答
```

### 2. 相似题样本

图片题目与题库中某题相似但并非同题：

```text
match_type = similar
```

用于测试 Agent 是否会区分：

```text
同题
vs
相似题
```

不能把相似题直接当作原题答案。

### 3. 新题/临时题样本

图片题目在题库中不存在，但识别内容有人工标注的标准答案：

```text
match_type = none
object_type = transient_question
```

用于测试：

- 创建临时学习对象；
- 不声称“题库中已有原题”；
- 仍然可以使用标准解或验证器讲解。

### 4. 识别失败样本

图片来自固定数据集，但故意包含：

- 模糊；
- 遮挡；
- 裁剪；
- 公式歧义；
- 一张图多道题；
- 图像与文字描述冲突。

用于测试：

```text
低置信度处理
→ 请求确认
→ 识别修正
→ 必要时拒绝继续
```

## 数据库建议

A1 至少需要保留四种关联：

```text
artifacts
    原始图片

recognition_runs
    OCR/公式/图形识别结果

learning_objects
    识别后的题目、教材页或实验对象

problem_matches
    与公共题库的精确/相似/无匹配关系
```

其中：

```text
图片是输入产物
题库题目是规范化知识实体
识别对象是中间状态
匹配关系是判断结果
```

不要把图片直接等同于题库题目。

## 任务生成时的两种模式

### 模式一：预置状态任务

初始状态已有上传图片：

```text
任务：
“请帮我识别并讲解学生上传的图片。”
```

适合 AgentWorld 的工具调用评测，因为 Agent 直接从环境读取固定 artifact。

### 模式二：工具调用模拟上传

任务描述中提供固定素材标识：

```text
任务：
“请处理素材 image_fixture_001，并判断其中的数学题。”
```

Agent 调用：

```text
upload_artifact(source_fixture_id="image_fixture_001")
```

工具只允许从固定 fixture 集合选择素材，不允许任意文件路径或网络 URL。

这种方式更接近真实产品，同时仍然保持确定性。

## 真实场景与评测场景的关系

可以这样理解：

```text
真实世界：
学生随时上传任意图片

你的项目：
从真实世界收集图片，构建固定场景库

评测任务：
从固定场景库抽取一张图片，模拟学生上传

工具执行：
在离线数据库中识别、匹配、验证和记录

评价：
根据预先标注的 ground truth 和状态迁移打分
```

因此，你的项目不是限制真实需求，而是把真实需求转换成：

```text
可复现的离线任务实例
```

## 对其他五个主题同样适用

### `homework_assistance`

作业通知、附件、rubric 和提交状态都来自固定快照。

### `adaptive_practice`

题库、学生历史作答和难度统计都来自固定数据库。

### `exam_preparation`

历年试卷、官方解析、地区和年份元数据都来自固定离线资料。

### `learning_diagnosis`

学生作答、学习记录、成绩和活动轨迹都使用脱敏固定数据。

### `personal_study_planning`

课程表、考试日期、作业截止时间和可用时间都使用固定初始状态。

## 结论

你的理解是正确的：

> 所有真实场景的任务，最终都应基于项目预先构建的数据库和固定数据集生成。

但对于 A1，最好的表述不是：

> 学生提供的图片必须是题库中已有的题目。

而是：

> 学生提供的图片必须来自项目预先构建的固定图片数据集；图片可以对应题库原题、相似题、临时题或识别失败样本。

这样既能保证：

- 可复现；
- 可验证；
- 有确定的 ground truth；
- 支持负样本；
- 覆盖真实多模态异常；

又不会把环境简化成“只要查表返回答案”。

> 那现在按照刚刚设想的目录结构更新A1

<details><summary>2 previous messages</summary>

> 我会把 A1 目录补成可实现的环境骨架：加入数据分层目录说明、数据库 schema、种子脚本、环境入口、工具接口、依赖图和测试样例。
>
> <details><summary>Created 8 files</summary>
>
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/README.md` (+28 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/dependencies.json` (+9 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/env.py` (+6 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/fixtures/README.md` (+3 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/schema.sql` (+75 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/seed.py` (+10 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/tests/README.md` (+3 -0)
> - Wrote `./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/tools.py` (+19 -0)
>
> </details>
> </details>

已按照刚才的设想更新 A1 环境：

```text
AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/
├── raw/
├── normalized/
├── indexes/
├── fixtures/
│   ├── README.md
├── tests/
│   ├── README.md
├── schema.sql
├── seed.py
├── env.py
├── tools.py
├── dependencies.json
└── README.md
```

主要内容：

- `schema.sql`
  - 定义来源、上传产物、内容区域、识别运行、人工修正、学习对象、题目匹配和审计日志。
- `seed.py`
  - 加入固定、可复现的数学题图片样例元数据。
- `tools.py`
  - 预留上传、区域检测、内容识别、识别确认、学习对象创建和题目匹配接口。
- `dependencies.json`
  - 定义识别流程的强依赖和弱依赖。
- `env.py`
  - 预留环境构建入口。
- `README.md`
  - 说明 A1 的环境目标、状态链、数据目录和验证重点。
- `fixtures/README.md`
  - 规定固定图片样例和 ground truth 的组织方式。
- `tests/README.md`
  - 规定 A1 后续测试范围。

当前是可继续实现的工程骨架，工具具体逻辑和真实 fixture 图片尚未填充。

> 下一步应该怎么做，收集原始数据吗

是的，下一步首先应收集和整理 A1 的原始数据，但不要立刻大规模抓取。建议采用“小规模闭环 → 验证格式 → 扩展数据”的顺序。

## 推荐实施顺序

### 1. 先确定 A1 的最小场景范围

第一版只覆盖：

```text
学生上传一张题目图片
→ 识别题目区域
→ 识别文字和公式
→ 处理低置信度
→ 匹配题目
→ 返回讲解所需的结构化输入
```

暂时不要同时加入：

- 视频；
- 语音；
- 教材长文档；
- 实验图；
- 地图；
- 多用户权限；
- 复杂题目解答模型。

否则数据库和工具边界会迅速膨胀。

### 2. 设计原始数据采集清单

建议第一批准备 30–50 个样本：

```text
20 个清晰印刷题
10 个手写或低质量图片
5 个一图多题
5 个公式识别困难题
5 个图形/表格题
5 个无法识别或信息不完整样本
```

学科可以先限定为：

```text
小学数学
初中数学
高中数学
```

后续再扩展物理、化学、语文和英语。

### 3. 优先使用合法公开来源

可以从以下来源获取：

- 教育考试院公开试卷；
- 国家中小学智慧教育平台；
- 开放题库；
- 开源教育数据集；
- 学校或教师明确授权的资料；
- 自己制作的测试题和图片。

每个文件都记录：

```text
source_id
source_type
publisher
source_uri
snapshot_path
content_hash
published_at
license
verification_status
```

不要直接把网上下载的图片放入 `raw/` 而不记录来源。

### 4. 先建立 A1 原始数据目录

建议：

```text
A1_multimodal_learning_understanding/
├── raw/
│   ├── printed_questions/
│   ├── handwritten_questions/
│   ├── multi_problem/
│   ├── diagram_questions/
│   └── failed_cases/
├── normalized/
├── indexes/
├── fixtures/
└── provenance/
```

其中：

- `raw/` 保存原始文件；
- `fixtures/` 保存用于测试的少量固定样例；
- `provenance/` 保存来源和版权元数据。

如果 `provenance/` 尚未建立，可以现在增加。

### 5. 给每张图片制作 ground truth

A1 最重要的不是图片数量，而是标注质量。

每张图片至少需要标注：

```json
{
  "artifact_id": "art_001",
  "file_path": "raw/printed_questions/math_001.jpg",
  "media_type": "image",
  "expected_regions": [
    {
      "region_id": "reg_001",
      "region_type": "question",
      "bbox": [100, 80, 1800, 700],
      "text": "已知椭圆...",
      "latex": "\\frac{x^2}{4}+\\frac{y^2}{9}=1"
    }
  ],
  "expected_object_type": "question",
  "expected_problem_id": "problem_001",
  "match_type": "exact",
  "requires_confirmation": false
}
```

对于模糊样本：

```json
{
  "artifact_id": "art_blurry_001",
  "requires_confirmation": true,
  "uncertain_fields": ["latex"],
  "acceptable_candidates": [
    "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
    "\\frac{x^2}{16}+\\frac{y^2}{9}=1"
  ]
}
```

ground truth 应该明确：

- 区域数量；
- 区域类型；
- 题干文本；
- 公式；
- 是否有图形；
- 是否能匹配题库；
- 匹配类型；
- 是否需要用户确认。

### 6. 再建立规范化数据

完成一批标注后，再填充：

```text
normalized/
├── sources.json
├── artifacts.json
├── artifact_regions.json
├── recognition_runs.json
├── recognition_corrections.json
├── learning_objects.json
└── object_matches.json
```

可以先用 JSON 文件作为数据载体，等字段和状态稳定后再固化到 `schema.sql` 对应的 SQLite 数据库。

### 7. 创建索引

第一版只需要三个索引：

```text
indexes/
├── text_index.json
├── formula_index.json
└── problem_similarity_index.json
```

先做简单的：

- 题干关键词索引；
- 公式规范化字符串索引；
- 题目 ID 的精确匹配。

不要一开始就引入向量数据库。等有 1000 条以上题目和相似题任务后，再考虑向量检索。

### 8. 再实现工具

数据和 ground truth 稳定后，按以下顺序实现：

```text
1. upload_artifact
2. get_artifact_metadata
3. detect_content_regions
4. recognize_content
5. get_recognition_result
6. confirm_recognition
7. correct_recognition
8. create_learning_object
9. search_matching_problems
10. confirm_problem_match
11. read_source_provenance
```

第一版工具可以使用 fixture 中预先标注的识别结果，不需要立即接入真实 OCR 模型。这样能先验证：

- 数据结构；
- 状态迁移；
- 工具依赖；
- 错误码；
- 评测逻辑。

之后再将 `recognize_content` 替换为实际 OCR 或视觉模型。

### 9. 编写正例和负例任务

正例：

```text
学生上传清晰题目图片，请识别题干并找到题库中的对应题目。
```

```text
学生上传略模糊的公式题，请先确认公式，再继续匹配。
```

负例：

```text
识别置信度不足，但 Agent 未请求确认。
```

```text
只找到相似题，却声称是完全相同的原题。
```

```text
图片区域检测失败，Agent 仍然生成题目。
```

### 10. 最后再扩展数据规模

推荐分三个阶段：

```text
阶段 1：30–50 张图片，验证 schema 和工具链
阶段 2：200–500 张图片，覆盖年级、学科和异常情况
阶段 3：1000+ 张图片，支持复杂搜索、相似题和任务批量生成
```

## 你现在最应该做的事情

当前建议按这个顺序执行：

```text
1. 确定第一版只支持“数学题图片”
2. 收集 30–50 张合法公开图片
3. 建立 provenance 元数据
4. 为每张图片制作 ground truth
5. 填充 normalized 数据
6. 用 fixtures 初始化 schema
7. 实现 upload → recognize → confirm → match 工具链
8. 写 5–10 个可执行任务
9. 验证任务能否稳定复现
```

最重要的一点是：

> 不要先追求数据规模，先保证每张图片都有清晰的来源、规范化结果、识别 ground truth、题目匹配标签和可验证的状态迁移。

当这条最小链路稳定后，再扩展到物理、化学、语文、英语、实验图和语音材料。

> 为每张图片制作 ground truth是用于什么

为每张图片制作 ground truth，是为了给 A1 环境提供“标准答案”和“可验证目标”。

它不是给学生看的，而是用于：

```text
工具验证
+ Agent 任务评测
+ 数据质量控制
+ 识别错误分析
```

## 一张图片的 ground truth 是什么

例如图片中是一道高中解析几何题，ground truth 可以记录：

```json
{
  "artifact_id": "art_001",
  "expected_regions": [
    {
      "region_type": "question",
      "bbox": [100, 80, 1800, 700],
      "text": "已知椭圆 ...",
      "latex": "\\frac{x^2}{4}+\\frac{y^2}{9}=1"
    }
  ],
  "object_type": "question",
  "problem_id": "problem_001",
  "match_type": "exact",
  "requires_confirmation": false
}
```

它描述的是：

- 图片里有几个内容区域；
- 每个区域在哪里；
- 区域是什么类型；
- 正确的题干文本是什么；
- 正确公式是什么；
- 对应哪个题目；
- 是否为同题、相似题或无匹配；
- 是否应该要求用户确认。

## 主要用途

### 1. 验证区域检测

Agent 或工具检测出：

```json
[
  {
    "region_type": "question",
    "bbox": [100, 80, 1800, 700]
  }
]
```

系统可以和 ground truth 比较：

- 区域数量是否正确；
- 类型是否正确；
- 坐标是否足够接近；
- 是否漏掉图形或第二道题。

如果没有 ground truth，只能说“看起来检测到了区域”，不能自动判断是否检测正确。

### 2. 验证 OCR 和公式识别

识别结果：

```text
x2/4 + y2/9 = 1
```

ground truth：

```text
\frac{x^2}{4}+\frac{y^2}{9}=1
```

工具可以进行规范化后比较：

```text
识别公式是否正确
```

也可以设置数值容差或等价表达规则，避免：

```text
x² / 4 + y² / 9 = 1
```

和：

```text
\frac{x^2}{4}+\frac{y^2}{9}=1
```

被错误判为不同。

### 3. 验证低置信度处理

例如 ground truth 规定：

```json
{
  "requires_confirmation": true,
  "uncertain_fields": ["latex"]
}
```

而工具返回：

```json
{
  "confidence": 0.82,
  "status": "needs_confirmation"
}
```

就可以检查 Agent 是否：

1. 发现识别不可靠；
2. 暂停后续题目匹配；
3. 向学生请求确认；
4. 保存确认或修正记录。

如果没有 ground truth，系统不知道这张图片是否本来就应该触发确认。

### 4. 验证题目匹配

ground truth 可以标记：

```json
{
  "problem_id": "problem_001",
  "match_type": "exact"
}
```

系统就能判断：

- Agent 是否找对题目；
- 是否把相似题误认为同题；
- 是否在无匹配时错误声称“题库中存在”。

可以专门设置三种样本：

```text
exact       完全匹配
similar     仅相似
none        题库中不存在
```

这对于测试 Agent 的谨慎程度很重要。

### 5. 生成任务的标准答案

AgentWorld 的任务不是只检查工具调用成功，还要检查最终结果。

例如任务：

> 请识别图片中的题目，并确认是否能在题库中找到原题。

ground truth 可以用于自动生成标准答案：

```json
{
  "expected_problem_id": "problem_001",
  "expected_match_type": "exact",
  "expected_confirmation": false
}
```

最终可以自动评测：

```text
是否识别正确
是否匹配正确
是否完成确认
是否遗漏不确定性说明
```

### 6. 支持错误样本和负样本

ground truth 不只描述正确情况，也可以描述预期失败：

```json
{
  "artifact_id": "art_blurry_001",
  "expected_regions": [],
  "requires_confirmation": true,
  "expected_failure": "insufficient_recognition"
}
```

这样可以测试：

- 图片模糊时是否拒绝继续；
- 遮挡关键条件时是否请求补图；
- 多个公式候选时是否要求确认；
- 图像与用户文字描述冲突时是否指出冲突。

### 7. 分析系统到底错在哪里

如果最终任务失败，ground truth 可以帮助区分：

```text
区域检测错误
OCR 错误
公式识别错误
题目匹配错误
确认流程错误
工具依赖错误
最终讲解错误
```

例如：

```text
图片区域识别正确
OCR 正确
公式识别错误
题目匹配错误
```

这比只得到一个“任务失败”更有用。

## ground truth 与数据库的区别

两者职责不同：

| 数据           | 作用                             |
| -------------- | -------------------------------- |
| `raw/`         | 保存原始图片                     |
| `normalized/`  | 保存环境运行时的事实和状态       |
| `fixtures/`    | 保存固定测试样例                 |
| `ground_truth` | 保存样例的预期正确结果           |
| `tests/`       | 编写比较实际结果和预期结果的代码 |

建议把 ground truth 放在：

```text
fixtures/ground_truth/
```

或：

```text
fixtures/expected_results.json
```

例如：

```text
fixtures/
├── images/
│   └── math_question_001.jpg
├── metadata/
│   └── math_question_001.json
└── ground_truth/
    └── math_question_001.json
```

## ground truth 不等于标准解答

对于 A1，ground truth 主要标注：

- 区域；
- 文本；
- 公式；
- 图形；
- 置信度；
- 匹配关系；
- 是否需要确认。

它不一定包含完整数学推导。

完整解答可以放在共享题库：

```text
shared/normalized/problems.json
shared/normalized/solutions.json
```

A1 只需要验证：

```text
是否正确识别并匹配到题目
```

后续解题环境再验证：

```text
是否给出正确步骤和答案
```

## 最简单的例子

原始图片：

```text
fixtures/images/math_001.jpg
```

ground truth：

```json
{
  "artifact_id": "art_math_001",
  "region_count": 1,
  "region_type": "question",
  "expected_text": "解方程 x^2 - 3x + 2 = 0",
  "expected_latex": "x^2-3x+2=0",
  "match_type": "exact",
  "problem_id": "problem_math_001",
  "requires_confirmation": false
}
```

工具实际输出：

```json
{
  "recognized_text": "解方程 x² - 3x + 2 = 0",
  "recognized_latex": "x^2-3x+2=0",
  "problem_id": "problem_math_001"
}
```

测试程序经过规范化后即可判断：

```text
通过
```

## 最核心的理解

ground truth 的作用是：

> 把“这张图片应该被怎样理解”明确记录下来，从而让 A1 的识别、确认、匹配和任务结果都能够自动验证。

没有 ground truth，A1 只能演示工具调用；有了 ground truth，A1 才能成为真正可评测、可复现的 AgentWorld 环境。

> 现在我已经收集了30张来源于中考、高考、考研的数学题目，位于/inspire/qb-ilm/project/ai4education/p-liuwentao/qy/AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/raw/assets   接下来应该怎么做去构建数据库

<details><summary>1 previous message</summary>

> 我先检查这 30 张图片的格式、命名和现有 A1 schema，再给出从原始素材到可执行数据库的具体落地步骤；如果信息足够，也会补齐首版数据清单模板。
> </details>

是的，下一步进入“原始素材整理 → 标注 → 规范化入库”阶段。你现在只有 30 个图片文件，数据库还缺少题目来源、考试属性、识别结果和 ground truth。建议按以下顺序进行。

## 1. 先建立图片清单

当前文件名只有 `1.png`、`11.jpg` 这类编号，不能表达来源。先生成一个资产清单：

```text
raw/
└── assets/
    ├── 1.png
    ├── 2.png
    └── ...
```

建立：

```text
raw/asset_manifest.csv
```

字段建议：

```csv
asset_id,file_name,media_type,width,height,size_bytes,sha256
art_0001,1.png,image,1024,768,32383,sha256:...
```

同时检查：

- 图片格式；
- 图片尺寸；
- 文件大小；
- 是否重复；
- 是否损坏；
- 是否包含多道题。

可以用脚本批量计算哈希和尺寸，但这一步只生成元数据，不推断题目内容。

## 2. 为每张图片补充来源信息

由于图片来自中考、高考、考研，必须建立来源表：

```text
normalized/sources.json
```

每条来源至少包括：

```json
{
  "source_id": "src_gaokao_sh_2025",
  "source_type": "official_exam",
  "exam_type": "gaokao",
  "region": "Shanghai",
  "year": 2025,
  "subject": "mathematics",
  "publisher": "上海市教育考试院",
  "source_uri": "...",
  "license": "...",
  "verification_status": "verified"
}
```

建议区分：

```text
junior_high_exam
gaokao
postgraduate_entrance_exam
```

不要只写 `source = exam`，否则以后无法区分中考、高考和考研。

## 3. 给图片和来源建立关联

建立：

```text
normalized/artifacts.json
```

示例：

```json
{
  "artifact_id": "art_0001",
  "file_name": "1.png",
  "storage_path": "raw/assets/1.png",
  "media_type": "image",
  "content_hash": "sha256:...",
  "source_id": "src_gaokao_sh_2025",
  "status": "uploaded"
}
```

这里的 `artifact_id` 是图片产物 ID，不能直接把文件名当成题目 ID。

一张图片可能是：

- 一道题；
- 多道题；
- 一道题加学生草稿；
- 一页试卷；
- 一张解析图片。

所以图片和题目不能简单一一对应。

## 4. 标注图片区域

为每张图标注内容区域，保存到：

```text
normalized/artifact_regions.json
```

示例：

```json
{
  "region_id": "reg_0001",
  "artifact_id": "art_0001",
  "region_index": 1,
  "region_type": "question",
  "bbox": [80, 120, 1800, 920],
  "ground_truth_status": "verified"
}
```

`region_type` 可以是：

```text
question
student_attempt
diagram
table
answer_choice
textbook_paragraph
unknown
```

至少需要人工确认：

- 区域数量；
- 每个区域的类型；
- 区域坐标；
- 是否包含图形；
- 是否包含学生作答。

## 5. 为每个区域制作识别 ground truth

这是最重要的人工标注步骤。

保存到：

```text
fixtures/ground_truth/
```

例如：

```json
{
  "artifact_id": "art_0001",
  "regions": [
    {
      "region_id": "reg_0001",
      "region_type": "question",
      "text": "已知椭圆 ...",
      "latex": "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
      "has_diagram": true,
      "requires_confirmation": false
    }
  ]
}
```

如果图片中公式模糊：

```json
{
  "requires_confirmation": true,
  "uncertain_fields": ["latex"],
  "acceptable_candidates": [
    "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
    "\\frac{x^2}{16}+\\frac{y^2}{9}=1"
  ]
}
```

ground truth 用于判断：

- OCR 是否正确；
- 公式识别是否正确；
- 区域检测是否正确；
- 是否应触发用户确认；
- 是否漏识别图形或表格。

## 6. 建立题目规范化数据

识别标注完成后，再建立：

```text
normalized/learning_objects.json
```

示例：

```json
{
  "object_id": "obj_0001",
  "artifact_id": "art_0001",
  "object_type": "question",
  "subject": "math",
  "grade_band": "high_school",
  "exam_type": "gaokao",
  "region": "Shanghai",
  "year": 2025,
  "question_no": 18,
  "statement": "已知椭圆 ...",
  "latex": "\\frac{x^2}{4}+\\frac{y^2}{9}=1",
  "confirmation_status": "confirmed"
}
```

这里建议增加以下字段：

```text
exam_type
region
year
paper_id
question_no
score
topic
difficulty
```

你当前的 `learning_objects` 表还没有这些考试字段，后续应修改 `schema.sql`。

## 7. 建立题目匹配和标准解

如果图片中的题目属于你的公共题库，可以建立：

```text
normalized/object_matches.json
normalized/problems.json
normalized/solutions.json
```

匹配类型建议分为：

```text
exact      题目完全一致
similar    题型或结构相似
none       题库中没有对应题目
```

示例：

```json
{
  "match_id": "match_0001",
  "object_id": "obj_0001",
  "problem_id": "problem_gaokao_2025_18",
  "match_type": "exact",
  "similarity_score": 1.0,
  "status": "verified"
}
```

标准解建议单独保存：

```json
{
  "problem_id": "problem_gaokao_2025_18",
  "final_answer": "...",
  "solution_steps": [
    {
      "step_no": 1,
      "text": "...",
      "latex": "...",
      "key_step": true
    }
  ],
  "verification_status": "verified"
}
```

不要把标准解直接写进图片元数据。图片是输入产物，题目和解法是知识实体。

## 8. 当前 schema 需要补充的字段

你当前 A1 的 schema 可以支撑基本流程，但对中考、高考、考研题目还不够。建议补充：

### `sources`

```text
exam_type
region
year
subject
publisher
source_uri
license
```

### `artifacts`

```text
file_name
width
height
size_bytes
original_format
```

### `artifact_regions`

```text
x
y
width
height
ground_truth_text
ground_truth_latex
has_diagram
```

### `learning_objects`

```text
paper_id
question_no
exam_type
region
year
topic
difficulty
```

### 新增 `problems`

```sql
CREATE TABLE problems (
  problem_id TEXT PRIMARY KEY,
  statement TEXT NOT NULL,
  subject TEXT NOT NULL,
  grade_band TEXT,
  exam_type TEXT,
  region TEXT,
  year INTEGER,
  paper_id TEXT,
  question_no INTEGER,
  topic TEXT,
  difficulty REAL
);
```

### 新增 `solutions`

```sql
CREATE TABLE solutions (
  solution_id TEXT PRIMARY KEY,
  problem_id TEXT NOT NULL REFERENCES problems(problem_id),
  final_answer TEXT NOT NULL,
  verification_status TEXT NOT NULL
);
```

### 新增 `solution_steps`

```sql
CREATE TABLE solution_steps (
  solution_id TEXT NOT NULL REFERENCES solutions(solution_id),
  step_no INTEGER NOT NULL,
  text TEXT NOT NULL,
  latex TEXT,
  is_key_step INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (solution_id, step_no)
);
```

## 9. 目录建议调整

你目前的 A1 目录可以调整成：

```text
A1_multimodal_learning_understanding/
├── raw/
│   ├── assets/
│   ├── source_documents/
│   └── asset_manifest.csv
├── normalized/
│   ├── sources.json
│   ├── artifacts.json
│   ├── artifact_regions.json
│   ├── recognition_runs.json
│   ├── learning_objects.json
│   ├── problems.json
│   ├── solutions.json
│   └── object_matches.json
├── indexes/
│   ├── text_index.json
│   ├── formula_index.json
│   └── problem_similarity_index.json
├── fixtures/
│   ├── ground_truth/
│   └── task_cases/
├── tests/
├── schema.sql
├── seed.py
├── env.py
├── tools.py
├── dependencies.json
└── README.md
```

其中：

- `raw/assets/`：你现在已有的 30 张图片；
- `raw/source_documents/`：对应的试卷 PDF 或网页快照；
- `normalized/`：正式业务数据；
- `fixtures/ground_truth/`：人工确认的正确识别结果；
- `fixtures/task_cases/`：任务初始状态和预期结果。

## 10. 30 张图片的推荐标注表

在正式写入数据库前，可以先建立一个人工维护的 CSV：

```text
normalized/asset_annotation.csv
```

字段：

```csv
asset_id,file_name,exam_type,region,year,paper_id,question_no,subject,grade_band,topic,has_diagram,region_count,ocr_text,latex,match_type,problem_id,requires_confirmation,annotation_status
```

这张表可以作为第一版数据构建的“中间表”。确认无误后，再由 `seed.py` 导入 SQLite。

## 11. 建议的实际顺序

不要一开始就处理全部 30 张。先选 5 张做闭环：

```text
1 张清晰高考题
1 张清晰中考题
1 张清晰考研题
1 张公式模糊题
1 张包含图形或多区域的题
```

完成：

```text
原始文件
→ 来源登记
→ 图片清单
→ 区域标注
→ OCR/公式 ground truth
→ 题目规范化
→ 标准解
→ 题目匹配
→ SQLite seed
→ 工具测试
```

这 5 张跑通后，再扩展到剩余 25 张。

## 12. 最终数据库关系

A1 的数据关系应是：

```text
source
  ↓
artifact（原始图片）
  ↓
artifact_region（图片区域）
  ↓
recognition_run（识别结果）
  ↓
learning_object（结构化学习对象）
  ↓
problem_match（同题/相似题/无匹配）
  ↓
problem + solution（标准题目和解法）
```

因此，你现在的 30 张图片不是直接“导入题目表”，而是要经过：

```text
图片资产登记
→ 来源和考试属性补全
→ 内容区域标注
→ OCR/公式 ground truth
→ 结构化题目
→ 题库匹配
→ 标准解关联
→ 数据库种子化
```

最推荐的下一步是：**先建立 `asset_manifest.csv` 和 `asset_annotation.csv`，完成 5 张图片的人工标注，再修改 `schema.sql` 和 `seed.py`。**

> 写题目来源是为了什么目的

写题目来源主要不是为了让 Agent 更容易答题，而是为了让环境中的数据具备真实性、可追溯性和可验证性。

## 1. 证明数据来自真实世界

AgentWorld 强调使用真实世界数据构建环境，而不是完全由 LLM 编造。

例如：

```json
{
  "problem_id": "problem_001",
  "source_id": "src_gaokao_shanghai_2025"
}
```

来源记录：

```json
{
  "source_id": "src_gaokao_shanghai_2025",
  "source_type": "official_exam",
  "publisher": "上海市教育考试院",
  "exam_type": "gaokao",
  "region": "Shanghai",
  "year": 2025
}
```

这能证明该题是某份真实试卷中的题目，而不是为了测试临时生成的题目。

## 2. 区分考试、年份和地区

中国考试题高度依赖：

```text
考试类型
年份
地区
科目
试卷版本
```

例如以下请求不能只靠题目文本判断：

> 查找 2025 年上海高考数学第 18 题。

数据库必须能按来源属性过滤：

```text
exam_type = gaokao
region = Shanghai
year = 2025
question_no = 18
```

否则容易出现：

- 把模拟题当成真题；
- 把北京卷当成上海卷；
- 把 2024 年题目当成 2025 年题目；
- 把网上改编题当成官方原题。

## 3. 区分官方答案和第三方解析

同一道题可能有多个解答来源：

```text
官方答案
学校教师解析
培训机构解析
题库转载
个人博客解析
LLM 生成解析
```

来源信息可以记录：

```json
{
  "solution_id": "solution_001",
  "source_id": "src_official_answer_001",
  "verification_status": "official"
}
```

或：

```json
{
  "solution_id": "solution_002",
  "source_id": "src_training_site_001",
  "verification_status": "third_party_verified"
}
```

Agent 才能准确表达：

```text
“根据官方参考答案……”
```

或者：

```text
“下面是一种非官方但已验证的解法……”
```

没有来源，就不能声称答案是官方的。

## 4. 支持去重和版本识别

同一道题可能被多个网站转载：

```text
考试院 PDF
新闻网站
培训机构网页
题库截图
社交平台图片
```

如果没有来源和题目出现记录，系统可能把同一道题保存成五道题。

推荐区分：

```text
problem
    规范化后的唯一题目

problem_occurrence
    这道题在哪个来源中出现
```

例如：

```json
{
  "problem_id": "problem_001",
  "occurrences": [
    {
      "source_id": "src_official_exam",
      "question_no": 18
    },
    {
      "source_id": "src_training_site",
      "question_no": 18
    }
  ]
}
```

这样既能去重，又保留不同来源。

## 5. 支持题目匹配判断

学生上传一张图片后，系统可能找到一条相似记录。

来源信息可以帮助判断：

- 是否确实来自同一份试卷；
- 是否是同一道题；
- 是否是数字被修改的变式题；
- 是否只是题型相似。

例如：

```text
图片 OCR 与题库文本高度相似
+ 年份、地区、题号一致
→ 更可能是 exact match

只有公式结构相似
+ 来源不同
→ 更可能是 similar match
```

来源不是唯一判断依据，但它是重要证据。

## 6. 支持任务生成

有来源字段后，可以生成更真实的任务：

```text
学生上传了一张题目截图，请判断它是否来自
2024 年上海中考数学试卷，并给出题号。
```

或者：

```text
这张图片被标注为高考题，请核验它实际上属于
高考真题、模拟题还是培训机构改编题。
```

这些任务需要 Agent：

```text
识别图片
→ 搜索题库
→ 查询来源
→ 比较考试属性
→ 给出结论
```

如果没有来源信息，只能生成“识别题目并回答”这种简单任务。

## 7. 支持自动评测

ground truth 可以记录：

```json
{
  "expected_problem_id": "problem_001",
  "expected_source_id": "src_gaokao_shanghai_2025",
  "expected_exam_type": "gaokao",
  "expected_region": "Shanghai",
  "expected_year": 2025
}
```

系统可以验证 Agent 是否：

- 找到了正确题目；
- 判断了正确年份；
- 判断了正确地区；
- 没有把第三方转载说成官方来源。

## 8. 支持数据纠错

如果以后发现题目年份、题号或答案错误，可以定位：

```text
错误来自哪个原始 PDF
由哪个网页转载
何时录入
谁做过人工修订
```

来源表可以进一步保存：

```text
snapshot_path
content_hash
fetched_at
verified_by
verification_status
```

这样数据库修订有明确依据。

## 9. 支持版权和使用范围管理

真实试卷、教材、题库和培训资料的授权范围可能不同。

来源信息可以记录：

```text
license
copyright_status
allowed_usage
```

例如：

```json
{
  "copyright_status": "publicly_available",
  "allowed_usage": "research_evaluation_only"
}
```

这有助于区分：

- 可以公开发布的数据；
- 只能用于内部研究的数据；
- 不能重新分发原始图片的数据；
- 只允许保存结构化元数据的数据。

## 10. 支持数据库更新

如果未来加入新年份试卷，可以根据：

```text
source_id
source_uri
published_at
content_hash
```

判断：

- 是否已经收录；
- 原文件是否变化；
- 是否需要重新提取；
- 新版是否覆盖旧版。

## 在 A1 中需要记录到什么程度

第一版不需要为每道题写非常复杂的来源信息，至少记录：

```text
source_id
source_type
exam_type
year
region
publisher
source_uri
snapshot_path
content_hash
verification_status
```

对于考研题，可以记录：

```json
{
  "source_id": "src_kaoyan_math_2025",
  "source_type": "official_exam",
  "exam_type": "postgraduate_entrance_exam",
  "year": 2025,
  "region": "national",
  "paper_variant": "Mathematics I",
  "publisher": "教育部教育考试院",
  "snapshot_path": "raw/source_documents/kaoyan_math_2025.pdf",
  "verification_status": "verified"
}
```

如果你只知道图片来自网络但不知道原始出处，应如实记录：

```json
{
  "source_type": "web_image",
  "publisher": null,
  "verification_status": "unverified"
}
```

不要为了字段完整而猜测来源。

## 核心结论

写题目来源有五个核心目的：

```text
真实性：证明数据不是凭空构造
可追溯：知道题目来自哪里
可区分：区分考试、年份、地区和版本
可验证：支持题目匹配和自动评测
可治理：支持纠错、版权和版本更新
```

对“学生上传图片请求解答”这一最简单任务，来源并不是完成解答的必要条件；但对整个 A1 环境的真实性、任务丰富度和长期可维护性，来源信息非常重要。

> 按照这个逻辑，我下一步该构建什么

下一步不应马上实现 OCR 或工具，而是先把 30 张图片变成一套“可追溯、可标注、可导入”的资产数据。

推荐按以下顺序推进。

## 第一步：建立图片资产清单

先构建：

```text
raw/asset_manifest.csv
```

每张图片一行：

```csv
artifact_id,file_name,storage_path,media_type,size_bytes,width,height,sha256,status
art_0001,1.png,raw/assets/1.png,image,32383,800,600,sha256:...,collected
```

这一阶段只记录客观文件属性，不填写题目内容。

目的：

- 确认恰好有 30 张图片；
- 检查损坏和重复文件；
- 为每张图片生成稳定 `artifact_id`；
- 后续所有标注都通过 `artifact_id` 关联。

## 第二步：建立来源标注表

构建：

```text
raw/source_annotations.csv
```

建议字段：

```csv
artifact_id,source_type,exam_type,year,region,paper_variant,question_no,publisher,source_uri,verification_status,notes
```

例如：

```csv
art_0001,official_exam,gaokao,2025,Shanghai,main,18,上海市教育考试院,https://...,verified,
art_0002,web_image,postgraduate_entrance_exam,2024,national,Mathematics-I,,,unverified,原始网页待确认
```

规则：

- 不知道的字段留空；
- 不要根据图片内容猜来源；
- 官方来源与转载来源分开；
- 保留原始 URL 或试卷 PDF 路径。

## 第三步：建立题目人工标注表

构建：

```text
normalized/problem_annotations.csv
```

建议字段：

```csv
artifact_id,object_type,subject,grade_band,exam_type,year,region,question_no,topic,question_type,region_count,has_diagram,statement,latex,annotation_status
```

示例：

```csv
art_0001,question,math,high_school,gaokao,2025,Shanghai,18,analytic_geometry,constructed_response,1,true,"已知椭圆……","\frac{x^2}{4}+...",verified
```

这里开始人工录入图片中的真实内容。

至少填写：

- 正确题干；
- 公式 LaTeX；
- 学段；
- 考试类型；
- 题型；
- 知识点；
- 是否带图；
- 一张图片中有几道题。

## 第四步：建立 ground truth

从人工标注表生成：

```text
fixtures/ground_truth/
├── art_0001.json
├── art_0002.json
└── ...
```

单个文件示例：

```json
{
  "artifact_id": "art_0001",
  "expected_regions": [
    {
      "region_index": 1,
      "region_type": "question",
      "bbox": [0, 0, 800, 600],
      "text": "已知椭圆……",
      "latex": "\\frac{x^2}{4}+\\frac{y^2}{9}=1"
    }
  ],
  "has_diagram": true,
  "requires_confirmation": false,
  "annotation_status": "verified"
}
```

如果图片模糊：

```json
{
  "requires_confirmation": true,
  "uncertain_fields": ["latex"],
  "acceptable_candidates": ["...", "..."]
}
```

## 第五步：建立规范化题库

将图片内容转换为独立的题目实体：

```text
normalized/problems.json
```

示例：

```json
{
  "problem_id": "problem_0001",
  "statement": "已知椭圆……",
  "subject": "math",
  "grade_band": "high_school",
  "exam_type": "gaokao",
  "topic": "analytic_geometry",
  "question_type": "constructed_response"
}
```

同时建立图片与题目的关系：

```text
normalized/object_matches.json
```

```json
{
  "artifact_id": "art_0001",
  "problem_id": "problem_0001",
  "match_type": "exact",
  "status": "verified"
}
```

需要注意：

```text
artifact_id = 图片
problem_id = 规范化题目
```

两者不要混用。

## 第六步：补充标准答案和解析

构建：

```text
normalized/solutions.json
```

```json
{
  "solution_id": "solution_0001",
  "problem_id": "problem_0001",
  "final_answer": "...",
  "solution_steps": [
    {
      "step_no": 1,
      "text": "...",
      "latex": "...",
      "is_key_step": true
    }
  ],
  "source_id": "src_0001",
  "verification_status": "verified"
}
```

解析来源可以和题目来源不同，因此 `solution` 也需要自己的 `source_id`。

## 第七步：修改 schema

完成前面数据标注后，再根据实际字段修改 `schema.sql`。

建议新增或扩展：

```text
sources
artifacts
artifact_regions
recognition_ground_truth
learning_objects
problems
problem_occurrences
solutions
solution_steps
object_matches
audit_log
```

不要先凭想象不断扩表。先标注 5 张图片，通过真实数据确定字段，再固定 schema。

## 第八步：修改 seed.py

让 `seed.py` 从规范化文件导入数据库：

```text
sources.json
artifacts.json
problems.json
solutions.json
ground_truth/*.json
```

不要继续使用当前硬编码的一条示例：

```python
conn.execute("INSERT INTO sources VALUES (...)")
```

更合理的是：

```python
def seed(conn, data_dir):
    load_sources(conn, data_dir / "normalized/sources.json")
    load_artifacts(conn, data_dir / "normalized/artifacts.json")
    load_problems(conn, data_dir / "normalized/problems.json")
    load_solutions(conn, data_dir / "normalized/solutions.json")
```

## 第九步：先实现 fixture 型识别工具

第一版不接真实 OCR，工具根据固定 fixture 返回预标注结果：

```text
detect_content_regions
→ 读取 ground truth 的区域，但可以返回预设噪声

recognize_content
→ 返回预设 OCR 候选和置信度
```

这样优先验证：

- 数据结构；
- 工具依赖；
- 确认流程；
- 题目匹配；
- 状态迁移；
- 任务评测。

之后再替换为真实 OCR。

## 现在最具体的下一项工作

建议立即完成下面三个文件：

```text
raw/asset_manifest.csv
raw/source_annotations.csv
normalized/problem_annotations.csv
```

然后先人工标注 5 张代表性图片：

```text
1 张中考题
1 张高考题
1 张考研题
1 张带图题
1 张模糊或公式容易误识别的题
```

这 5 张形成完整闭环后，再批量处理剩余 25 张。

因此，下一步最准确的任务是：

> 为 30 张图片建立资产清单，并选择其中 5 张补全来源与题目人工标注。

这一步完成后，才适合正式修改数据库 schema 和种子导入逻辑。

> 那index目录是为了干什么的

`indexes/` 用来保存“查询加速和匹配辅助数据”。它不是原始数据，也不是权威数据库状态。

可以简单理解为：

```text
raw/          原始图片
normalized/   图片、题目、解析等权威结构化数据
indexes/      为了更快找到这些数据而生成的辅助索引
```

例如，学生上传图片后识别出：

```text
已知椭圆 x²/4 + y²/9 = 1
```

系统不应该每次都扫描 `problems.json` 中的全部题目，而可以通过索引快速找到候选题。

## A1 可以有哪些索引

### 1. 文本索引

```text
indexes/problem_text_index.json
```

用于根据 OCR 题干搜索题目。

示例：

```json
{
  "已知": ["problem_0001", "problem_0007"],
  "椭圆": ["problem_0001", "problem_0012"],
  "切线": ["problem_0001", "problem_0015"]
}
```

识别出“椭圆”和“切线”后，可以快速得到候选：

```text
problem_0001
problem_0012
problem_0015
```

### 2. 公式索引

```text
indexes/formula_index.json
```

用于按照规范化公式查找题目。

示例：

```json
{
  "x^2/4+y^2/9=1": [
    "problem_0001"
  ],
  "x^2/a^2+y^2/b^2=1": [
    "problem_0001",
    "problem_0012"
  ]
}
```

公式索引可以支持两种粒度：

- 完全一致公式；
- 结构相似公式。

例如：

```text
x²/4 + y²/9 = 1
x²/9 + y²/16 = 1
```

数值不同，但结构相似。

### 3. 题目相似度索引

```text
indexes/problem_similarity_index.json
```

用于搜索相似题或变式题。

示例：

```json
{
  "problem_0001": [
    {
      "problem_id": "problem_0012",
      "score": 0.91,
      "relation": "parameter_variant"
    },
    {
      "problem_id": "problem_0015",
      "score": 0.78,
      "relation": "same_topic"
    }
  ]
}
```

它可以区分：

```text
exact      完全相同题目
variant    数值或条件变化
similar    同知识点或同解题方法
```

### 4. 知识点索引

```text
indexes/knowledge_point_index.json
```

用于按知识点查题：

```json
{
  "analytic_geometry.ellipse": [
    "problem_0001",
    "problem_0012"
  ],
  "analytic_geometry.tangent": [
    "problem_0001",
    "problem_0015"
  ]
}
```

它支持：

- 找同类题；
- 判断题目主题；
- 为后续练习环境推荐题目；
- 生成知识点相关任务。

### 5. 来源索引

```text
indexes/source_index.json
```

用于按考试来源查题：

```json
{
  "gaokao:Shanghai:2025": [
    "problem_0001",
    "problem_0002"
  ],
  "postgraduate:Mathematics-I:2025": [
    "problem_0021",
    "problem_0022"
  ]
}
```

可以支持：

> 查找 2025 年上海高考数学解析几何题。

### 6. 图片哈希索引

```text
indexes/artifact_hash_index.json
```

用于检查图片是否重复：

```json
{
  "sha256:abc123": "art_0001",
  "sha256:def456": "art_0002"
}
```

如果学生重复上传同一图片，工具可以快速返回已有 `artifact_id`，而不是重新识别。

还可以增加感知哈希：

```json
{
  "phash:a917...": [
    "art_0001",
    "art_0017"
  ]
}
```

用于发现：

- 图片被压缩；
- 图片尺寸变化；
- 图片加了水印；
- 图片被轻微裁剪。

## 索引和数据库表的区别

例如 `problems` 是权威数据：

```json
{
  "problem_id": "problem_0001",
  "statement": "已知椭圆……",
  "topic": "analytic_geometry"
}
```

索引只是指向它：

```json
{
  "椭圆": ["problem_0001"]
}
```

如果二者发生冲突，应以 `normalized/` 或 SQLite 数据库为准。

索引应该满足：

```text
可以删除
可以重建
不保存唯一事实
不由人工直接作为权威数据维护
```

## 为什么使用索引

### 数据量小时

你现在只有 30 张图片，直接扫描全部题目也可以，索引不是性能必需品。

但保留 `indexes/` 有三个价值：

1. 提前建立稳定的数据接口；
2. 便于扩展到数千或数万题；
3. 可以生成检索和题目匹配类任务。

### 数据量大时

假设未来有 10 万道题，每次识别后都逐条比较：

```text
OCR 文本 × 100000 道题
```

会非常慢。

使用索引后：

```text
OCR 关键词/公式
→ 索引返回 20 个候选
→ 对 20 个候选计算精确相似度
```

性能和任务逻辑都会更合理。

## 索引如何生成

索引不建议人工逐条填写，而应由脚本从权威数据生成：

```text
normalized/problems.json
        ↓
build_indexes.py
        ↓
indexes/problem_text_index.json
indexes/formula_index.json
indexes/knowledge_point_index.json
```

例如：

```python
def build_topic_index(problems):
    index = {}

    for problem in problems:
        topic = problem["topic"]
        index.setdefault(topic, []).append(problem["problem_id"])

    return index
```

如果题目更新，应重新运行索引构建脚本。

## 在 AgentWorld 中的作用

索引也可以成为工具依赖的一部分。

例如：

```text
recognize_content
→ normalize_recognition
→ search_problem_index
→ get_problem
→ verify_match
```

其中：

- `search_problem_index` 返回候选题；
- `get_problem` 返回候选详情；
- Agent 比较候选并确认；
- `verify_match` 写入最终匹配状态。

这样任务不是简单地从数据库直接取答案，而是要求 Agent：

```text
识别
→ 搜索
→ 比较
→ 验证
```

## 当前阶段是否必须构建

现在有 30 张图片，第一版只需要三个简单索引：

```text
indexes/
├── artifact_hash_index.json
├── problem_text_index.json
└── source_index.json
```

暂时可以不做：

- 向量数据库；
- 大模型 embedding；
- 复杂公式树索引；
- 图像特征库；
- 分布式全文检索。

建议等题目规范化完成后，再写一个 `build_indexes.py` 自动生成索引。

核心原则是：

> `normalized/` 保存“事实是什么”，`indexes/` 保存“怎样更快找到事实”。

> 帮我完成第一步：建立图片资产清单和第二步：建立来源标注表，你先完成，我再审核修改

<details><summary>1 previous message</summary>

> 我会扫描 30 张图片的客观元数据（尺寸、大小、哈希），生成资产清单；来源信息不臆测，先建立待审核的来源标注表并留空未知字段。
> </details>

已完成前两步，生成两份待审核 CSV：

1. [asset_manifest.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/raw/asset_manifest.csv)

记录 30 张图片的客观文件信息：

- `artifact_id`
- 文件名
- 存储路径
- 文件类型
- 文件大小
- 图片宽高
- SHA-256 内容哈希
- 当前状态

示例：

```csv
art_0001,1.png,raw/assets/1.png,image,32383,687,268,sha256:...,collected
```

2. [source_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/raw/source_annotations.csv)

建立了来源标注字段：

- `source_type`
- `exam_type`
- `year`
- `region`
- `paper_variant`
- `question_no`
- `publisher`
- `source_uri`
- `source_document`
- `license`
- `verification_status`
- `notes`

由于目前没有足够信息确认每张图片的具体来源，我没有自行猜测，30 条记录均标记为：

```text
verification_status = pending_review
notes = 请审核并补充来源
```

你可以先审核文件名和图片对应关系，再补充每张图片的考试类型、年份、地区、试卷版本和来源。

> source_uri
> source_document
> license
> verification_status
> notes
> 分别记录什么，是什么意思，必要吗

这几个字段都属于“数据来源治理信息”，不直接描述题目内容。它们主要用于追溯、核验、版权管理和人工审核。

对于当前只有 30 张题目的第一版环境，并非全部必填。

| 字段                  | 含义                     | 第一版是否必要           |
| --------------------- | ------------------------ | ------------------------ |
| `source_uri`          | 原始网页或下载地址       | 建议保留，可为空         |
| `source_document`     | 题目所在的原始完整文件   | 建议保留，可为空         |
| `license`             | 数据使用、复制和发布权限 | 建议保留，可填 `unknown` |
| `verification_status` | 来源信息是否经过核验     | 必要                     |
| `notes`               | 无法结构化表达的补充说明 | 可选                     |

## `source_uri`

记录题目原始网页、官方页面或下载链接。

例如：

```text
https://www.shmeea.edu.cn/...
```

或者：

```text
https://yz.chsi.com.cn/...
```

它回答：

> 这张题目图片是从哪个线上地址获得的？

主要用途：

- 以后重新查找原始页面；
- 核对年份、地区和试卷版本；
- 判断来源是官方网站还是第三方转载；
- 检查网页内容是否更新。

如果图片来自本地已有文件，且不知道网页地址，可以留空。

不要把当前本地路径写进 `source_uri`：

```text
raw/assets/1.png
```

本地路径应由 `asset_manifest.csv` 的 `storage_path` 记录。

## `source_document`

记录题目所属的完整原始文档或文档标识。

例如，图片是从整份试卷 PDF 截取的：

```text
raw/source_documents/2025_shanghai_gaokao_math.pdf
```

也可以先写文件名：

```text
2025_shanghai_gaokao_math.pdf
```

它回答：

> 这张截图原本属于哪一份完整试卷或资料？

`source_uri` 与 `source_document` 的区别：

```text
source_uri       原始资料在线上哪里
source_document  本地保存的完整原始文件在哪里
```

示例：

```csv
source_uri=https://example.edu/exam/2025
source_document=raw/source_documents/2025_math.pdf
```

如果你只收集了单独题目图片，没有完整试卷 PDF，可以留空。

长期来看，建议尽量保存完整试卷，因为它能帮助核验：

- 考试名称；
- 年份；
- 地区；
- 题号；
- 分值；
- 试卷版本；
- 图片是否被修改。

## `license`

记录这份数据允许怎样使用。

可能的值：

```text
public_domain
open_license
official_public_material
research_only
authorized
unknown
restricted
```

例如：

```csv
license=research_only
```

表示仅用于内部科研和评测，不应公开重新分发原始图片。

它回答：

> 这份题目是否允许被保存、加工、训练或公开发布？

需要注意，`license` 不应凭感觉填写。网页能公开访问不一定意味着可以任意转载或发布。

如果尚未核实，建议填写：

```text
unknown
```

不要留空，因为留空可能被误解为“没有版权限制”。

对于当前项目，建议统一使用有限枚举：

```text
official_public_material
open_license
authorized_research_use
research_only
unknown
restricted
```

## `verification_status`

记录这一行来源信息是否经过核验。

建议值：

```text
pending_review
verified
partially_verified
unverified
conflicting
rejected
```

含义如下：

| 状态                 | 含义                                         |
| -------------------- | -------------------------------------------- |
| `pending_review`     | 已录入，但还未人工检查                       |
| `verified`           | 已找到可靠来源并确认信息正确                 |
| `partially_verified` | 只确认部分信息，如只确定是高考题但不确定年份 |
| `unverified`         | 暂时无法找到可靠来源                         |
| `conflicting`        | 不同来源给出的年份或题号冲突                 |
| `rejected`           | 已确认来源标注错误或素材不应使用             |

它回答：

> 我们对这条来源信息有多大把握？

这是五个字段中最重要的字段。任务生成时可以限制：

```text
只有 verified 或 partially_verified 的题目可以用于来源核验任务
```

但普通图片识别任务可以使用 `unverified` 的素材，因为图片识别不一定依赖来源。

## `notes`

记录无法放入固定字段的人工说明。

例如：

```text
只找到培训机构转载页面，尚未找到官方试卷
```

```text
图片疑似经过裁剪，原题题号不可见
```

```text
网页标注为2024年，但PDF页眉显示2023年
```

```text
题目内容已核对，解析来源尚未核对
```

它回答：

> 审核过程中还有什么特殊情况需要告诉下一位维护者？

这是可选字段。不应把本来可以结构化的信息都写进 `notes`。

不推荐：

```text
notes=2025年上海高考第18题
```

这些应分别放进：

```text
year=2025
region=Shanghai
exam_type=gaokao
question_no=18
```

## 哪些字段当前必须保留

对于你目前 30 张图片的最小版本，我建议：

### 必须填写

```text
artifact_id
exam_type
verification_status
```

至少要知道：

- 这条来源属于哪张图片；
- 它大致是中考、高考还是考研；
- 来源信息是否经过核验。

### 强烈建议填写

```text
year
region
paper_variant
publisher
source_uri
license
```

如果确实知道，就填写；不知道时使用空值或 `unknown`，不要猜。

### 可选

```text
source_document
question_no
notes
```

如果有整份原始试卷、明确题号或特殊审核问题，再填写。

## 是否可以删减

第一版可以简化为：

```csv
artifact_id,file_name,exam_type,year,region,paper_variant,question_no,source_uri,license,verification_status,notes
```

可以暂时去掉：

```text
publisher
source_document
```

但我不建议删除。保留空列的成本很低，未来补充完整试卷和官方出版方时不需要修改数据格式。

## 推荐填写示例

### 官方来源明确

```csv
art_0001,1.png,official_exam,gaokao,2025,Shanghai,main,18,上海市教育考试院,https://...,raw/source_documents/2025_shanghai_math.pdf,official_public_material,verified,已与官方PDF核对
```

### 只知道考试类型

```csv
art_0002,2.png,web_image,postgraduate_entrance_exam,,,,,,,unknown,partially_verified,确定为考研数学题，年份和试卷类型待确认
```

### 来源完全未知

```csv
art_0003,3.png,unknown,,,,,,,,unknown,unverified,只有题目截图，无原始链接
```

核心原则是：

> 来源字段可以不完整，但必须真实反映你知道什么、不知道什么，以及哪些信息已经核验。

> 已审核并补充完成，下一步是什么

<details><summary>2 previous messages</summary>

> 我先检查你审核后的来源表完整度和字段一致性，然后基于实际结果确定下一步是建立题目标注表，还是先修正来源数据。
>
> 来源表不是 UTF-8 编码，读取检查时出现解码错误。我先识别实际编码并只读核对内容，不会改动你的审核结果。
> </details>

来源表已经基本完成，当前状态很好：

- 30 条图片记录齐全；
- `artifact_id` 无重复；
- 28 条 `verified`，2 条 `partially_verified`；
- 中考、高考、考研分类基本完整；
- 年份、地区、试卷版本、题号和出版社均已填写。

不过在进入下一步前，建议先修正一个格式问题：

```text
college entrance exam
```

应统一为：

```text
college_entrance_exam
```

否则后续按 `exam_type` 筛选时会被当成两个不同类别。

## 下一步：建立题目内容标注表

现在来源信息已经明确，下一步不是立即写入数据库，而是为每张图片标注“图片中到底有什么”。

建议创建：

```text
AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv
```

字段建议：

```csv
artifact_id,file_name,object_type,subject,grade_band,exam_type,year,region,paper_variant,question_no,topic,question_type,region_count,has_diagram,statement,latex,match_type,problem_id,requires_confirmation,annotation_status,notes
```

其中：

- `artifact_id`：关联图片；
- `object_type`：题目、学生作答、图表、实验图等；
- `subject`：数学；
- `grade_band`：初中、高中、大学/考研；
- `topic`：函数、几何、概率、解析几何等；
- `question_type`：选择题、填空题、解答题；
- `region_count`：图片中有几个内容区域；
- `has_diagram`：是否包含几何图、函数图像或表格；
- `statement`：人工核对后的题干；
- `latex`：公式的规范化表示；
- `match_type`：`exact`、`similar` 或 `none`；
- `problem_id`：对应的规范化题目 ID；
- `requires_confirmation`：识别时是否需要学生确认；
- `annotation_status`：`pending` 或 `verified`。

## 建议先标注 5 张

不要一次性处理全部 30 张，先选：

```text
1 张考研题
1 张中考题
1 张高考题
1 张带几何图形的题
1 张公式或图片质量较差的题
```

对每张图片完成：

```text
图片区域
→ 题目文本
→ 数学公式
→ 学科与学段
→ 知识点
→ 是否带图
→ 是否能匹配题库
→ 是否需要确认
```

例如：

```csv
art_0001,1.png,question,math,high_school,college_entrance_exam,2025,Shanghai,main,18,analytic_geometry,constructed_response,1,true,"已知椭圆……","\\frac{x^2}{4}+\\frac{y^2}{9}=1",exact,problem_gaokao_sh_2025_18,false,verified,
```

## 目前需要注意的一个问题

你的来源表当前字段是：

```text
artifact_id,file_name,source_type,exam_type,year,region,paper_variant,question_no,publisher,verification_status,notes,license
```

之前设计中提到的：

```text
source_uri
source_document
```

目前没有出现在实际表里。

这不影响当前题目标注，但建议后续补回，因为：

- `source_uri` 记录原始网页或下载地址；
- `source_document` 记录对应的完整试卷 PDF；
- 便于以后核验题目、版本和来源。

## 后续完整顺序

```text
1. 统一 exam_type 枚举
2. 建立 problem_annotations.csv
3. 标注 5 张代表性图片
4. 建立图片区域和识别 ground truth
5. 建立 problems.json
6. 建立 solutions.json
7. 修改 schema.sql
8. 修改 seed.py
9. 实现 fixture 识别工具
10. 编写 A1 任务和测试
```

因此，你现在最应该做的是：

> 建立 `normalized/problem_annotations.csv`，先完成 5 张图片的题目内容、公式、区域和题库匹配标注。

> 建立题目内容标注表的目的是什么，之后可能的完整任务描述和在本项目的实现逻辑会是什么

题目内容标注表的核心目的，是把“图片文件”转换成环境能够查询、匹配和验证的“结构化题目”。

目前你只有两层信息：

```text
asset_manifest.csv
    这是什么文件、在哪里、多大、哈希是多少

source_annotations.csv
    它来自什么考试、哪一年、哪张试卷、哪一道题
```

但环境还不知道：

```text
图片里写了什么
包含几个区域
有什么数学公式
属于哪个知识点
题型是什么
是否带图
是否可以完整识别
标准答案是什么
```

`problem_annotations.csv` 就是连接“原始图片”和“可执行环境数据库”的中间层。

## 一、为什么不能只用图片和来源表

例如：

```text
art_0001
文件：1.png
来源：2026 年考研数学二第 7 题
```

这些信息只能支持：

> 这张图片来自哪里？

却不能支持：

> 图片里是什么题？
> OCR 是否正确？
> 公式是否漏掉？
> 应该匹配哪个题目？
> Agent 的识别结果是否正确？
> 应该返回什么解法？

因此需要人工标注：

```json
{
  "artifact_id": "art_0001",
  "statement": "设随机变量……",
  "latex": "...",
  "topic": "probability",
  "question_type": "multiple_choice",
  "has_diagram": false,
  "region_count": 1,
  "problem_id": "problem_0001",
  "annotation_status": "verified"
}
```

## 二、题目标注表的五个用途

### 1. 生成规范化题库

从：

```text
1.png
```

生成：

```json
{
  "problem_id": "problem_0001",
  "statement": "……",
  "subject": "math",
  "topic": "probability",
  "question_type": "multiple_choice"
}
```

以后图片、标准答案、解析、知识点都通过 `problem_id` 关联。

### 2. 作为识别 ground truth

实际工具可能输出：

```text
设随机变量 X 服从……
```

标注表记录正确题干：

```text
设随机变量 X 与 Y 相互独立……
```

测试程序可以比较实际结果和正确结果，判断 OCR 是否通过。

### 3. 支持题目搜索和匹配

识别出文字后，系统需要根据：

- 关键词；
- 规范化公式；
- 考试来源；
- 知识点；
- 题型；

在题库中找候选题。

标注表提供构建文本、公式和知识点索引的基础数据。

### 4. 生成任务标准答案

例如任务：

> 请识别学生上传的图片，并说明它属于哪个考试和知识点。

ground truth 可以是：

```json
{
  "problem_id": "problem_0001",
  "exam_type": "postgraduate_entrance_exam",
  "year": 2026,
  "paper_variant": "Mathematics-II",
  "question_no": 7,
  "topic": "probability"
}
```

Agent 的最终回答可以自动核验。

### 5. 发现数据自身的问题

标注过程中可能发现：

- 来源表题号写错；
- 图片只包含半道题；
- 图片中有两道题；
- 来源称是高考题，实际是模拟题；
- 图片缺少选项；
- 公式无法确定；
- 同一道题被重复收集。

这也是数据清洗阶段。

# 三、完整任务描述示例

任务描述不能出现工具名、表名或内部调用顺序。对用户只呈现真实需求。

## 任务 1：清晰图片识题并讲解

> 我上传了一张数学题图片。请先准确识别题目内容，再告诉我这道题主要考查什么知识点，并给出完整解题思路和最终答案。不要只给结果。

预期环境数据：

```text
图片清晰
题库存在完全相同的题
标准答案和解析完整
不需要用户确认
```

## 任务 2：公式模糊，需要确认

> 请帮我解答这张数学题。图片中椭圆方程的一个分母可能不太清楚，如果你不能确定，请先告诉我你识别到了哪些可能值，等我确认后再继续。

预期行为：

```text
识别公式
→ 发现置信度不足
→ 暂停题目匹配
→ 请求用户确认
→ 收到确认
→ 创建题目对象
→ 获取解法
```

## 任务 3：一张图片包含多道题

> 这张截图里有三道数学题。请分别识别每道题，按照图片中的顺序编号，并只讲解第二道题。

预期行为：

```text
检测三个区域
→ 分别识别
→ 保留区域顺序
→ 选择第二个学习对象
→ 匹配题库
→ 获取第二题解法
```

## 任务 4：只有相似题，没有原题

> 请判断这张题能否在题库里找到原题。如果没有，请找一道解法最接近的题目，说明它们的区别，再讲解当前图片中的题。

预期行为：

```text
识别当前题目
→ 搜索候选
→ 判断只有 similar
→ 不宣称找到原题
→ 说明条件或数值差异
→ 使用当前题目完成解答
```

## 任务 5：图片信息不完整

> 我拍的题目可能没有拍全，请帮我看看能不能解。如果缺少条件，请明确告诉我缺少什么，不要自行补充。

预期行为：

```text
发现题干截断或选项缺失
→ 标记 insufficient_recognition
→ 指出缺失区域
→ 请求重新上传
→ 不生成虚构答案
```

## 任务 6：核验题目来源

> 这张图片据说是 2025 年上海高考数学题。请核验它是否确实来自这份试卷，并告诉我题号和主要考点。

预期行为：

```text
识别题目
→ 匹配 problem_id
→ 查询来源记录
→ 对比年份、地区、考试类型、题号
→ 返回核验结论
```

# 四、在本项目中的实现逻辑

以“清晰图片识题并讲解”为例。

## 1. 任务生成前

项目已经包含固定图片：

```text
raw/assets/1.png
```

资产表：

```json
{
  "artifact_id": "art_0001",
  "storage_path": "raw/assets/1.png",
  "content_hash": "sha256:..."
}
```

来源表：

```json
{
  "artifact_id": "art_0001",
  "exam_type": "postgraduate_entrance_exam",
  "year": 2026,
  "paper_variant": "Mathematics-II",
  "question_no": 7
}
```

题目标注表：

```json
{
  "artifact_id": "art_0001",
  "problem_id": "problem_0001",
  "statement": "……",
  "latex": "……",
  "topic": "probability",
  "region_count": 1,
  "requires_confirmation": false
}
```

标准解表：

```json
{
  "problem_id": "problem_0001",
  "final_answer": "B",
  "solution_steps": [
    {"step_no": 1, "text": "……"},
    {"step_no": 2, "text": "……"}
  ]
}
```

## 2. 初始化任务状态

`seed.py` 将该任务需要的数据导入内存 SQLite：

```text
sources
artifacts
artifact_regions
recognition_runs 或 recognition_fixtures
problems
solutions
solution_steps
```

初始状态通常只暴露：

```text
art_0001 已上传
```

其他信息存在数据库中，但 Agent 必须通过工具查询。

## 3. Agent 执行工具链

```text
get_artifact_metadata(art_0001)
    ↓
detect_content_regions(art_0001)
    ↓
recognize_content(reg_0001)
    ↓
get_recognition_result(rec_0001)
    ↓
create_learning_object(...)
    ↓
search_matching_problems(obj_0001)
    ↓
confirm_problem_match(...)
    ↓
get_problem(problem_0001)
    ↓
get_solution(problem_0001)
    ↓
verify_solution(problem_0001)
```

工具不是实时随机调用外部 OCR。第一版可以读取固定的识别 fixture：

```json
{
  "artifact_id": "art_0001",
  "recognized_text": "……",
  "confidence": 0.97
}
```

这样同一张图片每次返回相同结果，确保可复现。

## 4. 数据库状态迁移

初始：

```text
artifact.status = uploaded
```

检测后：

```text
artifact_regions 新增记录
artifact.status = regions_detected
```

识别后：

```text
recognition_runs 新增记录
artifact.status = recognized
```

如果低置信度：

```text
recognition.status = needs_confirmation
artifact.status = needs_confirmation
```

确认后：

```text
recognition.status = confirmed
confirmation_events 新增记录
```

创建题目对象后：

```text
learning_objects 新增记录
```

匹配后：

```text
object_matches 新增记录
match.status = verified
```

所有写操作同时写入：

```text
audit_log
```

## 5. 自动评测

任务执行结束后，验证器不只检查最终自然语言，还检查数据库状态：

```text
是否检测了正确区域
是否产生了识别记录
低置信度时是否进行了确认
是否创建了正确的 learning_object
是否匹配到正确 problem_id
是否将 similar 错标为 exact
是否读取并验证了正确解答
```

例如：

```json
{
  "expected": {
    "artifact_status": "matched",
    "problem_id": "problem_0001",
    "match_type": "exact",
    "confirmation_required": false,
    "solution_verified": true
  }
}
```

# 五、题目标注表与任务执行的关系

完整的数据流是：

```text
人工标注 problem_annotations.csv
          ↓
生成规范化 problems.json 和 ground_truth
          ↓
seed.py 写入任务初始数据库
          ↓
Agent 调用工具产生实际状态
          ↓
验证器对照 ground_truth 检查结果
```

需要注意：

> Agent 不应该直接读取 `problem_annotations.csv`。

这个文件用于：

- 数据准备；
- 生成种子数据库；
- 生成 ground truth；
- 测试验证。

Agent 只能通过环境工具看到允许暴露的信息，否则会造成答案泄漏。

# 六、建议的实现边界

A1 名称是“多模态学习理解”，因此最合理的核心终点是：

```text
可靠地形成结构化学习对象
+ 正确匹配题目
```

“完整数学推导质量”通常更适合后续解题或辅导环境评价。

但为了使“学生上传图片请求解答”能在单一 AgentWorld 环境中闭环，A1 第一版可以额外提供：

```text
get_solution
verify_solution
```

此时应明确：

- A1 评测重点：图片识别、确认、匹配是否正确；
- 解答内容：来自固定、已验证的标准解；
- 不把开放式数学推理作为工具正确率的唯一判断依据。

## 结论

题目内容标注表的目的不是简单“把图片抄成文字”，而是建立：

```text
图片输入
→ 正确内容
→ 规范化题目
→ 来源
→ 标准解
→ 自动评测
```

之间的可靠映射。

没有它，项目只能知道 Agent 调用了哪些工具；有了它，项目才能判断 Agent 是否真正理解了图片、找对了题目、处理了不确定性，并给出了正确解答。

> 就拿任务1举例，
> 任务 1：清晰图片识题并讲解
> 我上传了一张数学题图片。请先准确识别题目内容，再告诉我这道题主要考查什么知识点，并给出完整解题思路和最终答案。不要只给结果。
>
> 这个任务设计的图片应该是属于原始数据库里的吗，，然后agent会调用哪些工具，如何验证任务是否完成

是的。对于这个任务，图片应该属于 A1 环境预先构建的原始数据库/固定数据集，但任务描述不应直接暴露内部文件路径和数据库字段。

更准确地说：

```text
原始图片保存在 raw/assets/
图片元数据、题目标注、标准解保存在 normalized/ 和 fixtures/
任务执行时从固定数据集中选择一张图片
```

这样可以保证每次任务的输入、识别结果和标准答案可复现。

## 一、图片在数据库中的组织

例如：

```text
raw/assets/11.jpg
```

对应资产记录：

```json
{
  "artifact_id": "art_0011",
  "file_name": "11.jpg",
  "storage_path": "raw/assets/11.jpg",
  "media_type": "image",
  "content_hash": "sha256:...",
  "status": "uploaded"
}
```

对应 ground truth：

```json
{
  "artifact_id": "art_0011",
  "region_count": 1,
  "region_type": "question",
  "statement": "已知……",
  "latex": "...",
  "subject": "math",
  "grade_band": "high_school",
  "topic": "analytic_geometry",
  "problem_id": "problem_0011",
  "match_type": "exact",
  "requires_confirmation": false
}
```

对应标准解：

```json
{
  "problem_id": "problem_0011",
  "final_answer": "...",
  "solution_steps": [
    {"step_no": 1, "text": "..."},
    {"step_no": 2, "text": "..."}
  ],
  "verification_status": "verified"
}
```

## 二、任务描述如何提供图片

任务描述可以有两种方式。

### 方式一：初始状态预置图片

任务描述：

> 我上传了一张数学题图片。请先准确识别题目内容，再告诉我这道题主要考查什么知识点，并给出完整解题思路和最终答案。不要只给结果。

环境初始状态中已经存在：

```text
artifact_id = art_0011
status = uploaded
```

Agent 通过查询工具发现待处理图片。

这种方式适合测试“识别和讲解流程”。

### 方式二：任务中模拟上传

任务描述：

> 请处理我刚上传的数学题图片，并完成识别、知识点判断和解题讲解。

环境通过任务上下文提供一个固定素材引用，例如：

```text
fixture_id = math_image_0011
```

Agent 调用：

```text
upload_artifact(fixture_id="math_image_0011")
```

工具只允许从固定 fixture 集合中选择图片，不允许任意网络 URL 或任意本地路径。

这种方式更接近真实用户流程。

## 三、Agent 可能调用的工具

对于“清晰图片识题并讲解”任务，合法工具链可以是：

```text
get_artifact_metadata
→ detect_content_regions
→ recognize_content
→ get_recognition_result
→ create_learning_object
→ search_matching_problems
→ confirm_problem_match
→ get_solution
→ verify_solution
```

具体作用如下。

### 1. `get_artifact_metadata`

确认：

- 图片是否存在；
- 文件类型；
- 图片状态；
- 内容哈希；
- 图片尺寸。

示例返回：

```json
{
  "artifact_id": "art_0011",
  "media_type": "image",
  "status": "uploaded",
  "width": 1600,
  "height": 1100
}
```

### 2. `detect_content_regions`

检测图片中的题干、图形、表格或学生作答区域。

返回：

```json
{
  "regions": [
    {
      "region_id": "reg_0011",
      "region_type": "question",
      "bbox": [80, 100, 1480, 850],
      "confidence": 0.98
    }
  ]
}
```

### 3. `recognize_content`

对区域进行 OCR、公式识别和图形识别。

```json
{
  "recognition_id": "rec_0011",
  "region_id": "reg_0011",
  "raw_text": "已知椭圆……",
  "latex": "...",
  "confidence": 0.97,
  "status": "recognized"
}
```

### 4. `get_recognition_result`

读取完整识别结果，供 Agent 判断：

- 题干是否完整；
- 公式是否清晰；
- 是否包含关键图形；
- 是否需要用户确认。

对于清晰图片，`confidence` 可以达到阈值以上，因此不需要确认。

### 5. `create_learning_object`

将已经识别的区域转成结构化学习对象：

```json
{
  "object_id": "obj_0011",
  "object_type": "question",
  "statement": "已知椭圆……",
  "subject": "math",
  "grade_band": "high_school",
  "confirmation_status": "auto_confirmed"
}
```

### 6. `search_matching_problems`

利用：

- 题干文本；
- 公式；
- 学科；
- 年级；
- 题型；
- 来源元数据；

搜索题库候选题。

返回：

```json
{
  "candidates": [
    {
      "problem_id": "problem_0011",
      "match_type": "exact",
      "similarity_score": 1.0
    }
  ]
}
```

### 7. `confirm_problem_match`

确认最终匹配关系：

```json
{
  "object_id": "obj_0011",
  "problem_id": "problem_0011",
  "match_type": "exact",
  "status": "verified"
}
```

如果只找到相似题，应记录：

```json
{
  "match_type": "similar",
  "status": "candidate"
}
```

不能把它写成 `exact`。

### 8. `get_solution`

读取固定、已审核的标准解：

```json
{
  "problem_id": "problem_0011",
  "topic": "analytic_geometry",
  "final_answer": "...",
  "solution_steps": [...]
}
```

### 9. `verify_solution`

验证标准解或最终答案，例如：

- 代入检验；
- 符号计算；
- 方程等价性检查；
- 结果是否与标准答案一致。

返回：

```json
{
  "problem_id": "problem_0011",
  "verification_status": "verified",
  "methods": ["symbolic_check", "substitution_check"]
}
```

## 四、一个完整执行轨迹

### 初始状态

```text
art_0011.status = uploaded
数据库中尚未创建识别记录
数据库中尚未创建 learning_object
```

### Agent 执行

```text
1. get_artifact_metadata("art_0011")
2. detect_content_regions("art_0011")
3. recognize_content("reg_0011", modality="ocr")
4. recognize_content("reg_0011", modality="formula")
5. get_recognition_result("rec_0011")
6. create_learning_object(...)
7. search_matching_problems("obj_0011")
8. confirm_problem_match(...)
9. get_solution("problem_0011")
10. verify_solution("problem_0011")
```

### 最终状态

```text
artifact.status = matched
recognition_run.status = verified
learning_object.confirmation_status = confirmed
object_match.status = verified
solution.verification_status = verified
audit_log 有完整调用记录
```

Agent 最终向学生输出：

```text
我识别到的题目是：……

这道题主要考查：解析几何中的……

解题思路：
1. ……
2. ……
3. ……

最终答案：……

我已对结果进行了代入/符号验证。
```

## 五、如何验证任务完成

不能只检查 Agent 是否返回了自然语言答案，而应同时检查三层结果。

### 1. 工具调用层

检查是否完成必要调用：

```text
是否读取图片元数据
是否检测内容区域
是否完成文字/公式识别
是否创建结构化学习对象
是否搜索题目
是否读取标准解
是否执行验证
```

工具顺序不一定必须完全固定，但强依赖必须满足：

```text
detect_content_regions
必须在
recognize_content
之前

recognize_content
必须在
create_learning_object
之前

create_learning_object
必须在
search_matching_problems
之前
```

### 2. 数据状态层

检查数据库最终状态：

```json
{
  "artifact_status": "matched",
  "region_count": 1,
  "recognition_status": "verified",
  "object_type": "question",
  "problem_id": "problem_0011",
  "match_type": "exact",
  "solution_verified": true
}
```

### 3. 最终答案层

检查 Agent 输出是否包含：

- 正确题目内容；
- 正确知识点；
- 主要解题步骤；
- 正确最终答案；
- 必要的不确定性说明；
- 没有把内部工具名、表名和文件路径暴露给学生。

## 六、Ground truth 如何参与验证

任务的 ground truth 可以写成：

```json
{
  "task_id": "a1_clear_question_001",
  "artifact_id": "art_0011",
  "expected": {
    "region_count": 1,
    "recognized_text": "...",
    "recognized_latex": "...",
    "object_type": "question",
    "problem_id": "problem_0011",
    "match_type": "exact",
    "topic": "analytic_geometry",
    "requires_confirmation": false,
    "solution_verified": true
  }
}
```

验证器将实际结果和预期结果比较：

```text
实际识别文本 ≈ ground truth 文本
实际公式 ≈ ground truth 公式
实际题目 ID = expected problem_id
实际匹配类型 = exact
实际知识点 = analytic_geometry
实际解答验证状态 = verified
```

文本和公式比较应先规范化，避免因为：

```text
x²/4 + y²/9 = 1
```

和：

```text
\frac{x^2}{4}+\frac{y^2}{9}=1
```

格式不同而误判。

## 七、这个任务是否必须调用全部工具

不一定。

对于一张已经预置、清晰且已经匹配题库的图片，可以把：

```text
get_artifact_metadata
→ recognize_content
→ search_matching_problems
→ get_solution
→ verify_solution
```

作为最小链路。

但如果任务目标是测试完整的 A1 能力，建议保留：

```text
区域检测
+ 识别
+ 结构化对象
+ 题目匹配
+ 标准解读取
+ 解答验证
```

不建议将任务简化为：

```text
get_solution(problem_id)
```

因为这样实际上没有测试图片理解。

## 八、一个重要边界

“清晰图片识题并讲解”中：

- A1 负责图片理解、识别、匹配和讲解输入准备；
- `get_solution` 和 `verify_solution` 负责提供、核验标准答案；
- Agent 负责根据标准解组织适合学生的自然语言解释。

如果后续任务要求：

```text
分析学生自己的错误步骤
逐级释放提示
根据重试结果调整难度
```

则需要增加学生作答、错误诊断和提示状态；这已经超出最小 A1 任务，但可以作为 A1 的扩展任务，或放入 D1、B2 等环境。

因此，完整逻辑是：

```text
固定图片作为任务输入
→ Agent 调用 A1 工具链
→ 工具更新 SQLite/JSON 状态
→ 验证器对照 ground truth
→ 检查最终讲解是否完整、正确、可追溯
```

这就是在你的项目中实现“学生上传一张题目图片请求解答”的基本方式。

> 下一步将写一份题目内容标注表，帮我写一份初稿我来审核并修改

<details><summary>3 previous messages</summary>

> 我会根据现有 30 张图片和来源表生成一份“题目内容标注表”初稿：自动带入图片、考试来源、年份、地区、试卷版本和题号，其余需要人工确认的题干、公式、知识点和匹配字段留空或标为待审核。
>
> 来源表存在混合编码字符，直接读取会失败。我会采用容错解码生成初稿，并保留原始来源表不变；无法可靠解析的字符不会影响结构化字段。
>
> 初稿已生成，但我发现来源表中的 `Mathematics-Ⅱ` 在保存过程中已出现替换字符。为了避免把乱码带入后续数据库，我会仅在新标注表中将考研卷型规范化为 ASCII 枚举。
> </details>

已生成题目内容标注表初稿：

[problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)

当前包含 30 条图片记录，并自动带入：

- `artifact_id`
- `file_name`
- `object_type=question`
- `subject=math`
- `grade_band`
- `exam_type`
- `year`
- `region`
- `paper_variant`
- `question_no`

待你审核和补充的字段包括：

```text
topic
question_type
region_count
has_diagram
statement
latex
match_type
problem_id
requires_confirmation
```

所有记录当前标记为：

```text
annotation_status = pending_review
```

并附有：

```text
请人工补充题干、公式、知识点、区域和匹配信息
```

另外，我将考研试卷类型统一规范为：

```text
Mathematics-II
```

避免来源表中原有的特殊字符编码问题影响后续数据库导入。

> 我的source_annotations.csv内容如下，但是有中文乱码，帮我修改：
> artifact_id	file_name	source_type	exam_type	year	region	paper_variant	question_no	publisher	verification_status	notes	license
> art_0001	1.png	official_exam	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	7	教育部教育考试院	verified	确定为考研数学试卷原题	research_only
> art_0002	2.png	official_exam	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	21	教育部教育考试院	verified	确定为考研数学试卷原题	research_only
> art_0003	3.png	official_exam	postgraduate_entrance_exam	2025	national	Mathematics-Ⅱ	18	教育部教育考试院	verified	确定为考研数学试卷原题	research_only
> art_0004	4.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	33	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0005	5.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	26	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0006	6.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	34	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0007	7.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	4	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0008	8.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	7	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0009	9.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	21	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0010	10.png	web_image	postgraduate_entrance_exam	2026	national	Mathematics-Ⅱ	13	2026年张宇1000题	verified	确定为考研数学练习题	research_only
> art_0011	11.jpg	official_exam	college_entrance_exam	2025	Shanghai	main	18	上海市教育考试院	verified	确定为上海高考数学卷原题	research_only
> art_0012	12.jpg	official_exam	college_entrance_exam	2025	Shanghai	main	8,9,10	上海市教育考试院	verified	确定为上海高考数学卷原题	research_only
> art_0013	13.jpg	official_exam	college_entrance_exam	2025	national	paper-Ⅰ	16	教育部教育考试院	verified	确定为全国高考数学1卷原题	research_only
> art_0014	14.jpg	official_exam	college_entrance_exam	2025	national	paper-Ⅰ	14	教育部教育考试院	verified	确定为全国高考数学1卷原题	research_only
> art_0015	15.jpg	official_exam	college_entrance_exam	unknown	national	unknown	15	教育部教育考试院	partially_verified	确定为全国高考数学卷原题，年份和卷号待确认	research_only
> art_0016	16.jpg	official_exam	college_entrance_exam	unknown	national	unknown	11	教育部教育考试院	partially_verified	确定为全国高考数学卷原题，年份和卷号待确认	research_only
> art_0017	17.jpg	official_exam	college_entrance_exam	2026	national	paper-Ⅱ	8	教育部教育考试院	verified	确定为全国高考数学2卷原题	research_only
> art_0018	18.jpg	official_exam	college_entrance_exam	2026	national	paper-Ⅱ	10	教育部教育考试院	verified	确定为全国高考数学2卷原题	research_only
> art_0019	19.jpg	official_exam	college_entrance_exam	2026	national	paper-Ⅱ	5	教育部教育考试院	verified	确定为全国高考数学2卷原题	research_only
> art_0020	20.jpg	official_exam	college_entrance_exam	2026	Shanghai	main	16	上海市教育考试院	verified	确定为上海高考数学卷原题	research_only
> art_0021	21.png	official_exam	high_school_entrance_exam	2026	Shanghai	main	12	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0022	22.png	official_exam	high_school_entrance_exam	2026	Shanghai	main	20	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0023	23.png	official_exam	high_school_entrance_exam	2026	Shanghai	main	23	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0024	24.png	official_exam	high_school_entrance_exam	2026	Shanghai	main	6	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0025	25.png	official_exam	high_school_entrance_exam	2026	Shanghai	main	24	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0026	26.png	official_exam	high_school_entrance_exam	2025	Shanghai	main	15	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0027	27.png	official_exam	high_school_entrance_exam	2025	Shanghai	main	10	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0028	28.png	official_exam	high_school_entrance_exam	2025	Shanghai	main	6	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0029	29.png	official_exam	high_school_entrance_exam	2025	Shanghai	main	24	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only
> art_0030	30.png	official_exam	high_school_entrance_exam	2025	Shanghai	main	25	上海市教育考试院	verified	确定为上海中考数学卷原题	research_only

<details><summary>3 previous messages</summary>

> 我会将来源表统一转换为 UTF-8（带 BOM）并把试卷版本中的罗马数字 `Ⅱ` 规范为 `II`，避免 Excel 再次显示乱码。字段和审核内容保持不变。
>
> 文件当前不是“原始中文编码错误”，而是已经发生了乱码转码（例如 `教育部教育考试院` 已变成 `��������������Ժ`）。我会尝试逆向修复这类乱码，再验证中文字段和 30 条记录。
>
> 乱码已经是不可逆的替换字符，不能仅靠重新编码恢复。我会依据你消息中给出的原始审核内容，按 30 条记录重建中文出版社、试卷版本和备注字段，并输出标准 UTF-8 CSV。
> </details>

已修复 [source_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/raw/source_annotations.csv) 的中文乱码。

处理内容：

- 依据你提供的原始内容重建出版社和备注字段；
- 文件统一保存为 UTF-8 with BOM，兼容 Excel；
- `Mathematics-Ⅱ` 规范为 `Mathematics-II`；
- 保留全部 30 条记录；
- 已验证以下中文正常：
  - `教育部教育考试院`
  - `上海市教育考试院`
  - `确定为考研数学试卷原题`
  - `确定为全国高考数学卷原题，年份和卷号待确认`

此前乱码中已经存在不可逆的 `�` 替换字符，因此本次是根据你消息中的原始数据重建，而不是简单转换编码。

> artifact_id：关联图片；
> object_type：题目、学生作答、图表、实验图等；
> subject：数学；
> grade_band：初中、高中、大学/考研；
> topic：函数、几何、概率、解析几何等；
> question_type：选择题、填空题、解答题；
> region_count：图片中有几个内容区域；
> has_diagram：是否包含几何图、函数图像或表格；
> statement：人工核对后的题干；
> latex：公式的规范化表示；
> match_type：exact、similar 或 none；
> problem_id：对应的规范化题目 ID；
> requires_confirmation：识别时是否需要学生确认；
> annotation_status：pending 或 verified。
> 这些列的取值可以给一些参考样例吗，其中region_count是怎么判断的，就拿第一张图填入AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/raw/assets/1.png

<details><summary>4 previous messages</summary>

> 我先查看第一张图片的内容和尺寸，再据此给出一行完整标注示例，并解释 `region_count` 的判定规则。
>
> 图像查看工具受当前沙箱挂载限制，我改用本地 OCR/图像元数据读取；如果无法可靠识别题干，我会明确把需要人工确认的字段标为待审核，不会臆填。
>
> 本地没有可用 OCR 输出。我会把图片临时复制到 `/tmp` 进行视觉检查，再据图填写第一行。
>
> 我已确认第一张图是一道清晰的考研数学二选择题，主题是二重积分的 Riemann 和表示。接下来我会把可确定字段写入 `problem_annotations.csv`，题目匹配字段暂不臆测，保留待审核。
> </details>

已将第一张图片的初步标注写入：

[problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)

第一张图的建议取值如下：

| 字段                    | 取值                                                 |
| ----------------------- | ---------------------------------------------------- |
| `artifact_id`           | `art_0001`                                           |
| `object_type`           | `question`                                           |
| `subject`               | `math`                                               |
| `grade_band`            | `postgraduate`                                       |
| `topic`                 | `multivariable_calculus.double_integral_riemann_sum` |
| `question_type`         | `multiple_choice`                                    |
| `region_count`          | `1`                                                  |
| `has_diagram`           | `false`                                              |
| `match_type`            | 暂时留空                                             |
| `problem_id`            | 暂时留空                                             |
| `requires_confirmation` | `false`                                              |
| `annotation_status`     | `pending_review`                                     |

## `region_count` 怎么判断

`region_count` 表示图片中有多少个需要独立识别并形成学习对象的主要内容区域，不是文字有几行，也不是公式有几个。

第一张图包含：

```text
一道题干
+ 这道题的四个选项
```

题干和选项共同构成一道完整选择题，因此：

```text
region_count = 1
```

以下情况通常取不同值：

| 图片内容                       | `region_count` |
| ------------------------------ | -------------: |
| 一道选择题，含四个选项         |              1 |
| 一道几何题，含配套图形         |              1 |
| 一道题目和学生对应作答         |              2 |
| 一张截图包含第 8、9、10 三道题 |              3 |
| 两道题，第二题另有配套图形     |              2 |
| 一页试卷含五道相互独立的题     |              5 |

配套图形是否单独算区域取决于能否独立形成对象：

- 几何图只是题目的一部分：仍算 1 个学习对象；
- 图片中是独立图表分析材料，供多道题共用：可以单独标为材料区域；
- 学生作答与原题同时出现：题目和作答通常分成 2 个区域。

## 字段取值参考

- `object_type`：`question`、`student_attempt`、`chart`、`experiment_diagram`、`textbook_excerpt`
- `question_type`：`multiple_choice`、`fill_blank`、`constructed_response`、`proof`
- `has_diagram`：`true` 或 `false`
- `match_type`：`exact`、`similar`、`none`
- `requires_confirmation`：`true` 或 `false`
- `annotation_status`：`pending_review`、`verified`

第一张图虽然清晰，但题干之外还有四个复杂求和选项。目前 `statement` 只录入了题干，尚未完整录入四个选项，因此继续保留 `pending_review`。完整复核并补齐选项后，才适合改成 `verified`。

> match_type是什么意思，比如这题的题干中有公式，该如何填入statement列和latex列

## `match_type` 的含义

`match_type` 表示：

> 从图片识别出来的题目，与项目规范化题库中的某道题是什么关系。

它不是图片质量，也不是 OCR 是否正确。

可取三个值：

| 取值      | 含义                             |
| --------- | -------------------------------- |
| `exact`   | 题库中存在完全相同的题目         |
| `similar` | 题库中只有知识点或结构相似的题目 |
| `none`    | 题库中没有对应题目               |

### `exact`

图片对应的题目已经被规范化保存为：

```text
problem_0001
```

而且题干、条件和问题要求一致：

```csv
match_type=exact
problem_id=problem_0001
```

即使存在以下格式差异，也可以认为是 `exact`：

- 图片中使用 `x²`，题库使用 `x^2`；
- 图片中空格不同；
- 换行位置不同；
- 全角、半角符号不同；
- 题目编号不同；
- 图片中有排版变化。

但以下情况不能算 `exact`：

- 参数数值不同；
- 条件不同；
- 求解目标不同；
- 选项不同且会改变答案；
- 缺少关键条件。

### `similar`

题库没有完全相同的题，但存在相同解法或同知识点题目。

例如图片题目是：

```text
区域 D=[0,1]×[0,1]，且 f(x,y)=f(y,x)
```

题库题目是：

```text
区域 D=[0,2]×[0,2]，且 f(x,y)=f(y,x)
```

两题都考查对称区域上的二重积分和 Riemann 和，但边界不同，因此：

```csv
match_type=similar
problem_id=problem_0042
```

这里的 `problem_id` 表示最相似的候选题，不是当前图片原题。

### `none`

题库中没有原题，也没有达到相似度阈值的候选：

```csv
match_type=none
problem_id=
```

此时可以把图片题目创建为一个新的规范化题目，再重新建立 `exact` 关系。

## 第一张图应该如何填写 `match_type`

你目前正在建立规范化题库，第一张图片对应的题目还没有独立的 `problems` 记录。

因此当前阶段建议：

```csv
match_type=
problem_id=
```

先留空。

等后面创建：

```json
{
  "problem_id": "problem_0001",
  "statement": "...",
  "choices": [...]
}
```

之后再填写：

```csv
match_type=exact
problem_id=problem_0001
```

如果每张图片都用于创建一条新的规范化题目，那么初始构库结束后，这 30 张图片通常都会对应：

```text
match_type = exact
```

但执行任务时，Agent 不应该直接知道这个结果，而要通过搜索和匹配工具获得。

# `statement` 和 `latex` 如何分工

推荐的定义是：

```text
statement：完整、可供人阅读的题目内容
latex：题目中的数学表达式或整道题的结构化 LaTeX
```

## `statement`

应包含完整题目，包括：

- 题号；
- 文字条件；
- 数学公式；
- 问题要求；
- 选择题选项。

可以直接使用 Unicode 数学符号，使 CSV 中容易审核。

第一张图的 `statement` 建议填写为：

```text
7. 设函数 f(x,y) 在区域 D={(x,y)|0≤x≤1,0≤y≤1} 上连续，且 f(x,y)=f(y,x)，则 ∬_D f(x,y)dxdy=( )。A. ……；B. ……；C. ……；D. ……
```

这里的公式直接嵌入文字中即可：

```text
f(x,y)
D={(x,y)|0≤x≤1,0≤y≤1}
f(x,y)=f(y,x)
∬_D f(x,y)dxdy
```

`statement` 不应该只写：

```text
设函数在区域上连续……
```

否则丢失了数学条件。

## `latex`

`latex` 用于保存规范化、机器可处理的数学表达。

第一张图题干部分可以填写：

```latex
D=\\{(x,y)\\mid 0\\le x\\le 1,\\ 0\\le y\\le 1\\};\\quad
f(x,y)=f(y,x);\\quad
\\iint_D f(x,y)\\,dx\\,dy
```

在 CSV 中实际看到的内容可以是：

```text
D=\{(x,y)\mid 0\le x\le 1,\ 0\le y\le 1\};\quad f(x,y)=f(y,x);\quad \iint_D f(x,y)\,dx\,dy
```

CSV 本身不要求像 Python 字符串那样把反斜杠写两次。只有在 Python 源码字符串中，才可能需要写成：

```python
"D=\\{(x,y)\\mid ...\\}"
```

## 是否要把整道题都写进 `latex`

有两种方案。

### 方案一：只记录公式集合

当前 CSV 只有一个 `latex` 字段，可以用分号分隔多个公式：

```text
D=\{(x,y)\mid 0\le x\le1,\ 0\le y\le1\}; f(x,y)=f(y,x); \iint_D f(x,y)\,dx\,dy
```

优点：

- 容易人工编辑；
- 适合第一版；
- 便于建立公式索引。

### 方案二：整道题使用 LaTeX

例如：

```latex
7. 设函数 $f(x,y)$ 在区域
$D=\\{(x,y)\\mid 0\\le x\\le1,0\\le y\\le1\\}$
上连续，且 $f(x,y)=f(y,x)$，则
$\\iint_D f(x,y)\\,dx\\,dy=(\\quad)$。
```

这种方式更完整，但混合了中文和数学表达，不利于后续对单个公式建立索引。

第一版建议采用方案一：

```text
statement = 完整的人类可读题目
latex = 题目中的规范化公式集合
```

# 第一张图的推荐填写方式

## `statement`

建议完整填写题干和选项。题干部分可以先写为：

```text
7. 设函数 f(x,y) 在区域 D={(x,y)|0≤x≤1,0≤y≤1} 上连续，且 f(x,y)=f(y,x)，则 ∬_D f(x,y)dxdy=( )。
```

选项也应继续加入同一个字段，例如：

```text
A. 2lim...；B. 1/2 lim...；C. 2lim...；D. 1/2 lim...
```

由于选项公式复杂，人工审核时最好根据原图逐个录入，不建议仅依赖 OCR。

## `latex`

如果暂时只记录题干公式：

```text
D=\{(x,y)\mid 0\le x\le1,\ 0\le y\le1\}; f(x,y)=f(y,x); \iint_D f(x,y)\,dx\,dy
```

如果完整记录选项，建议不要继续把所有内容硬塞进单个 `latex` 字段，而是后续新增：

```text
choices_json
```

例如：

```json
[
  {
    "label": "A",
    "text": "...",
    "latex": "2\\lim_{n\\to\\infty}..."
  },
  {
    "label": "B",
    "text": "...",
    "latex": "\\frac12\\lim_{n\\to\\infty}..."
  }
]
```

对于选择题，一个 `choices_json` 字段比把四个复杂选项全部塞进 `statement` 和 `latex` 更可靠。

# 推荐调整标注表

建议后续给 `problem_annotations.csv` 增加：

```text
choices_json
answer
```

字段职责变为：

| 字段           | 保存内容           |
| -------------- | ------------------ |
| `statement`    | 不含选项的题干     |
| `latex`        | 题干中的规范化公式 |
| `choices_json` | 选择题选项及其公式 |
| `answer`       | 正确选项或最终答案 |

第一张题可以表示为：

```csv
statement="7. 设函数 f(x,y) 在区域……则二重积分为（ ）。"
latex="D=\{...\}; f(x,y)=f(y,x); \iint_D..."
choices_json="[{""label"":""A"",""latex"":""...""}, ...]"
answer="..."
```

## 最终建议

当前阶段：

```text
statement：填写完整题干，公式以 Unicode 或普通文本嵌入
latex：填写题干中全部规范化数学公式
match_type/problem_id：暂时留空
```

等建立 `problems` 题库后：

```text
match_type=exact
problem_id=problem_0001
```

对于选择题，建议尽快增加 `choices_json`，否则复杂选项容易在单个 CSV 字段中混乱。

> 例如，我的statement字段可以写成这样吗
> 7. 设函数 \(f(x,y)\) 在区域  \[
>    D=\{(x,y)\mid 0\le x\le 1,\ 0\le y\le 1\}
>    \]上连续，且 \(f(x,y)=f(y,x)\)，则  \[
>    \iint_D f(x,y)\,dx\,dy=(\quad).
>    \]
>    （A）
>
> \[
> 2\lim_{n\to\infty}\sum_{i=1}^{n}\sum_{j=n+1-i}^{n}
> f\left(\frac{i}{n},\frac{j}{n}\right)\frac{1}{n^2}
> \]（B）
> \[
> \frac{1}{2}\lim_{n\to\infty}\sum_{i=1}^{n}\sum_{j=1}^{n}
> f\left(\frac{i}{n},\frac{j}{n}\right)\frac{1}{n^2}
> \]（C）
> \[
> 2\lim_{n\to\infty}\sum_{i=1}^{2n}\sum_{j=1}^{2n+1-i}
> f\left(\frac{i}{2n},\frac{j}{2n}\right)\frac{1}{n^2}
> \]（D）
> \[
> \frac{1}{2}\lim_{n\to\infty}\sum_{i=1}^{2n}\sum_{j=1}^{i}
> f\left(\frac{i}{2n},\frac{j}{2n}\right)\frac{1}{n^2}
> \]

可以。从内容完整性角度看，这种写法很好，题干、条件、目标和所有选项都被保留下来了。

但如果存放在 CSV 的单个 `statement` 单元格中，需要注意换行、引号和 LaTeX 转义。

## 推荐写法

`statement` 可以保存完整的 Markdown + LaTeX：

```text
7. 设函数 \(f(x,y)\) 在区域
\[
D=\{(x,y)\mid 0\le x\le 1,\ 0\le y\le 1\}
\]
上连续，且 \(f(x,y)=f(y,x)\)，则
\[
\iint_D f(x,y)\,dx\,dy=(\quad).
\]

（A）
\[
2\lim_{n\to\infty}\sum_{i=1}^{n}\sum_{j=n+1-i}^{n}
f\left(\frac{i}{n},\frac{j}{n}\right)\frac{1}{n^2}
\]

（B）
\[
\frac{1}{2}\lim_{n\to\infty}\sum_{i=1}^{n}\sum_{j=1}^{n}
f\left(\frac{i}{n},\frac{j}{n}\right)\frac{1}{n^2}
\]

（C）
\[
2\lim_{n\to\infty}\sum_{i=1}^{2n}\sum_{j=1}^{2n+1-i}
f\left(\frac{i}{2n},\frac{j}{2n}\right)\frac{1}{n^2}
\]

（D）
\[
\frac{1}{2}\lim_{n\to\infty}\sum_{i=1}^{2n}\sum_{j=1}^{i}
f\left(\frac{i}{2n},\frac{j}{2n}\right)\frac{1}{n^2}
\]
```

这相当于保存“完整题目的规范化转写”。

## CSV 中必须整体加引号

由于这个字段包含：

- 逗号；
- 换行；
- LaTeX 反斜杠；
- 中文标点；

CSV 中整个 `statement` 字段必须由双引号包围：

```csv
art_0001,...,"7. 设函数 \(f(x,y)\) 在区域
\[
D=\{(x,y)\mid 0\le x\le 1,\ 0\le y\le 1\}
\]
上连续……
",...
```

建议不要手工编辑 CSV 原始文本，而是在 Excel、LibreOffice 或 Python 的 `csv` 模块中写入，否则容易破坏行结构。

Python 写入时：

```python
import csv

with open("problem_annotations.csv", "w", encoding="utf-8-sig", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    writer.writerow({
        "artifact_id": "art_0001",
        "statement": statement,
    })
```

`csv` 模块会自动处理换行和引号。

## `statement` 与 `latex` 会有部分重复

采用这种完整写法后：

- `statement` 保存完整的 Markdown/LaTeX 题目；
- `latex` 不应再简单重复整个 `statement`。

建议 `latex` 保存结构化公式列表，例如 JSON：

```json
[
  {
    "role": "domain",
    "latex": "D=\\{(x,y)\\mid 0\\le x\\le1,\\ 0\\le y\\le1\\}"
  },
  {
    "role": "symmetry_condition",
    "latex": "f(x,y)=f(y,x)"
  },
  {
    "role": "target",
    "latex": "\\iint_D f(x,y)\\,dx\\,dy"
  }
]
```

选项也可以包含进去：

```json
[
  {
    "role": "choice",
    "label": "A",
    "latex": "2\\lim_{n\\to\\infty}\\sum_{i=1}^{n}\\sum_{j=n+1-i}^{n}..."
  },
  {
    "role": "choice",
    "label": "B",
    "latex": "\\frac{1}{2}\\lim_{n\\to\\infty}..."
  }
]
```

不过把 JSON 塞进 CSV 的单元格会出现较多双引号转义。因此第一版可以采用更简单的约定：

```text
statement = 完整 Markdown + LaTeX 题目
latex = 题干核心公式，用分号分隔
```

例如：

```text
D=\{(x,y)\mid 0\le x\le1,\ 0\le y\le1\}; f(x,y)=f(y,x); \iint_D f(x,y)\,dx\,dy
```

## 更规范的长期方案

后续正式建立数据库时，建议拆成：

```text
problems
problem_formulas
problem_choices
```

### `problems`

```json
{
  "problem_id": "problem_0001",
  "statement": "设函数……则二重积分为（ ）。",
  "question_type": "multiple_choice"
}
```

### `problem_formulas`

```json
[
  {
    "problem_id": "problem_0001",
    "formula_no": 1,
    "role": "domain",
    "latex": "D=\\{...\\}"
  },
  {
    "problem_id": "problem_0001",
    "formula_no": 2,
    "role": "condition",
    "latex": "f(x,y)=f(y,x)"
  }
]
```

### `problem_choices`

```json
[
  {
    "problem_id": "problem_0001",
    "label": "A",
    "content_latex": "2\\lim_{n\\to\\infty}..."
  }
]
```

这样比把所有内容塞进一个字段更方便：

- 查询选项；
- 比较公式；
- 验证答案；
- 建立公式索引；
- 修改某个选项；
- 生成任务和 ground truth。

## 你这段内容还需要核对一处

你写的 C 选项是：

```latex
\sum_{i=1}^{2n}\sum_{j=1}^{2n+1-i}
```

从图片看，外层求和的上界更像：

```latex
2n
```

这一点没有问题，但复杂上下标很容易人工转写错误。建议你逐项核对：

- A：`j=n+1-i` 到 `n`；
- B：`i,j` 都从 `1` 到 `n`；
- C：`i=1` 到 `2n`，`j=1` 到 `2n+1-i`；
- D：`i=1` 到 `2n`，`j=1` 到 `i`。

另外，图片中的 C、D 系数排版可能包含：

```latex
\frac{1}{n^2}
```

需要确认它确实不是：

```latex
\frac{1}{(2n)^2}
```

这里涉及题目含义，必须以原图为准。

## 结论

你的 `statement` 写法可以采用，而且适合作为完整题目转写。建议约定：

```text
statement：完整 Markdown + LaTeX，包含题干和选项
latex：仅保存规范化核心公式，供搜索和公式匹配
```

正式数据库阶段再把选择题选项拆到独立的 `problem_choices` 表。

> 那你可以帮我写到csv里吗，按照statement：完整 Markdown + LaTeX，包含题干和选项
> latex：仅保存规范化核心公式，供搜索和公式匹配

<details><summary>2 previous messages</summary>

> 我会把第一张图的完整题干与四个选项写入 `statement`，并将题干中的三个核心公式写入 `latex`；其他标注字段保持不变。
>
> 刚才写入脚本末行出现语法错误，文件未被修改。我修正后重新写入并回读验证多行 CSV 字段。
> </details>

已写入 [problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)。

`art_0001` 当前采用：

- `statement`：完整 Markdown + LaTeX，包含题干和 A–D 四个选项；
- `latex`：只保存三个核心公式：
  - 积分区域；
  - 对称条件；
  - 目标二重积分。

当前仍保持：

```text
annotation_status = pending_review
```

请重点复核四个选项的求和上下界和系数。确认与原图一致后，可将其改为 `verified`。

> 按照相同的逻辑，把第2-10张图片也进行标注

<details><summary>3 previous messages</summary>

> 我会逐张查看第 2–10 张图片，按与第 1 张相同的规则填写完整 `statement`、核心 `latex`、题型、知识点、区域数和图形标记；不确定处会保留待审核说明。
>
> 第 2–6、9–10 张已能清晰读取；第 7、8 张在批量展示时未成功渲染，我单独读取后再统一写入，避免漏标或猜测。
>
> 九张图片均确认是单一、清晰的数学题区域，且不含独立图形。我现在写入完整题干/选项与核心公式，并保留 `pending_review` 供你复核复杂公式。
> </details>

已按第 1 张图片的相同规则，完成第 2–10 张图片的初步标注：

[problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)

已填写：

- 完整 Markdown + LaTeX 的 `statement`
- 用于检索的核心公式 `latex`
- `topic`
- `question_type`
- `region_count=1`
- `has_diagram=false`
- `requires_confirmation=false`

题目涉及：

- 微分方程
- 极限与可导性
- 偏微分方程
- 二重积分
- 条件极值
- 重心计算
- 积分不等式
- 弧长与函数极值
- 反常积分

目前第 1–10 张仍统一为：

```text
annotation_status = pending_review
```

请重点复核：

- 第 4 张偏微分方程的各偏导项；
- 第 5 张指数中的绝对值分式；
- 第 8 张四个积分不等式的方向；
- 第 9 张不定积分形式；
- 第 10 张四个命题的积分与极限表达。

确认无误后可改为 `verified`。

> 已经确认无误，改为verified并相应修改剩余地方

<details><summary>1 previous message</summary>

> 我会把第 1–10 张的题目标注状态改为 `verified`，清理“待复核”备注，并检查这些记录是否还残留待审核标记。
> </details>

已更新 [problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)。

第 1–10 张图片现在均为：

```text
annotation_status = verified
```

备注同步修改为：

```text
题干、选项、核心公式及分类已人工复核。
```

第 11–30 张仍保持 `pending_review`，等待后续标注。

> 下一步，该怎么做

下一步应先完成剩余 20 张图片的题目内容标注，再开始构建正式数据库。

当前状态是：

```text
30 张图片已登记
30 张来源已标注
第 1–10 张题目内容已标注并 verified
第 11–30 张仍 pending_review
```

## 推荐下一步

### 1. 标注第 11–30 张图片

继续填写：

```text
topic
question_type
region_count
has_diagram
statement
latex
requires_confirmation
annotation_status
```

这批图片中要特别注意：

- `12.jpg` 来源记录包含第 8、9、10 三道题，`region_count` 很可能是 3；
- JPG 图片分辨率较大，可能包含整页试卷或多个区域；
- 高考题可能带几何图、函数图像或统计图；
- 中考题可能包含选择题选项、表格和图形；
- 图片内容不完整时应设置 `requires_confirmation=true`。

完成后应确保：

```text
30 条 annotation_status = verified
```

### 2. 分配规范化 `problem_id`

完成标注后，为每个独立题目创建稳定 ID：

```text
problem_0001
problem_0002
...
```

需要注意 `12.jpg` 如果包含三道题，应生成三个题目 ID：

```text
problem_0012_01
problem_0012_02
problem_0012_03
```

因此，当前“一张图片一行”的 `problem_annotations.csv` 可能需要改为：

```text
一个题目区域一行
```

例如：

```csv
art_0012,12.jpg,1,...,question_no=8,problem_0012_01
art_0012,12.jpg,2,...,question_no=9,problem_0012_02
art_0012,12.jpg,3,...,question_no=10,problem_0012_03
```

建议增加：

```text
region_index
```

否则无法区分同一图片中的三道题。

### 3. 建立规范化题库

从审核完成的标注表生成：

```text
normalized/problems.json
```

每个题目对象包含：

```json
{
  "problem_id": "problem_0001",
  "artifact_id": "art_0001",
  "region_index": 1,
  "statement": "...",
  "latex": "...",
  "subject": "math",
  "grade_band": "postgraduate",
  "exam_type": "postgraduate_entrance_exam",
  "year": 2026,
  "topic": "multivariable_calculus.double_integral_riemann_sum",
  "question_type": "multiple_choice"
}
```

### 4. 建立区域 ground truth

建立：

```text
fixtures/ground_truth/
```

每张图片一个 JSON：

```text
art_0001.json
art_0002.json
...
```

内容包括：

```json
{
  "artifact_id": "art_0001",
  "expected_regions": [
    {
      "region_index": 1,
      "region_type": "question",
      "problem_id": "problem_0001",
      "statement": "...",
      "latex": "...",
      "requires_confirmation": false
    }
  ]
}
```

这是后续验证 `detect_content_regions` 和 `recognize_content` 的依据。

### 5. 补充标准答案与解析

创建：

```text
normalized/solutions.json
```

需要录入：

```text
problem_id
final_answer
solution_steps
knowledge_points
solution_source
verification_status
```

如果没有标准解析，可以：

- 使用官方答案；
- 使用权威解析；
- 人工整理并复核；
- 标记为 `third_party_verified`。

不建议直接让 LLM 生成后未经检查就标为 `verified`。

### 6. 修改 `schema.sql`

等实际标注结构稳定后，将 schema 扩展为：

```text
sources
artifacts
artifact_regions
recognition_runs
recognition_corrections
learning_objects
problems
problem_occurrences
solutions
solution_steps
object_matches
audit_log
```

其中应该明确：

```text
一张 artifact
→ 多个 region
→ 多个 learning_object/problem
```

### 7. 改造 `seed.py`

将当前硬编码的一条示例替换为批量导入：

```text
asset_manifest.csv
source_annotations.csv
problem_annotations.csv
problems.json
solutions.json
ground_truth/*.json
```

### 8. 实现第一批工具

推荐优先实现：

```text
get_artifact_metadata
detect_content_regions
recognize_content
get_recognition_result
create_learning_object
search_matching_problems
get_problem
get_solution
```

第一版识别工具可以读取固定 fixture，不必马上接真实 OCR。

## 最优执行顺序

```text
1. 标注第 11–30 张
2. 增加 region_index
3. 为每道题分配 problem_id
4. 生成 problems.json
5. 生成 ground_truth JSON
6. 补充 solutions.json
7. 更新 schema.sql
8. 更新 seed.py
9. 实现工具
10. 编写任务和验证器
```

因此，当前最直接的下一项工作是：

> 按照第 1–10 张的规则，继续标注第 11–30 张图片，并对一图多题的图片增加 `region_index`、拆成多行。

> 那现在帮我按照之前相同的规范，填写11-30的题目内容标注，并考虑一图多题的情况

<details><summary>10 previous messages</summary>

> 我会先逐张检查第 11–30 张图片，识别一图多题并确定区域拆分；随后按“一道题一行”的规范写入标注表，新增 `region_index` 来关联同一图片中的多道题。
>
> 拼图只成功显示了 26–30；我改为逐张加载 11–25，优先保证公式与图形信息准确。
>
> 这些 JPG 体积较大导致界面拒绝渲染。我会生成单张压缩预览并分批查看，同时保留原图作为标注依据。
>
> 当前界面对这些 JPG 仍无法显示。我将检查本机 OCR 能力并对 11–25 做离线文本提取；复杂图形题再结合缩略图像素信息保守标注。
>
> 本机没有 OCR。最后尝试把压缩预览转为 PNG（之前 PNG 可正常显示）；若成功，我会继续逐张准确录入。
>
> 我先完成原生 PNG 的第 21–25 张，再处理大图 JPG；这样可把可可靠识别的部分先推进。
>
> 第 21–25 张已清晰读取。对于第 11–20 张大图，我会将每张切成若干小块查看，避免压缩预览处理失败，并据此识别一图多题。
>
> 切片仍因宽度/编码被界面拒绝。我再缩到与可显示 PNG 相同的宽度；这是最后一个纯本地视觉方案。
>
> 可显示的图片都在约 40KB 以下。我将大图预览进一步二值化压缩到小体积，再读取 11–20。
>
> 这些 JPG 很可能带有异常色彩配置，普通灰度转换把内容抹掉了。我会检查像素范围并纠正转换后再读取。
> </details>

目前我还没有写入第 11–30 张的标注，原因是第 11–20 张 JPG 无法在当前视觉通道中可靠显示，不能安全地人工转写复杂数学公式。为避免把错误题干写入数据库，我没有猜测这些内容。

已确认可以继续处理的部分：

- 第 21–25 张 PNG 已成功读取；
- 第 26–30 张 PNG/JPG 预览已成功读取；
- 第 11–20 张图片文件本身存在，尺寸和格式正常，但当前大尺寸 JPG 预览无法可靠解析。

建议下一步采用以下任一方式：

1. 将第 11–20 张图片分别压缩为宽度约 `800px` 的 PNG 后重新放入 `raw/assets/`；
2. 每张图片单独上传或提供 OCR 文本；
3. 我先只标注第 21–30 张，再单独处理第 11–20 张。

当前不建议直接把第 11–20 张标为 `verified`，因为 `statement`、`latex` 和一图多题区域信息必须依据原图逐字核对。

> 现在完成了21-25的标注了吗

还没有写入 CSV。

我已经成功读取并确认了第 21–25 张图片的内容，但上一轮为了避免第 11–20 张识别失败导致批量标注不完整，没有将第 21–25 张单独写入 `problem_annotations.csv`。

当前状态：

```text
第 1–10 张：已标注，verified
第 11–20 张：未标注
第 21–25 张：已查看，尚未写入
第 26–30 张：已查看，尚未写入
```

下一步可以先把第 21–30 张按相同规范写入，再单独处理第 11–20 张。

> 先写第21-30张

<details><summary>1 previous message</summary>

> 我先将第 21–30 张按“一张图一个独立题目区域”写入；子问题仍属于同一道题，不拆成多个 region。复杂几何图和统计图会标记 `has_diagram=true`，状态保留待你复核。
> </details>

已完成第 21–30 张图片的初步标注并写入：

[problem_annotations.csv](./AgentWorld2/envs/StudentAssistant/A/A1_multimodal_learning_understanding/normalized/problem_annotations.csv)

已填写：

- 完整 `statement`，包含题干、选项和子问题；
- 核心公式 `latex`；
- `topic`；
- `question_type`；
- `region_count=1`；
- `has_diagram`；
- `requires_confirmation=false`。

其中第 22、24、25、26、28、30 张标记为：

```text
has_diagram=true
```

关于一图多题：这 10 张图片均只有一道独立题目。即使一道题中包含多个子问题或三幅配套图，也仍然是：

```text
region_count=1
```

目前状态统一为 `pending_review`。建议重点复核第 22、23、25、29、30 张的长题干、角度符号和线段比例，确认后再改为 `verified`。

> 已确认，改为verified，并相应地方进行修改

<details><summary>1 previous message</summary>

> 我会把第 21–30 张标注更新为 `verified`，同步清理待复核备注，并检查 1–30 的整体状态分布。
> </details>

已更新第 21–30 张图片的标注状态：

```text
annotation_status = verified
```

备注同步改为：

```text
题干、选项或子问、核心公式及分类已人工复核。
```

当前整体状态：

```text
第 1–10 张：verified
第 11–20 张：pending_review
第 21–30 张：verified
```

共计：

```text
verified: 20
pending_review: 10
```

> 之前11-20是图片太大了吗

是的，主要问题是第 11–20 张 JPG 的分辨率和文件体积明显大于其他图片。

例如：

```text
11.jpg：约 4.0 MB，3715 × 1871
13.jpg：约 3.9 MB，3231 × 1373
18.jpg：约 4.2 MB，3876 × 1284
20.jpg：约 4.1 MB，4030 × 1096
```

相比之下，第 21–30 张 PNG 多数只有几 KB 到几十 KB，能正常通过当前视觉通道展示。

我当时尝试了：

- 直接查看原始 JPG；
- 缩小为 JPEG；
- 转换为 PNG；
- 分块裁剪；
- 灰度和二值化压缩。

但当前工具的图像传递仍未正常解析第 11–20 张预览，因此无法可靠转写复杂题干和公式。图片本身没有损坏，PIL 可以正常读取尺寸和像素。

建议为第 11–20 张生成独立的预览副本，例如：

```text
raw/previews/11.png
...
raw/previews/20.png
```

参数建议：

```text
宽度：800–1200px
格式：PNG 或质量 80 左右的 JPEG
色彩：RGB
单张文件：最好小于 500 KB
```

原始 JPG 继续保留在 `raw/assets/`，预览图只用于人工标注，不替代原始数据。

> 现在按照你说的再试试

<details><summary>1 previous message</summary>

> 我会为第 11–20 张生成适合查看的高质量预览副本，保留原图不变，然后逐张读取并完成题目标注。
> </details>

预览已可读取。第 12 张确实包含 3 道独立填空题，我会拆成 3 行并新增 `region_index`；第 11–20 其余图片各为 1 道题。对第 11、19 等公式仍不够清晰的部分，我会保留待复核标记，不臆造内容。

> 继续

我先查看当前 README 和工作区状态，确认“继续”对应的未完成内容，再接着处理。

> 将本次对话历史整理输出一个md，使得之后我切换环境后能继续推进