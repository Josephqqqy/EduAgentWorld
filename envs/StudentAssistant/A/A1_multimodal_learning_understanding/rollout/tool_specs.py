"""Public model-facing tool contracts for A1."""

from __future__ import annotations


def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_ARTIFACT_ID = {"type": "string", "description": "当前图片的 artifact_id"}
_REGION_ID = {"type": "string", "description": "题目区域的 region_id"}

TOOL_SCHEMAS = (
    _tool("upload_artifact", "登记学生上传的题目图片。", {
        "user_id": {"type": "string", "description": "任务给出的用户 ID"},
        "fixture_path": {"type": "string", "description": "任务给出的图片路径"},
    }, ["user_id", "fixture_path"]),
    _tool("get_artifact", "查询图片的基本信息。", {
        "artifact_id": _ARTIFACT_ID,
    }, ["artifact_id"]),
    _tool("list_artifact_regions", "按顺序列出图片中的所有题目区域。", {
        "artifact_id": _ARTIFACT_ID,
    }, ["artifact_id"]),
    _tool("recognize_content", "识别一个题目区域中的内容。", {
        "region_id": _REGION_ID,
        "modality": {
            "type": "string",
            "enum": ["ocr", "formula", "layout", "vision", "other"],
        },
    }, ["region_id"]),
    _tool("extract_editable_text", "获取一个题目的可编辑文本和可选 LaTeX。", {
        "region_id": _REGION_ID,
        "include_latex": {"type": "boolean"},
    }, ["region_id"]),
    _tool("assess_content_completeness", "检查一个题目的内容是否完整。", {
        "region_id": _REGION_ID,
    }, ["region_id"]),
    _tool("get_problem_context", "获取一个题目的公开上下文，不含答案。", {
        "region_id": _REGION_ID,
    }, ["region_id"]),
    _tool("get_artifact_problem_contexts", "获取图片中的全部题目上下文，不含答案。", {
        "artifact_id": _ARTIFACT_ID,
    }, ["artifact_id"]),
    _tool("analyze_diagram", "分析一个题目已有的数学图形信息。", {
        "region_id": _REGION_ID,
    }, ["region_id"]),
    _tool("analyze_problem_knowledge", "分析一个题目的知识点。", {
        "region_id": _REGION_ID,
    }, ["region_id"]),
    _tool("submit_solution", "提交一个题目的答案与必要推理；一图多题需分别提交。", {
        "region_id": _REGION_ID,
        "final_answer": {"description": "模型给出的最终答案，可以是文本或结构化 JSON"},
        "reasoning": {"type": "string", "description": "非空的解题推理"},
    }, ["region_id", "final_answer", "reasoning"]),
)

_SCHEMAS_BY_NAME = {
    item["function"]["name"]: item["function"]["parameters"]
    for item in TOOL_SCHEMAS
}


def validate_arguments(name, arguments):
    """Reject unknown tools, extra fields and incorrect JSON argument types."""
    if name not in _SCHEMAS_BY_NAME:
        raise ValueError(f"Unknown public tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    schema = _SCHEMAS_BY_NAME[name]
    if set(arguments) - set(schema["properties"]):
        raise ValueError("Unknown tool argument")
    if set(schema["required"]) - set(arguments):
        raise ValueError("Missing required tool argument")
    for key, value in arguments.items():
        property_schema = schema["properties"][key]
        expected = property_schema.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        if "enum" in property_schema and value not in property_schema["enum"]:
            raise ValueError(f"Invalid {key}")
