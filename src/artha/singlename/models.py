"""D3 model family for the single-name study (TRACK_D_PLAN).

One frozen protocol, many inductive biases — the family separates
information, bias, and luck (plan D3). Floors: always-long and a linear
AR (ridge). Learners: LGBM (tabular nonlinearity), GRU and LSTM
(sequence memory), a small causal transformer (attention over lags),
and the equal-weight ensemble of all learners (the summary's
"ensembles reduce overfitting" claim, tested).

All torch models are deliberately small; they train on CPU or the 4GB
GPU equally well. Determinism: fixed seeds per retrain.
"""

from collections.abc import Callable

import numpy as np
import torch
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from torch import nn

SEQ_LEN = 20
HIDDEN = 32
EPOCHS = 40
LR = 1e-3


def _train_torch(model: nn.Module, x: np.ndarray, y: np.ndarray, seed: int) -> nn.Module:
    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    xt = torch.tensor(x, dtype=torch.float32, device=device)
    yt = torch.tensor(y, dtype=torch.float32, device=device)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.MSELoss()
    model.train()
    for _ in range(EPOCHS):
        opt.zero_grad()
        loss = loss_fn(model(xt).squeeze(-1), yt)
        loss.backward()
        opt.step()
    model.eval()
    return model


class _Recurrent(nn.Module):
    def __init__(self, kind: str) -> None:
        super().__init__()
        rnn_cls = nn.GRU if kind == "gru" else nn.LSTM
        self.rnn = rnn_cls(1, HIDDEN, batch_first=True)
        self.head = nn.Linear(HIDDEN, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x.unsqueeze(-1))
        return torch.as_tensor(self.head(out[:, -1, :]))


class _TinyTransformer(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.proj = nn.Linear(1, HIDDEN)
        self.pos = nn.Parameter(torch.zeros(SEQ_LEN, HIDDEN))
        layer = nn.TransformerEncoderLayer(
            HIDDEN, nhead=4, dim_feedforward=64, batch_first=True, norm_first=True
        )
        self.enc = nn.TransformerEncoder(layer, num_layers=2)
        self.head = nn.Linear(HIDDEN, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.proj(x.unsqueeze(-1)) + self.pos
        return torch.as_tensor(self.head(self.enc(h)[:, -1, :]))


def _torch_factory(kind: str) -> Callable[[np.ndarray, np.ndarray, int], object]:
    def fit(x: np.ndarray, y: np.ndarray, seed: int) -> object:
        model = _TinyTransformer() if kind == "transformer" else _Recurrent(kind)
        return _train_torch(model, x, y, seed)

    return fit


def predict_torch(model: object, x: np.ndarray) -> np.ndarray:
    assert isinstance(model, nn.Module)
    device = next(model.parameters()).device
    with torch.no_grad():
        out = model(torch.tensor(x, dtype=torch.float32, device=device))
    return np.asarray(out.squeeze(-1).cpu().numpy(), dtype=np.float64)


def fit_ridge(x: np.ndarray, y: np.ndarray, seed: int) -> object:
    return Ridge(alpha=1.0).fit(x, y)


def fit_lgbm(x: np.ndarray, y: np.ndarray, seed: int) -> object:
    return LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=60,
        subsample=0.8,
        subsample_freq=1,
        random_state=seed,
        verbose=-1,
    ).fit(x, y)


FAMILY: dict[str, Callable[[np.ndarray, np.ndarray, int], object]] = {
    "ridge": fit_ridge,
    "lgbm": fit_lgbm,
    "gru": _torch_factory("gru"),
    "lstm": _torch_factory("lstm"),
    "transformer": _torch_factory("transformer"),
}


def predict(name: str, model: object, x: np.ndarray) -> np.ndarray:
    if name in ("gru", "lstm", "transformer"):
        return predict_torch(model, x)
    return np.asarray(model.predict(x), dtype=np.float64)  # type: ignore[attr-defined]
