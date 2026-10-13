# A1 分层答案验证器设计

设计日期：2026-09-23

## 1. 背景

A1 环境当前由 `tools/evaluation.py` 读取隐藏标准答案，再调用
`tools/common.py` 中的 `answers_equivalent()` 进行比较。现有实现主要支持：

- Unicode 和空白规范化后的精确匹配；
- 有限的单选、多选答案提取；
- 二元结果：正确或错误。

这种比较方式会把下列情况误判为错误：

- 答案包含完整推导，而标准答案只保存最终表达式；
- 数值带单位，例如 `1800 人` 与 `1800`；
- 等价公式，例如 `-3∛2/8` 与 `-3/(4∛4)`；
- 等价区间和不等式，例如 `n > 4` 与 `(4,+∞)`；
- 多小问自由文本与字典形式标准答案之间的比较。

新验证器需要降低这类假阴性，同时避免把无法可靠判断的答案直接判错。

## 2. 目标

本次改造实现以下能力：

1. 保留现有保守规则，作为成本最低、风险最小的第一层比较。
2. 按答案类型调用选择题、数值、公式、区间、不等式和多小问比较器。
3. 使用 SymPy 判断受支持数学表达式和集合是否等价。
4. 支持结构化多小问标准答案，并继续兼容现有字符串和临时字典答案。
5. 将无法可靠判定的答案标记为 `needs_review`。
6. 不使用 LLM Judge 直接产生最终奖励。
7. 保持 `evaluate_submission()` 为 harness 私有接口，不向 Agent 暴露标准答案或验证细节。

## 3. 非目标

本次暂不实现：

- 使用 LLM Judge 自动判定证明题、开放题是否正确；
- 对自然语言证明进行完整的形式化证明验证；
- 一次性迁移全部标准答案；
- 自动修复缺少选项、题干残缺等源数据；
- 训练奖励的连续分值设计；
- 把隐藏标准答案或验证器诊断反馈给正在作答的模型。

## 4. 目录结构

验证器实现放在 A1 环境的 `verification/` 目录中。`verified/` 不用于实现代码，
因为该名称更容易被理解为“已经通过验证的数据输出”。

```text
envs/StudentAssistant/A/A1_multimodal_learning_understanding/
├── verification/
│   ├── __init__.py
│   ├── models.py
│   ├── normalize.py
│   ├── choice.py
│   ├── numeric.py
│   ├── symbolic.py
│   ├── interval.py
│   ├── multipart.py
│   ├── dispatcher.py
│   └── README.md
├── tools/
│   ├── common.py
│   └── evaluation.py
└── tests/
    └── test_verification.py
```

各模块职责：

- `models.py`：定义验证状态和统一结果对象。
- `normalize.py`：承接现有字符串规范化与保守规则。
- `choice.py`：处理单选和多选答案。
- `numeric.py`：处理整数、小数、分数、近似值、容差和简单单位。
- `symbolic.py`：处理受限数学表达式解析与符号等价。
- `interval.py`：处理区间、集合和一元不等式解集。
- `multipart.py`：逐小问验证并汇总结果。
- `dispatcher.py`：识别答案类型并按层调用比较器。
- `README.md`：记录支持范围、安全约束和标准答案格式。

## 5. 验证结果

内部统一返回以下结构：

```json
{
  "status": "correct",
  "score": 1.0,
  "match_method": "symbolic_equivalence",
  "needs_review": false,
  "part_results": [],
  "missing_parts": [],
  "diagnostics": []
}
```

`status` 只允许：

- `correct`：可以确定答案等价；
- `incorrect`：可以确定答案不等价或缺少必要答案部分；
- `needs_review`：解析失败、答案类型不支持，或现有规则无法可靠决定；
- `invalid_reference`：标准答案格式非法或题目参考数据自身不足。

`score` 在第一版中保持离散：

- `correct` 为 `1.0`；
- `incorrect` 为 `0.0`；
- `needs_review` 和 `invalid_reference` 为 `null`。

`diagnostics` 仅写入 harness 私有轨迹和审计结果，不作为工具观察返回给 Agent。

## 6. 分层验证流程

`dispatcher.verify_answer(actual, expected, context)` 按以下顺序执行：

1. **规则层**：使用现有规范化精确比较和保守的选择题别名比较。
2. **题型层**：根据结构化标准答案中的 `answer_type`，或题目的
   `question_type`，调用专用比较器。
3. **数学层**：对公式、数值、区间和不等式调用受限 SymPy 比较器。
4. **兜底层**：若没有比较器可以可靠得出结论，返回 `needs_review`。

只要前一层已经得到可靠的 `correct` 或 `incorrect`，后续层不再运行。
解析失败不等于答案错误；解析异常会转成诊断并继续尝试适用的下一层，最终仍无法
判断时返回 `needs_review`。

## 7. 专用比较器

### 7.1 选择题

支持：

- `B`、`答案 B`、`选 B` 等单选表达；
- `ACD`、`A,C,D`、`A C D` 等多选表达；
- 多选项按集合比较，不要求顺序一致。

只有当标准答案明确声明为 `choice` 或 `multiple_choice` 时，才允许从长文本中提取
字母，防止把数学变量 `A`、`B` 误识别为选项。

### 7.2 数值

支持：

- 整数、小数、分数和百分数；
- 可选绝对误差或相对误差；
- 常见简单单位规范化，例如 `1800 人` 与无量纲标准值 `1800`。

单位处理第一版采取白名单策略。若答案双方存在不兼容单位，返回 `incorrect`；
若单位无法识别，返回 `needs_review`。

### 7.3 符号表达式

表达式经过受限预处理后交给 SymPy：

- 常见 LaTeX 分数、根式、圆周率和无穷符号；
- 隐式乘法；
- 常见中文数学标点；
- 等式右侧最终结果提取。

优先比较 `simplify(actual - expected) == 0`。对可能涉及定义域、分母为零、分段函数
或多值函数的表达式，不能仅凭化简结果可靠判定时返回 `needs_review`。

### 7.4 区间与不等式

将区间和一元不等式转换为 SymPy 集合后比较：

- `x > 4` 与 `(4,+∞)`；
- `2 < r < 8` 与 `(2,8)`；
- 闭区间、开区间和有限并集。

变量不明确、多变量不等式或解析存在歧义时返回 `needs_review`。

### 7.5 多小问

结构化标准答案按 `part_id` 逐项比较。第一版要求所有必答小问均为 `correct`，
整体才为 `correct`：

- 任一必答小问明确错误：整体 `incorrect`；
- 没有明确错误，但至少一问无法判断：整体 `needs_review`；
- 缺少必答小问：整体 `incorrect`；
- 所有必答小问正确：整体 `correct`。

证明题小问第一版只验证明确声明的最终结论，不尝试自动判断整段证明是否严谨。
若任务明确要求证明过程，现有 `reasoning_present` 继续检查是否提供推理文本，
但不把“有文字”解释为“证明正确”。

## 8. 标准答案格式与迁移

`solutions.final_answer_json` 已经是合法 JSON 字段，因此数据库表结构不需要立即修改。
新增的推荐格式如下：

### 单值答案

```json
{
  "schema_version": "1.0",
  "answer_type": "expression",
  "value": "2*pi"
}
```

### 数值答案

```json
{
  "schema_version": "1.0",
  "answer_type": "numeric",
  "value": "1800",
  "unit": "人",
  "absolute_tolerance": 0
}
```

### 区间答案

```json
{
  "schema_version": "1.0",
  "answer_type": "interval",
  "variable": "r",
  "value": "(2, 8)"
}
```

### 多小问答案

```json
{
  "schema_version": "1.0",
  "answer_type": "multipart",
  "parts": [
    {
      "part_id": "1",
      "answer_type": "expression",
      "value": "2*pi",
      "required": true
    },
    {
      "part_id": "2",
      "answer_type": "proof_conclusion",
      "value": "QM parallel plane PBD",
      "required": true
    }
  ]
}
```

迁移采用渐进方式：

1. 旧字符串继续由规则层处理。
2. 优先迁移当前 rollout 中产生误判的题目。
3. 再迁移多小问、区间、不等式和带单位题目。
4. 每次迁移都增加对应回归测试。
5. 迁移工具只修改明确指定的标准答案，不自动猜测答案类型。

## 9. Harness 集成

`tools/evaluation.py` 保留公共函数：

```python
evaluate_submission(conn, submission)
```

它改为调用 `verification.verify_answer()`，并继续返回旧字段，同时增加新字段：

```json
{
  "answer_correct": true,
  "verification_status": "correct",
  "verification_method": "symbolic_equivalence",
  "needs_review": false,
  "reasoning_present": true,
  "task_completed": true,
  "reward": 1.0
}
```

兼容映射：

- `correct`：`answer_correct=true`；
- `incorrect`：`answer_correct=false`；
- `needs_review`：`answer_correct=null`；
- `invalid_reference`：`answer_correct=null`。

`task_completed` 只有在答案为 `correct` 且满足推理要求时才为 `true`。
`needs_review` 不产生最终奖励，`reward` 为 `null`。

## 10. Rollout 状态

轨迹增加独立状态：

```text
status = needs_review
termination_reason = answer_equivalence_uncertain
```

标准答案或源数据本身无效时使用：

```text
status = needs_review
termination_reason = invalid_reference
```

状态优先级：

1. 运行时或模型 API 错误；
2. 禁止提交、重复提交等明确策略失败；
3. 明确答案错误；
4. 答案或参考数据需要人工检查；
5. 工具或区域要求未完成；
6. 完成。

批处理摘要新增 `needs_review` 计数。`needs_review` 不计入 `completed`、`failed`
或 `incomplete`，便于后续人工审核和基准数据清洗。

## 11. SymPy 安全边界

当前运行环境尚未安装 SymPy。实现阶段需要：

- 增加明确的项目依赖，例如 `sympy>=1.13,<2`；
- 使用 SymPy 官方解析 API 和受控符号表；
- 禁止 Python `eval()`；
- 禁止自动导入模块或按输入解析任意属性；
- 限制允许的函数、符号数量、表达式长度和解析耗时；
- 捕获解析异常并返回 `needs_review`；
- 不把 Agent 输入作为可执行代码。

若运行环境未安装 SymPy，验证器仍可运行规则层和选择题比较器；涉及数学解析的答案
返回 `needs_review`，而不是导致整条轨迹出现 `error`。

## 12. 测试策略

实现采用测试驱动方式，先添加失败测试，再实现比较器。

单元测试至少覆盖：

- 现有精确和选择题规则不回归；
- `1800 人` 等价于结构化数值 `1800`；
- `61/25` 等价于 `2.44`；
- `2(e-1)` 可从完整答案文本中识别；
- `-3∛2/8` 等价于 `-3/(4∛4)`；
- `n > 4` 等价于 `(4,+∞)`；
- `2 < r < 8` 等价于 `(2,8)`；
- 多选答案顺序不影响结果；
- 多小问全部正确、缺失、明确错误和无法判断；
- 非法表达式不会执行代码；
- 不支持的证明内容返回 `needs_review`；
- 无效标准答案返回 `invalid_reference`。

集成测试至少覆盖：

- `evaluate_submission()` 旧字段兼容；
- runner 把不确定答案标记为 `needs_review`；
- 批处理摘要包含独立计数；
- `needs_review` 不产生最终奖励；
- 验证诊断不会进入模型上下文；
- 已知正确、已知错误和工具路径判定维持原有行为。

## 13. 实施顺序

1. 增加验证结果模型和规则层回归测试。
2. 搬迁现有比较逻辑，保持旧接口兼容。
3. 实现选择题和数值比较器。
4. 加入 SymPy 依赖并实现符号、区间和不等式比较器。
5. 实现结构化多小问比较器。
6. 接入 `tools/evaluation.py`。
7. 更新 rollout 状态与批处理摘要。
8. 迁移首批已知误判标准答案。
9. 运行单元测试、集成测试和现有任务回归。

## 14. 验收标准

满足以下条件时认为本次改造完成：

- 现有规则比较仍作为第一层工作；
- 支持选择题、数值、公式、区间、不等式和结构化多小问；
- 无法可靠判断的答案进入独立 `needs_review` 状态；
- LLM Judge 不参与最终奖励；
- SymPy 不可用或解析失败时不会使 rollout 崩溃；
- 当前已知的数学等价误判样例有回归测试；
- 旧标准答案和 `evaluate_submission()` 调用方仍可运行；
- 验证器和隐藏标准答案不会暴露给 Agent。
