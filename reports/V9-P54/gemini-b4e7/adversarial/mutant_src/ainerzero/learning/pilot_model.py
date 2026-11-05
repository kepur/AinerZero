"""FP32, action-conditioned pilot RSSM; this module alone imports MLX.

All random initialization and latent samples take explicit PRNG keys. No world
state or future observation is accepted by ``imagine``. Batch arrays contain
only the public sensor stream: B x (T + 1) observations and B x T actions.
"""

from __future__ import annotations

import math

import mlx.core as mx
import mlx.nn as nn

from ainerzero.core.pilot import PilotModel


class _Linear(nn.Module):
    """Xavier weights and zero bias without touching MLX's global RNG."""

    def __init__(self, inputs: int, outputs: int, *, key: mx.array):
        super().__init__()
        bound = math.sqrt(6 / (inputs + outputs))
        self.weight = mx.random.uniform(
            -bound, bound, shape=(outputs, inputs), dtype=mx.float32, key=key
        )
        self.bias = mx.zeros((outputs,), dtype=mx.float32)

    def __call__(self, x: mx.array) -> mx.array:
        return mx.addmm(self.bias, x, self.weight.T)


class _Embedding(nn.Module):
    def __init__(self, count: int, width: int, *, key: mx.array):
        super().__init__()
        self.weight = mx.random.normal(
            (count, width), scale=math.sqrt(1 / width), dtype=mx.float32, key=key
        )

    def __call__(self, indexes: mx.array) -> mx.array:
        return self.weight[indexes]


class _GRUCell(nn.Module):
    """One MLX-style GRU step, with explicit-key Xavier initialization.

    Parameter layout and equations match the installed MLX GRU (Wx, Wh, b,
    bhn). Explicit initialization avoids its constructor's global random state.
    """

    def __init__(self, inputs: int, hidden: int, *, key: mx.array):
        super().__init__()
        input_key, hidden_key = mx.random.split(key)
        input_bound = math.sqrt(6 / (inputs + 3 * hidden))
        hidden_bound = math.sqrt(6 / (4 * hidden))
        self.Wx = mx.random.uniform(
            -input_bound, input_bound, (3 * hidden, inputs), dtype=mx.float32, key=input_key
        )
        self.Wh = mx.random.uniform(
            -hidden_bound, hidden_bound, (3 * hidden, hidden), dtype=mx.float32, key=hidden_key
        )
        self.b = mx.zeros((3 * hidden,), dtype=mx.float32)
        self.bhn = mx.zeros((hidden,), dtype=mx.float32)

    def __call__(self, x: mx.array, h: mx.array) -> mx.array:
        xr, xg, xn = mx.split(mx.addmm(self.b, x, self.Wx.T), 3, axis=-1)
        hr, hg, hn = mx.split(h @ self.Wh.T, 3, axis=-1)
        reset = mx.sigmoid(xr + hr)
        gate = mx.sigmoid(xg + hg)
        candidate = mx.tanh(xn + reset * (hn + self.bhn))
        return (1 - gate) * candidate + gate * h


class PilotPredictor(nn.Module):
    """The registered 653,072-parameter pilot; no pretrained knowledge."""

    ARCHITECTURE = "pilot_predictor_v1"

    def __init__(self, config: PilotModel | None = None, *, key: mx.array):
        super().__init__()
        config = PilotModel.model_validate(config or PilotModel())
        keys = iter(mx.random.split(key, num=11))
        self.byte_embedding = _Embedding(256, config.byte_embedding_dim, key=next(keys))
        self.action_embedding = _Embedding(4, config.action_embedding_dim, key=next(keys))
        self.encoder = [
            _Linear(144, config.encoder_hidden_dim, key=next(keys)),
            _Linear(config.encoder_hidden_dim, config.embedding_dim, key=next(keys)),
        ]
        self.gru = _GRUCell(32, config.hidden_dim, key=next(keys))
        self.prior = [
            _Linear(config.hidden_dim, config.prior_hidden_dim, key=next(keys)),
            _Linear(config.prior_hidden_dim, 2 * config.latent_dim, key=next(keys)),
        ]
        self.posterior = [
            _Linear(config.hidden_dim + config.embedding_dim, 128, key=next(keys)),
            _Linear(128, 2 * config.latent_dim, key=next(keys)),
        ]
        self.decoder = [
            _Linear(config.hidden_dim + config.latent_dim, 128, key=next(keys)),
            _Linear(128, 2064, key=next(keys)),
        ]

    def initial(self, batch_size: int) -> tuple[mx.array, mx.array]:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        return mx.zeros((batch_size, 256)), mx.zeros((batch_size, 16))

    def encode(self, symbols: mx.array, visible_mask: mx.array, cursor: mx.array) -> mx.array:
        # Hidden byte slots must not leak their stored placeholder values.
        masked_symbols = mx.where(visible_mask, symbols, 0)
        embedded = self.byte_embedding(masked_symbols) * visible_mask[..., None]
        one_hot_cursor = (cursor[..., None] == mx.arange(8)).astype(mx.float32)
        x = mx.concatenate(
            [embedded.reshape((-1, 128)), visible_mask.astype(mx.float32), one_hot_cursor],
            axis=-1,
        )
        return nn.silu(self.encoder[1](nn.silu(self.encoder[0](x))))

    @staticmethod
    def _distribution(layers: list, x: mx.array) -> tuple[mx.array, mx.array]:
        mean, raw_std = mx.split(layers[1](nn.silu(layers[0](x))), 2, axis=-1)
        return mean, nn.softplus(raw_std) + 0.1

    def prior_distribution(self, h: mx.array) -> tuple[mx.array, mx.array]:
        return self._distribution(self.prior, h)

    def decode(self, h: mx.array, z: mx.array) -> dict[str, mx.array]:
        logits = self.decoder[1](nn.silu(self.decoder[0](mx.concatenate([h, z], axis=-1))))
        return {
            "symbols": logits[:, :2048].reshape((-1, 8, 256)),
            "visibility": logits[:, 2048:2056],
            "cursor": logits[:, 2056:],
        }

    def observe(
        self,
        h: mx.array,
        symbols: mx.array,
        visible_mask: mx.array,
        cursor: mx.array,
        *,
        key: mx.array,
    ) -> dict:
        embedding = self.encode(symbols, visible_mask, cursor)
        mean, std = self._distribution(self.posterior, mx.concatenate([h, embedding], axis=-1))
        z = mean + std * mx.random.normal(mean.shape, dtype=mx.float32, key=key)
        return {"h": h, "z": z, "mean": mean, "std": std, "logits": self.decode(h, z)}

    def imagine(self, h: mx.array, z: mx.array, actions: mx.array, *, key: mx.array) -> dict:
        next_h = self.gru(mx.concatenate([z, self.action_embedding(actions)], axis=-1), h)
        mean, std = self.prior_distribution(next_h)
        next_z = mean + std * mx.random.normal(mean.shape, dtype=mx.float32, key=key)
        return {
            "h": next_h,
            "z": next_z,
            "mean": mean,
            "std": std,
            "logits": self.decode(next_h, next_z),
        }


class ObservationStatePredictor(PilotPredictor):
    """Same tensors, with a learned deterministic path for current observation.

    The encoder overwrites the first half of the returned deterministic state;
    the other half retains the incoming recurrent state. No symbols are copied
    directly to output classes. The posterior distribution still conditions on
    the incoming state, before this observation write. Tensor compatibility does
    not make this architecture interchangeable with the original pilot.
    """

    ARCHITECTURE = "pilot_observation_state_v1"

    def observe(
        self,
        h: mx.array,
        symbols: mx.array,
        visible_mask: mx.array,
        cursor: mx.array,
        *,
        key: mx.array,
    ) -> dict:
        embedding = self.encode(symbols, visible_mask, cursor)
        mean, std = self._distribution(self.posterior, mx.concatenate([h, embedding], axis=-1))
        z = mean + std * mx.random.normal(mean.shape, dtype=mx.float32, key=key)
        observed_h = mx.concatenate([embedding, h[:, 128:]], axis=-1)
        return {
            "h": observed_h,
            "z": z,
            "mean": mean,
            "std": std,
            "logits": self.decode(observed_h, z),
        }


def observation_loss(
    logits: dict[str, mx.array], symbols: mx.array, visible_mask: mx.array, cursor: mx.array
) -> tuple[mx.array, mx.array]:
    """Per-example observation loss and symbol NLL; no hidden symbol labels."""
    labels = mx.where(visible_mask, symbols, 0)
    symbol_error = nn.losses.cross_entropy(logits["symbols"], labels)
    visible = visible_mask.astype(mx.float32)
    symbol_nll = mx.sum(symbol_error * visible, axis=-1) / mx.maximum(mx.sum(visible, axis=-1), 1)
    visibility_nll = mx.mean(
        nn.losses.binary_cross_entropy(logits["visibility"], visible, reduction="none"), axis=-1
    )
    cursor_nll = nn.losses.cross_entropy(logits["cursor"], cursor)
    return symbol_nll + 0.2 * visibility_nll + 0.2 * cursor_nll, symbol_nll


class SharedSymbolPredictor(PilotPredictor):
    """Smaller shared symbol codec with explicit observation slots in h.

    Byte embeddings and the independent linear readout are both randomly
    initialized and learned. No token IDs or one-hot answers bypass the state.
    This is a declared cellwise representation bias, not learned world rules.
    """

    ARCHITECTURE = "pilot_shared_symbol_v1"

    def __init__(self, config: PilotModel | None = None, *, key: mx.array):
        super().__init__(config, key=key)
        auxiliary_key, readout_key = mx.random.split(key, num=13)[-2:]
        self.decoder[1] = _Linear(128, 16, key=auxiliary_key)
        self.symbol_readout = _Linear(16, 256, key=readout_key)

    def decode(self, h: mx.array, z: mx.array) -> dict[str, mx.array]:
        auxiliary = self.decoder[1](nn.silu(self.decoder[0](mx.concatenate([h, z], axis=-1))))
        slots = h[:, :128].reshape((-1, 8, 16))
        return {
            "symbols": self.symbol_readout(slots),
            "visibility": auxiliary[:, :8],
            "cursor": auxiliary[:, 8:],
        }

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        embedding = self.encode(symbols, visible_mask, cursor)
        mean, std = self._distribution(self.posterior, mx.concatenate([h, embedding], axis=-1))
        z = mean + std * mx.random.normal(mean.shape, dtype=mx.float32, key=key)
        masked = mx.where(visible_mask, symbols, 0)
        slots = (self.byte_embedding(masked) * visible_mask[..., None]).reshape((-1, 128))
        observed_h = mx.concatenate([slots, h[:, 128:]], axis=-1)
        return {
            "h": observed_h,
            "z": z,
            "mean": mean,
            "std": std,
            "logits": self.decode(observed_h, z),
        }


def reconstruction_loss(
    model: PilotPredictor,
    batch: dict[str, mx.array],
    *,
    key: mx.array,
) -> tuple[mx.array, dict[str, mx.array]]:
    """Reconstruct one current frame from a fresh state, without transitions.

    Only symbols [B,8], visible_mask [B,8], and cursor [B] are accepted. The
    decoder reads the returned h/z rather than an observation cached elsewhere.
    There is no action, next-frame label, prior prediction, or KL objective.
    """
    if set(batch) != {"symbols", "visible_mask", "cursor"}:
        raise ValueError("reconstruction batch must contain only symbols, visible_mask, cursor")
    symbols = batch["symbols"]
    if symbols.ndim != 2 or symbols.shape[1] != 8 or symbols.shape[0] < 1:
        raise ValueError("symbols must have shape [B,8] with positive batch size")
    size = symbols.shape[0]
    if batch["visible_mask"].shape != symbols.shape:
        raise ValueError("visible_mask must match symbols shape [B,8]")
    if batch["cursor"].shape != (size,):
        raise ValueError("cursor must have shape [B]")
    h, _ = model.initial(size)
    posterior = model.observe(h, symbols, batch["visible_mask"], batch["cursor"], key=key)
    per_example, symbol_nll = observation_loss(
        model.decode(posterior["h"], posterior["z"]),
        symbols,
        batch["visible_mask"],
        batch["cursor"],
    )
    total = mx.mean(per_example)
    return total, {"reconstruction_loss": total, "symbol_nll": mx.mean(symbol_nll)}


def transition_observation_loss(
    logits, symbols, visible_mask, cursor, previous_symbols, previous_mask, changed_weight
):
    """Upweight visible changes in labels only; return raw NLL separately.

    Weights are normalized within each frame. Hidden-to-visible cells retain
    ordinary weight, because their previous value was not observable.
    """
    total, raw_nll = observation_loss(logits, symbols, visible_mask, cursor)
    if changed_weight == 1.0:
        return total, raw_nll
    changed = visible_mask & previous_mask & (symbols != previous_symbols)
    weights = visible_mask.astype(mx.float32) * (1 + (changed_weight - 1) * changed)
    labels = mx.where(visible_mask, symbols, 0)
    errors = nn.losses.cross_entropy(logits["symbols"], labels)
    weighted = mx.sum(errors * weights, axis=-1) / mx.maximum(mx.sum(weights, axis=-1), 1)
    return total - raw_nll + weighted, raw_nll


def sequence_loss(
    model: PilotPredictor,
    batch: dict[str, mx.array],
    *,
    burn_in: int = 4,
    beta_kl: float,
    key: mx.array,
    changed_weight: float = 1.0,
    rollout_horizon: int = 1,
    rollout_weight: float = 0.0,
) -> tuple[mx.array, dict[str, mx.array]]:
    """Posterior reconstruction + one-step prior prediction + free-nats KL.

    ``symbols``/``visible_mask`` are [B,T+1,8], ``cursor``/``episode_start``
    [B,T+1], and ``actions`` [B,T]. Optional ``valid_mask`` is [B,T] (defaults
    to all valid). Episode boundaries reset belief and invalidate the transition
    crossing into the next episode. Burn-in supplies state but no loss/gradient.
    Fixed windows from the middle of an episode approximate earlier context.
    """
    actions = batch["actions"]
    if actions.ndim != 2:
        raise ValueError("actions must have shape [B,T]")
    size, steps = actions.shape
    if size < 1 or type(burn_in) is not int or not 0 <= burn_in < steps:
        raise ValueError("burn_in must leave at least one training transition")
    if not math.isfinite(beta_kl) or not 0 <= beta_kl <= 0.1:
        raise ValueError("beta_kl must be finite and between 0 and 0.1")
    if not math.isfinite(changed_weight) or not 1 <= changed_weight <= 16:
        raise ValueError("changed_weight must be finite and between 1 and 16")
    if type(rollout_horizon) is not int or rollout_horizon not in (1, 4):
        raise ValueError("rollout_horizon must be 1 or 4")
    if not math.isfinite(rollout_weight) or not 0 <= rollout_weight <= 1:
        raise ValueError("rollout_weight must be finite and between 0 and 1")
    if rollout_weight and (rollout_horizon != 4 or steps - burn_in < rollout_horizon):
        raise ValueError("rollout loss requires a complete four-step learning path")
    expected_shapes = {
        "symbols": (size, steps + 1, 8),
        "visible_mask": (size, steps + 1, 8),
        "cursor": (size, steps + 1),
        "episode_start": (size, steps + 1),
    }
    for name, shape in expected_shapes.items():
        if batch[name].shape != shape:
            raise ValueError(f"{name} must have shape {shape}")
    valid_mask = batch.get("valid_mask", mx.ones(actions.shape, dtype=mx.bool_))
    if valid_mask.shape != actions.shape:
        raise ValueError("valid_mask must match actions shape")
    h, _ = model.initial(size)
    losses = {name: [] for name in ("posterior_loss", "prior_loss", "kl", "symbol_prior_nll")}
    masks = []
    step_keys = mx.random.split(key, num=2 * steps)
    rollout_losses, rollout_nlls, rollout_masks = [], [], []
    if rollout_weight:
        # Separate keys leave the causal one-step stream identical across arms.
        rollout_keys = mx.random.split(mx.random.split(key)[1], num=3 * steps)
    for t in range(steps):
        h = mx.where(batch["episode_start"][:, t, None], mx.zeros_like(h), h)
        if t == burn_in:
            h = mx.stop_gradient(h)
        posterior = model.observe(
            h,
            batch["symbols"][:, t],
            batch["visible_mask"][:, t],
            batch["cursor"][:, t],
            key=step_keys[2 * t],
        )
        imagined = model.imagine(
            posterior["h"], posterior["z"], actions[:, t], key=step_keys[2 * t + 1]
        )
        if t >= burn_in:
            reconstruction, _ = observation_loss(
                posterior["logits"],
                batch["symbols"][:, t],
                batch["visible_mask"][:, t],
                batch["cursor"][:, t],
            )
            prediction, symbol_nll = transition_observation_loss(
                imagined["logits"],
                batch["symbols"][:, t + 1],
                batch["visible_mask"][:, t + 1],
                batch["cursor"][:, t + 1],
                batch["symbols"][:, t],
                batch["visible_mask"][:, t],
                changed_weight,
            )
            if rollout_weight and t + rollout_horizon <= steps:
                future = imagined
                path_valid = valid_mask[:, t] & ~batch["episode_start"][:, t + 1]
                for offset in range(1, rollout_horizon):
                    future = model.imagine(
                        future["h"],
                        future["z"],
                        actions[:, t + offset],
                        key=rollout_keys[3 * t + offset - 1],
                    )
                    path_valid = (
                        path_valid
                        & valid_mask[:, t + offset]
                        & ~batch["episode_start"][:, t + offset + 1]
                    )
                target = t + rollout_horizon
                future_loss, future_nll = transition_observation_loss(
                    future["logits"],
                    batch["symbols"][:, target],
                    batch["visible_mask"][:, target],
                    batch["cursor"][:, target],
                    batch["symbols"][:, t],
                    batch["visible_mask"][:, t],
                    changed_weight,
                )
                rollout_losses.append(future_loss)
                rollout_nlls.append(future_nll)
                rollout_masks.append(path_valid.astype(mx.float32))
            # The prior must not see the current observation written by observe.
            prior_mean, prior_std = model.prior_distribution(h)
            q_mean, q_std = posterior["mean"], posterior["std"]
            kl = mx.sum(
                mx.log(prior_std / q_std)
                + (mx.square(q_std) + mx.square(q_mean - prior_mean)) / (2 * mx.square(prior_std))
                - 0.5,
                axis=-1,
            )
            losses["posterior_loss"].append(reconstruction)
            losses["prior_loss"].append(prediction)
            losses["symbol_prior_nll"].append(symbol_nll)
            losses["kl"].append(mx.maximum(kl, 1.0))
            masks.append(
                valid_mask[:, t].astype(mx.float32)
                * (1 - batch["episode_start"][:, t + 1].astype(mx.float32))
            )
        h = mx.where(valid_mask[:, t, None], imagined["h"], h)
    weights = mx.stack(masks, axis=1)
    denominator = mx.maximum(mx.sum(weights), 1)
    metrics = {
        name: mx.sum(mx.stack(values, axis=1) * weights) / denominator
        for name, values in losses.items()
    }
    total = metrics["posterior_loss"] + metrics["prior_loss"] + beta_kl * metrics["kl"]
    if rollout_weight:
        path_weights = mx.stack(rollout_masks, axis=1)
        path_count = mx.sum(path_weights)
        for name, values in (
            ("rollout_loss", rollout_losses),
            ("symbol_rollout_nll", rollout_nlls),
        ):
            metrics[name] = mx.sum(mx.stack(values, axis=1) * path_weights) / mx.maximum(
                path_count, 1
            )
        metrics["rollout_valid_paths"] = path_count
        total = total + rollout_weight * metrics["rollout_loss"]
    return total, metrics
