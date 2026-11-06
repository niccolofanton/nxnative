#!/usr/bin/env python3
# Translation chain version of the B shader library: one version for every game, which the host is compiled with (dm/gfx/nvn/dmsh_chain.h). The build result must be determined by source alone.
# Chain version V = first 12 digits of the sha256 of the contents of the following in-repo files + the translation options: this script, dmsh_build.py, dmsh_fetch.py (readable-tile version), dmsh_vin.py (shadow vertex inputs), dmsh_pull.py and dmsh_pull.metal (pulling vertex inputs),
# dmsh_geometry.py, dmsh_facts.py, the library ABI dm/gfx/nvn/dmsh_abi.h with its reader dmsh_abi.py, the dmsh_xlate sources (Program.cs, csproj), the iOS compile convention ios_metal.py, and the tool lock dmsh_chain.lock (measured fingerprints of the Ryujinx shader dll / spirv-cross / metal compiler).
# A game's own inputs are not part of V: its profile's shader tables and nvn_* / shader_* keys are in each shader's cache key (dmsh_build.py shader_key), so a change rebuilds the shaders it affects,
# and their digest (inputs below) stamps the library: <cache dir>/b-<V>/inputs.tsv says which game and which inputs it was built from. c1_full.tsv / cb_extent.tsv name V and that digest in their
# header (table_head), and the host takes them only when both match its library; build_ipa.sh packs a library only when its digest is the profile's.
# The build (dmsh_build.py) writes into <cache dir>/b-<V>/ and the reflection json records chain = V; at compile time the host takes V from dm/gfx/nvn/dmsh_chain.h, loads only from b-<V>/ and verifies each json.
# Usage: dmsh_chain.py                 print V (default options)
#       dmsh_chain.py --header        rewrite dm/gfx/nvn/dmsh_chain.h (run after changing any file listed above, and commit it with the change)
#       dmsh_chain.py --inputs        print the digest of the current game profile's inputs (DM_GAME), as b-<V>/inputs.tsv records it
#       (checking the tools against dmsh_chain.lock, and rewriting it, is tool_lock.py's: the checks decide no output, so they are outside V and the shaders' cache keys)
# Environment: XLATE_DEBUG / XLATE_REDUCED / DMSH_F32_ATOMIC / DMSH_LOOP_CAP / DMSH_MESH_TRIM (same meaning as in dmsh_build.py, default 1 / 1 / native / 65536 / 1; non-default options yield a different V, which the host will not load)
import os, sys, ast, hashlib
DM_ROOT = os.environ.get('DM_ROOT') or os.path.expanduser('~/dm-work')   # Workspace root (game files, build outputs and run artifacts are all under it)
HERE = os.path.dirname(os.path.abspath(__file__)); GFX = os.path.dirname(HERE); HOME = os.path.expanduser('~')
FILES = ['tools/dmsh_chain.py', 'tools/dmsh_build.py', 'tools/dmsh_atomic.py', 'tools/dmsh_wide.py', 'tools/dmsh_fetch.py', 'tools/dmsh_vin.py', 'tools/dmsh_pull.py', 'tools/dmsh_pull.metal', 'tools/dmsh_alpha.py', 'tools/dmsh_logic.py', 'tools/dmsh_side.py', 'tools/dmsh_geometry.py', 'tools/dmsh_mesh.py', 'tools/dmsh_meshstage.py', 'tools/dmsh_facts.py', 'tools/dmsh_ampere.py', 'nvn/dmsh_abi.h', 'tools/dmsh_abi.py', 'tools/dmsh_xlate/Program.cs', 'tools/dmsh_xlate/dmsh_xlate.csproj', '../ios/tools/ios_metal.py', 'tools/dmsh_chain.lock']
# This target-specific lowering lives in the vendored translator. Include its
# sources as well as the rebuilt DLL fingerprint; no old shader cache can bypass it.
FILES += ['../third_party/ryujinx/src/Ryujinx.Graphics.Shader/' + f for f in (
    'Instructions/InstEmitSurface.cs', 'IntermediateRepresentation/TextureFlags.cs',
    'Translation/TranslationFlags.cs', 'Translation/HostCapabilities.cs',
    'Translation/Transforms/GeometryToCompute.cs', 'Translation/TranslatorContext.cs', 'Translation/Translator.cs', 'Translation/EmitterContext.cs', 'Translation/ShaderDefinitions.cs', 'CodeGen/Spirv/Instructions.cs',
    'StructuredIr/ShaderProperties.cs', 'Translation/Optimizations/BindlessElimination.cs', 'Translation/Optimizations/Optimizer.cs',
    'Translation/Optimizations/GlobalToStorage.cs', 'CodeGen/Spirv/SpirvGenerator.cs', 'Instructions/InstEmitMemory.cs',
    'Translation/TranslationOptions.cs', 'CodeGen/CodeGenParameters.cs', 'CodeGen/Spirv/CodeGenContext.cs')]
INPUT_TABLES = ['shader_facts.tsv', 'shader_map.tsv', 'shader_map.tsv.conflicts.tsv', 'shader_pairs.tsv', 'pso_pairs.tsv', 'bf_want.tsv', 'geo_mesh.tsv', 'dual_want.tsv']   # in the game profile folder
OPTIONAL_TABLES = ['mesh_pairs.tsv']   # also inputs, but in the digest only where the profile has one: profiles without NVN2 mesh shaders keep their digest
LOCK = os.path.join(HERE, 'dmsh_chain.lock'); HEADER = os.path.join(GFX, 'nvn/dmsh_chain.h')
STAMP = 'inputs.tsv'   # in the library directory b-<V>/
# the translator defaults to the in-repo build that matches the lock file (a rebuilt dll has different fingerprints)
XLATE_DIR = os.path.dirname(os.environ.get('XLATE', os.path.join(HERE, 'dmsh_xlate_bin/dmsh_xlate')))
# spirv-cross likewise: the in-repo build (spirv_cross_bin/build.sh, a pinned upstream commit) that matches the lock file, not the one on PATH, so every Mac converts with the same build
SPIRV_CROSS = os.environ.get('SPIRV_CROSS', os.path.join(HERE, 'spirv_cross_bin/spirv-cross'))

def f32_atomic():
    """How a float atomic add (RED / ATOMG .ADD.F32) is translated: 'native', one atomic_float add (the default), or 'cas', the older compare-and-swap loop (DMSH_F32_ATOMIC=cas, to compare or
    to go back if the native add misbehaves on some GPU). Part of the options, so each choice has its own V and shader cache keys"""
    v = os.environ.get('DMSH_F32_ATOMIC', 'native')
    if v not in ('native', 'cas'): sys.exit(f'[RED] DMSH_F32_ATOMIC={v}: expected native or cas')
    return v

def loop_cap():
    """The most times one entry into a loop runs its body (DMSH_LOOP_CAP, default 0 = no limit): a loop whose bound comes from memory that holds garbage then exits early
    and shades a pixel wrong instead of hanging the GPU. A global cap of 65536 cut Ocarina of Time's house ceiling (a legitimately long loop) and did not stop its hangs, so it is off;
    the per-shader caps below take its place. Part of the options, so each value has its own V and shader cache keys"""
    v = os.environ.get('DMSH_LOOP_CAP', '0')
    if not v.isdigit() or int(v) >= 1 << 32: sys.exit(f'[RED] DMSH_LOOP_CAP={v}: expected an iteration count below 2^32 (0 = no limit)')
    return int(v)

# agl's task shaders 99280b7b8aae78df / 47f9b38490dcf9a2 / f75708d176bb6591 (Ocarina of Time) loop (min(end - start, 256) - 1) >> 5 times, unsigned: a group dispatched on an empty bucket
# (end == start) loops 2^27 - 1 times and hangs the GPU; valid data never needs more than 8 passes (256 / 32). DMSH_LOOP_CAP_KEYS=<key>:<cap>[,...] (default: the three agl task shaders at 64, 8x the valid maximum; nine Model / Agl pixel shaders whose clustered light-list loop reads its count from a storage buffer with no min() at 256; "" = none)
LOOP_CAP_KEYS_DEFAULT = '47f9b38490dcf9a2:64,99280b7b8aae78df:64,f75708d176bb6591:64,0234f634ed411a85:256,74a006f0005b2f7a:256,e2f868a2799ed178:256,fa20be590aae1d99:256,cecf164164f89670:256,5ad65c0eefd09c7f:256,d771b87d65be5aa4:256,2de775822c08b025:256,fa998d0ed212944a:256'
def loop_cap_keys():
    v = os.environ.get('DMSH_LOOP_CAP_KEYS', LOOP_CAP_KEYS_DEFAULT); out = {}
    for item in filter(None, v.split(',')):
        k, _, c = item.partition(':')
        if len(k) != 16 or not c.isdigit(): sys.exit(f'[RED] DMSH_LOOP_CAP_KEYS item {item!r}: expected <16-hex-digit key>:<cap>')
        out[k] = int(c)
    return out

def loop_cap_for(key):
    return loop_cap_keys().get(key[:16], loop_cap())

def mesh_trim():
    """Whether a mesh shader hands Metal only the outputs its paired pixel shaders read (mesh_pairs.tsv; dmsh_meshstage.py widths): on by default, DMSH_MESH_TRIM=0 keeps every output a float4
    as before. Part of the options, so each choice has its own V and shader cache keys"""
    v = os.environ.get('DMSH_MESH_TRIM', '1')
    if v not in ('0', '1'): sys.exit(f'[RED] DMSH_MESH_TRIM={v}: expected 0 or 1')
    return v == '1'

def options():
    return 'debug=%s reduced=%s f32_atomic=%s loop_cap=%d loop_cap_keys=%s mesh_trim=%s' % (os.environ.get('XLATE_DEBUG', '1') != '0', os.environ.get('XLATE_REDUCED', '1') == '1', f32_atomic(), loop_cap(), ','.join('%s:%d' % kv for kv in sorted(loop_cap_keys().items())), mesh_trim())

def version():
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode() + b'\0' + open(os.path.join(GFX, f), 'rb').read() + b'\0')
    h.update(options().encode())
    return h.hexdigest()[:12]

def code_form(source, blank=()):
    """The part of a Python source that can change what it computes, as bytes: the AST dump (comments, blank lines, formatting and line numbers are not in it) without docstrings, and with the bodies of
    the functions named in `blank` replaced by `pass` (dmsh_build.py: the rule functions, which have their own per-shader fingerprints). Anything else, a constant, a string literal that is not a
    docstring, a default argument, a decorator, changes it. ast.dump's text differs between Python versions, so the version is part of the form: two Macs with different Pythons just do not share a cache"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if getattr(node, 'name', None) in blank: node.body = [ast.Pass()]
            elif node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ('python %d.%d\0' % sys.version_info[:2]).encode() + ast.dump(tree).encode()

def load_game():   # the current game profile (DM_GAME), only for what needs one: the version itself does not
    sys.path.insert(0, os.path.join(GFX, '../games')); import game
    return game.load()

def profile_rows(g):   # the profile keys that change how a shader is built (nvn_*, shader_*)
    return ''.join(f'{k}\t{chr(9).join(v)}\n' for k, v in g.rows if k.startswith(('nvn_', 'shader_'))).encode()

def inputs(g):
    """Digest of a game profile's inputs to its shader library: the shader tables (a missing one counts as such) and the nvn_* / shader_* keys"""
    h = hashlib.sha256()
    for f in INPUT_TABLES:
        p = g.table(f)
        h.update(f'game/{f}'.encode() + b'\0' + (p.read_bytes() if p.exists() else b'missing') + b'\0')
    for f in OPTIONAL_TABLES:
        p = g.table(f)
        if p.exists(): h.update(f'game/{f}'.encode() + b'\0' + p.read_bytes() + b'\0')
    h.update(profile_rows(g))
    return h.hexdigest()[:12]

def read_stamp(lib):   # {'game': title ID, 'inputs': digest} of a library directory; {} when it has none
    try: return dict(l.rstrip('\n').split('\t', 1) for l in open(os.path.join(lib, STAMP)) if '\t' in l and not l.startswith('#'))
    except OSError: return {}

def write_stamp(lib, game_id, digest):
    tmp = os.path.join(lib, STAMP + '.tmp')
    with open(tmp, 'w') as f: f.write(f'# the game and the profile inputs this library was built from (dm/gfx/tools/dmsh_chain.py inputs)\ngame\t{game_id}\ninputs\t{digest}\n')
    os.replace(tmp, os.path.join(lib, STAMP))

def table_head(lib):   # the header c1_full.tsv / cb_extent.tsv start with: the library's chain version and its inputs ("none" when it has no stamp, which nothing takes)
    return f'# chain {os.path.basename(os.path.normpath(lib))} inputs {read_stamp(lib).get("inputs", "none")}'

def xlate_source_sha():   # same convention as dmsh_xlate --source-sha: the embedded Program.cs and csproj concatenated in that order
    return hashlib.sha256(b''.join(open(os.path.join(HERE, 'dmsh_xlate', f), 'rb').read() for f in ('Program.cs', 'dmsh_xlate.csproj'))).hexdigest()[:16]

def header_text(v):
    return (f'// Generated file (dm/gfx/tools/dmsh_chain.py --header): the B shader library translation chain version this source tree expects (default options), one for every game;\n'
            f'// the host loads only <library dir>/b-<V>/. Run dmsh_chain.py --header after changing the chain\'s tools and commit this file with the change\n'
            f'#define DMSH_CHAIN "{v}"\n')

if __name__ == '__main__':
    a = sys.argv[1:]
    if a == ['--header']:
        open(HEADER, 'w').write(header_text(version()))
        print(version())
    elif a == ['--inputs']: print(inputs(load_game()))
    elif not a: print(version())
    else: sys.exit(__doc__ if __doc__ else 'usage: see the file header')
