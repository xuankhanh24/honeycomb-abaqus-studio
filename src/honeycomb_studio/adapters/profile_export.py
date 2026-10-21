# -*- coding: utf-8 -*-
from __future__ import print_function
import cProfile, pstats, json, sys, os
from odbAccess import openOdb
import extract

cfg=json.load(open(sys.argv[-1]));out=str(cfg['extract_directory'])
if not os.path.isdir(os.path.join(out,'spool')):os.makedirs(os.path.join(out,'spool'))
odb=openOdb(path=str(cfg['odb']),readOnly=True)
def work():
    frame=odb.steps['Impact'].frames[10];names=list(odb.rootAssembly.instances.keys());lookup=dict((n,i) for i,n in enumerate(names));sequence=0
    for name,field in frame.fieldOutputs.items():
        meta={'field':name,'step':'Impact','frame':10,'time_s':frame.frameValue,'instances':names,'components':list(field.componentLabels)}
        sequence=extract.bulk_field(list(field.bulkDataBlocks),meta,os.path.join(out,'spool'),sequence,12000,lookup)
try:
    path=os.path.join(out,'profile.stats');cProfile.runctx('work()',globals(),locals(),path)
    with open(os.path.join(out,'profile.txt'),'w') as report:pstats.Stats(path,stream=report).sort_stats('cumulative').print_stats(25)
finally:odb.close()
