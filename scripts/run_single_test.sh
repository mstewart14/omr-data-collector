#!/bin/sh
uv run python3 -m pytest --cache-clear -rfpsxEX -vv -k test_reads_vendored_mobile_camera_sample
