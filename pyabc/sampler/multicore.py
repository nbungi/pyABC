from multiprocessing import Process, Queue
from .singlecore import SingleCoreSampler
import numpy as np
import random
import logging
from .multicorebase import MultiCoreSampler, get_if_worker_healthy
from .base import Sample, SamplerOptions


logger = logging.getLogger("MulticoreSampler")

SENTINEL = None


def feed(feed_q, n_jobs, n_proc):
    for _ in range(n_jobs):
        feed_q.put(1)

    for _ in range(n_proc):
        feed_q.put(SENTINEL)


def work(feed_q, result_q, sampler_options: SamplerOptions):
    random.seed()
    np.random.seed()
    single_core_sampler = SingleCoreSampler()

    # create copy of sampling options with n=1
    sampler_options_worker = SamplerOptions(
        n=1,
        sample_one=sampler_options.sample_one,
        simul_eval_one=sampler_options.simul_eval_one,
        sample_options=sampler_options.sample_options)

    while True:
        arg = feed_q.get()
        if arg == SENTINEL:
            break

        res = single_core_sampler.sample_until_n_accepted(
            sampler_options_worker)
        result_q.put((res, single_core_sampler.nr_evaluations_))


class MulticoreParticleParallelSampler(MultiCoreSampler):
    """
    Samples on multiple cores using the multiprocessing module.
    This sampler is optimized for low latencies and is efficient, even
    if the individual model evaluations are fast.

    Requires no pickling of the ``sample_one``,
    ``simulate_one`` and ``accept_one`` function.
    This is achieved using fork on linux (see :class:`Sampler`).

    The simulation results are still pickled as they are transmitted
    from the worker processes back to the parent process.
    Depending on the kind of summary statistics this can be fast or slow.
    If your summary statistics are only a dict with a couple of numbers,
    the overhead should not be substantial.
    However, if your summary statistics are large numpy arrays
    or similar, this could cause overhead


    Parameters
    ----------
        n_procs: int, optional
            If set to None, the Number of cores is determined according to
            :func:`pyabc.sge.nr_cores_available`.


    .. warning::

        Windows support is *not* tested.
        As there is no fork on Windows. This sampler might not work.

    """

    def sample_until_n_accepted(self, sampler_options: SamplerOptions):
        # starting more than n jobs
        # does not help in this parallelization scheme
        n_procs = min(sampler_options.n, self.n_procs)
        logger.debug("Start sampling on {} cores ({} requested)"
                     .format(n_procs, self.n_procs))
        feed_q = Queue()
        result_q = Queue()

        feed_process = Process(target=feed, args=(feed_q, sampler_options.n,
                                                  n_procs))

        worker_processes = [Process(target=work, args=(feed_q, result_q,
                                                       sampler_options))
                            for _ in range(n_procs)]

        for proc in worker_processes:
            proc.start()

        feed_process.start()

        collected_results = []

        for _ in range(sampler_options.n):
            res = get_if_worker_healthy(worker_processes, result_q)
            collected_results.append(res)

        feed_process.join()

        for proc in worker_processes:
            proc.join()

        # Queues get closed automatically on garbage collection
        # No explicit closing necessary.

        results, evaluations = zip(*collected_results)
        self.nr_evaluations_ = sum(evaluations)

        # create 1 to-be-returned sample from results
        sample = Sample(sampler_options.sample_options)
        for result in results:
            sample += result

        return sample
