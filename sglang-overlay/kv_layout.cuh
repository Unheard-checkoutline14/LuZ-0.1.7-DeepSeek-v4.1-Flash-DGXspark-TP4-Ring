#pragma once

// ⚠ Two facts about this file that are easy to get wrong (measured 2026-09-16):
//
// 1. It IS covered by the JIT cache, but not by the build *directory* key.
//    `load_jit` keys `build-<key>/` on the listed csrc sources only, so that name
//    does not move when this file changes -- which is what an earlier probe
//    (`probe_jit_cache_key.py`) measured, and it is not the thing that matters.
//    What matters is `cache.find_prebuilt`: it reads each leaf's recorded
//    dependency list (a real leaf here records 432 entries), re-hashes every one
//    of them by content, and requires `leaf.name == "deps-" + _deps_key(current)`.
//    This header is in that list, so editing it renames the expected leaf and the
//    old one becomes a MISS -- the cache self-invalidates and the kernel is
//    rebuilt. Verified both ways (probe_deps_closure.py): a leaf built before the
//    edit reports "CHANGED: kernels:include/sgl_kernel/deepseek_v4/kv_layout.cuh"
//    and MISSes; a leaf built after HITs.
//    ⇒ correctness needs no manual step. A rebuild does cost a compile at first
//      use, which `w6-kit/guard/jit-header-refresh.sh` can pre-empt by publishing
//      the new leaf ahead of time (offline, no GPU). It must only ever *publish*;
//      dropping leaves would remove what the running server is hitting.
//
// 2. Editing this file in place vs replacing it matters. `start.sh` bind-mounts
//    overlay files one by one, so a container holds the *inode* it mounted: an
//    editor that writes a new file (rename/unlink+create, which most tools do)
//    leaves the running container on the old bytes until it is recreated. The
//    next boot picks up the new content; the running process does not.

#include <sgl_kernel/type.cuh>
#include <sgl_kernel/utils.cuh>
#include <sgl_kernel/vec.cuh>
#include <sgl_kernel/warp.cuh>

#include <sgl_kernel/deepseek_v4/fp8_utils.cuh>
// `store_row_fp4` derives its e4m3 scale from `fp4::compressed_kv_scale` so the
// pool bytes and the V4 fp8 writers cannot drift apart (see the call site).
#include <sgl_kernel/deepseek_v4/fp4_utils.cuh>

#include <cstdint>
#ifndef USE_ROCM
#include <cuda_fp4.h>
#include <cuda_fp8.h>
#endif

// Paged fp8 / fp4 KV cache layouts read by the d_qk = 512 sparse MLA decode
// kernels. A page block is `page_size` data rows followed by `page_size` scale
// rows, so the scale region starts at byte `page_size * kDataBytes`:
//
//   V4       584 B/token: 448 e4m3 + 64 bf16 (RoPE) data, 7 ue8m0 scales + 1 pad,
//            one scale per 64 e4m3 values.
//   V41      528 B/token: 512 e4m3 data (the RoPE dims are quantized too),
//            16 ue8m0 scales, one per 32 values.
//   V41_FP4  288 B/token: 512 e2m1 data packed two per byte (even index in the
//            low nibble), 32 e4m3 scales, one per 16 values.
//
// The reader requires the rows of a page to be contiguous and the page stride
// to be a multiple of kPageAlign (its TMA row stride), which is what
// kv_page_bytes pads to. The pure-torch reference of the V4.1 quantizers is
// `sglang.srt.layers.attention.dsv4.torch_quant`.

namespace sglang {

namespace deepseek_v4 {

enum class KVLayout : int32_t { V4 = 0, V41 = 1, V41_FP4 = 2 };

template <KVLayout kLayout>
struct KVLayoutTraits;

template <>
struct KVLayoutTraits<KVLayout::V4> {
  static constexpr int64_t kDataBytes = 576;
  static constexpr int64_t kScaleBytes = 8;
  static constexpr int64_t kTileSize = 64;
  static constexpr int64_t kPageAlign = 576;
  static constexpr int64_t kBytesPerToken = kDataBytes + kScaleBytes;
};

template <>
struct KVLayoutTraits<KVLayout::V41> {
  static constexpr int64_t kDataBytes = 512;
  static constexpr int64_t kScaleBytes = 16;
  static constexpr int64_t kTileSize = 32;
  static constexpr int64_t kPageAlign = 512;
  static constexpr int64_t kBytesPerToken = kDataBytes + kScaleBytes;
};

template <>
struct KVLayoutTraits<KVLayout::V41_FP4> {
  static constexpr int64_t kDataBytes = 256;
  static constexpr int64_t kScaleBytes = 32;
  static constexpr int64_t kTileSize = 16;
  static constexpr int64_t kPageAlign = 256;
  static constexpr int64_t kBytesPerToken = kDataBytes + kScaleBytes;
};

/// Bytes of one page block: `page_size` tokens, padded up to the reader's row stride.
template <KVLayout kLayout>
constexpr int64_t kv_page_bytes(int64_t page_size) {
  using Traits = KVLayoutTraits<kLayout>;
  return (page_size * Traits::kBytesPerToken + Traits::kPageAlign - 1) / Traits::kPageAlign * Traits::kPageAlign;
}

/// Addressing of a paged cache in one layout: a page is `1 << kPageBits` data rows followed
/// by as many scale rows, padded to the layout's kPageAlign. Every member is a compile-time
/// constant or a constant shift / multiply of the token index, so it folds to the same code
/// as the hand-written arithmetic; the index keeps the caller's type `LocT`.
template <KVLayout kLayout, uint32_t kPageBits>
struct PagedKV {
  using Traits = KVLayoutTraits<kLayout>;
  static constexpr int64_t kPageSize = int64_t{1} << kPageBits;
  static constexpr int64_t kPageBytes = kv_page_bytes<kLayout>(kPageSize);
  /// Byte offset of the scale rows inside a page.
  static constexpr int64_t kScaleBase = Traits::kDataBytes << kPageBits;

  template <typename LocT>
  static constexpr LocT page_of(LocT loc) {
    return loc >> kPageBits;
  }
  template <typename LocT>
  static constexpr LocT slot_of(LocT loc) {
    return loc & (static_cast<LocT>(kPageSize) - 1);
  }
  /// Byte offsets of token `loc`'s data row and scale row from the cache base.
  template <typename LocT>
  static constexpr int64_t data_offset(LocT loc) {
    return page_of(loc) * kPageBytes + slot_of(loc) * Traits::kDataBytes;
  }
  template <typename LocT>
  static constexpr int64_t scale_offset(LocT loc) {
    return page_of(loc) * kPageBytes + kScaleBase + slot_of(loc) * Traits::kScaleBytes;
  }

  struct Row {
    uint8_t* data;
    uint8_t* scale;
  };
  /// The data row and scale row of token `loc`.
  template <typename LocT>
  SGL_DEVICE static Row row(uint8_t* cache, LocT loc) {
    uint8_t* page = cache + page_of(loc) * kPageBytes;
    return {page + slot_of(loc) * Traits::kDataBytes, page + kScaleBase + slot_of(loc) * Traits::kScaleBytes};
  }
};

#ifndef USE_ROCM

namespace v41 {

/// The row helpers below quantize one 512-wide token spread over `512 / kVecSize` threads,
/// thread `tx` holding elements `[kVecSize * tx, kVecSize * (tx + 1))` as fp32. They are
/// warp-collective (sub-warp reductions under the full mask), so every thread of the token
/// must call them together. `kVecSize` is even, a power of two and at most the tile size.
/// NaN / inf inputs are not handled.

/// Per-thread |max| over the vector.
template <uint32_t kVecSize>
SGL_DEVICE float vec_amax(const float (&v)[kVecSize]) {
  float amax = fabsf(v[0]);
#pragma unroll
  for (uint32_t i = 1; i < kVecSize; ++i) {
    amax = fmaxf(amax, fabsf(v[i]));
  }
  return amax;
}

/// V4.1 fp8 row: one ue8m0 scale per 32-element tile. `data_row` is the token's 512 B,
/// `scale_row` its 16 scale bytes. Scale `2^ceil(log2(max(amax / 448, 1e-4)))` stored as the
/// ue8m0 byte, payload `e4m3(x / scale)` rounded to nearest even (|x / scale| <= 448, so it
/// never saturates).
template <uint32_t kVecSize>
SGL_DEVICE void store_row_fp8(uint8_t* data_row, uint8_t* scale_row, uint32_t tx, const float (&v)[kVecSize]) {
  using namespace device;
  constexpr uint32_t kTileLanes = KVLayoutTraits<KVLayout::V41>::kTileSize / kVecSize;
  static_assert(kVecSize % 2 == 0 && kTileLanes >= 1 && (kTileLanes & (kTileLanes - 1)) == 0);

  const float amax = warp::reduce_max<kTileLanes>(vec_amax(v));
  // ceil(log2(max(amax / 448, 1e-4))) straight from the bits of amax: 448 = 1.75 * 2^8, so
  // the quotient's exponent is amax's minus 8, plus one when amax's mantissa exceeds 1.75
  // (the quotient is then just above a power of two), floored at 2^-13, the smallest power
  // of two >= 1e-4. Exact for every finite amax, without the reference's fp32 division.
  const uint32_t bits = __float_as_uint(amax);
  const int32_t exponent =
      max(static_cast<int32_t>(bits >> 23) - 8 + static_cast<int32_t>((bits & 0x7FFFFFu) > 0x600000u), 114);
  // The scale is a power of two, so the multiply by its reciprocal is the exact quotient.
  const float inv_scale = fp8::inv_scale_ue8m0(exponent);
  AlignedVector<fp8x2_e4m3_t, kVecSize / 2> out;
#pragma unroll
  for (uint32_t i = 0; i < kVecSize / 2; ++i) {
    // `cvt.rn.satfinite.e4m3x2` directly: |x / scale| <= 448 needs no clamp.
    out[i] = fp8x2_e4m3_t{fp32x2_t{v[2 * i] * inv_scale, v[2 * i + 1] * inv_scale}};
  }
  out.store(data_row, tx);
  // Every lane of the tile holds the exponent; they all store the same byte.
  scale_row[tx / kTileLanes] = static_cast<uint8_t>(exponent);
}

/// V4.1 fp4 row: one e4m3 scale per 16-element tile. `data_row` is the token's 256 B,
/// `scale_row` its 32 scale bytes. Scale `fp4::compressed_kv_scale(amax)` -- i.e.
/// `e4m3(clamp(amax * (1/6), 2^-9, 448))` rounded to nearest even; codes
/// `cvt.rn.satfinite.e2m1x2` of `x / scale` (ties to even, saturating at 6, the sign
/// kept for a value that rounds to zero), the even element in the low nibble.
template <uint32_t kVecSize>
SGL_DEVICE void store_row_fp4(uint8_t* data_row, uint8_t* scale_row, uint32_t tx, const float (&v)[kVecSize]) {
  using namespace device;
  constexpr uint32_t kTileLanes = KVLayoutTraits<KVLayout::V41_FP4>::kTileSize / kVecSize;
  static_assert(kVecSize % 2 == 0 && kTileLanes >= 1 && (kTileLanes & (kTileLanes - 1)) == 0);

  const float amax = warp::reduce_max<kTileLanes>(vec_amax(v));
  // The scale byte must come out of the *same expression* as the model reference
  // this layout reproduces, so call `fp4::compressed_kv_scale` (the fake quant the
  // V4 fp8 writers c1/c2.cuh apply before requantizing to fp8) instead of
  // re-deriving the clamp here. `compressed_kv_scale` multiplies by the reciprocal
  // `1/6`; writing `amax / 6.0f` instead rounds to a different e4m3 byte for ~1 in
  // 2^23 amax values, which breaks the byte-for-byte equivalence with the pre-fork
  // pool that the fp4 layout + `repack_fp4_to_v4` bridge exist to preserve.
  const __nv_fp8_e4m3 scale_e4m3{fp4::compressed_kv_scale(amax)};
  const float scale = static_cast<float>(scale_e4m3);
  AlignedVector<uint8_t, kVecSize / 2> out;
#pragma unroll
  for (uint32_t i = 0; i < kVecSize / 2; ++i) {
    // IEEE division by the rounded scale, as the reference divides; a reciprocal multiply
    // could land on the other side of an e2m1 tie. The `+ 0.0f` matches
    // `fp4::fake_quant_compressed_kv_x2`: it clears a negative zero element to +0.0 so
    // the stored code is 0x0 rather than 0x8 (value-neutral, byte-visible).
    out[i] = static_cast<uint8_t>(__nv_cvt_float2_to_fp4x2(
        fp32x2_t{__fdiv_rn(v[2 * i], scale) + 0.0f, __fdiv_rn(v[2 * i + 1], scale) + 0.0f}, __NV_E2M1,
        cudaRoundNearest));
  }
  out.store(data_row, tx);
  // Every lane of the tile holds the scale; they all store the same byte.
  scale_row[tx / kTileLanes] = scale_e4m3.__x;
}

/// Dispatch on the layout for a 512-wide row held as `kVecSize` consecutive fp32 per thread.
/// V4 has no row helper here: its writers keep their nope / RoPE split code.
template <KVLayout kLayout, uint32_t kVecSize>
SGL_DEVICE void store_row(uint8_t* data_row, uint8_t* scale_row, uint32_t tx, const float (&v)[kVecSize]) {
  static_assert(kLayout != KVLayout::V4, "V4 rows are written by the caller");
  if constexpr (kLayout == KVLayout::V41) {
    store_row_fp8(data_row, scale_row, tx, v);
  } else {
    store_row_fp4(data_row, scale_row, tx, v);
  }
}

/// Same, for a row kept in an `AlignedVector<float, kVecSize>`.
template <KVLayout kLayout, std::size_t kVecSize>
SGL_DEVICE void
store_row(uint8_t* data_row, uint8_t* scale_row, uint32_t tx, const device::AlignedVector<float, kVecSize>& v) {
  store_row<kLayout>(data_row, scale_row, tx, *reinterpret_cast<const float (*)[kVecSize]>(v.data()));
}

}  // namespace v41

#endif  // USE_ROCM

}  // namespace deepseek_v4

}  // namespace sglang
