// Pearl PoW offline GPU miner: finds nonce with keccak256(abi.encode(seed,nonce)) <= target.
// No keys, no network, no transactions.
#include "keccak_core.h"
#include "common_host.h"
#include "ref_keccak.h"
#include <cuda_runtime.h>
#include <signal.h>

__constant__ uint64_t c_seed[4];
__constant__ uint64_t c_tgt[4];
#define MAXRES 1024
struct Res { unsigned int n; uint64_t lo[MAXRES]; };

__global__ void __launch_bounds__(256) mine_kernel(uint64_t hi, uint64_t base, uint32_t iters, Res* res){
  uint64_t tid=(uint64_t)blockIdx.x*blockDim.x+threadIdx.x;
  uint64_t stride=(uint64_t)gridDim.x*blockDim.x;
  uint64_t s[4]={c_seed[0],c_seed[1],c_seed[2],c_seed[3]};
  uint64_t t[4]={c_tgt[0],c_tgt[1],c_tgt[2],c_tgt[3]};
  for(uint32_t k=0;k<iters;k++){
    uint64_t lo=base+tid+(uint64_t)k*stride;
    uint64_t d[4];
    pearl_hash(s,hi,lo,d);
    if(d[0]<=t[0] && le_target(d,t)){
      unsigned int i=atomicAdd(&res->n,1u);
      if(i<MAXRES) res->lo[i]=lo;
    }
  }
}
#define CK(x) do{cudaError_t e=(x); if(e!=cudaSuccess){fprintf(stderr,"CUDA error %s @%d: %s\n",#x,__LINE__,cudaGetErrorString(e)); exit(2);} }while(0)
static volatile int g_stop=0; static void onsig(int){ g_stop=1; }

__global__ void hash_kernel(const uint64_t* hi,const uint64_t* lo,int n,uint64_t* out){
  int i=blockIdx.x*blockDim.x+threadIdx.x; if(i>=n) return;
  uint64_t s[4]={c_seed[0],c_seed[1],c_seed[2],c_seed[3]}; uint64_t d[4]; pearl_hash(s,hi[i],lo[i],d);
  out[4*i]=d[0];out[4*i+1]=d[1];out[4*i+2]=d[2];out[4*i+3]=d[3];
}
static uint64_t xs=0x9E3779B97F4A7C15ULL; static uint64_t xr(){ xs^=xs<<13; xs^=xs>>7; xs^=xs<<17; return xs; }
// Strong selftest: GPU digests of many arbitrary 128-bit nonces vs independent host reference keccak, plus search test.
static int selftest(int dev,const char* seedhex,const uint64_t T[4]){
  uint8_t sb[32]; if(parse_hex32(seedhex,sb)) return 1; uint64_t L[4]; seed_lanes(sb,L);
  char h[80],r[80]; int bad=0;
  { uint8_t s0[32]; parse_hex32(SELF_SEED,s0); ref_pearl_hex(s0,0,SELF_NONCE,r);
    uint64_t L0[4],d[4]; seed_lanes(s0,L0); pearl_hash(L0,0,SELF_NONCE,d); digest_hex(d,h);
    int ok=!strcmp(h,SELF_DIGEST)&&!strcmp(r,SELF_DIGEST);
    printf("[selftest] host core+ref vector %s\n",ok?"OK":"FAIL"); if(!ok) return 1; }
  CK(cudaSetDevice(dev)); CK(cudaMemcpyToSymbol(c_seed,L,32)); CK(cudaMemcpyToSymbol(c_tgt,T,32));
  const int N=1<<16; uint64_t *H,*Lo,*O;
  CK(cudaMallocManaged(&H,N*8)); CK(cudaMallocManaged(&Lo,N*8)); CK(cudaMallocManaged(&O,N*32));
  for(int i=0;i<N;i++){
    switch(i%8){
      case 0: H[i]=0; Lo[i]=i; break;                              // small
      case 1: H[i]=xr(); Lo[i]=~0ULL-(i&255); break;               // near lo wrap
      case 2: H[i]=xr(); Lo[i]=xr(); break;                        // random 128-bit
      case 3: H[i]=((uint64_t)(i&1)<<56)|(xr()&0x00FFFFFFFFFFFFFFULL); Lo[i]=xr()&0xFFFFFFFFFFULL; break; // like mining
      case 4: H[i]=~0ULL; Lo[i]=~0ULL-(i&7); break;                // all ones
      case 5: H[i]=1ULL<<(i%64); Lo[i]=1ULL<<((i/8)%64); break;    // single bits
      case 6: H[i]=xr(); Lo[i]=(xr()&0xFFFFFFFFULL)<<32 | 0xFFFFFFFFULL; break; // 32-bit carry boundary
      default: H[i]=xr()>>((i/8)%64); Lo[i]=xr()>>((i/16)%64);
    }
  }
  hash_kernel<<<(N+255)/256,256>>>(H,Lo,N,O); CK(cudaGetLastError()); CK(cudaDeviceSynchronize());
  for(int i=0;i<N;i++){ digest_hex(O+4*i,h); ref_pearl_hex(sb,H[i],Lo[i],r);
    if(strcmp(h,r)){ if(bad<5){ char nd[64]; u128_dec(H[i],Lo[i],nd); printf("[selftest] MISMATCH nonce=%s gpu=%s ref=%s\n",nd,h,r);} bad++; } }
  printf("[selftest] gpu%d %d arbitrary nonces vs reference keccak: %d mismatches %s\n",dev,N,bad,bad?"FAIL":"OK");
  cudaFree(H);cudaFree(Lo);cudaFree(O);
  // search path test on the synthetic self seed: target 2^240-1 must find SELF_NONCE as minimum hit
  uint8_t s0[32]; parse_hex32(SELF_SEED,s0); uint64_t L0[4]; seed_lanes(s0,L0);
  uint64_t T16[4]={0x0000FFFFFFFFFFFFULL,~0ULL,~0ULL,~0ULL};
  CK(cudaMemcpyToSymbol(c_seed,L0,32)); CK(cudaMemcpyToSymbol(c_tgt,T16,32));
  Res* rr; CK(cudaMallocManaged(&rr,sizeof(Res))); rr->n=0;
  mine_kernel<<<64,256>>>(0,0,(uint32_t)(SELF_NONCE/(64*256)+1),rr); CK(cudaGetLastError()); CK(cudaDeviceSynchronize());
  uint64_t mn=~0ULL; for(unsigned i=0;i<rr->n&&i<MAXRES;i++) if(rr->lo[i]<mn) mn=rr->lo[i];
  printf("[selftest] gpu%d search: %u hits, min nonce=%llu %s\n",dev,rr->n,(unsigned long long)mn,mn==SELF_NONCE?"OK":"FAIL");
  int ok=(mn==SELF_NONCE)&&!bad; cudaFree(rr);
  CK(cudaMemcpyToSymbol(c_seed,L,32)); CK(cudaMemcpyToSymbol(c_tgt,T,32));
  return ok?0:1;
}

int main(int argc,char**argv){
  const char *seed=NULL,*tgt=NULL,*out="nonces.txt";
  int dev=0; long long count=0; int st=0; int force=0; uint64_t start=0; int have_start=0;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"--seed")&&i+1<argc) seed=argv[++i];
    else if(!strcmp(argv[i],"--target")&&i+1<argc) tgt=argv[++i];
    else if(!strcmp(argv[i],"--device")&&i+1<argc) dev=atoi(argv[++i]);
    else if(!strcmp(argv[i],"--count")&&i+1<argc) count=atoll(argv[++i]);
    else if(!strcmp(argv[i],"--out")&&i+1<argc) out=argv[++i];
    else if(!strcmp(argv[i],"--start")&&i+1<argc){ start=strtoull(argv[++i],0,0); have_start=1; }
    else if(!strcmp(argv[i],"--selftest")) st=1;
    else if(!strcmp(argv[i],"--force")) force=1;
    else { fprintf(stderr,"usage: %s --seed 0x.. [--target 0x..] [--device N] [--count N] [--out f] [--selftest]\n",argv[0]); return 1; }
  }
  if(!seed) seed=st?SELF_SEED:NULL;
  if(!tgt) tgt=st?"0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff":NULL;
  if(!seed||!tgt){ fprintf(stderr,"--seed and --target required (run fetch_challenge.py)\n"); return 1; }
  uint8_t sb[32],tb[32]; if(parse_hex32(seed,sb)||parse_hex32(tgt,tb)){ fprintf(stderr,"bad hex\n"); return 1; }
  uint64_t L[4],T[4]; seed_lanes(sb,L); be_words(tb,T);
  { int zb=target_bits(T); printf("target=%s  (leading zero bits=%d; contract stage0 = 2^226-1 = 30 zero bits)\n",tgt,zb);
    if(zb<30 && !force && !st){ fprintf(stderr,"ERROR: target looser than contract max 2^226-1 (only %d zero bits). Use --force to override.\n",zb); return 1; } }
  if(selftest(dev,seed,T)){ fprintf(stderr,"SELFTEST FAILED - refusing to mine\n"); return 3; }
  if(st) return 0;
  CK(cudaSetDevice(dev));
  cudaDeviceProp p; CK(cudaGetDeviceProperties(&p,dev));
  // nonce = hi<<64 | lo ; hi = (device id <<56) | random 56 bits  => disjoint per GPU and per run
  uint64_t hi=((uint64_t)(dev&0xff)<<56)|(rand64()&0x00FFFFFFFFFFFFFFULL);
  uint64_t base=have_start?start:0;
  CK(cudaMemcpyToSymbol(c_seed,L,32)); CK(cudaMemcpyToSymbol(c_tgt,T,32));
  Res* r; CK(cudaMallocManaged(&r,sizeof(Res))); r->n=0;
  int blocks=p.multiProcessorCount*16; uint32_t iters=64;
  uint64_t per=(uint64_t)blocks*256*iters;
  FILE* fo=fopen(out,"a"); if(!fo){perror(out);return 1;}
  signal(SIGINT,onsig); signal(SIGTERM,onsig);
  printf("GPU%d %s SMs=%d  nonce_hi=0x%016llx  batch=%llu  out=%s\n",dev,p.name,p.multiProcessorCount,
         (unsigned long long)hi,(unsigned long long)per,out); fflush(stdout);
  double t0=now_s(),tl=t0; uint64_t done=0,last=0; long long found=0;
  while(!g_stop){
    r->n=0;
    mine_kernel<<<blocks,256>>>(hi,base,iters,r); CK(cudaGetLastError()); CK(cudaDeviceSynchronize());
    unsigned n=r->n; if(n>MAXRES) n=MAXRES;
    for(unsigned i=0;i<n;i++){
      uint64_t d[4]; char nd[64],h[80],rh[80]; pearl_hash(L,hi,r->lo[i],d);
      u128_dec(hi,r->lo[i],nd); digest_hex(d,h); ref_pearl_hex(sb,hi,r->lo[i],rh);
      uint8_t rb[32]; parse_hex32(rh,rb); uint64_t rw[4]; be_words(rb,rw);
      if(strcmp(h,rh)||!le_target(rw,T)){ printf("DROP nonce=%s core=%s ref=%s (fails reference re-verify)\n",nd,h,rh); fflush(stdout); continue; }
      fprintf(fo,"%s,0x%s\n",nd,h); fflush(fo); found++;
      printf("FOUND #%lld nonce=%s digest=0x%s\n",found,nd,h); fflush(stdout);
      if(count&&found>=count) g_stop=1;
    }
    base+=per; done+=per;
    if(base<per){ hi=(hi&0xFF00000000000000ULL)|(rand64()&0x00FFFFFFFFFFFFFFULL); } // wrapped: new range
    double tn=now_s();
    if(tn-tl>=10){ printf("[gpu%d] %.2f GH/s (avg %.2f)  found=%lld  hashes=%.3e\n",dev,(done-last)/(tn-tl)/1e9,
       done/(tn-t0)/1e9,found,(double)done); fflush(stdout); tl=tn; last=done; }
  }
  fclose(fo); printf("stopped. found=%lld\n",found); return 0;
}
