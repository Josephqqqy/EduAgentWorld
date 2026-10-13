# A1 工具包

`tools/` 是 A1 多模态学习理解环境的工具实现目录。工具面向“用户提供一张具体学习材料，Agent 对材料进行识别、理解、分析或解答”的任务。

## 工具模块

- `artifacts.py`：上传和查询学生提供的图片、PDF 等学习素材。
- `recognition.py`：列出图片中的题目区域、执行 Fixture 识别、导出可编辑文本、评估题目内容是否完整。
- `solving.py`：获取单题上下文、批量获取一张图片中的多道题上下文、接收 Agent 提交的解答。
- `diagram.py`：返回题目标注中已知的图形信息，并明确当前 Fixture 是否只有元数据。
- `knowledge.py`：根据规范化题库和知识点标注生成题目知识点分析。
- `graph.py`：构建完全连接的加权工具依赖图，并执行随机游走。
- `task_generation.py`：精炼随机游走、实例化参数并合成公开任务与隐藏评测信息。
- `evaluation.py`：Harness 内部的隐藏评测逻辑，不注册为 Agent 可见工具。
- `common.py`：审计、文件哈希和答案规范化等内部辅助函数。
- `__init__.py`：统一导出公开工具。

## Agent 可见工具

由 `env.py` 注册：

```python
upload_artifact                 # 上传学习材料
get_artifact                    # 查询学习材料
list_artifact_regions           # 列出题目区域
recognize_content               # 识别题目内容
extract_editable_text           # 导出可编辑文本
assess_content_completeness     # 判断题目完整性
get_problem_context             # 获取单题上下文
get_artifact_problem_contexts   # 获取图片中的全部题目
analyze_diagram                 # 分析数学图形
analyze_problem_knowledge       # 分析题目知识点
submit_solution                 # 提交题目解答
```

隐藏评测器 `evaluate_submission` 不会出现在 `environment["tools"]` 中，避免 Agent 直接读取标准答案。

## 当前能力边界

- 一图多题：支持按区域顺序获取每道题的上下文。
- 图片转文本：当前返回确定性的 Fixture 文本和 LaTeX，格式为 Markdown。
- 完整性判断：依据已有标注、识别文本和确认状态判断，不代表真实像素级检测。
- 图形分析：当前可确认是否存在数学图形及其主题类别，但 `entities` 和 `relations` 只有在后续增加独立图形标注后才会填充。
- 知识点分析：返回规范化题库中的主题和解法关联知识点，不返回标准答案或解题步骤。

后续接入真实 OCR、视觉模型或图形标注时，优先保持这些工具的输入输出契约不变，仅替换 Fixture 实现。

## 工具图和任务合成

- 强依赖：权重为 `3`，后一个工具必须依赖前一个工具的输出。
- 弱依赖：权重为 `2`，前一个工具的输出可以作为后一个工具的输入。
- 独立边：权重为 `1`，用于补齐完全连接图并避免随机游走进入死路。

调用示例：

```python
from env import build

environment = build()

task = environment["generate_task"](length=5)
tasks = environment["generate_tasks"](
    count=30,
    seed=42,
    length=[15] * 20 + [20] * 7 + [25] * 3,
)

environment["close"]()
```

每个合成任务包含：

- `instruction`：公开给 Agent 的自然语言任务，不包含工具名或数据库结构。
- `raw_walk`：工具图上的原始加权随机游走。
- `tool_sequence`：补齐前置依赖并保证提交动作为末步后的精炼调用序列，允许重复工具。
- `execution_plan`：为每次调用生成独立 `call_id`，绑定前序工具输出；区域级工具通过 `for_each` 逐题执行。
- `rubric`：Harness 使用的隐藏工具要求和最低步骤数。

`generate_task` 和 `generate_tasks` 属于 Harness 构建与数据合成接口，不属于 Agent 在解题过程中可直接调用的工具。工具图由 `task_generation.py` 在任务合成阶段内部构建和使用，也不会放入运行时环境字典或 Agent 上下文。

## 重复工具调用

随机游走允许再次访问已经经过的工具节点。重复工具不会再按工具名直接删除，因为以下轨迹是合理的：

- 对不同题目区域重复执行同一工具。
- 对同一区域依次执行 OCR、公式和视觉识别。
- 完整性检查后重新识别。
- 环境状态变化后重新查询。
- 对答案进行再次提交或修订。

精炼流程在参数实例化之后执行调用级裁剪：

- 工具名、参数和 `for_each` 范围完全相同，且两次调用之间没有状态变化时，后一次调用视为冗余。
- 同一路径的重复 `upload_artifact` 是幂等调用，会被裁剪。
- `submit_solution` 会改变环境状态，因此重复提交会保留，并允许状态变化后的查询再次执行。
- 同一工具使用不同区域、参数或识别模态时会保留。

因此，`raw_walk` 可以包含重复节点，而 `execution_plan` 只保留具有独立作用的调用。
