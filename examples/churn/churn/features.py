"""Feature pipeline: raw CSV row -> numeric feature vector. The model only sees what is encoded here."""

NUMERIC = ["tenure_months", "monthly_charges"]
CONTRACTS = ["month", "year", "two_year"]
FEATURE_NAMES = NUMERIC + ["contract"]


def encode(row: dict) -> list:
    numeric = [float(row[c]) for c in NUMERIC]
    return numeric + [row["contract"]]
