"""Denoising transforms for the D2 preprocessing study (TRACK_D_PLAN).

Two families from the forecasting literature, each applied to a return
series in two variants:

- LEAKY: transform the full series once. This is how most published
  decomposition-forecasting papers do it, and it lets every training
  sample see the future through the transform.
- CAUSAL: at each step t, transform only the trailing window ending at
  t and keep the LAST value. Nothing after t ever touches the output.

The delta between variants measures how much of a method's apparent
edge is look-ahead. Wavelet denoising: Donoho-Johnstone soft threshold
(universal threshold, db4). EMD: drop the highest-frequency IMF
(standard noise-removal convention); CEEMDAN is the noise-assisted
variant (Torres 2011) — its causal form is computationally prohibitive
at daily re-decomposition, so it runs leaky-only with that limitation
recorded (EMD serves as the causal representative of the family).
"""

import math
import warnings

import numpy as np
import pywt

WAVELET = "db4"
CAUSAL_WINDOW = 252


def wavelet_denoise(x: np.ndarray, *, wavelet: str = WAVELET) -> np.ndarray:
    """Donoho-Johnstone soft-threshold denoising; output same length."""
    n = len(x)
    coeffs = pywt.wavedec(x, wavelet, mode="periodization")
    # noise scale from the finest detail level, MAD estimator
    sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if len(coeffs[-1]) else 0.0
    thresh = sigma * math.sqrt(2 * math.log(max(n, 2)))
    denoised = [coeffs[0]] + [pywt.threshold(c, thresh, mode="soft") for c in coeffs[1:]]
    out = pywt.waverec(denoised, wavelet, mode="periodization")
    return np.asarray(out[:n])


def emd_denoise(x: np.ndarray) -> np.ndarray:
    """Remove the highest-frequency IMF (the conventional noise component)."""
    from PyEMD import EMD

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        imfs = EMD(DTYPE=np.float64, spline_kind="cubic").emd(x)
    if imfs.shape[0] <= 1:
        return x.copy()
    return np.asarray(imfs[1:].sum(axis=0))


def ceemdan_denoise(x: np.ndarray, *, trials: int = 50, seed: int = 7) -> np.ndarray:
    """CEEMDAN (Torres 2011) noise removal: drop IMF1. Leaky use only —
    causal daily re-decomposition is computationally prohibitive."""
    from PyEMD import CEEMDAN

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dec = CEEMDAN(trials=trials, seed=seed)
        imfs = dec.ceemdan(x)
    if imfs.shape[0] <= 1:
        return x.copy()
    return np.asarray(imfs[1:].sum(axis=0))


def causal_transform(x: np.ndarray, fn: object, *, window: int = CAUSAL_WINDOW) -> np.ndarray:
    """Causal variant of any full-series transform: output[t] is the last
    value of fn(x[t-window+1 .. t]). The first window-1 outputs are NaN.
    By construction, changing x[t+1:] cannot change output[:t+1]."""
    assert callable(fn)
    n = len(x)
    out = np.full(n, np.nan)
    for t in range(window - 1, n):
        out[t] = fn(x[t - window + 1 : t + 1])[-1]
    return out
