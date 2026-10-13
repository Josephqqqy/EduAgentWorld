"""Export the A1 tool dependency graph for offline visualization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph import build_tool_graph


TOOL_LABELS = {
    "upload_artifact": ("上传学习材料", "上传学生提供的图片或 PDF 等学习素材"),
    "get_artifact": ("查询学习材料", "查询已上传学习材料的基本信息"),
    "list_artifact_regions": ("列出题目区域", "识别一张图片中包含的题目区域"),
    "recognize_content": ("识别题目内容", "识别题目文字、数学表达式和结构化内容"),
    "extract_editable_text": ("导出可编辑文本", "将题目整理为 Markdown 和 LaTeX 等可编辑文本"),
    "assess_content_completeness": ("判断题目完整性", "判断题目内容是否完整，并指出可能缺失的部分"),
    "get_problem_context": ("获取单题上下文", "获取某道题的规范化题目、元数据和解题上下文"),
    "get_artifact_problem_contexts": (
        "获取图片全部题目",
        "按题目区域顺序获取一张图片中的全部题目上下文",
    ),
    "analyze_diagram": ("分析数学图形", "分析题目中的数学图形及其已知关系"),
    "analyze_problem_knowledge": ("分析知识点", "分析题目涉及的主题和解法关联知识点"),
    "submit_solution": ("提交题目解答", "提交某道题的最终答案和推理过程"),
}

KIND_LABELS = {
    "independent": "独立关系",
    "weak": "弱依赖",
    "strong": "强依赖",
}


def graph_to_dict(graph=None) -> dict[str, Any]:
    """Convert the internal graph into JSON-safe visualization data."""
    graph = graph or build_tool_graph()
    nodes = [
        {
            "id": name,
            "label": TOOL_LABELS[name][0],
            "description": TOOL_LABELS[name][1],
        }
        for name in graph.nodes
    ]
    edges = [
        {
            "source": source,
            "target": target,
            "kind": relation["kind"],
            "kind_label": KIND_LABELS[relation["kind"]],
            "weight": relation["weight"],
        }
        for (source, target), relation in graph.edges.items()
    ]
    return {
        "title": "A1 多模态学习理解环境工具依赖图",
        "nodes": nodes,
        "edges": edges,
        "edge_kind_labels": KIND_LABELS,
        "edge_weight_legend": {
            "1": "独立关系",
            "2": "弱依赖",
            "3": "强依赖",
        },
    }


def export_graph_data(output_path: str | Path) -> Path:
    """Write the current graph to a UTF-8 JSON file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(graph_to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    path = export_graph_data(root / "visualization" / "tool_graph_data.json")
    print(path)
