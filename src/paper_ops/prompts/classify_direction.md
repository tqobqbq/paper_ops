# Direction Classification Agent

Map the paper into exactly one controlled direction label.

The label should reflect the paper's primary intellectual center of gravity, not every topic it
mentions in passing.

Allowed labels:

- predictive_coding
- local_learning
- three_factor_learning
- ei_balance
- attractor_dynamics
- criticality_avalanches
- efficient_sparse_coding
- neuromodulation
- benchmark_baselines
- theory_reviews

Decision rules:

- Choose the single best label even if the paper spans multiple topics.
- Prefer mechanism over application domain.
- Prefer the paper's main technical contribution over a side experiment.
- Use `benchmark_baselines` for benchmark, evaluation, or engineering-heavy papers whose main value
  is comparison rather than a new mechanistic idea.
- Use `theory_reviews` for surveys, reviews, conceptual syntheses, or theory-heavy framing papers.

Output requirements:

- Return only the label, with no explanation.
