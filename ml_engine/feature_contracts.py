"""Keep historical explanations bound to their original model's inputs."""

from . import features, simulated_features


def get_contract(schema):
    for contract in (features, simulated_features):
        if schema == contract.SCHEMA_VERSION:
            return contract
    raise ValueError("Unsupported model feature schema")
