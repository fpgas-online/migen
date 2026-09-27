#!/bin/sh
# Install test (docs/packaging.md, "Builds"): run after the built python3-migen
# is installed into a clean debian:<suite> container. python3-migen ships no
# command, so this imports it, elaborates a small design to Verilog and runs it
# in migen's own simulator: the paths LiteX uses, outside the source tree.
set -eu
cd /
python3 - <<'PY'
import importlib.metadata
import migen
from migen import Module, Signal, run_simulation
from migen.fhdl.verilog import convert

class Counter(Module):
    def __init__(self):
        self.count = Signal(4)
        self.sync += self.count.eq(self.count + 1)

assert migen.__file__.startswith("/usr/lib/python3/dist-packages/"), migen.__file__
v = str(convert(Counter()))
assert "always @(posedge sys_clk)" in v, v

dut = Counter()
seen = []
def bench():
    for _ in range(5):
        seen.append((yield dut.count))
        yield
run_simulation(dut, bench())
assert seen == [0, 1, 2, 3, 4], seen
print("python3-migen", importlib.metadata.version("migen"), "from", migen.__file__, "OK")
PY
