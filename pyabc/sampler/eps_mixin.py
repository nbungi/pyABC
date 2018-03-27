import numpy as np
import cloudpickle as pickle
from sortedcontainers import SortedListWithKey
from .base import Sample, SamplerOptions


class EPSMixin:
    def full_submit_function_pickle(self, param, job_id):
        simulate_one = pickle.loads(self.simulate_accept_one)
        result_batch = []
        for j in range(self.batchsize):
            eval_result = simulate_one(param[j])
            eval_accept = eval_result.accepted
            result_batch.append((eval_result, eval_accept, job_id[j]))
        return result_batch

    def sample_until_n_accepted(self, sampler_options: SamplerOptions):
        # For default pickling
        if self.default_pickle:
            self.simulate_accept_one = pickle.dumps(
                sampler_options.simul_eval_one)
            full_submit_function = self.full_submit_function_pickle
        else:
            # For advanced pickling, e.g. cloudpickle
            def full_submit_function(param, job_id):
                result_batch = []
                for j in range(self.batchsize):
                    eval_result = sampler_options.simul_eval_one(param[j])
                    eval_accept = eval_result.accepted
                    result_batch.append((eval_result, eval_accept, job_id[j]))
                return result_batch

        num_accepted_total = 0
        num_accepted_sequential = 0
        next_job_id = 0
        running_jobs = []
        unprocessed_results = SortedListWithKey(key=lambda x: x[0])
        all_results = SortedListWithKey(key=lambda x: x[0])
        next_valid_index = -1

        # Main Loop, leave once we have enough material
        while True:
            # Gather finished jobs
            # make sure to track and update both
            # total accepted and sequentially
            # accepted jobs
            for curJob in running_jobs:
                if curJob.done():
                    remote_batch = curJob.result()
                    running_jobs.remove(curJob)
                    for i in range(self.batchsize):
                        remote_evaluated = remote_batch[i]
                        remote_result = remote_evaluated[0]
                        remote_accept = remote_evaluated[1]
                        remote_jobid = remote_evaluated[2]
                        # print("Received result on job ", remote_jobid)
                        unprocessed_results.add((remote_jobid, remote_accept,
                                                 remote_result))
                        if remote_accept:
                            num_accepted_total += 1

            if len(unprocessed_results) > 0:
                next_index = unprocessed_results[0][0]
            else:
                next_index = np.nan
            while next_index == next_valid_index+1:
                seq_evaluated = unprocessed_results.pop(0)
                # add to all_results
                all_results.add((seq_evaluated[0], seq_evaluated[2]))
                # update accepted counter
                if seq_evaluated[1]:
                    num_accepted_sequential += 1
                next_valid_index += 1
                if len(unprocessed_results) > 0:
                    next_index = unprocessed_results[0][0]
                else:
                    next_index = np.nan

            # If num_accepted >= n
            # return the first n accepted results
            if num_accepted_sequential >= sampler_options.n:
                break

            # Update information on scheduler state
            # Only submit more jobs if:
            # Number of jobs open < max_jobs
            # Number of jobs open < self.scheduler_workers_running *
            # worker_load_factor
            # num_accepted_total < jobs required
            if (len(running_jobs) < self.client_max_jobs) and \
                    (len(running_jobs) < self.client_cores()) and \
                    (num_accepted_total < sampler_options.n):
                for _ in range(0,
                               np.minimum(self.client_max_jobs,
                                          self.client_cores()).astype(int)
                               - len(running_jobs)):
                    para_batch = []
                    job_id_batch = []
                    for i in range(self.batchsize):
                        para_batch.append(sampler_options.sample_one())
                        job_id_batch.append(next_job_id)
                        next_job_id += 1

                    running_jobs.append(
                        self.my_client.submit(full_submit_function,
                                              para_batch,
                                              job_id_batch))

        # cancel all unfinished jobs
        for curJob in running_jobs:
            curJob.cancel()

        # create and to-be-returned sample from all results
        sample = Sample(sampler_options.sample_options)
        counter_accepted = 0
        while counter_accepted < sampler_options.n:
            cur_res = all_results.pop(0)
            particle = cur_res[1]
            sample.append(particle)
            if particle.accepted:
                counter_accepted += 1
            self.nr_evaluations_ = cur_res[0]

        return sample
