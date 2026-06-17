"""Fresh process: reconnect to the spawned call by id and fetch its result.

Proves the orchestration survived the launcher (spawn_detached.py) exiting.
"""

import pathlib

import modal

ID_FILE = pathlib.Path("/tmp/mgr_probe_call_id.txt")


def main():
    call_id = ID_FILE.read_text().strip()
    print(f"reconnecting to call id = {call_id}")
    call = modal.FunctionCall.from_id(call_id)
    result = call.get(timeout=600)
    print("detached result ->", result)


if __name__ == "__main__":
    main()
