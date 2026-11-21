/* Minimal Unicode GUI launcher for the adjacent embedded Windows runtime. */
typedef unsigned short W;
typedef unsigned long DWORD;
typedef void *HANDLE;
typedef struct {
    DWORD cb;
    W *reserved, *desktop, *title;
    DWORD x, y, width, height, xchars, ychars, fill, flags;
    unsigned short show, reserved_len;
    unsigned char *reserved_data;
    HANDLE input, output, error;
} Startup;
typedef struct { HANDLE process, thread; DWORD pid, tid; } Process;
__declspec(dllimport) DWORD GetModuleFileNameW(HANDLE, W *, DWORD);
__declspec(dllimport) int CreateProcessW(const W *, W *, void *, void *, int, DWORD, void *, const W *, Startup *, Process *);
__declspec(dllimport) int CloseHandle(HANDLE);
__declspec(dllimport) void ExitProcess(DWORD);
__declspec(dllimport) int MessageBoxW(HANDLE, const W *, const W *, unsigned int);

static W folder[32768], program[32768], args[32768];
static Startup startup;
static Process child;
static W *append(W *out, const W *text) {
    while (*text) *out++ = *text++;
    *out = 0;
    return out;
}
void start(void) {
    DWORD length = GetModuleFileNameW(0, folder, 32768);
    if (length && length < 32700) {
        while (length && folder[length-1] != L'\\') --length;
        folder[length] = 0;
        append(append(program, folder), L"runtime\\pythonw.exe");
        /* The module is resolved by the embedded runtime. The working directory is fixed
           to the application folder, even when launched through a shortcut. */
        W *end = append(args, L"\"");
        end = append(end, program);
        append(end, L"\" -B -m hoverling");
        startup.cb = sizeof(startup);
        if (CreateProcessW(program, args, 0, 0, 0, 0, 0, folder, &startup, &child)) {
            CloseHandle(child.thread);
            CloseHandle(child.process);
            ExitProcess(0);
        }
    }
    MessageBoxW(0, L"Please extract the entire HoverLing ZIP before starting HoverLing.exe.", L"HoverLing", 0x10);
    ExitProcess(1);
}
