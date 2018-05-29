import Pyro4
import train
import pickle
import sonic_utils
from model import CNNPolicy
import utils
from time import sleep


def find_workers(prefix):
    workers = []
    with Pyro4.locateNS() as ns:
        for sampler, sampler_uri in ns.list(prefix="{}.".format(prefix)).items():
            print("found {}".format(prefix), sampler)
            workers.append(Pyro4.Proxy(sampler_uri))
    if not workers:
        raise ValueError("no {} found!".format(prefix))
    print('found total {} {}s'.format(len(workers), prefix))
    return workers


def init_workers(workers, config, weights):
    results = []
    print('start workers initialization')
    for worker in workers:
        res = Pyro4.Future(worker.initialize)(config, pickle.dumps(weights))
        results.append(res)

    while len(results) > 0:
        for res in results:
            if res.ready:
                results.remove(res)

    print('finish workers initialization')


def wait_run_end(workers_results, model, timeout=None):
    # TODO: use timeout
    weights = pickle.dumps(model.get_weights())

    for w, res in workers_results.items():

        while not res.ready:
            sleep(1)

        res = utils.unpickle(res.value)
        grads = res["grads"]
        model.add_grads(grads)

        new_res = Pyro4.Future(w.run)(weights)
        workers_results[w] = new_res


def run_maml():
    config = train.get_config()
    train_params = config["train_params"]

    # open and close env just to get right action and obs space
    env = sonic_utils.make_from_config(config['env_params'], True)
    env.close()

    # init model
    model = CNNPolicy(
        env.observation_space, env.action_space, train_params["vf_coef"],
        train_params["ent_coef"], train_params["lr_meta"], train_params["max_grad_norm"]

    )

    workers = find_workers("worker")

    # start run
    workers_results = {w: Pyro4.Future(w.run)() for w in workers}

    while True:
        # first zero all grads
        model.optimizer.zero_grad()

        # then apply add grads from remote workers
        wait_run_end(workers_results, model)

        # apply gradient
        model.optimizer.step()


if __name__ == '__main__':
    run_maml()