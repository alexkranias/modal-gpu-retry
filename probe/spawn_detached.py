"""Spawn the deployed driver, persist the FunctionCall id, then exit.

Requires `modal deploy probe/probe_app.py` first. Proves the detached path:
this process spawns server-side work and exits; get_detached.py reconnects.
"""

import pathlib

import modal

ID_FILE = pathlib.Path("/tmp/mgr_probe_call_id.txt")


def main():
    driver = modal.Function.from_name("mgr-probe", "driver")
    call = driver.spawn(20.0, ["A100"])  # base T4 OOM -> escalate A100
    ID_FILE.write_text(call.object_id)
    print(f"spawned driver; call id = {call.object_id}")
    print(f"wrote {ID_FILE}; exiting WITHOUT waiting (detached).")


if __name__ == "__main__":
    main()
