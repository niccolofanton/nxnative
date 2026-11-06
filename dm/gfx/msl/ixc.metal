// Indirect draws Metal cannot take as they are: records converted to indexed indirect draws (nvn_mtl.m ixc_run)
#include <metal_stdlib>
using namespace metal;
// The clamp log shared with mdx_mask (dm/gfx/msl/mdx.metal ilog; nvn_mtl.m indc_buf). With on (DM_NVN_IND_CLAMP), a record whose count or instances is past 2^24, or whose
// count × instances is past pmax, draws nothing: a garbage instance count passed through the conversion ran one draw for seconds
struct ilog { atomic_uint hit; uint kind, js, words; uint rec[5]; uint on; ulong pmax; };
static bool ilog_sane(device ilog *lg, uint kind, uint js, uint words, device const uint *rec) {
  uint c = rec[0], n = rec[1];
  if (!lg->on || (c <= (1u << 24) && n <= (1u << 24) && (ulong)c * n <= lg->pmax)) return true;
  if (!atomic_exchange_explicit(&lg->hit, 1u, memory_order_relaxed)) { lg->kind = kind; lg->js = js; lg->words = words; for (uint k = 0; k < words; k++) lg->rec[k] = rec[k]; }
  return false; }
struct ajob { device const uint *rec; device uint *args; uint prim, cap, js, pad; };
kernel void ixc_arrays(device const ajob *j [[buffer(0)]], device ilog *lg [[buffer(1)]], uint i [[threadgroup_position_in_grid]]) {
  device const uint *s = j[i].rec; uint n = s[0], c = j[i].prim == 7 ? n / 4 * 6 : n >= 3 ? (n - 2) * 3 : 0;
  bool ok = ilog_sane(lg, 3u, j[i].js, 4u, s); if (!ok) c = 0;
  device uint *d = j[i].args; d[0] = min(c, j[i].cap); d[1] = ok ? s[1] : 0u; d[2] = 0; d[3] = s[2]; d[4] = s[3]; }
struct ejob { device const uint *rec; device const uchar *ib; device uint *out; device uint *args; uint prim, isz, ilen, cap, js, pad; };
kernel void ixc_expand(constant ejob &j [[buffer(0)]], device ilog *lg [[buffer(1)]], uint i [[thread_position_in_grid]]) {
  uint n = j.rec[0], m = min(j.prim == 7 ? n / 4 * 6 : j.prim == 6 ? (n >= 3 ? (n - 2) * 3 : 0) : n, j.cap);
  bool ok = ilog_sane(lg, 4u, j.js, 5u, j.rec); if (!ok) m = 0;   // every thread checks; only the insane path touches the log
  if (i == 0) { j.args[0] = m; j.args[1] = ok ? j.rec[1] : 0u; j.args[2] = 0; j.args[3] = j.rec[3]; j.args[4] = j.rec[4]; }
  if (i >= m) return;
  uint t = i / 3, c = i % 3, p = j.prim == 7 ? t / 2 * 4 + (c ? c + (t & 1) : 0) : j.prim == 6 ? (c ? t + c : 0) : i, x = j.rec[2] + p;
  j.out[i] = (ulong)x * j.isz + j.isz > j.ilen ? 0u : j.isz == 1 ? uint(j.ib[x]) : j.isz == 2 ? uint(((device const ushort *)j.ib)[x]) : ((device const uint *)j.ib)[x]; }
// Indirect dispatch arguments clamped before the dispatch reads them (nvn_mtl.m dispatch, DM_NVN_DISPATCH_CLAMP): a group count the GPU wrote from bad data (billions of threadgroups) runs
// for ever on the GPU and is not reclaimed when the process exits (PRAGMATA's first real frame, twice followed by the Mac's WindowServer stopping; PR #1444)
struct djob { device const uint *rec; device uint *out; uint maxdim; uint maxtotal; };
kernel void dpc_clamp(device const djob *j [[buffer(0)]]) {
  uint x = min(j->rec[0], j->maxdim), y = min(j->rec[1], j->maxdim), z = min(j->rec[2], j->maxdim);
  bool ok = (ulong)x * y * z <= j->maxtotal;
  j->out[0] = ok ? x : 0u; j->out[1] = ok ? y : 0u; j->out[2] = ok ? z : 0u; }
