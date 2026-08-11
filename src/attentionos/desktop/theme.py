"""Design tokens for the native AttentionOS desktop UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Colors:
    background: str = "#F6F7F9"
    surface: str = "#FFFFFF"
    surface_secondary: str = "#F0F2F5"
    surface_hover: str = "#F8FAFB"
    border: str = "#E2E5E9"
    border_strong: str = "#CED3D9"
    text: str = "#16181D"
    text_secondary: str = "#69707D"
    text_tertiary: str = "#8C939D"
    accent: str = "#2F8F83"
    accent_hover: str = "#287C72"
    accent_soft: str = "#E4F3F0"
    success: str = "#3BA272"
    warning: str = "#D99A32"
    danger: str = "#D95C5C"
    idle: str = "#A8AFB8"
    overlay: str = "#E9ECEF"


LIGHT_COLORS = Colors()
DARK_COLORS = Colors(
    background="#111317",
    surface="#1A1D23",
    surface_secondary="#242832",
    surface_hover="#20242C",
    border="#2E3440",
    border_strong="#3A4250",
    text="#F2F4F7",
    text_secondary="#A8B0BD",
    text_tertiary="#788292",
    accent="#40B3A6",
    accent_hover="#36A196",
    accent_soft="#173B38",
    success="#4AB889",
    warning="#E0A84A",
    danger="#E06B6B",
    idle="#6E7785",
    overlay="#2A303A",
)


@dataclass(frozen=True)
class Spacing:
    xxs: int = 4
    xs: int = 8
    sm: int = 12
    md: int = 16
    lg: int = 24
    xl: int = 32


@dataclass(frozen=True)
class Radius:
    sm: int = 8
    md: int = 12
    lg: int = 14


@dataclass(frozen=True)
class Typography:
    family: str = "Segoe UI Variable"
    fallback: str = "Segoe UI"
    display: tuple[str, int, str] = ("Segoe UI Variable", 38, "bold")
    page_title: tuple[str, int, str] = ("Segoe UI Variable", 28, "bold")
    section: tuple[str, int, str] = ("Segoe UI Variable", 16, "bold")
    metric: tuple[str, int, str] = ("Segoe UI Variable", 26, "bold")
    body: tuple[str, int] = ("Segoe UI Variable", 13)
    body_semibold: tuple[str, int, str] = ("Segoe UI Variable", 13, "bold")
    caption: tuple[str, int] = ("Segoe UI Variable", 11)
    caption_semibold: tuple[str, int, str] = ("Segoe UI Variable", 11, "bold")


COLORS = Colors()
SPACING = Spacing()
RADIUS = Radius()
TYPOGRAPHY = Typography()

APP_COLORS = [
    "#2F8F83",
    "#6B7C93",
    "#8A6FAD",
    "#C8845A",
    "#5D8AA8",
    "#A87575",
    "#7B8A5B",
    "#9B7B52",
]


def apply_color_theme(theme: str) -> None:
    """Mutate shared color tokens so existing imports see the selected palette."""
    source = DARK_COLORS if theme == "dark" else LIGHT_COLORS
    for key, value in source.__dict__.items():
        setattr(COLORS, key, value)
