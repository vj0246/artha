"""D2 preprocessing transforms: denoising behavior and causality."""

import numpy as np

from artha.singlename.preprocess import causal_transform, emd_denoise, wavelet_denoise


def _noisy_series(n: int = 600, seed: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    signal = 0.01 * np.sin(2 * np.pi * t / 63)
    return signal + rng.normal(0, 0.02, n)


def test_wavelet_denoise_reduces_variance_keeps_shape() -> None:
    x = _noisy_series()
    d = wavelet_denoise(x)
    assert d.shape == x.shape
    assert np.var(d) < np.var(x)
    assert np.all(np.isfinite(d))


def test_emd_denoise_removes_high_frequency_energy() -> None:
    x = _noisy_series()
    d = emd_denoise(x)
    assert d.shape == x.shape
    # dropping IMF1 removes the fastest oscillation: day-over-day
    # differences must shrink
    assert np.abs(np.diff(d)).mean() < np.abs(np.diff(x)).mean()


def test_causal_transform_ignores_the_future() -> None:
    x = _noisy_series(400)
    a = causal_transform(x, wavelet_denoise, window=126)
    y = x.copy()
    y[300:] += 5.0  # violently change the future
    b = causal_transform(y, wavelet_denoise, window=126)
    # outputs before the perturbation are bit-identical
    np.testing.assert_array_equal(a[:300], b[:300])


def test_causal_transform_nan_head() -> None:
    x = _noisy_series(200)
    out = causal_transform(x, wavelet_denoise, window=126)
    assert np.isnan(out[:125]).all()
    assert np.isfinite(out[125:]).all()
