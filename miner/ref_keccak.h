// Independent byte-oriented reference keccak256 (host only, NOT sharing code with keccak_core.h).
// Used to cross-check GPU results: builds abi.encode(seed,nonce) as 64 raw bytes and hashes generically.
#pragma once
#include <stdint.h>
#include <string.h>
static uint64_t ref_rol(uint64_t x,unsigned n){ n%=64; return n?((x<<n)|(x>>(64-n))):x; }
static void ref_f1600(uint64_t s[25]){
  static const uint64_t RC[24]={0x1ULL,0x8082ULL,0x800000000000808aULL,0x8000000080008000ULL,0x808bULL,0x80000001ULL,
   0x8000000080008081ULL,0x8000000000008009ULL,0x8aULL,0x88ULL,0x80008009ULL,0x8000000aULL,0x8000808bULL,
   0x800000000000008bULL,0x8000000000008089ULL,0x8000000000008003ULL,0x8000000000008002ULL,0x8000000000000080ULL,
   0x800aULL,0x800000008000000aULL,0x8000000080008081ULL,0x8000000000008080ULL,0x80000001ULL,0x8000000080008008ULL};
  static const unsigned R[5][5]={{0,36,3,41,18},{1,44,10,45,2},{62,6,43,15,61},{28,55,25,21,56},{27,20,39,8,14}}; // R[x][y]
  for(int r=0;r<24;r++){
    uint64_t C[5],D[5],B[25];
    for(int x=0;x<5;x++) C[x]=s[x]^s[x+5]^s[x+10]^s[x+15]^s[x+20];
    for(int x=0;x<5;x++) D[x]=C[(x+4)%5]^ref_rol(C[(x+1)%5],1);
    for(int i=0;i<25;i++) s[i]^=D[i%5];
    for(int x=0;x<5;x++) for(int y=0;y<5;y++) B[y+5*((2*x+3*y)%5)]=ref_rol(s[x+5*y],R[x][y]);
    for(int x=0;x<5;x++) for(int y=0;y<5;y++) s[x+5*y]=B[x+5*y]^((~B[(x+1)%5+5*y])&B[(x+2)%5+5*y]);
    s[0]^=RC[r];
  }
}
static void ref_keccak256(const uint8_t* in,size_t len,uint8_t out[32]){
  uint64_t s[25]; memset(s,0,sizeof s); const size_t rate=136; uint8_t blk[136];
  while(1){
    size_t take=len<rate?len:rate; memset(blk,0,rate); memcpy(blk,in,take);
    int last=(len<rate); if(last){ blk[take]^=0x01; blk[rate-1]^=0x80; }
    for(size_t i=0;i<rate;i++) s[i/8]^=(uint64_t)blk[i]<<(8*(i%8));
    ref_f1600(s); if(last) break; in+=take; len-=take;
  }
  for(int i=0;i<32;i++) out[i]=(uint8_t)(s[i/8]>>(8*(i%8)));
}
// digest of abi.encode(bytes32 seed, uint256 nonce) with nonce=(hi<<64)|lo, as hex (64 chars)
static void ref_pearl_hex(const uint8_t seed[32],uint64_t hi,uint64_t lo,char* hex){
  uint8_t m[64],o[32]; memcpy(m,seed,32); memset(m+32,0,16);
  for(int i=0;i<8;i++){ m[48+i]=(uint8_t)(hi>>(56-8*i)); m[56+i]=(uint8_t)(lo>>(56-8*i)); }
  ref_keccak256(m,64,o); for(int i=0;i<32;i++) sprintf(hex+2*i,"%02x",o[i]);
}
