import os

from helper import load_models, parse_datasets
from slurm import run_job

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--models_config', type=str, default='./models_config.json')
parser.add_argument('--datasets', type=str, nargs='+', default=['wds/imagenet1k', 'wds/imagenetv2', 'wds/imagenet-a', 'wds/imagenet-r', 'wds/imagenet_sketch'],
                    help="datasets can be a list of dataset names or a file (e.g., webdatasets.txt) containing dataset names.")
args = parser.parse_args()

MODELS_CONFIG = args.models_config

DATASETS = " ".join(parse_datasets(arg.datasets))

BASE_PROJECT_PATH = "/home/space/diverse_priors"
DATASETS_ROOT = os.path.join(BASE_PROJECT_PATH, 'datasets')
FEATURES_ROOT = os.path.join(BASE_PROJECT_PATH, 'features')

if __name__ == "__main__":
    # Retrieve the configuration of all models we intend to evaluate.
    models, n_models = load_models(MODELS_CONFIG)
    if "SegmentAnything_vit_b" in models.keys():
        models.pop('SegmentAnything_vit_b')

    model_keys = list(models.keys())

    # Extract features for all models and datasets.
    for key in model_keys:
        print(f"Running feature extraction for {key}")
        job_cmd = f"""export XLA_PYTHON_CLIENT_PREALLOCATE=false && \
        export XLA_PYTHON_CLIENT_ALLOCATOR=platform && \
        clip_benchmark --dataset {DATASETS} \
                       --dataset_root {DATASETS_ROOT} \
                       --feature_root {FEATURES_ROOT} \
                       --task=feature_extraction \
                       --model_key {key} \
                       --models_config_file {MODELS_CONFIG} \
                       --batch_size=64 \
                       --train_split train \
                       --test_split test \
                       --num_workers=0
        """

        run_job(
            job_name=f"feat_extr_{key}",
            job_cmd=job_cmd,
            partition='gpu-2d',
            log_dir=f'{FEATURES_ROOT}/logs',
            num_jobs_in_array=1,
            mem=64
        )
