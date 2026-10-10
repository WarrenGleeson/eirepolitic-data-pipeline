#!/usr/bin/env python3
"""Apply Director-only review adjustments after the production audit.

For the TD comparison, the Ceann Comhairle is not an ordinary comparable voting
member. Remove Verona Murphy from the TD review output entirely. This script
changes review evidence only; it does not mutate production source data.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

OUT_DIR = Path(os.getenv("DIRECTOR_VOTE_AUDIT_DIR", "artifacts/director-recorded-voting-participation"))
TD_PATH = OUT_DIR / "td_participation.csv"
CEANN_MEMBER_CODE = "Verona-Murphy.D.2020-02-08"
CEANN_NAME = "Verona Murphy"


def main() -> int:
    td = pd.read_csv(TD_PATH)
    before = len(td)
    mask = td["member_code"].astype(str).eq(CEANN_MEMBER_CODE) | td["member_name"].astype(str).eq(CEANN_NAME)
    removed = td.loc[mask].copy()
    if removed.empty:
        raise RuntimeError(f"Expected {CEANN_NAME} in base audit TD output, but no row was found")

    td = td.loc[~mask].copy()
    if td["member_code"].astype(str).eq(CEANN_MEMBER_CODE).any() or td["member_name"].astype(str).eq(CEANN_NAME).any():
        raise RuntimeError(f"{CEANN_NAME} still present after TD review exclusion")

    td.to_csv(TD_PATH, index=False)
    print(f"Removed {len(removed)} Ceann Comhairle row(s) from TD review comparison; {before} -> {len(td)} rows")
    print(removed.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
