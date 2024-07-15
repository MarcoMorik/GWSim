import json
from itertools import product


def load_models(file_path):
    with open(file_path, "r") as file:
        models = json.load(file)
    return models, len(models)


def count_nr_datasets(datasets_path):
    with open(datasets_path, 'r') as f:
        return len(f.readlines())


def prepare_for_combined_usage(models):
    model_names = []
    sources = []
    model_parameters = []
    module_names = []
    for data in models.values():
        model_names.append(data["model_name"])
        sources.append(data["source"])
        model_parameters.append(data["model_parameters"])
        module_names.append(data["module_name"])
    return model_names, sources, model_parameters, module_names


def get_hyperparams(num_seeds=10, size="extended"):
    if size == "small":
        hyper_params = dict(
            fewshot_lrs=['0.1', '0.01', '0.001'],
            fewshot_ks=['-1'],
            fewshot_epochs=['20'],
            weight_decay=['0.0'],
            weight_decay_type=["L2"],
            seeds=[str(num) for num in range(num_seeds)],
        )
    elif size == "imagenet1k":
        hyper_params = dict(
            fewshot_lrs=['0.01', '0.001'],
            fewshot_ks=['-1'],
            fewshot_epochs=['20'],
            weight_decay=['1e-1', '1e-2', '1e-3', '1e-4', '1e-5', '1e-6'],
            weight_decay_type=["L2", "L1"],
            seeds=[str(num) for num in range(num_seeds)],
        )
    else:
        hyper_params = dict(
            fewshot_lrs=['0.1', '0.01'],
            fewshot_ks=['-1', '5', '10', '100'],
            fewshot_epochs=['10', '20', '30'],
            weight_decay=['0.0'],
            weight_decay_type=["L2"],
            seeds=[str(num) for num in range(num_seeds)],
        )
    num_jobs = len(list(product(*hyper_params.values())))
    return hyper_params, num_jobs


def format_path(path, num_samples_class, split):
    return path.format(
        num_samples_class=num_samples_class,
        split=split
    )
