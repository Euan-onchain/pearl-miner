// CPU fallback miner (multi-threaded, pthreads). Same keccak core as the GPU build.
// Finds nonce with uint256(keccak256(abi.encode(bytes32 seed, uint256 nonce))) <= target.
// Pure computation: no keys, no network.
#include "keccak_core.h"
#include "common_host.h"
#include "ref_keccak.h"
#include <pthread.h>
#include <signal.h>

static uint64_t g_L[4], g_T[4], g_hi; static uint8_t g_sb[32];
static volatile int g_stop=0; static long long g_count=0, g_found=0;
static FILE* g_fo; static pthread_mutex_t g_mu=PTHREAD_MUTEX_INITIALIZER;
static int g_threads=1; static volatile uint64_t g_hashes=0;
static void onsig(int s){ (void)s; g_stop=1; }

static void* worker(void* arg){
  uint64_t tid=(uint64_t)(uintptr_t)arg, n=0;
  for(uint64_t lo=tid; !g_stop; lo+=g_threads){
    uint64_t d[4]; pearl_hash(g_L,g_hi,lo,d);
    if(le_target(d,g_T)){
      char nd[64],h[80],rh[80]; u128_dec(g_hi,lo,nd); digest_hex(d,h); ref_pearl_hex(g_sb,g_hi,lo,rh);
      if(strcmp(h,rh)){ printf("DROP nonce=%s (reference mismatch)\n",nd); continue; }
      pthread_mutex_lock(&g_mu);
      if(!g_count || g_found<g_count){ fprintf(g_fo,"%s,0x%s\n",nd,h); fflush(g_fo); g_found++;
        printf("FOUND #%lld nonce=%s digest=0x%s\n",g_found,nd,h); fflush(stdout); }
      if(g_count && g_found>=g_count) g_stop=1;
      pthread_mutex_unlock(&g_mu);
    }
    if(++n==1<<20){ __sync_fetch_and_add(&g_hashes,n); n=0; }
  }
  return 0;
}
static int selftest(void){
  uint8_t s0[32]; parse_hex32(SELF_SEED,s0); uint64_t L0[4],d[4]; char h[80],r[80];
  seed_lanes(s0,L0); pearl_hash(L0,0,SELF_NONCE,d); digest_hex(d,h); ref_pearl_hex(s0,0,SELF_NONCE,r);
  int ok=!strcmp(h,SELF_DIGEST)&&!strcmp(r,SELF_DIGEST);
  uint64_t T16[4]={0x0000FFFFFFFFFFFFULL,~0ULL,~0ULL,~0ULL}, mn=~0ULL;
  for(uint64_t lo=0;lo<=SELF_NONCE;lo++){ pearl_hash(L0,0,lo,d); if(le_target(d,T16)){ mn=lo; break; } }
  ok=ok&&(mn==SELF_NONCE);
  printf("[selftest] cpu core vs reference + search: %s\n",ok?"OK":"FAIL"); return ok?0:1;
}
static void usage(const char* p){
  fprintf(stderr,"usage: %s --seed 0x.. --target 0x.. [--threads N] [--count N] [--out f] [--hi N] [--selftest] [--force]\n",p);
}
int main(int argc,char**argv){
  const char *seed=NULL,*tgt=NULL,*out="nonces_cpu.txt"; int st=0,force=0,have_hi=0;
  g_threads=(int)sysconf(_SC_NPROCESSORS_ONLN); if(g_threads<1) g_threads=1;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"--seed")&&i+1<argc) seed=argv[++i];
    else if(!strcmp(argv[i],"--target")&&i+1<argc) tgt=argv[++i];
    else if(!strcmp(argv[i],"--threads")&&i+1<argc) g_threads=atoi(argv[++i]);
    else if(!strcmp(argv[i],"--count")&&i+1<argc) g_count=atoll(argv[++i]);
    else if(!strcmp(argv[i],"--out")&&i+1<argc) out=argv[++i];
    else if(!strcmp(argv[i],"--hi")&&i+1<argc){ g_hi=strtoull(argv[++i],0,0); have_hi=1; }
    else if(!strcmp(argv[i],"--selftest")) st=1;
    else if(!strcmp(argv[i],"--force")) force=1;
    else { usage(argv[0]); return 1; }
  }
  if(selftest()) return 3; if(st) return 0;
  if(!seed||!tgt){ usage(argv[0]); fprintf(stderr,"--seed and --target are required (run fetch_challenge.py)\n"); return 1; }
  uint8_t tb[32]; if(parse_hex32(seed,g_sb)||parse_hex32(tgt,tb)){ fprintf(stderr,"bad hex\n"); return 1; }
  seed_lanes(g_sb,g_L); be_words(tb,g_T);
  int zb=target_bits(g_T); if(zb<30&&!force){ fprintf(stderr,"ERROR: target has only %d leading zero bits (<30). Use --force.\n",zb); return 1; }
  if(!have_hi) g_hi=0xFF00000000000000ULL|(rand64()&0x00FFFFFFFFFFFFFFULL); // CPU uses device id 0xFF
  g_fo=fopen(out,"a"); if(!g_fo){ perror(out); return 1; }
  signal(SIGINT,onsig); signal(SIGTERM,onsig);
  printf("CPU threads=%d nonce_hi=0x%016llx target_zero_bits=%d out=%s\n",g_threads,(unsigned long long)g_hi,zb,out); fflush(stdout);
  pthread_t* th=malloc(sizeof(pthread_t)*g_threads);
  for(int i=0;i<g_threads;i++) pthread_create(&th[i],0,worker,(void*)(uintptr_t)i);
  double t0=now_s();
  while(!g_stop){ sleep(1); static int k=0; if(++k%10==0){ double el=now_s()-t0;
    printf("[cpu] %.2f MH/s found=%lld\n",g_hashes/el/1e6,g_found); fflush(stdout);} }
  for(int i=0;i<g_threads;i++) pthread_join(th[i],0);
  fclose(g_fo); printf("stopped. found=%lld\n",g_found); return 0;
}
