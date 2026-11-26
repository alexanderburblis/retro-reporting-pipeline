"""Check the Foundry transforms without a Foundry environment.

A minimal stand-in for transforms.api records each decorated function and its
Input/Output paths. The test then executes the transforms in dependency order on
the locally generated data and compares the outputs with the local pipeline.
"""
import importlib
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FOUNDRY_SRC = ROOT / "foundry" / "transforms-python" / "src"


class _Spec:
    def __init__(self, path):
        self.path = path


class _In:
    def __init__(self, df):
        self._df = df

    def pandas(self):
        return self._df


class _Out:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def write_table(self, df):
        self.store[self.path] = df


def _install_stub(registry):
    api = types.ModuleType("transforms.api")
    api.Input = _Spec
    api.Output = _Spec

    def transform_pandas(output, **inputs):
        def deco(fn):
            registry.append(("pandas", fn, {"__out__": output, **inputs}))
            return fn
        return deco

    class _T:
        @staticmethod
        def using(**specs):
            def deco(fn):
                registry.append(("multi", fn, specs))
                return fn
            return deco

    api.transform_pandas = transform_pandas
    api.transform = _T()
    pkg = types.ModuleType("transforms")
    pkg.api = api
    sys.modules["transforms"], sys.modules["transforms.api"] = pkg, api


def test_core_copies_match_source():
    for name in ["validate.py", "report.py"]:
        a = (ROOT / "src" / "retro_pipeline" / name).read_text()
        b = (FOUNDRY_SRC / "retro_pipeline" / "core" / name).read_text()
        assert a == b, f"{name} in foundry/ is out of sync with src/"


def test_foundry_transforms_reproduce_local_results(tmp_path):
    from retro_pipeline import pipeline

    local = pipeline.run(tmp_path)
    raw_dir = tmp_path / "data" / "raw"

    registry = []
    _install_stub(registry)
    saved = {k: v for k, v in sys.modules.items() if k == "retro_pipeline" or k.startswith("retro_pipeline.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(FOUNDRY_SRC))
    try:
        paths = importlib.import_module("retro_pipeline.datasets.paths")
        importlib.import_module("retro_pipeline.datasets.transforms")
        store = {f"{paths.RAW}/{p.stem}": pd.read_csv(p) for p in raw_dir.glob("*.csv")}

        pending = list(registry)
        while pending:
            progressed = False
            for item in list(pending):
                kind, fn, specs = item
                ins = {k: v for k, v in specs.items() if k != "__out__" and isinstance(v, _Spec)
                       and not (kind == "multi" and k.endswith("_out"))}
                if not all(s.path in store for s in ins.values()):
                    continue
                if kind == "pandas":
                    store[specs["__out__"].path] = fn(**{k: store[s.path] for k, s in ins.items()})
                else:
                    outs = {k: _Out(store, s.path) for k, s in specs.items() if k.endswith("_out")}
                    fn(**outs, **{k: _In(store[s.path]) for k, s in ins.items()})
                pending.remove(item)
                progressed = True
            assert progressed, "a transform has an input that nothing produces"

        f_res = store[f"{paths.ONTOLOGY}/quarterly_contract_results"]
        l_res = local["reporting/quarterly_contract_results"]
        assert len(registry) == 10
        assert abs(f_res["net_retro_result_usd"].sum() - l_res["net_retro_result_usd"].sum()) < 0.05
        assert len(store[f"{paths.ONTOLOGY}/validation_issues"]) == len(local["clean/validation_issues"])
    finally:
        sys.path.remove(str(FOUNDRY_SRC))
        for k in [k for k in sys.modules if k == "retro_pipeline" or k.startswith("retro_pipeline.")]:
            del sys.modules[k]
        sys.modules.update(saved)
        for k in ["transforms", "transforms.api"]:
            sys.modules.pop(k, None)
