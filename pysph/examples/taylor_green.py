"""Taylor Green vortex flow (10 minutes).
"""

import numpy as np
import os

# PySPH imports
from pysph.base.nnps import DomainManager
from pysph.base.utils import get_particle_array_tvf_fluid
from pysph.base.kernels import QuinticSpline
from pysph.solver.solver import Solver
from pysph.solver.application import Application
from pysph.sph.integrator import PECIntegrator
from pysph.sph.integrator_step import TransportVelocityStep, WCSPHStep

# the eqations
from pysph.sph.equation import Group
from pysph.sph.wc.transport_velocity import SummationDensity,\
    StateEquation, MomentumEquationPressureGradient, MomentumEquationViscosity,\
    MomentumEquationArtificialStress, SolidWallPressureBC

from pysph.sph.basic_equations import XSPHCorrection, ContinuityEquation
from pysph.sph.wc.basic import TaitEOS, MomentumEquation
from pysph.sph.wc.viscosity import LaminarViscosity

# domain and constants
L = 1.0; U = 1.0
rho0 = 1.0; c0 = 10 * U
p0 = c0**2 * rho0


def exact_velocity(U, b, t, x, y):
    pi = np.pi; sin = np.sin; cos = np.cos
    factor = U * np.exp(b*t)

    u = -cos( 2 * pi * x ) * sin( 2 * pi * y)
    v = sin( 2 * pi * x ) * cos( 2 * pi * y)

    return factor * u, factor * v


class TaylorGreen(Application):
    def add_user_options(self, group):
        group.add_argument(
            "--init", action="store", type=str, default=None,
            help="Initialize particle positions from given file."
        )
        group.add_argument(
            "--perturb", action="store", type=float, dest="perturb", default=0,
            help="Random perturbation of initial particles as a fraction "\
                "of dx (setting it to zero disables it, the default)."
        )
        group.add_argument(
            "--standard-sph", action="store_true", dest="standard_sph",
            default=False, help="Use standard SPH (defaults to TVF)."
        )
        group.add_argument(
            "--nx", action="store", type=int, dest="nx", default=50,
            help="Number of points along x direction. (default 50)"
        )
        group.add_argument(
            "--re", action="store", type=float, dest="re", default=100,
            help="Reynolds number (defaults to 100)."
        )
        group.add_argument(
            "--hdx", action="store", type=float, dest="hdx", default=1.0,
            help="Ratio h/dx."
        )
        group.add_argument(
            "--gamma", action="store", type=float, dest="gamma",
            default=7.0, help="Gamma for the state equation."
        )
        group.add_argument(
            "--pb-factor", action="store", type=float, dest="pb_factor",
            default=1.0,
            help="Use fraction of the background pressure (default: 1.0)."
        )
        group.add_argument(
            "--tensile-correction", action="store_true", dest="tensile_corr",
            default=False,
            help="Use tensile instability correction (for standard SPH)."
        )

    def consume_user_options(self):
        nx = self.options.nx
        re = self.options.re

        self.nu = nu = U*L/re

        self.dx = dx = L/nx
        self.volume = dx*dx
        self.hdx = self.options.hdx
        self.gamma = self.options.gamma

        h0 = self.hdx * self.dx
        dt_cfl = 0.25 * h0/( c0 + U )
        dt_viscous = 0.125 * h0**2/nu
        dt_force = 0.25 * 1.0

        self.tf = 5.0
        self.dt = 0.5 * min(dt_cfl, dt_viscous, dt_force)

    def create_domain(self):
        return DomainManager(
            xmin=0, xmax=L, ymin=0, ymax=L, periodic_in_x=True,
            periodic_in_y=True
        )

    def create_particles(self):
        # create the particles
        dx = self.dx
        _x = np.arange( dx/2, L, dx )
        x, y = np.meshgrid(_x, _x); x = x.ravel(); y = y.ravel()
        if self.options.init is not None:
            fname = self.options.init
            from pysph.solver.utils import load
            data = load(fname)
            _f = data['arrays']['fluid']
            x, y = _f.x.copy(), _f.y.copy()

        if self.options.perturb > 0:
            np.random.seed(1)
            factor = dx*self.options.perturb
            x += np.random.random(x.shape)*factor
            y += np.random.random(x.shape)*factor
        h = np.ones_like(x) * dx

        # create the arrays

        fluid = get_particle_array_tvf_fluid(name='fluid', x=x, y=y, h=h)

        # add the requisite arrays
        fluid.add_property('color')
        fluid.add_output_arrays(['color'])

        print("Taylor green vortex problem :: nfluid = %d, dt = %g"%(
            fluid.get_number_of_particles(), self.dt))

        # setup the particle properties
        pi = np.pi; cos = np.cos; sin=np.sin

        # color
        fluid.color[:] = cos(2*pi*x) * cos(4*pi*y)

        # velocities
        fluid.u[:] = -U * cos(2*pi*x) * sin(2*pi*y)
        fluid.v[:] = +U * sin(2*pi*x) * cos(2*pi*y)
        fluid.p[:] = -U*U*(np.cos(4*np.pi*x) + np.cos(4*np.pi*y))*0.25

        # mass is set to get the reference density of each phase
        fluid.rho[:] = rho0
        fluid.m[:] = self.volume * fluid.rho

        # volume is set as dx^2
        fluid.V[:] = 1./self.volume

        # smoothing lengths
        fluid.h[:] = self.hdx * dx

        if self.options.standard_sph:
            fluid.remove_property('vmag2')
            for prop in ('cs', 'arho', 'ax', 'ay', 'az', 'rho0', 'u0', 'v0',
                'w0', 'x0', 'y0', 'z0'):
                fluid.add_property(prop)

            fluid.set_output_arrays(
                ['x', 'y', 'z', 'u', 'v', 'w', 'rho', 'p', 'm', 'h']
            )
        # return the particle list
        return [fluid]

    def create_solver(self):
        kernel = QuinticSpline(dim=2)
        if self.options.standard_sph:
            integrator = PECIntegrator(fluid=WCSPHStep())
        else:
            integrator = PECIntegrator(fluid=TransportVelocityStep())
        solver = Solver(kernel=kernel, dim=2, integrator=integrator)

        solver.set_time_step(self.dt)
        solver.set_final_time(self.tf)
        return solver

    def create_equations(self):
        if self.options.standard_sph:
           equations = [
                Group(equations=[
                        TaitEOS(dest='fluid', sources=None, rho0=rho0,
                                c0=c0, gamma=self.gamma),
                        ], real=False),

                Group(equations=[
                        ContinuityEquation(dest='fluid',  sources=['fluid',]),

                        MomentumEquation(
                            dest='fluid', sources=['fluid'], alpha=0.1,
                            beta=0.0, c0=c0,
                            tensile_correction=self.options.tensile_corr
                        ),

                        LaminarViscosity(
                            dest='fluid', sources=['fluid'], nu=self.nu
                        ),

                        XSPHCorrection(dest='fluid', sources=['fluid']),

                        ],),

                ]
        else:
            equations = [
                # Summation density along with volume summation for the fluid
                # phase. This is done for all local and remote particles. At
                # the end of this group, the fluid phase has the correct
                # density taking into consideration the fluid and solid
                # particles.
                Group(
                    equations=[
                        SummationDensity(dest='fluid', sources=['fluid']),
                        ], real=False),

                # Once the fluid density is computed, we can use the EOS to
                # set the fluid pressure. Additionally, the shepard filtered
                # velocity for the fluid phase is determined.
                Group(
                    equations=[
                        StateEquation(dest='fluid', sources=None,
                                      p0=p0, rho0=rho0, b=1.0),
                        ], real=False),

                # The main accelerations block. The acceleration arrays for
                # the fluid phase are updated in this stage for all local
                # particles.
                Group(
                    equations=[
                        # Pressure gradient terms
                        MomentumEquationPressureGradient(
                            dest='fluid', sources=['fluid'],
                            pb=p0*self.options.pb_factor
                        ),

                        # fluid viscosity
                        MomentumEquationViscosity(
                            dest='fluid', sources=['fluid'], nu=self.nu),

                        # Artificial stress for the fluid phase
                        MomentumEquationArtificialStress(
                            dest='fluid', sources=['fluid']
                        ),

                        ], real=True
                ),
            ]
        return equations

    def post_process(self, info_fname):
        info = self.read_info(info_fname)
        if len(self.output_files) == 0:
            return

        from pysph.solver.utils import iter_output
        decay_rate = -8.0 * np.pi**2/self.options.re

        files = self.output_files
        t, ke, ke_ex, decay, linf, l1 = [], [], [], [], [], []
        for sd, array in iter_output(files, 'fluid'):
            _t = sd['t']
            t.append(_t)
            m, u, v, x, y = array.get('m', 'u', 'v', 'x', 'y')
            u_e, v_e = exact_velocity(U, decay_rate, _t, x, y)
            vmag2 = u**2 + v**2
            vmag = np.sqrt(vmag2)
            ke.append(0.5*np.sum(m*vmag2))
            vmag2_e = u_e**2 + v_e**2
            vmag_e = np.sqrt(vmag2_e)
            ke_ex.append(0.5*np.sum(m*vmag2_e))

            vmag_max = vmag.max()
            decay.append(vmag_max)
            theoretical_max = U * np.exp(decay_rate * _t)
            linf.append(abs( (vmag_max - theoretical_max)/theoretical_max ))

            l1_err = np.average(np.abs(vmag - vmag_e))
            avg_vmag_e = np.average(np.abs(vmag_e))
            # scale the error by the maximum velocity.
            l1.append(l1_err/avg_vmag_e)

        t, ke, ke_ex, decay, l1, linf = list(map(
            np.asarray, (t, ke, ke_ex, decay, l1, linf))
        )
        decay_ex = U*np.exp(decay_rate*t)
        fname = os.path.join(self.output_dir, 'results.npz')
        np.savez(fname, t=t, ke=ke, ke_ex=ke_ex, decay=decay, linf=linf, l1=l1,
                 decay_ex=decay_ex)

        from matplotlib import pyplot as plt
        plt.clf()
        plt.semilogy(t, decay_ex, label="exact")
        plt.semilogy(t, decay, label="computed")
        plt.xlabel('t'); plt.ylabel('max velocity')
        plt.legend()
        fig = os.path.join(self.output_dir, "decay.png")
        plt.savefig(fig, dpi=300)

        plt.clf()
        plt.plot(t, linf)
        plt.xlabel('t'); plt.ylabel(r'$L_\infty$ error')
        fig = os.path.join(self.output_dir, "linf_error.png")
        plt.savefig(fig, dpi=300)

        plt.clf()
        plt.plot(t, l1, label="error")
        plt.xlabel('t'); plt.ylabel(r'$L_1$ error')
        fig = os.path.join(self.output_dir, "l1_error.png")
        plt.savefig(fig, dpi=300)


if __name__ == '__main__':
    app = TaylorGreen()
    app.run()
    app.post_process(app.info_filename)