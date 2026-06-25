"""
Board-position value estimator for ISMCTS.

Replaces full game rollouts with a fast learned approximation.
Trained on (features, terminal_score_diff) pairs from self-play games.

Interface
---------
    from value import ValueModel
    model = ValueModel.load()          # load from model/
    v = model.predict(features)        # float in ~[-1, 1]
    model.fit(X, y)                    # train / retrain
    model.save()                       # write to model/

The model is intentionally simple (linear regression) so it is:
  - Fast at inference (one dot product)
  - Easy to train with small amounts of data (100-500 games)
  - Interpretable (weight per feature)
An MLP option is provided via --model mlp for higher capacity.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import math

from features import N_FEATURES, FEATURE_NAMES

_MODEL_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model")
_WEIGHTS_F  = os.path.join(_MODEL_DIR, "value_weights.json")


# ---------------------------------------------------------------------------
# Linear value model (default)
# ---------------------------------------------------------------------------

class LinearValue:
    """Single-layer linear regression: v = w · x + b."""

    def __init__(self):
        self.w = [0.0] * N_FEATURES
        self.b = 0.0

    def predict(self, x: list) -> float:
        return sum(wi * xi for wi, xi in zip(self.w, x)) + self.b

    def fit(self, X: list, y: list, lr: float = 0.01, epochs: int = 200):
        """Stochastic gradient descent on MSE loss. X: list of feature lists."""
        n = len(X)
        if n == 0:
            return
        import random
        rng = random.Random(42)
        indices = list(range(n))
        for _ in range(epochs):
            rng.shuffle(indices)
            for i in indices:
                xi, yi = X[i], y[i]
                pred = self.predict(xi)
                err  = pred - yi
                self.b -= lr * err
                for j in range(N_FEATURES):
                    self.w[j] -= lr * err * xi[j]

    def to_dict(self) -> dict:
        return {"type": "linear", "w": self.w, "b": self.b,
                "feature_names": FEATURE_NAMES}

    @classmethod
    def from_dict(cls, d: dict) -> "LinearValue":
        m = cls()
        m.w = list(d["w"])
        m.b = float(d["b"])
        return m


# ---------------------------------------------------------------------------
# MLP value model (optional — higher capacity)
# ---------------------------------------------------------------------------

class MLPValue:
    """
    Two-layer MLP: x → ReLU(W1·x + b1) → W2·h + b2 → scalar.
    Hidden size is fixed at 64.
    Trained with SGD + MSE loss (no external dependencies).
    """

    HIDDEN = 64

    def __init__(self):
        H = self.HIDDEN
        # Xavier init
        scale1 = math.sqrt(2.0 / N_FEATURES)
        scale2 = math.sqrt(2.0 / H)
        import random
        rng = random.Random(0)
        self.W1 = [[rng.gauss(0, scale1) for _ in range(N_FEATURES)] for _ in range(H)]
        self.b1 = [0.0] * H
        self.W2 = [rng.gauss(0, scale2) for _ in range(H)]
        self.b2 = 0.0

    def _forward(self, x):
        H = self.HIDDEN
        h = [max(0.0, sum(self.W1[i][j] * x[j] for j in range(N_FEATURES)) + self.b1[i])
             for i in range(H)]
        out = sum(self.W2[i] * h[i] for i in range(H)) + self.b2
        return h, out

    def predict(self, x: list) -> float:
        _, out = self._forward(x)
        return out

    def fit(self, X: list, y: list, lr: float = 0.005, epochs: int = 100):
        n = len(X)
        if n == 0:
            return
        import random
        H = self.HIDDEN
        rng = random.Random(42)
        indices = list(range(n))
        for _ in range(epochs):
            rng.shuffle(indices)
            for i in indices:
                xi, yi = X[i], y[i]
                h, pred = self._forward(xi)
                err = pred - yi           # dL/d_out = err (MSE gradient)
                # Output layer gradients
                self.b2 -= lr * err
                dh = [0.0] * H
                for k in range(H):
                    self.W2[k] -= lr * err * h[k]
                    dh[k] = err * self.W2[k]
                # Hidden layer gradients (ReLU: zero if h[k]==0)
                for k in range(H):
                    if h[k] <= 0:
                        continue
                    dk = dh[k]
                    self.b1[k] -= lr * dk
                    for j in range(N_FEATURES):
                        self.W1[k][j] -= lr * dk * xi[j]

    def to_dict(self) -> dict:
        return {"type": "mlp", "hidden": self.HIDDEN,
                "W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2,
                "feature_names": FEATURE_NAMES}

    @classmethod
    def from_dict(cls, d: dict) -> "MLPValue":
        m = cls.__new__(cls)
        m.W1 = d["W1"]
        m.b1 = d["b1"]
        m.W2 = d["W2"]
        m.b2 = float(d["b2"])
        return m


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class ValueModel:
    """Thin wrapper around a Linear or MLP model with load/save/predict."""

    def __init__(self, inner=None):
        self._m = inner or LinearValue()

    def predict(self, features: list) -> float:
        return self._m.predict(features)

    def fit(self, X: list, y: list, **kw):
        self._m.fit(X, y, **kw)

    def save(self):
        os.makedirs(_MODEL_DIR, exist_ok=True)
        with open(_WEIGHTS_F, "w") as f:
            json.dump(self._m.to_dict(), f, indent=2)

    @classmethod
    def load(cls) -> "ValueModel":
        if not os.path.exists(_WEIGHTS_F):
            return cls()
        with open(_WEIGHTS_F) as f:
            d = json.load(f)
        if d.get("type") == "mlp":
            return cls(MLPValue.from_dict(d))
        return cls(LinearValue.from_dict(d))

    @classmethod
    def new_mlp(cls) -> "ValueModel":
        return cls(MLPValue())

    def mse(self, X: list, y: list) -> float:
        if not X:
            return float("nan")
        errs = [(self.predict(x) - yi) ** 2 for x, yi in zip(X, y)]
        return sum(errs) / len(errs)
