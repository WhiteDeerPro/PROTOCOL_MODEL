#!/bin/sh
set -eu

asset_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for stem in operation-families concurrency-progress exclusive-monitors; do
    temporary="$asset_dir/$stem.svg.tmp"
    dot -Tsvg "$asset_dir/$stem.dot" -o "$temporary"
    mv "$temporary" "$asset_dir/$stem.svg"
done
