#!/usr/bin/env python3
"""Native float atomic adds (dmsh_atomic.py float_atomics / uses_float_atomics, the translator's MetalFloatAtomics): SPIRV-Cross's atomic_uint add of a float's bits into a float result
becomes an atomic_float add on device memory, any other float result of an integer atomic fails the shader, and a module with OpAtomicFAddEXT is written at MSL 3.1. The translator's
side (RED.E.ADD.F32 to OpAtomicFAddEXT) is in test_dmsh_ampere_mem.py RedF32, which needs the built translator."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import dmsh_atomic  # noqa: E402

XC = ['--msl', '--msl-version', '20300', '--msl-argument-buffers', '--msl-texture-buffer-native', '--msl-pad-fragment-output']
SPIRV_CROSS = TOOLS / 'spirv_cross_bin/spirv-cross'


def module(*insts):
    """A SPIR-V module (header and the given instructions, each a list of words with the opcode first): enough for the opcode scan, not a valid shader"""
    words = [0x07230203, 0x00010300, 0, 100, 0]
    for op, *operands in insts:
        words += [(len(operands) + 1) << 16 | op, *operands]
    return struct.pack('<%dI' % len(words), *words)


# A compute shader with a storage buffer of uint words (as the translator declares them) and a float atomic add on word 5 through the uint element pointer, as Instructions.GenerateAtomicAddF32
# writes it for a storage buffer. Words of `spirv-as --target-env spv1.3` of the assembly in the comment of each part
def fadd_on_uint_buffer():
    w = [0x07230203, 0x00010300, 0, 30, 0]
    def i(op, *ops): w.extend([(len(ops) + 1) << 16 | op, *ops])
    def s(text):   # a literal string's words
        b = text.encode() + b'\0'; b += b'\0' * (-len(b) % 4)
        return struct.unpack('<%dI' % (len(b) // 4), b)
    i(17, 1)                          # OpCapability Shader
    i(17, 6033)                       # OpCapability AtomicFloat32AddEXT
    i(10, *s('SPV_EXT_shader_atomic_float_add'))
    i(14, 0, 1)                       # OpMemoryModel Logical GLSL450
    i(15, 5, 1, *s('main'))           # OpEntryPoint GLCompute %1 "main"
    i(16, 1, 17, 64, 1, 1)            # OpExecutionMode %1 LocalSize 64 1 1
    i(71, 6, 6, 4)                    # OpDecorate %6 ArrayStride 4
    i(72, 7, 0, 35, 0)                # OpMemberDecorate %7 0 Offset 0
    i(71, 7, 3)                       # OpDecorate %7 BufferBlock
    i(71, 9, 34, 0)                   # OpDecorate %9 DescriptorSet 0
    i(71, 9, 33, 3)                   # OpDecorate %9 Binding 3
    i(19, 2)                          # %2 = OpTypeVoid
    i(33, 3, 2)                       # %3 = OpTypeFunction %2
    i(21, 4, 32, 0)                   # %4 = OpTypeInt 32 0
    i(22, 5, 32)                      # %5 = OpTypeFloat 32
    i(29, 6, 4)                       # %6 = OpTypeRuntimeArray %4
    i(30, 7, 6)                       # %7 = OpTypeStruct %6
    i(32, 8, 2, 7)                    # %8 = OpTypePointer Uniform %7
    i(32, 10, 2, 4)                   # %10 = OpTypePointer Uniform %4
    i(59, 8, 9, 2)                    # %9 = OpVariable %8 Uniform
    i(43, 4, 11, 0)                   # %11 = OpConstant %4 0
    i(43, 4, 12, 1)                   # %12 = OpConstant %4 1
    i(43, 4, 13, 5)                   # %13 = OpConstant %4 5
    i(43, 5, 14, 0x3fc00000)          # %14 = OpConstant %5 1.5
    i(54, 2, 1, 0, 3)                 # %1 = OpFunction %2 None %3
    i(248, 15)                        # %15 = OpLabel
    i(65, 10, 16, 9, 11, 13)          # %16 = OpAccessChain %10 %9 %11 %13
    i(6035, 5, 17, 16, 12, 11, 14)    # %17 = OpAtomicFAddEXT %5 %16 %12 %11 %14
    i(124, 4, 18, 17)                 # %18 = OpBitcast %4 %17
    i(62, 16, 18)                     # OpStore %16 %18
    i(253)                            # OpReturn
    i(56)                             # OpFunctionEnd
    return struct.pack('<%dI' % len(w), *w)


class Detection(unittest.TestCase):
    def scan(self, data):
        with tempfile.NamedTemporaryFile(suffix='.spv') as f:
            f.write(data); f.flush()
            return dmsh_atomic.uses_float_atomics(f.name), dmsh_atomic.cross_args(XC, f.name)

    def test_a_float_add_raises_the_msl_version(self):
        uses, args = self.scan(module([6035, 5, 17, 16, 12, 11, 14]))
        self.assertTrue(uses)
        self.assertEqual(args[args.index('--msl-version') + 1], dmsh_atomic.MSL_VERSION_ATOMICS)

    def test_an_integer_add_keeps_it(self):
        uses, args = self.scan(module([234, 4, 17, 16, 12, 11, 14]))   # OpAtomicIAdd
        self.assertFalse(uses)
        self.assertEqual(args, XC)

    def test_the_words_bytes_inside_an_operand_are_not_an_instruction(self):   # the first word's bytes as a constant's value, not as an opcode
        uses, _ = self.scan(module([43, 4, 11, 7 << 16 | 6035]))
        self.assertFalse(uses)


class Rewrite(unittest.TestCase):
    def test_storage_buffer_add(self):
        src = '    float _22 = atomic_fetch_add_explicit((device atomic_uint*)&(*spvDescriptorSet0.cp_s0)._m0[int(_813)], as_type<uint>(_775), memory_order_relaxed);\n'
        self.assertEqual(dmsh_atomic.check_msl(src),
                         '    float _22 = atomic_fetch_add_explicit((device atomic_float*)&(*spvDescriptorSet0.cp_s0)._m0[int(_813)], _775, memory_order_relaxed);\n')

    def test_hoisted_result(self):
        src = '    float _24;\n    if (c)\n    {\n        _24 = atomic_fetch_add_explicit((device atomic_uint*)&b._m0[i], as_type<uint>(fma(a, as_type<float>(x), 1.0)), memory_order_relaxed);\n    }\n'
        self.assertIn('_24 = atomic_fetch_add_explicit((device atomic_float*)&b._m0[i], fma(a, as_type<float>(x), 1.0), memory_order_relaxed);', dmsh_atomic.check_msl(src))

    def test_a_value_not_in_a_cast_is_read_as_a_float(self):
        src = '    float _27 = atomic_fetch_add_explicit((device atomic_uint*)&b._m0[5u], _9, memory_order_relaxed);\n'
        self.assertIn('(device atomic_float*)&b._m0[5u], as_type<float>(_9), memory_order_relaxed)', dmsh_atomic.check_msl(src))

    def test_integer_atomics_stay(self):
        src = ('    uint _26 = atomic_fetch_add_explicit((device atomic_uint*)&b._m0[5u], as_type<uint>(_24), memory_order_relaxed);\n'
               '    uint _30;\n    _30 = atomic_fetch_add_explicit((device atomic_uint*)&b._m0[6u], 0u, memory_order_relaxed);\n'
               '    float _31 = as_type<float>(_30);\n')
        self.assertEqual(dmsh_atomic.check_msl(src), src)

    def test_threadgroup_float_add_fails(self):   # Metal has no atomic_float add on threadgroup memory
        with self.assertRaises(ValueError):
            dmsh_atomic.check_msl('    float _24 = atomic_fetch_add_explicit((threadgroup atomic_uint*)&_15[2u], as_type<uint>(1.5), memory_order_relaxed);\n')

    def test_float_result_of_another_integer_atomic_fails(self):
        with self.assertRaises(ValueError):
            dmsh_atomic.check_msl('    float _24 = atomic_exchange_explicit((device atomic_uint*)&b._m0[2u], as_type<uint>(1.5), memory_order_relaxed);\n')


@unittest.skipUnless(SPIRV_CROSS.exists(), 'the in-repo spirv-cross')
class ThroughSpirvCross(unittest.TestCase):
    def test_storage_buffer_add_is_native(self):
        with tempfile.TemporaryDirectory(prefix='float_atomic_') as d:
            spv = Path(d) / 'k.spv'; spv.write_bytes(fadd_on_uint_buffer())
            r = subprocess.run([str(SPIRV_CROSS), *dmsh_atomic.cross_args(XC, spv), str(spv)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            msl = dmsh_atomic.check_msl(r.stdout)
        self.assertRegex(msl, r'float _\d+ = atomic_fetch_add_explicit\(\(device atomic_float\*\)&\(\*spvDescriptorSet0\.\w+\)\._m0\[5u\], 1\.5, memory_order_relaxed\);')
        self.assertNotRegex(msl, r'float _\d+ = atomic_\w+\(\(device atomic_uint')


if __name__ == '__main__':
    unittest.main()
