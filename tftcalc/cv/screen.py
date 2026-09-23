"""화면 캡처 (표준 라이브러리 + ctypes 만 사용).

왜 의존성 없이 하는가
-------------------
이 프로젝트는 지금까지 외부 패키지 0개로 동작한다(PIL/numpy/cv2 없음).
오버레이 도구는 배포/유지가 쉬워야 하고, `pip install` 없이 바로 돌아가는 것이 실전에서 크다.
Windows GDI(ctypes)로 화면을 그대로 복사하고, BMP 입출력은 직접 구현한다.

지원
----
* 전체 화면 캡처(1920x1080 기준 좌표계)
* 특정 창 제목으로 창 영역 캡처(테두리 없이 겹쳐 놓았을 때 유용)
* BMP 저장/로드(디버그용 + 테스트용 오프라인 입력)
"""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
_gdi32 = ctypes.windll.gdi32 if hasattr(ctypes, "windll") else None


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def is_supported() -> bool:
    """이 플랫폼에서 캡처가 가능한가(Windows + GDI)."""
    return _user32 is not None and _gdi32 is not None


@dataclass
class Image:
    """BGRA 픽셀 버퍼(위->아래 순서). 값은 0~255 정수."""

    width: int
    height: int
    pixels: bytearray

    def __post_init__(self) -> None:
        expected = self.width * self.height * 4
        if len(self.pixels) != expected:
            raise ValueError(
                f"픽셀 버퍼 크기 불일치: {len(self.pixels)} != {expected}"
            )

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        """(R, G, B) 반환."""
        offset = (y * self.width + x) * 4
        blue, green, red = self.pixels[offset], self.pixels[offset + 1], self.pixels[offset + 2]
        return red, green, blue

    def gray(self, x: int, y: int) -> float:
        red, green, blue = self.pixel(x, y)
        return 0.299 * red + 0.587 * green + 0.114 * blue

    def crop(self, x: int, y: int, width: int, height: int) -> "Image":
        """하위 영역을 잘라 새 Image 로 반환(화면 밖은 0으로 채움)."""
        buffer = bytearray(width * height * 4)
        for row in range(height):
            source_y = y + row
            if source_y < 0 or source_y >= self.height:
                continue
            for column in range(width):
                source_x = x + column
                if source_x < 0 or source_x >= self.width:
                    continue
                source_offset = (source_y * self.width + source_x) * 4
                target_offset = (row * width + column) * 4
                buffer[target_offset : target_offset + 4] = self.pixels[
                    source_offset : source_offset + 4
                ]
        return Image(width=width, height=height, pixels=buffer)

    def variance(self) -> float:
        """단순 분산(캡처가 검은 화면인지 확인용)."""
        step = max(1, self.width // 64)
        step_y = max(1, self.height // 36)
        values = [
            self.gray(x, y)
            for y in range(0, self.height, step_y)
            for x in range(0, self.width, step)
        ]
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / len(values)


def capture(
    x: int = 0, y: int = 0, width: int | None = None, height: int | None = None
) -> Image:
    """화면(또는 지정 영역)을 캡처한다. width/height 생략 시 전체 화면."""
    if not is_supported():
        raise RuntimeError("화면 캡처는 Windows(GDI)에서만 지원됩니다.")
    _user32.SetProcessDPIAware()
    if width is None:
        width = _user32.GetSystemMetrics(0)
    if height is None:
        height = _user32.GetSystemMetrics(1)

    screen_dc = _user32.GetDC(0)
    memory_dc = _gdi32.CreateCompatibleDC(screen_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    _gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not _gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY):
            raise RuntimeError("BitBlt 실패(화면 캡처 권한을 확인하세요).")
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # 음수 = 위->아래 순서
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB
        buffer = (ctypes.c_char * (width * height * 4))()
        copied = _gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
        )
        if copied == 0:
            raise RuntimeError("GetDIBits 실패.")
        return Image(width=width, height=height, pixels=bytearray(buffer))
    finally:
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memory_dc)
        _user32.ReleaseDC(0, screen_dc)


def _title_score(window_title: str, wanted: str) -> int:
    """창 제목 매칭 점수(높을수록 좋음). 0 이면 불일치.

    ``FindWindowW`` 는 제목이 **정확히** 같아야 하는데, 실제 TFT 창 제목은 뒤에 공백이
    붙어 있다(실측: ``'TFT  '``). 그래서 정확 일치를 우선하되 공백/대소문자 차이와
    부분 일치까지 허용한다.

    * 3 = 정확 일치
    * 2 = 양끝 공백 제거 후 일치(대소문자 무시)
    * 1 = 부분 일치(대소문자 무시)
    """
    if not wanted:
        return 0
    if window_title == wanted:
        return 3
    left, right = window_title.strip().casefold(), wanted.strip().casefold()
    if left == right:
        return 2
    if right and right in left:
        return 1
    return 0


def _find_handle(title: str) -> int | None:
    """제목이 가장 잘 맞는 최상위 창 핸들(없으면 None)."""
    if not is_supported():
        return None
    best_score = 0
    best_handle = 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(handle, _param):
        nonlocal best_score, best_handle
        length = _user32.GetWindowTextLengthW(handle)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(handle, buffer, length + 1)
            score = _title_score(buffer.value, title)
            if score > best_score:
                best_score, best_handle = score, handle
        return True

    _user32.EnumWindows(callback_type(visit), 0)
    return best_handle or None


def find_window(title: str) -> tuple[int, int, int, int] | None:
    """창 제목으로 (x, y, width, height) 를 찾는다. 없으면 None.

    제목은 정확 일치를 우선하되, 뒤 공백/대소문자 차이와 부분 일치도 받아준다
    (``_title_score``). 창 전체(타이틀바·테두리 포함) 크기다.
    """
    if not is_supported():
        return None
    handle = _find_handle(title)
    if not handle:
        return None
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(handle, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def capture_window(title: str) -> Image | None:
    """창 제목으로 그 창 영역만 캡처(없으면 None)."""
    rect = find_window(title)
    if rect is None:
        return None
    x, y, width, height = rect
    return capture(x, y, width, height)


def find_client(title: str) -> tuple[int, int, int, int] | None:
    """창 제목으로 **클라이언트 영역**(타이틀바·테두리 제외)을 찾는다. 없으면 None.

    왜 창 전체가 아니라 클라이언트인가: 비율 좌표(``cv/layout.py``)는 게임 화면(=클라이언트)
    기준으로 만든 값이다. 창모드에서 창 전체를 캡처하면 타이틀바·테두리 두께만큼
    좌표가 위/왼쪽으로 밀려 상점·벤치 칸이 어긋난다(실측: 타이틀바 31px).
    """
    if not is_supported():
        return None
    handle = _find_handle(title)
    if not handle:
        return None
    rect = wintypes.RECT()
    if not _user32.GetClientRect(handle, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(handle, ctypes.byref(origin)):
        return None
    return (origin.x, origin.y, rect.right, rect.bottom)


def capture_client(title: str) -> Image | None:
    """창 제목으로 그 창의 클라이언트 영역만 캡처(없으면 None).

    창모드(``TFT`` 등)에서 비율 좌표를 그대로 쓰려면 이 함수를 쓴다.
    """
    rect = find_client(title)
    if rect is None:
        return None
    x, y, width, height = rect
    if width <= 0 or height <= 0:
        return None
    return capture(x, y, width, height)


def save_bmp(image: Image, path: str) -> None:
    """32비트 BMP(위->아래)로 저장한다. 디버그/공유용."""
    header = struct.pack("<2sIHHI", b"BM", 14 + 40 + len(image.pixels), 0, 0, 14 + 40)
    info = struct.pack(
        "<IiiHHIIiiII",
        40,
        image.width,
        -image.height,  # 음수 = 위->아래
        1,
        32,
        0,
        len(image.pixels),
        2835,
        2835,
        0,
        0,
    )
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(info)
        handle.write(image.pixels)


def load_bmp(path: str) -> Image:
    """BMP 파일을 읽는다(24/32비트 비압축). 테스트/오프라인 입력용."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:2] != b"BM":
        raise ValueError("BMP 파일이 아닙니다.")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    width, height, planes, bits = struct.unpack_from("<iiHH", data, 18)
    compression = struct.unpack_from("<I", data, 30)[0]
    if compression != 0:
        raise ValueError("비압축 BMP 만 지원합니다.")
    if bits not in (24, 32):
        raise ValueError(f"{bits}비트 BMP 는 지원하지 않습니다(24/32 만).")
    top_down = height < 0
    height = abs(height)
    bytes_per_pixel = bits // 8
    row_size = ((width * bits + 31) // 32) * 4
    pixels = bytearray(width * height * 4)
    for row in range(height):
        source_row = row if top_down else (height - 1 - row)
        base = pixel_offset + source_row * row_size
        for column in range(width):
            offset = base + column * bytes_per_pixel
            target = (row * width + column) * 4
            pixels[target] = data[offset]
            pixels[target + 1] = data[offset + 1]
            pixels[target + 2] = data[offset + 2]
            pixels[target + 3] = 255
    return Image(width=width, height=height, pixels=pixels)
