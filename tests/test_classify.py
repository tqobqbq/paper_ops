from paper_ops.classify import classify_direction


def test_classify_direction_maps_predictive_coding_terms():
    direction = classify_direction(
        title="Difference Predictive Coding for Training Spiking Neural Networks",
        abstract="A predictive coding method for training SNNs with local errors.",
        keywords=["predictive coding", "spiking neural network"],
    )
    assert direction == "predictive_coding"


def test_classify_direction_maps_ei_balance_terms():
    direction = classify_direction(
        title="Balanced networks for efficient stimulus representations",
        abstract="We study excitatory inhibitory balance and sparse coding.",
        keywords=["EI balance", "sparse coding"],
    )
    assert direction == "ei_balance"


def test_classify_direction_falls_back_to_benchmark_baselines():
    direction = classify_direction(
        title="A new approach for robust visual recognition",
        abstract="We present a method with no explicit controlled-direction keywords.",
        keywords=["vision", "classification"],
    )
    assert direction == "benchmark_baselines"
