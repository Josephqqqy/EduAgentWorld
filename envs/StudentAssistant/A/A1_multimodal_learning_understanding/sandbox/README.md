# 候选任务 Sandbox

该目录用于在受控、可复现的环境中验证候选任务的 `execution_plan`。

每个任务都会创建独立的内存 SQLite 数据库，按计划解析参数绑定并调用公开工具。
对于 `for_each: "$regions"`，执行器会逐个题目区域执行对应工具。遇到
`submit_solution` 时，执行器仅在内部读取隐藏标准答案并调用隐藏评测器，用来确认
任务链路可以完成；标准答案和标准推理不会写入验证轨迹。

运行全部候选任务：

```powershell
python -m sandbox.runner generated/tasks_seed_42.json `
  -o generated/tasks_seed_42_validation.json
```

报告中的 `passed` 表示工具、参数绑定、数据和隐藏评测链路均可执行，不代表某个待测
模型已经完成该任务，也不能将这份参考执行记录直接作为训练轨迹。
