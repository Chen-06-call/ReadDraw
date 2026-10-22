#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static void send_path(const wchar_t *path, unsigned short port) {
    char utf8[65507];
    int size;
    SOCKET sock;
    struct sockaddr_in address;
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return;
    size = WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8, sizeof(utf8), NULL, NULL);
    sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock != INVALID_SOCKET) {
        ZeroMemory(&address, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        InetPtonA(AF_INET, "127.0.0.1", &address.sin_addr);
        if (size > 0) sendto(sock, utf8, size, 0, (struct sockaddr *)&address, sizeof(address));
        closesocket(sock);
    }
    WSACleanup();
}

__declspec(dllexport) LRESULT CALLBACK ReadDrawGetMessageProc(int code, WPARAM wparam, LPARAM lparam) {
    if (code >= 0 && wparam == PM_REMOVE && lparam) {
        MSG *message = (MSG *)lparam;
        unsigned short port = (unsigned short)(UINT_PTR)GetPropW(message->hwnd, L"ReadDrawDropPort");
        if (port && message->message == WM_DROPFILES) {
            HDROP drop = (HDROP)message->wParam;
            UINT count = DragQueryFileW(drop, 0xFFFFFFFF, NULL, 0), index;
            for (index = 0; index < count; index++) {
                wchar_t path[32768];
                if (DragQueryFileW(drop, index, path, 32768)) {
                    const wchar_t *extension = wcsrchr(path, L'.');
                    if (extension && (!_wcsicmp(extension, L".pdf") || !_wcsicmp(extension, L".epub")))
                        send_path(path, port);
                }
            }
            /* Consume once: do not let Flutter free this HDROP again. */
            DragFinish(drop);
            message->message = WM_NULL;
            message->wParam = message->lParam = 0;
        }
    }
    return CallNextHookEx(NULL, code, wparam, lparam);
}
