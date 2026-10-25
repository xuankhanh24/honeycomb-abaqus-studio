# -*- coding: utf-8 -*-
"""Tiny real Explicit qualification model; compatible with Abaqus Python 2.7+."""
from abaqus import mdb
from abaqusConstants import *
import mesh

m = mdb.Model(name='CloudProbe')
s = m.ConstrainedSketch(name='section', sheetSize=10.)
s.rectangle(point1=(0., 0.), point2=(1., 1.))
p = m.Part(name='Block', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=1.)
material = m.Material(name='Aluminium')
material.Density(table=((2.7e-9,),))
material.Elastic(table=((70000., .33),))
m.HomogeneousSolidSection(name='Solid', material='Aluminium', thickness=None)
p.Set(name='All', cells=p.cells)
p.SectionAssignment(region=p.sets['All'], sectionName='Solid')
p.setElementType(regions=(p.cells,), elemTypes=(mesh.ElemType(elemCode=C3D8R, elemLibrary=EXPLICIT),))
p.seedPart(size=.5)
p.generateMesh()
a = m.rootAssembly
a.DatumCsysByDefault(CARTESIAN)
i = a.Instance(name='Block-1', part=p, dependent=ON)
a.Set(name='Bottom', faces=i.faces.getByBoundingBox(zMin=-1.e-6, zMax=1.e-6))
m.EncastreBC(name='Fixed', createStepName='Initial', region=a.sets['Bottom'])
m.ExplicitDynamicsStep(name='Impact', previous='Initial', timePeriod=1.e-6)
mdb.Job(name='CloudProbe', model=m.name, explicitPrecision=DOUBLE, nodalOutputPrecision=FULL, numCpus=4)
mdb.jobs['CloudProbe'].writeInput(consistencyChecking=ON)
mdb.saveAs(pathName='CloudProbe.cae')
