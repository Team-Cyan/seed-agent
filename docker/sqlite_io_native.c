#define _GNU_SOURCE
#include <errno.h>
#include <dlfcn.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define CAPACITY 64u
#define MAX_MESSAGE 512u
/* state: empty=0, exclusively writing=1, published=2, exclusively reading=3. */
typedef struct {
    uint64_t sequence, monotonic_ns;
    uint32_t tid, sqlite_code;
    int32_t os_errno, unix_line;
    uint32_t syscall_kind, target_kind, flags;
} Record;
typedef struct { _Atomic unsigned state; Record value; } Slot;
static Slot slots[CAPACITY];
static _Atomic uint64_t next_sequence = 1, dropped = 0;
#define MAX_DB_PATH 256u
static char configured_db[MAX_DB_PATH+1u];
static size_t configured_length=0, configured_parent_length=0;
static _Atomic unsigned path_state=0;

/* Startup only. The bytes remain immutable for the rest of the process. */
int configure_db_path(const char *path) {
    if (!path || path[0]!='/') return -1;
    size_t length=0, parent=0;
    while (length<=MAX_DB_PATH && path[length]) {
        unsigned char c=(unsigned char)path[length];
        if(c<32u || c==127u || c=='(' || c==')' || c=='\\' || c=='\"' || c=='\'' || c==',') return -1;
        if(c=='/')parent=length;
        length++;
    }
    if(length<2u || length>MAX_DB_PATH || path[length-1u]=='/')return -1;
    unsigned state=atomic_load_explicit(&path_state,memory_order_acquire);
    if(state==1u)return length==configured_length && memcmp(path,configured_db,length)==0 ? 0 : -2;
    unsigned expected=0u;
    if(!atomic_compare_exchange_strong_explicit(&path_state,&expected,2u,memory_order_acquire,memory_order_relaxed))return -3;
    memcpy(configured_db,path,length);configured_db[length]=0;configured_length=length;configured_parent_length=parent?parent:1u;
    atomic_store_explicit(&path_state,1u,memory_order_release);return 0;
}


static int decimal(const char *s, size_t n, size_t *position, unsigned maximum) {
    unsigned value=0; size_t begin=*position;
    while (*position<n && s[*position]>='0' && s[*position]<='9') {
        unsigned digit=(unsigned)(s[*position]-'0');
        if (value>(maximum-digit)/10u) return -1;
        value=value*10u+digit; (*position)++;
    }
    return *position==begin ? -1 : (int)value;
}
static void parse_message(Record *r, const char *s, size_t n) {
    if (n<10u || memcmp(s,"os_unix.c:",10)!=0) return;
    size_t position=10u;
    int line=decimal(s,n,&position,1000000u);
    if (line<0 || position+3u>n || s[position++]!=':' || s[position++]!=' ' || s[position++]!='(') return;
    int number=decimal(s,n,&position,4095u);
    if (number<0 || position+2u>n || s[position++]!=')' || s[position++]!=' ') return;
    size_t start=position;
    while (position<n && ((s[position]>='a'&&s[position]<='z') || (s[position]>='A'&&s[position]<='Z') || s[position]=='_' || (s[position]>='0'&&s[position]<='9'))) position++;
    if (position>=n || s[position]!='(' || position-start>31u) return;
    static const char *names[]={"open","lstat","access","fstat","fcntl","close","unlink","readlink","mmap","fsync","ftruncate","stat","openat"};
    static const unsigned sizes[]={4,5,6,5,5,5,6,8,4,5,9,4,6};
    for (unsigned i=0;i<13u;i++) if (position-start==sizes[i] && memcmp(s+start,names[i],sizes[i])==0) r->syscall_kind=i+1u;
    r->os_errno=number; r->unix_line=line; r->flags|=1u;
    /* Only the first unquoted path argument of a known native syscall counts. */
    if(!r->syscall_kind || (r->flags&2u) || atomic_load_explicit(&path_state,memory_order_acquire)!=1u)return;
    size_t path_start=position+1u, path_end=path_start;
    while(path_end<n && s[path_end]!=')'){
        unsigned char c=(unsigned char)s[path_end];
        if(c<32u || c==127u || c=='(' || c=='\\' || c=='\"' || c=='\'' || c==',')return;
        path_end++;
    }
    if(path_end+4u>n || memcmp(s+path_end,") - ",4)!=0)return;
    for(size_t i=path_end+4u;i<n;i++)if(s[i]=='(' || s[i]==')')return;
    size_t path_length=path_end-path_start;
    if(path_length==configured_length && memcmp(s+path_start,configured_db,configured_length)==0)r->target_kind=1u;
    else if(path_length==configured_length+4u && memcmp(s+path_start,configured_db,configured_length)==0){
        if(memcmp(s+path_start+configured_length,"-wal",4)==0)r->target_kind=2u;
        if(memcmp(s+path_start+configured_length,"-shm",4)==0)r->target_kind=3u;
    }else if(path_length==configured_parent_length && memcmp(s+path_start,configured_db,configured_parent_length)==0)r->target_kind=4u;
}

/* SQLite calls this directly: no Python, SQLite call, logger, mutex or heap use. */
void capture(void *unused, int code, const char *message) {
    (void)unused; int saved_errno=errno;
    unsigned primary=(unsigned)code&255u;
    if (!message || (primary!=14u && primary!=10u && primary!=8u && primary!=13u)) { errno=saved_errno; return; }
    uint64_t sequence=atomic_fetch_add_explicit(&next_sequence,1,memory_order_relaxed);
    Slot *chosen=NULL;
    for (unsigned attempt=0; attempt<CAPACITY; attempt++) {
        Slot *slot=&slots[(sequence+attempt)%CAPACITY]; unsigned expected=0;
        if (atomic_compare_exchange_strong_explicit(&slot->state,&expected,1,memory_order_acquire,memory_order_relaxed)) { chosen=slot; break; }
    }
    if (!chosen) { atomic_fetch_add_explicit(&dropped,1,memory_order_relaxed); errno=saved_errno; return; }
    Record value={0}; value.sequence=sequence; value.tid=(uint32_t)syscall(SYS_gettid); value.sqlite_code=(uint32_t)code; value.os_errno=-1;
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC,&now)==0) value.monotonic_ns=(uint64_t)now.tv_sec*1000000000u+(uint64_t)now.tv_nsec;
    size_t length=0; while(length<MAX_MESSAGE && message[length]) length++;
    if (length==MAX_MESSAGE) value.flags|=2u;
    parse_message(&value,message,length);
    chosen->value=value;
    atomic_store_explicit(&chosen->state,2,memory_order_release);
    errno=saved_errno;
}

/* Concurrent readers acquire a published slot before copying it; no half rows. */
size_t drain(Record *output, size_t maximum) {
    size_t count=0; if (!output) return 0;
    for (unsigned i=0;i<CAPACITY && count<maximum;i++) {
        unsigned expected=2;
        if (!atomic_compare_exchange_strong_explicit(&slots[i].state,&expected,3,memory_order_acquire,memory_order_relaxed)) continue;
        output[count++]=slots[i].value;
        atomic_store_explicit(&slots[i].state,0,memory_order_release);
    }
    return count;
}
uint64_t sequence_mark(void) { return atomic_load_explicit(&next_sequence,memory_order_acquire); }
uint64_t dropped_count(void) { return atomic_load_explicit(&dropped,memory_order_acquire); }
size_t record_size(void) { return sizeof(Record); }
int lock_free(void) { return atomic_is_lock_free(&next_sequence) && atomic_is_lock_free(&dropped) && atomic_is_lock_free(&slots[0].state); }

#ifdef POC
/* Test-only: callers must have joined every writer/reader before reset. */
void reset_for_test(void) {
    for(unsigned i=0;i<CAPACITY;i++) atomic_store_explicit(&slots[i].state,0,memory_order_relaxed);
    atomic_store_explicit(&next_sequence,1,memory_order_relaxed); atomic_store_explicit(&dropped,0,memory_order_relaxed);
}
int preserves_errno_for_test(const char *message) { errno=EDOM; capture(NULL,14,message); return errno==EDOM; }
#endif

#ifndef EXPECTED_SQLITE_SOURCE_ID
#define EXPECTED_SQLITE_SOURCE_ID ""
#endif
const char *expected_source_id(void) { return EXPECTED_SQLITE_SOURCE_ID; }
unsigned capture_abi(void) { return 1u; }
int same_provider(void *config, void *source, void *version) {
    Dl_info a, b, c;
    return dladdr(config, &a) && dladdr(source, &b) && dladdr(version, &c)
        && a.dli_fbase == b.dli_fbase && a.dli_fbase == c.dli_fbase;
}
