// Shared Keccak-f1600 core (Ethereum keccak256, pad 0x01). Compiles as CUDA or plain C.
#pragma once
#include <stdint.h>
#ifdef __CUDACC__
#define KFN __device__ __host__ __forceinline__
#else
#define KFN static inline
#endif
KFN uint64_t rotl64(uint64_t x, int n){ return (x<<n)|(x>>(64-n)); }
KFN uint64_t bswap64_(uint64_t x){
  x=((x&0x00FF00FF00FF00FFULL)<<8)|((x>>8)&0x00FF00FF00FF00FFULL);
  x=((x&0x0000FFFF0000FFFFULL)<<16)|((x>>16)&0x0000FFFF0000FFFFULL);
  return (x<<32)|(x>>32);
}
#define KRC_LIST {0x0000000000000001ULL,0x0000000000008082ULL,0x800000000000808aULL,0x8000000080008000ULL,\
0x000000000000808bULL,0x0000000080000001ULL,0x8000000080008081ULL,0x8000000000008009ULL,0x000000000000008aULL,\
0x0000000000000088ULL,0x0000000080008009ULL,0x000000008000000aULL,0x000000008000808bULL,0x800000000000008bULL,\
0x8000000000008089ULL,0x8000000000008003ULL,0x8000000000008002ULL,0x8000000000000080ULL,0x000000000000800aULL,\
0x800000008000000aULL,0x8000000080008081ULL,0x8000000000008080ULL,0x0000000080000001ULL,0x8000000080008008ULL}
KFN void keccakf(uint64_t a[25]){
  const uint64_t RC[24]=KRC_LIST;
#ifdef __CUDACC__
#pragma unroll
#endif
  for(int r=0;r<24;r++){
    uint64_t c0=a[0]^a[5]^a[10]^a[15]^a[20], c1=a[1]^a[6]^a[11]^a[16]^a[21],
             c2=a[2]^a[7]^a[12]^a[17]^a[22], c3=a[3]^a[8]^a[13]^a[18]^a[23],
             c4=a[4]^a[9]^a[14]^a[19]^a[24];
    uint64_t d0=c4^rotl64(c1,1), d1=c0^rotl64(c2,1), d2=c1^rotl64(c3,1), d3=c2^rotl64(c4,1), d4=c3^rotl64(c0,1);
    for(int i=0;i<25;i+=5){a[i]^=d0;a[i+1]^=d1;a[i+2]^=d2;a[i+3]^=d3;a[i+4]^=d4;}
    // rho+pi
    uint64_t b[25];
    b[0]=a[0];
    b[10]=rotl64(a[1],1);  b[7]=rotl64(a[10],3);  b[11]=rotl64(a[7],6);  b[17]=rotl64(a[11],10);
    b[18]=rotl64(a[17],15);b[3]=rotl64(a[18],21); b[5]=rotl64(a[3],28);  b[16]=rotl64(a[5],36);
    b[8]=rotl64(a[16],45); b[21]=rotl64(a[8],55); b[24]=rotl64(a[21],2); b[4]=rotl64(a[24],14);
    b[15]=rotl64(a[4],27); b[23]=rotl64(a[15],41);b[19]=rotl64(a[23],56);b[13]=rotl64(a[19],8);
    b[12]=rotl64(a[13],25);b[2]=rotl64(a[12],43); b[20]=rotl64(a[2],62); b[14]=rotl64(a[20],18);
    b[22]=rotl64(a[14],39);b[9]=rotl64(a[22],61); b[6]=rotl64(a[9],20);  b[1]=rotl64(a[6],44);
    for(int i=0;i<25;i+=5){
      uint64_t x0=b[i],x1=b[i+1],x2=b[i+2],x3=b[i+3],x4=b[i+4];
      a[i]=x0^(~x1&x2); a[i+1]=x1^(~x2&x3); a[i+2]=x2^(~x3&x4); a[i+3]=x3^(~x4&x0); a[i+4]=x4^(~x0&x1);
    }
    a[0]^=RC[r];
  }
}
// seedL[4]: seed bytes as little-endian lanes. nonce = (hi<<64)|lo (128-bit, upper 128 bits zero).
// out d[4]: digest as big-endian 64-bit words (d[0] = most significant).
KFN void pearl_hash(const uint64_t seedL[4], uint64_t hi, uint64_t lo, uint64_t d[4]){
  uint64_t a[25];
  for(int i=0;i<25;i++) a[i]=0;
  a[0]=seedL[0];a[1]=seedL[1];a[2]=seedL[2];a[3]=seedL[3];
  a[6]=bswap64_(hi); a[7]=bswap64_(lo);
  a[8]=0x01ULL; a[16]=0x8000000000000000ULL;
  keccakf(a);
  d[0]=bswap64_(a[0]);d[1]=bswap64_(a[1]);d[2]=bswap64_(a[2]);d[3]=bswap64_(a[3]);
}
KFN int le_target(const uint64_t d[4], const uint64_t t[4]){
  for(int i=0;i<4;i++){ if(d[i]<t[i]) return 1; if(d[i]>t[i]) return 0; }
  return 1;
}
