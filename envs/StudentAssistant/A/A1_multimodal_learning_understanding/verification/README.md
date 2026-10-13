# A1 答案验证器

本目录是 harness 内部验证逻辑，不是 Agent 可调用的工具。`tools/evaluation.py`
读取隐藏的 `solutions.final_answer_json`，调用 `verify_answer(actual, expected,
question_type=...)`；验证结果仅写入私有评估和轨迹，不返回给模型。

## 环境与测试

项目根目录的 `requirements.txt` 声明 SymPy 依赖。使用项目虚拟环境：

```powershell
.\eduworld\Scripts\python.exe -m pip install -r requirements.txt
.\eduworld\Scripts\python.exe -m unittest discover -s envs/StudentAssistant/A/A1_multimodal_learning_understanding/tests -q
```

在 macOS/Linux 上，解释器路径为 `./eduworld/bin/python`。批量运行脚本会优先
查找项目的 `eduworld`，也可通过 `PYTHON` 环境变量指定解释器。

## 标准答案格式

旧版字符串答案仍可使用；复杂答案建议逐题迁移为结构化 JSON。例如：

```json
{
  "schema_version": "1.0",
  "answer_type": "multipart",
  "parts": [
    {"part_id": "part_1", "answer_type": "expression", "value": "2*pi"},
    {"part_id": "part_2", "answer_type": "proof_conclusion",
     "value": "QM parallel plane PBD"}
  ]
}
```

支持的 `answer_type`：`choice`、`multiple_choice`、`numeric`、`expression`、
`interval`、`inequality`、`proof_conclusion`、`multipart`。区间和不等式标准答案
须提供 `variable`，如 `{"answer_type":"interval","variable":"n",
"value":"(4,+infinity)"}`。数值答案可选 `unit`、`absolute_tolerance`；
多小问用 `part_id` 对应模型提交的对象键，可用 `required: false` 标记选答题。

## 验证边界

依次尝试旧规则、题型专用比较和受限 SymPy 表达式/集合比较。支持常见四则、
有限幂、根式、`pi`、区间和一元不等式；输入不是 Python 代码，不使用 `eval`。
未声明变量或超出解析范围的表达式不自动判错。自然语言证明目前只能精确
匹配声明的结论，不能验证证明过程是否严谨。仅对明确标为（1）、（2）的短
文本做保守分段；长篇自由文本中的小问答案不会被猜测抽取，建议模型提交结构化对象。

返回状态为 `correct`、`incorrect`、`needs_review` 或 `invalid_reference`。
后两者表示无法可靠判定或参考答案无效；不产生最终奖励，也不进入已完成
或已失败的答案统计。任务策略违规（如重复或禁止提交）仍可独立判为失败。
诊断只供离线审查，不向 Agent 暴露。LLM Judge 不直接决定最终奖励。

## 历史轨迹离线复评

在 A1 目录运行：

```powershell
& "F:\CODE\AgentWorld2\eduworld\Scripts\python.exe" -m verification.reassess generated/rollouts/batch_20260923_142909 generated/rollouts/reassessment_20260923_142909_v2 --tasks generated/tasks_seed_42.json
```

每次指定**新的**输出目录；脚本拒绝覆盖已有报告。它只重新验证原状态为
`needs_review` 的提交，按原候选任务中的私有 rubric 重算状态，不调用模型，
不改变历史轨迹或已完成任务。输出 `reassessment.json` 和
`manual_review_queue.json`；后者的 `human_decision` 应由人工核对后填写。
本次试验产生的 `reassessment_20260923_142909_v1` 未载入原始 rubric，
**结论无效**；使用 `v2` 报告。
