//! CPython `random.Random` (MT19937) の bit 完全再現。
//!
//! Python engine の `state.rng` は `random.Random`。 効果 (trash_self_hand_random=randrange /
//! shuffle_self_deck=shuffle) が消費する乱数を Rust で同一列生成し、 rng 依存 effect も差分テストで
//! bit-match させる (= 「python と同じ状態」 を rng 込みで維持)。
//!
//! 状態は Python の `rng.getstate()` = (version=3, keys[625], gauss_next) から復元する。
//! keys[0..624] = MT word 配列、 keys[624] = pos (次に読む index、 624 で twist 発生)。
//!
//! 実装は CPython Modules/_randommodule.c の genrand_uint32 / getrandbits / _randbelow に一致。

const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908b0df;
const UPPER_MASK: u32 = 0x80000000;
const LOWER_MASK: u32 = 0x7fffffff;

#[derive(Clone, Debug, PartialEq)]
pub struct PyRandom {
    mt: [u32; N],
    pos: usize,
}

impl PyRandom {
    /// Python の getstate() の keys (625 要素 = mt[0..624] + pos) から復元。
    pub fn from_state(keys: &[u64]) -> Option<PyRandom> {
        if keys.len() != N + 1 {
            return None;
        }
        let mut mt = [0u32; N];
        for i in 0..N {
            mt[i] = keys[i] as u32;
        }
        let pos = keys[N] as usize;
        Some(PyRandom { mt, pos })
    }

    /// CPython genrand_uint32: 32bit 乱数を1つ生成 (pos>=N で twist)。
    pub fn genrand_uint32(&mut self) -> u32 {
        if self.pos >= N {
            let mt = &mut self.mt;
            let mag01 = [0u32, MATRIX_A];
            let mut kk = 0;
            while kk < N - M {
                let y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
                mt[kk] = mt[kk + M] ^ (y >> 1) ^ mag01[(y & 0x1) as usize];
                kk += 1;
            }
            while kk < N - 1 {
                let y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
                // kk + (M - N) を wrap なしで: kk + M - N (N=624,M=397 → M-N 負) = kk - 227
                mt[kk] = mt[kk + M - N] ^ (y >> 1) ^ mag01[(y & 0x1) as usize];
                kk += 1;
            }
            let y = (mt[N - 1] & UPPER_MASK) | (mt[0] & LOWER_MASK);
            mt[N - 1] = mt[M - 1] ^ (y >> 1) ^ mag01[(y & 0x1) as usize];
            self.pos = 0;
        }
        let mut y = self.mt[self.pos];
        self.pos += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680;
        y ^= (y << 15) & 0xefc60000;
        y ^= y >> 18;
        y
    }

    /// CPython getrandbits(k) の k<=32 経路 (engine の randbelow は hand/deck 幅 → k<=~6 で常に該当)。
    /// k>32 は engine 効果では発生しないため未対応 (panic 回避で 32bit 分だけ返す近似はせず、 k をそのまま扱う)。
    pub fn getrandbits(&mut self, k: u32) -> u64 {
        debug_assert!(k >= 1 && k <= 32, "engine 用途では k<=32 のみ");
        if k == 0 {
            return 0;
        }
        if k <= 32 {
            return (self.genrand_uint32() >> (32 - k)) as u64;
        }
        // k>32: 32bit ワードを little-endian に組む (念のため実装、 engine では未使用)
        let mut result: u64 = 0;
        let mut kk = k;
        let mut shift = 0;
        while kk > 0 {
            let take = kk.min(32);
            let mut r = self.genrand_uint32();
            if take < 32 {
                r >>= 32 - take;
            }
            result |= (r as u64) << shift;
            shift += 32;
            kk -= take;
        }
        result
    }

    /// CPython _randbelow_with_getrandbits(n): [0, n) の一様乱数。 n=0 は 0。
    pub fn randbelow(&mut self, n: u64) -> u64 {
        if n == 0 {
            return 0;
        }
        let bits = 64 - n.leading_zeros(); // = Python n.bit_length()
        let mut r = self.getrandbits(bits);
        while r >= n {
            r = self.getrandbits(bits);
        }
        r
    }

    /// random.randrange(stop) (start=0,step=1) = randbelow(stop)。
    pub fn randrange(&mut self, stop: u64) -> u64 {
        self.randbelow(stop)
    }

    /// random.shuffle(x): Fisher-Yates (Python 3.11+、 random 引数なし)。
    /// インデックス列 [0..n) を in-place シャッフルした結果の並びを返す。
    pub fn shuffle_perm(&mut self, n: usize) -> Vec<usize> {
        let mut x: Vec<usize> = (0..n).collect();
        let mut i = n;
        while i > 1 {
            i -= 1;
            let j = self.randbelow((i + 1) as u64) as usize;
            x.swap(i, j);
        }
        x
    }

    /// 現在の状態を getstate() 形式 (625 要素) に書き出す (後段 rng 更新の追跡用、 将来利用)。
    pub fn to_state(&self) -> Vec<u64> {
        let mut v: Vec<u64> = self.mt.iter().map(|&w| w as u64).collect();
        v.push(self.pos as u64);
        v
    }
}
