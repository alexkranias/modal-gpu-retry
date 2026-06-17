"""Detached: fresh process reconnects to the spawned batch and fetches results."""

import pathlib

from modal_gpu_retry import LadderCall

ID_FILE = pathlib.Path("/tmp/mgr_integration_call_id.txt")


def main():
    call_id = ID_FILE.read_text().strip()
    print(f"reconnecting to {call_id}")
    results = LadderCall.from_id(call_id).get(timeout=600)
    for i, r in enumerate(results):
        print(f"   [{i}] {r!r}")


if __name__ == "__main__":
    main()
