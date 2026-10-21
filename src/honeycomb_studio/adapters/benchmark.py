# -*- coding: utf-8 -*-
"""Read-only developer timing probe; not a simulation or validation result."""
from __future__ import print_function
from odbAccess import openOdb
import time, sys
odb=openOdb(path=sys.argv[-1],readOnly=True)
try:
    frame=odb.steps['Impact'].frames[10]
    for name,field in frame.fieldOutputs.items():
        start=time.time();rows=0
        for block in field.bulkDataBlocks:rows+=len(block.data)
        bulk=time.time()-start
        start=time.time();value_count=len(field.values)
        first=field.values[0].precision if value_count else None
        print(name,rows,'bulk_s',bulk,'values_s',time.time()-start,'precision',first)
        sys.stdout.flush()
finally:odb.close()
