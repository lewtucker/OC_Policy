#!/usr/bin/env bash
# Kill the OC Policy server running on port 8080.
pids=$(lsof -ti :8080)
if [ -z "$pids" ]; then
  echo "No process found on port 8080."
else
  echo "$pids" | xargs kill -9
  echo "Killed process(es) on port 8080: $pids"
fi
