"""Small tabular transformer for the model study (plan v2 section 7.3).

FT-Transformer-style: each feature becomes a token (value * learned
embedding + feature bias), a CLS token attends over them through a small
encoder, and a linear head regresses the label. This is the standard way to
put a transformer on tabular cross-sectional data; at ~230k weekly rows and
19 features the model is deliberately tiny. Runs on CUDA when available
(RTX 2050), otherwise CPU — at this scale both are minutes per fold.

Wrapped in the study's fit/predict protocol.
"""

from typing import cast

import numpy as np
import torch
from torch import nn

SEED = 7


class _FTLite(nn.Module):
    def __init__(self, n_features: int, d_model: int, n_heads: int, n_layers: int) -> None:
        super().__init__()
        self.value_emb = nn.Parameter(torch.randn(n_features, d_model) * 0.02)
        self.feat_bias = nn.Parameter(torch.zeros(n_features, d_model))
        self.cls = nn.Parameter(torch.zeros(1, 1, d_model))
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=d_model * 2,
            dropout=0.1,
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        tokens = x.unsqueeze(-1) * self.value_emb + self.feat_bias
        cls = self.cls.expand(x.shape[0], -1, -1)
        out = self.encoder(torch.cat([cls, tokens], dim=1))
        return cast(torch.Tensor, self.head(out[:, 0, :]).squeeze(-1))


class TabTransformerRegressor:
    """sklearn-like wrapper satisfying models.study.SupervisedModel."""

    def __init__(
        self,
        d_model: int = 32,
        n_heads: int = 2,
        n_layers: int = 1,
        epochs: int = 15,
        batch_size: int = 8192,
        lr: float = 1e-3,
    ) -> None:
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._net: _FTLite | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "TabTransformerRegressor":
        torch.manual_seed(SEED)
        net = _FTLite(X.shape[1], self.d_model, self.n_heads, self.n_layers).to(self.device)
        opt = torch.optim.AdamW(net.parameters(), lr=self.lr, weight_decay=1e-4)
        loss_fn = nn.MSELoss()
        xt = torch.tensor(X, dtype=torch.float32)
        yt = torch.tensor(y, dtype=torch.float32)
        n = len(xt)
        net.train()
        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for i in range(0, n, self.batch_size):
                idx = perm[i : i + self.batch_size]
                xb = xt[idx].to(self.device)
                yb = yt[idx].to(self.device)
                opt.zero_grad()
                loss = loss_fn(net(xb), yb)
                loss.backward()
                opt.step()
        self._net = net
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._net is None:
            raise RuntimeError("fit before predict")
        self._net.eval()
        out: list[np.ndarray] = []
        with torch.no_grad():
            xt = torch.tensor(X, dtype=torch.float32)
            for i in range(0, len(xt), self.batch_size):
                xb = xt[i : i + self.batch_size].to(self.device)
                out.append(self._net(xb).cpu().numpy())
        return np.concatenate(out)
