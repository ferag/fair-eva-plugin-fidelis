"""A light FAIR EVA base stub keeps mapper unit tests independent of core I/O."""

from __future__ import annotations

import ast
import sys
import types


class EvaluatorBase:
    def __init__(self, item_id, api_endpoint, lang, config, name, **kwargs):
        self.item_id = item_id
        self.api_endpoint = api_endpoint or config.get("Generic", "endpoint")
        self.lang = lang
        self.config = config
        self.name = name
        section = config[name]
        for key in (
            "supported_data_formats",
            "terms_access_protocols",
            "metadata_standard",
        ):
            setattr(self, key, ast.literal_eval(section[key]))


api_module = types.ModuleType("fair_eva.api")
evaluator_module = types.ModuleType("fair_eva.api.evaluator")
evaluator_module.EvaluatorBase = EvaluatorBase
api_module.evaluator = evaluator_module
sys.modules.setdefault("fair_eva.api", api_module)
sys.modules.setdefault("fair_eva.api.evaluator", evaluator_module)
