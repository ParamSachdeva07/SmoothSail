"""The same trilinear interpolation for route samples and display batches."""
from dataclasses import dataclass
from itertools import product
import math

import numpy as np


CORNERS = tuple(product((0, 1), repeat=3))


def blend(a, b, fraction):
    # Exact grid nodes use only their observed value, even if a neighbour is missing.
    return a if fraction == 0 else b if fraction == 1 else a * (1 - fraction) + b * fraction


@dataclass(frozen=True)
class GridField:
    axes: tuple
    values: np.ndarray
    maximum_gap_seconds: float
    snapshot_id: str

    def sample(self, timestamp, latitude, longitude):
        indices, fractions = [], []
        for axis, value in zip(self.axes, (timestamp, latitude, longitude)):
            if value < axis[0] or value > axis[-1]:
                return None
            index = min(len(axis) - 2, max(0, int(axis.searchsorted(value)) - 1))
            indices.append(index)
            fractions.append(float((value - axis[index]) / (axis[index + 1] - axis[index])))
        t = fractions[0]
        if 0 < t < 1 and self.axes[0][indices[0] + 1] - self.axes[0][indices[0]] > self.maximum_gap_seconds:
            return None
        i, j, k = indices
        t, y, x = fractions
        cells = self.values
        lower = blend(blend(cells[i, j, k], cells[i, j, k + 1], x),
                      blend(cells[i, j + 1, k], cells[i, j + 1, k + 1], x), y)
        upper = blend(blend(cells[i + 1, j, k], cells[i + 1, j, k + 1], x),
                      blend(cells[i + 1, j + 1, k], cells[i + 1, j + 1, k + 1], x), y)
        result = float(blend(lower, upper, t))
        return result if math.isfinite(result) else None

    def sample_many(self, coordinates):
        """Nx3 [UTC seconds, latitude, longitude]; NaN denotes unknown, never calm."""
        indices, fractions = [], []
        valid = np.isfinite(coordinates).all(axis=1)
        for axis, column in zip(self.axes, coordinates.T):
            valid &= (column >= axis[0]) & (column <= axis[-1])
            index = np.clip(axis.searchsorted(column) - 1, 0, len(axis) - 2)
            indices.append(index)
            fractions.append((column - axis[index]) / (axis[index + 1] - axis[index]))
        gap = self.axes[0][indices[0] + 1] - self.axes[0][indices[0]]
        valid &= (fractions[0] == 0) | (fractions[0] == 1) | (gap <= self.maximum_gap_seconds)
        result = np.zeros(len(coordinates))
        for corner in CORNERS:
            weight = np.prod([f if bit else 1 - f for f, bit in zip(fractions, corner)], axis=0)
            value = self.values[tuple(i + bit for i, bit in zip(indices, corner))]
            needed = weight != 0
            valid &= ~needed | np.isfinite(value)
            result += np.where(needed, np.nan_to_num(value) * weight, 0)
        return np.where(valid, result, np.nan)
