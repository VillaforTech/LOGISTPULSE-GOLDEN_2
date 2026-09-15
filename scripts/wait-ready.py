#!/usr/bin/env python3
"""Bounded readiness for every routed API; HTTP errors never count as ready."""
import json, sys, time, urllib.request
base=sys.argv[1] if len(sys.argv)>1 else 'http://localhost:8080'
pending=set(['inventory','logistics','operations','fulfillment'])
deadline=time.monotonic()+120
while pending and time.monotonic()<deadline:
    for service in list(pending):
        try:
            with urllib.request.urlopen(base+'/health/'+service,timeout=3) as r:
                if json.load(r)['status']=='UP':pending.remove(service)
        except Exception:pass
    if pending:time.sleep(1)
if pending:raise SystemExit('Readiness failed: '+', '.join(sorted(pending)))
print('All routed APIs ready')
