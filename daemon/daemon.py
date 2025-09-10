# TODO: hadle the keyboard interrupt
# TODO: dedicated comments before every functions
#!/usr/bin/env python3
import yaml
import os
import sys
from inotify_simple import INotify, flags

from fluent import sender, event

def load_config(config_path):
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("logs", [])

def tail_files(file_paths):
    """Open files, seek to end, and return dict of file handles + watch descriptors."""
    handles = {}
    for path in file_paths:
        try:
            fd = open(path, "r")
            fd.seek(0, os.SEEK_END)  # start at end (like tail -f)
            handles[path] = fd
        except Exception as e:
            print(f"Error opening {path}: {e}", file=sys.stderr)
    return handles

def follow_logs(config_path):
    log_files = load_config(config_path)
    if not log_files:
        print("No log files found in config.")
        return

    # setup fluentd logger (read from config.yaml)
    data = yaml.safe_load(open(config_path))
    host, port = data.get("host", ["127.0.0.1", 24224])
    sender.setup("myapp", host=host, port=int(port))

    inotify = INotify()
    watch_flags = flags.MODIFY

    # Open and watch files
    handles = tail_files(log_files)
    wd_map = {}  # map wd → file path
    for path, fd in handles.items():
        wd = inotify.add_watch(path, watch_flags)
        wd_map[wd] = (path, fd)

    print("Watching logs... (Ctrl+C to exit)")
    while True:
        for event_ in inotify.read():
            path, fd = wd_map[event_.wd]
            if flags.MODIFY in flags.from_mask(event_.mask):
                for line in fd:
                    log_line = line.strip()
                    if log_line:
                        # Send to fluentd
                        event.Event("log", {"file": path, "message": log_line})
                        print(f"Sent to Fluentd: [{path}] {log_line}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>")
        sys.exit(1)

    follow_logs(sys.argv[1])
