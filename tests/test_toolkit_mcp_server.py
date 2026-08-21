from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import toolkit_mcp_server as server  # noqa: E402


class MCPServerCoreTests(unittest.TestCase):
    def test_order_structure_distinguishes_list_and_order_identity(self) -> None:
        schema = server.order_structure_schema()
        hierarchy = schema["hierarchy"]
        self.assertFalse(hierarchy["order_list_group"]["has_independent_object_id_observed"])
        self.assertTrue(hierarchy["top_level_order"]["has_order_id"])
        self.assertTrue(hierarchy["stacked_order"]["has_order_id"])
        self.assertFalse(hierarchy["stacked_order"]["may_have_stacked_children"])
        self.assertIn("same global allocator", hierarchy["stacked_order"]["id_rules"])

    def test_distribution_updates_are_unique_and_bounded(self) -> None:
        result = server._distribution_map(
            [{"group_index": 1, "mode": "fixed", "fixed_interval_seconds": 420}]
        )
        self.assertEqual(result[1]["fixed_interval_seconds"], 420)
        with self.assertRaises(ValueError):
            server._distribution_map([{"group_index": 10, "mode": "fixed"}])
        with self.assertRaises(ValueError):
            server._distribution_map([{"group_index": 1}, {"group_index": 1}])

    def test_zip_output_is_new_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "rules.zip"
            result = server.write_script_mod(
                {"id": "mcp_rules", "garage_join": True}, str(target)
            )
            self.assertTrue(target.is_file())
            self.assertTrue(result["atomic_write_verified"])
            self.assertEqual(len(result["sha256"]), 64)
            with self.assertRaises(ValueError):
                server.write_script_mod(
                    {"id": "mcp_rules", "garage_join": True}, str(target)
                )

    def test_vehicle_preview_includes_physics_without_writing(self) -> None:
        result = server.preview_vehicle_mod(
            {"model_id": "mcp_emu", "model_name": "MCP EMU"}
        )
        self.assertEqual(result["mod_id"], "mcp_emu")
        self.assertGreater(result["physics"][0]["cars"], 0)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "official MCP SDK not installed")
class MCPProtocolTests(unittest.TestCase):
    def test_official_client_lists_and_calls_tools(self) -> None:
        async def run() -> None:
            from mcp import Client

            mcp_server = server.create_mcp_server()
            async with Client(mcp_server) as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("order_structure_schema", names)
                self.assertIn("inspect_order_lists", names)
                self.assertIn("write_order_plan_new_save", names)
                self.assertIn("scan_vehicle_mods", names)
                result = await client.call_tool("order_structure_schema", {})
                self.assertFalse(result.is_error)
                self.assertIsNotNone(result.structured_content)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
