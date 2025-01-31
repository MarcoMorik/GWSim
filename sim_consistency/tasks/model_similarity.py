import json
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Tuple, List, Optional

import numpy as np
import ot
from scipy.spatial.distance import cdist
from thingsvision.core.cka import get_cka
from thingsvision.core.rsa import compute_rdm, correlate_rdms
from tqdm import tqdm

from sim_consistency.utils.utils import load_features, check_models


class BaseModelSimilarity:
    def __init__(self, feature_root: str, subset_root: Optional[str], split: str = 'train', device: str = 'cuda',
                 max_workers: int = 4) -> None:
        self.feature_root = feature_root
        self.split = split
        self.device = device
        self.model_ids = []
        self.max_workers = max_workers
        self.subset_indices = self._load_subset_indices(subset_root)
        self.name = 'Base'

    def _load_subset_indices(self, subset_root) -> Optional[List[int]]:
        subset_path = os.path.join(subset_root, f'subset_indices_{self.split}.json')
        if not os.path.exists(subset_path):
            warnings.warn(
                f"Subset indices not found at {subset_path}. Continuing with full datasets."
            )
            return None
        with open(subset_path, 'r') as f:
            subset_indices = json.load(f)
        return subset_indices

    def load_model_ids(self, model_ids: List[str]) -> None:
        assert os.path.exists(self.feature_root), "Feature root path non-existent"
        self.model_ids = check_models(self.feature_root, model_ids, self.split)
        self.model_ids_with_idx = [(i, model_id) for i, model_id in enumerate(self.model_ids)]

    def _prepare_sim_matrix(self) -> np.ndarray:
        return np.ones((len(self.model_ids_with_idx), len(self.model_ids_with_idx)))

    def _load_feature(self, model_id: str) -> np.ndarray:
        raise NotImplementedError()

    def _compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        raise NotImplementedError()

    def compute_pairwise_similarity(self, features_1: np.ndarray, model2: str) -> float:
        features_2 = self._load_feature(model_id=model2)

        assert features_1.shape[0] == features_2.shape[0], (f"Number of features should be equal for "
                                                            f"similarity computation.")

        rho = self._compute_similarity(features_1, features_2)
        return rho

    def compute_similarity_matrix(self) -> np.ndarray:
        sim_matrix = self._prepare_sim_matrix()
        max_workers = self.max_workers
        for idx1, model1 in tqdm(self.model_ids_with_idx, desc=f"Computing {self.name} matrix"):
            features_1 = self._load_feature(model_id=model1)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for idx2, model2 in self.model_ids_with_idx:
                    if idx1 < idx2:
                        future = executor.submit(self.compute_pairwise_similarity, features_1, model2)
                        futures[future] = (idx1, idx2)

                for future in tqdm(as_completed(futures), total=len(futures), desc="Pairwise similarity computation"):
                    cidx1, cidx2 = futures[future]
                    rho = future.result()
                    sim_matrix[cidx1, cidx2] = rho
        upper_tri = np.triu(sim_matrix)
        sim_matrix = upper_tri + upper_tri.T - np.diag(np.diag(sim_matrix))
        return sim_matrix

    def get_model_ids(self) -> List[str]:
        return self.model_ids


class CKAModelSimilarity(BaseModelSimilarity):
    def __init__(self, feature_root: str, subset_root: Optional[str], split: str = 'train', device: str = 'cuda',
                 kernel: str = 'linear', backend: str = 'torch', unbiased: bool = True, sigma: Optional[float] = None,
                 max_workers: int = 4) -> None:
        super().__init__(feature_root=feature_root, subset_root=subset_root, split=split, device=device,
                         max_workers=max_workers)
        self.kernel = kernel
        self.backend = backend
        self.unbiased = unbiased
        self.sigma = sigma

    # def _load_feature(self, model_id:str) -> np.ndarray:
    #     features = load_features(self.feature_root, model_id, self.split, self.subset_indices)
    #     return features

    # def _compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
    #     m = feat1.shape[0]
    #     cka = get_cka(backend=self.backend, m=m, kernel=self.kernel, unbiased=self.unbiased, device=self.device,
    #                     sigma=self.sigma)
    #     rho = cka.compare(X=feat1, Y=feat2)
    #     return rho

    def compute_similarity_matrix(self) -> np.ndarray:
        sim_matrix = self._prepare_sim_matrix()
        for idx1, model1 in tqdm(self.model_ids_with_idx, desc=f"Computing CKA matrix"):
            features_i = load_features(self.feature_root, model1, self.split, self.subset_indices)
            for idx2, model2 in self.model_ids_with_idx:
                if idx1 >= idx2:
                    continue
                features_j = load_features(self.feature_root, model2, self.split, self.subset_indices)
                assert features_i.shape[0] == features_j.shape[0], \
                    f"Number of features should be equal for CKA computation. (model1: {model1}, model2: {model2})"

                m = features_i.shape[0]
                cka = get_cka(backend=self.backend, m=m, kernel=self.kernel, unbiased=self.unbiased, device=self.device,
                              sigma=self.sigma)
                rho = cka.compare(X=features_i, Y=features_j)
                sim_matrix[idx1, idx2] = rho
                sim_matrix[idx2, idx1] = rho

        return sim_matrix

    def get_name(self) -> str:
        method_name = f"cka_kernel_{self.kernel}{'_unbiased' if self.unbiased else '_biased'}"
        if self.kernel == 'rbf':
            method_name += f"_sigma_{self.sigma}"
        return method_name


class RSAModelSimilarity(BaseModelSimilarity):
    def __init__(self, feature_root: str, subset_root: Optional[str], split: str = 'train', device: str = 'cuda',
                 rsa_method: str = 'correlation', corr_method: str = 'spearman', max_workers: int = 4) -> None:
        super().__init__(feature_root=feature_root, subset_root=subset_root, split=split, device=device,
                         max_workers=max_workers)
        self.rsa_method = rsa_method
        self.corr_method = corr_method
        self.name = 'RSA'

    def _load_feature(self, model_id: str) -> np.ndarray:
        features = load_features(self.feature_root, model_id, self.split, self.subset_indices).numpy()
        rdm_features = compute_rdm(features, method=self.rsa_method)
        return rdm_features

    def _compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        return correlate_rdms(feat1, feat2, correlation=self.corr_method)

    def get_name(self):
        if self.rsa_method == 'correlation':
            return f"rsa_method_{self.rsa_method}_corr_method_{self.corr_method}"
        else:
            return f"rsa_method_{self.rsa_method}"


class GWModelSimilarity(BaseModelSimilarity):
    def __init__(
            self,
            feature_root: str,
            subset_root: Optional[str],
            split: str = 'train',
            device: str = 'cuda',
            cost_fun: str = 'euclidian',
            fixed_coupling: bool = False,
            loss_fun: str = 'square_loss',
            max_workers: int = 4,
            store_coupling: bool = False,
            output_root: Optional[str] = None,
    ) -> None:
        super().__init__(feature_root=feature_root, subset_root=subset_root, split=split, device=device,
                         max_workers=max_workers)

        self.output_root = None

        if store_coupling:
            assert output_root is not None, "Output root should be provided for storing coupling matrices"
            self.output_root = Path(output_root)
            assert self.output_root.exists(), "Output root path does not exist"

        self.store_coupling = store_coupling

        if cost_fun not in ['euclidian', 'cosine']:
            raise ValueError(f"Unknown cost function: {cost_fun}")
        else:
            self.cost_fun = cost_fun

        if loss_fun not in ['square_loss', 'kl_loss']:
            raise ValueError(f"Unknown loss function: {loss_fun}")
        else:
            self.loss_fun = loss_fun

        self.fixed_coupling = fixed_coupling

    def _prepare_sim_matrix(self) -> np.ndarray:
        return np.zeros((len(self.model_ids_with_idx), len(self.model_ids_with_idx)))

    def _load_feature(self, model_id: str) -> np.ndarray:
        features = load_features(self.feature_root, model_id, self.split, self.subset_indices).numpy()
        C_mat = cdist(features.numpy(), features, metric=self.cost_fun)
        C_mat /= C_mat.max()
        return C_mat

    def get_name(self):
        return f"gw_sim_cost_{'fixed_coupling' if self.fixed_coupling else 'learned_coupling'}_fun_{self.cost_fun}_loss_fun_{self.loss_fun}"

    def store_coupling_matrix(self, model1: str, model2: str, coupling_matrix: np.ndarray) -> None:
        if self.store_coupling:
            output_path = self.output_root / f"{model1}_{model2}_coupling.npy"
            np.save(output_path, coupling_matrix)

    def _comput_gromov_distance(self, C1: np.ndarray, C2: np.ndarray, T: np.ndarray) -> float:
        # simple get_backend as the full one will be handled in gromov_wasserstein
        nx = ot.backend.get_backend(C1, C2)

        # init marginals if set as None
        p = ot.utils.unif(C1.shape[0], type_as=C1)
        q = ot.utils.unif(C2.shape[0], type_as=C1)

        if self.loss_fun == "square_loss":
            gC1 = 2 * C1 * nx.outer(p, p) - 2 * nx.dot(T, nx.dot(C2, T.T))
            gC2 = 2 * C2 * nx.outer(q, q) - 2 * nx.dot(T.T, nx.dot(C1, T))
        elif self.loss_fun == "kl_loss":
            gC1 = nx.log(C1 + 1e-15) * nx.outer(p, p) - nx.dot(
                T, nx.dot(nx.log(C2 + 1e-15), T.T)
            )
            gC2 = -nx.dot(T.T, nx.dot(C1, T)) / (C2 + 1e-15) + nx.outer(q, q)

        gw = nx.set_gradients(
            gw,
            (p, q, C1, C2),
            (
                log_gw["u"] - nx.mean(log_gw["u"]),
                log_gw["v"] - nx.mean(log_gw["v"]),
                gC1,
                gC2,
            ),
        )

    def compute_similarity_matrix(self) -> np.ndarray:
        dist_matrix = self._prepare_sim_matrix()
        for idx1, model1 in tqdm(self.model_ids_with_idx, desc=f"Computing CKA matrix"):
            C_i = load_features(self.feature_root, model1, self.split, self.subset_indices)
            for idx2, model2 in self.model_ids_with_idx:
                if idx1 >= idx2:
                    continue
                C_j = load_features(self.feature_root, model2, self.split, self.subset_indices)

                assert C_i.shape[0] == C_j.shape[0], \
                    (f"Number of samples should be equal for both models. (model1: {model1}, model2: {model2},"
                     f"feature_root: {self.feature_root})")

                if self.fixed_coupling:
                    T = np.eye(C_i.shape[0])

                else:
                    gw_dist, log_gw = ot.gromov.gromov_wasserstein2(C_i, C_j, loss_fun=self.loss_fun, log=True)

                self.store_coupling_matrix(model1, model2, log_gw['T'])
                dist_matrix[idx1, idx2] = gw_dist
                dist_matrix[idx2, idx1] = gw_dist


def compute_sim_matrix(
        sim_method: str,
        feature_root: str,
        model_ids: List[str],
        split: str,
        subset_root: Optional[str] = None,
        kernel: str = 'linear',
        rsa_method: str = 'correlation',
        corr_method: str = 'spearman',
        backend: str = 'torch',
        unbiased: bool = True,
        device: str = 'cuda',
        sigma: Optional[float] = None,
        max_workers: int = 4,
) -> Tuple[np.ndarray, List[str], str]:
    if sim_method == 'cka':
        model_similarity = CKAModelSimilarity(
            feature_root=feature_root,
            subset_root=subset_root,
            split=split,
            device=device,
            kernel=kernel,
            backend=backend,
            unbiased=unbiased,
            sigma=sigma,
            max_workers=max_workers
        )
    elif sim_method == 'rsa':
        model_similarity = RSAModelSimilarity(
            feature_root=feature_root,
            subset_root=subset_root,
            split=split,
            device=device,
            rsa_method=rsa_method,
            corr_method=corr_method,
            max_workers=max_workers
        )
    else:
        raise ValueError(f"Unknown similarity method: {sim_method}")

    model_similarity.load_model_ids(model_ids)
    model_ids = model_similarity.get_model_ids()
    sim_mat = model_similarity.compute_similarity_matrix()
    method_slug = model_similarity.get_name()
    return sim_mat, model_ids, method_slug
