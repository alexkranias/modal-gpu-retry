"""Detached: spawn_map against the deployed app, save the id, exit."""

import pathlib

from app import BIG, SMALL, Model  # the mgr.cls proxy

ID_FILE = pathlib.Path("/tmp/mgr_integration_call_id.txt")


def main():
    handle = Model().run.spawn_map([BIG, SMALL, BIG])
    ID_FILE.write_text(handle.object_id)
    print(f"spawned spawn_map; call id = {handle.object_id}")
    print("exiting WITHOUT waiting (detached).")


if __name__ == "__main__":
    main()
