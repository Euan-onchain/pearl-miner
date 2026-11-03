// Host helpers shared by CUDA and CPU builds.
#pragma once
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <sys/time.h>
#include <unistd.h>
// Synthetic self-test vector (NOT tied to any wallet):
//   seed = keccak256("PEARL_MINER_SELFTEST"); smallest nonce with digest <= 2^240-1 is 127902.
static const char* SELF_SEED="0x046fd124564362d5c7ff15227901849a9b55d286ff4b2c19df32985676ee795c";
static const uint64_t SELF_NONCE=127902ULL;
static const char* SELF_DIGEST="00008b065acc3d587f85b3fe78b27dbe6b2bf6ac5d4791f6bc0f06f208b432f0";
static int hexval(char c){ if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10; if(c>='A'&&c<='F')return c-'A'+10; return -1;}
// parse up to 64 hex digits (right aligned) into 32 bytes big-endian
static int parse_hex32(const char* s, uint8_t out[32]){
  if(s[0]=='0'&&(s[1]=='x'||s[1]=='X')) s+=2;
  size_t n=strlen(s); if(n>64||n==0) return -1;
  memset(out,0,32);
  for(size_t i=0;i<n;i++){ int v=hexval(s[n-1-i]); if(v<0) return -1;
    out[31-i/2] |= (uint8_t)(i%2? v<<4 : v); }
  return 0;
}
static void seed_lanes(const uint8_t b[32], uint64_t L[4]){
  for(int i=0;i<4;i++){ uint64_t x=0; for(int j=7;j>=0;j--) x=(x<<8)|b[i*8+j]; L[i]=x; }
}
static void be_words(const uint8_t b[32], uint64_t W[4]){
  for(int i=0;i<4;i++){ uint64_t x=0; for(int j=0;j<8;j++) x=(x<<8)|b[i*8+j]; W[i]=x; }
}
static void u128_dec(uint64_t hi, uint64_t lo, char* buf){
  unsigned __int128 v=((unsigned __int128)hi<<64)|lo; char t[64]; int n=0;
  if(!v) t[n++]='0'; while(v){ t[n++]='0'+(int)(v%10); v/=10; }
  for(int i=0;i<n;i++) buf[i]=t[n-1-i]; buf[n]=0;
}
static void digest_hex(const uint64_t d[4], char* buf){ sprintf(buf,"%016llx%016llx%016llx%016llx",
  (unsigned long long)d[0],(unsigned long long)d[1],(unsigned long long)d[2],(unsigned long long)d[3]); }
static double now_s(){ struct timeval tv; gettimeofday(&tv,0); return tv.tv_sec+tv.tv_usec*1e-6; }
static uint64_t rand64(){
  uint64_t r=0; FILE* f=fopen("/dev/urandom","rb");
  if(f){ if(fread(&r,8,1,f)!=1) r=0; fclose(f); }
  if(!r) r=((uint64_t)time(0)<<20)^(uint64_t)getpid();
  return r;
}
static int target_bits(const uint64_t T[4]){ int z=0; for(int i=0;i<4;i++){ if(!T[i]){z+=64;continue;} uint64_t x=T[i]; while(!(x>>63)){z++;x<<=1;} break; } return z; }
