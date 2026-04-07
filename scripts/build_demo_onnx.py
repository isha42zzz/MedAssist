from __future__ import annotations

from pathlib import Path

import onnx
from onnx import TensorProto, helper, numpy_helper
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/cardio-risk-v1.onnx"


def build_demo_model(output_path: Path) -> None:
    weights = np.asarray(
        [[0.02], [0.15], [0.30], [0.01], [0.005], [0.20], [-0.01], [0.35], [0.50]],
        dtype=np.float32,
    )
    bias = np.asarray([-6.0], dtype=np.float32)

    input_tensor = helper.make_tensor_value_info("features", TensorProto.FLOAT, [None, 9])
    output_tensor = helper.make_tensor_value_info("risk_score", TensorProto.FLOAT, [None, 1])

    weights_initializer = numpy_helper.from_array(weights, name="weights")
    bias_initializer = numpy_helper.from_array(bias, name="bias")

    nodes = [
        helper.make_node("MatMul", ["features", "weights"], ["matmul_out"]),
        helper.make_node("Add", ["matmul_out", "bias"], ["logits"]),
        helper.make_node("Sigmoid", ["logits"], ["risk_score"]),
    ]

    graph = helper.make_graph(
        nodes,
        "cardio-risk-v1",
        [input_tensor],
        [output_tensor],
        initializer=[weights_initializer, bias_initializer],
    )
    model = helper.make_model(
        graph,
        producer_name="medassist",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    onnx.checker.check_model(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, output_path)


def main() -> None:
    build_demo_model(MODEL_PATH)
    print(f"Wrote {MODEL_PATH}")
