"""Image atomics run natively on the Metal texture (MSL 3.1 texture atomics).

SPIRV-Cross below MSL 3.1 emulates an image atomic with a raw device pointer
beside the texture (<image>_atomic), indexed by the bound texture's width: a
block-linear image is a deswizzled Metal copy whose pool memory has another
layout, so those atomics went to a scratch buffer that nothing read, and a 3D
image did not compile at all (an int3 subscript). Native texture atomics act on
the texture every other access of the image uses, for buffer, 2D, 2D-array and
3D images. The translator still guards each coordinate (IGN bounds) before the
atomic.

Only shaders with image atomics (OpImageTexelPointer) are written at MSL 3.1:
every other shader keeps its MSL 2.3 source byte for byte, so its library comes
from the MSL-keyed compile cache. The emulation must never come back silently:
check_msl fails the shader when SPIRV-Cross writes the pointer form anyway.

Float atomic adds (RED / ATOMG .ADD.F32, the translator's MetalFloatAtomics) are native
atomic_float adds on device memory (MSL 3.0; Apple7 and later; Metal has none on
threadgroup memory, where the translator keeps its compare-and-swap loop). On raw global memory the SPIR-V is a
proper OpAtomicFAddEXT on a float pointer. On a storage buffer, whose words are uint,
the op takes the uint element pointer (logical pointers cannot be cast), and SPIRV-Cross
writes the add on an atomic_uint with the value's bits into a float result:
float_atomics turns each of those into the atomic_float add, and fails the shader on
any float result of an integer atomic left. Modules with the op are written at MSL 3.1 too.
"""
import re
import struct

MSL_VERSION = '20300'
MSL_VERSION_ATOMICS = '30100'
OP_IMAGE_TEXEL_POINTER = 60
OP_ATOMIC_FADD_EXT = 6035   # OpAtomicFAddEXT (SPV_EXT_shader_atomic_float_add)


def _has_op(spv, op, first_word):
    """Whether the SPIR-V module (path) has an instruction with opcode op. first_word: the instruction's first word as bytes (its length is fixed), nowhere in most modules, which are
    then answered without walking their instructions in Python"""
    with open(spv, 'rb') as f:
        data = f.read()
    if len(data) < 20 or data[:4] != b'\x03\x02\x23\x07':
        raise ValueError('not a SPIR-V module: ' + str(spv))
    if first_word not in data:
        return False
    words = struct.unpack('<%dI' % (len(data) // 4), data[:len(data) // 4 * 4])
    i = 5
    while i < len(words):
        n, o = words[i] >> 16, words[i] & 0xffff
        if o == op:
            return True
        if n == 0:
            raise ValueError('malformed SPIR-V instruction in ' + str(spv))
        i += n
    return False


def uses_image_atomics(spv):
    """Whether the SPIR-V module (path) has an image texel pointer, the operand of every image atomic"""
    return _has_op(spv, OP_IMAGE_TEXEL_POINTER, b'\x3c\x00\x06\x00')   # always 6 words long


def uses_float_atomics(spv):
    """Whether the SPIR-V module (path) has a float atomic add"""
    return _has_op(spv, OP_ATOMIC_FADD_EXT, struct.pack('<I', 7 << 16 | OP_ATOMIC_FADD_EXT))   # always 7 words long


def cross_args(xc, spv):
    """spirv-cross arguments for this module: xc with its --msl-version raised to 3.1 when the module has image atomics or float atomic adds (atomic_float needs MSL 3.0)"""
    if not uses_image_atomics(spv) and not uses_float_atomics(spv):
        return list(xc)
    args = list(xc)
    args[args.index('--msl-version') + 1] = MSL_VERSION_ATOMICS
    return args


_EMULATED = re.compile(r'\bspvImage2DAtomicCoord\b|device\s+atomic_u?int\s*\*\s*\w+_atomic\b')


def check_msl(source):
    """Fail closed on SPIRV-Cross's pointer emulation of image atomics; return the source with its float atomic adds native (float_atomics)"""
    if 'tomic' in source and _EMULATED.search(source):   # (both alternatives hold the word; the pattern alone tries every character of the source)
        raise ValueError('image atomics emulated through a raw pointer; they must be native texture atomics (MSL 3.1)')
    return float_atomics(source)


# An integer atomic's result: <name> = atomic_fetch_<op>_explicit((<space> atomic_uint*)..., declared with its type on that line or, when SPIRV-Cross hoists it, on a line of its own
_INT_ATOMIC = re.compile(r'^([ \t]*)(?:(\w+) )?(\w+) = (atomic_\w+_explicit)\(\((device|threadgroup) atomic_u?int\*\)', re.M)


def _call_args(source, i):
    """The top-level arguments of the call whose '(' is at source[i], and the index past its ')'"""
    depth, args, start, j = 0, [], i + 1, i
    while True:
        ch = source[j]
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
            if depth == 0:
                args.append(source[start:j].strip())
                return args, j + 1
        elif ch == ',' and depth == 1:
            args.append(source[start:j].strip())
            start = j + 1
        j += 1


def _float_value(value):
    """The add's value as a float: the operand of SPIRV-Cross's as_type<uint>(...) / as_type<int>(...) around it, else the value's bits as a float"""
    for cast in ('as_type<uint>(', 'as_type<int>('):
        if value.startswith(cast):
            args, end = _call_args(value, len(cast) - 1)
            if end == len(value) and len(args) == 1:
                return args[0]
    return 'as_type<float>(%s)' % value


def float_atomics(source):
    """The translator's float atomic adds on a storage buffer (see the module's docstring) as native atomic_float adds: each atomic_fetch_add_explicit on an atomic_uint whose result is a
    float. ValueError on any other integer atomic with a float result, a form this does not know"""
    if 'atomic_' not in source or 'float' not in source:
        return source
    out, at = [], 0
    for m in _INT_ATOMIC.finditer(source):
        decl, name, fn = m.group(2), m.group(3), m.group(4)
        if decl is None:   # hoisted: its type is on its declaration
            d = re.search(r'^[ \t]*(\w+) %s;' % re.escape(name), source, re.M)
            decl = d.group(1) if d else None
        if decl != 'float':
            continue
        if fn != 'atomic_fetch_add_explicit':
            raise ValueError(f'float result of an integer {fn}: {source[m.start():m.start() + 160].strip()}')
        if m.group(5) != 'device':   # Metal has atomic_float adds on device memory only (the translator keeps shared memory's loop)
            raise ValueError('float atomic add on threadgroup memory: ' + source[m.start():m.start() + 160].strip())
        args, end = _call_args(source, m.end(4))
        if len(args) != 3 or not args[0].startswith('(device atomic_'):
            raise ValueError('float atomic add of an unknown form: ' + source[m.start():end].strip()[:160])
        addr = '(device atomic_float*)' + args[0][args[0].index(')') + 1:]
        out += [source[at:m.end(4)], '(%s, %s, %s)' % (addr, _float_value(args[1]), args[2])]
        at = end
    out.append(source[at:])
    return ''.join(out)
