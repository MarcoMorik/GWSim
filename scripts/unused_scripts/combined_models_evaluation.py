import argparse
import json
import os
import sys

sys.path.append('..')
from helper import get_hyperparams, parse_datasets
from slurm import run_job

parser = argparse.ArgumentParser()
parser.add_argument('--models_config', type=str, default='./models_config.json')
parser.add_argument('--datasets', type=str, nargs='+',
                    default=['wds/imagenet1k', 'wds/imagenetv2', 'wds/imagenet-a', 'wds/imagenet-r',
                             'wds/imagenet_sketch'],
                    help="datasets can be a list of dataset names or a file (e.g., webdatasets.txt) containing dataset names.")
parser.add_argument('--sampling_folder', type=str, nargs='+')
parser.add_argument('--combination', type=str, default='ensemble',
                    choices=['ensemble', 'concat', 'concat_pca'], help="Model combination to use")

args = parser.parse_args()

MODELS_CONFIG = args.models_config
DATASETS = " ".join(parse_datasets(args.datasets))

BASE_PROJECT_PATH = "/home/space/diverse_priors"
DATASETS_ROOT = os.path.join(BASE_PROJECT_PATH, 'datasets')
FEATURES_ROOT = os.path.join(BASE_PROJECT_PATH, 'features')
MODELS_ROOT = os.path.join(BASE_PROJECT_PATH, 'models')
OUTPUT_ROOT = os.path.join(BASE_PROJECT_PATH, 'results')
SAMPLING_ROOT = os.path.join(BASE_PROJECT_PATH, 'sampling')

if __name__ == "__main__":
    # We find all files in each sampling folder and load the jsons
    model_keys = []
    for sampling_folder in args.sampling_folder:
        cur_folder = os.path.join(SAMPLING_ROOT, sampling_folder)
        for file in os.listdir(cur_folder):
            if file.endswith(".json"):
                # Open the JSON, which should contain a list of lists
                with open(os.path.join(cur_folder, file), 'r') as f:
                    model_keys.extend(json.load(f))

    # Sort each list within model_keys alphabetically
    model_keys = [sorted(model_key) for model_key in model_keys]
    print(f"Found {len(model_keys)} model sets in the sampling folders.")

    # Filter out duplicates
    model_keys = list(set([tuple(model_key) for model_key in model_keys]))
    print(f"Filtered out duplicates, {len(model_keys)} model sets remaining.")

    # Extracting hyperparameters for evaluation: learning rate, few-shot k samples, epoch numbers, and seeds.
    hyper_params, num_jobs = get_hyperparams(num_seeds=1, size='imagenet1k')

    val_proportion = 0.2

    print("We evaluate the following hyperparameter", hyper_params)

    # Run evaluation for each model set
    for model_set in model_keys:
        print(f"Submitting Job with model_key{' '.join(model_set)}")
        job_cmd = f"""export XLA_PYTHON_CLIENT_PREALLOCATE=false && \
                export XLA_PYTHON_CLIENT_ALLOCATOR=platform && \
                sim_consistency --dataset {DATASETS} \
                               --dataset_root {DATASETS_ROOT} \
                               --feature_root {FEATURES_ROOT} \
                               --model_root {MODELS_ROOT} \
                               --output_root {OUTPUT_ROOT} \
                               --models_config_file {MODELS_CONFIG} \
                               --task=linear_probe \
                               --mode={'ensemble' if args.combination == 'ensemble' else 'combined_models'} \
                               --feature_combiner {args.combination if args.combination != 'ensemble' else 'concat'} \
                               --model_key {' '.join(model_set)} \
                               --batch_size=1024 \
                               --fewshot_k {' '.join(hyper_params['fewshot_ks'])} \
                               --fewshot_lr {' '.join(hyper_params['fewshot_lrs'])} \
                               --fewshot_epochs {' '.join(hyper_params['fewshot_epochs'])} \
                               --reg_lambda {hyper_params['reg_lambda']} \
                               --regularization {' '.join(hyper_params['regularization'])} \
                               --train_split train \
                               --test_split test \
                               --val_proportion {val_proportion} \
                               --seed {' '.join(hyper_params['seeds'])}
                """
        mem = 32 if args.combination == 'ensemble' else 128

        run_job(
            job_name=f"combined_eval",
            job_cmd=job_cmd,
            partition='cpu-5h' if args.combination == 'ensemble' else 'gpu-2d',
            log_dir=f'{OUTPUT_ROOT}/logs',
            num_jobs_in_array=num_jobs,
            mem=mem
        )
