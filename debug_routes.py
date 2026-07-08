#!/usr/bin/env python
import sys
sys.path.insert(0, '.')
from app import app

with open('routes_debug.txt', 'w') as f:
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        line = f"{rule.rule} -> {rule.endpoint} ({methods})\n"
        f.write(line)
        print(line, end='')

print("\nRoutes written to routes_debug.txt")
