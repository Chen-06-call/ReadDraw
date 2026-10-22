/* Hook only this application's window thread, never unrelated processes. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>
#include <wchar.h>

typedef LRESULT (CALLBACK *HookProc)(int, WPARAM, LPARAM);
static DWORD owner_pid;
static HWND target_window;

static DWORD parent_of(DWORD pid) {
    PROCESSENTRY32 entry = {0};
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    DWORD parent = 0;
    entry.dwSize = sizeof(entry);
    if (snapshot == INVALID_HANDLE_VALUE) return 0;
    if (Process32First(snapshot, &entry)) {
        do {
            if (entry.th32ProcessID == pid) { parent = entry.th32ParentProcessID; break; }
        } while (Process32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return parent;
}

static BOOL CALLBACK find_window(HWND hwnd, LPARAM unused) {
    wchar_t title[256];
    DWORD pid, attempts;
    (void)unused;
    if (!IsWindowVisible(hwnd)) return TRUE;
    GetWindowTextW(hwnd, title, 256);
    if (wcsstr(title, L"ReadDraw") == NULL) return TRUE;
    GetWindowThreadProcessId(hwnd, &pid);
    for (attempts = 0; pid && attempts < 8; attempts++) {
        if (pid == owner_pid) { target_window = hwnd; return FALSE; }
        pid = parent_of(pid);
    }
    return TRUE;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    int count, result = 0;
    unsigned int port;
    LPWSTR *args = CommandLineToArgvW(GetCommandLineW(), &count);
    HMODULE library;
    HookProc callback;
    HHOOK hook = NULL;
    HANDLE owner, input = GetStdHandle(STD_INPUT_HANDLE);
    MSG message;
    (void)instance; (void)previous; (void)command_line; (void)show;
    if (!args || count != 4) return 2;
    port = (unsigned int)wcstoul(args[2], NULL, 10);
    owner_pid = (DWORD)wcstoul(args[3], NULL, 10);
    library = LoadLibraryW(args[1]);
    LocalFree(args);
    if (!library) return 3;
    callback = (HookProc)GetProcAddress(library, "ReadDrawGetMessageProc");
    owner = OpenProcess(SYNCHRONIZE, FALSE, owner_pid);
    if (!callback || !owner) { FreeLibrary(library); return 4; }
    while (WaitForSingleObject(owner, 0) == WAIT_TIMEOUT) {
        DWORD available = 0;
        /* Closing stdin signals graceful stop, also on abnormal parent exit. */
        if (!PeekNamedPipe(input, NULL, 0, NULL, &available, NULL) || available) break;
        if (!hook) {
            EnumWindows(find_window, 0);
            if (target_window) {
                DWORD thread_id = GetWindowThreadProcessId(target_window, NULL);
                SetPropW(target_window, L"ReadDrawDropPort", (HANDLE)(UINT_PTR)port);
                hook = SetWindowsHookExW(WH_GETMESSAGE, callback, library, thread_id);
                if (!hook) { result = 5; break; }
                DragAcceptFiles(target_window, TRUE);
                PostMessageW(target_window, WM_NULL, 0, 0);
            }
        } else if (!IsWindow(target_window)) {
            break;
        }
        MsgWaitForMultipleObjects(1, &owner, FALSE, 100, QS_ALLINPUT);
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            if (message.message == WM_QUIT) goto cleanup;
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
cleanup:
    if (target_window && IsWindow(target_window)) {
        DragAcceptFiles(target_window, FALSE);
        RemovePropW(target_window, L"ReadDrawDropPort");
    }
    if (hook) UnhookWindowsHookEx(hook);
    CloseHandle(owner);
    FreeLibrary(library);
    return result;
}
