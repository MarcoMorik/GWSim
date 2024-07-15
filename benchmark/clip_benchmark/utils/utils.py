import os
import random
import sqlite3
import json
from pathlib import Path
from typing import List, Union, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import torch

from clip_benchmark.data.builder import get_dataset_collection_from_file, get_dataset_collection
from clip_benchmark.data.constants import probe_dataset_map


def as_list(l):
    if not l:
        return []
    return [l] if type(l) != list else l


## Load features and targets
def load_features(feature_root: str, model_id: Optional[str] = None, split: str = 'train') -> torch.Tensor:
    model_dir = os.path.join(feature_root, model_id) if model_id else feature_root
    features = torch.load(os.path.join(model_dir, f'features_{split}.pt'))
    return features


def load_targets(feature_root: str, model_id: Optional[str] = None, split: str = 'train') -> torch.Tensor:
    model_dir = os.path.join(feature_root, model_id) if model_id else feature_root
    targets = torch.load(os.path.join(model_dir, f'targets_{split}.pt'))
    return targets


def check_equal_targets(list_targets: List[torch.Tensor]) -> bool:
    if len(list_targets) > 1:
        first_targets = list_targets[0]
        for curr_target in list_targets[1:]:
            if not (first_targets == curr_target).all().item():
                return False
    return True


def load_features_targets(
        feature_root: str,
        model_id: Optional[str] = None,
        split: str = 'train'
) -> Tuple[torch.Tensor, torch.Tensor]:
    if isinstance(feature_root, list):
        features = [load_features(f, model_id, split) for f in feature_root]
        targets = [load_targets(f, model_id, split) for f in feature_root]
        if not check_equal_targets(targets):
            raise ValueError("Not all targets are equal.")
        targets = targets[0]
    else:
        features = load_features(feature_root, model_id, split)
        targets = load_targets(feature_root, model_id, split)
    return features, targets


## Check if features exist for all models
def check_models(feature_root, model_ids, split):
    prev_model_ids = model_ids

    model_ids = sorted(
        [mid for mid in model_ids if os.path.exists(os.path.join(feature_root, mid, f'features_{split}.pt'))])

    if len(set(prev_model_ids)) != len(set(model_ids)):
        print(f"Features do not exist for the following models: {set(prev_model_ids) - set(model_ids)}")
        print(f"Removing the above models from the list of models for distance computation.")

    # Check if enough remaining models to compute distance matrix
    assert len(model_ids) > 1, f"At least two models are required for distance computation"

    return model_ids


def get_list_of_datasets(base):
    datasets = []
    dataset_collection = get_dataset_collection()
    for name in as_list(base.dataset):
        if os.path.isfile(name):
            # If path, read file, each line is a dataset name
            datasets.extend(get_dataset_collection_from_file(name))
        elif name in dataset_collection:
            # if part of `dataset_collection`, retrieve from it
            datasets.extend(dataset_collection[name])
        else:
            # if not, assume it is simply the name of the dataset
            datasets.append(name)
    return datasets


def map_to_probe_dataset(dataset: str, verbose: bool = False) -> str:
    if dataset in probe_dataset_map:
        if verbose:
            print(f"Dataset mapping for loading probes found. Mapping {dataset} to {probe_dataset_map[dataset]}")
        return probe_dataset_map[dataset]
    return dataset


def prepare_ds_name(dataset: str) -> str:
    # if dataset.startswith("wds/"):
    #     dataset = dataset.replace("wds/", "", 1)
    dataset = dataset.replace("/", "_")
    return dataset


def single_option_to_multiple_datasets(cur_option: List[str], datasets: List[str], name: str) -> List[str]:
    cur_len = len(cur_option)
    ds_len = len(datasets)
    if cur_len != ds_len:
        # If user wants to use same value for all datasets
        if cur_len == 1:
            return [cur_option[0]] * ds_len
        else:
            raise ValueError(f"The incommensurable number of {name}")
    else:
        return cur_option


def get_train_val_splits(
        train_split: Union[str, List[str]],
        val_proportion: Union[float, List[float]],
        datasets: List[str]
) -> Dict[str, Dict[str, Optional[Union[str, float]]]]:
    train_splits = as_list(train_split)
    train_splits = single_option_to_multiple_datasets(train_splits, datasets, "train_split")
    proportions = None
    if val_proportion is not None:
        proportions = as_list(val_proportion)
        proportions = single_option_to_multiple_datasets(proportions, datasets, "val_proportion")

    dataset_info = {}
    for i in range(len(datasets)):
        dataset_info[datasets[i]] = {
            "train_split": train_splits[i],
            "proportion": proportions[i] if proportions is not None else None
        }
    return dataset_info


def world_info_from_env():
    # from openclip
    local_rank = 0
    for v in ('LOCAL_RANK', 'MPI_LOCALRANKID', 'SLURM_LOCALID', 'OMPI_COMM_WORLD_LOCAL_RANK'):
        if v in os.environ:
            local_rank = int(os.environ[v])
            break
    global_rank = 0
    for v in ('RANK', 'PMI_RANK', 'SLURM_PROCID', 'OMPI_COMM_WORLD_RANK'):
        if v in os.environ:
            global_rank = int(os.environ[v])
            break
    world_size = 1
    for v in ('WORLD_SIZE', 'PMI_SIZE', 'SLURM_NTASKS', 'OMPI_COMM_WORLD_SIZE'):
        if v in os.environ:
            world_size = int(os.environ[v])
            break
    return local_rank, global_rank, world_size


def all_paths_exist(list_of_paths: List[str]) -> bool:
    return all([os.path.exists(p) for p in list_of_paths])


def set_all_random_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    if torch.cuda.device_count() > 1:
        torch.cuda.manual_seed_all(seed)


def retrieve_model_dataset_results(base_path_exp: str, verbose: Optional[bool] = False) -> pd.DataFrame:
    path = Path(base_path_exp)
    dfs = []
    for fn in path.rglob("**/results.json"):
        df = pd.read_json(fn)
        dfs.append(df)

    if len(dfs) == 0:
        # backward compatibility
        bak_fn  = path / 'results.db'
        if bak_fn.is_file():
            print(f'Did not find any results.json files. Trying to load data from {bak_fn}')
            try:
                conn = sqlite3.connect(bak_fn)
                df = pd.read_sql('SELECT * FROM "results"', conn)
                conn.close()
            except pd.errors.DatabaseError as e:
                print(f"Tried to extract data from {path=}, but got Error: {e}")
                raise e

            for col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].apply(json.loads)
        else:
            raise FileNotFoundError(f"No results found for in {base_path_exp=}")
    else:
        df = pd.concat(dfs).reset_index(drop=True)

    if verbose:
        print(f"Found {len(df)} results in {base_path_exp=}")
    return df
