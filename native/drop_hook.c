#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <wchar.h>

static unsigned short g_port = 47831;
static int g_wsa_ready = 0;

static void send_path(const wchar_t *path) {
    char utf8[32768];
    int size;
    SOCKET sock;
    struct sockaddr_in address;
    WSADATA wsa;
    if (!g_wsa_ready) {
        if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return;
        g_wsa_ready = 1;
    }
    size = WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8, sizeof(utf8), NULL, NULL);
    if (size <= 0) return;
    sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock == INVALID_SOCKET) return;
    ZeroMemory(&address, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(g_port);
    InetPtonA(AF_INET, "127.0.0.1", &address.sin_addr);
    sendto(sock, utf8, size, 0, (struct sockaddr *)&address, sizeof(address));
    closesocket(sock);
}

static int is_read_draw_window(HWND hwnd) {
    wchar_t title[256];
    GetWindowTextW(hwnd, title, sizeof(title) / sizeof(title[0]));
    return wcsstr(title, L"ReadDraw") != NULL;
}

__declspec(dllexport) LRESULT CALLBACK ReadDrawCallWndProc(int code, WPARAM wparam, LPARAM lparam) {
    if (code >= 0 && lparam) {
        CWPSTRUCT *message = (CWPSTRUCT *)lparam;
        if (message->message == WM_CREATE || message->message == WM_DROPFILES) {
            if (is_read_draw_window(message->hwnd)) {
                DragAcceptFiles(message->hwnd, TRUE);
                if (message->message == WM_DROPFILES) {
                    HDROP drop = (HDROP)message->wParam;
                    UINT count = DragQueryFileW(drop, 0xFFFFFFFF, NULL, 0);
                    UINT index;
                    for (index = 0; index < count; index++) {
                        wchar_t path[32768];
                        UINT length = DragQueryFileW(drop, index, path, sizeof(path) / sizeof(path[0]));
                        if (length > 0) {
                            const wchar_t *extension = wcsrchr(path, L'.');
                            if (extension && (_wcsicmp(extension, L".pdf") == 0 || _wcsicmp(extension, L".epub") == 0)) {
                                send_path(path);
                            }
                        }
                    }
                    DragFinish(drop);
                }
            }
        }
    }
    return CallNextHookEx(NULL, code, wparam, lparam);
}

__declspec(dllexport) void ReadDrawSetPort(unsigned short port) {
    if (port) g_port = port;
}
