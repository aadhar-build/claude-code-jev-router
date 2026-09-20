"""Arms. Every arm implements one function:

    evaluate(state: str, questions: dict, config: ArmConfig) -> Run

This is the project's primary test seam. A fake arm behind it lets the worker's
orchestration, interleaving, randomisation, retry and row-writing all be tested
with zero API spend and zero flakiness. Adding a fourth arm means adding one file.
"""
