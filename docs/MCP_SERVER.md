# NIMBY Rails Toolkit MCP Server

`toolkit_mcp_server.py` exposes the toolkit's verified timetable, vehicle and
NimbyScript capabilities to MCP clients. It uses the official Python SDK v2
and local `stdio`; it does not start a network listener.

## Install

```powershell
python -m pip install -r requirements.txt
```

You can verify the Order model without starting MCP:

```powershell
python toolkit_mcp_server.py --describe
```

## Connect an MCP client

Use an absolute path. Clients whose configuration uses the common
`mcpServers` shape can add:

```json
{
  "mcpServers": {
    "nimby-rails-toolkit": {
      "command": "python",
      "args": [
        "C:\\absolute\\path\\NIMBY_Timetable_Toolkit\\toolkit_mcp_server.py"
      ]
    }
  }
}
```

If `python` is not on `PATH`, replace it with the absolute path to
`python.exe`. Do not use `pythonw.exe`: MCP needs stdin/stdout.

## Tools

| Tool | Effect |
|---|---|
| `order_structure_schema` | Explain the verified Schedule → inline group → top-level Order → stacked Order structure. |
| `inspect_order_lists` | Read persisted orders and their individual Order IDs from a save. |
| `preview_order_plan` | Apply edit/insert/stack and offset changes in memory, with structural read-back; writes nothing. |
| `write_order_plan_new_save` | Apply a previewed complete plan to a brand-new save beside the input. Existing paths and the input are rejected. |
| `analyze_save_with_export` | Run the existing read-only save/export health analysis. |
| `scan_vehicle_mods` | Scan built-in, private and Steam Workshop vehicle definitions without modifying them. |
| `get_vehicle_mod` | Load one scanned vehicle mod by its opaque scan token. |
| `preview_vehicle_mod` / `write_vehicle_mod` | Validate arbitrary TrainUnits and compositions, calculate physics, and optionally create a new ZIP. |
| `validate_script_source` | Statically check NimbyScript metadata, structure and known performance/safety hazards. |
| `preview_script_mod` / `write_script_mod` | Generate a checked rules mod in memory or as a new ZIP. |

## Order and stack identity

The verified persisted hierarchy is:

```text
Schedule (0x6 object ID)
└─ inline Order List / offset group (no independent object ID observed)
   ├─ top-level Order (unique positive-even Order ID)
   │  ├─ stacked Order (its own unique Order ID)
   │  └─ stacked Order (its own unique Order ID)
   └─ top-level Order (unique Order ID)
```

Parameter 7 of a top-level Order stores the number of complete child Order
records immediately following it. Children are flat, not recursively nested,
and do not increment the group's top-level count. Existing IDs must be retained;
new top-level and child records obtain IDs from the same global allocator.

## Safety guarantees

- `stdio` only: no unauthenticated HTTP endpoint.
- Read and preview tools do not write files.
- ZIP tools reject existing output paths.
- Save writes reject the input path, reject existing outputs, and require the
  output to remain beside the input save.
- A generated save is compressed, decompressed, byte-compared and written
  atomically, with a manifest placed beside it.
- Unknown Order layouts, invalid IDs, deletion of persisted Orders, recursively
  stacked children, and collateral group changes are rejected.

The game export format does not include the actual vehicle model/composition
assigned to each Train. The MCP server therefore does not claim to reconstruct
that mapping from an export.
