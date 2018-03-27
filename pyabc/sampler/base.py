from abc import ABC, abstractmethod
from typing import Callable, TypeVar
from pyabc.population import FullInfoParticle, Population

A = TypeVar('A')

class SamplerOptions:
    """
    Options passed to a sampler.

    Properties
    ----------

    n: int
        The number of samples to be accepted, i.e. the population size.

    sample_one: Callable[[], A]
        A function which takes no arguments and returns
        a proposal parameter :math:`\\theta`.

    simul_eval_one: Callable[[A], FullInfoParticle]
        A function which takes as sole argument a proposal
        parameter :math:`\\theta` as returned by `sample_one`.
        It returns a :class:`FullInfoParticle` containing the summary
        statistics. In a field accepted, this particle returns also the
        information whether it got accepted.

    sample_options: SampleOptions
        Options passed to the samples created during sampling process.

    """

    def __init__(self,
                 n: int,
                 sample_one: Callable[[], A],
                 simul_eval_one: Callable[[A], FullInfoParticle],
                 record_rejected_sum_stat: bool = False):
        self.n = n
        self.sample_one = sample_one
        self.simul_eval_one = simul_eval_one
        self.record_rejected_sum_stat = record_rejected_sum_stat


class Sample:
    """
    A Sample is created and filled during the sampling process by the Sampler.

    Parameters
    ----------

    record_rejected_summary_statistics: bool
        Whether to record the summary statistics of rejected particles as well.


    Properties
    ----------

    accepted_population: Population
        Contains all accepted particles.

    all_summary_statistics_list: List[dict]
        Contains all summary statistics created during the sampling process.
    """

    def __init__(self, record_rejected_sum_stat: bool):
        self.accepted_particles = []
        self.all_summary_statistics_list = []
        self.record_rejected_sum_stat = record_rejected_sum_stat

    def append(self, full_info_particle: FullInfoParticle):
        """
        Add new particle to sample and handle all_summary_statistics_list.
        Checks itself based on the particle.accepted flag whether the particle
        is accepted.

        :param full_info_particle:
            Sampled particle containing all information needed later.
        """

        # add to population if accepted
        if full_info_particle.accepted:
            self.accepted_particles.append(full_info_particle.to_particle())

        # keep track of all summary statistics sampled
        if self.record_rejected_sum_stat:
            self.all_summary_statistics_list.extend(
                full_info_particle.all_summary_statistics_list)

    def __add__(self, other):
        """
        Sum function.
        :param other:
        :return:
        """
        sample = self.__class__(self.record_rejected_sum_stat)
        sample.accepted_particles = self.accepted_particles \
            + other.accepted_particles
        sample.all_summary_statistics_list = \
            self.all_summary_statistics_list \
            + other.all_summary_statistics_list

        return sample

    def get_accepted_population(self):
        """
        Create and return a population from the internal list of accepted
        particles.

        :return:
            A Population object.
        """

        return Population(self.accepted_particles)


class Sampler(ABC):
    """
    Abstract Sampler base class.

    Produce valid particles: :class:`pyabc.parameters.ValidParticle`.

    Properties
    ----------

    nr_evaluations_: int
        This is set after a population and counts the total number
        of model evaluations. This can be used to calculate the acceptance
        rate.
    """
    def __init__(self):
        self.nr_evaluations_ = 0
        self._record_all_sum_stats = True

    def require_all_sum_stats(self):
        self._record_all_sum_stats = True

    def _create_empty_sample(self):
        return Sample(self._record_all_sum_stats)

    @abstractmethod
    def sample_until_n_accepted(self,
                                sampler_options: SamplerOptions) -> Sample:
        """
        Parameters
        ----------

        sampler_options: SamplerOptions
            Contains all options needed to customize the sampling process.

        Returns
        -------

        sample: :class:`Sample`
            The generated sample.
        """
