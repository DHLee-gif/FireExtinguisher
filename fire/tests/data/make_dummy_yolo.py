"""Tiny model shaped like an ultralytics YOLO export: (1,3,320,320) -> (1,5,100).
Every box: center (160,160), size 64x64, fire score 0.9. Used only by fire/tests."""
import sys
import numpy as np, onnx
from onnx import helper, TensorProto, numpy_helper
W = numpy_helper.from_array(np.zeros((5, 3, 1, 1), np.float32), "W")
B = numpy_helper.from_array(np.array([160, 160, 64, 64, 0.9], np.float32), "B")
shape = numpy_helper.from_array(np.array([1, 5, 100], np.int64), "shape")
conv = helper.make_node("Conv", ["images", "W", "B"], ["c"], strides=[32, 32], kernel_shape=[1, 1])
reshape = helper.make_node("Reshape", ["c", "shape"], ["output0"])
graph = helper.make_graph([conv, reshape], "dummy_yolo",
    [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 320, 320])],
    [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 5, 100])], [W, B, shape])
model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 12)])
model.ir_version = 7
onnx.checker.check_model(model)
onnx.save(model, sys.argv[1])
