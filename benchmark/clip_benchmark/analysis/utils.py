import os

from clip_benchmark.utils.utils import retrieve_model_dataset_results

HYPER_PARAM_COLS = ['model_ids', 'fewshot_k', 'fewshot_epochs', 'batch_size']


def retrieve_performance(model_id: str, dataset_id: str, metric_column: str = 'test_lp_acc1',
                         results_root: str = '/home/space/diverse_priors/results/linear_probe/single_model',
                         regularization: str = "weight_decay",
                         allow_db_results: bool = True):
    path = os.path.join(results_root, dataset_id, model_id)

    df = retrieve_model_dataset_results(path, allow_db_results=allow_db_results)

    if df.dataset.nunique() > 1:
        raise ValueError(
            f"Result files for {model_id=} and {dataset_id=} contain multiple datasets. Cannot proceed."
        )

    # filter regularization method
    if 'regularization' not in df.columns:
        raise ValueError(f"Regularization was not available yet.")
            
    df = df[df.regularization == regularization]

    if len(df) == 0:
        raise ValueError(f'No results available for {dataset_id=}, {model_id=} and {regularization=}.')

    # TODO: Remove manually filtering for seeds
    df = df[df['seed'].isin([0,1,2])]
    
    performance = df.groupby(HYPER_PARAM_COLS)[metric_column].mean()
    
    # TODO: Remove allowing for more than one configuration setting
    if len(performance)>1:
        print(performance)
        raise ValueError('Experiment setup did not consider more configurations than one. Something is fishy ...')
    
    return performance.max()
