#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

typedef LRESULT (CALLBACK *HookProc)(int, WPARAM, LPARAM);
typedef void (WINAPI *SetPortProc)(unsigned short);

static BOOL CALLBACK enable_drop(HWND hwnd, LPARAM unused) {
    wchar_t title[256];
    (void)unused;
    GetWindowTextW(hwnd, title, sizeof(title) / sizeof(title[0]));
    if (wcsstr(title, L"ReadDraw") != NULL) DragAcceptFiles(hwnd, TRUE);
    return TRUE;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    wchar_t dll_path[MAX_PATH];
    unsigned int port = 47831;
    HMODULE library;
    HookProc hook_proc;
    SetPortProc set_port;
    HHOOK hook;
    MSG message;
    int argument_count = 0;
    LPWSTR *arguments;
    (void)instance;
    (void)previous;
    (void)show;
    arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (!arguments || argument_count < 2) return 2;
    wcsncpy(dll_path, arguments[1], sizeof(dll_path) / sizeof(dll_path[0]) - 1);
    dll_path[sizeof(dll_path) / sizeof(dll_path[0]) - 1] = L'\0';
    if (argument_count >= 3) swscanf(arguments[2], L"%u", &port);
    LocalFree(arguments);
    library = LoadLibraryW(dll_path);
    if (!library) return 3;
    hook_proc = (HookProc)GetProcAddress(library, "ReadDrawCallWndProc");
    set_port = (SetPortProc)GetProcAddress(library, "ReadDrawSetPort");
    if (!hook_proc) return 4;
    if (set_port) set_port((unsigned short)port);
    hook = SetWindowsHookExW(WH_CALLWNDPROC, hook_proc, library, 0);
    if (!hook) return 5;
    EnumWindows(enable_drop, 0);
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    UnhookWindowsHookEx(hook);
    FreeLibrary(library);
    return 0;
}
