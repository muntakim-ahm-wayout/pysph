"""Tests for periodic boundary conditions using a simple advection function

The problem is purely kinematical with a circular fluid patch (R =
0.25) in a doubly periodic box [0,1] X [0,1] subjected to a velocity
profile :

u(x, y) = 1.0
v(x, y) = 1.0

which is divergence free and periodic with period 1 in each coordinate
direction. Running a long loop of the simulation should let use test
the periodic boundary conditions iplemented in PySPH.

To ensure the neighbors are appropriately set up in periodic
calculations, the density is estimated by summation for each
particle. This should remain constant through the simulation.

"""

# PyZoltan imports
from pyzoltan.core.carray import LongArray

# PySPH imports
from pysph.base.nnps import DomainLimits
from pysph.base.utils import get_particle_array_wcsph
from pysph.base.kernels import Gaussian, WendlandQuintic, CubicSpline
from pysph.solver.solver import Solver
from pysph.solver.application import Application
from pysph.sph.integrator import EulerIntegrator

# the eqations
from pysph.sph.equations import Group
from pysph.sph.advection_equations import Advect

# numpy
import numpy as np

# domain and constants
a = 0.25; b = 0.75

# Numerical setup
nx = 50; dx = 1.0/nx
hdx = 1.2

def create_particles(empty=False, **kwargs):
    if empty:
        fluid = get_particle_array_wcsph(name='fluid')
    else:
        # create the particles
        _x = np.arange( a, b+1e-3, dx )
        x, y = np.meshgrid(_x, _x); x = x.ravel(); y = y.ravel()
        h = np.ones_like(x) * dx

        cx = cy = 0.5
        indices = []
        for i in range(x.size):
            xi = x[i]; yi = y[i]
            if ( (xi - cx)**2 + (yi - cy)**2 > 0.25**2 ):
                indices.append(i)
                
        # create the arrays
        fluid = get_particle_array_wcsph(name='fluid', x=x, y=y, h=h)
        
        # remove particles outside the circular patch
        to_remove = LongArray(len(indices)); to_remove.set_data(np.array(indices))
        fluid.remove_particles(to_remove)
    
        # add the requisite arrays
        fluid.add_property( {'name': 'color'} )
        fluid.add_property( {'name': 'ax'} )
        fluid.add_property( {'name': 'ay'} )
        fluid.add_property( {'name': 'az'} )

        print "Advection test :: nfluid = %d"%(
            fluid.get_number_of_particles())

        # setup the particle properties
        pi = np.pi; cos = np.cos; sin=np.sin

        # color
        fluid.color[:] = cos(2*pi*fluid.x) * cos(2*pi*fluid.y)
        fluid.u[:] = 1.0; fluid.v[:] = 1.0
        
        # mass 
        fluid.m[:] = dx**2 * 1.0

    # return the particle list
    return [fluid,]

# domain for periodicity
domain = DomainLimits(xmin=0, xmax=1.0, ymin=0, ymax=1.0, 
                      periodic_in_x=True, periodic_in_y=True)

# Create the application.
app = Application(domain=domain)

# Create the kernel
kernel = WendlandQuintic(dim=2)

# Create a solver.
solver = Solver(
    kernel=kernel, dim=2, integrator_type=EulerIntegrator)

# Setup default parameters.
tf = 5 * np.sqrt(2.0)
solver.set_time_step(1e-3)
solver.set_final_time(tf)

equations = [

    # Update velocities and advect
    Group(
        equations=[
            Advect(dest='fluid', sources=None),
            ])
    ]

# Setup the application and solver.  This also generates the particles.
app.setup(solver=solver, equations=equations, 
          particle_factory=create_particles)

with open('test.pyx', 'w') as f:
    app.dump_code(f)

app.run()