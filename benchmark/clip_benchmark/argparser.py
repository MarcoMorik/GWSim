import argparse
import json
import os
from typing import Tuple, List

from clip_benchmark.utils.utils import as_list


def get_parser_args() -> Tuple[argparse.ArgumentParser, argparse.Namespace]:
    """Get the parser arguments."""
    parser = argparse.ArgumentParser()

    def aa(*args, **kwargs):
        return parser.add_argument(*args, **kwargs)

    # DATASET
    aa('--dataset', type=str, default="cifar10", nargs="+",
       help="Dataset(s) to use for the benchmark. Can be the name of a dataset, or a collection "
            "name ('vtab', 'vtab+', 'imagenet_robustness', 'retrieval') or path of a text file "
            "where each line is a dataset name")
    aa('--dataset_root', default="root", type=str,
       help="dataset root folder where the data are downloaded. Can be in the form of a "
            "template depending on dataset name, e.g., --dataset_root='data/{dataset}'. "
            "This is useful if you evaluate on multiple data.")
    aa('--split', type=str, default="test", help="Dataset split to use")
    aa('--test_split', dest="split", action='store', type=str, default="test",
       help="Dataset split to use")
    aa('--train_split', type=str, default="train",
       help="Dataset(s) train split names")
    aa('--val_proportion', default=0, type=float,
       help="what is the share of the train dataset will be used for validation part, "
            "if it doesn't predefined.")
    aa('--wds_cache_dir', default=None, type=str,
       help="optional cache directory for webdataset only")

    # FEATURES
    aa('--feature_root', default="features", type=str,
       help="feature root folder where the features are stored.")
    aa('--normalize', dest='normalize', action="store_true", default=True,
       help="enable features normalization")
    aa('--no-normalize', dest='normalize', action='store_false',
       help="disable features normalization")

    # MODEL(S)
    aa('--model_key', type=str, nargs="+", default=["dinov2-vit-large-p14"],
       help="Models to use from the models config file.")
    aa('--models_config_file', default=None, type=str,
       help="Path to the models config file.")

    # TASKS
    aa('--task', type=str, default="linear_probe",
       choices=["feature_extraction", "linear_probe", "model_similarity"],
       help="Task to evaluate on. With --task=auto, the task is automatically inferred from the "
            "dataset.")
    aa('--mode', type=str, default="single_model",
       choices=["single_model", "combined_models"],
       help="Mode to use for linear probe task.")
    aa('--feature_combiner', type=str, default="concat",
       choices=['concat', 'concat_pca', "ensemble"], help="Feature combiner to use")

    aa('--fewshot_k', default=[-1], type=int, nargs="+",
       help="for linear probe, how many shots. -1 = whole dataset.")
    aa('--fewshot_epochs', default=[10], type=int, nargs='+',
       help="for linear probe, how many epochs.")
    aa('--fewshot_lr', default=[0.1], type=float, nargs='+',
       help="for linear probe, what is the learning rate.")
    aa('--batch_size', default=64, type=int)
    aa('--no_amp', action="store_false", dest="amp", default=True,
       help="whether to use mixed precision")
    aa("--skip_load", action="store_true",
       help="for linear probes, when everything is cached, no need to load model.")
    aa('--skip_existing', default=False, action="store_true",
       help="whether to skip an evaluation if the output file exists.")

    ### Model similarity
    aa('--sim_method', type=str, default="cka",
       choices=['cka', 'rsa'], help="Method to use for model similarity task.")
    aa('--sim_kernel', type=str, default="linear",
       choices=['linear', 'rbf'], help="Kernel used during CKA. Ignored if sim_method is rsa.")
    aa('--rsa_method', type=str, default="correlation",
       choices=['cosine', 'correlation'],
       help="Method used during RSA. Ignored if sim_method is cka.")
    aa('--corr_method', type=str, default="spearman",
       choices=['pearson', 'spearman'],
       help="Kernel used during CKA. Ignored if sim_method is cka.")
    aa('--sigma', type=float, default=None, help="sigma for CKA rbf kernel.")
    aa('--biased_cka', action="store_false", dest="unbiased", help="use biased CKA")

    # STORAGE
    aa('--output_root', default="results", type=str,
       help="Path to root folder where the results are stored.")
    aa('--model_root', default="models", type=str,
       help="Path to root folder where linear probe model checkpoints are stored.")

    # GENERAL
    aa('--num_workers', default=4, type=int)

    aa("--distributed", action="store_true", help="evaluation in parallel")
    aa('--quiet', dest='verbose', action="store_false",
       help="suppress verbose messages")

    # REPRODUCABILITY
    aa('--seed', default=[0], type=int, nargs='+', help="random seed.")

    args = parser.parse_args()
    return parser, args


def prepare_args(args: argparse.Namespace, model_info: Tuple[str, str, dict, str, str, str]) -> argparse.Namespace:
    args.model = model_info[0]  # model
    args.model_source = model_info[1]  # model_source
    args.model_parameters = model_info[2]  # model_parameters
    args.module_name = model_info[3]  # module_name
    args.feature_alignment = model_info[4]  # feature_alignment
    args.model_key = model_info[5]  # model_key
    return args


def prepare_combined_args(args: argparse.Namespace,
                          model_comb: List[Tuple[str, str, dict, str, str, str]]) -> argparse.Namespace:
    args.model = [tup[0] for tup in model_comb]
    args.model_source = [tup[1] for tup in model_comb]
    args.model_parameters = [tup[2] for tup in model_comb]
    args.module_name = [tup[3] for tup in model_comb]
    args.feature_alignment = [tup[4] for tup in model_comb]
    args.model_key = [tup[5] for tup in model_comb]
    return args


def load_model_configs_args(base: argparse.Namespace) -> argparse.Namespace:
    """Loads the model_configs file and transcribes its parameters into base."""
    if base.models_config_file is None:
        raise FileNotFoundError("Model config file not provided.")

    if not os.path.exists(base.models_config_file):
        raise FileNotFoundError(f"Model config file {base.models_config_file} does not exist.")

    with open(base.models_config_file, "r") as f:
        model_configs = json.load(f)

    model = []
    model_source = []
    model_parameters = []
    module_name = []
    feature_alignment = []

    for model_key in as_list(base.model_key):
        model.append(model_configs[model_key]["model_name"])
        model_source.append(model_configs[model_key]["source"])
        model_parameters.append(model_configs[model_key]["model_parameters"])
        module_name.append(model_configs[model_key]["module_name"])
        feature_alignment.append(model_configs[model_key]["alignment"])

    setattr(base, "model", model)
    setattr(base, "model_source", model_source)
    setattr(base, "model_parameters", model_parameters)
    setattr(base, "module_name", module_name)
    setattr(base, "feature_alignment", feature_alignment)

    return base
