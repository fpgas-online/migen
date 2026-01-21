import operator
import collections.abc
import inspect
from functools import wraps

from migen.fhdl.structure import *
from migen.fhdl.structure import (_Value, _Statement,
                                  _Operator, _Slice, _Part, _ArrayProxy,
                                  _Assign, _Fragment)
from migen.fhdl.bitcontainer import value_bits_sign
from migen.fhdl.tools import (list_targets, list_signals,
                              insert_resets, lower_specials)
from migen.fhdl.simplify import MemoryToArray
from migen.fhdl.specials import _MemoryLocation
from migen.fhdl.module import Module
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.sim.vcd import VCDWriter, DummyVCDWriter


class ClockState:
    def __init__(self, high, half_period, time_before_trans):
        self.high = high
        self.half_period = half_period
        self.time_before_trans = time_before_trans


class TimeManager:
    def __init__(self, description):
        self.clocks = collections.OrderedDict()

        for k, period_phase in description.items():
            if isinstance(period_phase, tuple):
                period, phase = period_phase
            else:
                period = period_phase
                phase = 0
            half_period = period//2
            if phase >= half_period:
                phase -= half_period
                high = True
            else:
                high = False
            self.clocks[k] = ClockState(high, half_period, half_period - phase)

    def tick(self):
        rising = set()
        falling = set()
        dt = min(cs.time_before_trans for cs in self.clocks.values())
        for k, cs in self.clocks.items():
            if cs.time_before_trans == dt:
                cs.high = not cs.high
                if cs.high:
                    rising.add(k)
                else:
                    falling.add(k)
            cs.time_before_trans -= dt
            if not cs.time_before_trans:
                cs.time_before_trans += cs.half_period
        return dt, rising, falling


str2op = {
    "~": operator.invert,
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,

    ">>>": operator.rshift,
    "<<<": operator.lshift,

    "&": operator.and_,
    "^": operator.xor,
    "|": operator.or_,

    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
}


def _truncate(value, nbits, signed):
    value = value & ((1<<nbits) - 1)
    if signed and (value & (1 << (nbits - 1))):
        value -= (1 << nbits)
    return value


class Evaluator:
    def __init__(self, clock_domains, replaced_memories):
        self.clock_domains = clock_domains
        self.replaced_memories = replaced_memories
        self.signal_values = [None] * DUID.get_max_duid() # index by duid
        self.modifications = dict() # duid -> int

    def commit_changed(self):
        changed = False
        sv = self.signal_values
        mods = self.modifications
        for duid, v in mods.items():
            old = sv[duid]
            if old != v:
                sv[duid] = v
                changed = True
        mods.clear()
        return changed

    def commit_set(self):
        r = set()
        sv = self.signal_values
        mods = self.modifications
        for duid, v in mods.items():
            old = sv[duid]
            if old != v:
                sv[duid] = v
                r.add(duid)
        mods.clear()
        return r

    def eval(self, node, postcommit=False):
        t = type(node)
        while True:
            if t is Constant:
                return node.value
            elif t is Signal:
                duid = node.duid
                if postcommit:
                    v = self.modifications.get(duid)
                    if v is not None:
                        return v
                v = self.signal_values[duid]
                return node.reset.value if v is None else v
            elif t is _Operator:
                op = node.op
                ops = node.operands
                a = self.eval(ops[0], postcommit)
                # all ops with one param:
                if op == "~": return ~a
                if op == "-" and len(ops) == 1: return -a
                if op == "m":
                    return self.eval(ops[1], postcommit) if a else self.eval(ops[2], postcommit)
                # all ops with two params:
                b = self.eval(ops[1], postcommit)
                if op == "+":    return a + b
                if op == "-":    return a - b
                if op == "*":    return a * b
                if op == ">>>":  return a >> b
                if op == "<<<":  return a << b
                if op == "&":    return a & b
                if op == "^":    return a ^ b
                if op == "|":    return a | b
                if op == "<":    return a < b
                if op == "<=":   return a <= b
                if op == "==":   return a == b
                if op == "!=":   return a != b
                if op == ">":    return a > b
                if op == ">=":   return a >= b
                raise NotImplementedError(op)
            elif t is _Slice:
                v = self.eval(node.value, postcommit)
                w = node.stop - node.start
                return (v >> node.start) & ((1 << w) - 1)
            elif t is _Part:
                v = self.eval(node.value, postcommit)
                offset = self.eval(node.offset, postcommit)
                return (v >> offset) & ((1 << node.width) - 1)
            elif t is Cat:
                shift = 0
                r = 0
                for element in node.l:
                    nbits = len(element)
                    # make value always positive
                    r |= (self.eval(element, postcommit) & ((1<<nbits)-1)) << shift
                    shift += nbits
                return r
            elif t is Replicate:
                nbits = len(node.v)
                v = self.eval(node.v, postcommit) & ((1<<nbits) - 1)
                return sum(v << i*nbits for i in range(node.n))
            elif t is _ArrayProxy:
                idx = min(len(node.choices) - 1, self.eval(node.key, postcommit))
                return self.eval(node.choices[idx], postcommit)
            elif t is _MemoryLocation:
                array = self.replaced_memories[node.memory]
                return self.eval(array[self.eval(node.index, postcommit)], postcommit)
            elif t is ClockSignal:
                return self.eval(self.clock_domains[node.cd].clk, postcommit)
            elif t is ResetSignal:
                rst = self.clock_domains[node.cd].rst
                if rst is None:
                    if node.allow_reset_less:
                        return 0
                    else:
                        raise ValueError("Attempted to get reset signal of resetless"
                                        " domain '{}'".format(node.cd))
                else:
                    return self.eval(rst, postcommit)
            else:
                if isinstance(node, Constant): t = Constant
                elif isinstance(node, Signal): t = Signal
                elif isinstance(node, _Operator): t = _Operator
                elif isinstance(node, _Slice): t = _Slice
                elif isinstance(node, _Part): t = _Part
                elif isinstance(node, Cat): t = Cat
                elif isinstance(node, Replicate): t = Replicate
                elif isinstance(node, _ArrayProxy): t = _ArrayProxy
                elif isinstance(node, _MemoryLocation): t = _MemoryLocation
                elif isinstance(node, ClockSignal): t = ClockSignal
                elif isinstance(node, ResetSignal): t = ResetSignal
                else:
                    raise NotImplementedError(node)

    def assign(self, node, value):
        t = type(node)
        while True:
            if t is Signal:
                assert not node.variable
                # hot path: _truncate inlined:
                duid = node.duid
                full = 1 << node.nbits
                v = value & (full - 1)
                if node.signed and (v & (full >> 1)):
                    v -= full
                self.modifications[duid] = v
                return
            elif t is Cat:
                for element in node.l:
                    nbits = len(element)
                    self.assign(element, value & ((1<<nbits)-1))
                    value >>= nbits
                return
            elif t is _Slice:
                full_value = self.eval(node.value, True)
                # clear bits assigned to by the slice
                full_value &= ~(((1 << (node.stop - node.start)) - 1) << node.start)
                # set them to the new value
                value &= (1 << (node.stop - node.start)) - 1
                full_value |= value << node.start
                self.assign(node.value, full_value)
                return
            elif t is _Part:
                full_value = self.eval(node.value, True)
                offset = self.eval(node.offset, True)
                start = offset
                stop = offset + node.width
                full_value &= ~((2**stop-1) - (2**start-1))
                value &= 2**(stop - start)-1
                full_value |= value << start
                self.assign(node.value, full_value)
                return
            elif t is _ArrayProxy:
                idx = min(len(node.choices) - 1, self.eval(node.key))
                self.assign(node.choices[idx], value)
                return
            elif t is _MemoryLocation:
                array = self.replaced_memories[node.memory]
                self.assign(array[self.eval(node.index)], value)
                return
            else: # slow path for subclasses:
                if isinstance(node, Signal): t = Signal
                elif isinstance(node, Cat): t = Cat
                elif isinstance(node, _Slice): t = _Slice
                elif isinstance(node, _Part): t = _Part
                elif isinstance(node, _ArrayProxy): t = _ArrayProxy
                elif isinstance(node, _MemoryLocation): t = _MemoryLocation
                else:
                    raise NotImplementedError(node)


    def execute(self, statements):
        for s in statements:
            t = type(s)
            if t is _Assign:
                self.assign(s.l, self.eval(s.r))
            elif t is If:
                if self.eval(s.cond) & ((1 << len(s.cond)) - 1):
                    self.execute(s.t)
                else:
                    self.execute(s.f)
            elif t is Case:
                nbits, signed = value_bits_sign(s.test)
                test = _truncate(self.eval(s.test), nbits, signed)
                found = False
                for k, v in s.cases.items():
                    if isinstance(k, Constant) and k.value == test:
                        self.execute(v)
                        found = True
                        break
                if not found and "default" in s.cases:
                    self.execute(s.cases["default"])
            elif t is tuple:
                self.execute(s)
            elif isinstance(s, Display):
                args = []
                for arg in s.args:
                    assert isinstance(arg, _Value)
                    v = self.signal_values[arg.duid]
                    args.append(arg.reset.value if v is None else v)
                print(s.s %(*args,))
            # slow path for subclasses of _Assign, If, Case
            elif isinstance(s, _Assign):
                self.assign(s.l, self.eval(s.r))
            elif isinstance(s, If):
                if self.eval(s.cond) & ((1 << len(s.cond)) - 1):
                    self.execute(s.t)
                else:
                    self.execute(s.f)
            elif isinstance(s, Case):
                nbits, signed = value_bits_sign(s.test)
                test = _truncate(self.eval(s.test), nbits, signed)
                found = False
                for k, v in s.cases.items():
                    if isinstance(k, Constant) and k.value == test:
                        self.execute(v)
                        found = True
                        break
                if not found and "default" in s.cases:
                    self.execute(s.cases["default"])
            elif isinstance(s, collections.abc.Iterable):
                self.execute(s)
            else:
                raise NotImplementedError


class DummyAsyncResetSynchronizerImpl(Module):
    def __init__(self, cd, async_reset):
        # TODO: asynchronous set
        # This naive implementation has a minimum reset pulse
        # width requirement of one clock period in cd.
        self.comb += cd.rst.eq(async_reset)


class DummyAsyncResetSynchronizer:
    @staticmethod
    def lower(dr):
        return DummyAsyncResetSynchronizerImpl(dr.cd, dr.async_reset)


# TODO: instances via Iverilog/VPI
class Simulator:
    def __init__(self, fragment_or_module, generators, clocks={"sys": 10}, vcd_name=None,
                 special_overrides={}):
        if isinstance(fragment_or_module, _Fragment):
            self.fragment = fragment_or_module
        else:
            self.fragment = fragment_or_module.get_fragment()

        mta = MemoryToArray()
        mta.transform_fragment(None, self.fragment)

        overrides = {AsyncResetSynchronizer: DummyAsyncResetSynchronizer}
        overrides.update(special_overrides)
        f, lowered = lower_specials(overrides, self.fragment)
        if self.fragment.specials:
            raise ValueError("Could not lower all specials", self.fragment.specials)

        if not isinstance(generators, dict):
            generators = {"sys": generators}
        self.generators = dict()
        self.passive_generators = set()
        for k, v in generators.items():
            if (isinstance(v, collections.abc.Iterable)
                    and not inspect.isgenerator(v)):
                self.generators[k] = list(v)
            else:
                self.generators[k] = [v]

        clocks = collections.OrderedDict(sorted(clocks.items(),
                                                key=operator.itemgetter(0)))
        self.time = TimeManager(clocks)
        for clock in clocks.keys():
            if clock not in self.fragment.clock_domains:
                cd = ClockDomain(name=clock, reset_less=True)
                cd.clk.reset = C(self.time.clocks[clock].high)
                self.fragment.clock_domains.append(cd)

        insert_resets(self.fragment)
        # comb signals return to their reset value if nothing assigns them
        self.fragment.comb[0:0] = [s.eq(s.reset)
                                   for s in list_targets(self.fragment.comb)]
        self.evaluator = Evaluator(self.fragment.clock_domains,
                                   mta.replacements)

        if vcd_name is None:
            self.vcd = DummyVCDWriter()
            self._duid2sig = None
        else:
            self.vcd = VCDWriter(vcd_name, module_name=type(fragment_or_module).__name__)

            signals = list_signals(self.fragment)
            for cd in self.fragment.clock_domains:
                signals.add(cd.clk)
                if cd.rst is not None:
                    signals.add(cd.rst)
            for memory_array in mta.replacements.values():
                signals |= set(memory_array)
            duid2sig = [None] * DUID.get_max_duid()
            for signal in sorted(signals, key=lambda x: x.duid):
                self.vcd.set(signal, signal.reset.value)
                duid2sig[signal.duid] = signal
            self._duid2sig = duid2sig
    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        self.vcd.close()

    def _commit_and_comb_propagate(self):
        # TODO: optimize
        if type(self.vcd) is DummyVCDWriter:
            # no-trace fast path
            modified = self.evaluator.commit_changed()
            while modified:
                self.evaluator.execute(self.fragment.comb)
                modified = self.evaluator.commit_changed()
            return
        all_modified = set() # duid
        modified = self.evaluator.commit_set()
        all_modified |= modified
        while modified:
            self.evaluator.execute(self.fragment.comb)
            modified = self.evaluator.commit_set()
            all_modified |= modified
        for duid in all_modified:
            signal = self._duid2sig[duid]
            self.vcd.set(signal, self.evaluator.signal_values[duid])

    def _evalexec_nested_lists(self, x):
        if isinstance(x, list):
            return [self._evalexec_nested_lists(e) for e in x]
        elif isinstance(x, _Value):
            return self.evaluator.eval(x)
        elif isinstance(x, _Statement):
            # need to update signal list if vcd is on because
            # generators might create new signals
            if self._duid2sig is not None:
                for s in list_signals(x):
                    if self._duid2sig[s.duid] is None:
                        self._duid2sig[s.duid] = s
            self.evaluator.execute([x])
            return None
        else:
            raise ValueError("Invalid simulator exec/eval request", x)

    def _process_generators(self, cd):
        exhausted = []
        for generator in self.generators[cd]:
            reply = None
            while True:
                try:
                    request = generator.send(reply)
                    if request is None:
                        break  # next cycle
                    elif isinstance(request, str):
                        if request == "passive":
                            self.passive_generators.add(generator)
                        elif request == "active":
                            self.passive_generators.discard(generator)
                        else:
                            raise ValueError("Unknown simulator command: '{}'"
                                             .format(request))
                    else:
                        try:
                            reply = self._evalexec_nested_lists(request)
                        except Exception as e:
                            tb = inspect.getframeinfo(generator.gi_frame)
                            print("While evaluating the following generator, an error occurred:")
                            print("  File {}, line {}, in {}".format(tb.filename, tb.lineno, tb.function))
                            for c in tb.code_context:
                                print("    ", c.lstrip())
                            raise

                except StopIteration:
                    exhausted.append(generator)
                    break
        for generator in exhausted:
            self.generators[cd].remove(generator)

    def _continue_simulation(self):
        for cd_generators in self.generators.values():
            if set(cd_generators) - self.passive_generators:
                return True
        return False

    def run(self):
        self.evaluator.execute(self.fragment.comb)
        self._commit_and_comb_propagate()

        while True:
            dt, rising, falling = self.time.tick()
            self.vcd.delay(dt)
            for cd in rising:
                self.evaluator.assign(self.fragment.clock_domains[cd].clk, 1)
                if cd in self.fragment.sync:
                    self.evaluator.execute(self.fragment.sync[cd])
                if cd in self.generators:
                    self._process_generators(cd)
            for cd in falling:
                self.evaluator.assign(self.fragment.clock_domains[cd].clk, 0)
            self._commit_and_comb_propagate()

            if not self._continue_simulation():
                break


def run_simulation(*args, **kwargs):
    with Simulator(*args, **kwargs) as s:
        s.run()


def passive(generator):
    @wraps(generator)
    def wrapper(*args, **kwargs):
        yield "passive"
        yield from generator(*args, **kwargs)
    return wrapper
