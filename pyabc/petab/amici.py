import logging
from collections.abc import Sequence, Mapping
from typing import Callable, Union

import pyabc

logger = logging.getLogger(__name__)

try:
    import petab
except ImportError:
    logger.error("Install petab (see https://github.com/icb-dcm/petab) to use "
                 "the petab functionality.")

try:
    import amici
    from amici.petab_objective import simulate_petab
except ImportError:
    logger.error("Install amici (see https://github.com/icb-dcm/amici) to use "
                 "the amici functionality.")


class AmiciPetabImporter:
    """
    Import a PEtab model using AMICI to simulate it as a deterministic ODE.

    This class provides methods to generate prior, model, and stochastic kernel
    for a pyABC analysis.

    Parameters
    ----------

    petab_problem:
        A PEtab problem containing all information on the parameter estimation
        problem.
    amici_model:
        A corresponding compiled AMICI model that allows simulating data for
        parameters. If not provided, one is created using
        `amici.petab_import.import_petab_problem`.
    amici_solver:
        An AMICI model to simulate the model. If not provided, one is created
        using `amici_model.getSolver()`.
    """

    def __init__(
            self,
            petab_problem: petab.Problem,
            amici_model: amici.Model = None,
            amici_solver: amici.Solver = None,
            free_parameters: bool = True,
            fixed_parameters: bool = False,
            store_simulations: bool = False):
        self.petab_problem = petab_problem

        if amici_model is None:
            amici_model = amici.getab_import.import_petab_problem(
                petab_problem)
        self.amici_model = amici_model

        if amici_solver is None:
            amici_solver = self.amici_model.getSolver()
        self.amici_solver = amici_solver

        self.free_parameters = free_parameters
        self.fixed_parameters = fixed_parameters
        self.store_simulations = store_simulations

    def create_prior(self) -> pyabc.Distribution:
        """
        Create prior.

        Returns
        -------
        prior:
            A valid pyabc.Distribution for the parameters to estimate.
        """
        # add default values
        parameter_df = petab.normalize_parameter_df(
            self.petab_problem.parameter_df)

        prior_dct = {}

        # iterate over parameters
        for _, row in parameter_df.reset_index().iterrows():
            # check whether we can ignore
            if not self.fixed_parameters and row[petab.C.ESTIMATE] == 0:
                # ignore fixed parameters
                continue
            if not self.free_parameters and row[petab.C.ESTIMATE] == 1:
                # ignore free parameters
                continue

            # pyabc currently only knows objective priors, no
            #  initialization priors
            prior_type = row[petab.C.OBJECTIVE_PRIOR_TYPE]
            pars_str = row[petab.C.OBJECTIVE_PRIOR_PARAMETERS]
            prior_pars = tuple([float(val) for val in pars_str.split(';')])

            # create random variable from table entry
            if prior_type in [petab.C.PARAMETER_SCALE_UNIFORM,
                              petab.C.UNIFORM]:
                lb, ub = prior_pars
                rv = pyabc.RV('uniform', lb, ub-lb)
            elif prior_type in [petab.C.PARAMETER_SCALE_NORMAL,
                                petab.C.NORMAL]:
                mean, std = prior_pars
                rv = pyabc.RV('norm', mean, std)
            elif prior_type in [petab.C.PARAMETER_SCALE_LAPLACE,
                                petab.C.LAPLACE]:
                mean, scale = prior_pars
                rv = pyabc.RV('laplace', mean, scale)
            elif prior_type == petab.C.LOG_NORMAL:
                mean, std = prior_pars
                rv = pyabc.RV('lognorm', mean, std)
            elif prior_type == petab.C.LOG_LAPLACE:
                mean, scale = prior_pars
                rv = pyabc.RV('loglaplace', mean, scale)
            else:
                raise ValueError(f"Cannot handle rior type {prior_type}.")

            prior_dct[row[petab.C.PARAMETER_ID]] = rv

        # create prior distribution
        prior = pyabc.Distribution(**prior_dct)

        return prior

    def create_model(
        self
    ) -> Callable[[Union[Sequence, Mapping]], Mapping]:
        """Create model."""
        # parameter ids to consider
        x_ids = self.petab_problem.get_x_ids(
            free=self.free_parameters, fixed=self.fixed_parameters)

        # extract variables for improved pickling
        petab_problem = self.petab_problem
        amici_model = self.amici_model
        amici_solver = self.amici_solver
        store_simulations = self.store_simulations

        # no gradients for pyabc
        amici_solver.setSensitivityOrder(0)

        def model(par: Union[Sequence, Mapping]) -> Mapping:
            """The model function."""
            # convenience to allow calling model not only with dicts
            if not isinstance(par, Mapping):
                par = {key: val for key, val in zip(x_ids, par)}

            # simulate model
            sim = simulate_petab(
                petab_problem=petab_problem,
                amici_model=amici_model,
                solver=amici_solver,
                problem_parameters=par,
                scaled_parameters=True)

            # return values of interest
            ret = {'llh': sim['llh']}
            if store_simulations:
                for i_rdata, rdata in enumerate(ret['rdatas']):
                    ret[f'y_{i_rdata}'] = rdata['y']

            return ret

        return model

    def create_kernel(
        self
    ) -> pyabc.StochasticKernel:
        """
        Create acceptance kernel.

        Returns
        -------
        kernel:
            A pyabc distribution encoding the kernel function.
        """
        def kernel_fun(x, x_0, t, par):
            # we cheat: the kernel value is computed by the model already
            return x['llh']

        # create a kernel from function, returning log-scaled values
        kernel = pyabc.distance.SimpleFunctionKernel(
            kernel_fun, ret_scale=pyabc.distance.SCALE_LOG)

        return kernel