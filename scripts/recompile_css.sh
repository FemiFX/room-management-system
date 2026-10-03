#!/bin/bash

echo "Recompiling CSS."
cd ~/btf_mvp/static && npm run build:css && cd ../../..

echo "Recompiliation complete!"