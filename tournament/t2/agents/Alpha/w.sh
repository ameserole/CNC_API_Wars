#!/bin/bash
# loop watch; suppress repeat enemies_near_base-only digests for up to ~100s
cd /c/Users/user/Documents/CNC_Generals_AI/python
end=$((SECONDS+100))
while true; do
  out=$(.venv/Scripts/python.exe -m generals_api.watch ws://127.0.0.1:49683 --max-wait 60 --state ../tournament/t2/agents/Alpha/watch.json); rc=$?
  if [ $rc -ne 0 ]; then echo "$out"; echo EXIT $rc; exit $rc; fi
  first=$(echo "$out" | head -1)
  if [[ "$first" != *"triggers: enemies_near_base" ]] || [ $SECONDS -ge $end ]; then echo "$out" | head -6; tail -2 ../tournament/t2/agents/Alpha/bot.log; exit 0; fi
done
