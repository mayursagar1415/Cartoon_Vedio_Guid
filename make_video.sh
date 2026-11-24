#!/bin/bash
# Flat Puppet Studio — full render + encode (run from this folder)
set -e
cd "$(dirname "$0")"

python3 flat_puppet_demo.py encode --output FLAT-DEMO.mp4
echo "Done: FLAT-DEMO.mp4"
