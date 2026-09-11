"""Manifiesto de cada corrida: un resultado que no se puede reproducir no es un resultado.

Guarda el YAML exacto de la estrategia, el hash del dataset, el commit del código
y las métricas. Todo eso es determinístico: dos corridas del mismo backtest
producen el mismo archivo byte a byte.

La única excepción es ``created_at``, que por definición cambia entre corridas.
Está fuera del ``fingerprint`` y ``deterministic_payload()`` lo excluye, que es
lo que compara el test de reproducibilidad.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot import __version__
from tradingbot.config import StrategyConfig
from tradingbot.data.cache import dataset_hash


def code_commit(repo_dir: str | Path | None = None) -> str:
    """Commit del código, o ``desconocido`` si no hay git alrededor."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir) if repo_dir else None,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return "desconocido"
    return out.stdout.strip() if out.returncode == 0 else "desconocido"


def build_manifest(
    config: StrategyConfig,
    frames: dict[str, pd.DataFrame],
    metrics: dict[str, Any],
    *,
    repo_dir: str | Path | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tradingbot_version": __version__,
        "code_commit": code_commit(repo_dir),
        "strategy": json.loads(config.model_dump_json()),
        "data": {
            "symbols": sorted(frames),
            "hash": dataset_hash(frames),
            "bars": {s: int(len(frames[s])) for s in sorted(frames)},
            "first_bar": min(df.index[0] for df in frames.values()).strftime("%Y-%m-%d"),
            "last_bar": max(df.index[-1] for df in frames.values()).strftime("%Y-%m-%d"),
        },
        "metrics": _round_metrics(metrics),
    }
    payload["fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    payload["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return payload


def deterministic_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    """El manifiesto sin el único campo que cambia entre corridas."""
    return {k: v for k, v in manifest.items() if k != "created_at"}


def dumps(manifest: dict[str, Any], *, deterministic: bool = False) -> str:
    data = deterministic_payload(manifest) if deterministic else manifest
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def save_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(manifest), encoding="utf-8")
    return path


def _round_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Redondea los floats para que el manifiesto no dependa del último bit."""
    out: dict[str, Any] = {}
    for key, value in sorted(metrics.items()):
        if isinstance(value, float):
            out[key] = None if pd.isna(value) else round(value, 10)
        else:
            out[key] = value
    return out
