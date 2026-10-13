import json
import sys
import unittest
from pathlib import Path


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class GraphExportTests(unittest.TestCase):
    def test_export_contains_all_nodes_and_weighted_edges(self):
        from tools.export_graph import graph_to_dict
        from tools.graph import build_tool_graph

        data = graph_to_dict()
        graph = build_tool_graph()

        self.assertEqual(
            {node["id"] for node in data["nodes"]},
            set(graph.nodes),
        )
        self.assertEqual(len(data["edges"]), len(graph.edges))
        self.assertEqual(
            next(
                edge
                for edge in data["edges"]
                if edge["source"] == "upload_artifact"
                and edge["target"] == "list_artifact_regions"
            )["weight"],
            3,
        )

    def test_export_writes_utf8_json(self):
        from tools.export_graph import export_graph_data

        output = self._temporary_path()
        try:
            path = export_graph_data(output)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["title"], "A1 多模态学习理解环境工具依赖图")
            self.assertTrue(any(node["label"] == "上传学习材料" for node in data["nodes"]))
        finally:
            output.unlink(missing_ok=True)

    def _temporary_path(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            suffix=".json",
            dir=ENV_DIR,
            delete=False,
        )
        handle.close()
        return Path(handle.name)


if __name__ == "__main__":
    unittest.main()
