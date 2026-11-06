// Indirect-count multi-draws masked on the GPU, and plain indirect draws clamped (nvn_mtl.m mdx_run, DM_NVN_IND_CLAMP)
#include <metal_stdlib>
using namespace metal;
// cnt null: a plain indirect draw (no count; DM_NVN_IND_CLAMP). js: the host's serial for the job, to name the draw's shaders in the clamp log (nvn_mtl.m indc_report)
struct mjob { device const uint *rec; device const uint *cnt; device uint *out; uint i, words, js, pad; };
// The first record clamped in the run, read by the host when the submission completes (nvn_mtl.m indc_buf): hit is taken once, then the record as the GPU found it.
// on / pmax are the host's settings: pmax bounds count × instances (2^27 with DM_NVN_IND_CLAMP, else no bound)
struct ilog { atomic_uint hit; uint kind, js, words; uint rec[5]; uint on; ulong pmax; };
static void ilog_put(device ilog *lg, uint kind, uint js, uint words, device const uint *rec) {
  if (atomic_exchange_explicit(&lg->hit, 1u, memory_order_relaxed)) return;
  lg->kind = kind; lg->js = js; lg->words = words; for (uint k = 0; k < words; k++) lg->rec[k] = rec[k]; }
kernel void mdx_mask(device const mjob *j [[buffer(0)]], device ilog *lg [[buffer(1)]], uint t [[thread_position_in_grid]]) {
  mjob m = j[t]; if (!m.out) return;
  // An indirect mesh draw: NVN's {count, first} as Metal's threadgroups {x, y, z} (nvn_geometry.inc mesh_tasks_draw). The count is clamped to the 65,535 task groups NVN allows:
  // a stale or overwritten record (the host reads records ahead, mdx_run) launched ~10^9 groups and the GPU watchdog killed the command buffer (Ocarina, Link's house, M1 Pro)
  if (!m.words) { uint c = m.rec[0]; if (c > 65535u) ilog_put(lg, 2u, m.js, 2u, m.rec); m.out[0] = min(c, 65535u); m.out[1] = 1u; m.out[2] = 1u; return; }
  // A record whose vertex/index or instance count is past 2^24, or (DM_NVN_IND_CLAMP) whose count × instances is past 2^27, is garbage for the same reason: it is drawn as empty
  // instead of hanging the GPU (a GPU-written record read before its writer finished, or never written: 2^31 instances ran one draw for seconds)
  uint c = m.rec[0], n = m.rec[1];
  bool sane = c <= (1u << 24) && n <= (1u << 24) && (ulong)c * n <= lg->pmax;
  bool live = !m.cnt || m.i < *m.cnt;
  if (live && !sane) ilog_put(lg, m.cnt ? 1u : 0u, m.js, m.words, m.rec);
  for (uint k = 0; k < m.words; k++) m.out[k] = live && sane ? m.rec[k] : 0u; }
