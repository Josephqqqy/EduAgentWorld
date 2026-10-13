# A1 Agent Rollout

本目录实现 OpenAI-compatible `/chat/completions` 模型客户端、A1 公开工具 schema、单任务工具调用循环和 JSON 轨迹保存。需要模型支持原生 `tool_calls`；`AGENT_API_TYPE=openai_compatible`。

从项目根目录的 `.env` 读取 `AGENT_API_KEY`、`AGENT_BASE_URL`、`AGENT_MODEL` 和可选参数；同名进程环境变量优先。不要把密钥写入任务、测试或轨迹。根目录 `.gitignore` 忽略 `.env` 和未筛选的 rollout 轨迹。

在 A1 目录下运行一个候选任务（会调用模型 API 并产生用量）：

```powershell
cd "F:\CODE\AgentWorld2\envs\StudentAssistant\A\A1_multimodal_learning_understanding"
python -m rollout.runner generated/tasks_seed_42.json --task-id task_a1_000009 --max-turns 6
```

默认轨迹保存在 `generated/rollouts/`；可用 `--output` 指定路径。每个模型或工具步骤都有连续的 `step_id`（如 `step_0001`）。`status` 可能是 `completed`、`incomplete`（要求提交解答但缺题）、`step_limit`、`token_limit`、`timeout`、`error` 或 `interrupted`。`completed` 仅表示模型结束并满足提交覆盖要求，**不表示答案正确**。轨迹含模型/工具步骤、公开提交、token 用量和私有 `evaluation`；不能直接把未经审查的轨迹当作优质训练样本。

模型仅收到公开任务描述、图片 ID/fixture 路径、公开工具 schema 与工具观察；候选任务的 `execution_plan`、`raw_walk`、`rubric` 和标准答案不进入模型上下文。隐藏评测仅写入轨迹，不作为工具观察返回。当前 `recognize_content` 使用种子数据中的固定识别结果，并非实时 OCR，不能以此评测模型的原始视觉/OCR 能力。

底层客户端也可单独调用：

在 A1 目录下调用：

```python
from rollout import ModelClient, load_config

client = ModelClient(load_config())
reply = client.complete(
    [{"role": "user", "content": "请计算 12 加 30。"}],
    tools=[
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "计算两个数之和",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            },
        }
    ],
    tool_choice="auto",
)
```

`reply.content` 是文本，`reply.tool_calls` 中每项有 `id`、`name` 和已解析的 `arguments`。`reply.message` 可回填到历史；runner 会执行工具并添加对应 `role="tool"`、`tool_call_id` 的观察。`reply.usage`、`reply.latency_ms` 和 `reply.request_id` 用于轨迹统计。

当前仅接受合法 JSON 对象作为工具参数；无效响应会抛出 `ModelClientError`。429 和临时服务错误最多重试两次，401 等请求错误立即失败。不要把异常中的底层响应正文或密钥写入轨迹。

离线测试：

```powershell
cd "F:\CODE\AgentWorld2\envs\StudentAssistant\A\A1_multimodal_learning_understanding"
python -m unittest discover -s tests -v
```
