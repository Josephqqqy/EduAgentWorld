# A2 知识点与概念学习

## 环境目标

模拟学生向教育 Agent 询问某个知识点、公式、定理、概念或科学现象后，Agent 根据学生的年级、学科、教材版本和理解水平，查询课程标准、教材章节、知识点关系、例子、反例和常见误区，并生成有依据、适龄且易于理解的解释。

A2 的核心不是让工具直接生成整段答案，而是：

```text
工具负责检索事实、教材依据和知识关系
模型负责理解问题、规划调用、综合信息和生成解释
```

## 与其他环境的边界

```text
A1 多模态学习理解
    负责识别学生上传的图片、公式、题目和图形
        |
        v
A2 知识点与概念学习
    负责解释题目涉及的概念、公式、定理和前置知识
```

A2 不负责以下完整业务流程：

- 图片 OCR 和题目区域识别：属于 A1；
- 具体题目的完整解答：属于 A1 当前解题 MVP 或后续练习环境；
- 学生作答判错、渐进提示和重试：属于 B1 或 D1；
- 根据正确率自动选择下一道练习：属于 B2；
- 长期成绩和薄弱点诊断：属于 D2；
- 互联网学习资料搜索与核验：属于 E1；
- 收藏笔记和错题管理：属于 E2；
- 制定长期学习计划：属于 D3。

## 典型任务

- 按指定年级解释一个知识点；
- 解释公式中符号、单位和各部分含义；
- 说明公式、定理或方法的适用条件；
- 使用直观方式解释公式或定理的原理；
- 查询学习某概念需要掌握的前置知识；
- 为缺少前置知识的学生生成补学顺序；
- 比较两个相似或容易混淆的概念；
- 提供生活实例、学科实例和典型正例；
- 提供反例并解释概念边界；
- 识别并澄清常见错误认识；
- 解释自然或科学现象背后的知识；
- 连接定义、公式、图像和应用等多种表示；
- 生成概念关系和阶段学习摘要；
- 定位指定教材版本中的章节和页码；
- 根据学生反馈降低或提高解释难度；
- 在多轮追问中补充例子、前置知识或反例。

## 状态链

```text
接收学生问题
    |
    v
读取年级、学科、教材版本和解释偏好
    |
    v
解析并匹配规范化知识点
    |
    v
判断是否需要教材依据或课程标准
    |
    v
查询定义、前置知识和关联概念
    |
    v
按任务需要查询例子、反例和常见误区
    |
    v
模型综合工具结果并生成适龄解释
    |
    v
提交解释并进行隐藏评测
    |
    v
记录学生反馈和学习会话
```

简单、稳定且不要求特定来源的问题可以由模型直接回答。涉及教材版本、课程标准、出处、前置知识、常见误区或学生上下文时，应调用相应工具。

## 目录框架

当前目录：

```text
A2_concept_learning/
├── raw/                 原始课程标准、教材页、讲义和来源快照
├── normalized/          规范化知识点、章节、关系、例子和误区
├── indexes/             全文检索、别名匹配和知识点关系索引
├── fixtures/            固定学生问题、教材版本和预期结果样例
├── tests/               数据、工具、任务生成和状态迁移测试
└── README.md            环境目标、边界和后续构建说明
```

后续拟扩展为：

```text
A2_concept_learning/
├── raw/
│   ├── curriculum/      课程标准原文及固定快照
│   ├── textbooks/       教材章节、页码和来源材料
│   └── references/      经核验的讲义、术语表和补充资料
├── normalized/
│   ├── concepts.json    规范化知识点及定义
│   ├── relations.json   前置、包含、关联和易混淆关系
│   ├── examples.json    正例、生活实例和学科实例
│   ├── counterexamples.json
│   ├── misconceptions.json
│   └── explanation_profiles.json
├── indexes/
│   ├── concept_aliases.json
│   ├── textbook_sections.json
│   └── concept_graph.json
├── visualization/
│   ├── templates/       参数化 HTML 交互模板
│   ├── schemas/         模板参数 Schema
│   └── tool_graph/      工具依赖图和知识点关系图
├── fixtures/
│   ├── learner_contexts/
│   ├── concept_queries/
│   ├── visualization_configs/
│   └── expected_explanations/
├── tools/
│   ├── concepts.py
│   ├── curriculum.py
│   ├── relations.py
│   ├── examples.py
│   ├── learner.py
│   ├── sessions.py
│   ├── evaluation.py
│   ├── graph.py
│   ├── task_generation.py
│   └── README.md
├── generated/           候选任务及 Sandbox 验证报告
├── sandbox/             候选 execution_plan 执行器
├── pipeline/            A2 数据与任务构建流程
├── tests/
├── schema.sql           SQLite 数据库结构
├── seed.py              可复现数据初始化
├── env.py               环境和公开工具装配入口
└── README.md
```

模型 API 和 Agent Rollout 可以继续作为 Harness 的公共能力建设，不应在每个环境中重复保存真实 API Key。

## 数据库核心内容

### 课程与教材

- 学科、学段和年级；
- 教材版本；
- 课程标准条目；
- 教材章节和页码；
- 学习目标和掌握层级；
- 原始来源、版本、哈希和审核状态。

### 知识点

- 规范化 `concept_id`；
- 标准名称、别名和常见简称；
- 定义、符号和基本性质；
- 适用范围和成立条件；
- 父概念和子概念；
- 前置知识和后续知识；
- 关联概念和易混淆概念；
- 所属教材章节和课程标准。

### 教学内容

- 不同年级的解释版本；
- 正例、生活实例和典型应用；
- 反例和边界条件；
- 常见误区、错误原因和纠正要点；
- 图表、公式和其他表示方式；
- 可用的参数化可视化模板及参数约束；
- 内容来源和人工审核状态。

### 学习上下文

- 稳定、脱敏的学生 ID；
- 当前年级、学科和教材版本；
- 当前学习章节；
- 解释难度和表达偏好；
- 本次概念学习会话；
- 学生反馈和追问记录。

A2 可以保存本次学习过程和学生明确反馈，但不应直接写入“学生已经掌握该知识点”之类的长期诊断结论。

## 拟建公开工具

### 学习上下文

```text
get_learner_context             # 获取学习者年级、教材版本和解释偏好
```

### 知识点定位

```text
search_concepts                 # 根据名称、别名或自然语言搜索知识点
get_concept                     # 获取规范化知识点详情
```

### 教材与课程依据

```text
get_curriculum_requirements     # 查询课程标准要求
locate_textbook_section         # 定位教材章节和页码
retrieve_learning_passages      # 检索相关教材或讲义片段
```

### 知识关系

```text
get_concept_prerequisites       # 查询前置知识
get_related_concepts            # 查询父子、后续、关联和易混淆概念
compare_concepts                # 获取两个概念的结构化差异
```

### 例子和误区

```text
get_concept_examples            # 获取正例、生活实例和典型应用
get_concept_counterexamples     # 获取反例和不适用情形
get_common_misconceptions       # 获取常见误区和纠正要点
```

### 可视化呈现（可选）

```text
get_visualization_template      # 获取适用于指定知识点的可视化模板及参数 Schema
render_concept_visualization    # 使用模板和参数生成可交互的概念演示
compute_visualization_state     # 根据拖动、滑块等输入计算新的图形与数值状态
```

`compute_visualization_state` 只在函数、动态几何或物理仿真等需要可靠数值计算的模板中使用。纯图示模板不必强制调用。

### 会话与提交

```text
record_concept_feedback         # 记录学生对解释的明确反馈
submit_concept_explanation      # 提交最终概念解释
```

隐藏评测器暂定为：

```text
evaluate_concept_explanation
```

隐藏评测器不注册给 Agent，负责使用任务要求、标准知识、必要组成部分和来源约束检查最终解释。

## 模型内部能力与工具职责

以下工作由模型完成：

- 理解学生的自然语言问题；
- 判断是否需要调用工具；
- 处理知识点名称歧义；
- 选择工具及调用顺序；
- 综合多个来源；
- 判断文字解释是否需要可视化辅助；
- 选择合适的可视化模板并填写教学参数；
- 根据学生水平组织语言；
- 生成类比、分步解释和总结；
- 回应学生追问。

以下工作由工具和数据库完成：

- 返回指定教材版本的事实；
- 定位课程标准和教材章节；
- 查询知识点之间的稳定关系；
- 返回经过审核的正例、反例和误区；
- 返回经过验证的可视化模板、参数约束和初始状态；
- 执行必要的数学计算、几何校验和交互状态更新；
- 读取经过授权的学习上下文；
- 保存学习反馈和最终提交；
- 为隐藏评测提供标准数据。

不建议将 `generate_explanation`、`generate_analogy` 或 `write_summary` 直接设计成工具，否则主要教学能力会被工具替模型完成，不利于评测模型的规划、综合和表达能力。

## 参数化可视化设计

表格中的“动画展示”是教育场景对呈现能力的需求，不代表每个知识点都要预制一段固定视频。A2 优先采用“模板固定、参数动态”的参数化 HTML 交互模板：

```text
Agent 理解学生问题
    |
    v
检索概念、教材依据和知识关系
    |
    v
选择经过验证的可视化模板
    |
    v
填写函数、点位、范围、标注和交互控件等参数
    |
    v
渲染工具生成交互页面
    |
    v
学生操作后由计算工具更新图形和数值状态
```

需要预先实现和验证的内容包括：

- 页面结构以及绘图、拖动、滑块、播放和重置逻辑；
- 模板支持的参数、类型、范围和必填项；
- 数学计算、图形约束和状态更新规则；
- 模板输出格式和异常处理方式。

每次任务动态产生的内容包括：

- 要展示的函数、数值、点位和坐标范围；
- 要显示的辅助线、公式、结论和重点标注；
- 可用控件、初始状态和演示步骤；
- 与当前年级和学习目标匹配的提示语。

例如，同一个 `secant_to_tangent` 模板可以通过不同参数展示不同函数和切点：

```json
{
  "template_id": "secant_to_tangent",
  "function": "x^2",
  "point_x": 1,
  "initial_delta_x": 1,
  "controls": ["delta_x_slider", "play", "reset"],
  "overlays": ["secant", "tangent", "slope_label"]
}
```

参数化模板的目的不仅是生成动画，也包括：

- 让 Sandbox 离线检查模板是否存在、参数是否合法、计算结果是否正确；
- 让优质轨迹体现模型选择模板和设置参数的能力；
- 避免把临场编写前端代码的能力混入概念教学能力测评；
- 保证不同模型在相同工具能力下得到公平、可复现的比较；
- 降低真实部署时执行任意模型生成代码带来的稳定性和安全风险。

建议首批模板保持通用和少量，例如：

```text
function_graph              # 函数图像、参数变化和表图式联动
secant_to_tangent           # 割线逼近切线
dynamic_circle              # 半径、弦、直径和圆心角
venn_diagram                # 集合的交、并、补和差
number_line                 # 数、区间和不等式
geometry_relation           # 三角形、平行、全等和相似关系
fraction_partition          # 分数切分、拼合和等值关系
```

固定视频或生成式视频适合故事、口型和实验过程等连续叙事场景，不作为 A2 初始数学 MVP 的必要能力。

## 典型工具轨迹

### 通用概念解释

```text
search_concepts
→ get_concept
→ submit_concept_explanation
```

### 指定教材版本

```text
get_learner_context
→ search_concepts
→ locate_textbook_section
→ retrieve_learning_passages
→ get_concept
→ submit_concept_explanation
```

### 前置知识补学

```text
search_concepts
→ get_concept_prerequisites
→ get_concept
→ get_concept_examples
→ submit_concept_explanation
```

### 澄清常见误区

```text
search_concepts
→ get_concept
→ get_common_misconceptions
→ get_concept_counterexamples
→ submit_concept_explanation
```

### 带可视化的概念解释

```text
search_concepts
→ get_concept
→ get_visualization_template
→ render_concept_visualization
→ submit_concept_explanation
```

需要实时数学计算时：

```text
search_concepts
→ get_concept
→ get_visualization_template
→ compute_visualization_state
→ render_concept_visualization
→ submit_concept_explanation
```

工具依赖图用于候选任务合成、路径验证和可视化，不应直接提供给运行任务的 Agent。

## 可验证任务设计

A2 候选任务应优先包含至少一种环境特有约束，使任务不能只靠模型记忆稳定完成，例如：

- 指定年级和教材版本；
- 要求引用教材章节或课程标准；
- 要求列出数据库中记录的前置知识；
- 要求使用指定类型的正例或反例；
- 要求澄清某个已标注的常见误区；
- 要求比较两个规范化概念；
- 要求覆盖定义、条件、例子和误区等指定组成部分；
- 要求为指定概念选择正确的可视化模板并提供合法参数。

隐藏评测可以检查：

- 是否匹配正确知识点；
- 是否使用正确教材版本；
- 是否引用正确章节和依据；
- 是否覆盖必要定义和成立条件；
- 前置知识和概念关系是否正确；
- 正例和反例是否合法；
- 是否准确纠正常见误区；
- 是否选择了支持目标概念和交互要求的模板；
- 可视化参数是否符合 Schema，计算状态是否与标准结果一致；
- 解释难度是否符合目标年级；
- 是否引入超出教材范围或相互矛盾的内容；
- 工具参数、依赖顺序和最终提交是否完整。

不应要求模型机械复现唯一工具路径。只要使用合法信息完成任务，不同但合理的工具序列都应允许通过。

第一阶段不要求实现完整浏览器动画。Sandbox 可以只执行并验证结构化可视化配置，包括模板 ID、参数 Schema、数学结果和依赖顺序。概念数据、候选任务和工具调用稳定后，第二阶段再接入真实 HTML 渲染并增加浏览器交互测试。

## 推荐构建顺序

```text
1. 选择首批学科、年级、教材版本和知识点
2. 收集课程标准、教材章节及固定来源快照
3. 建立知识点、别名、章节和来源标注
4. 建立前置、包含、关联和易混淆关系
5. 建立正例、反例和常见误区数据
6. 建立不同年级的解释要求与评测 Rubric
7. 定义首批参数化模板元数据和参数 Schema
8. 设计并验证 schema.sql
9. 实现并验证 seed.py
10. 实现公开工具和隐藏评测器
11. 构建工具依赖图和可视化
12. 随机游走、参数实例化并生成候选任务
13. 使用 Sandbox 验证候选任务和可视化配置
14. 接入真实 HTML 渲染和浏览器交互测试
15. 接入公共 Agent Rollout Harness
16. 生成、评测和筛选真实 Agent 轨迹
```

## 初始 MVP 建议

首批数据可以继续使用初中数学，但不依赖 A1 的图片数据。建议选取 10 至 20 个关系清晰、容易验证的知识点，例如：

```text
有理数
平方根
一元一次方程
一次函数
一元二次方程
二次函数
全等三角形
相似三角形
勾股定理
圆
```

每个知识点至少准备：

- 一条规范化定义；
- 一组名称和别名；
- 所属年级、教材版本、章节和页码；
- 前置知识；
- 关联或易混淆概念；
- 一个正例；
- 一个反例或不适用情形；
- 一个常见误区及纠正要点；
- 一个适龄解释要求；
- 一个可选的可视化模板映射及合法参数样例；
- 可用于隐藏评测的关键事实。

## 验证重点

- 教材版本不能混用；
- 课程标准和教材来源必须可追溯；
- 知识点别名不能错误匹配；
- 查询前置知识时必须保留关系方向；
- 正例和反例必须符合概念条件；
- 模型不能通过公开工具读取隐藏参考解释；
- 学生上下文只能在授权范围内使用；
- 简单问题允许直接回答，环境特有任务必须正确使用数据工具；
- 不需要可视化的问题不能为了延长轨迹而强制调用渲染工具；
- 可视化模板必须与知识点、年级和教学目标匹配；
- 模板参数必须通过 Schema 校验，数学状态必须可重复计算；
- 模型生成的任意 HTML 或脚本不能直接进入受信任的渲染流程；
- 写操作需要保留会话版本和审计记录；
- Fixture 检索结果不等于模型已经掌握概念。
