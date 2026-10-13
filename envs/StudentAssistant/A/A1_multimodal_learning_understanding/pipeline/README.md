# A1 多模态学习理解环境构建流程

本文档总结 `A1_multimodal_learning_understanding` 环境的构建逻辑、当前实现状态，以及后续如何使用优质轨迹评测 Agent 能力。

## 1. 环境目标

A1 模拟如下真实教育场景：

> 学生上传一张数学题图片，Agent 识别图片中的题目，处理一图多题、文字、公式和数学图形，提取结构化题目内容，分析知识点，并在需要时逐题给出答案和推理过程。

A1 的重点不是把所有能力合并成一个 `solve_problem(image)` 接口，而是将真实 Agent 可能使用的能力拆成多个可观察工具，用于：

- 训练模型学习工具调用和任务规划；
- 记录完整 Agent 轨迹；
- 区分上传、区域检测、OCR、图形理解、知识点分析和解题等错误来源；
- 构造工具依赖图并合成任务；
- 使用标准答案和任务规则进行评测。

## 2. 总体构建链路

```text
原始图片与来源信息
        |
        v
人工标注题目区域、题号、题目文本和图形信息
        |
        v
建立 ground truth 与规范化题库
        |
        v
设计 schema.sql 数据库结构
        |
        v
由 seed.py 将 CSV/JSON/ground truth/solutions 导入 SQLite
        |
        v
实现 tools/ 中的公开工具和隐藏评测器
        |
        v
在 graph.py 中定义工具依赖关系
        |
        v
由 task_generation.py 在工具图上随机游走
        |
        v
补齐前置依赖、实例化参数、生成任务规格
        |
        v
Agent 执行任务并产生真实轨迹
        |
        v
轨迹评测 + 答案评测 + 任务完成度评测
```

## 3. 数据准备

### 3.1 原始素材

原始图片放在：

```text
raw/assets/
```

素材清单位于：

```text
raw/asset_manifest.csv
```

素材清单主要记录：

- `artifact_id`；
- 文件名；
- 存储路径；
- 媒体类型；
- 文件大小、宽高和哈希；
- 收集状态。

来源和出处信息位于：

```text
raw/source_annotations.csv
```

这些信息用于把一张图片与考试类型、年份、地区、来源和验证状态关联起来。

### 3.2 图片标注

对每张图片进行逐题标注，尤其要支持一图多题。每个题目区域至少需要：

- 区域序号；
- `problem_id`；
- 题号；
- 区域类型；
- 边界框（如果已经完成坐标标注）；
- 题目原文；
- LaTeX 或其他公式表达；
- 学科、年级、题型和知识点；
- 是否包含数学图形；
- 是否需要人工确认；
- 标注状态。

区域级 ground truth 位于：

```text
fixtures/ground_truth/art_XXXX.json
```

`expected_regions` 表示一张图片中应当被识别出的题目区域。`expected_region_count` 用于检查区域数量是否与标注一致。

### 3.3 规范化题库

规范化题库位于：

```text
normalized/problems.json
```

它把图片中的题目从“图像区域”提升为可查询的题目对象，主要保存：

- 题目陈述；
- 公式表示；
- 题型；
- 知识点；
- 是否有图形；
- 考试类型、年份和题号；
- 来源和出现位置；
- 标注与审核状态。

同一道题可能在不同图片或不同来源中出现，因此题目对象和图片中的出现记录分开保存。

### 3.4 标准解答

标准答案和解题步骤位于：

```text
normalized/solutions.json
```

标准解答用于隐藏评测，不应该直接出现在 Agent 可见的题目上下文中。当前数据模型支持：

- `final_answer`；
- 分步解题过程；
- 关键步骤；
- 关联知识点；
- 解答来源；
- 验证状态和验证方式。

## 4. Schema 的作用

`schema.sql` 定义 A1 的 SQLite 数据库结构。它把原始素材、题目、区域、识别结果、ground truth、题目出现记录、标准答案、提交记录和审计日志连接起来。

核心表包括：

| 表 | 作用 |
|---|---|
| `sources` | 保存图片或题目来源信息 |
| `artifacts` | 保存用户上传素材和 fixture 素材 |
| `artifact_regions` | 保存图片中的题目区域 |
| `recognition_runs` | 保存 OCR、公式识别和视觉识别运行结果 |
| `recognition_corrections` | 保存识别结果的人工修正 |
| `problems` | 保存规范化题目 |
| `recognition_ground_truth` | 保存区域级识别标准 |
| `problem_occurrences` | 关联题目、图片和区域，支持一题多图或重复出现 |
| `solutions` | 保存标准答案 |
| `solution_steps` | 保存标准解答步骤 |
| `solution_knowledge_points` | 保存解答关联的知识点 |
| `audit_log` | 记录工具调用和评测事件 |

其中：

- `artifact_regions` 解决“图片中有几道题、每道题在哪里”；
- `recognition_ground_truth` 解决“这个区域应当识别成什么”；
- `problems` 解决“这道题作为规范化题目是什么”；
- `solutions` 解决“这道题的标准答案是什么”。

## 5. seed.py 的作用

`seed.py` 是数据库初始化脚本，不负责生成随机任务。

它按照以下顺序读取数据并写入 SQLite：

```text
raw/asset_manifest.csv
raw/source_annotations.csv
normalized/problems.json
normalized/solutions.json
fixtures/ground_truth/*.json
        |
        v
schema.sql 初始化的 SQLite 数据库
```

`env.py` 在构建环境时调用：

```python
conn.executescript((ENV_DIR / "schema.sql").read_text(encoding="utf-8"))
seed(conn, ENV_DIR)
```

因此每次调用 `build()`，都会获得一套按当前数据文件初始化的环境数据库。

## 6. 工具层设计

工具代码位于：

```text
tools/
```

当前 Agent 可见工具为：

```text
upload_artifact
get_artifact
list_artifact_regions
recognize_content
extract_editable_text
assess_content_completeness
get_problem_context
get_artifact_problem_contexts
analyze_diagram
analyze_problem_knowledge
submit_solution
```

工具大致分为四类：

### 6.1 素材管理

```text
upload_artifact
get_artifact
```

模拟用户上传图片和 Agent 查询图片基本信息。

### 6.2 图片与区域理解

```text
list_artifact_regions
recognize_content
extract_editable_text
assess_content_completeness
```

当前实现使用确定性的 fixture 数据模拟 OCR、公式识别和完整性判断。后续接入真实 OCR 或视觉模型时，应尽量保持工具的输入输出契约不变。

### 6.3 题目上下文与教育分析

```text
get_problem_context
get_artifact_problem_contexts
analyze_diagram
analyze_problem_knowledge
```

这些工具只返回题目理解所需的信息，不返回标准答案。

### 6.4 解题提交

```text
submit_solution
```

接收 Agent 提交的最终答案和推理过程。它改变环境状态，因此可以作为轨迹末端的状态变化动作。

隐藏评测器：

```text
evaluate_submission
```

不注册到 `environment["tools"]`，避免 Agent 直接读取标准答案。

## 7. 工具依赖图

工具依赖图的唯一真实来源是：

```text
tools/graph.py
```

该图用于：

1. 任务合成；
2. 工具依赖关系可视化；
3. 检查随机游走是否能覆盖完整流程。

它不属于 Agent 的运行时观察内容，Agent 不需要看到这张图。

边权含义：

| 权重 | 含义 |
|---|---|
| `3` | 强依赖，后一个工具通常需要前一个工具的输出 |
| `2` | 弱依赖，前一个工具的结果可以帮助后一个工具 |
| `1` | 独立或补充关系，用于保持图连通和增加任务变化 |

例如：

```text
upload_artifact
    -> list_artifact_regions
        -> recognize_content
        -> get_problem_context
        -> analyze_diagram
        -> analyze_problem_knowledge
        -> submit_solution
```

图片中的题目区域一般需要先由 `list_artifact_regions` 得到，然后区域级工具通过：

```json
"for_each": "$regions"
```

对每一道题分别执行。

## 8. 任务生成逻辑

任务生成代码位于：

```text
tools/task_generation.py
```

核心流程：

```text
generate_tasks()
  -> random.Random(seed)
  -> generate_task()
  -> build_tool_graph()
  -> random_walk()
  -> refine_tool_sequence()
  -> _select_fixture()
  -> build_execution_plan()
  -> prune_redundant_calls()
  -> 生成 instruction、rubric 等字段
```

### 8.1 随机游走

`random_walk()` 默认从 `upload_artifact` 开始，根据当前工具的出边权重选择下一个工具。原始路径保存在：

```json
"raw_walk": [...]
```

随机游走允许重复访问工具节点，用于模拟真实 Agent 可能出现的重复查询、不同模态识别、状态变化后的再次操作等行为。

### 8.2 前置依赖补齐

`refine_tool_sequence()` 会把随机路径整理成可执行序列，例如：

- 区域级工具之前补充 `upload_artifact`；
- 区域级工具之前补充 `list_artifact_regions`；
- `submit_solution` 之前补充 `get_problem_context`；
- 将 `submit_solution` 延后到序列末端。

### 8.3 图片选择

`_select_fixture()` 从数据库的 `artifacts` 表中随机选择图片素材。因此任务文件中的图片路径是任务生成时选出的 fixture，不是 Agent 自己临时决定的。

例如：

```json
"arguments": {
  "artifact_id": "art_0021",
  "fixture_path": "raw/assets/21.png"
}
```

表示这条任务模拟用户上传 `raw/assets/21.png`。

### 8.4 execution_plan

`execution_plan` 是带有参数绑定的工具调用计划。例如：

```json
{
  "tool": "upload_artifact",
  "arguments": {
    "user_id": "student_task_user",
    "fixture_path": "raw/assets/21.png"
  },
  "save_as": "upload"
}
```

后续工具可以引用前一步输出：

```json
{
  "tool": "list_artifact_regions",
  "arguments": {
    "artifact_id": "$upload.artifact_id"
  },
  "save_as": "regions"
}
```

`$item.region_id` 表示在 `for_each: "$regions"` 循环中当前题目区域的 ID。

### 8.5 任务文件字段

生成文件示例：

```text
generated/tasks_seed_42.json
```

字段含义：

| 字段 | 含义 |
|---|---|
| `task_id` | 任务编号 |
| `instruction` | Agent 可见的自然语言任务 |
| `arguments` | 任务绑定的 fixture 和素材 ID |
| `raw_walk` | 工具图上的原始随机路径 |
| `tool_sequence` | 整理和裁剪后的工具序列 |
| `execution_plan` | 带参数绑定的参考执行计划 |
| `difficulty` | 根据原始游走长度得到的粗粒度难度 |
| `rubric` | 任务要求的工具覆盖和最低步骤信息 |

## 9. seed_42 的含义

```text
tasks_seed_42.json
```

表示这批任务使用随机种子 `42` 生成。

`42`：

- 不是第 42 题；
- 不是数据库编号；
- 不是图片编号；
- 只是随机过程的起点。

在相同数据库、相同工具图、相同 `count` 和相同 `length` 下，重复使用 `seed=42`，通常可以复现相同的图片选择和任务路径。

示例：

```python
environment["generate_tasks"](
    count=30,
    seed=42,
    length=[15] * 20 + [20] * 7 + [25] * 3,
)
```

## 10. 当前任务是否包含验证答案

需要区分三种内容：

### 10.1 任务规格

`generated/tasks_seed_42.json` 主要描述：

- 用户要做什么；
- 使用哪一张 fixture 图片；
- 参考工具调用计划；
- 需要哪些工具；
- 最低完成步骤数。

它不是某次 Agent 执行的完整结果日志。

### 10.2 标准答案

标准答案来自：

```text
normalized/solutions.json
```

写入数据库后保存在：

```text
solutions.final_answer_json
```

Agent 不应通过题目上下文工具直接看到这些答案。

### 10.3 Agent 实际结果

Agent 执行时产生：

- 实际工具调用；
- 工具参数；
- 工具返回值；
- 最终答案；
- 推理过程；
- 提交记录；
- 审计日志。

这些内容才是用于评价模型的真实轨迹。

## 11. 优质轨迹与 Agent 能力评测

当前 `execution_plan` 是由工具图随机游走合成的参考计划。它可以作为任务可执行性的基线，但不能自动等同于“优质轨迹”或“专家轨迹”。

优质轨迹应当满足：

- 工具顺序符合依赖关系；
- 只调用完成任务所需的工具；
- 对一图多题逐题处理；
- 在需要时进行 OCR、公式识别和图形分析；
- 出现识别不完整时能够补救；
- 每道题只提交一次最终答案，除非任务明确要求修订；
- 最终答案和推理过程正确。

建议为每个任务保存两类轨迹：

```text
reference_trajectory
    经过人工或强模型审核的优质轨迹

agent_trajectory
    待测模型实际执行产生的轨迹
```

### 11.1 轨迹层指标

可以评价：

- 必需工具覆盖率；
- 工具依赖是否合法；
- 工具调用顺序；
- 不必要调用数量；
- 重复调用数量；
- 是否正确使用 `for_each`；
- 是否覆盖图片中的全部题目区域；
- 是否成功处理工具错误并恢复；
- 实际步骤数与参考轨迹的差异。

### 11.2 结果层指标

可以评价：

- OCR 文本是否匹配 ground truth；
- 题目区域数量是否正确；
- 完整性判断是否正确；
- 图形实体和关系是否正确；
- 知识点分析是否正确；
- 最终答案是否匹配 `solutions`；
- 推理过程是否存在且满足最低质量要求；
- 是否完成所有题目的提交。

### 11.3 综合奖励示例

```text
总奖励 =
  工具覆盖与依赖合法性
  + 轨迹效率
  + 区域处理完整性
  + OCR/结构化结果正确性
  + 数学答案正确性
  + 推理过程质量
```

当前已经实现的隐藏评测器 `evaluate_submission` 主要检查：

1. Agent 最终答案是否与标准答案一致；
2. Agent 是否提交了非空推理过程；
3. 是否将这次提交判定为完成。

因此，完整的“优质轨迹评测器”仍应在此基础上增加轨迹比较和过程指标。

## 12. 当前实现边界和注意事项

### 12.1 Fixture 工具不等于真实 OCR

当前 `recognize_content` 从 fixture ground truth 返回确定性文本，主要用于验证接口、数据流和任务机制。它不代表真实 OCR 的像素级能力。

后续接入真实 OCR、公式识别模型或视觉模型时，应保留工具接口，并将真实识别结果写入 `recognition_runs`。

### 12.2 图形分析当前依赖标注

当前图形分析主要读取已有标注和规范化数据。它适合先验证 Agent 工作流，不能直接证明模型已经具备真实数学图形识别能力。

### 12.3 任务路径不是自动生成的专家答案

工具图随机游走主要用于丰富任务分布。随机路径可能包含重复调用或不够高效的步骤，需要通过人工、强模型或规则审核后，才能作为优质轨迹。

### 12.4 中文编码

任务生成模板和已生成任务文件中的中文必须统一使用 UTF-8。若出现类似：

```text
璇峰鐞嗘垜
```

应检查 `tools/task_generation.py` 和 `generated/tasks_seed_42.json` 的编码读写方式，并在修复模板后重新生成任务文件。

### 12.5 不再使用的文件

当前工具依赖图的唯一来源是：

```text
tools/graph.py
```

已删除的 `dependencies.json` 和 `indexes/` 不应再作为 A1 的运行时依赖。可视化数据可以由 `tools/export_graph.py` 根据 `graph.py` 重新导出。

## 13. 推荐的实际构建顺序

```text
1. 收集并固定原始图片
2. 建立 asset_manifest.csv 和 source_annotations.csv
3. 标注每张图片的题目区域
4. 建立 fixtures/ground_truth/*.json
5. 建立 normalized/problems.json
6. 建立 normalized/solutions.json
7. 修改并验证 schema.sql
8. 修改并验证 seed.py
9. 实现并测试 tools/
10. 在 graph.py 中定义工具依赖
11. 生成可视化 graph data 和 HTML
12. 生成任务规格
13. 审核并保存优质 reference trajectory
14. 运行 Agent，记录 agent trajectory
15. 使用答案评测和轨迹评测计算奖励
16. 根据失败轨迹补充工具、数据或任务
```

## 14. 最小可运行示例

```python
from env import build

environment = build()

tasks = environment["generate_tasks"](
    count=30,
    seed=42,
    length=[15] * 20 + [20] * 7 + [25] * 3,
)

for task in tasks:
    print(task["task_id"])
    print(task["arguments"]["fixture_path"])
    print(task["tool_sequence"])

environment["close"]()
```

这个调用只生成任务规格。要真正测量 Agent 能力，还需要让 Agent 执行任务、保存实际工具调用和提交结果，然后调用隐藏评测器以及新增的轨迹评测逻辑。
