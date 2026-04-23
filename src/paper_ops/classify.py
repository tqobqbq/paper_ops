CONTROLLED_DIRECTIONS = {
    "predictive_coding": [
        "predictive coding",
        "prediction error",
        "difference predictive coding",
    ],
    "local_learning": ["local learning", "hebbian", "local plasticity"],
    "three_factor_learning": ["three-factor", "eligibility trace", "e-prop"],
    "ei_balance": ["ei balance", "excitatory inhibitory", "balanced network"],
    "attractor_dynamics": ["attractor", "persistent state", "hopfield"],
    "criticality_avalanches": ["criticality", "avalanche", "branching ratio"],
    "efficient_sparse_coding": [
        "sparse coding",
        "dictionary learning",
        "efficient coding",
    ],
    "neuromodulation": ["neuromodulation", "dopamine", "modulation"],
    "benchmark_baselines": ["benchmark", "baseline", "leaderboard"],
    "theory_reviews": ["review", "survey", "theory"],
}


def classify_direction(title: str, abstract: str, keywords: list[str]) -> str:
    haystack = " ".join([title, abstract, *keywords]).lower()
    for direction, triggers in CONTROLLED_DIRECTIONS.items():
        if any(trigger in haystack for trigger in triggers):
            return direction
    return "benchmark_baselines"
