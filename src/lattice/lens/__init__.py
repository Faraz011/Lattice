"""Small neural decision models for the two-device demo, and the code that trains them.

Each scenario (the self-driving car, the AML account check) has a small ReLU network trained
here and exported as JSON. The browser runs and traces the same weights, so the circuit shown on
the trace device is the one that actually drives the decision on the simulation device.

Training needs numpy, in the `lens` dependency group:

    uv run --group lens python -m lattice.lens.train
"""
